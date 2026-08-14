import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import MaxNLocator
from scipy import ndimage
import changSNR as ch
from file_naming import iter_feature_files, sequence_type_from_name

from sklearn.covariance import EllipticEnvelope
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM


MODEL_COLUMNS = ["One_class_SVM", "EllipticEnvelope", "IsolationForest", "LocalOutlierFactor"]
LOW_OUTLIER_METRICS = {"SNR Chang", "tSNR (Averaged Brain ROI)", "SNR Normal"}
HIGH_OUTLIER_METRICS = {"Displacement factor (std of Mutual information)"}
QC_METRIC_COLUMNS = LOW_OUTLIER_METRICS | HIGH_OUTLIER_METRICS


# =========================
# Compatibility stubs (keep ParsingData.py happy)
# =========================
def tic():
    """No-op timer stub for compatibility."""
    pass


def toc(*_, **__):
    """No-op timer stub for compatibility."""
    pass


# =========================
# Vectorized mutual information
# =========================
def mutualInfo(Im1: np.ndarray, Im2: np.ndarray, bins: int = 20) -> float:
    """
    Compute mutual information (in nats) between two images using a vectorized 2D histogram.
    """
    x = np.asarray(Im1, dtype=float).ravel()
    y = np.asarray(Im2, dtype=float).ravel()
    if x.size != y.size:
        raise ValueError("Mutual information inputs must have the same size")

    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if x.size == 0:
        return 0.0

    x_min, x_max = np.min(x), np.max(x)
    y_min, y_max = np.min(y), np.max(y)
    if x_min == x_max:
        x_max = x_min + 1.0
    if y_min == y_max:
        y_max = y_min + 1.0

    x_idx = np.floor((x - x_min) * (bins / (x_max - x_min))).astype(np.int64)
    y_idx = np.floor((y - y_min) * (bins / (y_max - y_min))).astype(np.int64)
    x_idx = np.clip(x_idx, 0, bins - 1)
    y_idx = np.clip(y_idx, 0, bins - 1)

    joint_idx = x_idx * bins + y_idx
    h2d = np.bincount(joint_idx, minlength=bins * bins).reshape(bins, bins)

    pxy = h2d.astype(np.float64)
    s = pxy.sum()
    if s == 0:
        return 0.0
    pxy /= s

    px = pxy.sum(axis=1, keepdims=True)
    py = pxy.sum(axis=0, keepdims=True)
    pxpy = px @ py  # outer product

    nz = pxy > 0
    return float(np.sum(pxy[nz] * (np.log(pxy[nz]) - np.log(pxpy[nz]))))


def otsu_threshold(x: np.ndarray, bins: int = 256) -> float:
    """
    Otsu threshold using finite data only; sqrt(N) bins (capped) for stability.
    """
    v = x[np.isfinite(x)]
    if v.size == 0:
        return np.nan
    nb = int(min(bins, max(32, np.sqrt(v.size))))
    hist, edges = np.histogram(v, bins=nb)
    p = hist.astype(np.float64)
    s = p.sum()
    if s == 0:
        return np.nan
    p /= s
    omega = np.cumsum(p)
    centers = (edges[:-1] + edges[1:]) * 0.5
    mu = np.cumsum(p * centers)
    mu_t = mu[-1]
    denom = omega * (1.0 - omega) + 1e-12
    sigma_b2 = (mu_t * omega - mu) ** 2 / denom
    k = int(np.nanargmax(sigma_b2))
    return float(centers[k])


# =========================
# Nyquist ghost detection (GSR + Otsu)
# =========================
def GhostCheck(input_file, pe_axis: int = 0) -> float:
    """
    Detect Nyquist ghosting via background-corrected Ghost-to-Signal Ratio using rolled masks.

    GSR = (Mean_ghost - Mean_background) / Median_signal
    """
    # --- Load & reduce ---
    img = input_file.get_fdata()
    if img.ndim < 2 or pe_axis not in (0, 1):
        return float("nan")
    while img.ndim > 3:
        img = img.mean(axis=-1)
    if img.ndim == 2:
        img = img[:, :, np.newaxis]
    _, _, Z = img.shape
    sl = img[:, :, Z // 2]

    # --- Object mask via Otsu (largest component) ---
    thr = otsu_threshold(sl)
    if not np.isfinite(thr):
        return float("nan")
    mask = sl > thr*0.85
    lbl, nlab = ndimage.label(mask)
    if nlab == 0:
        return float("nan")
    sizes = ndimage.sum(mask, lbl, index=np.arange(1, nlab + 1))
    keep = 1 + int(np.argmax(sizes))
    mask = (lbl == keep)

    # Roll data of mask through the appropriate axis
    n2_mask = np.roll(mask, mask.shape[pe_axis] // 2, axis=pe_axis)

    # Step 3: remove from n2_mask pixels inside the brain
    n2_mask = n2_mask * (1 - mask)

    # Step 4: non-ghost background region is labeled as 2
    n2_mask = n2_mask + 2 * (1 - n2_mask - mask)

    # Step 5: signal is the entire foreground image
    ghost_values = sl[n2_mask == 1]
    background_values = sl[n2_mask == 2]
    signal_values = sl[n2_mask == 0]
    if not ghost_values.size or not background_values.size or not signal_values.size:
        return float("nan")

    ghost = np.mean(ghost_values) - np.mean(background_values)
    signal = np.median(signal_values)
    if not np.isfinite(ghost) or not np.isfinite(signal) or signal == 0:
        return float("nan")
    return float(ghost / signal)

# =========================
# Resolution
# =========================
def ResCalculator(input_file):
    """Return voxel size (pixdim[1:4])."""
    return input_file.header["pixdim"][1:4]


def _safe_db_ratio(signal: float, noise: float) -> float:
    """Return 20*log10(signal/noise), or NaN for invalid measurements."""
    if not np.isfinite(signal) or not np.isfinite(noise) or signal <= 0 or noise <= 0:
        return float("nan")
    value = 20 * np.log10(signal / noise)
    return float(value) if np.isfinite(value) else float("nan")


def load_feature_tables(path: str):
    """Load one calculated-feature table per sequence type."""
    tables = []
    seen = set()

    for file_path in iter_feature_files(path):
        seq_type = sequence_type_from_name(file_path.name)
        if not seq_type or seq_type in seen:
            continue

        tables.append((pd.read_csv(file_path), seq_type))
        seen.add(seq_type)

    return tables


def iqr_outlier_index(series: pd.Series, high_is_bad: bool) -> pd.Series:
    """Return rows outside the 1.5*IQR bound for one metric."""
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    finite_values = values.dropna()
    if finite_values.size < 2:
        return pd.Series(False, index=series.index)

    q75, q25 = np.percentile(finite_values, [75, 25])
    iqr = q75 - q25
    if not np.isfinite(iqr) or iqr <= 0:
        return pd.Series(False, index=series.index)

    if high_is_bad:
        return values > (q75 + 1.5 * iqr)
    return values < (q25 - 1.5 * iqr)


# =========================
# SNR (Chang)
# =========================
def snr_calculator_chang(input_file) -> float:
    """Compute SNR using Chang’s estimator on central slices / directions."""
    image = np.squeeze(np.asanyarray(input_file.dataobj).astype("float64"))

    if image.ndim < 3 or not np.isfinite(image).any() or np.nanmean(image) == 0:
        return np.nan

    ns = image.shape[2]
    n_dir = image.shape[-1] if image.ndim > 3 else 0
    direction_start = 0 if n_dir < 10 else 5

    if ns > 4:
        sl_lo = int(np.floor(ns / 2) - 2)
        sl_hi = int(np.floor(ns / 2) + 2)
    else:
        sl_lo, sl_hi = 0, ns

    values = []
    if image.ndim == 3:
        for sl in range(sl_lo, sl_hi):
            slc = image[:, :, sl]
            try:
                _, est_std, _ = ch.calcSNR(slc, 0, 1)
            except ValueError:
                est_std = np.nan
            values.append(_safe_db_ratio(np.nanmean(slc), est_std))
    else:
        for sl in range(sl_lo, sl_hi):
            for bb in range(direction_start, max(direction_start, n_dir - 1)):
                slc = image[:, :, sl, bb]
                try:
                    _, est_std, _ = ch.calcSNR(slc, 0, 1)
                except ValueError:
                    est_std = np.nan
                values.append(_safe_db_ratio(np.nanmean(slc), est_std))

    values = np.asarray(values)
    finite = np.isfinite(values)
    return float(np.mean(values[finite])) if finite.any() else float("nan")


# =========================
# SNR (Normal)
# =========================
def sphere(shape, radius: int, position) -> np.ndarray:
    """Generate an n-D spherical (ellipsoidal) mask with guards."""
    if radius is None or radius <= 0:
        return np.zeros(shape, dtype=bool)
    assert len(position) == len(shape)
    semisizes = (float(radius),) * len(shape)
    grid = [slice(-x0, dim - x0) for x0, dim in zip(position, shape)]
    axes = np.ogrid[grid]
    arr = np.zeros(shape, dtype=float)
    for ax, semi in zip(axes, semisizes):
        arr += (ax / semi) ** 2
    return arr <= 1.0


def snr_calculator_normal(input_file) -> float:
    """Compute conventional SNR using central spherical ROI and corner noise."""
    image = np.squeeze(np.asanyarray(input_file.dataobj).astype("float64"))
    if image.ndim == 2:
        image = np.repeat(image[:, :, np.newaxis], 10, axis=2)
    elif image.ndim == 4:
        image = image[:, :, :, 0]
    if image.ndim != 3:
        return float("nan")

    shape = image.shape

    # Spherical mask around center-of-mass
    center = ndimage.center_of_mass(image)
    if not np.all(np.isfinite(center)):
        return float("nan")
    center = [int(i) for i in center]
    radius = min(int(np.floor(0.10 * np.mean(shape))), shape[2])
    mask = sphere(shape, radius, center)
    if not np.any(mask):
        return float("nan")
    signal_value = float(image[mask].mean())

    # 8-corner noise regions (vectorized)
    x = int(np.ceil(shape[0] * 0.15))
    y = int(np.ceil(shape[1] * 0.15))
    z = int(np.ceil(shape[2] * 0.15))
    if x == 0 or y == 0 or z == 0:
        return float("nan")

    blocks = (
        image[:x, :y, :z], image[:x, -y:, :z], image[-x:, :y, :z], image[-x:, -y:, :z],
        image[:x, :y, -z:], image[:x, -y:, -z:], image[-x:, :y, -z:], image[-x:, -y:, -z:]
    )
    noise_std = float(np.std(np.concatenate([b.ravel() for b in blocks])))
    return _safe_db_ratio(signal_value, noise_std)


# =========================
# tSNR
# =========================
def tsnr_calculator(input_file) -> float:
    """Compute temporal SNR (tSNR) with initial burn-in (10 volumes if available)."""
    image = np.asanyarray(input_file.dataobj)
    if image.ndim == 3:
        image = image.reshape(image.shape[0], image.shape[1], 1, image.shape[2])
    if image.ndim != 4 or image.shape[-1] == 0:
        return float("nan")

    image = image.astype("float64")
    burn_in = 10 if image.shape[-1] > 10 else 0
    signal = image[:, :, :, burn_in:]
    with np.errstate(divide="ignore", invalid="ignore"):
        tsnr_map = 20 * np.log10(signal.mean(axis=-1) / signal.std(axis=-1))

    image_average = image.mean(axis=-1)
    center = ndimage.center_of_mass(image_average)
    if not np.all(np.isfinite(center)):
        return float("nan")
    center = [int(i) for i in center]
    radius = int(np.floor(0.10 * np.mean(image.shape[:2])))
    mask = sphere(image.shape[:3], radius, center)
    values = tsnr_map[mask]
    values = values[np.isfinite(values)]
    if not values.size:
        return float("nan")
    return float(np.mean(values))


# Legacy names kept for downstream scripts and older notebooks.
snrCalclualtor_chang = snr_calculator_chang
snrCalclualtor_normal = snr_calculator_normal
TsnrCalclualtor = tsnr_calculator


# =========================
# Motion (rsfMRI)
# =========================
def Ismotion(input_file):
    """
    Basic motion metric using mutual information change across time
    on the brightest slice (by mean intensity).
    """
    image = np.asanyarray(input_file.dataobj)
    if image.ndim == 3:
        image = image.reshape(image.shape[0], image.shape[1], 1, image.shape[2])
    if image.ndim != 4:
        return np.asarray([]), str([0, 0]), 0.0, 0.0

    image = image.astype("float64")
    burn_in = 10 if image.shape[-1] > 10 else 0
    sig = image[:, :, :, burn_in:]
    if sig.shape[-1] < 2:
        return np.asarray([]), str([0, 0]), 0.0, 0.0

    # Choose slice with highest mean intensity across time
    temp_mean = sig.mean(axis=(0, 1, 3))
    k = int(np.argmax(temp_mean))
    stack = sig[:, :, k, :]  # (H, W, T)
    ref = stack[:, :, 0]

    mi_vals = [mutualInfo(ref, stack[:, :, t]) for t in range(1, stack.shape[-1])]
    final = np.asarray(mi_vals)
    if final.size == 0:
        return final, str([0, 0]), 0.0, 0.0

    max_mov_between = str([final.argmin() + 10, final.argmax() + 10])
    gmv = float(final.max() - final.min())
    lmv = float(final.std())
    return final, max_mov_between, gmv, lmv


# =========================
# QC plotting & pies
# =========================
def QCPlot(Path: str) -> None:
    """Generate QC histograms and spatial resolution pie charts from feature CSVs."""
    qc_fig_path = os.path.join(Path, "QCfigures")
    if not os.path.isdir(qc_fig_path):
        os.mkdir(qc_fig_path)

    feature_tables = load_feature_tables(Path)
    if not feature_tables:
        return

    title_font = {"family": "serif", "fontname": "DejaVu Sans"}
    label_font = {"family": "serif", "fontname": "DejaVu Sans"}

    hh = 1
    for df, N in feature_tables:
        for C in (column for column in df.columns if column in QC_METRIC_COLUMNS):
            data = pd.to_numeric(df[C], errors="coerce").to_numpy()
            data = data[np.isfinite(data)]
            n = data.size
            if n < 2:
                continue

            q75, q25 = np.percentile(data, [75, 25])
            iqr = q75 - q25
            rng = float(data.max() - data.min())

            if rng <= 0 or iqr <= 0:
                B = 1
            else:
                h = 2 * iqr / (n ** (1 / 3))
                B = 1 if (not np.isfinite(h) or h <= 0) else int(np.ceil(rng / h))

            nbins = max(1, B * 7)
            XX = min(22, max(1, B) * 5)

            plt.figure(hh, figsize=(9, 5), dpi=300)
            ax2 = plt.subplot(1, 1, 1, label="hist")
            y, _, bars = plt.hist(data, bins=nbins, histtype="bar", edgecolor="white")

            plt.xlabel(f"{N}: {C} [a.u.]", fontdict=label_font)
            plt.ylabel("Frequency", fontdict=label_font)
            ax2.spines["right"].set_visible(False)
            ax2.spines["top"].set_visible(False)
            plt.locator_params(axis="x", nbins=XX)
            ax2.yaxis.set_major_locator(MaxNLocator(integer=True))

            if iqr > 0:
                if C == "Displacement factor (std of Mutual information)":
                    limit = q75 + 1.5 * iqr
                    label = "Q3 + 1.5*IQ"
                    is_outlier = lambda bar: bar.get_x() > limit
                else:
                    limit = q25 - 1.5 * iqr
                    label = "Q1 - 1.5*IQ"
                    is_outlier = lambda bar: bar.get_x() < limit

                if len(y):
                    plt.text(limit, 2 * max(y) / 3, label, color="grey", fontdict=label_font)
                for bar in bars:
                    if is_outlier(bar):
                        bar.set_facecolor("red")
                plt.axvline(limit, color="grey", linestyle="--")

            plt.suptitle(f"{N}: {C}", fontdict=title_font)
            legend = plt.legend(
                handles=[mpatches.Patch(color="tab:blue", label="Keep"),
                         mpatches.Patch(color="red", label="Discard")],
                fontsize=8,
            )
            for text in legend.get_texts():
                text.set_fontfamily("serif")
                text.set_fontsize(8)

            ax2.xaxis.set_tick_params(labelsize=8)
            ax2.yaxis.set_tick_params(labelsize=8)

            out = os.path.join(qc_fig_path, f"{C}{N}.png")
            plt.savefig(out, dpi=300)
            plt.close()

        hh += 1

    # Spatial resolution pies
    plt.figure(hh, figsize=(9, 5), dpi=300)
    rr = 1
    for df, N in feature_tables:
        for C in (column for column in df.columns if column in {"SpatRx", "SpatRy", "SpatRz"}):
            vals = pd.to_numeric(df[C], errors="coerce").to_numpy()
            vals = vals[np.isfinite(vals)]
            if vals.size == 0:
                continue
            labels, counts = np.unique(vals, return_counts=True)
            labels2 = [f"{l:.3f} mm" for l in labels]

            ax1 = plt.subplot(len(feature_tables), 3, rr)
            ax1.pie(counts, labels=labels2, autopct="%1.0f%%", startangle=180)
            ax1.axis("equal")
            ax1.set_title(f"{N}:{C}", fontdict=title_font)
            plt.suptitle("Resolution homogeneity between data", weight="bold")
            ax1.xaxis.set_tick_params(labelsize=8)
            ax1.yaxis.set_tick_params(labelsize=8)
            rr += 1

    out = os.path.join(qc_fig_path, "Spatial_Resolution.png")
    plt.savefig(out, dpi=300)
    plt.close()


# =========================
# ML voting
# =========================
def _predict_or_inliers(model, features: pd.DataFrame) -> np.ndarray:
    """Fit one detector, falling back to inliers for unsuitable small datasets."""
    predictions = np.ones(len(features), dtype=int)
    if len(features) < 2:
        return predictions

    try:
        return model.fit_predict(features)
    except (ValueError, RuntimeError, np.linalg.LinAlgError):
        return predictions


def ML(Path: str, format_type: str):
    """
    Run multiple outlier detectors and return per-row predictions for each *_features_*.csv.
    Returns list[pd.DataFrame].
    """
    results = []
    seen = set()
    for csv_path in iter_feature_files(Path):
        seq_type = sequence_type_from_name(csv_path.name)
        if not seq_type or seq_type in seen:
            continue
        seen.add(seq_type)

        A = pd.read_csv(csv_path).dropna(how="all", axis="columns")

        # Build feature matrix from metric columns only.
        feature_start = A.columns.get_loc("Ghosting") + 1 if "Ghosting" in A.columns else 1
        X = A.iloc[:, feature_start:].copy()

        # Coerce to numeric, drop inf/NaN rows and all-NaN cols
        X = X.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        X = X.dropna(how="all", axis="columns").dropna(how="any", axis="index")

        idx = X.index
        if len(idx) == 0:
            continue

        address = A.loc[idx, "FileAddress"].tolist()
        sequence_name = A.loc[idx, "sequence name"].tolist() if "sequence name" in A else None
        img_name = A.loc[idx, "corresponding_img"].tolist() if "corresponding_img" in A else None

        # Drop zero-variance columns
        if hasattr(X, "var"):
            X = X.loc[:, X.var(axis=0, ddof=0) > 0]

        n_samples, n_features = X.shape

        # If no usable feature columns remain, default to all inliers
        if n_features == 0:
            df = pd.DataFrame({
                column: np.ones(n_samples, dtype=int)
                for column in MODEL_COLUMNS
            })
            df["sequence_type"] = seq_type
            df["Paths"] = address
            if sequence_name is not None:
                df["sequence_name"] = sequence_name
            if img_name is not None:
                df["corresponding_img"] = img_name
            results.append(df)
            continue

        # Scale features
        X = pd.DataFrame(StandardScaler().fit_transform(X), index=X.index)

        n_neighbors = max(2, min(20, n_samples - 1))
        models = (
            OneClassSVM(gamma="auto", kernel="poly", nu=0.05, shrinking=False),
            EllipticEnvelope(contamination=0.025, random_state=1),
            IsolationForest(
                n_estimators=100, max_samples="auto", contamination=0.05,
                max_features=1.0, bootstrap=False, n_jobs=-1, random_state=1
            ),
            LocalOutlierFactor(
                n_neighbors=n_neighbors, algorithm="auto", metric="minkowski",
                contamination=0.04, novelty=False, n_jobs=-1
            ),
        )
        predictions = [_predict_or_inliers(model, X) for model in models]

        df = pd.DataFrame(
            np.vstack(predictions).T,
            columns=MODEL_COLUMNS,
        )

        # Metadata
        df["sequence_type"] = seq_type
        df["Paths"] = address
        if sequence_name is not None:
            df["sequence_name"] = sequence_name
        if img_name is not None:
            df["corresponding_img"] = img_name

        results.append(df)

    return results


# =========================
# QC table generation
# =========================
def QCtable(Path: str, format_type: str) -> None:
    """Aggregate statistical outliers and ML detections into votings.csv."""
    algs = ML(Path, format_type)
    if not algs:
        return
    algs = pd.concat(algs, ignore_index=True)

    # convert -1 flags to boolean outlier flags
    cols_out = MODEL_COLUMNS
    algs[cols_out] = algs[cols_out] == -1

    paths = set()

    for df, _seq_type in load_feature_tables(Path):
        for column in LOW_OUTLIER_METRICS.intersection(df.columns):
            paths.update(df.loc[iqr_outlier_index(df[column], high_is_bad=False), "FileAddress"])
        for column in HIGH_OUTLIER_METRICS.intersection(df.columns):
            paths.update(df.loc[iqr_outlier_index(df[column], high_is_bad=True), "FileAddress"])

    # mark statistical outliers in ML voting
    algs["statistical_method"] = algs["Paths"].isin(paths)
    vote_cols = MODEL_COLUMNS + ["statistical_method"]
    algs["Voting outliers (from 5)"] = algs[vote_cols].sum(axis=1)
    algs = algs[algs["Voting outliers (from 5)"] >= 1]

    metadata_cols = ["Paths", "corresponding_img", "sequence_type"]
    if format_type == "raw":
        metadata_cols.insert(1, "sequence_name")
    keep_cols = [column for column in metadata_cols + vote_cols if column in algs]
    algs = algs[keep_cols]

    final_result = os.path.join(Path, "votings.csv")
    algs.to_csv(final_result, index=False)
