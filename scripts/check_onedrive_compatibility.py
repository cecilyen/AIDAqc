#!/usr/bin/env python3
"""Audit a directory against public OneDrive sync restrictions."""

from __future__ import print_function

import argparse
import os
import sys
from urllib.parse import quote


INVALID_CHARACTERS = set('"*:<>?/\\|')
RESERVED_NAMES = {".LOCK", "DESKTOP.INI"}
WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    "COM{0}".format(number) for number in range(10)
} | {
    "LPT{0}".format(number) for number in range(10)
}
MAX_SEGMENT_LENGTH = 255
MAX_CLOUD_PATH_LENGTH = 400
MAX_LOCAL_SYNC_PATH_LENGTH = 520
MAX_DESKTOP_PATH_LENGTH = 260
MAX_FILE_SIZE = 250 * 1000 ** 3
RECOMMENDED_ITEM_LIMIT = 300000


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Check file names, paths, links, sizes, and item count for OneDrive."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="directory to audit (default: current directory)",
    )
    parser.add_argument(
        "--onedrive-root",
        help="OneDrive sync root; normally detected from the path or environment",
    )
    return parser.parse_args()


def normalized_path(path):
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))


def is_within(path, parent):
    try:
        return os.path.normcase(os.path.commonpath([path, parent])) == os.path.normcase(parent)
    except ValueError:
        return False


def detect_onedrive_root(root):
    for variable in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        candidate = os.environ.get(variable)
        if candidate:
            candidate = normalized_path(candidate)
            if is_within(root, candidate):
                return candidate

    candidate = root
    while True:
        if os.path.basename(candidate).lower().startswith("onedrive"):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            return None
        candidate = parent


def relative_path(path, root):
    relative = os.path.relpath(path, root)
    return "." if relative == "." else relative


def human_size(size):
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return "{0:.1f} {1}".format(value, unit)
        value /= 1024.0


def is_link_or_junction(path):
    if os.path.islink(path):
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(path))


def audit(root, onedrive_root):
    violations = []
    warnings = []
    seen_casefolded_paths = {}
    metrics = {
        "directories": 0,
        "files": 0,
        "max_cloud_path": (0, "."),
        "max_full_path": (len(root), "."),
        "max_segment": (len(os.path.basename(root)), "."),
        "largest_file": (0, "."),
    }

    def add_violation(path, message):
        violations.append((relative_path(path, root), message))

    def add_warning(path, message):
        warnings.append((relative_path(path, root), message))

    def check_item(path, is_directory):
        name = os.path.basename(path)
        name_upper = name.upper()
        relative = relative_path(path, root)

        if any(character in INVALID_CHARACTERS for character in name):
            add_violation(path, "name contains a character that OneDrive does not allow")
        if name != name.strip(" "):
            add_violation(path, "name has a leading or trailing space")
        if len(name) > MAX_SEGMENT_LENGTH:
            add_violation(path, "name exceeds the 255-character segment limit")

        device_stem = name_upper.split(".", 1)[0]
        if name_upper in RESERVED_NAMES or device_stem in WINDOWS_DEVICE_NAMES:
            add_violation(path, "name is reserved by OneDrive or Windows")
        if "_VTI_" in name_upper:
            add_violation(path, "name contains the reserved text _vti_")
        if name.startswith("~$"):
            add_violation(path, "name starts with the reserved Office prefix ~$")
        if not is_directory and name.lower().endswith(".tmp"):
            add_violation(path, "temporary .tmp files are not synchronized by OneDrive")
        if not is_directory and name.lower() == ".ds_store":
            add_violation(path, ".DS_Store is not synchronized by OneDrive")
        if is_directory and name.startswith(("\u309b", "\u1027")):
            add_violation(path, "folder starts with a character that OneDrive does not allow")
        if (
            onedrive_root
            and os.path.dirname(path) == onedrive_root
            and name.lower() == "forms"
        ):
            add_violation(path, "forms is not allowed at the root of a OneDrive library")

        if "#" in name or "%" in name:
            add_warning(path, "# and % support depends on the organization's tenant setting")
        if is_directory and ";" in name:
            add_warning(path, "Office desktop apps cannot save through a folder containing ;")
        if is_link_or_junction(path):
            add_violation(path, "OneDrive does not support symbolic links or junctions")

        full_length = len(path)
        if full_length > metrics["max_full_path"][0]:
            metrics["max_full_path"] = (full_length, relative)
        if full_length > MAX_LOCAL_SYNC_PATH_LENGTH:
            add_violation(path, "local path exceeds the 520-character OneDrive sync limit")
        elif full_length > MAX_DESKTOP_PATH_LENGTH:
            add_warning(path, "local path exceeds the 260-character File Explorer/Office limit")

        if len(name) > metrics["max_segment"][0]:
            metrics["max_segment"] = (len(name), relative)

        if onedrive_root:
            cloud_path = os.path.relpath(path, onedrive_root).replace(os.sep, "/")
            cloud_length = len(quote(cloud_path, safe="/"))
            if cloud_length > metrics["max_cloud_path"][0]:
                metrics["max_cloud_path"] = (cloud_length, relative)
            if cloud_length > MAX_CLOUD_PATH_LENGTH:
                add_violation(path, "cloud path exceeds the 400-character OneDrive limit")

        casefolded = relative.replace("\\", "/").casefold()
        existing = seen_casefolded_paths.get(casefolded)
        if existing is not None and existing != relative:
            add_violation(path, "path differs from {0} only by letter case".format(existing))
        else:
            seen_casefolded_paths[casefolded] = relative

        if not is_directory:
            try:
                size = os.path.getsize(path)
            except OSError as error:
                add_violation(path, "file size could not be read: {0}".format(error))
            else:
                if size > metrics["largest_file"][0]:
                    metrics["largest_file"] = (size, relative)
                if size > MAX_FILE_SIZE:
                    add_violation(path, "file exceeds the 250 GB OneDrive limit")

    check_item(root, True)

    def record_walk_error(error):
        path = getattr(error, "filename", root) or root
        add_violation(path, "directory could not be scanned: {0}".format(error))

    for current, directory_names, file_names in os.walk(
        root, topdown=True, onerror=record_walk_error, followlinks=False
    ):
        directory_names.sort(key=str.casefold)
        file_names.sort(key=str.casefold)
        for name in directory_names:
            metrics["directories"] += 1
            check_item(os.path.join(current, name), True)
        for name in file_names:
            metrics["files"] += 1
            check_item(os.path.join(current, name), False)

    item_count = metrics["directories"] + metrics["files"]
    if item_count > RECOMMENDED_ITEM_LIMIT:
        warnings.append(
            (
                ".",
                "tree has {0} items; Microsoft recommends no more than {1}".format(
                    item_count, RECOMMENDED_ITEM_LIMIT
                ),
            )
        )

    return violations, warnings, metrics


def print_report(root, onedrive_root, violations, warnings, metrics):
    print("OneDrive compatibility audit")
    print("Root: {0}".format(root))
    print("OneDrive root: {0}".format(onedrive_root or "not detected"))
    print(
        "Items: {0} files, {1} directories".format(
            metrics["files"], metrics["directories"]
        )
    )
    print(
        "Longest local path: {0} characters ({1})".format(
            metrics["max_full_path"][0], metrics["max_full_path"][1]
        )
    )
    if onedrive_root:
        print(
            "Longest cloud path: {0} encoded characters ({1})".format(
                metrics["max_cloud_path"][0], metrics["max_cloud_path"][1]
            )
        )
    else:
        print("Longest cloud path: not checked; specify --onedrive-root")
    print(
        "Longest name: {0} characters ({1})".format(
            metrics["max_segment"][0], metrics["max_segment"][1]
        )
    )
    print(
        "Largest file: {0} ({1})".format(
            human_size(metrics["largest_file"][0]), metrics["largest_file"][1]
        )
    )

    for path, message in sorted(violations):
        print("ERROR: {0}: {1}".format(path, message))
    for path, message in sorted(warnings):
        print("WARNING: {0}: {1}".format(path, message))

    if violations:
        print("FAIL: {0} blocking issue(s), {1} warning(s)".format(len(violations), len(warnings)))
    else:
        print("PASS: no public OneDrive sync violations; {0} warning(s)".format(len(warnings)))
    print("NOTE: Tenant DLP, retention, sharing, and administrator-blocked file types are not locally testable.")


def main():
    arguments = parse_arguments()
    root = normalized_path(arguments.root)
    if not os.path.isdir(root):
        print("ERROR: audit root is not a directory: {0}".format(root), file=sys.stderr)
        return 2

    if arguments.onedrive_root:
        onedrive_root = normalized_path(arguments.onedrive_root)
        if not os.path.isdir(onedrive_root):
            print(
                "ERROR: OneDrive root is not a directory: {0}".format(onedrive_root),
                file=sys.stderr,
            )
            return 2
        if not is_within(root, onedrive_root):
            print("ERROR: audit root is outside --onedrive-root", file=sys.stderr)
            return 2
    else:
        onedrive_root = detect_onedrive_root(root)

    violations, warnings, metrics = audit(root, onedrive_root)
    print_report(root, onedrive_root, violations, warnings, metrics)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
