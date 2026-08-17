#!/usr/bin/env python3
"""Convert dashboard-approved EDF files into BIDS EEG / iEEG raw dataset layouts."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import pyedflib
except ImportError as exc:
    raise SystemExit(
        "pyedflib is required. Install it with:\n\n"
        "    python -m pip install pyedflib\n"
    ) from exc


SUPPORTED_BIDS_VERSION = "1.11.1"

VALID_RECORDING_MODALITIES = {
    "Scalp EEG": "eeg",
    "Stereo EEG (SEEG)": "ieeg",
    "Subdural Grid/Strip EEG (ECoG)": "ieeg",
    "Magnetoencephalography (MEG)": "meg",
}

ENTITY_ORDER = {
    "eeg": ("task", "acq", "run", "space", "recording"),
    "ieeg": ("task", "acq", "run", "space", "recording"),
}

INDEX_FIELDS = {"run", "split"}

COMMON_OPTIONAL_BIDS_MAP = {
    "task_description": "TaskDescription",
    "instructions": "Instructions",
    "cog_atlas_id": "CogAtlasID",
    "cog_po_id": "CogPOID",
    "manufacturer": "Manufacturer",
    "model_name": "ManufacturersModelName",
    "software_versions": "SoftwareVersions",
    "device_serial_number": "DeviceSerialNumber",
    "institution_name": "InstitutionName",
    "institution_address": "InstitutionAddress",
    "institutional_department_name": "InstitutionalDepartmentName",
    "recording_type": "RecordingType",
    "epoch_length": "EpochLength",
    "hardware_filters": "HardwareFilters",
    "subject_artefact_description": "SubjectArtefactDescription",
    "electrical_stimulation": "ElectricalStimulation",
    "electrical_stimulation_parameters": "ElectricalStimulationParameters",
}

EEG_OPTIONAL_BIDS_MAP = {
    "cap_manufacturer": "CapManufacturer",
    "cap_model_name": "CapManufacturersModelName",
    "eeg_ground": "EEGGround",
    "head_circumference": "HeadCircumference",
    "eeg_placement_scheme": "EEGPlacementScheme",
}

IEEG_OPTIONAL_BIDS_MAP = {
    "electrode_manufacturer": "ElectrodeManufacturer",
    "electrode_model_name": "ElectrodeManufacturersModelName",
    "ieeg_ground": "iEEGGround",
    "ieeg_placement_scheme": "iEEGPlacementScheme",
    "ieeg_electrode_groups": "iEEGElectrodeGroups",
}


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------

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
                values.append(
                    str(value).replace("\t", " ").replace("\n", " ")
                )
            handle.write("\t".join(values) + "\n")


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
        "task": "task-",
        "run": "run-",
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

    if not re.fullmatch(r"[A-Za-z0-9+]+", text):
        raise ValueError(
            f"{field} may contain only letters, numbers, and +."
        )
    return text


def clean_task_from_name(task_name: str) -> str:
    """
    Derive a valid BIDS task entity from TaskName.

    BIDS allows the filename task label to be derived from TaskName by
    removing non-alphanumeric / non-plus characters.
    """
    candidate = re.sub(r"[^A-Za-z0-9+]+", "", task_name.strip())
    if not candidate:
        raise ValueError(
            "Task Name must contain at least one letter or number."
        )
    return clean_label(candidate, "task")


def required_text(raw: Dict[str, Any], key: str, index: int) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ValueError(f"Record {index} is missing: {key}")
    return value


def required_list(raw: Dict[str, Any], key: str, index: int) -> List[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Record {index} is missing: {key}")
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    if not cleaned:
        raise ValueError(f"Record {index} is missing: {key}")
    return cleaned


def parse_json_object_or_na(value: str, field: str) -> Any:
    text = str(value).strip()
    if text.lower() == "n/a":
        return "n/a"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{field} must be a JSON object or 'n/a'."
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object or 'n/a'.")
    return parsed


def parse_number_or_na(value: str, field: str) -> Any:
    text = str(value).strip()
    if text.lower() == "n/a":
        return "n/a"
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be numeric or 'n/a'.") from exc


def parse_bool(value: str, field: str) -> bool:
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise ValueError(f"{field} must be true or false.")


def parse_optional_number(value: str, field: str) -> Optional[float]:
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    return number


def parse_number_or_array(value: str, field: str) -> Any:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{field} must be a number or JSON array of numbers."
        ) from exc
    if not isinstance(parsed, list) or not all(
        isinstance(item, (int, float)) for item in parsed
    ):
        raise ValueError(
            f"{field} must be a number or JSON array of numbers."
        )
    return parsed


# -----------------------------------------------------------------------------
# EDF / participant helpers
# -----------------------------------------------------------------------------

def read_edf_metadata(edf_path: Path) -> Dict[str, Any]:
    reader = pyedflib.EdfReader(str(edf_path))
    try:
        channel_count = reader.signals_in_file
        sample_frequencies: List[Optional[float]] = []

        for index in range(channel_count):
            try:
                sample_frequencies.append(
                    float(reader.getSampleFrequency(index))
                )
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
        "ECG": "ECG",
        "EKG": "ECG",
        "ECG1": "ECG",
        "EKG1": "ECG",
        "EOG": "EOG",
        "LOC": "EOG",
        "ROC": "EOG",
        "HEOG": "HEOG",
        "VEOG": "VEOG",
        "EMG": "EMG",
        "EMG1": "EMG",
        "TRIG": "TRIG",
        "TRIGGER": "TRIG",
        "STATUS": "TRIG",
        "EVENT": "TRIG",
        "MARKER": "TRIG",
    }.get(normalized)


def channel_type_for(label: str, recording_modality: str) -> str:
    auxiliary = exact_auxiliary_channel_type(label)
    if auxiliary is not None:
        return auxiliary

    return {
        "Scalp EEG": "EEG",
        "Stereo EEG (SEEG)": "SEEG",
        "Subdural Grid/Strip EEG (ECoG)": "ECOG",
    }[recording_modality]


def primary_sampling_frequency(
    metadata: Dict[str, Any],
    record: Dict[str, Any],
) -> float:
    """
    Use the most common sampling frequency among neural channels.

    Auxiliary channels may legitimately have a different sampling rate and
    are documented per channel in channels.tsv.
    """
    neural_types = {
        "eeg": {"EEG"},
        "ieeg": {"SEEG", "ECOG", "EEG", "DBS"},
    }[record["datatype"]]

    frequencies: List[float] = []
    for index, label in enumerate(metadata["channel_labels"]):
        channel_type = channel_type_for(
            label,
            record["recording_modality"],
        )
        frequency = metadata["sample_frequencies"][index]
        if channel_type in neural_types and frequency is not None:
            frequencies.append(float(frequency))

    if not frequencies:
        frequencies = [
            float(value)
            for value in metadata["sample_frequencies"]
            if value is not None
        ]

    if not frequencies:
        raise ValueError(
            f"Could not determine SamplingFrequency from {record['edf_path']}."
        )

    counts = Counter(frequencies)
    return counts.most_common(1)[0][0]


def channel_type_counts(
    metadata: Dict[str, Any],
    record: Dict[str, Any],
) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for label in metadata["channel_labels"]:
        counts[channel_type_for(label, record["recording_modality"])] += 1
    return dict(counts)


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
        return {
            "age_at_recording": "n/a",
            "sex": "n/a",
        }

    payload = load_json(sidecar_path)

    age = find_nested_value(
        payload,
        {
            "age_at_recording",
            "ageatrecording",
            "age",
            "participant_age",
        },
    )
    sex = find_nested_value(
        payload,
        {
            "sex",
            "gender",
            "participant_sex",
        },
    )

    return {
        "age_at_recording": age if age not in (None, "") else "n/a",
        "sex": sex if sex not in (None, "") else "n/a",
    }


# -----------------------------------------------------------------------------
# Channel / recording sidecars
# -----------------------------------------------------------------------------

def make_channels_rows(
    metadata: Dict[str, Any],
    record: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for index, label in enumerate(metadata["channel_labels"]):
        header = metadata["signal_headers"][index]
        rows.append(
            {
                "name": label,
                "type": channel_type_for(
                    label,
                    record["recording_modality"],
                ),
                "units": header.get("dimension", "n/a") or "n/a",
                "low_cutoff": "n/a",
                "high_cutoff": "n/a",
                "reference": "n/a",
                "group": "n/a",
                "sampling_frequency": (
                    metadata["sample_frequencies"][index]
                    if metadata["sample_frequencies"][index] is not None
                    else "n/a"
                ),
                "notch": "n/a",
                "status": "n/a",
                "status_description": "n/a",
            }
        )

    return rows


def add_optional_sidecar_fields(
    sidecar: Dict[str, Any],
    bids: Dict[str, Any],
    mapping: Dict[str, str],
) -> None:
    for source_key, bids_key in mapping.items():
        raw_value = str(bids.get(source_key, "")).strip()
        if not raw_value:
            continue

        if source_key in {"hardware_filters"}:
            sidecar[bids_key] = parse_json_object_or_na(
                raw_value,
                bids_key,
            )
        elif source_key in {
            "electrical_stimulation",
        }:
            sidecar[bids_key] = parse_bool(raw_value, bids_key)
        elif source_key in {
            "epoch_length",
            "head_circumference",
        }:
            number = parse_optional_number(raw_value, bids_key)
            if number is not None:
                sidecar[bids_key] = number
        else:
            sidecar[bids_key] = raw_value


def make_recording_sidecar(
    metadata: Dict[str, Any],
    record: Dict[str, Any],
) -> Dict[str, Any]:
    bids = record["bids_metadata"]
    duration = metadata["duration_seconds"]

    if not isinstance(duration, (int, float)):
        raise ValueError(
            f"Could not determine recording duration for {record['edf_path']}."
        )

    sampling_frequency = primary_sampling_frequency(metadata, record)
    counts = channel_type_counts(metadata, record)

    sidecar: Dict[str, Any] = {
        # BIDS task / required recording metadata.
        "TaskName": record["task_name"],
        "SamplingFrequency": sampling_frequency,
        "PowerLineFrequency": parse_number_or_na(
            str(bids["power_line_frequency"]),
            "PowerLineFrequency",
        ),
        "SoftwareFilters": parse_json_object_or_na(
            str(bids["software_filters"]),
            "SoftwareFilters",
        ),

        # RecordingDuration is recommended by BIDS and required by CoCANoT.
        # The same value is used for both, in seconds.
        "RecordingDuration": float(duration),

        # CoCANoT extension metadata.
        "CoCANoTPatientID": record["cocanot_patient_id"],
        "SurgeryID": record["surgery_id"],
        "RecordingID": record["recording_id"],
        "RecordingModality": record["recording_modality"],
        "Purpose": record["purpose"],
        "TimingRelativeToSurgery": record["timing_relative_to_surgery"],
        "ThalamusRecorded": record["thalamus_recorded"],
        "ThalamusStimulated": record["thalamus_stimulated"],
        "NumberOfSeizuresCaptured": record["number_of_seizures_captured"],
        "PrimarySeizureOnsetLocalization": record[
            "primary_seizure_onset_localization"
        ],
        "Comments": record["comments"],
    }

    add_optional_sidecar_fields(
        sidecar,
        bids,
        COMMON_OPTIONAL_BIDS_MAP,
    )

    if record["datatype"] == "eeg":
        sidecar["EEGReference"] = str(bids["eeg_reference"]).strip()

        sidecar["EEGChannelCount"] = int(counts.get("EEG", 0))
        sidecar["ECGChannelCount"] = int(counts.get("ECG", 0))
        sidecar["EMGChannelCount"] = int(counts.get("EMG", 0))
        sidecar["EOGChannelCount"] = int(
            counts.get("EOG", 0)
            + counts.get("HEOG", 0)
            + counts.get("VEOG", 0)
        )
        sidecar["MISCChannelCount"] = int(counts.get("MISC", 0))
        sidecar["TriggerChannelCount"] = int(counts.get("TRIG", 0))

        add_optional_sidecar_fields(
            sidecar,
            bids,
            EEG_OPTIONAL_BIDS_MAP,
        )

    elif record["datatype"] == "ieeg":
        sidecar["iEEGReference"] = str(bids["ieeg_reference"]).strip()

        sidecar["ECOGChannelCount"] = int(counts.get("ECOG", 0))
        sidecar["SEEGChannelCount"] = int(counts.get("SEEG", 0))
        sidecar["EEGChannelCount"] = int(counts.get("EEG", 0))
        sidecar["EOGChannelCount"] = int(
            counts.get("EOG", 0)
            + counts.get("HEOG", 0)
            + counts.get("VEOG", 0)
        )
        sidecar["ECGChannelCount"] = int(counts.get("ECG", 0))
        sidecar["EMGChannelCount"] = int(counts.get("EMG", 0))
        sidecar["MiscChannelCount"] = int(counts.get("MISC", 0))
        sidecar["TriggerChannelCount"] = int(counts.get("TRIG", 0))

        add_optional_sidecar_fields(
            sidecar,
            bids,
            IEEG_OPTIONAL_BIDS_MAP,
        )

    return sidecar


# -----------------------------------------------------------------------------
# Companion electrode / coordinate files
# -----------------------------------------------------------------------------

def tsv_header(path: Path) -> List[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            return next(reader)
        except StopIteration:
            return []


def validate_ieeg_electrode_files(
    electrodes_path: Path,
    coordsystem_path: Path,
) -> None:
    if not electrodes_path.is_file():
        raise ValueError(
            f"Required iEEG electrodes TSV does not exist: {electrodes_path}"
        )
    if not coordsystem_path.is_file():
        raise ValueError(
            f"Required iEEG coordinate system JSON does not exist: {coordsystem_path}"
        )

    columns = tsv_header(electrodes_path)
    required_columns = ["name", "x", "y", "z", "size"]
    missing = [column for column in required_columns if column not in columns]
    if missing:
        raise ValueError(
            f"iEEG electrodes TSV is missing required column(s): "
            + ", ".join(missing)
        )

    coords = load_json(coordsystem_path)
    for key in ("iEEGCoordinateSystem", "iEEGCoordinateUnits"):
        if str(coords.get(key, "")).strip() == "":
            raise ValueError(
                f"iEEG coordinate system JSON is missing required key: {key}"
            )

    if (
        str(coords.get("iEEGCoordinateSystem", "")).strip() == "Other"
        and not str(
            coords.get("iEEGCoordinateSystemDescription", "")
        ).strip()
    ):
        raise ValueError(
            "iEEGCoordinateSystemDescription is required when "
            "iEEGCoordinateSystem is Other."
        )


def validate_optional_eeg_electrode_files(
    electrodes_path: Optional[Path],
    coordsystem_path: Optional[Path],
) -> None:
    if electrodes_path is None and coordsystem_path is None:
        return
    if electrodes_path is None or coordsystem_path is None:
        raise ValueError(
            "EEG electrodes TSV and coordinate system JSON must be supplied together."
        )
    if not electrodes_path.is_file():
        raise ValueError(f"EEG electrodes TSV does not exist: {electrodes_path}")
    if not coordsystem_path.is_file():
        raise ValueError(
            f"EEG coordinate system JSON does not exist: {coordsystem_path}"
        )

    columns = tsv_header(electrodes_path)
    required_columns = ["name", "x", "y", "z"]
    missing = [column for column in required_columns if column not in columns]
    if missing:
        raise ValueError(
            "EEG electrodes TSV is missing required column(s): "
            + ", ".join(missing)
        )

    coords = load_json(coordsystem_path)
    for key in ("EEGCoordinateSystem", "EEGCoordinateUnits"):
        if str(coords.get(key, "")).strip() == "":
            raise ValueError(
                f"EEG coordinate system JSON is missing required key: {key}"
            )

    if (
        str(coords.get("EEGCoordinateSystem", "")).strip() == "Other"
        and not str(
            coords.get("EEGCoordinateSystemDescription", "")
        ).strip()
    ):
        raise ValueError(
            "EEGCoordinateSystemDescription is required when "
            "EEGCoordinateSystem is Other."
        )


def optional_path(value: Any) -> Optional[Path]:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


# -----------------------------------------------------------------------------
# Validation / BIDS naming
# -----------------------------------------------------------------------------

def validate_record(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    path = Path(str(raw.get("edf_path", "")).strip()).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".edf":
        raise ValueError(f"Record {index} has an invalid EDF path: {path}")

    recording_modality = required_text(
        raw,
        "recording_modality",
        index,
    )
    datatype = str(raw.get("datatype", "")).strip().lower()

    expected_datatype = VALID_RECORDING_MODALITIES.get(recording_modality)
    if expected_datatype is None:
        raise ValueError(
            f"Record {index} has an unsupported recording modality: "
            f"{recording_modality}"
        )
    if datatype != expected_datatype:
        raise ValueError(
            f"Record {index} datatype {datatype!r} does not match "
            f"recording modality {recording_modality!r}."
        )

    if datatype == "meg":
        raise ValueError(
            "Raw BIDS MEG must remain in the native MEG acquisition format. "
            "EDF files cannot be exported as raw BIDS MEG by this converter."
        )

    task_name = required_text(raw, "task_name", index)

    record: Dict[str, Any] = {
        "edf_path": path,
        "project": clean_project(str(raw.get("project", ""))),
        "project_description": str(
            raw.get("project_description", "")
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
        "task_name": task_name,
        "task": clean_task_from_name(task_name),
        "recording_modality": recording_modality,
        "datatype": datatype,
    }

    # CoCANoT metadata.
    record["cocanot_patient_id"] = required_text(
        raw,
        "cocanot_patient_id",
        index,
    )
    record["surgery_id"] = required_text(raw, "surgery_id", index)
    record["recording_id"] = required_text(raw, "recording_id", index)
    record["purpose"] = required_list(raw, "purpose", index)
    record["timing_relative_to_surgery"] = required_text(
        raw,
        "timing_relative_to_surgery",
        index,
    )
    record["thalamus_recorded"] = required_text(
        raw,
        "thalamus_recorded",
        index,
    )
    record["thalamus_stimulated"] = required_text(
        raw,
        "thalamus_stimulated",
        index,
    )

    for field in ("thalamus_recorded", "thalamus_stimulated"):
        if record[field] not in {"Yes", "No"}:
            raise ValueError(
                f"Record {index} {field} must be either Yes or No."
            )

    seizure_text = required_text(
        raw,
        "number_of_seizures_captured",
        index,
    )
    if not seizure_text.isdigit():
        raise ValueError(
            f"Record {index} number_of_seizures_captured must be "
            "zero or a positive whole number."
        )
    seizure_count = int(seizure_text)
    record["number_of_seizures_captured"] = seizure_count

    localizations = raw.get("primary_seizure_onset_localization", [])
    if not isinstance(localizations, list):
        raise ValueError(
            f"Record {index} primary_seizure_onset_localization must be a list."
        )
    localizations = [
        str(item).strip()
        for item in localizations
        if str(item).strip()
    ]

    if seizure_count > 0 and not localizations:
        raise ValueError(
            f"Record {index} requires primary seizure onset localization "
            "when seizures were captured."
        )
    if seizure_count == 0:
        localizations = ["N/A"]

    record["primary_seizure_onset_localization"] = localizations
    record["comments"] = required_text(raw, "comments", index)

    # Participant sidecar from scrubber.
    sidecar_value = str(raw.get("sidecar_path", "")).strip()
    sidecar_path = (
        Path(sidecar_value).expanduser().resolve()
        if sidecar_value
        else None
    )
    if sidecar_path is not None and not sidecar_path.exists():
        raise ValueError(
            f"Record {index} participant sidecar does not exist: "
            f"{sidecar_path}"
        )
    record["sidecar_path"] = sidecar_path

    # BIDS metadata.
    bids = raw.get("bids_metadata", {})
    if not isinstance(bids, dict):
        raise ValueError(
            f"Record {index} bids_metadata must be a JSON object."
        )

    record["bids_metadata"] = {
        str(key): value
        for key, value in bids.items()
    }

    for key in ("power_line_frequency", "software_filters"):
        if not str(bids.get(key, "")).strip():
            raise ValueError(f"Record {index} is missing BIDS field: {key}")

    # Validate the values immediately.
    parse_number_or_na(
        str(bids["power_line_frequency"]),
        "PowerLineFrequency",
    )
    parse_json_object_or_na(
        str(bids["software_filters"]),
        "SoftwareFilters",
    )

    if str(bids.get("hardware_filters", "")).strip():
        parse_json_object_or_na(
            str(bids["hardware_filters"]),
            "HardwareFilters",
        )

    if str(bids.get("electrical_stimulation", "")).strip():
        parse_bool(
            str(bids["electrical_stimulation"]),
            "ElectricalStimulation",
        )

    if datatype == "eeg":
        if not str(bids.get("eeg_reference", "")).strip():
            raise ValueError(
                f"Record {index} is missing BIDS EEGReference."
            )

        eeg_electrodes = optional_path(
            bids.get("eeg_electrodes_tsv_path")
        )
        eeg_coordsystem = optional_path(
            bids.get("eeg_coordsystem_json_path")
        )
        validate_optional_eeg_electrode_files(
            eeg_electrodes,
            eeg_coordsystem,
        )
        record["eeg_electrodes_tsv_path"] = eeg_electrodes
        record["eeg_coordsystem_json_path"] = eeg_coordsystem

    elif datatype == "ieeg":
        if not str(bids.get("ieeg_reference", "")).strip():
            raise ValueError(
                f"Record {index} is missing BIDS iEEGReference."
            )

        electrodes_path = optional_path(
            bids.get("ieeg_electrodes_tsv_path")
        )
        coordsystem_path = optional_path(
            bids.get("ieeg_coordsystem_json_path")
        )
        if electrodes_path is None or coordsystem_path is None:
            raise ValueError(
                f"Record {index} requires iEEG electrodes TSV and "
                "coordinate system JSON."
            )
        validate_ieeg_electrode_files(
            electrodes_path,
            coordsystem_path,
        )
        record["ieeg_electrodes_tsv_path"] = electrodes_path
        record["ieeg_coordsystem_json_path"] = coordsystem_path

    return record


def build_entity_prefix(
    record: Dict[str, Any],
    run_override: Optional[int] = None,
) -> str:
    parts = [f"sub-{record['participant']}"]

    if record["session"]:
        parts.append(f"ses-{record['session']}")

    for field in ENTITY_ORDER[record["datatype"]]:
        value = record.get(field, "")
        if field == "task":
            value = record["task"]
        if field == "run" and run_override is not None:
            value = f"{run_override:02d}"
        if value:
            parts.append(f"{field}-{value}")

    return "_".join(parts)


def build_bids_base(
    record: Dict[str, Any],
    run_override: Optional[int] = None,
) -> str:
    return (
        build_entity_prefix(record, run_override=run_override)
        + f"_{record['datatype']}"
    )


def choose_output_base(
    data_dir: Path,
    record: Dict[str, Any],
    overwrite: bool,
) -> str:
    base = build_bids_base(record)
    if overwrite or not (data_dir / f"{base}.edf").exists():
        return base

    start = int(record.get("run") or 1) + 1
    for run in range(start, 10000):
        candidate = build_bids_base(record, run_override=run)
        if not (data_dir / f"{candidate}.edf").exists():
            return candidate

    raise ValueError(f"Could not find an available run number for {base}")


# -----------------------------------------------------------------------------
# participants.tsv / participants.json
# -----------------------------------------------------------------------------

def read_existing_tsv(
    path: Path,
    key: str,
) -> Dict[str, Dict[str, Any]]:
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


def write_participants(
    project_dir: Path,
    participant_rows: List[Dict[str, Any]],
) -> None:
    participants_path = project_dir / "participants.tsv"
    existing = read_existing_tsv(
        participants_path,
        "participant_id",
    )

    for row in participant_rows:
        existing[row["participant_id"]] = row

    columns = [
        "participant_id",
        "age_at_recording",
        "sex",
    ]

    write_tsv(
        participants_path,
        [existing[key] for key in sorted(existing)],
        columns,
    )

    write_json(
        project_dir / "participants.json",
        {
            "participant_id": {
                "Description": (
                    "CoCANoT coded participant identifier stored as the "
                    "BIDS participant_id."
                )
            },
            "age_at_recording": {
                "Description": (
                    "Participant age at the time of the electrophysiology "
                    "recording."
                )
            },
            "sex": {
                "Description": "Participant sex when available."
            },
        },
    )


# -----------------------------------------------------------------------------
# Copy / conversion
# -----------------------------------------------------------------------------

def copy_companion_files(
    record: Dict[str, Any],
    data_dir: Path,
    entity_prefix: str,
    overwrite: bool,
) -> None:
    if record["datatype"] == "ieeg":
        electrodes_src = record["ieeg_electrodes_tsv_path"]
        coordsystem_src = record["ieeg_coordsystem_json_path"]

        electrodes_dst = data_dir / f"{entity_prefix}_electrodes.tsv"
        coordsystem_dst = data_dir / f"{entity_prefix}_coordsystem.json"

        if overwrite:
            electrodes_dst.unlink(missing_ok=True)
            coordsystem_dst.unlink(missing_ok=True)

        shutil.copy2(electrodes_src, electrodes_dst)
        shutil.copy2(coordsystem_src, coordsystem_dst)

    elif record["datatype"] == "eeg":
        electrodes_src = record.get("eeg_electrodes_tsv_path")
        coordsystem_src = record.get("eeg_coordsystem_json_path")

        if electrodes_src is not None and coordsystem_src is not None:
            electrodes_dst = data_dir / f"{entity_prefix}_electrodes.tsv"
            coordsystem_dst = data_dir / f"{entity_prefix}_coordsystem.json"

            if overwrite:
                electrodes_dst.unlink(missing_ok=True)
                coordsystem_dst.unlink(missing_ok=True)

            shutil.copy2(electrodes_src, electrodes_dst)
            shutil.copy2(coordsystem_src, coordsystem_dst)


def copy_record(
    record: Dict[str, Any],
    output_root: Path,
    overwrite: bool,
) -> Dict[str, Any]:
    project_dir = output_root / record["project"]
    data_dir = project_dir / f"sub-{record['participant']}"

    if record["session"]:
        data_dir /= f"ses-{record['session']}"

    data_dir /= record["datatype"]
    data_dir.mkdir(parents=True, exist_ok=True)

    base = choose_output_base(data_dir, record, overwrite)
    output_edf = data_dir / f"{base}.edf"
    output_json = data_dir / f"{base}.json"
    output_channels = data_dir / f"{base}_channels.tsv"

    if overwrite:
        output_edf.unlink(missing_ok=True)
        output_json.unlink(missing_ok=True)
        output_channels.unlink(missing_ok=True)

    metadata = read_edf_metadata(record["edf_path"])
    shutil.copy2(record["edf_path"], output_edf)

    write_json(
        output_json,
        make_recording_sidecar(metadata, record),
    )

    write_tsv(
        output_channels,
        make_channels_rows(metadata, record),
        [
            "name",
            "type",
            "units",
            "low_cutoff",
            "high_cutoff",
            "reference",
            "group",
            "sampling_frequency",
            "notch",
            "status",
            "status_description",
        ],
    )

    entity_prefix = base.rsplit(f"_{record['datatype']}", 1)[0]
    copy_companion_files(
        record,
        data_dir,
        entity_prefix,
        overwrite,
    )

    participant_fields = read_participant_fields(
        record["sidecar_path"]
    )

    return {
        "participant_id": f"sub-{record['participant']}",
        "age_at_recording": participant_fields["age_at_recording"],
        "sex": participant_fields["sex"],
        "output": output_edf,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert approved EDF files into BIDS EEG / iEEG raw layouts."
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
            "Manifest contains no selected electrophysiology records."
        )

    records = [
        validate_record(record, index)
        for index, record in enumerate(raw_records, start=1)
    ]

    output_root.mkdir(parents=True, exist_ok=True)
    by_project: Dict[str, List[Dict[str, Any]]] = {}

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
            f"[{index}/{len(records)}] {record['edf_path']} -> "
            f"{record['project']} / {record['datatype']}"
        )

        result = copy_record(
            record,
            output_root,
            args.overwrite,
        )
        by_project.setdefault(
            record["project"],
            [],
        ).append(result)

        print(f"    -> {result['output']}")

    for project, participant_rows in by_project.items():
        write_participants(
            output_root / project,
            participant_rows,
        )

    print("\nBIDS electrophysiology conversion complete.")
    print(f"Converted files: {len(records)}")
    print(f"Output folder: {output_root}")


if __name__ == "__main__":
    main()
