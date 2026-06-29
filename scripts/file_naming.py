"""Shared filename conventions for AIDAqc generated CSV files."""

from pathlib import Path
from typing import Iterable, List, Optional, Set, Union


SEQUENCE_TYPES = ("anat", "diff", "func")

ADDRESS_FILE_TEMPLATE = "{format_type}_data_addresses_{seq_type}.csv"
FEATURE_FILE_TEMPLATE = "calculated_features_{seq_type}.csv"

ADDRESS_FILE_PATTERNS = ("*data_addresses*.csv", "*data_addreses*.csv")
FEATURE_FILE_PATTERNS = ("*calculated_features*.csv", "*caculated_features*.csv")


PathLike = Union[str, Path]


def iter_matching_files(path: PathLike, patterns: Iterable[str]) -> List[Path]:
    """Return unique files matching any pattern, preserving pattern order."""
    base_path = Path(path)
    seen: Set[Path] = set()
    files: List[Path] = []

    for pattern in patterns:
        for file_path in sorted(base_path.glob(pattern)):
            resolved = file_path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(file_path)

    return files


def iter_address_files(path: PathLike) -> List[Path]:
    """Return current and legacy address CSV files."""
    return iter_matching_files(path, ADDRESS_FILE_PATTERNS)


def iter_feature_files(path: PathLike) -> List[Path]:
    """Return current and legacy calculated-feature CSV files."""
    return iter_matching_files(path, FEATURE_FILE_PATTERNS)


def sequence_type_from_name(name: str) -> Optional[str]:
    """Infer the AIDAqc sequence type encoded in a generated filename."""
    lowered = name.lower()
    return next((seq_type for seq_type in SEQUENCE_TYPES if seq_type in lowered), None)
