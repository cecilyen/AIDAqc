<img align="right" src="https://github.com/Aswendt-Lab/AIDAqc/blob/main/docs/AIDA_Logo_wide.001.png" width="500">
<h1>AIDA<i>qc</i></h1>

*An automated and simple tool for fast quality analysis of animal MRI*
<br/>
<br/>
<h3>Features</h3> 

- **Input:** Bruker raw data or NIfTI (T2-weighted MRI, diffusion-weighted MRI, or DTI, and rs-fMRI)
- **Calculations:** SNR, tSNR, movement variability, data quality categorization (finds bad quality outliers)
- **Output Format:** CSV sheets, PDFs, & images

<h3>Changes in this fork</h3>

This branch is based on the original [Aswendt-Lab/AIDAqc](https://github.com/Aswendt-Lab/AIDAqc) project and keeps the same main entry point, `scripts/ParsingData.py`, and the same high-level workflow: discover scans, classify sequences, calculate QC features, and generate summary outputs.

Compared with the original upstream repository, this fork changes the implementation in these areas:

- **Simpler pipeline code:** feature extraction now builds one output row per scan directly instead of maintaining parallel accumulator lists.
- **Centralized output naming:** generated address and feature CSV filename conventions are shared in `scripts/file_naming.py`.
- **Backward-compatible file reads:** legacy misspelled outputs such as `data_addreses` and `caculated_features` are still recognized, while new files use `data_addresses` and `calculated_features`.
- **QC robustness:** QC table generation uses explicit model columns, an explicit 1.5*IQR outlier rule, numeric guards for empty or degenerate images, and a corrected output path column named `Paths`.
- **Performance and reproducibility:** mutual-information calculations and SNR code are more vectorized, and the Chang SNR sampling path is deterministic for repeatable runs.
- **Python 3 cleanup:** old wildcard imports, brittle type-string checks, and Python 2-era dictionary-to-XML logic were simplified while preserving existing public helper names.
- **Container and docs cleanup:** the Dockerfile now uses a single Conda-based stage, fixes the Conda environment path, and the README Docker commands use valid build and volume syntax.
- **Dependency list cleanup:** `requirements.txt` removes unused/commented entries from the original list and adds the local `dict2xml` dependency used by Bruker metadata parsing.
- **Follow-up cleanup:** the feature path now shares sequence-specific metric logic, address CSVs use an explicit `FileAddress` column, raw/NIfTI I/O uses safer `Path` handling, SNR/KDE helpers bound their working set, and Bruker diffusion tables are written with consistent rows and columns.
- **OneDrive compatibility:** the complete checkout can be audited for Microsoft's public sync restrictions with `scripts/check_onedrive_compatibility.py`; operational limits and NIH tenant-policy boundaries are documented in [docs/ONEDRIVE.md](docs/ONEDRIVE.md).

Validation performed for this fork has covered Python 3.6 grammar/compile checks, lightweight XML helper smoke tests, and a complete OneDrive compatibility audit. Full MRI dataset validation and container image builds have not yet been rerun; the isolated validation runtime also does not include the scientific dependencies required for the full pipeline.

<img align="left" src="https://github.com/Aswendt-Lab/AIDAqc/blob/main/docs/AIDAqc_workflow.png">

<br/>
<br/>

[**See the poster for all details**](https://github.com/Aswendt-Lab/AIDAqc/blob/main/docs/AIDAqc_Poster_Summary.pdf) 

<h3>Installation</h3> 
Download the repository, install Python 3.6 with Conda, then import the AIDAqc Conda environment from `aidaqc.yaml`.

Main function: *ParsingData*

See the full manual [here](https://github.com/Aswendt-Lab/AIDAqc/blob/main/docs/AIDAqc_v2_1.pdf).

For work/school OneDrive checkouts, run the compatibility audit before and after
large file changes:

```powershell
uv run python -OO scripts/check_onedrive_compatibility.py .
```

See [docs/ONEDRIVE.md](docs/ONEDRIVE.md) for the checked limits, migration
location, and the boundary between public Microsoft restrictions and
tenant-specific NIH controls.

<h3>Docker/Apptainer Usage</h3>

```bash
# Build

docker build -t aidaqc:2.1 .

# Running the main ParsingData.py:

docker run --rm -v /your/project/data:/data -v /your/project/qc:/qc aidaqc:2.1 -i /data -o /qc -f raw

```

For installation in a [apptainer](https://apptainer.org/) container for GNU/Linux:
```bash
# Download the repository
git clone https://github.com/Aswendt-Lab/AIDAqc.git
cd AIDAqc

# Create a new apptainer container
apptainer build aidaqc.sif apptainer.def

# Get into a bash shell in the container
apptainer shell aidaqc.sif

```
<h3>Branches</h3>

AIDAqc is organized into multiple branches to support development:

- **`main`** – the stable branch containing officially released and validated versions of AIDAqc.  
- **`open-dev`** – the public development branch that can be used by external contributors to implement code modifications, enhancements, or bug fixes.  
  *Researchers and developers are welcome to fork the repository, work within the `open-dev` branch, and submit pull requests for review.*   

<h3>Tutorial</h3>

To guide you through running the pipeline, please watch the [YouTube tutorial](https://youtu.be/SP4sWW313DQ?si=4WaTI544FzAkBVbY).

<h3>The story behind this tool</h3> 

It can be challenging to acquire MR images of consistent quality or to decide between good vs. bad quality data in large databases. Manual screening without quantitative criteria is strictly user-dependent and for large databases is neither practical nor in the spirit of good scientific practice. In contrast to clinical MRI, in animal MRI, there is no consensus on the standardization of quality control measures or categorization of good vs. bad quality images. As we were forced to screen hundreds of scans for a recent project, we decided to automate this process as part of our Atlas-based Processing Pipeline (AIDA).

<h3>Validation and Datasets</h3> 

This tool has been validated and used in the following publication: [Publication Link](https://gin.g-node.org/Aswendt_Lab/2023_Kalantari_AIDAqc)

A total of 23 datasets from various institutes were used for validation and testing. These datasets can be found via: [Datasets Link](https://gin.g-node.org/Aswendt_Lab/2023_Kalantari_AIDAqc)

<h3>Download test dataset</h3>

[Dataset Link](https://gin.g-node.org/Aswendt_Lab/testdata_aida)

<h3><b>CONTACT</h3></b>
 
If you encounter problems, report directly in [![Gitter](https://badges.gitter.im/AIDA_tools/community.svg)](https://gitter.im/AIDA_tools/community?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge)
or 
join our Open Office Hour - each Thursday 3:00 pm (UTC+2) [![Zoom](https://img.shields.io/badge/Zoom-2D8CFF?style=for-the-badge&logo=zoom&logoColor=white)](https://uni-frankfurt.zoom-x.de/j/63112745009?pwd=JBTjMVbuaTw9cZvFnppTwCPjGdQEyx.1)


For all other inquiries: Markus Aswendt (aswendtATmed.uni-frankfurt.de)

<h3><b>LICENSE</h3></b>

[GNU General Public License v3.0](https://github.com/aswendtlab/AIDAqc/blob/main/LICENSE)
