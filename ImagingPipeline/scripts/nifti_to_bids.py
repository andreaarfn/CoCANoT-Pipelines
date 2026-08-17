#!/usr/bin/env python3
"""Convert dashboard-approved NIfTI files into CoCANoT MRI / CT dataset layouts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

SUPPORTED_BIDS_VERSION = "1.11.1"

MRI_SEQUENCE_MAP = {
    "T1": ("anat", "T1w"),
    "T2": ("anat", "T2w"),
    "FLAIR": ("anat", "FLAIR"),
    "DWI": ("dwi", "dwi"),
    # Core BIDS 1.11.1 does not define an SWI suffix. CoCANoT represents
    # appropriately T2*-weighted SWI output as acq-swi_T2starw.
    "SWI": ("anat", "T2starw"),
}

INDEX_FIELDS = {"run"}
ENUM_FIELDS = {
    "part": {"mag", "phase", "real", "imag"},
}

PYDEFACE_NAME = "PyDeface"
PYDEFACE_URL = "https://github.com/poldracklab/pydeface"

IMAGING_PURPOSE_OPTIONS = {
    "Diagnostic evaluation",
    "Presurgical evaluation",
    "Neuromodulation Planning",
    "Electrode Localization",
    "Postoperative Evaluation (<30 days)",
    "Follow-up Evaluation (>30 days after surgery)",
    "Other",
    "Unknown",
}

SURGERY_TIMING_OPTIONS = {
    "Preoperative",
    "Intraoperative",
    "Immediate Postoperative (<30 days after surgery)",
    "Follow-up (>30 days after surgery)",
    "Unknown",
}

MRI_OPTIONAL_MAP = {
    "manufacturer": "Manufacturer",
    "model_name": "ManufacturersModelName",
    "software_versions": "SoftwareVersions",
    "magnetic_field_strength": "MagneticFieldStrength",
    "receive_coil_name": "ReceiveCoilName",
    "sequence_name": "SequenceName",
    "pulse_sequence_details": "PulseSequenceDetails",
    "echo_time": "EchoTime",
    "repetition_time_excitation": "RepetitionTimeExcitation",
    "inversion_time": "InversionTime",
    "flip_angle": "FlipAngle",
    "phase_encoding_direction": "PhaseEncodingDirection",
    "effective_echo_spacing": "EffectiveEchoSpacing",
    "total_readout_time": "TotalReadoutTime",
}

CT_OPTIONAL_MAP = {
    "manufacturer": "Manufacturer",
    "model_name": "ManufacturersModelName",
    "software_versions": "SoftwareVersions",
    "kvp": "KVP",
    "slice_thickness": "SliceThickness",
    "convolution_kernel": "ConvolutionKernel",
    "pixel_spacing": "PixelSpacing",
    "reconstruction_diameter": "ReconstructionDiameter",
}

NUMERIC_OPTIONAL_FIELDS = {
    "magnetic_field_strength",
    "echo_time",
    "repetition_time_excitation",
    "inversion_time",
    "flip_angle",
    "effective_echo_spacing",
    "total_readout_time",
    "kvp",
    "slice_thickness",
    "reconstruction_diameter",
}


def strip_nifti_suffix(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return path.name[:-7]
    if path.name.endswith(".nii"):
        return path.name[:-4]
    return path.stem


def nifti_extension(path: Path) -> str:
    return ".nii.gz" if path.name.endswith(".nii.gz") else ".nii"


def matching_json_path(path: Path) -> Optional[Path]:
    candidate = path.with_name(f"{strip_nifti_suffix(path)}.json")
    return candidate if candidate.exists() else None


def matching_extra_sidecars(path: Path) -> list[Path]:
    base = strip_nifti_suffix(path)
    extras: list[Path] = []
    for extension in (".bval", ".bvec"):
        candidate = path.with_name(f"{base}{extension}")
        if candidate.exists():
            extras.append(candidate)
    return extras


def load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"JSON file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def clean_project(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f/\\]+", "-", value.strip()).strip(" .-")
    if not cleaned:
        raise ValueError("Project must contain a usable folder name.")
    return cleaned


def clean_label(
    value: str,
    field: str,
    *,
    optional: bool = False,
) -> str:
    text = str(value).strip()
    if not text and optional:
        return ""

    prefixes = {
        "participant_id": "sub-",
        "session_id": "ses-",
    }
    prefix = prefixes.get(field)
    if prefix and text.lower().startswith(prefix):
        text = text[len(prefix):]

    if not text:
        raise ValueError(f"{field} is required.")

    if field in INDEX_FIELDS:
        if not text.isdigit():
            raise ValueError(f"{field} must contain digits only.")
        return text

    if field in ENUM_FIELDS:
        if text not in ENUM_FIELDS[field]:
            raise ValueError(
                f"{field} must be one of: {', '.join(sorted(ENUM_FIELDS[field]))}"
            )
        return text

    if not re.fullmatch(r"[A-Za-z0-9+]+", text):
        raise ValueError(
            f"{field} may contain only letters, numbers, and +."
        )
    return text


def clean_optional_entity(value: Any, field: str) -> str:
    return clean_label(str(value or ""), field, optional=True)


def parse_optional_number(value: Any, field: str) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be numeric.") from exc


def parse_pixel_spacing(value: Any) -> Optional[list[float]]:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Pixel Spacing must be a JSON array, for example [0.5, 0.5]."
        ) from exc

    if (
        not isinstance(parsed, list)
        or len(parsed) != 2
        or not all(isinstance(item, (int, float)) for item in parsed)
    ):
        raise ValueError(
            "Pixel Spacing must be a two-number JSON array."
        )

    return [float(item) for item in parsed]


def normalize_optional_metadata(
    raw: Dict[str, Any],
    *,
    modality: str,
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("optional_metadata must be a JSON object.")

    normalized: Dict[str, Any] = {}

    for key, value in raw.items():
        text = str(value).strip()
        if not text:
            continue

        if key in NUMERIC_OPTIONAL_FIELDS:
            normalized[key] = parse_optional_number(text, key)
        elif key == "pixel_spacing":
            normalized[key] = parse_pixel_spacing(text)
        elif key == "run":
            normalized[key] = clean_optional_entity(text, "run")
        elif key == "part":
            normalized[key] = clean_optional_entity(text, "part")
        elif key in {"acq", "rec"}:
            normalized[key] = clean_label(text, key, optional=True)
        else:
            normalized[key] = text

    if modality == "MRI":
        allowed = set(MRI_OPTIONAL_MAP) | {"acq", "rec", "run", "part"}
    else:
        allowed = set(CT_OPTIONAL_MAP) | {"acq", "rec", "run"}

    invalid = sorted(set(normalized) - allowed)
    if invalid:
        raise ValueError(
            f"Unsupported optional metadata field(s) for {modality}: "
            + ", ".join(invalid)
        )

    return normalized


def validate_record(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    path = Path(str(raw.get("nifti_path", "")).strip()).expanduser().resolve()
    if not path.is_file() or not path.name.endswith((".nii", ".nii.gz")):
        raise ValueError(f"Record {index} has an invalid NIfTI path: {path}")

    modality = str(raw.get("imaging_modality", "")).strip()
    if modality not in {"MRI", "CT"}:
        raise ValueError(
            f"Record {index} has an unsupported imaging modality: {modality}"
        )

    raw_purposes = raw.get("imaging_purpose", [])
    if not isinstance(raw_purposes, list) or not raw_purposes:
        raise ValueError(
            f"Record {index} requires at least one purpose of imaging."
        )

    purposes = [str(value).strip() for value in raw_purposes]
    invalid_purposes = [
        value for value in purposes if value not in IMAGING_PURPOSE_OPTIONS
    ]
    if invalid_purposes:
        raise ValueError(
            f"Record {index} has invalid imaging purpose: {invalid_purposes[0]}"
        )

    timing = str(raw.get("timing_relative_to_surgery", "")).strip()
    if timing not in SURGERY_TIMING_OPTIONS:
        raise ValueError(
            f"Record {index} has invalid timing relative to surgery: {timing!r}"
        )

    record: Dict[str, Any] = {
        "nifti_path": path,
        "project": clean_project(str(raw.get("project", ""))),
        "participant": clean_label(
            str(raw.get("participant_id", "")),
            "participant_id",
        ),
        "session": clean_label(
            str(raw.get("session_id", "")),
            "session_id",
            optional=True,
        ),
        "cocanot_patient_id": str(
            raw.get("cocanot_patient_id", "")
        ).strip(),
        "surgery_id": str(raw.get("surgery_id", "")).strip(),
        "image_id": str(raw.get("image_id", "")).strip(),
        "imaging_modality": modality,
        "imaging_purpose": purposes,
        "timing_relative_to_surgery": timing,
        "comments": str(raw.get("comments", "")).strip(),
    }

    for key in ("cocanot_patient_id", "surgery_id", "image_id"):
        if not record[key]:
            raise ValueError(f"Record {index} is missing required CoCANoT field: {key}")

    optional = normalize_optional_metadata(
        raw.get("optional_metadata", {}),
        modality=modality,
    )
    record["optional_metadata"] = optional

    if modality == "MRI":
        sequence = str(raw.get("mri_sequence", "")).strip()
        if sequence not in MRI_SEQUENCE_MAP:
            raise ValueError(
                f"Record {index} has an unsupported MRI sequence: {sequence}"
            )

        expected_datatype, expected_suffix = MRI_SEQUENCE_MAP[sequence]
        datatype = str(raw.get("datatype", "")).strip()
        suffix = str(raw.get("suffix", "")).strip()

        if datatype != expected_datatype or suffix != expected_suffix:
            raise ValueError(
                f"Record {index} MRI sequence {sequence!r} must map to "
                f"{expected_datatype}/{expected_suffix}."
            )

        if sequence == "SWI":
            optional.setdefault("acq", "swi")

        record["mri_sequence"] = sequence
        record["datatype"] = datatype
        record["suffix"] = suffix

        if sequence == "DWI":
            base = strip_nifti_suffix(path)
            missing = [
                ext
                for ext in (".bval", ".bvec")
                if not path.with_name(f"{base}{ext}").exists()
            ]
            if missing:
                raise ValueError(
                    f"Record {index} is DWI but is missing: {', '.join(missing)}"
                )

    else:
        record["mri_sequence"] = ""
        record["datatype"] = "ct"
        record["suffix"] = "ct"

    return record


def build_bids_base(
    record: Dict[str, Any],
    run_override: Optional[int] = None,
) -> str:
    parts = [f"sub-{record['participant']}"]

    if record["session"]:
        parts.append(f"ses-{record['session']}")

    optional = record["optional_metadata"]

    acq = str(optional.get("acq", "")).strip()
    rec = str(optional.get("rec", "")).strip()
    run = str(optional.get("run", "")).strip()
    part = str(optional.get("part", "")).strip()

    if acq:
        parts.append(f"acq-{acq}")
    if rec:
        parts.append(f"rec-{rec}")

    if run_override is not None:
        parts.append(f"run-{run_override:02d}")
    elif run:
        parts.append(f"run-{run}")

    if record["imaging_modality"] == "MRI" and part:
        parts.append(f"part-{part}")

    parts.append(record["suffix"])
    return "_".join(parts)


def choose_output_base(
    data_dir: Path,
    record: Dict[str, Any],
    extension: str,
    overwrite: bool,
) -> str:
    base = build_bids_base(record)

    if overwrite or not (data_dir / f"{base}{extension}").exists():
        return base

    existing_run = str(
        record["optional_metadata"].get("run", "")
    ).strip()
    start = int(existing_run or 1) + 1

    for run in range(start, 10000):
        candidate = build_bids_base(
            record,
            run_override=run,
        )
        if not (data_dir / f"{candidate}{extension}").exists():
            return candidate

    raise ValueError(
        f"Could not find an available run number for {base}"
    )


def source_sidecar_metadata(path: Path) -> Dict[str, Any]:
    source_json = matching_json_path(path)
    if source_json is None:
        return {}

    sidecar = load_json(source_json)

    # The scrubber nests selected acquisition metadata. Lift those fields back
    # to the top level for BIDS-compatible MRI sidecars.
    acquisition = sidecar.pop("acquisition", None)
    if isinstance(acquisition, dict):
        for key, value in acquisition.items():
            sidecar.setdefault(key, value)

    # Internal QC metadata can remain in derivatives/logs but is not needed in
    # the final raw-style organization sidecar.
    for key in (
        "SourceFile",
        "PHIScrubbed",
        "PHIScrubbedBy",
        "imaging_file",
        "imaging_session",
    ):
        sidecar.pop(key, None)

    return sidecar


def add_optional_fields(
    sidecar: Dict[str, Any],
    record: Dict[str, Any],
) -> None:
    optional = record["optional_metadata"]

    mapping = (
        MRI_OPTIONAL_MAP
        if record["imaging_modality"] == "MRI"
        else CT_OPTIONAL_MAP
    )

    for source_key, output_key in mapping.items():
        if source_key in optional:
            sidecar[output_key] = optional[source_key]


def write_participants(
    project_dir: Path,
    participant_ids: list[str],
) -> None:
    path = project_dir / "participants.tsv"
    existing: set[str] = set()

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines[1:]:
            value = line.strip()
            if value:
                existing.add(value)

    existing.update(
        f"sub-{participant}"
        for participant in participant_ids
    )

    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("participant_id\n")
        for participant in sorted(existing):
            handle.write(f"{participant}\n")


def output_data_dir(
    output_root: Path,
    record: Dict[str, Any],
) -> Path:
    project_dir = output_root / record["project"]
    data_dir = project_dir / f"sub-{record['participant']}"

    if record["session"]:
        data_dir /= f"ses-{record['session']}"

    data_dir /= record["datatype"]
    return data_dir


def copy_record(
    record: Dict[str, Any],
    output_root: Path,
    overwrite: bool,
) -> Path:
    data_dir = output_data_dir(output_root, record)
    data_dir.mkdir(parents=True, exist_ok=True)

    path = record["nifti_path"]
    extension = nifti_extension(path)
    base = choose_output_base(
        data_dir,
        record,
        extension,
        overwrite,
    )

    output_nifti = data_dir / f"{base}{extension}"
    output_json = data_dir / f"{base}.json"

    if overwrite:
        output_nifti.unlink(missing_ok=True)
        output_json.unlink(missing_ok=True)
        for ext in (".bval", ".bvec"):
            (data_dir / f"{base}{ext}").unlink(missing_ok=True)

    shutil.copy2(path, output_nifti)

    sidecar = source_sidecar_metadata(path)
    add_optional_fields(sidecar, record)

    sidecar["Defaced"] = True
    sidecar["DefacingSoftware"] = PYDEFACE_NAME
    sidecar["DefacingSoftwareURL"] = PYDEFACE_URL

    # CoCANoT extension metadata.
    sidecar["CoCANoTPatientID"] = record["cocanot_patient_id"]
    sidecar["SurgeryID"] = record["surgery_id"]
    sidecar["ImageID"] = record["image_id"]
    sidecar["ImagingModality"] = record["imaging_modality"]
    if record["imaging_modality"] == "MRI":
        sidecar["MRISequence"] = record["mri_sequence"]
    sidecar["PurposeOfImaging"] = record["imaging_purpose"]
    sidecar["TimingRelativeToSurgery"] = record[
        "timing_relative_to_surgery"
    ]
    if record["comments"]:
        sidecar["Comments"] = record["comments"]

    if record["imaging_modality"] == "CT":
        sidecar["CoCANoTExtension"] = (
            "CT raw-data organization is a CoCANoT extension and is not "
            "a core BIDS 1.11.1 datatype."
        )

    write_json(output_json, sidecar)

    for extra in matching_extra_sidecars(path):
        shutil.copy2(
            extra,
            data_dir / f"{base}{extra.suffix}",
        )

    return output_nifti


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert approved NIfTI files into CoCANoT MRI / CT dataset layouts."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    manifest = load_json(
        args.manifest.expanduser().resolve()
    )
    output_root = args.output_dir.expanduser().resolve()

    raw_records = manifest.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise SystemExit(
            "Manifest contains no selected imaging records."
        )

    records = [
        validate_record(record, index)
        for index, record in enumerate(raw_records, start=1)
    ]

    output_root.mkdir(parents=True, exist_ok=True)

    by_project: dict[str, list[str]] = {}

    for index, record in enumerate(records, start=1):
        project_dir = output_root / record["project"]

        write_json(
            project_dir / "dataset_description.json",
            {
                "Name": record["project"],
                "BIDSVersion": str(
                    manifest.get("bids_version")
                    or SUPPORTED_BIDS_VERSION
                ),
                "DatasetType": "raw",
            },
        )

        print(
            f"[{index}/{len(records)}] "
            f"{record['nifti_path']} -> "
            f"{record['project']} / "
            f"{record['datatype']} / "
            f"{record['suffix']}"
        )

        output = copy_record(
            record,
            output_root,
            args.overwrite,
        )

        by_project.setdefault(
            record["project"],
            [],
        ).append(record["participant"])

        print(f"    -> {output}")

    for project, participants in by_project.items():
        write_participants(
            output_root / project,
            participants,
        )

    print("\nImaging MRI / CT conversion complete.")
    print(f"Converted files: {len(records)}")
    print(f"Output folder: {output_root}")
    print(
        "Note: MRI follows BIDS 1.11.1 naming for the supported profiles. "
        "CT is stored as a documented CoCANoT extension."
    )


if __name__ == "__main__":
    main()
