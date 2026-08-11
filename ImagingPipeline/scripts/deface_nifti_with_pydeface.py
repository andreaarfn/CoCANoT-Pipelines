#!/usr/bin/env python3
"""
Deface configured NIfTI files using PyDeface.

Paths come from the shared parent-level pipeline_settings.json through
pipeline_config.py. There are no machine-specific fallback directories.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

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


def nifti_base_name(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return path.name[:-7]
    if path.name.endswith(".nii"):
        return path.name[:-4]
    return path.stem


def matching_json_path(nifti_path: Path) -> Path:
    return nifti_path.with_name(f"{nifti_base_name(nifti_path)}.json")


def find_nifti_files(input_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.name.endswith((".nii", ".nii.gz"))
    )


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.2f} MB"
    return f"{size_bytes / (1024**3):.2f} GB"


def format_seconds(seconds: float) -> str:
    return f"{seconds:.2f} sec" if seconds < 60 else f"{seconds / 60:.2f} min"


def load_configured_paths(
    input_override: Path | None,
    output_override: Path | None,
    log_override: Path | None,
) -> tuple[Path, Path, Path]:
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
    input_dir = (
        input_override.expanduser().resolve()
        if input_override is not None
        else imaging.converted_nifti_dir
    )
    output_dir = (
        output_override.expanduser().resolve()
        if output_override is not None
        else imaging.defaced_dir
    )
    log_dir = (
        log_override.expanduser().resolve()
        if log_override is not None
        else imaging.pydeface_logs_dir
    )
    return input_dir, output_dir, log_dir


def copy_and_update_json(
    input_json: Path,
    output_json: Path,
    source_nifti: Path,
    input_dir: Path,
) -> str:
    if not input_json.exists():
        return "No matching JSON sidecar found."

    try:
        with input_json.open("r", encoding="utf-8") as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        return f"JSON sidecar was not copied because it could not be read: {exc}"

    if not isinstance(metadata, dict):
        return "JSON sidecar was not copied because it is not a JSON object."

    metadata["DefacingSoftware"] = "pydeface"
    metadata["SourceFile"] = str(source_nifti.relative_to(input_dir))

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, allow_nan=False)
        file.write("\n")

    return "JSON sidecar copied and updated."


def run_and_log(
    command: list[str],
    log_path: Path,
    log_header: str,
) -> tuple[int, float]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start_datetime = datetime.now()
    start_time = time.perf_counter()

    with log_path.open("w", encoding="utf-8") as log:
        log.write(log_header)
        log.write("\n")
        log.write("=" * 80 + "\nCommand\n" + "=" * 80 + "\n")
        log.write(" ".join(command) + "\n\n")
        log.write("=" * 80 + "\nTiming\n" + "=" * 80 + "\n")
        log.write(f"Start time: {start_datetime.isoformat(timespec='seconds')}\n\n")
        log.write("=" * 80 + "\nPyDeface output\n" + "=" * 80 + "\n")

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout is not None:
            for line in process.stdout:
                print(line, end="")
                log.write(line)

        exit_code = process.wait()
        elapsed = time.perf_counter() - start_time
        end_datetime = datetime.now()

        log.write("\n" + "=" * 80 + "\nRun summary\n" + "=" * 80 + "\n")
        log.write(f"End time: {end_datetime.isoformat(timespec='seconds')}\n")
        log.write(f"Elapsed time: {format_seconds(elapsed)}\n")
        log.write(f"Exit code: {exit_code}\n")

    return exit_code, elapsed


def get_nifti_shape(nifti_path: Path) -> tuple[int, ...]:
    return tuple(int(value) for value in nib.load(str(nifti_path)).shape)


def validate_output(input_nifti: Path, output_nifti: Path) -> None:
    if not output_nifti.exists():
        raise RuntimeError("PyDeface reported success but created no output file.")

    input_img = nib.load(str(input_nifti))
    output_img = nib.load(str(output_nifti))

    if input_img.shape != output_img.shape:
        raise RuntimeError(
            f"Defaced output shape differs from input: {input_img.shape} -> {output_img.shape}"
        )
    if not np.allclose(input_img.affine, output_img.affine, rtol=1e-5, atol=1e-6):
        raise RuntimeError("Defaced output affine differs from input.")


def run_4d_pydeface(
    input_nifti: Path,
    output_nifti: Path,
    log_path: Path,
    log_header: str,
) -> tuple[int, float]:
    start_time = time.perf_counter()

    try:
        img = nib.load(str(input_nifti))
        if len(img.shape) != 4:
            raise ValueError(f"Expected a 4D NIfTI, found shape {img.shape}")

        data = np.asanyarray(img.dataobj)
        mean_data = np.mean(data, axis=3, dtype=np.float32)

        with tempfile.TemporaryDirectory(prefix="pydeface_4d_") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            mean_input = temp_dir / "temporal_mean.nii.gz"
            mean_defaced = temp_dir / "temporal_mean_defaced.nii.gz"

            mean_header = img.header.copy()
            mean_header.set_data_shape(mean_data.shape)
            mean_header.set_data_dtype(np.float32)
            nib.save(
                nib.Nifti1Image(mean_data, img.affine, mean_header),
                str(mean_input),
            )

            command = [
                "pydeface",
                str(mean_input),
                "--outfile",
                str(mean_defaced),
            ]
            exit_code, _ = run_and_log(
                command=command,
                log_path=log_path,
                log_header=(
                    log_header
                    + f"Input dimensions: {img.shape}\n"
                    + "Processing mode: 4D temporal-mean mask\n"
                ),
            )
            if exit_code != 0:
                return exit_code, time.perf_counter() - start_time

            defaced_mean = np.asanyarray(
                nib.load(str(mean_defaced)).dataobj
            ).astype(np.float32, copy=False)
            if defaced_mean.shape != mean_data.shape:
                raise RuntimeError(
                    "Defaced reference shape does not match the temporal mean: "
                    f"{defaced_mean.shape} versus {mean_data.shape}"
                )

            removed_mask = (
                ~np.isclose(mean_data, 0.0, atol=1e-6)
                & np.isclose(defaced_mean, 0.0, atol=1e-6)
            )
            if not np.any(removed_mask):
                raise RuntimeError("No removed voxels were detected in the defaced reference.")

            keep_mask = ~removed_mask
            output_data = data * keep_mask[..., np.newaxis]

            output_header = img.header.copy()
            output_header.set_data_shape(img.shape)
            output_header.set_data_dtype(img.get_data_dtype())
            output_nifti.parent.mkdir(parents=True, exist_ok=True)
            nib.save(
                nib.Nifti1Image(output_data, img.affine, output_header),
                str(output_nifti),
            )

        elapsed = time.perf_counter() - start_time
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n" + "=" * 80 + "\n4D mask application\n" + "=" * 80 + "\n")
            log.write(f"Original shape: {img.shape}\n")
            log.write(f"Spatial mask shape: {keep_mask.shape}\n")
            log.write(f"Volumes defaced: {img.shape[3]}\n")
            log.write(f"Removed voxels: {int(np.count_nonzero(removed_mask))}\n")
            log.write(f"Final output: {output_nifti}\n")
            log.write(f"Total 4D processing time: {format_seconds(elapsed)}\n")
        return 0, elapsed

    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n" + "=" * 80 + "\n4D processing error\n" + "=" * 80 + "\n")
            log.write(f"{type(exc).__name__}: {exc}\n")
        output_nifti.unlink(missing_ok=True)
        return 1, elapsed


def append_json_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n" + "=" * 80 + "\nJSON sidecar status\n" + "=" * 80 + "\n")
        log.write(message + "\n")


def print_processing_summary(results: list[dict[str, Any]]) -> None:
    print("\n==============================")
    print("PyDeface Processing Summary")
    print("==============================")

    if not results:
        print("No files were processed.")
        return

    processed = sum(result["status"] == "processed" for result in results)
    skipped = sum(result["status"] == "skipped" for result in results)
    failed = sum(result["status"] == "failed" for result in results)
    total_time = sum(
        float(result["elapsed"])
        for result in results
        if result["status"] == "processed" and result["elapsed"] is not None
    )

    for result in results:
        elapsed = "-" if result["elapsed"] is None else format_seconds(float(result["elapsed"]))
        print(
            f"{result['input']} | {result['size']} | "
            f"{result['status']} | {elapsed}"
        )

    print(f"Processed: {processed}")
    print(f"Skipped:   {skipped}")
    print(f"Failed:    {failed}")
    print(f"Total processing time: {format_seconds(total_time)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deface configured 3D and 4D NIfTI files using PyDeface."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Override <imaging.derivatives_dir>/converted_nifti.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override <imaging.derivatives_dir>/pydeface_deface.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        help="Override <imaging.derivatives_dir>/logs/pydeface_deface.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing defaced files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if shutil.which("pydeface") is None:
        raise SystemExit(
            "pydeface was not found on PATH. Activate the correct environment "
            "and install pydeface before running this script."
        )

    input_dir, output_dir, log_dir = load_configured_paths(
        input_override=args.input_dir,
        output_override=args.output_dir,
        log_override=args.log_dir,
    )

    print("Input NIfTI folder:", input_dir)
    print("Output defaced folder:", output_dir)
    print("Log folder:", log_dir)

    if not input_dir.exists():
        raise SystemExit(f"Configured NIfTI input directory does not exist:\n{input_dir}")
    if not input_dir.is_dir():
        raise SystemExit(f"Configured NIfTI input path is not a directory:\n{input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    nifti_files = find_nifti_files(input_dir)
    print(f"Found {len(nifti_files)} NIfTI file(s).")
    if not nifti_files:
        raise SystemExit(f"No .nii or .nii.gz files were found under:\n{input_dir}")

    results: list[dict[str, Any]] = []

    for nifti_path in nifti_files:
        relative_path = nifti_path.relative_to(input_dir)
        relative_folder = relative_path.parent
        base = nifti_base_name(nifti_path)
        output_subdir = output_dir / relative_folder
        log_subdir = log_dir / relative_folder
        output_nifti = output_subdir / f"{base}_defaced.nii.gz"
        output_json = output_subdir / f"{base}_defaced.json"
        input_json = matching_json_path(nifti_path)
        log_path = log_subdir / f"{base}_pydeface_deface.log"
        input_size_text = format_file_size(nifti_path.stat().st_size)

        # Preserve the input folder structure in both output locations.
        # PyDeface and the log writer cannot create missing parent folders.
        output_subdir.mkdir(parents=True, exist_ok=True)
        log_subdir.mkdir(parents=True, exist_ok=True)

        print("\n--------------------")
        print("Input:", relative_path)
        print("Input size:", input_size_text)
        print("Output:", output_nifti.relative_to(output_dir))
        print("Log:", log_path.relative_to(log_dir))

        if output_nifti.exists() and not args.overwrite:
            print("Skipping: output already exists. Use --overwrite to replace it.")
            results.append(
                {
                    "input": str(relative_path),
                    "size": input_size_text,
                    "status": "skipped",
                    "elapsed": None,
                }
            )
            continue

        if args.overwrite:
            output_nifti.unlink(missing_ok=True)
            output_json.unlink(missing_ok=True)
            log_path.unlink(missing_ok=True)

        log_header = (
            "=" * 80 + "\nPyDeface defacing log\n" + "=" * 80 + "\n"
            f"Input: {relative_path}\n"
            f"Input size: {input_size_text}\n"
            f"Output: {output_nifti.relative_to(output_dir)}\n"
            f"JSON input: {input_json.relative_to(input_dir) if input_json.exists() else 'None found'}\n"
            f"JSON output: {output_json.relative_to(output_dir)}\n"
            f"Log: {log_path.relative_to(log_dir)}\n"
        )

        try:
            nifti_shape = get_nifti_shape(nifti_path)
            print("Dimensions:", nifti_shape)

            if len(nifti_shape) == 4:
                exit_code, elapsed = run_4d_pydeface(
                    input_nifti=nifti_path,
                    output_nifti=output_nifti,
                    log_path=log_path,
                    log_header=log_header,
                )
            elif len(nifti_shape) == 3:
                command = [
                    "pydeface",
                    str(nifti_path),
                    "--outfile",
                    str(output_nifti),
                ]
                exit_code, elapsed = run_and_log(
                    command=command,
                    log_path=log_path,
                    log_header=(
                        log_header
                        + f"Input dimensions: {nifti_shape}\n"
                        + "Processing mode: standard 3D pydeface\n"
                    ),
                )
            else:
                raise RuntimeError(
                    f"Only 3D and 4D NIfTI images are supported; found shape {nifti_shape}."
                )

            if exit_code != 0:
                raise RuntimeError(f"PyDeface exited with code {exit_code}.")

            validate_output(nifti_path, output_nifti)
            json_message = copy_and_update_json(
                input_json=input_json,
                output_json=output_json,
                source_nifti=nifti_path,
                input_dir=input_dir,
            )
            append_json_log(log_path, json_message)
            print(f"Done. Processing time: {format_seconds(elapsed)}")
            results.append(
                {
                    "input": str(relative_path),
                    "size": input_size_text,
                    "status": "processed",
                    "elapsed": elapsed,
                }
            )
        except Exception as exc:
            output_nifti.unlink(missing_ok=True)
            print(f"ERROR: Defacing failed for {relative_path}")
            print(exc)
            print(f"See log: {log_path}")
            results.append(
                {
                    "input": str(relative_path),
                    "size": input_size_text,
                    "status": "failed",
                    "elapsed": None,
                }
            )

    print("\nPyDeface defacing complete.")
    print("Defaced outputs saved in:", output_dir)
    print("Logs saved in:", log_dir)
    print_processing_summary(results)

    if any(result["status"] == "failed" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
