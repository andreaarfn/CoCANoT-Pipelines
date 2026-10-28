#!/usr/bin/env python3
"""
Convert configured DICOM inputs to NIfTI using dcm2niix.

Paths come from the shared parent-level pipeline_settings.json through
pipeline_config.py. There are no machine-specific fallback directories.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
IMAGING_PIPELINE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = IMAGING_PIPELINE_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from pipeline_config import (
        PipelineConfigError,
        load_imaging_config,
        validate_imaging_config,
    )
except ImportError as exc:
    raise SystemExit(
        "Could not import the shared pipeline_config.py.\n\n"
        f"Expected it here:\n{PROJECT_ROOT / 'pipeline_config.py'}"
    ) from exc

DICOM_EXTENSIONS = {".dcm", ".ima", ""}


def resolve_dcm2niix() -> str:
    """Locate dcm2niix in PATH or the bundled Windows Conda runtime."""
    found = shutil.which("dcm2niix")
    if found:
        return found

    executable = "dcm2niix.exe" if os.name == "nt" else "dcm2niix"
    # For packaged CoCANoT, sys.executable points to <runtime>/python.exe.
    runtime = Path(sys.executable).resolve().parent
    candidates = [
        runtime / "Library" / "bin" / executable,
        runtime / "Scripts" / executable,
        runtime / executable,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(
        "dcm2niix was not found in the CoCANoT runtime or on PATH. "
        "The Windows installer should bundle dcm2niix; verify the installed "
        "runtime contains Library\\\\bin\\\\dcm2niix.exe."
    )


def is_possible_dicom_file(path: Path) -> bool:
    if not path.is_file() or path.name.startswith("."):
        return False
    return path.suffix.lower() in DICOM_EXTENSIONS


def directory_contains_dicom_files(directory: Path) -> bool:
    try:
        return any(is_possible_dicom_file(child) for child in directory.iterdir())
    except (OSError, PermissionError):
        return False


def find_dirs_with_dicom_files(input_dir: Path) -> list[Path]:
    discovered: list[Path] = []

    if directory_contains_dicom_files(input_dir):
        discovered.append(input_dir.resolve())

    try:
        descendants = sorted(path for path in input_dir.rglob("*") if path.is_dir())
    except (OSError, PermissionError) as exc:
        raise RuntimeError(
            f"Could not scan DICOM input directory:\n{input_dir}\n\n{exc}"
        ) from exc

    for directory in descendants:
        if directory_contains_dicom_files(directory):
            discovered.append(directory.resolve())

    unique: list[Path] = []
    seen: set[Path] = set()
    for directory in discovered:
        if directory not in seen:
            seen.add(directory)
            unique.append(directory)
    return unique


def normalize_input_dirs(values: Iterable[Path]) -> list[Path]:
    normalized: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        resolved = value.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            normalized.append(resolved)
    return normalized


def load_configured_paths(
    input_overrides: list[Path] | None,
    output_override: Path | None,
) -> tuple[list[Path], Path]:
    try:
        config = load_imaging_config()
        validate_imaging_config(config, create_outputs=True)
    except PipelineConfigError as exc:
        raise SystemExit(
            "Imaging configuration is missing or invalid.\n\n"
            f"{exc}\n\n"
            "Open the imaging dashboard and save the imaging folder settings "
            "before running this script."
        ) from exc

    imaging = config.imaging
    input_dirs = normalize_input_dirs(
        input_overrides if input_overrides else list(imaging.input_dirs)
    )
    output_dir = (
        output_override.expanduser().resolve()
        if output_override is not None
        else imaging.converted_nifti_dir
    )
    return input_dirs, output_dir


def build_output_subdir(
    output_dir: Path,
    input_root: Path,
    dicom_dir: Path,
    source_index: int,
    multiple_sources: bool,
) -> Path:
    relative = dicom_dir.relative_to(input_root)
    source_root = (
        output_dir / f"source-{source_index:03d}"
        if multiple_sources
        else output_dir
    )
    return source_root if relative == Path(".") else source_root / relative


def _valid_existing_nifti_pair(output_dir: Path, reported_stem: str) -> bool:
    """Validate an existing NIfTI and JSON pair before treating a no-overwrite retry as skipped."""
    import json
    import nibabel as nib

    for suffix in (".nii.gz", ".nii"):
        image_path = output_dir / (reported_stem + suffix)
        json_path = output_dir / (reported_stem + ".json")
        if not (image_path.is_file() and json_path.is_file()):
            continue
        if not image_path.stat().st_size or not json_path.stat().st_size:
            continue
        try:
            with json_path.open("r", encoding="utf-8") as handle:
                sidecar = json.load(handle)
            if not isinstance(sidecar, dict):
                continue
            image = nib.load(str(image_path))
            if not image.shape or any(int(size) <= 0 for size in image.shape):
                continue
            return True
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return False


def run_dcm2niix(
    dicom_dir: Path,
    output_dir: Path,
    filename_pattern: str,
    overwrite: bool,
    converter: str,
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        converter,
        "-z", "y",
        "-b", "y",
        "-ba", "y",
        "-w", "1" if overwrite else "0",
        "-f", filename_pattern,
        "-o", str(output_dir),
        str(dicom_dir),
    ]

    print("\\n--------------------")
    print("Converting:", dicom_dir)
    print("Saving to:", output_dir)
    print("Command:", " ".join(command))

    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
    )
    log = result.stdout or ""
    if log:
        print(log, end="" if log.endswith("\\n") else "\\n")
    if result.returncode == 0:
        print("Done.")
        return "processed"

    # dcm2niix exits non-zero for '-w 0' when a valid conversion is already
    # present. Only accept a clean, all-skipped result: never hide unrelated
    # conversion errors or partially completed multi-series input folders.
    import re
    skipped_names = re.findall(r"^Warning: Skipping existing file named (.+)$", log, re.MULTILINE)
    found = re.search(r"^Found (\\d+) DICOM file\\(s\\)", log, re.MULTILINE)
    if not overwrite and found and int(found.group(1)) == 1 and len(skipped_names) == 1:
        reported = Path(skipped_names[0].strip().strip('"'))
        try:
            same_folder = reported.parent.resolve() == output_dir.resolve()
        except OSError:
            same_folder = False
        if same_folder and _valid_existing_nifti_pair(output_dir, reported.name):
            print("Skipping verified existing DICOM conversion:", reported.name)
            return "skipped"

    print(f"ERROR: dcm2niix failed for:\\n{dicom_dir}\\nExit code: {result.returncode}")
    return "failed"



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert configured DICOM, .IMA, and extensionless DICOM folders "
            "to NIfTI using dcm2niix."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        action="append",
        dest="input_dirs",
        help=(
            "Override a configured imaging input directory. Repeat this option "
            "to process multiple input directories."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Override the configured converted NIfTI output directory. "
            "Default: <imaging.derivatives_dir>/converted_nifti"
        ),
    )
    parser.add_argument(
        "--skip-dicom-dir", action="append", type=Path, default=[],
        help="Previously prepared DICOM leaf directory to skip (repeatable).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow dcm2niix to overwrite existing converted files.",
    )
    parser.add_argument(
        "--filename-pattern",
        default="%p_%s",
        help="dcm2niix filename pattern. Default: '%%p_%%s'.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    converter = resolve_dcm2niix()

    input_dirs, output_dir = load_configured_paths(
        input_overrides=args.input_dirs,
        output_override=args.output_dir,
    )

    print("Configured DICOM input folders:")
    for path in input_dirs:
        print(" -", path)
    print("Converted NIfTI output folder:", output_dir)
    print("Filename pattern:", args.filename_pattern)

    output_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[int, Path, Path]] = []

    for source_index, input_dir in enumerate(input_dirs, start=1):
        if not input_dir.exists():
            raise SystemExit(
                f"Configured imaging input directory does not exist:\n{input_dir}"
            )
        if not input_dir.is_dir():
            raise SystemExit(
                f"Configured imaging input path is not a directory:\n{input_dir}"
            )

        dicom_dirs = find_dirs_with_dicom_files(input_dir)
        print(
            f"Found {len(dicom_dirs)} DICOM-containing folder(s) under {input_dir}"
        )
        for dicom_dir in dicom_dirs:
            jobs.append((source_index, input_dir, dicom_dir))

    if not jobs:
        raise SystemExit(
            "No .dcm, .ima, or extensionless DICOM files were found in the "
            "configured imaging input directories."
        )

    skip_dirs = {p.expanduser().resolve() for p in args.skip_dicom_dir}
    skipped = 0
    processed = 0
    failed = 0
    multiple_sources = len(input_dirs) > 1

    for source_index, input_root, dicom_dir in jobs:
        if dicom_dir.resolve() in skip_dirs and not args.overwrite:
            skipped += 1
            print("Skipping previously prepared DICOM series:", dicom_dir)
            continue
        out_subdir = build_output_subdir(
            output_dir=output_dir,
            input_root=input_root,
            dicom_dir=dicom_dir,
            source_index=source_index,
            multiple_sources=multiple_sources,
        )
        status = run_dcm2niix(
            dicom_dir=dicom_dir,
            output_dir=out_subdir,
            filename_pattern=args.filename_pattern,
            overwrite=args.overwrite,
            converter=converter,
        )
        if status == "processed":
            processed += 1
        elif status == "skipped":
            skipped += 1
        else:
            failed += 1

    print("\nDICOM to NIfTI conversion complete.")
    print(f"Converted folders: {processed}")
    print(f"Skipped completed folders: {skipped}")
    print(f"Failed folders:    {failed}")
    print("Output folder:", output_dir)

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
