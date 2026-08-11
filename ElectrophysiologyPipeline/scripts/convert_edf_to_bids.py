#!/usr/bin/env python3
"""
Convert dashboard-selected, scrubbed EDF files into BIDS datasets.

Each record supplies project, subject, optional session, task, recording
modality, structured recording context, and device metadata.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import pyedflib
except ImportError as exc:
    raise SystemExit(
        "pyedflib is required. Install it with:\n\n"
        "    python -m pip install pyedflib\n"
    ) from exc


DEFAULT_BIDS_VERSION = "1.11.1"
VALID_DATATYPES = {"eeg", "ieeg", "meg"}
VALID_RECORDING_MODALITIES = {
    "Scalp EEG": "eeg",
    "Stereo EEG (SEEG)": "ieeg",
    "Subdural Grid/Strip EEG (ECoG)": "ieeg",
    "Magnetoencephalography (MEG)": "meg",
}


def bids_safe(value: str, field_name: str, optional: bool = False) -> str:
    cleaned = str(value).strip()
    if optional and not cleaned:
        return ""
    for prefix in ("sub-", "ses-", "task-", "run-", "site-"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    cleaned = re.sub(r"[^A-Za-z0-9+]+", "", cleaned)
    if not cleaned:
        raise ValueError(f"{field_name} must contain at least one letter, number, or +.")
    return cleaned


def folder_safe(value: str, field_name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        raise ValueError(f"{field_name} cannot be blank.")
    return cleaned


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


def write_tsv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            values: List[str] = []
            for column in columns:
                value = row.get(column, "n/a")
                if value in (None, ""):
                    value = "n/a"
                values.append(str(value).replace("\t", " ").replace("\n", " "))
            handle.write("\t".join(values) + "\n")


def read_edf_metadata(edf_path: Path) -> Dict[str, Any]:
    reader = pyedflib.EdfReader(str(edf_path))
    try:
        channel_count = reader.signals_in_file
        sample_frequencies: List[Optional[float]] = []
        for index in range(channel_count):
            try:
                sample_frequencies.append(float(reader.getSampleFrequency(index)))
            except Exception:
                sample_frequencies.append(None)
        try:
            duration_seconds: Any = float(reader.file_duration)
        except Exception:
            duration_seconds = "n/a"
        return {
            "channel_count": channel_count,
            "channel_labels": list(reader.getSignalLabels()),
            "signal_headers": list(reader.getSignalHeaders()),
            "sample_frequencies": sample_frequencies,
            "duration_seconds": duration_seconds,
        }
    finally:
        reader.close()


def exact_auxiliary_channel_type(label: str) -> Optional[str]:
    normalized = re.sub(r"[\s_-]+", "", str(label).upper())
    return {
        "ECG": "ECG", "EKG": "ECG", "ECG1": "ECG", "EKG1": "ECG",
        "EOG": "EOG", "LOC": "EOG", "ROC": "EOG", "HEOG": "EOG", "VEOG": "EOG",
        "EMG": "EMG", "EMG1": "EMG",
        "TRIG": "TRIG", "TRIGGER": "TRIG", "STATUS": "TRIG",
        "EVENT": "TRIG", "MARKER": "TRIG",
    }.get(normalized)


def channel_type_for(label: str, recording_modality: str) -> str:
    auxiliary = exact_auxiliary_channel_type(label)
    if auxiliary is not None:
        return auxiliary
    return {
        "Scalp EEG": "EEG",
        "Stereo EEG (SEEG)": "SEEG",
        "Subdural Grid/Strip EEG (ECoG)": "ECOG",
        "Magnetoencephalography (MEG)": "MEG",
    }[recording_modality]


def common_sampling_frequency(values: Iterable[Optional[float]]) -> Any:
    present = sorted({value for value in values if value is not None})
    return present[0] if len(present) == 1 else "n/a"


def find_nested_value(payload: Any, keys: set[str]) -> Any:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in keys and value not in (None, ""):
                return value
        for value in payload.values():
            found = find_nested_value(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_nested_value(value, keys)
            if found not in (None, ""):
                return found
    return None


def read_participant_fields(sidecar_path: Optional[Path]) -> Dict[str, Any]:
    if sidecar_path is None or not sidecar_path.exists():
        return {"sex": "n/a"}
    payload = load_json(sidecar_path)
    sex = find_nested_value(payload, {"sex", "gender", "participant_sex"})
    return {"sex": sex if sex not in (None, "") else "n/a"}


def make_channels_rows(metadata: Dict[str, Any], record: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, label in enumerate(metadata["channel_labels"]):
        header = metadata["signal_headers"][index]
        rows.append(
            {
                "name": label,
                "type": channel_type_for(label, record["recording_modality"]),
                "units": header.get("dimension", "n/a") or "n/a",
                "low_cutoff": "n/a",
                "high_cutoff": "n/a",
                "reference": "n/a",
                "group": "n/a",
                "sampling_frequency": metadata["sample_frequencies"][index],
                "notch": "n/a",
                "status": "n/a",
                "status_description": "n/a",
            }
        )
    return rows


def make_recording_sidecar(metadata: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    sidecar: Dict[str, Any] = {
        "TaskName": record["task"],
        "TaskDescription": record["task_description"],
        "Instructions": "n/a",
        "Manufacturer": record["manufacturer"],
        "ManufacturersModelName": record["model_name"],
        "SamplingFrequency": common_sampling_frequency(metadata["sample_frequencies"]),
        "RecordingDuration": metadata["duration_seconds"],
        "ChannelCount": metadata["channel_count"],
        "ChannelTypeDescription": record["channel_type_description"],
        "RecordingModality": record["recording_modality"],
        "Purpose": record["purpose"],
        "TimingRelativeToSurgery": record["timing_relative_to_surgery"],
    }

    seizure_count = record["number_of_seizures_captured"]
    if seizure_count is not None:
        sidecar["NumberOfSeizuresCaptured"] = seizure_count
    if seizure_count and seizure_count > 0:
        sidecar["PrimarySeizureOnsetLocalization"] = record[
            "primary_seizure_onset_localization"
        ]
    if record["comments"]:
        sidecar["Comments"] = record["comments"]
    return sidecar


def ensure_dataset_files(
    dataset_dir: Path,
    dataset_name: str,
    dataset_description: str,
    bids_version: str,
) -> None:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        dataset_dir / "dataset_description.json",
        {
            "Name": dataset_name,
            "Description": dataset_description,
            "BIDSVersion": bids_version,
            "DatasetType": "raw",
        },
    )
    readme = dataset_dir / "README"
    if not readme.exists():
        readme.write_text(f"{dataset_name}\n\n{dataset_description}\n", encoding="utf-8")


def read_existing_tsv(path: Path, key: str) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return result
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return result
    columns = lines[0].split("\t")
    for line in lines[1:]:
        if not line.strip():
            continue
        row = dict(zip(columns, line.split("\t")))
        if row.get(key):
            result[row[key]] = row
    return result


def update_participants(dataset_dir: Path, participant_rows: List[Dict[str, Any]]) -> None:
    participants_path = dataset_dir / "participants.tsv"
    existing = read_existing_tsv(participants_path, "participant_id")
    for row in participant_rows:
        existing[row["participant_id"]] = row

    write_tsv(
        participants_path,
        [existing[key] for key in sorted(existing)],
        ["participant_id", "sex", "site"],
    )
    write_json(
        dataset_dir / "participants.json",
        {
            "participant_id": {"Description": "BIDS participant identifier."},
            "sex": {"Description": "Sex when available."},
            "site": {"Description": "User-assigned de-identified site code."},
        },
    )


def next_run_number(data_dir: Path, prefix: str) -> int:
    pattern = re.compile(re.escape(prefix) + r"_run-(\d+)_")
    used: List[int] = []
    for path in data_dir.glob(f"{prefix}_run-*.*"):
        match = pattern.search(path.name)
        if match:
            used.append(int(match.group(1)))
    return max(used, default=0) + 1


def required_text(raw: Dict[str, Any], key: str, index: int) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ValueError(f"Manifest record {index} is missing: {key}")
    return value


def required_list(raw: Dict[str, Any], key: str, index: int) -> List[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Manifest record {index} is missing: {key}")
    return [str(item).strip() for item in value if str(item).strip()]


def validate_record(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    edf_path = Path(required_text(raw, "edf_path", index)).expanduser().resolve()
    if not edf_path.is_file() or edf_path.suffix.lower() != ".edf":
        raise ValueError(f"Manifest record {index} has an invalid EDF path: {edf_path}")

    recording_modality = required_text(raw, "recording_modality", index)
    expected_datatype = VALID_RECORDING_MODALITIES.get(recording_modality)
    if expected_datatype is None:
        raise ValueError(f"Manifest record {index} has an invalid recording modality.")

    datatype = required_text(raw, "datatype", index).lower()
    if datatype not in VALID_DATATYPES or datatype != expected_datatype:
        raise ValueError(
            f"Manifest record {index} datatype {datatype!r} does not match "
            f"recording modality {recording_modality!r}."
        )

    seizure_text = str(raw.get("number_of_seizures_captured", "")).strip()
    seizure_count: Optional[int]
    if not seizure_text:
        seizure_count = None
    elif seizure_text.isdigit():
        seizure_count = int(seizure_text)
    else:
        raise ValueError(
            f"Manifest record {index} number_of_seizures_captured must be blank, zero, "
            "or a positive whole number."
        )

    localizations = raw.get("primary_seizure_onset_localization", [])
    if not isinstance(localizations, list):
        raise ValueError(
            f"Manifest record {index} primary_seizure_onset_localization must be a list."
        )
    localizations = [str(item).strip() for item in localizations if str(item).strip()]
    if seizure_count and not localizations:
        raise ValueError(
            f"Manifest record {index} requires seizure onset localization when seizures "
            "captured is above zero."
        )

    sidecar_value = str(raw.get("sidecar_path", "")).strip()
    sidecar_path = Path(sidecar_value).expanduser().resolve() if sidecar_value else None
    dataset_name = required_text(raw, "dataset_name", index)

    return {
        "edf_path": edf_path,
        "sidecar_path": sidecar_path,
        "dataset_name": dataset_name,
        "dataset_folder": folder_safe(dataset_name, "dataset_name"),
        "dataset_description": required_text(raw, "dataset_description", index),
        "participant": bids_safe(required_text(raw, "participant_id", index), "participant_id"),
        "session": bids_safe(str(raw.get("session_id", "")), "session_id", optional=True),
        "task": bids_safe(required_text(raw, "task", index), "task"),
        "task_description": required_text(raw, "task_description", index),
        "recording_modality": recording_modality,
        "datatype": datatype,
        "site": bids_safe(required_text(raw, "site", index), "site"),
        "manufacturer": required_text(raw, "manufacturer", index),
        "model_name": required_text(raw, "model_name", index),
        "channel_type_description": required_text(raw, "channel_type_description", index),
        "purpose": required_list(raw, "purpose", index),
        "timing_relative_to_surgery": required_text(
            raw, "timing_relative_to_surgery", index
        ),
        "number_of_seizures_captured": seizure_count,
        "primary_seizure_onset_localization": localizations,
        "comments": str(raw.get("comments", "")).strip(),
    }


def convert_record(record: Dict[str, Any], dataset_dir: Path, overwrite: bool) -> Dict[str, Any]:
    participant = record["participant"]
    session = record["session"]
    task = record["task"]
    datatype = record["datatype"]
    edf_path: Path = record["edf_path"]

    subject_dir = dataset_dir / f"sub-{participant}"
    if session:
        data_dir = subject_dir / f"ses-{session}" / datatype
    else:
        data_dir = subject_dir / datatype
    data_dir.mkdir(parents=True, exist_ok=True)

    prefix_parts = [f"sub-{participant}"]
    if session:
        prefix_parts.append(f"ses-{session}")
    prefix_parts.append(f"task-{task}")
    prefix = "_".join(prefix_parts)

    base = f"{prefix}_{datatype}"
    destination = data_dir / f"{base}.edf"
    if destination.exists() and not overwrite:
        run = next_run_number(data_dir, prefix)
        base = f"{prefix}_run-{run:02d}_{datatype}"
        destination = data_dir / f"{base}.edf"

    metadata = read_edf_metadata(edf_path)
    shutil.copy2(edf_path, destination)
    write_json(data_dir / f"{base}.json", make_recording_sidecar(metadata, record))
    write_tsv(
        data_dir / f"{base}_channels.tsv",
        make_channels_rows(metadata, record),
        [
            "name", "type", "units", "low_cutoff", "high_cutoff",
            "reference", "group", "sampling_frequency", "notch",
            "status", "status_description",
        ],
    )

    participant_fields = read_participant_fields(record["sidecar_path"])
    return {
        "participant_id": f"sub-{participant}",
        "sex": participant_fields["sex"],
        "site": record["site"],
        "output": destination,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert dashboard-selected scrubbed EDF files into BIDS datasets."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    manifest = load_json(args.manifest.expanduser().resolve())
    output_root = args.output_dir.expanduser().resolve()
    bids_version = str(manifest.get("bids_version") or DEFAULT_BIDS_VERSION).strip()

    records_raw = manifest.get("records")
    if not isinstance(records_raw, list) or not records_raw:
        raise SystemExit("The manifest contains no selected records.")
    records = [
        validate_record(record, index)
        for index, record in enumerate(records_raw, start=1)
    ]

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["dataset_folder"], []).append(record)

    total = 0
    for dataset_folder, dataset_records in grouped.items():
        dataset_dir = output_root / dataset_folder
        first = dataset_records[0]
        descriptions = {record["dataset_description"] for record in dataset_records}
        names = {record["dataset_name"] for record in dataset_records}
        if len(descriptions) != 1 or len(names) != 1:
            raise SystemExit(
                f"Dataset folder '{dataset_folder}' has inconsistent names or descriptions."
            )

        ensure_dataset_files(
            dataset_dir,
            first["dataset_name"],
            first["dataset_description"],
            bids_version,
        )

        participant_rows: List[Dict[str, Any]] = []
        for record in dataset_records:
            total += 1
            print(f"[{total}/{len(records)}] Converting {record['edf_path']}")
            result = convert_record(record, dataset_dir, args.overwrite)
            participant_rows.append(result)
            print(f"    -> {result['output']}")
        update_participants(dataset_dir, participant_rows)

    print(
        f"\nDone. Converted {len(records)} EDF file(s) into "
        f"{len(grouped)} project folder(s)."
    )
    print(f"BIDS output root: {output_root}")


if __name__ == "__main__":
    main()
