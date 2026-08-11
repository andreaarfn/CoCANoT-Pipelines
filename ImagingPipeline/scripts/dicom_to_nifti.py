#!/usr/bin/env python3
"""
Convert configured DICOM inputs to NIfTI using dcm2niix.

Paths come from the shared parent-level pipeline_settings.json through
pipeline_config.py. There are no machine-specific fallback directories.
"""

from __future__ import annotations

import argparse
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


def run_dcm2niix(
    dicom_dir: Path,
    output_dir: Path,
    filename_pattern: str,
    overwrite: bool,
) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "dcm2niix",
        "-z", "y",
        "-b", "y",
        "-ba", "y",
        "-w", "1" if overwrite else "0",
        "-f", filename_pattern,
        "-o", str(output_dir),
        str(dicom_dir),
    ]

    print("\n--------------------")
    print("Converting:", dicom_dir)
    print("Saving to:", output_dir)
    print("Command:", " ".join(command))

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        print(
            "ERROR: dcm2niix failed for:\n"
            f"{dicom_dir}\n"
            f"Exit code: {exc.returncode}"
        )
        return False

    print("Done.")
    return True


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

    if shutil.which("dcm2niix") is None:
        raise SystemExit(
            "dcm2niix was not found on PATH. Install it before running conversion."
        )

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

    processed = 0
    failed = 0
    multiple_sources = len(input_dirs) > 1

    for source_index, input_root, dicom_dir in jobs:
        out_subdir = build_output_subdir(
            output_dir=output_dir,
            input_root=input_root,
            dicom_dir=dicom_dir,
            source_index=source_index,
            multiple_sources=multiple_sources,
        )
        if run_dcm2niix(
            dicom_dir=dicom_dir,
            output_dir=out_subdir,
            filename_pattern=args.filename_pattern,
            overwrite=args.overwrite,
        ):
            processed += 1
        else:
            failed += 1

    print("\nDICOM to NIfTI conversion complete.")
    print(f"Converted folders: {processed}")
    print(f"Failed folders:    {failed}")
    print("Output folder:", output_dir)

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
