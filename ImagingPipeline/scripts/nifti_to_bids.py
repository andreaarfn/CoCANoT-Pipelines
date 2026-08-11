#!/usr/bin/env python3
"""Convert dashboard-approved NIfTI files into a BIDS-style raw dataset layout."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

SUPPORTED_BIDS_VERSION = "1.11.1"

BIDS_MODALITY_DATATYPES = {
    "MRI": ("anat", "func", "dwi", "fmap", "perf"),
    "PET": ("pet",),
    "meeg": ("eeg", "meg", "ieeg"),
    "behavioral": ("beh",),
    "microscopy": ("micr",),
    "NIRS": ("nirs",),
    "motion": ("motion",),
    "MRS": ("mrs",),
}

BIDS_DATATYPE_SUFFIXES = {
    "anat": {"T1w", "T2w", "FLAIR", "PDw", "T2starw", "CT", "MEGRE", "MESE", "VFA", "IRT1", "MP2RAGE", "MPM", "MTS", "MTR"},
    "func": {"bold", "cbv", "sbref", "phase"},
    "dwi": {"dwi", "sbref"},
    "fmap": {"epi", "m0scan", "TB1DAM", "TB1EPI", "RB1COR", "TB1AFI", "TB1RFM", "TB1TFL", "TB1SRGE", "RB1map", "TB1map"},
    "perf": {"asl", "m0scan", "noRF"},
    "pet": {"pet"}, "eeg": {"eeg"}, "meg": {"meg"}, "ieeg": {"ieeg"},
    "beh": {"beh"}, "micr": {"micr"}, "nirs": {"nirs"}, "motion": {"motion"},
    "mrs": {"mrsi", "mrsref", "svs", "unloc"},
}

ENTITY_ORDER = {
    "anat": ("task", "acq", "ce", "rec", "run", "echo", "flip", "inv", "mt", "part", "chunk"),
    "func": ("task", "acq", "ce", "rec", "dir", "run", "echo", "part", "chunk"),
    "dwi": ("acq", "rec", "dir", "run", "part", "chunk"),
    "fmap": ("acq", "ce", "rec", "dir", "run", "echo", "flip", "inv", "part", "chunk"),
    "perf": ("acq", "rec", "dir", "run", "mod", "echo", "part"),
    "pet": ("task", "trc", "rec", "run"),
    "eeg": ("task", "acq", "run", "space", "recording"),
    "meg": ("task", "acq", "run", "proc", "split", "space", "recording"),
    "ieeg": ("task", "acq", "run", "space", "recording"),
    "beh": ("task", "acq", "run", "recording"),
    "micr": ("sample", "acq", "stain", "run", "chunk"),
    "nirs": ("task", "acq", "run", "space", "recording"),
    "motion": ("task", "tracksys", "acq", "run", "recording"),
    "mrs": ("task", "acq", "nuc", "voi", "rec", "run", "echo", "inv"),
}

REQUIRED_TASK_DATATYPES = {"func", "eeg", "meg", "ieeg", "beh", "nirs", "motion"}
REQUIRED_FIELDS = {"micr": ("sample",), "motion": ("tracksys",)}
INDEX_FIELDS = {"run", "echo", "flip", "inv", "chunk", "split"}
ENUM_FIELDS = {"part": {"mag", "phase", "real", "imag"}, "mt": {"on", "off"}}

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

PYDEFACE_NAME = "PyDeface"
PYDEFACE_URL = "https://github.com/poldracklab/pydeface"


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
    return [candidate for ext in (".bval", ".bvec") if (candidate := path.with_name(f"{base}{ext}")).exists()]


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
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def clean_project(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f/\\]+", "-", value.strip()).strip(" .-")
    if not cleaned:
        raise ValueError("Project must contain a usable folder name.")
    return cleaned


def clean_label(value: str, field: str, *, optional: bool = False) -> str:
    text = str(value).strip()
    if not text and optional:
        return ""
    prefixes = {"participant_id": "sub-", "session_id": "ses-", "task": "task-"}
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
            raise ValueError(f"{field} must be one of: {', '.join(sorted(ENUM_FIELDS[field]))}")
        return text
    if not re.fullmatch(r"[A-Za-z0-9+]+", text):
        raise ValueError(f"{field} may contain only letters, numbers, and +.")
    return text


def validate_record(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    path = Path(str(raw.get("nifti_path", "")).strip()).expanduser().resolve()
    if not path.is_file() or not path.name.endswith((".nii", ".nii.gz")):
        raise ValueError(f"Record {index} has an invalid NIfTI path: {path}")

    modality = str(raw.get("modality", "")).strip()
    datatype = str(raw.get("datatype", "")).strip()
    suffix = str(raw.get("suffix", "")).strip()
    if modality not in BIDS_MODALITY_DATATYPES:
        raise ValueError(f"Record {index} has an unsupported modality: {modality}")
    if datatype not in BIDS_MODALITY_DATATYPES[modality]:
        raise ValueError(f"Record {index} datatype {datatype!r} does not match modality {modality!r}.")
    if suffix not in BIDS_DATATYPE_SUFFIXES[datatype]:
        raise ValueError(f"Record {index} suffix {suffix!r} is not valid for {datatype!r}.")

    record: Dict[str, Any] = {
        "nifti_path": path,
        "project": clean_project(str(raw.get("project", ""))),
        "participant": clean_label(str(raw.get("participant_id", "")), "participant_id"),
        "session": clean_label(str(raw.get("session_id", "")), "session_id", optional=True),
        "modality": modality,
        "datatype": datatype,
        "suffix": suffix,
    }
    for field in ENTITY_ORDER[datatype]:
        record[field] = clean_label(str(raw.get(field, "")), field, optional=True)

    if datatype in REQUIRED_TASK_DATATYPES and not record.get("task"):
        raise ValueError(f"Record {index} requires a task for datatype {datatype}.")
    for field in REQUIRED_FIELDS.get(datatype, ()):
        if not record.get(field):
            raise ValueError(f"Record {index} requires {field} for datatype {datatype}.")

    raw_purposes = raw.get("imaging_purpose", [])
    if not isinstance(raw_purposes, list) or not raw_purposes:
        raise ValueError(f"Record {index} requires at least one purpose of imaging.")
    purposes = [str(value).strip() for value in raw_purposes]
    invalid_purposes = [value for value in purposes if value not in IMAGING_PURPOSE_OPTIONS]
    if invalid_purposes:
        raise ValueError(f"Record {index} has invalid imaging purpose: {invalid_purposes[0]}")
    timing = str(raw.get("timing_relative_to_surgery", "")).strip()
    if timing not in SURGERY_TIMING_OPTIONS:
        raise ValueError(f"Record {index} has invalid timing relative to surgery: {timing!r}")
    record["imaging_purpose"] = purposes
    record["timing_relative_to_surgery"] = timing

    if datatype == "dwi" and suffix == "dwi":
        missing = [ext for ext in (".bval", ".bvec") if not path.with_name(f"{strip_nifti_suffix(path)}{ext}").exists()]
        if missing:
            raise ValueError(f"Record {index} is DWI but is missing: {', '.join(missing)}")
    return record


def build_bids_base(record: Dict[str, Any], run_override: Optional[int] = None) -> str:
    parts = [f"sub-{record['participant']}"]
    if record["session"]:
        parts.append(f"ses-{record['session']}")
    for field in ENTITY_ORDER[record["datatype"]]:
        value = record.get(field, "")
        if field == "run" and run_override is not None:
            value = f"{run_override:02d}"
        if value:
            parts.append(f"{field}-{value}")
    parts.append(record["suffix"])
    return "_".join(parts)


def choose_output_base(data_dir: Path, record: Dict[str, Any], extension: str, overwrite: bool) -> str:
    base = build_bids_base(record)
    if overwrite or not (data_dir / f"{base}{extension}").exists():
        return base
    start = int(record.get("run") or 1) + 1
    for run in range(start, 10000):
        candidate = build_bids_base(record, run_override=run)
        if not (data_dir / f"{candidate}{extension}").exists():
            return candidate
    raise ValueError(f"Could not find an available run number for {base}")


def write_participants(project_dir: Path, participants: list[str]) -> None:
    path = project_dir / "participants.tsv"
    existing: set[str] = set()
    if path.exists():
        existing.update(line.strip() for line in path.read_text(encoding="utf-8").splitlines()[1:] if line.strip())
    existing.update(f"sub-{participant}" for participant in participants)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write("participant_id\n")
        for participant in sorted(existing):
            file.write(f"{participant}\n")


def copy_record(record: Dict[str, Any], output_root: Path, overwrite: bool) -> Path:
    project_dir = output_root / record["project"]
    data_dir = project_dir / f"sub-{record['participant']}"
    if record["session"]:
        data_dir /= f"ses-{record['session']}"
    data_dir /= record["datatype"]
    data_dir.mkdir(parents=True, exist_ok=True)

    path: Path = record["nifti_path"]
    extension = nifti_extension(path)
    base = choose_output_base(data_dir, record, extension, overwrite)
    output_nifti = data_dir / f"{base}{extension}"
    output_json = data_dir / f"{base}.json"

    if overwrite:
        output_nifti.unlink(missing_ok=True)
        output_json.unlink(missing_ok=True)
        for ext in (".bval", ".bvec"):
            (data_dir / f"{base}{ext}").unlink(missing_ok=True)

    shutil.copy2(path, output_nifti)
    source_json = matching_json_path(path)
    sidecar: Dict[str, Any] = load_json(source_json) if source_json else {}

    # Remove pipeline bookkeeping and stale task metadata from the source sidecar.
    for key in ("SourceFile", "PHIScrubbed", "PHIScrubbedBy", "TaskName"):
        sidecar.pop(key, None)

    # TaskName is required for task-based datatypes, but should not leak into anat, dwi, etc.
    if record["datatype"] in REQUIRED_TASK_DATATYPES and record.get("task"):
        sidecar["TaskName"] = record["task"]

    sidecar["Defaced"] = True
    sidecar["DefacingSoftware"] = PYDEFACE_NAME
    sidecar["DefacingSoftwareURL"] = PYDEFACE_URL
    sidecar["PurposeOfImaging"] = record["imaging_purpose"]
    sidecar["TimingRelativeToSurgery"] = record["timing_relative_to_surgery"]
    write_json(output_json, sidecar)
    for extra in matching_extra_sidecars(path):
        shutil.copy2(extra, data_dir / f"{base}{extra.suffix}")
    return output_nifti


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert approved NIfTI files into a BIDS-style raw layout.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_json(args.manifest.expanduser().resolve())
    output_root = args.output_dir.expanduser().resolve()
    raw_records = manifest.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise SystemExit("Manifest contains no selected imaging records.")
    records = [validate_record(record, index) for index, record in enumerate(raw_records, start=1)]
    output_root.mkdir(parents=True, exist_ok=True)

    by_project: dict[str, list[str]] = {}
    for index, record in enumerate(records, start=1):
        project_dir = output_root / record["project"]
        write_json(project_dir / "dataset_description.json", {
            "Name": record["project"],
            "BIDSVersion": str(manifest.get("bids_version") or SUPPORTED_BIDS_VERSION),
            "DatasetType": "raw",
        })
        print(f"[{index}/{len(records)}] {record['nifti_path']} -> {record['project']} / {record['datatype']} / {record['suffix']}")
        output = copy_record(record, output_root, args.overwrite)
        by_project.setdefault(record["project"], []).append(record["participant"])
        print(f"    -> {output}")

    for project, participants in by_project.items():
        write_participants(output_root / project, participants)
    print("\nBIDS imaging conversion complete.")
    print(f"Converted files: {len(records)}")
    print(f"Output folder: {output_root}")


if __name__ == "__main__":
    main()
