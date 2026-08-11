#!/usr/bin/env python3
"""
Scrub metadata from already-defaced NIfTI files before BIDS organization.

Purpose:
- Centers should run de-identification and defacing before upload.
- This script is a second safety pass.
- It removes PHI-risky NIfTI header text fields.
- It removes PHI-risky JSON sidecar fields.
- It preserves selected non-identifying metadata useful for later BIDS organization.
- It adds directly measured NIfTI file metadata when available.
- It does not infer the imaging modality, BIDS suffix, task, or scan type.
- It does not write placeholder values such as "n/a".
- Optional fields are omitted when unavailable.

Input:
    EEGPipeline/derivatives/pydeface_deface/

Output:
    EEGPipeline/derivatives/scrubbed_defaced_nifti/
"""

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


PHI_KEYS_TO_REMOVE = {
    # Patient identifiers and demographics
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAge",
    "PatientSex",
    "PatientWeight",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "PatientMotherBirthName",
    "OtherPatientIDs",
    "OtherPatientNames",
    "EthnicGroup",

    # Institution and location information
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",

    # Clinician and operator information
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "PhysiciansOfRecord",
    "OperatorsName",

    # Study and scan identifiers
    "AccessionNumber",
    "StudyID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "FrameOfReferenceUID",
    "SOPInstanceUID",

    # Device identifiers
    "DeviceSerialNumber",

    # Dates
    "StudyDate",
    "SeriesDate",
    "AcquisitionDate",
    "ContentDate",
    "InstanceCreationDate",

    # Times
    "StudyTime",
    "SeriesTime",
    "AcquisitionTime",
    "ContentTime",
    "InstanceCreationTime",
}


FREE_TEXT_KEYS_TO_REVIEW = {
    "ProtocolName",
    "SeriesDescription",
    "StudyDescription",
    "ImageComments",
}


# These fields are copied only when they already exist in the input JSON.
# No values are inferred or calculated for this section.
ACQUISITION_KEYS_TO_KEEP = {
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
}


def is_nifti(path: Path) -> bool:
    """Return True when the path is a .nii or .nii.gz file."""
    return path.is_file() and path.name.endswith((".nii", ".nii.gz"))


def strip_nifti_suffix(path: Path) -> str:
    """Return a NIfTI filename without .nii or .nii.gz."""
    name = path.name

    if name.endswith(".nii.gz"):
        return name[:-7]

    if name.endswith(".nii"):
        return name[:-4]

    return path.stem


def scrubbed_nifti_name(path: Path) -> str:
    """Create the output filename for a scrubbed NIfTI file."""
    base = strip_nifti_suffix(path)
    suffix = ".nii.gz" if path.name.endswith(".nii.gz") else ".nii"
    return f"{base}_scrubbed{suffix}"


def matching_json_path(nifti_path: Path) -> Optional[Path]:
    """Return the matching JSON sidecar path when one exists."""
    base = strip_nifti_suffix(nifti_path)
    candidate = nifti_path.with_name(f"{base}.json")
    return candidate if candidate.exists() else None


def output_json_path(output_nifti: Path) -> Path:
    """Return the JSON sidecar path for an output NIfTI file."""
    base = strip_nifti_suffix(output_nifti)
    return output_nifti.with_name(f"{base}.json")


def normalize_sex(value: Any) -> Optional[str]:
    """
    Normalize an explicitly provided sex value.

    Returns one of:
    - Male
    - Female
    - Other
    - Unknown

    Returns None when the value is absent or cannot be mapped directly.
    """
    if value is None:
        return None

    text = str(value).strip().upper()

    if not text:
        return None

    mapping = {
        "M": "Male",
        "MALE": "Male",
        "F": "Female",
        "FEMALE": "Female",
        "O": "Other",
        "OTHER": "Other",
        "U": "Unknown",
        "UNK": "Unknown",
        "UNKNOWN": "Unknown",
    }

    return mapping.get(text)


def normalize_age(value: Any) -> Optional[float | int]:
    """
    Convert an explicitly stored age to years when the unit is clear.

    Supported examples:
    - 34
    - 34.5
    - "34"
    - "034Y"
    - "018M"
    - "090W"
    - "120D"

    Returns None when the value is absent, invalid, negative, or ambiguous.
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        age = float(value)

        if not math.isfinite(age) or age < 0:
            return None

        return int(age) if age.is_integer() else round(age, 3)

    text = str(value).strip().upper()

    if not text:
        return None

    dicom_match = re.fullmatch(r"(\d+(?:\.\d+)?)([YMWD])", text)

    if dicom_match:
        number = float(dicom_match.group(1))
        unit = dicom_match.group(2)

        if unit == "Y":
            age_years = number
        elif unit == "M":
            age_years = number / 12
        elif unit == "W":
            age_years = number / 52.1429
        else:
            age_years = number / 365.2425

        return (
            int(age_years)
            if age_years.is_integer()
            else round(age_years, 3)
        )

    try:
        age_years = float(text)
    except ValueError:
        return None

    if not math.isfinite(age_years) or age_years < 0:
        return None

    return int(age_years) if age_years.is_integer() else round(age_years, 3)


def looks_phi_like(value: Any) -> bool:
    """
    Conservatively check for obvious PHI-like free text.

    This does not replace center-side de-identification.
    """
    text = str(value or "")

    patterns = [
        r"\b\d{8}\b",
        r"\b\d{4}[-/]\d{2}[-/]\d{2}\b",
        r"\b\d{2}[-/]\d{2}[-/]\d{4}\b",
        r"\bMRN\b",
        r"\bDOB\b",
        r"\bPATIENT\b",
    ]

    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in patterns
    )


def clean_json_value(value: Any) -> Any:
    """
    Return a JSON-safe value.

    Non-finite floating-point values are omitted by returning None.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


def extract_imaging_session(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract session-level values only when directly available.

    Missing or unrecognized values are omitted.
    """
    imaging_session: Dict[str, Any] = {}

    age_at_session = normalize_age(metadata.get("PatientAge"))
    sex = normalize_sex(metadata.get("PatientSex"))

    if age_at_session is not None:
        imaging_session["age_at_session"] = age_at_session

    if sex is not None:
        imaging_session["sex"] = sex

    return imaging_session


def extract_imaging_file_metadata(nifti_path: Path) -> Dict[str, Any]:
    """
    Extract directly stored NIfTI metadata useful for later BIDS organization.

    No scan type, modality, task, or BIDS suffix is inferred.
    """
    img = nib.load(str(nifti_path))
    header = img.header

    shape = [int(value) for value in img.shape]
    zooms = header.get_zooms()
    spatial_dimension_count = min(3, len(shape), len(zooms))

    imaging_file: Dict[str, Any] = {
        "dimensions": shape,
        "number_of_dimensions": len(shape),
        "number_of_volumes": int(shape[3]) if len(shape) >= 4 else 1,
        "voxel_size": [
            float(zooms[index])
            for index in range(spatial_dimension_count)
        ],
        "data_type": str(img.get_data_dtype()),
    }

    spatial_unit, time_unit = header.get_xyzt_units()

    if spatial_unit and spatial_unit != "unknown":
        imaging_file["spatial_units"] = spatial_unit

    if len(shape) >= 4 and len(zooms) >= 4:
        time_step = float(zooms[3])

        if math.isfinite(time_step) and time_step > 0:
            imaging_file["time_step"] = time_step

    if len(shape) >= 4 and time_unit and time_unit != "unknown":
        imaging_file["time_units"] = time_unit

    return imaging_file


def extract_acquisition_metadata(
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Copy selected acquisition metadata only when present in the source JSON.

    Values are copied as stored. Nothing is inferred.
    """
    acquisition: Dict[str, Any] = {}

    for key in sorted(ACQUISITION_KEYS_TO_KEEP):
        if key not in metadata:
            continue

        value = clean_json_value(metadata[key])

        if value is None:
            continue

        acquisition[key] = value

    return acquisition


def scrub_json_metadata(
    metadata: Dict[str, Any],
    nifti_path: Path,
) -> Dict[str, Any]:
    """
    Remove PHI-risky JSON fields and add directly extracted metadata.

    Placeholder values are not written. Missing sections are omitted.
    """
    cleaned: Dict[str, Any] = {}

    for key, value in metadata.items():
        if key in PHI_KEYS_TO_REMOVE:
            continue

        # Selected acquisition fields are written into the acquisition section.
        if key in ACQUISITION_KEYS_TO_KEEP:
            continue

        if key in FREE_TEXT_KEYS_TO_REVIEW:
            if looks_phi_like(value):
                continue

        cleaned_value = clean_json_value(value)

        if cleaned_value is None:
            continue

        cleaned[key] = cleaned_value

    imaging_session = extract_imaging_session(metadata)
    imaging_file = extract_imaging_file_metadata(nifti_path)
    acquisition = extract_acquisition_metadata(metadata)

    if imaging_session:
        cleaned["imaging_session"] = imaging_session

    if imaging_file:
        cleaned["imaging_file"] = imaging_file

    if acquisition:
        cleaned["acquisition"] = acquisition

    cleaned["Defaced"] = True
    cleaned["PHIScrubbed"] = True
    cleaned["PHIScrubbedBy"] = "scrub_defaced_nifti_header.py"

    return cleaned


def scrub_nifti_header(input_path: Path, output_path: Path) -> None:
    """
    Remove PHI-risky text fields from the NIfTI header.

    Preserve:
    - Image data
    - Data type
    - Affine
    - qform
    - sform
    - Image dimensions
    - Spatial geometry
    """
    img = nib.load(str(input_path))
    header = img.header.copy()

    for field in ("descrip", "aux_file", "intent_name"):
        if field in header:
            header[field] = b""

    image_data = np.asanyarray(img.dataobj)

    scrubbed_img = nib.Nifti1Image(
        image_data,
        affine=img.affine,
        header=header,
    )

    try:
        qform, qform_code = img.get_qform(coded=True)
        sform, sform_code = img.get_sform(coded=True)

        scrubbed_img.set_qform(qform, code=int(qform_code))
        scrubbed_img.set_sform(sform, code=int(sform_code))
    except Exception as exc:
        print(
            "WARNING: Could not explicitly restore qform or sform for "
            f"{input_path.name}: {exc}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(scrubbed_img, str(output_path))


def copy_and_scrub_json(
    input_json: Path,
    input_nifti: Path,
    output_json: Path,
) -> None:
    """Read, scrub, enrich, and save a JSON sidecar."""
    with input_json.open("r", encoding="utf-8") as file:
        metadata = json.load(file)

    if not isinstance(metadata, dict):
        raise ValueError(
            f"JSON sidecar must contain a JSON object: {input_json}"
        )

    cleaned = scrub_json_metadata(
        metadata=metadata,
        nifti_path=input_nifti,
    )

    output_json.parent.mkdir(parents=True, exist_ok=True)

    with output_json.open("w", encoding="utf-8") as file:
        json.dump(cleaned, file, indent=2, allow_nan=False)
        file.write("\n")


def create_json_without_input_sidecar(
    input_nifti: Path,
    output_json: Path,
) -> None:
    """
    Create a JSON sidecar from directly available NIfTI metadata.

    No acquisition or imaging-session values are invented.
    """
    cleaned: Dict[str, Any] = {
        "imaging_file": extract_imaging_file_metadata(input_nifti),
        "Defaced": True,
        "PHIScrubbed": True,
        "PHIScrubbedBy": "scrub_defaced_nifti_header.py",
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)

    with output_json.open("w", encoding="utf-8") as file:
        json.dump(cleaned, file, indent=2, allow_nan=False)
        file.write("\n")


def verify_nifti(
    input_path: Path,
    output_path: Path,
) -> None:
    """Verify that key image geometry is unchanged."""
    try:
        input_img = nib.load(str(input_path))
        output_img = nib.load(str(output_path))

        if input_img.shape != output_img.shape:
            raise RuntimeError(
                "Image shape changed during scrubbing: "
                f"{input_img.shape} -> {output_img.shape}"
            )

        if not np.allclose(
            input_img.affine,
            output_img.affine,
            rtol=1e-5,
            atol=1e-6,
        ):
            raise RuntimeError("Image affine changed during scrubbing.")

    except Exception as exc:
        raise RuntimeError(
            f"Scrubbed NIfTI failed validation: {output_path}\n{exc}"
        ) from exc


def process_one_file(
    input_path: Path,
    input_dir: Path,
    output_dir: Path,
    overwrite: bool,
) -> str:
    """Scrub one NIfTI file and its matching JSON sidecar."""
    relative_path = input_path.relative_to(input_dir)

    output_nifti = (
        output_dir
        / relative_path.parent
        / scrubbed_nifti_name(input_path)
    )
    output_json = output_json_path(output_nifti)

    if output_nifti.exists() and not overwrite:
        print(
            "Skipping existing: "
            f"{output_nifti.relative_to(output_dir)}"
        )
        return "skipped"

    if overwrite:
        if output_nifti.exists():
            output_nifti.unlink()

        if output_json.exists():
            output_json.unlink()

    scrub_nifti_header(
        input_path=input_path,
        output_path=output_nifti,
    )

    verify_nifti(
        input_path=input_path,
        output_path=output_nifti,
    )

    input_json = matching_json_path(input_path)

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

    print(f"Scrubbed: {relative_path}")
    return "processed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scrub PHI-risky metadata from already-defaced NIfTI files."
        )
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Folder containing defaced NIfTI files.",
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

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    print("Input defaced NIfTI folder:", input_dir)
    print("Output scrubbed NIfTI folder:", output_dir)

    if not input_dir.exists():
        raise SystemExit(
            f"Input directory does not exist: {input_dir}"
        )

    nifti_files = sorted(
        path
        for path in input_dir.rglob("*")
        if is_nifti(path)
    )

    print(f"Found {len(nifti_files)} NIfTI file(s).")

    if not nifti_files:
        raise SystemExit("No .nii or .nii.gz files found.")

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
            print(f"ERROR: Could not scrub {path}")
            print(exc)

    print("\nNIfTI header scrubbing complete.")
    print(f"Processed: {processed_count}")
    print(f"Skipped:   {skipped_count}")
    print(f"Failed:    {failed_count}")
    print("Output folder:", output_dir)

    if failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
