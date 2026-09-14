#!/usr/bin/env python3
"""Scrub NIfTI headers and retain approved source metadata."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import nibabel as nib
    import numpy as np
except ImportError as exc:
    raise SystemExit(
        "nibabel and numpy are required. Install them with:\n\n"
        "    python -m pip install nibabel numpy\n"
    ) from exc


PROJECT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_INPUT_DIR = PROJECT_DIR / "derivatives" / "pydeface_deface"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "derivatives" / "scrubbed_defaced_nifti"


SOURCE_KEYS_TO_KEEP = {
    "Manufacturer",
    "ManufacturersModelName",
    "MagneticFieldStrength",
    "RepetitionTime",
    "EchoTime",
    "FlipAngle",
    "SliceThickness",
    "SpacingBetweenSlices",
    "PhaseEncodingDirection",
    "EffectiveEchoSpacing",
    "TotalReadoutTime",
    "ImageType",
    "SeriesNumber",
    "AcquisitionNumber",
    "InstanceNumber",
    "ScanningSequence",
    "SequenceVariant",
    "ScanOptions",
    "MRAcquisitionType",
    "PulseSequenceName",
    "PulseSequenceDetails",
    "EchoTrainLength",
    "PercentSampling",
    "PercentPhaseFieldOfView",
    "AcquisitionMatrixPE",
    "ReconMatrixPE",
    "PixelBandwidth",
    "InPlanePhaseEncodingDirectionDICOM",
    "ImageOrientationPatientDICOM",
    "DwellTime",
    "PartialFourier",
    "ParallelReductionFactorInPlane",
    "SAR",
    "TxRefAmp",
    "ShimSetting",
    "ConversionSoftware",
    "ConversionSoftwareVersion",
}


SOURCE_FREE_TEXT_KEYS = {
    "ProtocolName",
    "SeriesDescription",
}


def is_nifti(path: Path) -> bool:
    return path.is_file() and path.name.endswith(
        (".nii", ".nii.gz")
    )


def strip_nifti_suffix(path: Path) -> str:
    name = path.name

    if name.endswith(".nii.gz"):
        return name[:-7]

    if name.endswith(".nii"):
        return name[:-4]

    return path.stem


def scrubbed_nifti_name(path: Path) -> str:
    base = strip_nifti_suffix(path)
    suffix = ".nii.gz" if path.name.endswith(".nii.gz") else ".nii"
    return f"{base}_scrubbed{suffix}"


def matching_json_path(
    nifti_path: Path,
) -> Optional[Path]:
    base = strip_nifti_suffix(nifti_path)
    candidate = nifti_path.with_name(
        f"{base}.json"
    )
    return candidate if candidate.exists() else None


def output_json_path(
    output_nifti: Path,
) -> Path:
    base = strip_nifti_suffix(output_nifti)
    return output_nifti.with_name(
        f"{base}.json"
    )


def looks_phi_like(value: Any) -> bool:
    text = str(value or "")

    patterns = (
        r"\b\d{8}\b",
        r"\b\d{4}[-/]\d{2}[-/]\d{2}\b",
        r"\b\d{2}[-/]\d{2}[-/]\d{4}\b",
        r"\bMRN\b",
        r"\bDOB\b",
        r"\bPATIENT\b",
    )

    return any(
        re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for pattern in patterns
    )


def clean_json_value(value: Any) -> Any:
    if type(value) is float and not math.isfinite(value):
        return None

    return value


def extract_imaging_file_metadata(
    nifti_path: Path,
) -> Dict[str, Any]:
    img = nib.load(str(nifti_path))
    header = img.header

    shape = [
        int(value)
        for value in img.shape
    ]
    zooms = header.get_zooms()
    spatial_dimension_count = min(
        3,
        len(shape),
        len(zooms),
    )

    metadata: Dict[str, Any] = {
        "dimensions": shape,
        "number_of_dimensions": len(shape),
        "number_of_volumes": (
            int(shape[3])
            if len(shape) >= 4
            else 1
        ),
        "voxel_size": [
            float(zooms[index])
            for index in range(
                spatial_dimension_count
            )
        ],
        "data_type": str(
            img.get_data_dtype()
        ),
    }

    spatial_unit, time_unit = (
        header.get_xyzt_units()
    )

    if (
        spatial_unit
        and spatial_unit != "unknown"
    ):
        metadata[
            "spatial_units"
        ] = spatial_unit

    if len(shape) >= 4 and len(zooms) >= 4:
        time_step = float(zooms[3])

        if (
            math.isfinite(time_step)
            and time_step > 0
        ):
            metadata[
                "time_step"
            ] = time_step

    if (
        len(shape) >= 4
        and time_unit
        and time_unit != "unknown"
    ):
        metadata[
            "time_units"
        ] = time_unit

    return metadata


def approved_source_metadata(
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}

    for key in sorted(SOURCE_KEYS_TO_KEEP):
        if key not in metadata:
            continue

        value = clean_json_value(
            metadata[key]
        )

        if value is None:
            continue

        cleaned[key] = value

    for key in sorted(SOURCE_FREE_TEXT_KEYS):
        if key not in metadata:
            continue

        value = metadata[key]

        if looks_phi_like(value):
            continue

        value = clean_json_value(value)

        if value is None:
            continue

        cleaned[key] = value

    return cleaned


def scrub_json_metadata(
    metadata: Dict[str, Any],
    nifti_path: Path,
) -> Dict[str, Any]:
    cleaned = approved_source_metadata(
        metadata
    )

    cleaned[
        "imaging_file"
    ] = extract_imaging_file_metadata(
        nifti_path
    )
    cleaned["Defaced"] = True
    cleaned["PHIScrubbed"] = True
    cleaned[
        "PHIScrubbedBy"
    ] = "scrub_nifti_header.py"

    return cleaned


def scrub_nifti_header(
    input_path: Path,
    output_path: Path,
) -> None:
    img = nib.load(str(input_path))
    header = img.header.copy()

    for field in (
        "descrip",
        "aux_file",
        "intent_name",
    ):
        if field in header:
            header[field] = b""

    image_data = np.asanyarray(
        img.dataobj
    )

    scrubbed_img = nib.Nifti1Image(
        image_data,
        affine=img.affine,
        header=header,
    )

    try:
        qform, qform_code = (
            img.get_qform(coded=True)
        )
        sform, sform_code = (
            img.get_sform(coded=True)
        )

        scrubbed_img.set_qform(
            qform,
            code=int(qform_code),
        )
        scrubbed_img.set_sform(
            sform,
            code=int(sform_code),
        )
    except Exception as exc:
        print(
            "WARNING: Could not restore qform or sform for "
            f"{input_path.name}: {exc}"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    nib.save(
        scrubbed_img,
        str(output_path),
    )


def copy_and_scrub_json(
    input_json: Path,
    input_nifti: Path,
    output_json: Path,
) -> None:
    with input_json.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(file)

    if type(metadata) is not dict:
        raise ValueError(
            f"JSON sidecar must contain a JSON object: {input_json}"
        )

    cleaned = scrub_json_metadata(
        metadata=metadata,
        nifti_path=input_nifti,
    )

    output_json.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_json.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            cleaned,
            file,
            indent=2,
            allow_nan=False,
        )
        file.write("\n")


def create_json_without_input_sidecar(
    input_nifti: Path,
    output_json: Path,
) -> None:
    cleaned: Dict[str, Any] = {
        "imaging_file": (
            extract_imaging_file_metadata(
                input_nifti
            )
        ),
        "Defaced": True,
        "PHIScrubbed": True,
        "PHIScrubbedBy": (
            "scrub_nifti_header.py"
        ),
    }

    output_json.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_json.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            cleaned,
            file,
            indent=2,
            allow_nan=False,
        )
        file.write("\n")


def verify_nifti(
    input_path: Path,
    output_path: Path,
) -> None:
    try:
        input_img = nib.load(
            str(input_path)
        )
        output_img = nib.load(
            str(output_path)
        )

        if input_img.shape != output_img.shape:
            raise RuntimeError(
                "Image shape changed during scrubbing: "
                f"{input_img.shape} -> "
                f"{output_img.shape}"
            )

        if not np.allclose(
            input_img.affine,
            output_img.affine,
            rtol=1e-5,
            atol=1e-6,
        ):
            raise RuntimeError(
                "Image affine changed during scrubbing."
            )
    except Exception as exc:
        raise RuntimeError(
            "Scrubbed NIfTI failed validation: "
            f"{output_path}\n{exc}"
        ) from exc


def process_one_file(
    input_path: Path,
    input_dir: Path,
    output_dir: Path,
    overwrite: bool,
) -> str:
    relative_path = input_path.relative_to(
        input_dir
    )

    output_nifti = (
        output_dir
        / relative_path.parent
        / scrubbed_nifti_name(
            input_path
        )
    )
    output_json = output_json_path(
        output_nifti
    )

    if (
        output_nifti.exists()
        and not overwrite
    ):
        print(
            "Skipping existing: "
            f"{output_nifti.relative_to(output_dir)}"
        )
        return "skipped"

    if overwrite:
        output_nifti.unlink(
            missing_ok=True
        )
        output_json.unlink(
            missing_ok=True
        )

    scrub_nifti_header(
        input_path=input_path,
        output_path=output_nifti,
    )

    verify_nifti(
        input_path=input_path,
        output_path=output_nifti,
    )

    input_json = matching_json_path(
        input_path
    )

    if input_json is not None:
        copy_and_scrub_json(
            input_json=input_json,
            input_nifti=input_path,
            output_json=output_json,
        )
    else:
        print(
            "WARNING: No JSON sidecar found for "
            f"{relative_path}. Creating one from NIfTI metadata only."
        )
        create_json_without_input_sidecar(
            input_nifti=input_path,
            output_json=output_json,
        )

    print(
        f"Scrubbed: {relative_path}"
    )
    return "processed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scrub NIfTI headers and retain approved source metadata."
        )
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Folder containing NIfTI files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Folder for scrubbed NIfTI files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing scrubbed files.",
    )

    args = parser.parse_args()

    input_dir = (
        args.input_dir
        .expanduser()
        .resolve()
    )
    output_dir = (
        args.output_dir
        .expanduser()
        .resolve()
    )

    print(
        "Input NIfTI folder:",
        input_dir,
    )
    print(
        "Output scrubbed NIfTI folder:",
        output_dir,
    )

    if not input_dir.exists():
        raise SystemExit(
            f"Input directory does not exist: {input_dir}"
        )

    nifti_files = sorted(
        path
        for path in input_dir.rglob("*")
        if is_nifti(path)
    )

    print(
        f"Found {len(nifti_files)} NIfTI file(s)."
    )

    if not nifti_files:
        raise SystemExit(
            "No .nii or .nii.gz files found."
        )

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for path in nifti_files:
        try:
            status = process_one_file(
                input_path=path,
                input_dir=input_dir,
                output_dir=output_dir,
                overwrite=args.overwrite,
            )

            if status == "processed":
                processed_count += 1
            else:
                skipped_count += 1

        except Exception as exc:
            failed_count += 1
            print(
                f"ERROR: Could not scrub {path}"
            )
            print(exc)

    print(
        "\nNIfTI header scrubbing complete."
    )
    print(
        f"Processed: {processed_count}"
    )
    print(
        f"Skipped:   {skipped_count}"
    )
    print(
        f"Failed:    {failed_count}"
    )
    print(
        "Output folder:",
        output_dir,
    )

    if failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
