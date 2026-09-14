#!/usr/bin/env python3
"""Convert dashboard-approved NIfTI files into CoCANoT MRI / CT dataset layouts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from MetadataPipeline.storage.data_link_store import PatientDataLinkStore
from MetadataPipeline.storage.record_repository import MetadataRepository
from MetadataPipeline.validation import MetadataValidator, load_dictionary

SUPPORTED_BIDS_VERSION = "1.11.1"
METADATA_DICTIONARY = (
    PROJECT_ROOT
    / "MetadataPipeline"
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)

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

MRI_SEQUENCE_FIELDS = (
    "MRI Sequence(s) (if applicable)",
    "MRI Sequence(s) - if MRI (multiselect)",
)




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




def imaging_sequence_value(
    metadata: Dict[str, Any],
) -> str:
    """Return the one MRI sequence assigned to this image."""

    for field_name in MRI_SEQUENCE_FIELDS:
        value = metadata.get(
            field_name
        )

        if type(value) is list:
            selected = [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]

            if len(selected) == 1:
                return selected[0]

            if selected:
                return ""

            continue

        text = str(
            value
            or ""
        ).strip()

        if text:
            return text

    return ""


def load_metadata_validator() -> MetadataValidator:
    """Load the active CoCANoT dictionary and build the shared validator."""
    dictionary = load_dictionary(
        METADATA_DICTIONARY
    )
    return MetadataValidator(
        dictionary
    )


def validate_cocanot_metadata(
    raw: Dict[str, Any],
    index: int,
    validator: MetadataValidator,
) -> Dict[str, Any]:
    metadata = raw.get("cocanot_metadata")

    if type(metadata) is not dict:
        raise ValueError(
            f"Record {index} is missing the cocanot_metadata object."
        )

    validation = validator.validate_record(
        "Imaging",
        metadata,
    )

    if not validation["passes_automatic_validation"]:
        problems = [
            result["message"]
            for result in validation["results"]
            if result["status"] in {
                "invalid",
                "missing_required",
            }
        ]
        raise ValueError(
            f"Record {index} has invalid CoCANoT metadata: "
            + "; ".join(problems[:5])
        )

    if validation["requires_manual_review"] and not raw.get(
        "metadata_confirmed"
    ):
        raise ValueError(
            f"Record {index} contains free-text metadata that has not "
            "been manually confirmed."
        )

    return metadata

def validate_record(
    raw: Dict[str, Any],
    index: int,
    metadata_validator: MetadataValidator,
) -> Dict[str, Any]:
    path = Path(
        str(raw.get("nifti_path", "")).strip()
    ).expanduser().resolve()

    if not path.is_file() or not path.name.endswith(
        (".nii", ".nii.gz")
    ):
        raise ValueError(
            f"Record {index} has an invalid NIfTI path: {path}"
        )

    metadata = validate_cocanot_metadata(
        raw,
        index,
        metadata_validator,
    )

    modality = str(
        metadata.get("Imaging Modality") or ""
    ).strip()

    record: Dict[str, Any] = {
        "nifti_path": path,
        "project": clean_project(
            str(raw.get("project", ""))
        ),
        "project_description": str(
            raw.get(
                "project_description",
                "",
            )
        ).strip(),
        "participant": clean_label(
            str(raw.get("participant_id", "")),
            "participant_id",
        ),
        "session": clean_label(
            str(raw.get("session_id", "")),
            "session_id",
            optional=True,
        ),
        "cocanot_metadata": metadata,
        "imaging_modality": modality,
        "bids_entities": {},
        "defacing_source": str(
            raw.get(
                "defacing_source",
                ""
            )
            or ""
        ).strip(),
    }

    if modality == "MRI":
        sequence = imaging_sequence_value(
            metadata
        )

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
            record["bids_entities"]["acq"] = "swi"

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
                    f"Record {index} is DWI but is missing: "
                    + ", ".join(missing)
                )

    elif modality == "CT":
        record["mri_sequence"] = ""
        record["datatype"] = "ct"
        record["suffix"] = "ct"

    else:
        raise ValueError(
            f"Record {index} has an unsupported imaging modality: {modality}"
        )

    return record


def build_bids_base(
    record: Dict[str, Any],
    run_override: Optional[int] = None,
) -> str:
    parts = [f"sub-{record['participant']}"]

    if record["session"]:
        parts.append(f"ses-{record['session']}")

    acq = str(
        record["bids_entities"].get("acq", "")
    ).strip()

    if acq:
        parts.append(f"acq-{acq}")

    if run_override is not None:
        parts.append(f"run-{run_override:02d}")

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

    for run in range(2, 10000):
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

    sidecar["Defaced"] = True

    if record.get(
        "defacing_source"
    ) == "external":
        sidecar[
            "DefacingSoftware"
        ] = "External defacing software"
        sidecar.pop(
            "DefacingSoftwareURL",
            None,
        )
    else:
        sidecar[
            "DefacingSoftware"
        ] = PYDEFACE_NAME
        sidecar[
            "DefacingSoftwareURL"
        ] = PYDEFACE_URL

    # CoCANoT metadata validated against the active dictionary.
    metadata = record["cocanot_metadata"]

    sidecar["CoCANoTSiteID"] = record["site_id"]
    sidecar["CoCANoTPatientID"] = metadata["CoCANoT Patient ID"]
    sidecar["ClinicalAssessmentID"] = metadata["Clinical Assessment ID"]
    sidecar["ImageID"] = metadata["Image ID"]

    surgery_id = str(metadata.get("Surgery ID") or "").strip()
    if surgery_id:
        sidecar["SurgeryID"] = surgery_id

    sidecar["ImagingModality"] = metadata["Imaging Modality"]

    if record["imaging_modality"] == "MRI":
        sidecar["MRISequence"] = record[
            "mri_sequence"
        ]

    sidecar["PurposeOfImaging"] = metadata[
        "Purpose of Imaging (multiselect)"
    ]

    other_purpose = str(
        metadata.get(
            "Other Purpose of Imaging (if applicable; free text)"
        )
        or ""
    ).strip()
    if other_purpose:
        sidecar["OtherPurposeOfImaging"] = other_purpose

    sidecar["TimingRelativeToSurgery"] = metadata[
        "Timing Relative to Surgery"
    ]

    sidecar["ImagingFindings"] = metadata[
        "Imaging Findings (multiselect)"
    ]

    other_findings = str(
        metadata.get(
            "Other Imaging Findings (if applicable; free text)"
        )
        or ""
    ).strip()
    if other_findings:
        sidecar["OtherImagingFindings"] = other_findings

    comments = str(
        metadata.get("Comments (free text)")
        or ""
    ).strip()
    if comments:
        sidecar["Comments"] = comments

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

    site_id = str(
        manifest.get("site_id") or ""
    ).strip()

    if not site_id:
        raise SystemExit(
            "Manifest is missing the CoCANoT Site ID."
        )

    metadata_validator = load_metadata_validator()
    metadata_repository = MetadataRepository()
    data_links = PatientDataLinkStore()

    records = [
        validate_record(
            record,
            index,
            metadata_validator,
        )
        for index, record in enumerate(
            raw_records,
            start=1,
        )
    ]

    for record in records:
        record["site_id"] = site_id

    output_root.mkdir(parents=True, exist_ok=True)

    by_project: dict[str, list[str]] = {}
    project_descriptions: dict[str, str] = {}

    for record in records:
        project = record["project"]
        description = record[
            "project_description"
        ]

        current = project_descriptions.get(
            project
        )

        if (
            current is not None
            and current
            and description
            and current != description
        ):
            raise SystemExit(
                f"Project {project!r} has more than one Project Description."
            )

        if description:
            project_descriptions[
                project
            ] = description
        elif current is None:
            project_descriptions[
                project
            ] = ""

    for index, record in enumerate(records, start=1):
        project_dir = output_root / record["project"]

        dataset_description = {
            "Name": record["project"],
            "BIDSVersion": str(
                manifest.get("bids_version")
                or SUPPORTED_BIDS_VERSION
            ),
            "DatasetType": "raw",
        }

        project_description = (
            project_descriptions.get(
                record["project"],
                "",
            )
        )

        if project_description:
            dataset_description[
                "Description"
            ] = project_description

        write_json(
            project_dir / "dataset_description.json",
            dataset_description,
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

        output_json = output.with_name(
            f"{strip_nifti_suffix(output)}.json"
        )
        metadata = record[
            "cocanot_metadata"
        ]

        link_context = {
            "project": record[
                "project"
            ],
            "project_description": record[
                "project_description"
            ],
            "session_id": record[
                "session"
            ],
            "bids_data_path": str(
                output.resolve()
            ),
            "bids_sidecar_path": str(
                output_json.resolve()
            ),
            "defacing_source": record.get(
                "defacing_source",
                "",
            ),
        }

        metadata_repository.save_record(
            record["site_id"],
            "Imaging",
            metadata,
            source="imaging_pipeline",
            context=link_context,
        )

        data_links.save_link(
            record["site_id"],
            metadata[
                "CoCANoT Patient ID"
            ],
            "Imaging",
            metadata[
                "Image ID"
            ],
            link_context,
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
