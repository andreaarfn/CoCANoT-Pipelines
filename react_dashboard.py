#!/usr/bin/env python3
"""React + PyWebView launcher for the unified CoCANoT application."""

from __future__ import annotations

import base64
import csv
import io
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable

import webview
import nibabel as nib
import numpy as np
from matplotlib import image as mpl_image


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent

FRONTEND_DIR = ROOT / "react_frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

IMAGING_DIR = ROOT / "ImagingPipeline"
IMAGING_SCRIPTS = IMAGING_DIR / "scripts"

EPHYS_DIR = ROOT / "ElectrophysiologyPipeline"
EPHYS_SCRIPTS = EPHYS_DIR / "scripts"

IMAGING_DICOM_CONVERTER = IMAGING_SCRIPTS / "dicom_to_nifti.py"
IMAGING_HEADER_SCRUBBER = IMAGING_SCRIPTS / "scrub_nifti_header.py"
IMAGING_DEFACER = IMAGING_SCRIPTS / "deface_nifti_with_pydeface.py"
IMAGING_BIDS_CONVERTER = IMAGING_SCRIPTS / "nifti_to_bids.py"
METADATA_DICTIONARY = ROOT / "MetadataPipeline" / "dictionaries" / "CoCANoT_Metadata_Phase1.xlsx"
MRI_SEQUENCE_FIELDS = (
    "MRI Sequence(s) (if applicable)",
    "MRI Sequence(s) - if MRI (multiselect)",
)
MRI_SEQUENCE_MAP = {
    "T1": ("anat", "T1w"),
    "T2": ("anat", "T2w"),
    "FLAIR": ("anat", "FLAIR"),
    "DWI": ("dwi", "dwi"),
    "SWI": ("anat", "T2starw"),
}

EPHYS_SCRUBBER = EPHYS_SCRIPTS / "scrub_edf_metadata.py"
EPHYS_COMPARISON = EPHYS_SCRIPTS / "compare_raw_and_scrubbed_edf.py"
EPHYS_BIDS_CONVERTER = EPHYS_SCRIPTS / "convert_edf_to_bids.py"
EPHYS_MODALITY_TO_DATATYPE = {
    "Scalp EEG": "eeg",
    "Stereo EEG (SEEG)": "ieeg",
    "Subdural grid": "ieeg",
    "Subdural strips": "ieeg",
    "Depth electrodes (not SEEG)": "ieeg",
    "Intraoperative electrocorticography (ECoG)": "ieeg",
    "Magnetoencephalography (MEG)": "meg",
}
EPHYS_DERIVED_FIELDS = {"Recording Duration (hours)"}

REVIEW_STATE_FILENAME = "imaging_review_state.json"
EDITABLE_HEADER_FIELDS = {"descrip", "aux_file", "intent_name"}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from MetadataPipeline.forms.clinical_assessment import tracked_clinical_fields
from MetadataPipeline.storage import LocalMetadataStore
from MetadataPipeline.storage.data_link_store import PatientDataLinkStore
from MetadataPipeline.storage.record_deletion import RecordDeletionService
from MetadataPipeline.storage.record_repository import MetadataRepository
from MetadataPipeline.validation import MetadataValidator, load_dictionary

from pipeline_config import (
    build_imaging_settings_dict,
    build_settings_dict,
    load_imaging_config,
    load_pipeline_config,
    load_settings_dict,
    save_settings_dict,
    validate_pipeline_config,
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _as_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text).expanduser() if text else None


def _resolve_text(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _unique_paths(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        path = _as_path(value)
        if path is None:
            continue

        normalized = _resolve_text(path)
        if normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return result


def _is_nifti(path: Path) -> bool:
    name = path.name.lower()
    return path.is_file() and (
        name.endswith(".nii")
        or name.endswith(".nii.gz")
    )


def _matching_json(path: Path) -> Path | None:
    if path.name.endswith(".nii.gz"):
        base = path.name[:-7]
    elif path.name.endswith(".nii"):
        base = path.name[:-4]
    else:
        base = path.stem

    candidate = path.with_name(f"{base}.json")
    return candidate if candidate.exists() else None


def _matching_extra_sidecars(path: Path) -> list[Path]:
    if path.name.endswith(".nii.gz"):
        base = path.name[:-7]
    elif path.name.endswith(".nii"):
        base = path.name[:-4]
    else:
        base = path.stem

    result: list[Path] = []
    for suffix in (".bval", ".bvec"):
        candidate = path.with_name(f"{base}{suffix}")
        if candidate.exists():
            result.append(candidate)

    return result


def _scan_edf_sources(sources: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    counter = 1

    for source_index, source_text in enumerate(sources, start=1):
        source = Path(source_text).expanduser()

        try:
            source = source.resolve()
        except OSError:
            continue

        if source.is_file():
            if source.suffix.lower() != ".edf":
                continue
            edf_files = [source]
            source_root = source.parent
            source_name = source.parent.name

        elif source.is_dir():
            edf_files = sorted(
                path
                for path in source.rglob("*")
                if path.is_file() and path.suffix.lower() == ".edf"
            )
            source_root = source
            source_name = source.name

        else:
            continue

        for edf_path in edf_files:
            relative = (
                Path(edf_path.name)
                if source.is_file()
                else edf_path.relative_to(source_root)
            )

            records.append(
                {
                    "id": f"raw-{counter}",
                    "include": True,
                    "source_index": source_index,
                    "source_folder": str(source_root),
                    "source_name": source_name,
                    "relative_path": str(relative),
                    "edf_path": str(edf_path),
                    "file_name": edf_path.name,
                }
            )
            counter += 1

    return records


def _scan_imaging_sources(sources: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    counter = 1

    for source_text in sources:
        source = Path(source_text).expanduser()

        try:
            source = source.resolve()
        except OSError:
            continue

        if source.is_file():
            candidates = [source]
            source_name = source.parent.name
        elif source.is_dir():
            candidates = sorted(path for path in source.rglob("*") if path.is_file())
            source_name = source.name
        else:
            continue

        for path in candidates:
            if _is_nifti(path):
                file_type = "NIfTI"
            elif path.suffix.lower() in {".dcm", ".dicom", ""}:
                file_type = "DICOM"
            else:
                continue

            records.append(
                {
                    "id": f"image-{counter}",
                    "include": True,
                    "file_name": path.name,
                    "source_name": source_name,
                    "file_type": file_type,
                    "path": str(path),
                }
            )
            counter += 1

    return records


def _normalize_patient_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("patient_id", "patientId", "id", "CoCANoT Patient ID"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                return str(candidate).strip()
        return ""

    return str(value or "").strip()


def _record_table_name(record: dict[str, Any]) -> str:
    for key in ("table_name", "table", "type", "modality", "category"):
        value = record.get(key)
        if value:
            return str(value).strip().lower()
    return ""


def _safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


# ---------------------------------------------------------------------------
# Dynamic comparison-module loader
# ---------------------------------------------------------------------------

_COMPARISON_MODULE = None


def _load_ephys_comparison_module():
    global _COMPARISON_MODULE

    if _COMPARISON_MODULE is not None:
        return _COMPARISON_MODULE

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cocanot_edf_comparison_helpers",
        EPHYS_COMPARISON,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load EDF comparison helpers from {EPHYS_COMPARISON}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _COMPARISON_MODULE = module
    return module


# ---------------------------------------------------------------------------
# React API
# ---------------------------------------------------------------------------

class CoCANoTAPI:
    """Methods exposed to React through PyWebView."""

    def __init__(self) -> None:
        self.window = None

        self.store = LocalMetadataStore()
        self.repository = MetadataRepository()

        self.ephys_sources: list[str] = []
        self.dicom_input_paths: list[str] = []
        self.nifti_input_paths: list[str] = []

        self.ephys_logs: list[str] = []
        self.imaging_logs: list[str] = []

        self.ephys_process: subprocess.Popen[str] | None = None
        self.imaging_process: subprocess.Popen[str] | None = None

        self._load_initial_state()

    # ------------------------------------------------------------------
    # Startup state
    # ------------------------------------------------------------------

    def _load_initial_state(self) -> None:
        try:
            settings = load_settings_dict()
        except Exception:
            settings = {}

        ephys = settings.get("electrophysiology", {})
        ephys_inputs = ephys.get("input_dirs") or (
            [ephys.get("input_dir")] if ephys.get("input_dir") else []
        )

        self.ephys_sources = _unique_paths(
            str(value) for value in ephys_inputs if value
        )

        imaging = settings.get("imaging", {})

        saved_inputs = [
            str(value)
            for value in imaging.get("input_dirs", [])
            if value
        ]

        dicom_values = imaging.get(
            "dicom_input_dirs",
            saved_inputs,
        ) or []

        nifti_values = imaging.get(
            "nifti_input_dirs",
            imaging.get(
                "nifti_input_files",
                [],
            ),
        ) or []

        if isinstance(dicom_values, str):
            dicom_values = [dicom_values]

        if isinstance(nifti_values, str):
            nifti_values = [nifti_values]

        self.dicom_input_paths = _unique_paths(
            str(value)
            for value in dicom_values
            if value
        )

        self.nifti_input_paths = _unique_paths(
            str(value)
            for value in nifti_values
            if value
        )

    # ------------------------------------------------------------------
    # Site
    # ------------------------------------------------------------------

    def get_site_id(self) -> str:
        return self.store.get_site_id() or ""

    def set_site_id(self, site_id: str) -> str:
        normalized = str(site_id or "").strip().upper()

        if not normalized:
            raise ValueError("Site ID cannot be blank.")

        return self.store.set_site_id(normalized)

    # ------------------------------------------------------------------
    # Native dialogs
    # ------------------------------------------------------------------

    def choose_folder(self) -> str:
        if self.window is None:
            return ""

        result = self.window.create_file_dialog(
            webview.FileDialog.FOLDER,
        )

        if not result:
            return ""

        if isinstance(result, str):
            return result

        return str(result[0]) if result else ""

    # ------------------------------------------------------------------
    # Electrophysiology
    # ------------------------------------------------------------------

    def ephys_get_state(self) -> dict[str, Any]:
        try:
            settings = load_settings_dict()
        except Exception:
            settings = {}

        ephys = settings.get("electrophysiology", {})

        return {
            "input_dirs": list(self.ephys_sources),
            "records": _scan_edf_sources(self.ephys_sources),
            "derivatives_dir": str(ephys.get("derivatives_dir", "") or ""),
            "bids_output_dir": str(ephys.get("bids_output_dir", "") or ""),
            "status": (
                "Running"
                if self._process_running(self.ephys_process)
                else "Ready"
            ),
            "logs": list(self.ephys_logs),
        }

    def ephys_choose_files(self) -> dict[str, Any]:
        if self.window is None:
            return self.ephys_get_state()

        selected = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=("EDF files (*.edf)",),
        )

        if selected:
            if isinstance(selected, str):
                selected = [selected]

            self.ephys_sources = _unique_paths(
                list(self.ephys_sources)
                + [
                    str(path)
                    for path in selected
                    if str(path).lower().endswith(".edf")
                ]
            )
            self._ephys_log("Added EDF file selection.")

        return self.ephys_get_state()

    def ephys_choose_folders(self) -> dict[str, Any]:
        if self.window is None:
            return self.ephys_get_state()

        selected = self.window.create_file_dialog(
            webview.FileDialog.FOLDER,
        )

        if selected:
            if isinstance(selected, str):
                selected = [selected]

            self.ephys_sources = _unique_paths(
                list(self.ephys_sources)
                + [str(path) for path in selected]
            )
            self._ephys_log("Added EDF source folder.")

        return self.ephys_get_state()

    def ephys_remove_sources(self, selected: list[str]) -> dict[str, Any]:
        indices: list[int] = []

        for value in selected or []:
            text = str(value)
            if not text.startswith("source:"):
                continue

            try:
                indices.append(int(text.split(":", 1)[1]))
            except ValueError:
                continue

        for index in sorted(indices, reverse=True):
            if 0 <= index < len(self.ephys_sources):
                del self.ephys_sources[index]

        self._ephys_log("Updated EDF source list.")
        return self.ephys_get_state()

    def ephys_save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        sources = _unique_paths(
            str(value)
            for value in payload.get("input_dirs", [])
            if value
        )

        derivatives = str(payload.get("derivatives_dir", "") or "").strip()
        bids = str(payload.get("bids_output_dir", "") or "").strip()

        if not sources:
            raise ValueError("Add at least one EDF file or folder.")

        if not derivatives or not bids:
            raise ValueError(
                "Select both the derivatives and BIDS output folders."
            )

        config_inputs: list[str] = []

        for source_text in sources:
            source = Path(source_text).expanduser()
            if source.is_file():
                source = source.parent

            resolved = _resolve_text(source)
            if resolved not in config_inputs:
                config_inputs.append(resolved)

        settings = build_settings_dict(
            input_dirs=config_inputs,
            derivatives_dir=derivatives,
            bids_output_dir=bids,
        )

        electrophysiology = settings.setdefault(
            "electrophysiology",
            {},
        )
        electrophysiology["input_dirs"] = list(sources)

        # Follow the existing Tkinter dashboard behavior: the settings builder
        # returns the complete settings payload expected by save_settings_dict.
        save_settings_dict(settings)

        config = load_pipeline_config()
        validate_pipeline_config(config, create_outputs=True)

        self.ephys_sources = sources
        self._ephys_log("Electrophysiology folder settings saved.")

        return self.ephys_get_state()

    def ephys_run_operation(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation", "")).strip().lower()
        records = payload.get("records", [])

        self.ephys_save_settings(
            {
                "input_dirs": list(self.ephys_sources),
                "derivatives_dir": payload.get("derivatives_dir", ""),
                "bids_output_dir": payload.get("bids_output_dir", ""),
            }
        )

        config = load_pipeline_config()
        overwrite = bool(payload.get("overwrite", False))

        if operation == "scrub":
            return self._ephys_scrub(
                records=records,
                derivatives_dir=config.electrophysiology.derivatives_dir,
                scrubbed_dir=config.electrophysiology.scrubbed_dir,
                overwrite=overwrite,
            )

        if operation == "review":
            staged = (
                config.electrophysiology.derivatives_dir
                / "_selected_raw"
            )
            scrubbed = config.electrophysiology.scrubbed_dir

            if not staged.is_dir():
                raise ValueError(
                    "No staged raw EDFs were found. Run Step 1 first."
                )

            if not scrubbed.is_dir():
                raise ValueError(
                    "No scrubbed EDFs were found. Run Step 1 first."
                )

            pairs = self.ephys_review_get_pairs()

            if not pairs:
                raise ValueError(
                    "No matching raw and scrubbed EDF pairs were found."
                )

            return {
                "ok": True,
                "status": "Ready for EDF review",
                "log": f"Found {len(pairs)} EDF pair(s) for review.",
                "pairs": pairs,
            }

        if operation == "bids":
            scrubbed = config.electrophysiology.scrubbed_dir
            has_edf = (
                scrubbed.exists()
                and any(
                    path.is_file()
                    and path.suffix.lower() == ".edf"
                    for path in scrubbed.rglob("*")
                )
            )

            if not has_edf:
                raise ValueError(
                    "No scrubbed EDFs were found. Run the scrubber first."
                )

            return {
                "ok": True,
                "status": "Ready for metadata review",
                "log": (
                    "Opening Electrophysiology metadata and BIDS review."
                ),
            }

        raise ValueError(
            f"Unknown Electrophysiology operation: {operation}"
        )

    def _ephys_scrub(
        self,
        *,
        records: list[dict[str, Any]],
        derivatives_dir: Path,
        scrubbed_dir: Path,
        overwrite: bool,
    ) -> dict[str, Any]:
        if not EPHYS_SCRUBBER.is_file():
            raise FileNotFoundError(
                f"EDF scrubber not found: {EPHYS_SCRUBBER}"
            )

        included = self._included_imaging_records(
            records
        )

        if not included:
            raise ValueError("Include at least one EDF file.")

        staging = Path(derivatives_dir) / "_selected_raw"

        if staging.exists():
            shutil.rmtree(staging)

        staging.mkdir(parents=True, exist_ok=True)

        selected_files: list[str] = []

        for index, record in enumerate(included, start=1):
            source = Path(
                str(record.get("edf_path", ""))
            ).expanduser()

            if not source.is_file():
                continue

            relative = Path(
                str(record.get("relative_path", source.name))
            )

            source_index = int(
                record.get("source_index", index)
            )

            destination = (
                staging
                / f"source-{source_index:03d}"
                / relative
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.copy2(source, destination)
            selected_files.append(_resolve_text(source))

        if not selected_files:
            raise ValueError(
                "None of the included EDF source files could be found."
            )

        selection_log = {
            "source_folders": list(self.ephys_sources),
            "selected_files": selected_files,
        }

        (staging / "selection.json").write_text(
            json.dumps(selection_log, indent=2) + "\n",
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-u",
            str(EPHYS_SCRUBBER),
            "--input-dir",
            str(staging),
            "--output-dir",
            str(scrubbed_dir),
        ]

        if overwrite:
            command.append("--overwrite")

        self._start_process(
            command=command,
            workflow="ephys",
            description="EDF metadata scrubbing",
        )

        return {
            "ok": True,
            "status": "EDF metadata scrubbing started",
            "log": f"Staged {len(selected_files)} EDF file(s) in {staging}.",
        }

    def ephys_review_get_pairs(self) -> list[dict[str, Any]]:
        config = load_pipeline_config()
        input_dir = (
            config.electrophysiology.derivatives_dir
            / "_selected_raw"
        )
        scrubbed_dir = config.electrophysiology.scrubbed_dir

        if not input_dir.is_dir() or not scrubbed_dir.is_dir():
            return []

        helpers = _load_ephys_comparison_module()
        result: list[dict[str, Any]] = []

        for raw_path in helpers.find_edf_files(input_dir):
            relative = raw_path.relative_to(input_dir)
            scrubbed_path = (
                scrubbed_dir
                / relative.parent
                / helpers.scrubbed_filename(raw_path)
            )

            if not scrubbed_path.exists():
                continue

            result.append(
                {
                    "id": str(len(result)),
                    "label": str(relative),
                    "raw_path": str(raw_path.resolve()),
                    "scrubbed_path": str(scrubbed_path.resolve()),
                }
            )

        return result

    def ephys_review_get_pair(self, pair_id: str | int) -> dict[str, Any]:
        pairs = self.ephys_review_get_pairs()

        try:
            index = int(pair_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid EDF review pair.")

        if index < 0 or index >= len(pairs):
            raise ValueError("EDF review pair not found.")

        pair = pairs[index]
        helpers = _load_ephys_comparison_module()

        return {
            **pair,
            "raw": helpers.read_review_data(
                Path(pair["raw_path"])
            ),
            "scrubbed": helpers.read_review_data(
                Path(pair["scrubbed_path"])
            ),
            "editable_header_fields": sorted(
                str(value)
                for value in helpers.EDITABLE_HEADER_FIELDS
            ),
        }

    def ephys_review_save_pair(
        self,
        pair_id: str | int,
        scrubbed_header: dict[str, Any],
        scrubbed_annotations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pairs = self.ephys_review_get_pairs()

        try:
            index = int(pair_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid EDF review pair.")

        if index < 0 or index >= len(pairs):
            raise ValueError("EDF review pair not found.")

        pair = pairs[index]
        helpers = _load_ephys_comparison_module()

        helpers.rewrite_scrubbed_edf(
            Path(pair["scrubbed_path"]),
            scrubbed_header,
            scrubbed_annotations,
        )

        self._ephys_log(
            f"Saved scrubbed EDF review edits: {pair['label']}"
        )

        return self.ephys_review_get_pair(index)


    @staticmethod
    def _rule_payload(
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "field_name": str(rule.get("field_name", "")),
            "ui_prompt": str(
                rule.get("ui_prompt")
                or rule.get("field_name")
                or ""
            ),
            "input_type": str(
                rule.get("input_type", "free_text")
            ),
            "allowed_values": [
                str(value)
                for value in (
                    rule.get("allowed_values")
                    or []
                )
            ],
            "required": bool(
                rule.get("required", False)
            ),
            "required_if_field": str(
                rule.get("required_if_field")
                or ""
            ),
            "required_if_operator": str(
                rule.get("required_if_operator")
                or ""
            ),
            "required_if_value": rule.get(
                "required_if_value"
            ),
            "system_generated": bool(
                rule.get("system_generated", False)
            ),
            "help_text": str(
                rule.get("help_text")
                or ""
            ),
            "dictionary_version": str(
                rule.get("dictionary_version")
                or ""
            ),
        }

    def _dictionary_context(
        self,
        table_name: str,
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        MetadataValidator,
    ]:
        dictionary = load_dictionary(
            METADATA_DICTIONARY
        )
        rules = dictionary[
            "tables"
        ][
            table_name
        ][
            "fields"
        ]
        validator = MetadataValidator(
            dictionary
        )
        return (
            dictionary,
            rules,
            validator,
        )

    @staticmethod
    def _normalize_metadata_values(
        metadata: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized = dict(
            metadata or {}
        )

        for rule in rules:
            if bool(
                rule.get(
                    "system_generated",
                    False,
                )
            ):
                continue

            field_name = str(
                rule.get(
                    "field_name",
                    "",
                )
            )
            if not field_name:
                continue

            input_type = str(
                rule.get(
                    "input_type",
                    "",
                )
            ).strip().lower()
            value = normalized.get(
                field_name
            )

            if input_type == "multi_select":
                if value in (
                    None,
                    "",
                ):
                    selected: list[str] = []
                elif isinstance(
                    value,
                    (
                        list,
                        tuple,
                        set,
                    ),
                ):
                    selected = [
                        str(item).strip()
                        for item in value
                        if str(item).strip()
                    ]
                else:
                    scalar = str(
                        value
                    ).strip()
                    selected = (
                        [
                            item.strip()
                            for item in re.split(
                                r"[;|]",
                                scalar,
                            )
                            if item.strip()
                        ]
                        if scalar
                        else []
                    )

                allowed = [
                    str(item)
                    for item in (
                        rule.get(
                            "allowed_values",
                            [],
                        )
                        or []
                    )
                ]

                if allowed:
                    selected_set = set(
                        selected
                    )
                    selected = [
                        item
                        for item in allowed
                        if item in selected_set
                    ]
                else:
                    selected = list(
                        dict.fromkeys(
                            selected
                        )
                    )

                normalized[
                    field_name
                ] = selected

            elif value is None:
                normalized[
                    field_name
                ] = ""

        return normalized

    @staticmethod
    def _recording_duration_hours(
        edf_path: Path,
    ) -> object:
        try:
            import pyedflib

            reader = pyedflib.EdfReader(
                str(edf_path)
            )
            try:
                return round(
                    float(
                        reader.file_duration
                    )
                    / 3600.0,
                    8,
                )
            finally:
                reader.close()
        except Exception:
            return ""

    def ephys_bids_get_state(
        self,
    ) -> dict[str, Any]:
        config = load_pipeline_config()
        scrubbed_dir = (
            config.electrophysiology.scrubbed_dir
        )

        if not scrubbed_dir.exists():
            raise ValueError(
                "No scrubbed EDF directory exists. "
                "Run the scrubber first."
            )

        edf_files = sorted(
            path
            for path in scrubbed_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() == ".edf"
        )

        if not edf_files:
            raise ValueError(
                "No scrubbed EDF files were found. "
                "Run the scrubber first."
            )

        _dictionary, rules, _validator = (
            self._dictionary_context(
                "Electrophysiology"
            )
        )

        records: list[
            dict[str, Any]
        ] = []

        for index, edf_path in enumerate(
            edf_files,
            start=1,
        ):
            sidecar = (
                edf_path.with_suffix(
                    ".json"
                )
            )
            records.append(
                {
                    "id": f"record-{index}",
                    "include": True,
                    "edf_path": str(
                        edf_path.resolve()
                    ),
                    "sidecar_path": (
                        str(
                            sidecar.resolve()
                        )
                        if sidecar.exists()
                        else ""
                    ),
                    "source_label": str(
                        edf_path.relative_to(
                            scrubbed_dir
                        )
                    ),
                    "project": "",
                    "project_description": "",
                    "session_id": "",
                    "cocanot_metadata": {
                        "Recording Duration (hours)": (
                            self._recording_duration_hours(
                                edf_path
                            )
                        ),
                    },
                    "status": "Missing metadata",
                }
            )

        return {
            "site_id": self.get_site_id(),
            "records": records,
            "rules": [
                self._rule_payload(
                    rule
                )
                for rule in rules
                if not bool(
                    rule.get(
                        "system_generated",
                        False,
                    )
                )
            ],
            "derived_fields": sorted(
                EPHYS_DERIVED_FIELDS
            ),
            "bids_output_dir": str(
                config.electrophysiology.bids_output_dir
            ),
        }

    def ephys_bids_validate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        records = list(
            payload.get(
                "records",
                [],
            )
            or []
        )
        included = [
            record
            for record in records
            if bool(
                record.get(
                    "include",
                    True,
                )
            )
        ]

        if not included:
            return {
                "ok": False,
                "problems": [
                    "Include at least one recording."
                ],
                "records": records,
            }

        _dictionary, rules, validator = (
            self._dictionary_context(
                "Electrophysiology"
            )
        )

        problems: list[str] = []
        normalized_records: list[
            dict[str, Any]
        ] = []

        for record in included:
            source_label = str(
                record.get(
                    "source_label",
                    "",
                )
            )
            project = str(
                record.get(
                    "project",
                    "",
                )
                or ""
            ).strip()
            session_id = str(
                record.get(
                    "session_id",
                    "",
                )
                or ""
            ).strip()

            if not project:
                problems.append(
                    f"{source_label}: Project is required."
                )
                continue

            if not session_id:
                problems.append(
                    f"{source_label}: Session ID is required."
                )
                continue

            metadata = self._normalize_metadata_values(
                dict(
                    record.get(
                        "cocanot_metadata",
                        {},
                    )
                    or {}
                ),
                rules,
            )

            patient_id = str(
                metadata.get(
                    "CoCANoT Patient ID",
                    "",
                )
                or ""
            ).strip()

            if patient_id:
                latest = (
                    self.store.latest_clinical_assessment(
                        self.get_site_id(),
                        patient_id,
                    )
                )
                if latest is None:
                    problems.append(
                        f"{source_label}: Patient {patient_id} "
                        "has no Clinical Assessment in the "
                        "local database."
                    )
                    continue

                metadata[
                    "Clinical Assessment ID"
                ] = str(
                    latest.get(
                        "assessment_id",
                        "",
                    )
                )

            if not metadata.get(
                "Recording Duration (hours)"
            ):
                metadata[
                    "Recording Duration (hours)"
                ] = self._recording_duration_hours(
                    Path(
                        str(
                            record.get(
                                "edf_path",
                                "",
                            )
                        )
                    )
                )

            validation = (
                validator.validate_record(
                    "Electrophysiology",
                    metadata,
                )
            )

            bad = [
                result
                for result in validation[
                    "results"
                ]
                if result[
                    "status"
                ] in {
                    "invalid",
                    "missing_required",
                }
            ]

            if bad:
                for result in bad:
                    problems.append(
                        f"{source_label} — "
                        f"{result['field_name']}: "
                        f"{result['message']}"
                    )
                continue

            modality = str(
                metadata.get(
                    "Recording Modality",
                    "",
                )
                or ""
            )

            if modality in {
                "Other",
                "Unknown",
            }:
                problems.append(
                    f"{source_label}: Recording Modality must "
                    "identify a BIDS EEG, iEEG, or MEG datatype."
                )
                continue

            if modality == (
                "Magnetoencephalography (MEG)"
            ):
                problems.append(
                    f"{source_label}: MEG conversion requires "
                    "the native acquisition format."
                )
                continue

            if modality not in (
                EPHYS_MODALITY_TO_DATATYPE
            ):
                problems.append(
                    f"{source_label}: Unsupported Recording Modality."
                )
                continue

            normalized = dict(
                record
            )
            normalized[
                "project"
            ] = project
            normalized[
                "session_id"
            ] = session_id
            normalized[
                "cocanot_metadata"
            ] = metadata
            normalized[
                "datatype"
            ] = (
                EPHYS_MODALITY_TO_DATATYPE[
                    modality
                ]
            )
            normalized[
                "status"
            ] = "Ready"
            normalized_records.append(
                normalized
            )

        return {
            "ok": not problems,
            "problems": problems,
            "records": (
                normalized_records
                if not problems
                else records
            ),
        }

    def ephys_bids_convert(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        validation = (
            self.ephys_bids_validate(
                payload
            )
        )

        if not validation[
            "ok"
        ]:
            return validation

        included = validation[
            "records"
        ]

        if not EPHYS_BIDS_CONVERTER.is_file():
            raise FileNotFoundError(
                "Electrophysiology BIDS converter "
                f"not found: {EPHYS_BIDS_CONVERTER}"
            )

        config = load_pipeline_config()
        scrubbed_dir = (
            config.electrophysiology.scrubbed_dir
        )
        output_dir = (
            config.electrophysiology.bids_output_dir
        )
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        manifest_path = (
            scrubbed_dir.parent
            / "bids_conversion_manifest.json"
        )

        payload_json = {
            "bids_version": "1.11.1",
            "records": [
                {
                    "edf_path": record[
                        "edf_path"
                    ],
                    "sidecar_path": record.get(
                        "sidecar_path",
                        "",
                    ),
                    "site_id": self.get_site_id(),
                    "project": record[
                        "project"
                    ],
                    "project_description": str(
                        record.get(
                            "project_description",
                            "",
                        )
                        or ""
                    ),
                    "session_id": record[
                        "session_id"
                    ],
                    "cocanot_metadata": record[
                        "cocanot_metadata"
                    ],
                    "metadata_confirmed": True,
                }
                for record in included
            ],
        }

        manifest_path.write_text(
            json.dumps(
                payload_json,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-u",
            str(
                EPHYS_BIDS_CONVERTER
            ),
            "--manifest",
            str(
                manifest_path
            ),
            "--output-dir",
            str(
                output_dir
            ),
        ]

        if bool(
            payload.get(
                "overwrite",
                False,
            )
        ):
            command.append(
                "--overwrite"
            )

        def save_metadata_after_success() -> None:
            records_to_save = []

            for record in included:
                records_to_save.append(
                    {
                        "metadata": dict(
                            record[
                                "cocanot_metadata"
                            ]
                        ),
                        "context": {
                            "project": record[
                                "project"
                            ],
                            "project_description": str(
                                record.get(
                                    "project_description",
                                    "",
                                )
                                or ""
                            ),
                            "session_id": record[
                                "session_id"
                            ],
                            "source_label": str(
                                record.get(
                                    "source_label",
                                    "",
                                )
                                or ""
                            ),
                            "edf_path": record[
                                "edf_path"
                            ],
                            "sidecar_path": str(
                                record.get(
                                    "sidecar_path",
                                    "",
                                )
                                or ""
                            ),
                            "bids_output_dir": str(
                                output_dir
                            ),
                        },
                    }
                )

            saved = self.repository.save_records(
                self.get_site_id(),
                "Electrophysiology",
                records_to_save,
                source="electrophysiology_pipeline",
            )
            self._ephys_log(
                f"Saved {len(saved)} Electrophysiology "
                "record(s) to Metadata Management."
            )

        self._start_process(
            command=command,
            workflow="ephys",
            description=(
                "Electrophysiology BIDS / "
                "CoCANoT conversion"
            ),
            on_success=(
                save_metadata_after_success
            ),
        )

        return {
            "ok": True,
            "status": (
                "Electrophysiology BIDS / "
                "CoCANoT conversion started"
            ),
            "manifest_path": str(
                manifest_path
            ),
            "record_count": len(
                included
            ),
        }

    def ephys_stop_operation(self) -> dict[str, Any]:
        self._stop_process("ephys")
        return {"ok": True, "status": "Stopped"}

    # ------------------------------------------------------------------
    # Imaging
    # ------------------------------------------------------------------

    def _raw_dicom_files(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[str] = set()

        for source_text in self.dicom_input_paths:
            source = Path(source_text).expanduser()

            if source.is_file():
                files = [source]
                source_name = source.parent.name
            elif source.is_dir():
                files = sorted(
                    path
                    for path in source.rglob("*")
                    if path.is_file()
                    and not path.name.startswith(".")
                )
                source_name = source.name
            else:
                continue

            for path in files:
                resolved = _resolve_text(path)

                if resolved in seen:
                    continue

                seen.add(resolved)
                rows.append(
                    {
                        "file_name": path.name,
                        "source_name": source_name,
                    }
                )

        return rows

    def _raw_nifti_files(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[str] = set()

        for source_text in self.nifti_input_paths:
            source = Path(source_text).expanduser()

            if source.is_file():
                files = [source] if _is_nifti(source) else []
                source_name = source.parent.name
            elif source.is_dir():
                files = sorted(
                    path
                    for path in source.rglob("*")
                    if _is_nifti(path)
                )
                source_name = source.name
            else:
                continue

            for path in files:
                resolved = _resolve_text(path)

                if resolved in seen:
                    continue

                seen.add(resolved)
                rows.append(
                    {
                        "file_name": path.name,
                        "source_name": source_name,
                    }
                )

        return rows

    def imaging_get_state(self) -> dict[str, Any]:
        try:
            settings = load_settings_dict()
        except Exception:
            settings = {}

        imaging = settings.get("imaging", {})

        return {
            "dicom_input_dirs": list(self.dicom_input_paths),
            "nifti_input_dirs": list(self.nifti_input_paths),
            "raw_dicom_files": self._raw_dicom_files(),
            "raw_nifti_files": self._raw_nifti_files(),
            "derivatives_dir": str(
                imaging.get("derivatives_dir", "") or ""
            ),
            "bids_output_dir": str(
                imaging.get("bids_output_dir", "") or ""
            ),
            "status": (
                "Running"
                if self._process_running(self.imaging_process)
                else "Ready"
            ),
            "logs": list(self.imaging_logs),
        }

    def _select_files(
        self,
        *,
        kind: str,
    ) -> list[str]:
        if self.window is None:
            return []

        file_types = (
            ("NIfTI files (*.nii)", "Compressed NIfTI files (*.nii.gz)", "All files (*.*)")
            if kind == "nifti"
            else ("DICOM files (*.dcm)", "All files (*.*)")
        )

        selected = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=file_types,
        )

        if not selected:
            return []

        if isinstance(selected, str):
            selected = [selected]

        values = [str(path) for path in selected]

        if kind == "nifti":
            values = [
                value
                for value in values
                if _is_nifti(Path(value))
            ]

        return values

    def _select_folder(self) -> list[str]:
        if self.window is None:
            return []

        selected = self.window.create_file_dialog(
            webview.FileDialog.FOLDER,
        )

        if not selected:
            return []

        if isinstance(selected, str):
            selected = [selected]

        return [str(path) for path in selected]

    def imaging_add_dicom_files(self) -> dict[str, Any]:
        self.dicom_input_paths = _unique_paths(
            list(self.dicom_input_paths)
            + self._select_files(kind="dicom")
        )
        self._imaging_log("Updated DICOM file sources.")
        return self.imaging_get_state()

    def imaging_add_dicom_folders(self) -> dict[str, Any]:
        self.dicom_input_paths = _unique_paths(
            list(self.dicom_input_paths)
            + self._select_folder()
        )
        self._imaging_log("Updated DICOM folder sources.")
        return self.imaging_get_state()

    def imaging_add_nifti_files(self) -> dict[str, Any]:
        self.nifti_input_paths = _unique_paths(
            list(self.nifti_input_paths)
            + self._select_files(kind="nifti")
        )
        self._imaging_log("Updated NIfTI file sources.")
        return self.imaging_get_state()

    def imaging_add_nifti_folders(self) -> dict[str, Any]:
        self.nifti_input_paths = _unique_paths(
            list(self.nifti_input_paths)
            + self._select_folder()
        )
        self._imaging_log("Updated NIfTI folder sources.")
        return self.imaging_get_state()

    def imaging_remove_sources(
        self,
        kind: str,
        indices: list[int],
    ) -> dict[str, Any]:
        target = (
            self.dicom_input_paths
            if kind == "dicom"
            else self.nifti_input_paths
        )

        for index in sorted(
            {
                int(value)
                for value in indices or []
            },
            reverse=True,
        ):
            if 0 <= index < len(target):
                del target[index]

        self._imaging_log(
            f"Updated {kind.upper()} source list."
        )
        return self.imaging_get_state()

    def imaging_save_settings(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.dicom_input_paths = _unique_paths(
            str(value)
            for value in payload.get(
                "dicom_input_dirs",
                self.dicom_input_paths,
            )
            if value
        )
        self.nifti_input_paths = _unique_paths(
            str(value)
            for value in payload.get(
                "nifti_input_dirs",
                self.nifti_input_paths,
            )
            if value
        )

        self._save_imaging_settings(
            derivatives_dir=str(
                payload.get(
                    "derivatives_dir",
                    "",
                )
            ),
            bids_output_dir=str(
                payload.get(
                    "bids_output_dir",
                    "",
                )
            ),
        )

        self._imaging_log(
            "Imaging folder settings saved."
        )
        return self.imaging_get_state()

    def _classify_imaging_sources(
        self,
    ) -> tuple[list[str], list[str]]:
        return (
            list(self.dicom_input_paths),
            list(self.nifti_input_paths),
        )

    def _save_imaging_settings(
        self,
        *,
        derivatives_dir: str,
        bids_output_dir: str,
    ):
        derivatives_dir = str(derivatives_dir or "").strip()
        bids_output_dir = str(bids_output_dir or "").strip()

        if not self.dicom_input_paths and not self.nifti_input_paths:
            raise ValueError("Add at least one DICOM or NIfTI file/folder.")

        if not derivatives_dir or not bids_output_dir:
            raise ValueError(
                "Select derivatives and BIDS output folders."
            )

        dicom_sources, nifti_sources = (
            self._classify_imaging_sources()
        )

        config_inputs: list[str] = []

        for source_text in (
            dicom_sources + nifti_sources
        ):
            source = Path(source_text).expanduser()

            if source.is_file():
                source = source.parent

            resolved = _resolve_text(source)
            if resolved not in config_inputs:
                config_inputs.append(resolved)

        # IMPORTANT: this matches the signature used by the existing
        # ImagingDashboard. It accepts input_dirs, not dicom_input_dirs.
        settings = build_imaging_settings_dict(
            input_dirs=config_inputs,
            derivatives_dir=derivatives_dir,
            bids_output_dir=bids_output_dir,
        )

        imaging = settings.setdefault(
            "imaging",
            {},
        )
        imaging["dicom_input_dirs"] = list(
            dicom_sources
        )
        imaging["nifti_input_dirs"] = list(
            nifti_sources
        )
        imaging.pop(
            "nifti_input_files",
            None,
        )

        save_settings_dict(settings)

        config = load_imaging_config()
        self._create_imaging_stage_dirs(config)

        return config

    @staticmethod
    def _imaging_stage_paths(
        config,
    ) -> dict[str, Path]:
        derivatives = config.imaging.derivatives_dir

        return {
            "converted": derivatives / "converted_nifti",
            "scrubbed": derivatives / "scrubbed_header",
            "defaced": derivatives / "scrubbed_defaced",
            "external_defaced": derivatives / "external_defaced",
            "logs": derivatives / "logs",
            "review_state": derivatives / REVIEW_STATE_FILENAME,
        }

    def _create_imaging_stage_dirs(
        self,
        config,
    ) -> None:
        stages = self._imaging_stage_paths(config)

        for name, path in stages.items():
            if name == "review_state":
                path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
            else:
                path.mkdir(
                    parents=True,
                    exist_ok=True,
                )

        config.imaging.bids_output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )


    def imaging_get_accepted_files(self) -> dict[str, Any]:
        """
        Return exactly the Imaging files accepted during review.

        This mirrors the original Tkinter ImagingDashboard._accepted_files()
        behavior and uses imaging_review_state.json as the source of truth.
        """
        config = load_imaging_config()
        stages = self._imaging_stage_paths(config)
        state_path = stages["review_state"]

        if not state_path.exists():
            return {
                "files": [],
                "held_count": 0,
            }

        try:
            state = json.loads(
                state_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            json.JSONDecodeError,
        ):
            return {
                "files": [],
                "held_count": 0,
            }

        accepted: list[dict[str, Any]] = []
        held_count = 0

        for relative_text, saved in state.items():
            if isinstance(saved, str):
                status = saved
                accepted_path = ""
                defacing_source = (
                    "pydeface"
                    if status == "Accepted"
                    else ""
                )

            elif isinstance(saved, dict):
                status = str(
                    saved.get(
                        "status",
                        "",
                    )
                )
                accepted_path = str(
                    saved.get(
                        "accepted_defaced_path",
                        "",
                    )
                    or ""
                )
                defacing_source = str(
                    saved.get(
                        "defacing_source",
                        "",
                    )
                    or ""
                )

            else:
                continue

            if status == "On Hold - Needs Defaced Replacement":
                held_count += 1

            if status not in {
                "Accepted",
                "Accepted - External",
            }:
                continue

            selected_path: Path | None = None

            if accepted_path:
                candidate = Path(
                    accepted_path
                ).expanduser()

                if candidate.is_file():
                    selected_path = candidate.resolve()

            if selected_path is None:
                relative = Path(
                    relative_text
                )
                base = self._strip_nifti_suffix(
                    relative
                )

                candidates = [
                    stages["defaced"]
                    / relative.parent
                    / f"{base}_scrubbed_defaced.nii.gz",
                    stages["defaced"]
                    / relative.parent
                    / f"{base}_scrubbed_defaced.nii",
                ]

                selected_path = next(
                    (
                        path.resolve()
                        for path in candidates
                        if path.exists()
                    ),
                    None,
                )

            if selected_path is None:
                continue

            accepted.append(
                {
                    "id": f"accepted-{len(accepted) + 1}",
                    "source_key": str(relative_text),
                    "file_name": selected_path.name,
                    "nifti_path": str(selected_path),
                    "status": status,
                    "defacing_source": (
                        defacing_source
                        or (
                            "external"
                            if "external_defaced"
                            in selected_path.parts
                            else "pydeface"
                        )
                    ),
                }
            )

        accepted.sort(
            key=lambda item: str(
                item["source_key"]
            ).casefold()
        )

        return {
            "files": accepted,
            "held_count": held_count,
        }



    @staticmethod
    def _file_hash(path: Path) -> str:
        """SHA-256 helper used by the original Tkinter duplicate check."""
        digest = hashlib.sha256()

        with path.open("rb") as file:
            while True:
                chunk = file.read(1024 * 1024)

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()

    def _index_existing_bids(
        self,
        output_dir: Path,
    ) -> dict[int, list[dict[str, Any]]]:
        """
        Index existing BIDS NIfTI files by byte size.

        This mirrors the original Tkinter BIDSMetadataWindow. File size is
        only a fast candidate filter; exact duplicate identity is confirmed
        with SHA-256 in _existing_bids_export().
        """
        index: dict[int, list[dict[str, Any]]] = {}

        if not output_dir.exists():
            return index

        for path in output_dir.rglob("*"):
            if not _is_nifti(path):
                continue

            try:
                file_size = path.stat().st_size
            except OSError:
                continue

            json_path = _matching_json(path)
            metadata: dict[str, Any] = {}

            if json_path is not None:
                try:
                    loaded = json.loads(
                        json_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    loaded = {}

                if isinstance(loaded, dict):
                    metadata = loaded

            index.setdefault(
                file_size,
                [],
            ).append(
                {
                    "nifti_path": str(path.resolve()),
                    "json_path": (
                        str(json_path.resolve())
                        if json_path is not None
                        else ""
                    ),
                    "metadata": metadata,
                    "sha256": "",
                }
            )

        return index

    def _existing_bids_export(
        self,
        path: Path,
        index: dict[int, list[dict[str, Any]]],
    ) -> dict[str, Any] | None:
        """
        Return an exact already-exported BIDS match for path, if one exists.

        The check is identical in spirit to the original GUI:
        byte-size match first, SHA-256 equality second.
        """
        try:
            file_size = path.stat().st_size
        except OSError:
            return None

        candidates = index.get(
            file_size,
            [],
        )

        if not candidates:
            return None

        try:
            source_hash = self._file_hash(path)
        except OSError:
            return None

        for candidate in candidates:
            candidate_hash = str(
                candidate.get("sha256")
                or ""
            )

            if not candidate_hash:
                try:
                    candidate_hash = self._file_hash(
                        Path(
                            str(
                                candidate["nifti_path"]
                            )
                        )
                    )
                except OSError:
                    continue

                candidate["sha256"] = candidate_hash

            if candidate_hash == source_hash:
                return candidate

        return None

    @staticmethod
    def _cocanot_metadata_from_existing_bids(
        existing_metadata: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Restore CoCANoT fields from the existing BIDS JSON sidecar."""
        metadata: dict[str, Any] = {
            "CoCANoT Patient ID": str(
                existing_metadata.get(
                    "CoCANoTPatientID",
                    "",
                )
                or ""
            ),
            "Clinical Assessment ID": str(
                existing_metadata.get(
                    "ClinicalAssessmentID",
                    "",
                )
                or ""
            ),
            "Image ID": str(
                existing_metadata.get(
                    "ImageID",
                    "",
                )
                or ""
            ),
            "Surgery ID": str(
                existing_metadata.get(
                    "SurgeryID",
                    "",
                )
                or ""
            ),
            "Imaging Modality": str(
                existing_metadata.get(
                    "ImagingModality",
                    "",
                )
                or ""
            ),
            "Purpose of Imaging (multiselect)": list(
                existing_metadata.get(
                    "PurposeOfImaging",
                    [],
                )
                or []
            ),
            "Timing Relative to Surgery": str(
                existing_metadata.get(
                    "TimingRelativeToSurgery",
                    "",
                )
                or ""
            ),
            "Imaging Findings (multiselect)": list(
                existing_metadata.get(
                    "ImagingFindings",
                    [],
                )
                or []
            ),
            "Other Purpose of Imaging (if applicable; free text)": str(
                existing_metadata.get(
                    "OtherPurposeOfImaging",
                    "",
                )
                or ""
            ),
            "Other Imaging Findings (if applicable; free text)": str(
                existing_metadata.get(
                    "OtherImagingFindings",
                    "",
                )
                or ""
            ),
            "Comments (free text)": str(
                existing_metadata.get(
                    "Comments",
                    "",
                )
                or ""
            ),
        }

        if metadata["Imaging Modality"] == "MRI":
            sequence_value = str(
                existing_metadata.get(
                    "MRISequence",
                    "",
                )
                or ""
            ).strip()

            for rule in rules:
                field_name = str(
                    rule.get(
                        "field_name",
                        "",
                    )
                )

                if field_name not in MRI_SEQUENCE_FIELDS:
                    continue

                if rule.get("input_type") == "multi_select":
                    metadata[field_name] = (
                        [sequence_value]
                        if sequence_value
                        else []
                    )
                else:
                    metadata[field_name] = sequence_value

                break

        return metadata

    @staticmethod
    def _imaging_rule_payload(rule: dict[str, Any]) -> dict[str, Any]:
        """Return the JSON-safe rule subset needed by the React form."""
        return {
            "field_name": str(rule.get("field_name", "")),
            "ui_prompt": str(
                rule.get("ui_prompt")
                or rule.get("field_name")
                or ""
            ),
            "input_type": str(rule.get("input_type", "free_text")),
            "allowed_values": [
                str(value)
                for value in (
                    rule.get("allowed_values")
                    or []
                )
            ],
            "required": bool(rule.get("required", False)),
            "required_if_field": str(
                rule.get("required_if_field")
                or ""
            ),
            "required_if_operator": str(
                rule.get("required_if_operator")
                or ""
            ),
            "required_if_value": rule.get("required_if_value"),
            "system_generated": bool(
                rule.get("system_generated", False)
            ),
            "help_text": str(
                rule.get("help_text")
                or ""
            ),
            "dictionary_version": str(
                rule.get("dictionary_version")
                or ""
            ),
        }

    @staticmethod
    def _imaging_sequence_value(
        metadata: dict[str, Any],
    ) -> str:
        for field_name in MRI_SEQUENCE_FIELDS:
            value = metadata.get(field_name)

            if isinstance(value, list):
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

            text = str(value or "").strip()
            if text:
                return text

        return ""

    @staticmethod
    def _derive_bids_subject(
        patient_id: str,
    ) -> str:
        return re.sub(
            r"[^A-Za-z0-9+]",
            "",
            str(patient_id or ""),
        )

    def _imaging_dictionary_context(
        self,
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        MetadataValidator,
    ]:
        """
        Load the Imaging dictionary once per operation and return the
        dictionary, Imaging field rules, and validator together.

        Keeping this in one helper prevents Step 5 methods from repeating
        dictionary-loading logic or accidentally using an undefined `rules`
        variable.
        """
        dictionary = load_dictionary(
            METADATA_DICTIONARY
        )

        rules = dictionary[
            "tables"
        ][
            "Imaging"
        ][
            "fields"
        ]

        validator = MetadataValidator(
            dictionary
        )

        return (
            dictionary,
            rules,
            validator,
        )

    @staticmethod
    def _dictionary_version_from_rules(
        rules: list[dict[str, Any]],
    ) -> str:
        if not rules:
            return ""

        return str(
            rules[0].get(
                "dictionary_version",
                "",
            )
            or ""
        )

    def imaging_bids_get_state(self) -> dict[str, Any]:
        accepted_payload = self.imaging_get_accepted_files()
        accepted = accepted_payload["files"]

        if not accepted:
            raise ValueError(
                "No accepted images were found. "
                "Accept at least one image in Step 4 Review first."
            )

        _dictionary, rules, _validator = (
            self._imaging_dictionary_context()
        )

        config = load_imaging_config()
        output_dir = config.imaging.bids_output_dir

        existing_bids_by_size = self._index_existing_bids(
            output_dir
        )

        records: list[dict[str, Any]] = []

        for index, image in enumerate(
            accepted,
            start=1,
        ):
            nifti_path = Path(
                str(
                    image["nifti_path"]
                )
            ).expanduser().resolve()

            existing_export = self._existing_bids_export(
                nifti_path,
                existing_bids_by_size,
            )

            project = ""
            project_description = ""
            session_id = ""
            participant_id = ""
            cocanot_metadata: dict[str, Any] = {}

            if existing_export is not None:
                existing_path = Path(
                    str(
                        existing_export["nifti_path"]
                    )
                )
                existing_metadata = dict(
                    existing_export.get(
                        "metadata",
                        {},
                    )
                    or {}
                )

                try:
                    relative = existing_path.relative_to(
                        output_dir
                    )
                    parts = relative.parts

                    if parts:
                        project = parts[0]

                    session_part = next(
                        (
                            part
                            for part in parts
                            if part.startswith("ses-")
                        ),
                        "",
                    )

                    if session_part:
                        session_id = session_part[4:]

                except ValueError:
                    pass

                cocanot_metadata = (
                    self._cocanot_metadata_from_existing_bids(
                        existing_metadata,
                        rules,
                    )
                )

                participant_id = str(
                    existing_metadata.get(
                        "CoCANoTPatientID",
                        "",
                    )
                    or ""
                )

                dataset_description = (
                    output_dir
                    / project
                    / "dataset_description.json"
                )

                if dataset_description.exists():
                    try:
                        dataset_payload = json.loads(
                            dataset_description.read_text(
                                encoding="utf-8"
                            )
                        )
                    except (
                        OSError,
                        json.JSONDecodeError,
                    ):
                        dataset_payload = {}

                    if isinstance(
                        dataset_payload,
                        dict,
                    ):
                        project_description = str(
                            dataset_payload.get(
                                "Description",
                                "",
                            )
                            or ""
                        )

            records.append(
                {
                    "id": f"image-{index}",
                    # Original behavior: exact duplicates are excluded by default.
                    "include": existing_export is None,
                    "nifti_path": str(nifti_path),
                    "source_label": image["file_name"],
                    "source_key": image["source_key"],
                    "defacing_source": image["defacing_source"],
                    "project": project,
                    "project_description": project_description,
                    "session_id": session_id,
                    "participant_id": self._derive_bids_subject(
                        participant_id
                    ),
                    "cocanot_metadata": cocanot_metadata,
                    "datatype": "",
                    "suffix": "",
                    "existing_export": existing_export,
                    "metadata_confirmed": False,
                    "status": (
                        "Already exported"
                        if existing_export is not None
                        else "Missing metadata"
                    ),
                }
            )

        return {
            "site_id": self.get_site_id(),
            "records": records,
            "rules": [
                self._imaging_rule_payload(rule)
                for rule in rules
                if not bool(
                    rule.get(
                        "system_generated",
                        False,
                    )
                )
            ],
            "held_count": int(
                accepted_payload.get(
                    "held_count",
                    0,
                )
            ),
            "bids_output_dir": str(
                output_dir
            ),
            "local_database": {
                "site_id": self.get_site_id(),
                "connected": bool(
                    self.get_site_id()
                ),
            },
        }


    @staticmethod
    def _normalize_imaging_metadata_values(
        metadata: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return CoCANoTAPI._normalize_metadata_values(
            metadata,
            rules,
        )


    def _latest_clinical_assessment_for_patient(
        self,
        patient_id: str,
    ) -> dict[str, Any] | None:
        patient_id = str(
            patient_id or ""
        ).strip()

        if not patient_id:
            return None

        return self.store.latest_clinical_assessment(
            self.get_site_id(),
            patient_id,
        )

    @staticmethod
    def _included_imaging_records(
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            record
            for record in records
            if bool(
                record.get(
                    "include",
                    True,
                )
            )
        ]

    def imaging_bids_validate(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        records = payload.get("records") or []
        included = [
            record
            for record in records
            if bool(record.get("include", True))
        ]

        if not included:
            raise ValueError(
                "Include at least one image."
            )

        overwrite = bool(
            payload.get(
                "overwrite",
                False,
            )
        )

        existing_included = [
            record
            for record in included
            if record.get(
                "existing_export"
            )
        ]

        if existing_included and not overwrite:
            names = ", ".join(
                str(
                    record.get(
                        "source_label",
                        "",
                    )
                )
                for record in existing_included[:5]
            )

            return {
                "ok": False,
                "problems": [
                    (
                        "One or more included images already exist in the "
                        "BIDS output. Exclude them or enable overwrite. "
                        f"Existing: {names}"
                    )
                ],
                "records": records,
            }

        _dictionary, rules, validator = (
            self._imaging_dictionary_context()
        )

        problems: list[str] = []
        normalized_records: list[dict[str, Any]] = []

        for record in included:
            source_label = str(
                record.get(
                    "source_label",
                    "",
                )
            )
            project = str(
                record.get(
                    "project",
                    "",
                )
            ).strip()

            if not project:
                problems.append(
                    f"{source_label}: Project is required."
                )
                continue

            metadata = dict(
                record.get(
                    "cocanot_metadata",
                    {},
                )
                or {}
            )

            metadata = self._normalize_imaging_metadata_values(
                metadata,
                rules,
            )

            patient_id = str(
                metadata.get(
                    "CoCANoT Patient ID",
                    "",
                )
                or ""
            ).strip()

            if patient_id:
                participant_id = (
                    self._derive_bids_subject(
                        patient_id
                    )
                )

                if not participant_id:
                    problems.append(
                        f"{source_label}: CoCANoT Patient ID cannot "
                        "be converted to a BIDS subject label."
                    )
                    continue
            else:
                participant_id = ""

            # Step 5 must resolve Clinical Assessment ID from the same
            # local database used by the Tkinter workflow. Do this even when
            # a value was preloaded from an existing BIDS sidecar so the local
            # database remains the source of truth.
            if patient_id:
                latest = (
                    self._latest_clinical_assessment_for_patient(
                        patient_id
                    )
                )

                if latest is None:
                    problems.append(
                        f"{source_label}: Patient {patient_id} has no "
                        "Clinical Assessment in the local database."
                    )
                    continue

                metadata[
                    "Clinical Assessment ID"
                ] = str(
                    latest.get(
                        "assessment_id",
                        "",
                    )
                )

            validation = (
                validator.validate_record(
                    "Imaging",
                    metadata,
                )
            )

            if not validation[
                "passes_automatic_validation"
            ]:
                for result in validation["results"]:
                    if result["status"] in {
                        "invalid",
                        "missing_required",
                    }:
                        problems.append(
                            f"{source_label} — "
                            f"{result['field_name']}: "
                            f"{result['message']}"
                        )
                continue

            modality = str(
                metadata.get(
                    "Imaging Modality",
                    "",
                )
                or ""
            ).strip()

            sequence = self._imaging_sequence_value(
                metadata
            )

            if modality == "MRI":
                sequence_values: list[str] = []

                for sequence_field in MRI_SEQUENCE_FIELDS:
                    raw_sequence = metadata.get(
                        sequence_field
                    )

                    if isinstance(
                        raw_sequence,
                        list,
                    ):
                        sequence_values = [
                            str(value).strip()
                            for value in raw_sequence
                            if str(value).strip()
                        ]
                        if sequence_values:
                            break

                    elif str(
                        raw_sequence
                        or ""
                    ).strip():
                        sequence_values = [
                            str(
                                raw_sequence
                            ).strip()
                        ]
                        break

                if len(sequence_values) > 1:
                    problems.append(
                        f"{source_label}: MRI Sequence is a multiselect field, "
                        "but one image can map to only one BIDS datatype/suffix. "
                        "Select exactly one MRI sequence for this image."
                    )
                    continue

                datatype, suffix = (
                    MRI_SEQUENCE_MAP.get(
                        sequence,
                        ("", ""),
                    )
                )

                if not datatype or not suffix:
                    problems.append(
                        f"{source_label}: Select one supported MRI sequence."
                    )
                    continue

            elif modality == "CT":
                datatype, suffix = (
                    "ct",
                    "ct",
                )

            else:
                datatype, suffix = (
                    "",
                    "",
                )

            normalized = dict(record)
            normalized["project"] = project
            normalized["participant_id"] = participant_id
            normalized["cocanot_metadata"] = metadata
            normalized["datatype"] = datatype
            normalized["suffix"] = suffix
            normalized["metadata_validation"] = validation
            normalized["status"] = "Ready for confirmation"

            normalized_records.append(
                normalized
            )

        return {
            "ok": not problems,
            "problems": problems,
            "records": normalized_records,
        }

    def imaging_bids_convert(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        validation = self.imaging_bids_validate(
            payload
        )

        if not validation["ok"]:
            return validation

        included = validation["records"]

        if not included:
            raise ValueError(
                "No validated images are available for conversion."
            )

        if not IMAGING_BIDS_CONVERTER.is_file():
            raise FileNotFoundError(
                f"NIfTI to BIDS converter not found: {IMAGING_BIDS_CONVERTER}"
            )

        config = load_imaging_config()
        output_dir = config.imaging.bids_output_dir
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        first_path = Path(
            str(
                included[0]["nifti_path"]
            )
        )
        manifest_path = (
            first_path.parent.parent
            / "nifti_bids_manifest.json"
        )

        _dictionary, rules, _validator = (
            self._imaging_dictionary_context()
        )
        dictionary_version = (
            self._dictionary_version_from_rules(
                rules
            )
        )

        manifest = {
            "bids_version": "1.11.1",
            "dictionary_version": dictionary_version,
            "site_id": self.get_site_id(),
            "records": [
                {
                    "nifti_path": record["nifti_path"],
                    "project": record["project"],
                    "project_description": str(
                        record.get(
                            "project_description",
                            "",
                        )
                        or ""
                    ),
                    "participant_id": record["participant_id"],
                    "session_id": str(
                        record.get(
                            "session_id",
                            "",
                        )
                        or ""
                    ),
                    "cocanot_metadata": record[
                        "cocanot_metadata"
                    ],
                    "datatype": record["datatype"],
                    "suffix": record["suffix"],
                    "metadata_confirmed": True,
                    "defacing_source": str(
                        record.get(
                            "defacing_source",
                            "pydeface",
                        )
                        or "pydeface"
                    ),
                }
                for record in included
            ],
        }

        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        command = [
            sys.executable,
            "-u",
            str(IMAGING_BIDS_CONVERTER),
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
        ]

        if bool(
            payload.get(
                "overwrite",
                False,
            )
        ):
            command.append(
                "--overwrite"
            )

        self._start_process(
            command=command,
            workflow="imaging",
            description="Imaging BIDS / CoCANoT conversion",
        )

        return {
            "ok": True,
            "status": "Imaging BIDS / CoCANoT conversion started",
            "manifest_path": str(manifest_path),
            "record_count": len(included),
        }

    def imaging_run_operation(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        operation = str(
            payload.get("operation", "")
        ).strip().lower()

        self.dicom_input_paths = _unique_paths(
            str(value)
            for value in payload.get(
                "dicom_input_dirs",
                self.dicom_input_paths,
            )
            if value
        )
        self.nifti_input_paths = _unique_paths(
            str(value)
            for value in payload.get(
                "nifti_input_dirs",
                self.nifti_input_paths,
            )
            if value
        )

        config = self._save_imaging_settings(
            derivatives_dir=str(
                payload.get("derivatives_dir", "")
            ),
            bids_output_dir=str(
                payload.get("bids_output_dir", "")
            ),
        )

        overwrite = bool(
            payload.get("overwrite", False)
        )

        stages = self._imaging_stage_paths(
            config
        )

        if operation == "prepare":
            return self._prepare_imaging(
                config=config,
                stages=stages,
                overwrite=overwrite,
            )

        if operation == "scrub":
            if not IMAGING_HEADER_SCRUBBER.is_file():
                raise FileNotFoundError(
                    f"NIfTI header scrubber not found: {IMAGING_HEADER_SCRUBBER}"
                )

            command = [
                sys.executable,
                "-u",
                str(IMAGING_HEADER_SCRUBBER),
                "--input-dir",
                str(stages["converted"]),
                "--output-dir",
                str(stages["scrubbed"]),
            ]

            if overwrite:
                command.append("--overwrite")

            self._start_process(
                command=command,
                workflow="imaging",
                description="NIfTI header scrubbing",
            )

            return {
                "ok": True,
                "status": "NIfTI header scrubbing started",
            }

        if operation == "deface":
            if not IMAGING_DEFACER.is_file():
                raise FileNotFoundError(
                    f"PyDeface script not found: {IMAGING_DEFACER}"
                )

            command = [
                sys.executable,
                "-u",
                str(IMAGING_DEFACER),
                "--input-dir",
                str(stages["scrubbed"]),
                "--output-dir",
                str(stages["defaced"]),
                "--log-dir",
                str(stages["logs"] / "pydeface"),
            ]

            if overwrite:
                command.append("--overwrite")

            self._start_process(
                command=command,
                workflow="imaging",
                description="NIfTI defacing",
            )

            return {
                "ok": True,
                "status": "NIfTI defacing started",
            }

        if operation == "review":
            has_converted = (
                stages["converted"].is_dir()
                and any(
                    _is_nifti(path)
                    for path in stages["converted"].rglob("*")
                    if path.is_file()
                )
            )
            has_scrubbed = (
                stages["scrubbed"].is_dir()
                and any(
                    _is_nifti(path)
                    for path in stages["scrubbed"].rglob("*")
                    if path.is_file()
                )
            )
            has_defaced = (
                stages["defaced"].is_dir()
                and any(
                    _is_nifti(path)
                    for path in stages["defaced"].rglob("*")
                    if path.is_file()
                )
            )

            if not (
                has_converted
                and has_scrubbed
                and has_defaced
            ):
                raise ValueError(
                    "Run preparation, header scrubbing, and defacing "
                    "before opening Imaging review."
                )

            return {
                "ok": True,
                "status": "Ready for imaging review",
                "log": "Opening React imaging review.",
            }

        if operation == "bids":
            accepted_payload = self.imaging_get_accepted_files()
            accepted = accepted_payload["files"]
            held_count = int(
                accepted_payload.get(
                    "held_count",
                    0,
                )
            )

            if not accepted:
                raise ValueError(
                    "No accepted images were found. "
                    "Accept at least one image in Step 4 Review first."
                )

            return {
                "ok": True,
                "status": "Ready for Imaging metadata review",
                "accepted_files": accepted,
                "held_count": held_count,
                "log": (
                    f"Loaded {len(accepted)} accepted image"
                    f"{'' if len(accepted) == 1 else 's'} "
                    "for Metadata & BIDS."
                ),
            }

        raise ValueError(
            f"Unknown Imaging operation: {operation}"
        )

    def _prepare_imaging(
        self,
        *,
        config,
        stages: dict[str, Path],
        overwrite: bool,
    ) -> dict[str, Any]:
        dicom_sources, nifti_sources = (
            self._classify_imaging_sources()
        )

        # Prepare existing NIfTI data immediately. This mirrors the current
        # Tkinter _prepare_selected_nifti_files behavior, including sidecars.
        copied = self._prepare_selected_nifti_files(
            nifti_sources,
            stages["converted"],
            overwrite,
        )

        if not dicom_sources:
            self._imaging_log(
                f"Prepared {copied} NIfTI file(s)."
            )

            return {
                "ok": True,
                "status": "Imaging preparation completed",
                "log": f"Prepared {copied} NIfTI file(s).",
            }

        if not IMAGING_DICOM_CONVERTER.is_file():
            raise FileNotFoundError(
                f"DICOM converter not found: {IMAGING_DICOM_CONVERTER}"
            )

        dicom_dirs: list[Path] = []
        dicom_files: list[Path] = []

        for source_text in dicom_sources:
            source = Path(source_text).expanduser()

            if source.is_file():
                dicom_files.append(source)
            elif source.is_dir():
                dicom_dirs.append(source)
            else:
                raise ValueError(
                    f"DICOM source does not exist: {source}"
                )

        # The existing Tkinter dashboard stages individually selected DICOM
        # files into one directory before invoking dicom_to_nifti.py.
        if dicom_files:
            staged_dir = (
                config.imaging.derivatives_dir
                / "selected_dicom_files"
            )

            if staged_dir.exists() and overwrite:
                shutil.rmtree(staged_dir)

            staged_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            for index, source in enumerate(
                dicom_files,
                start=1,
            ):
                destination = (
                    staged_dir
                    / f"{index:05d}_{source.name}"
                )

                if destination.exists() and not overwrite:
                    continue

                shutil.copy2(source, destination)

            dicom_dirs.append(staged_dir)

        command = [
            sys.executable,
            "-u",
            str(IMAGING_DICOM_CONVERTER),
        ]

        for input_dir in dicom_dirs:
            command.extend(
                [
                    "--input-dir",
                    str(input_dir),
                ]
            )

        command.extend(
            [
                "--output-dir",
                str(stages["converted"]),
            ]
        )

        if overwrite:
            command.append("--overwrite")

        self._start_process(
            command=command,
            workflow="imaging",
            description="DICOM to NIfTI conversion",
        )

        return {
            "ok": True,
            "status": "DICOM to NIfTI conversion started",
            "log": (
                f"Prepared {copied} existing NIfTI file(s); "
                f"started DICOM conversion from {len(dicom_dirs)} source(s)."
            ),
        }

    def _prepare_selected_nifti_files(
        self,
        sources: list[str],
        converted_dir: Path,
        overwrite: bool,
    ) -> int:
        copied = 0

        for source_index, source_text in enumerate(
            sources,
            start=1,
        ):
            source = Path(source_text).expanduser()

            if source.is_file():
                if not _is_nifti(source):
                    continue

                nifti_files = [source]
                source_dir = source.parent
                source_root = (
                    converted_dir
                    / f"nifti-file-{source_index:03d}"
                )
                keep_relative_parent = False

            elif source.is_dir():
                nifti_files = sorted(
                    path
                    for path in source.rglob("*")
                    if _is_nifti(path)
                )
                source_dir = source
                source_root = (
                    converted_dir
                    / f"nifti-source-{source_index:03d}"
                )
                keep_relative_parent = True

            else:
                continue

            for nifti_path in nifti_files:
                relative_parent = (
                    nifti_path.relative_to(source_dir).parent
                    if keep_relative_parent
                    else Path()
                )

                destination_dir = (
                    source_root
                    / relative_parent
                )
                destination_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                destination = (
                    destination_dir
                    / nifti_path.name
                )

                if destination.exists() and not overwrite:
                    self._imaging_log(
                        f"Skipping existing prepared NIfTI: {destination}"
                    )
                    continue

                shutil.copy2(
                    nifti_path,
                    destination,
                )

                sidecar = _matching_json(
                    nifti_path
                )
                if sidecar is not None:
                    shutil.copy2(
                        sidecar,
                        destination_dir / sidecar.name,
                    )

                for extra in _matching_extra_sidecars(
                    nifti_path
                ):
                    shutil.copy2(
                        extra,
                        destination_dir / extra.name,
                    )

                copied += 1
                self._imaging_log(
                    f"Prepared NIfTI: {nifti_path} -> {destination}"
                )

        return copied

    # ------------------------------------------------------------------
    # Imaging review API
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_nifti_suffix(path: Path) -> str:
        if path.name.endswith(".nii.gz"):
            return path.name[:-7]
        if path.name.endswith(".nii"):
            return path.name[:-4]
        return path.stem

    @staticmethod
    def _load_review_state(state_path: Path) -> dict[str, dict[str, str]]:
        if not state_path.exists():
            return {}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, dict[str, str]] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                normalized[str(key)] = {
                    "status": value,
                    "accepted_defaced_path": "",
                    "defacing_source": "pydeface" if value == "Accepted" else "",
                }
            elif isinstance(value, dict):
                normalized[str(key)] = {
                    "status": str(value.get("status", "Pending")),
                    "accepted_defaced_path": str(value.get("accepted_defaced_path", "") or ""),
                    "defacing_source": str(value.get("defacing_source", "") or ""),
                }
        return normalized

    @staticmethod
    def _save_review_state(state_path: Path, state: dict[str, dict[str, str]]) -> None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def _imaging_review_items(self) -> tuple[list[dict[str, Any]], Path]:
        config = load_imaging_config()
        stages = self._imaging_stage_paths(config)
        prepared_dir = stages["converted"]
        scrubbed_dir = stages["scrubbed"]
        defaced_dir = stages["defaced"]
        state_path = stages["review_state"]
        review_state = self._load_review_state(state_path)
        items: list[dict[str, Any]] = []

        if not prepared_dir.exists():
            return items, state_path

        for prepared_path in sorted(path for path in prepared_dir.rglob("*") if _is_nifti(path)):
            relative = prepared_path.relative_to(prepared_dir)
            base = self._strip_nifti_suffix(prepared_path)
            scrubbed_candidates = [
                scrubbed_dir / relative.parent / f"{base}_scrubbed.nii.gz",
                scrubbed_dir / relative.parent / f"{base}_scrubbed.nii",
            ]
            scrubbed_path = next((path for path in scrubbed_candidates if path.exists()), None)
            if scrubbed_path is None:
                continue

            scrubbed_base = self._strip_nifti_suffix(scrubbed_path)
            defaced_candidates = [
                defaced_dir / relative.parent / f"{scrubbed_base}_defaced.nii.gz",
                defaced_dir / relative.parent / f"{scrubbed_base}_defaced.nii",
            ]
            automated_defaced = next((path for path in defaced_candidates if path.exists()), None)
            if automated_defaced is None:
                continue

            key = str(relative)
            saved = review_state.get(key, {})
            accepted_path = str(saved.get("accepted_defaced_path", "") or "")
            review_defaced = automated_defaced
            if accepted_path:
                candidate = Path(accepted_path).expanduser()
                if candidate.is_file():
                    review_defaced = candidate.resolve()

            items.append({
                "id": str(len(items)),
                "key": key,
                "status": str(saved.get("status", "Pending")),
                "prepared_path": str(prepared_path.resolve()),
                "scrubbed_path": str(scrubbed_path.resolve()),
                "automated_defaced_path": str(automated_defaced.resolve()),
                "review_defaced_path": str(review_defaced.resolve()),
                "accepted_defaced_path": accepted_path,
                "defacing_source": str(saved.get("defacing_source", "") or ""),
            })
        return items, state_path

    def imaging_review_get_items(self) -> list[dict[str, Any]]:
        items, _ = self._imaging_review_items()
        return [{"id": i["id"], "key": i["key"], "status": i["status"], "defacing_source": i["defacing_source"]} for i in items]

    @staticmethod
    def _header_dict(path: Path) -> dict[str, str]:
        image = nib.load(str(path))
        values: dict[str, str] = {}
        for key in image.header.keys():
            value = image.header[key]
            try:
                if hasattr(value, "tolist"):
                    value = value.tolist()
            except Exception:
                pass
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            values[str(key)] = str(value)
        values["shape"] = str(tuple(int(value) for value in image.shape))
        values["affine"] = np.array2string(image.affine, precision=5)
        return values

    @staticmethod
    def _volume_array(image, volume: int) -> np.ndarray:
        if len(image.shape) == 4:
            return np.asanyarray(image.dataobj[..., volume])
        return np.asanyarray(image.dataobj)

    @staticmethod
    def _intensity_limits(raw: np.ndarray, clean: np.ndarray) -> tuple[float, float]:
        raw_finite = raw[np.isfinite(raw)]
        clean_finite = clean[np.isfinite(clean)]
        if raw_finite.size == 0 and clean_finite.size == 0:
            return 0.0, 1.0
        combined = np.concatenate((raw_finite.ravel(), clean_finite.ravel()))
        low, high = np.percentile(combined, [1, 99])
        low = float(low); high = float(high)
        if high <= low:
            high = low + 1.0
        return low, high

    @staticmethod
    def _slice_png_data_url(array: np.ndarray, low: float, high: float) -> str:
        buffer = io.BytesIO()
        mpl_image.imsave(buffer, array, cmap="gray", vmin=low, vmax=high, format="png", origin="lower")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return "data:image/png;base64," + encoded

    @staticmethod
    def _clamp_review_index(value: Any, size: int) -> int:
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            number = 0
        return max(0, min(size - 1, number))

    def imaging_review_get_item(self, item_id: str | int, x: int | None = None, y: int | None = None, z: int | None = None, volume: int | None = None) -> dict[str, Any]:
        items, _ = self._imaging_review_items()
        try:
            index = int(item_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid imaging review item.")
        if index < 0 or index >= len(items):
            raise ValueError("Imaging review item not found.")

        item = items[index]
        prepared_path = Path(item["prepared_path"])
        scrubbed_path = Path(item["scrubbed_path"])
        defaced_path = Path(item["review_defaced_path"])
        raw_image = nib.load(str(prepared_path))
        defaced_image = nib.load(str(defaced_path))

        if raw_image.shape != defaced_image.shape:
            raise ValueError(f"Raw and defaced image shapes do not match: {raw_image.shape} vs {defaced_image.shape}")
        if len(raw_image.shape) not in {3, 4}:
            raise ValueError("Only 3D and 4D NIfTI images are supported.")

        shape = tuple(int(value) for value in raw_image.shape)
        x_index = self._clamp_review_index(shape[0] // 2 if x is None else x, shape[0])
        y_index = self._clamp_review_index(shape[1] // 2 if y is None else y, shape[1])
        z_index = self._clamp_review_index(shape[2] // 2 if z is None else z, shape[2])
        volume_count = shape[3] if len(shape) == 4 else 1
        volume_index = self._clamp_review_index(0 if volume is None else volume, volume_count)

        raw = self._volume_array(raw_image, volume_index)
        clean = self._volume_array(defaced_image, volume_index)
        low, high = self._intensity_limits(raw, clean)

        views = {
            "raw_axial": np.rot90(raw[:, :, z_index]),
            "raw_coronal": np.rot90(raw[:, y_index, :]),
            "raw_sagittal": np.rot90(raw[x_index, :, :]),
            "defaced_axial": np.rot90(clean[:, :, z_index]),
            "defaced_coronal": np.rot90(clean[:, y_index, :]),
            "defaced_sagittal": np.rot90(clean[x_index, :, :]),
        }

        raw_header = self._header_dict(prepared_path)
        scrubbed_header = self._header_dict(scrubbed_path)
        header_rows = [
            {
                "field": key,
                "raw": raw_header.get(key, ""),
                "scrubbed": scrubbed_header.get(key, ""),
                "editable": key in EDITABLE_HEADER_FIELDS,
            }
            for key in sorted(set(raw_header) | set(scrubbed_header))
        ]

        return {
            "id": item["id"],
            "key": item["key"],
            "status": item["status"],
            "defacing_source": item["defacing_source"],
            "shape": list(shape),
            "ndim": len(shape),
            "is_4d": len(shape) == 4,
            "x": x_index,
            "y": y_index,
            "z": z_index,
            "volume": volume_index,
            "limits": {
                "x_max": shape[0] - 1,
                "y_max": shape[1] - 1,
                "z_max": shape[2] - 1,
                "volume_max": volume_count - 1,
            },
            "views": {name: self._slice_png_data_url(array, low, high) for name, array in views.items()},
            "header_rows": header_rows,
        }

    def imaging_review_save_header(self, item_id: str | int, field: str, value: str) -> dict[str, Any]:
        field = str(field or "").strip()
        if field not in EDITABLE_HEADER_FIELDS:
            raise ValueError("Only NIfTI text fields are editable.")

        items, _ = self._imaging_review_items()
        index = int(item_id)
        if index < 0 or index >= len(items):
            raise ValueError("Imaging review item not found.")
        item = items[index]
        scrubbed_path = Path(item["scrubbed_path"])
        image = nib.load(str(scrubbed_path))
        header = image.header.copy()
        header[field] = str(value or "").encode("utf-8")
        updated = nib.Nifti1Image(np.asanyarray(image.dataobj), image.affine, header)
        qform, qform_code = image.get_qform(coded=True)
        sform, sform_code = image.get_sform(coded=True)
        updated.set_qform(qform, int(qform_code))
        updated.set_sform(sform, int(sform_code))
        nib.save(updated, str(scrubbed_path))
        self._imaging_log(f"Saved scrubbed NIfTI header edit: {item['key']} | {field}")
        return self.imaging_review_get_item(index)

    def imaging_review_set_status(self, item_id: str | int, status: str) -> dict[str, Any]:
        items, state_path = self._imaging_review_items()
        index = int(item_id)
        if index < 0 or index >= len(items):
            raise ValueError("Imaging review item not found.")
        item = items[index]
        status = str(status or "").strip()
        allowed = {"Accepted", "Rejected - Not Included", "On Hold - Needs Defaced Replacement", "Pending"}
        if status not in allowed:
            raise ValueError(f"Unsupported review status: {status}")

        state = self._load_review_state(state_path)
        accepted_path = ""
        defacing_source = ""
        if status == "Accepted":
            accepted_path = str(Path(item["automated_defaced_path"]).resolve())
            defacing_source = "pydeface"

        state[item["key"]] = {
            "status": status,
            "accepted_defaced_path": accepted_path,
            "defacing_source": defacing_source,
        }
        self._save_review_state(state_path, state)
        self._imaging_log(f"Imaging review status: {item['key']} -> {status}")
        return {"ok": True, "id": item["id"], "key": item["key"], "status": status}


    def imaging_review_choose_external_defaced(
        self,
        item_id: str | int,
    ) -> dict[str, Any]:
        items, state_path = self._imaging_review_items()

        try:
            index = int(item_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid imaging review item.")

        if index < 0 or index >= len(items):
            raise ValueError("Imaging review item not found.")

        if self.window is None:
            return {"ok": False}

        selected = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "NIfTI files (*.nii;*.nii.gz)",
            ),
        )

        if not selected:
            return {"ok": False}

        if isinstance(selected, (list, tuple)):
            selected = selected[0]

        selected_path = Path(str(selected)).expanduser().resolve()

        if not _is_nifti(selected_path):
            raise ValueError(
                "Select a .nii or .nii.gz NIfTI file."
            )

        item = items[index]
        prepared_path = Path(item["prepared_path"])

        original = nib.load(str(prepared_path))
        replacement = nib.load(str(selected_path))

        if original.shape != replacement.shape:
            raise ValueError(
                "The replacement dimensions do not match the original image."
            )

        if len(original.shape) not in {3, 4}:
            raise ValueError(
                "Only 3D and 4D NIfTI replacements are supported."
            )

        if not np.allclose(
            original.affine,
            replacement.affine,
            rtol=1e-5,
            atol=1e-6,
        ):
            raise ValueError(
                "The replacement affine does not match the original image."
            )

        original_zooms = tuple(
            float(value)
            for value in original.header.get_zooms()
        )
        replacement_zooms = tuple(
            float(value)
            for value in replacement.header.get_zooms()
        )

        if (
            len(original_zooms) != len(replacement_zooms)
            or not np.allclose(
                original_zooms,
                replacement_zooms,
                rtol=1e-5,
                atol=1e-6,
            )
        ):
            raise ValueError(
                "The replacement voxel sizes do not match the original image."
            )

        config = load_imaging_config()
        stages = self._imaging_stage_paths(config)
        relative = prepared_path.relative_to(stages["converted"])

        replacement_dir = (
            stages["external_defaced"]
            / relative.parent
        )
        replacement_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        base = self._strip_nifti_suffix(prepared_path)
        extension = (
            ".nii.gz"
            if selected_path.name.endswith(".nii.gz")
            else ".nii"
        )
        destination = (
            replacement_dir
            / f"{base}_external_defaced{extension}"
        )

        shutil.copy2(
            selected_path,
            destination,
        )

        sidecar = _matching_json(selected_path)
        if sidecar is not None:
            shutil.copy2(
                sidecar,
                replacement_dir
                / f"{base}_external_defaced.json",
            )

        state = self._load_review_state(
            state_path
        )
        state[item["key"]] = {
            "status": "Pending External Review",
            "accepted_defaced_path": str(
                destination.resolve()
            ),
            "defacing_source": "external",
        }
        self._save_review_state(
            state_path,
            state,
        )

        self._imaging_log(
            f"External defaced replacement added: {item['key']}"
        )

        return {
            "ok": True,
            "status": "Pending External Review",
            "path": str(destination.resolve()),
        }

    def imaging_stop_operation(self) -> dict[str, Any]:
        self._stop_process("imaging")
        return {"ok": True, "status": "Stopped"}

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def metadata_get_patients(
        self,
        site_id: str,
    ) -> list[dict[str, str]]:
        """Return all locally stored patient IDs for the active site."""
        site_id = str(site_id or "").strip()

        if not site_id:
            return []

        patient_ids = self.repository.patient_ids_for_site(
            site_id
        )

        return [
            {
                "patient_id": str(patient_id),
            }
            for patient_id in patient_ids
        ]

    def metadata_get_patient(
        self,
        site_id: str,
        patient_id: str,
    ) -> dict[str, Any]:
        """Return the same grouped local records used by PatientExplorer."""
        site_id = str(site_id or "").strip()
        patient_id = str(patient_id or "").strip()

        result: dict[str, Any] = {
            "patient_id": patient_id,
            "clinical": [],
            "surgical": [],
            "imaging": [],
            "electrophysiology": [],
        }

        if not site_id or not patient_id:
            return result

        summary = self.repository.patient_summary(
            site_id,
            patient_id,
        )

        result["clinical"] = list(
            summary.get(
                "Clinical",
                [],
            )
        )
        result["surgical"] = list(
            summary.get(
                "Surgical",
                [],
            )
        )
        result["imaging"] = list(
            summary.get(
                "Imaging",
                [],
            )
        )
        result["electrophysiology"] = list(
            summary.get(
                "Electrophysiology",
                [],
            )
        )

        return result


    @staticmethod
    def _metadata_record_file_candidates(
        record: dict[str, Any],
        *,
        kind: str,
    ) -> list[Path]:
        """
        Return plausible locally linked files from a metadata record/context.

        The React patient-data review uses the same locally stored record
        context written by the Imaging/Electrophysiology workflows. Older
        records are tolerated by checking several historical context keys.
        """
        context = dict(
            record.get(
                "context",
                {},
            )
            or {}
        )
        metadata = dict(
            record.get(
                "metadata",
                {},
            )
            or {}
        )

        if kind == "imaging":
            keys = (
                "nifti_path",
                "accepted_defaced_path",
                "prepared_path",
                "scrubbed_path",
                "file_path",
                "source_path",
                "path",
            )
        else:
            keys = (
                "edf_path",
                "scrubbed_path",
                "file_path",
                "source_path",
                "path",
            )

        values: list[str] = []

        for key in keys:
            value = context.get(
                key
            )
            if value:
                values.append(
                    str(value)
                )

        # Some early records stored useful path-like values in metadata.
        for key in keys:
            value = metadata.get(
                key
            )
            if value:
                values.append(
                    str(value)
                )

        candidates: list[Path] = []
        seen: set[str] = set()

        for value in values:
            path = Path(
                value
            ).expanduser()

            try:
                resolved = path.resolve()
            except OSError:
                resolved = path

            key = str(
                resolved
            )

            if key in seen:
                continue

            seen.add(
                key
            )
            candidates.append(
                resolved
            )

        return candidates

    def _metadata_find_imaging_file(
        self,
        record: dict[str, Any],
    ) -> Path:
        for candidate in (
            self._metadata_record_file_candidates(
                record,
                kind="imaging",
            )
        ):
            if candidate.is_file() and _is_nifti(
                candidate
            ):
                return candidate

        metadata = dict(
            record.get(
                "metadata",
                {},
            )
            or {}
        )
        patient_id = str(
            metadata.get(
                "CoCANoT Patient ID",
                "",
            )
            or ""
        ).strip()
        image_id = str(
            metadata.get(
                "Image ID",
                "",
            )
            or ""
        ).strip()

        config = load_imaging_config()
        output_dir = (
            config.imaging.bids_output_dir
        )

        if (
            output_dir.exists()
            and patient_id
            and image_id
        ):
            for sidecar in output_dir.rglob(
                "*.json"
            ):
                try:
                    payload = json.loads(
                        sidecar.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    continue

                if not isinstance(
                    payload,
                    dict,
                ):
                    continue

                if (
                    str(
                        payload.get(
                            "CoCANoTPatientID",
                            "",
                        )
                        or ""
                    )
                    != patient_id
                    or str(
                        payload.get(
                            "ImageID",
                            "",
                        )
                        or ""
                    )
                    != image_id
                ):
                    continue

                stem = sidecar.name[
                    :-5
                ]
                possibilities = (
                    sidecar.with_name(
                        stem
                        + ".nii.gz"
                    ),
                    sidecar.with_name(
                        stem
                        + ".nii"
                    ),
                )

                for candidate in possibilities:
                    if candidate.is_file():
                        return candidate.resolve()

        raise FileNotFoundError(
            "The NIfTI file linked to this Imaging record "
            "could not be found on this computer."
        )

    def metadata_get_imaging_preview(
        self,
        record: dict[str, Any],
        x: int | None = None,
        y: int | None = None,
        z: int | None = None,
        volume: int | None = None,
    ) -> dict[str, Any]:
        path = self._metadata_find_imaging_file(
            record
        )
        image = nib.load(
            str(
                path
            )
        )

        if len(
            image.shape
        ) not in {
            3,
            4,
        }:
            raise ValueError(
                "Only 3D and 4D NIfTI images are supported."
            )

        shape = tuple(
            int(value)
            for value in image.shape
        )
        is_4d = len(
            shape
        ) == 4

        x_index = self._clamp_review_index(
            shape[0] // 2
            if x is None
            else x,
            shape[0],
        )
        y_index = self._clamp_review_index(
            shape[1] // 2
            if y is None
            else y,
            shape[1],
        )
        z_index = self._clamp_review_index(
            shape[2] // 2
            if z is None
            else z,
            shape[2],
        )

        volume_count = (
            shape[3]
            if is_4d
            else 1
        )
        volume_index = self._clamp_review_index(
            0
            if volume is None
            else volume,
            volume_count,
        )

        data = self._volume_array(
            image,
            volume_index,
        )
        low, high = self._intensity_limits(
            data,
            data,
        )

        views = {
            "axial": np.rot90(
                data[
                    :,
                    :,
                    z_index,
                ]
            ),
            "coronal": np.rot90(
                data[
                    :,
                    y_index,
                    :,
                ]
            ),
            "sagittal": np.rot90(
                data[
                    x_index,
                    :,
                    :,
                ]
            ),
        }

        return {
            "path": str(
                path
            ),
            "file_name": path.name,
            "shape": list(
                shape
            ),
            "ndim": len(
                shape
            ),
            "is_4d": is_4d,
            "x": x_index,
            "y": y_index,
            "z": z_index,
            "volume": volume_index,
            "limits": {
                "x_max": shape[0] - 1,
                "y_max": shape[1] - 1,
                "z_max": shape[2] - 1,
                # A volume maximum is returned for API consistency,
                # but the React viewer only renders the control when
                # is_4d is true.
                "volume_max": (
                    volume_count - 1
                ),
            },
            "views": {
                name: self._slice_png_data_url(
                    array,
                    low,
                    high,
                )
                for name, array in views.items()
            },
        }

    def _metadata_find_edf_file(
        self,
        record: dict[str, Any],
    ) -> Path:
        for candidate in (
            self._metadata_record_file_candidates(
                record,
                kind="ephys",
            )
        ):
            if (
                candidate.is_file()
                and candidate.suffix.lower()
                == ".edf"
            ):
                return candidate

        metadata = dict(
            record.get(
                "metadata",
                {},
            )
            or {}
        )
        patient_id = str(
            metadata.get(
                "CoCANoT Patient ID",
                "",
            )
            or ""
        ).strip()
        recording_id = str(
            metadata.get(
                "Recording ID",
                "",
            )
            or ""
        ).strip()

        config = load_pipeline_config()
        output_dir = (
            config.electrophysiology.bids_output_dir
        )

        if output_dir.exists():
            for candidate in output_dir.rglob(
                "*.edf"
            ):
                sidecar = candidate.with_suffix(
                    ".json"
                )

                if not sidecar.exists():
                    continue

                try:
                    payload = json.loads(
                        sidecar.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    continue

                if not isinstance(
                    payload,
                    dict,
                ):
                    continue

                stored_patient = str(
                    payload.get(
                        "CoCANoTPatientID",
                        "",
                    )
                    or ""
                )
                stored_recording = str(
                    payload.get(
                        "RecordingID",
                        "",
                    )
                    or ""
                )

                if (
                    patient_id
                    and stored_patient
                    and stored_patient
                    != patient_id
                ):
                    continue

                if (
                    recording_id
                    and stored_recording
                    and stored_recording
                    != recording_id
                ):
                    continue

                if (
                    patient_id
                    or recording_id
                ):
                    return candidate.resolve()

        raise FileNotFoundError(
            "The EDF file linked to this Electrophysiology "
            "record could not be found on this computer."
        )

    def metadata_get_ephys_signal_preview(
        self,
        record: dict[str, Any],
        start_seconds: float = 0.0,
        window_seconds: float = 10.0,
        channels: list[str] | None = None,
        max_points: int = 1600,
    ) -> dict[str, Any]:
        try:
            import pyedflib
        except ImportError as exc:
            raise RuntimeError(
                "pyedflib is required to review EDF signals."
            ) from exc

        path = self._metadata_find_edf_file(
            record
        )
        reader = pyedflib.EdfReader(
            str(
                path
            )
        )

        try:
            labels = [
                str(value)
                for value in reader.getSignalLabels()
            ]
            channel_count = len(
                labels
            )
            duration = float(
                reader.file_duration
            )

            if channel_count == 0:
                raise ValueError(
                    "This EDF does not contain any signal channels."
                )

            requested = [
                str(value)
                for value in (
                    channels or []
                )
                if str(
                    value
                ) in labels
            ]

            if not requested:
                requested = labels[
                    : min(
                        8,
                        channel_count,
                    )
                ]

            start = max(
                0.0,
                min(
                    float(
                        start_seconds
                    ),
                    max(
                        0.0,
                        duration,
                    ),
                ),
            )
            window = max(
                1.0,
                min(
                    float(
                        window_seconds
                    ),
                    max(
                        1.0,
                        duration,
                    ),
                ),
            )

            if start + window > duration:
                start = max(
                    0.0,
                    duration
                    - window,
                )

            rows: list[
                dict[str, Any]
            ] = []

            for label in requested:
                channel_index = labels.index(
                    label
                )
                sample_frequency = float(
                    reader.getSampleFrequency(
                        channel_index
                    )
                )
                physical_dimension = str(
                    reader.getPhysicalDimension(
                        channel_index
                    )
                    or ""
                ).strip()
                start_sample = int(
                    round(
                        start
                        * sample_frequency
                    )
                )
                sample_count = max(
                    1,
                    int(
                        round(
                            window
                            * sample_frequency
                        )
                    ),
                )

                signal = np.asarray(
                    reader.readSignal(
                        channel_index,
                        start=start_sample,
                        n=sample_count,
                    ),
                    dtype=float,
                )

                if signal.size == 0:
                    continue

                stride = max(
                    1,
                    int(
                        np.ceil(
                            signal.size
                            / max(
                                100,
                                int(
                                    max_points
                                ),
                            )
                        )
                    ),
                )
                sampled = signal[
                    ::stride
                ]
                times = (
                    start
                    + (
                        np.arange(
                            sampled.size
                        )
                        * stride
                        / sample_frequency
                    )
                )

                finite = sampled[
                    np.isfinite(
                        sampled
                    )
                ]

                if finite.size:
                    minimum = float(
                        np.min(
                            finite
                        )
                    )
                    maximum = float(
                        np.max(
                            finite
                        )
                    )
                else:
                    minimum = 0.0
                    maximum = 0.0

                rows.append(
                    {
                        "label": label,
                        "sample_frequency": sample_frequency,
                        "unit": physical_dimension,
                        "times": [
                            round(
                                float(value),
                                6,
                            )
                            for value in times
                        ],
                        "values": [
                            (
                                float(value)
                                if np.isfinite(
                                    value
                                )
                                else 0.0
                            )
                            for value in sampled
                        ],
                        "min": minimum,
                        "max": maximum,
                    }
                )

            return {
                "path": str(
                    path
                ),
                "file_name": path.name,
                "duration_seconds": duration,
                "channel_labels": labels,
                "selected_channels": requested,
                "start_seconds": start,
                "window_seconds": window,
                "signals": rows,
            }
        finally:
            reader.close()

    def metadata_create_patient(
        self,
        site_id: str,
        patient_id: str,
    ) -> dict[str, Any]:
        site_id = str(site_id or "").strip()
        patient_id = str(patient_id or "").strip()

        if not site_id:
            raise ValueError("Site ID is required.")

        if not patient_id:
            raise ValueError("Patient ID is required.")

        exists = getattr(
            self.repository,
            "patient_exists",
            None,
        )

        if callable(exists) and exists(
            site_id,
            patient_id,
        ):
            return {
                "patient_id": patient_id,
                "created": False,
                "exists": True,
            }

        create = getattr(
            self.repository,
            "create_patient",
            None,
        )

        if not callable(create):
            raise RuntimeError(
                "MetadataRepository.create_patient() is unavailable."
            )

        create(
            site_id,
            patient_id,
        )

        return {
            "patient_id": patient_id,
            "created": True,
            "exists": False,
        }


    def metadata_get_rules(
        self,
        table_name: str,
    ) -> list[dict[str, Any]]:
        table_name = str(
            table_name or ""
        ).strip()

        if table_name not in {
            "Clinical",
            "Surgical",
            "Imaging",
            "Electrophysiology",
        }:
            raise ValueError(
                f"Unsupported metadata table: {table_name}"
            )

        _dictionary, rules, _validator = (
            self._dictionary_context(
                table_name
            )
        )

        return [
            self._rule_payload(
                rule
            )
            for rule in rules
            if not bool(
                rule.get(
                    "system_generated",
                    False,
                )
            )
        ]

    def metadata_save_clinical(
        self,
        patient_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        patient_id = str(
            patient_id or ""
        ).strip()

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID is required."
            )

        dictionary = load_dictionary(
            METADATA_DICTIONARY
        )
        rules = dictionary[
            "tables"
        ][
            "Clinical"
        ][
            "fields"
        ]
        clean = self._normalize_metadata_values(
            dict(
                metadata or {}
            ),
            rules,
        )
        clean[
            "CoCANoT Patient ID"
        ] = patient_id

        validator = MetadataValidator(
            dictionary
        )
        validation = (
            validator.validate_record(
                "Clinical",
                clean,
            )
        )
        bad = [
            result
            for result in validation[
                "results"
            ]
            if result[
                "status"
            ] in {
                "invalid",
                "missing_required",
            }
        ]

        if bad:
            raise ValueError(
                "\n".join(
                    f"{item['field_name']}: "
                    f"{item['message']}"
                    for item in bad[:20]
                )
            )

        tracked = tracked_clinical_fields(
            dictionary
        )
        saved = (
            self.store.save_clinical_assessment(
                self.get_site_id(),
                patient_id,
                clean,
                tracked,
            )
        )
        self.repository.create_patient(
            self.get_site_id(),
            patient_id,
        )
        return dict(
            saved
        )

    def metadata_save_record(
        self,
        table_name: str,
        metadata: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        table_name = str(
            table_name or ""
        ).strip()

        if table_name == "Clinical":
            patient_id = str(
                metadata.get(
                    "CoCANoT Patient ID",
                    "",
                )
                or ""
            )
            return self.metadata_save_clinical(
                patient_id,
                metadata,
            )

        if table_name not in {
            "Surgical",
            "Imaging",
            "Electrophysiology",
        }:
            raise ValueError(
                f"Unsupported metadata table: {table_name}"
            )

        dictionary, rules, validator = (
            self._dictionary_context(
                table_name
            )
        )
        clean = self._normalize_metadata_values(
            dict(
                metadata or {}
            ),
            rules,
        )

        validation = (
            validator.validate_record(
                table_name,
                clean,
            )
        )
        bad = [
            result
            for result in validation[
                "results"
            ]
            if result[
                "status"
            ] in {
                "invalid",
                "missing_required",
            }
        ]

        if bad:
            raise ValueError(
                "\n".join(
                    f"{item['field_name']}: "
                    f"{item['message']}"
                    for item in bad[:20]
                )
            )

        return self.repository.save_record(
            self.get_site_id(),
            table_name,
            clean,
            source="metadata_dashboard",
            context=dict(
                context or {}
            ),
        )

    @staticmethod
    def _read_tabular_rows(
        path: Path,
    ) -> list[dict[str, Any]]:
        suffix = path.suffix.lower()

        if suffix == ".csv":
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                return [
                    dict(row)
                    for row in csv.DictReader(
                        handle
                    )
                ]

        if suffix in {
            ".xlsx",
            ".xlsm",
        }:
            from openpyxl import load_workbook

            workbook = load_workbook(
                path,
                read_only=True,
                data_only=True,
            )
            sheet = workbook.active
            rows = list(
                sheet.iter_rows(
                    values_only=True
                )
            )
            if not rows:
                return []

            headers = [
                str(value or "").strip()
                for value in rows[0]
            ]
            result: list[
                dict[str, Any]
            ] = []

            for values in rows[1:]:
                if not any(
                    value not in (
                        None,
                        "",
                    )
                    for value in values
                ):
                    continue

                result.append(
                    {
                        headers[index]: value
                        for index, value in enumerate(
                            values
                        )
                        if index < len(
                            headers
                        )
                        and headers[
                            index
                        ]
                    }
                )

            return result

        raise ValueError(
            "Choose a CSV or XLSX file."
        )



    @staticmethod
    def _metadata_comparison_projection(
        metadata: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Compare only MR-defined, non-system-generated fields.

        This prevents Clinical Assessment ID and other generated values from
        making an otherwise identical upload look changed.
        """
        projection: dict[str, Any] = {}

        for rule in rules:
            if bool(
                rule.get(
                    "system_generated",
                    False,
                )
            ):
                continue

            field_name = str(
                rule.get(
                    "field_name",
                    "",
                )
            ).strip()

            if not field_name:
                continue

            value = metadata.get(
                field_name
            )

            if isinstance(
                value,
                list,
            ):
                projection[
                    field_name
                ] = [
                    str(item).strip()
                    for item in value
                    if str(item).strip()
                ]
            elif value is None:
                projection[
                    field_name
                ] = ""
            elif isinstance(
                value,
                str,
            ):
                projection[
                    field_name
                ] = value.strip()
            else:
                projection[
                    field_name
                ] = value

        return projection

    def _metadata_batch_difference_status(
        self,
        table_name: str,
        metadata: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Classify a staged row without mutating storage.

        Clinical classification follows the same MR-driven tracked-field
        concept as save_clinical_assessment(). Historical assessments are
        treated as immutable: a differing historical match is blocked for
        manual review instead of being overwritten.
        """
        clean = self._normalize_metadata_values(
            dict(metadata or {}),
            rules,
        )
        patient_id = str(
            clean.get(
                "CoCANoT Patient ID",
                "",
            )
            or ""
        ).strip()

        base = {
            "existing_record_id": "",
            "has_changes": True,
            "requires_review": False,
            "immutable": False,
            "import_allowed": True,
        }

        if not patient_id:
            return {
                **base,
                "difference_status": "New",
                "proposed_action": "Create record",
            }

        incoming_projection = (
            self._metadata_comparison_projection(
                clean,
                rules,
            )
        )

        if table_name == "Clinical":
            dictionary = load_dictionary(
                METADATA_DICTIONARY
            )
            tracked = {
                str(field).strip()
                for field in tracked_clinical_fields(
                    dictionary
                )
                if str(field).strip()
            }

            assessments = (
                self.repository.clinical_assessments(
                    self.get_site_id(),
                    patient_id,
                )
            )

            if not assessments:
                return {
                    **base,
                    "difference_status": "New",
                    "proposed_action": (
                        "Create first Clinical Assessment"
                    ),
                }

            current = assessments[0]
            uploaded_assessment_id = str(
                clean.get(
                    "Clinical Assessment ID",
                    "",
                )
                or ""
            ).strip()

            projections: list[
                tuple[
                    dict[str, Any],
                    dict[str, Any],
                ]
            ] = []

            for record in assessments:
                existing_clean = (
                    self._normalize_metadata_values(
                        dict(
                            record.get(
                                "metadata",
                                {},
                            )
                            or {}
                        ),
                        rules,
                    )
                )
                projections.append(
                    (
                        record,
                        self._metadata_comparison_projection(
                            existing_clean,
                            rules,
                        ),
                    )
                )

            def tracked_projection(
                projection: dict[str, Any],
            ) -> dict[str, Any]:
                return {
                    key: projection.get(
                        key,
                        "",
                    )
                    for key in tracked
                }

            # If the upload names a CA explicitly, honor that identity.
            if uploaded_assessment_id:
                matched = next(
                    (
                        pair
                        for pair in projections
                        if str(
                            pair[0].get(
                                "record_id",
                                "",
                            )
                        )
                        == uploaded_assessment_id
                    ),
                    None,
                )

                if matched is not None:
                    record, existing_projection = (
                        matched
                    )
                    is_current = (
                        str(
                            record.get(
                                "record_id",
                                "",
                            )
                        )
                        == str(
                            current.get(
                                "record_id",
                                "",
                            )
                        )
                    )
                    exact = (
                        existing_projection
                        == incoming_projection
                    )

                    if exact:
                        return {
                            **base,
                            "difference_status": "Unchanged",
                            "proposed_action": "Skip unchanged",
                            "existing_record_id": str(
                                record.get(
                                    "record_id",
                                    "",
                                )
                            ),
                            "has_changes": False,
                            "import_allowed": False,
                            "immutable": not is_current,
                        }

                    if not is_current:
                        return {
                            **base,
                            "difference_status": (
                                "Historical review"
                            ),
                            "proposed_action": (
                                "Historical CA is immutable; review differences"
                            ),
                            "existing_record_id": str(
                                record.get(
                                    "record_id",
                                    "",
                                )
                            ),
                            "requires_review": True,
                            "immutable": True,
                            "import_allowed": False,
                        }

            # Exact duplicate against any assessment: always skip.
            exact_match = next(
                (
                    pair
                    for pair in projections
                    if pair[1]
                    == incoming_projection
                ),
                None,
            )

            if exact_match is not None:
                record = exact_match[
                    0
                ]
                return {
                    **base,
                    "difference_status": "Unchanged",
                    "proposed_action": "Skip unchanged",
                    "existing_record_id": str(
                        record.get(
                            "record_id",
                            "",
                        )
                    ),
                    "has_changes": False,
                    "import_allowed": False,
                    "immutable": (
                        str(
                            record.get(
                                "record_id",
                                "",
                            )
                        )
                        != str(
                            current.get(
                                "record_id",
                                "",
                            )
                        )
                    ),
                }

            current_projection = projections[
                0
            ][
                1
            ]
            current_tracked = tracked_projection(
                current_projection
            )
            incoming_tracked = tracked_projection(
                incoming_projection
            )

            # If tracked values identify an older assessment, do not
            # silently correct history.
            historical_tracked_match = next(
                (
                    pair
                    for pair in projections[
                        1:
                    ]
                    if tracked_projection(
                        pair[
                            1
                        ]
                    )
                    == incoming_tracked
                ),
                None,
            )

            if historical_tracked_match is not None:
                return {
                    **base,
                    "difference_status": (
                        "Historical review"
                    ),
                    "proposed_action": (
                        "Possible historical CA correction; manual review required"
                    ),
                    "existing_record_id": str(
                        historical_tracked_match[
                            0
                        ].get(
                            "record_id",
                            "",
                        )
                    ),
                    "requires_review": True,
                    "immutable": True,
                    "import_allowed": False,
                }

            if incoming_tracked == current_tracked:
                return {
                    **base,
                    "difference_status": "Correction",
                    "proposed_action": (
                        "Correct current Clinical Assessment"
                    ),
                    "existing_record_id": str(
                        current.get(
                            "record_id",
                            "",
                        )
                    ),
                }

            return {
                **base,
                "difference_status": "New assessment",
                "proposed_action": (
                    "Create new Clinical Assessment"
                ),
                "existing_record_id": str(
                    current.get(
                        "record_id",
                        "",
                    )
                ),
            }

        if table_name == "Surgical":
            record_id = str(
                clean.get(
                    "Surgery ID",
                    "",
                )
                or ""
            ).strip()

            if not record_id:
                return {
                    **base,
                    "difference_status": "New",
                    "proposed_action": "Create Surgical record",
                }

            existing = self.repository.get_record(
                self.get_site_id(),
                "Surgical",
                record_id,
                patient_id=patient_id,
            )

            if existing is None:
                return {
                    **base,
                    "difference_status": "New",
                    "proposed_action": "Create Surgical record",
                }

            existing_clean = (
                self._normalize_metadata_values(
                    dict(
                        existing.get(
                            "metadata",
                            {},
                        )
                        or {}
                    ),
                    rules,
                )
            )
            existing_projection = (
                self._metadata_comparison_projection(
                    existing_clean,
                    rules,
                )
            )
            unchanged = (
                existing_projection
                == incoming_projection
            )

            return {
                **base,
                "difference_status": (
                    "Unchanged"
                    if unchanged
                    else "Changed"
                ),
                "proposed_action": (
                    "Skip unchanged"
                    if unchanged
                    else "Update existing Surgical record"
                ),
                "existing_record_id": record_id,
                "has_changes": not unchanged,
                "import_allowed": not unchanged,
            }

        return {
            **base,
            "difference_status": "New",
            "proposed_action": "Create record",
        }


    def metadata_batch_choose_file(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        table_name = str(table_name or "").strip()

        if table_name not in {"Clinical", "Surgical"}:
            raise ValueError(
                "Batch import is supported for Clinical and Surgical metadata."
            )

        if self.window is None:
            return {"ok": False, "cancelled": True}

        selected = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "CSV files (*.csv)",
                "Excel files (*.xlsx;*.xlsm)",
            ),
        )

        if not selected:
            return {"ok": False, "cancelled": True}

        if isinstance(selected, (list, tuple)):
            selected = selected[0]

        path = Path(str(selected)).expanduser()
        rows = self._read_tabular_rows(path)

        if not rows:
            raise ValueError(
                "The selected file contains no data rows."
            )

        _dictionary, rules, validator = self._dictionary_context(
            table_name
        )

        preview: list[dict[str, Any]] = []

        for row_number, row in enumerate(rows, start=2):
            clean = self._normalize_metadata_values(
                dict(row),
                rules,
            )
            validation = validator.validate_record(
                table_name,
                clean,
            )
            problems = [
                {
                    "field_name": result["field_name"],
                    "status": result["status"],
                    "message": result["message"],
                }
                for result in validation["results"]
                if result["status"] in {
                    "invalid",
                    "missing_required",
                }
            ]

            difference = (
                self._metadata_batch_difference_status(
                    table_name,
                    clean,
                    rules,
                )
            )

            preview.append(
                {
                    "row_number": row_number,
                    "include": (
                        not problems
                        and bool(
                            difference.get(
                                "import_allowed",
                                True,
                            )
                        )
                    ),
                    "patient_id": str(
                        clean.get("CoCANoT Patient ID", "") or ""
                    ).strip(),
                    "metadata": clean,
                    "problems": problems,
                    "status": (
                        "Needs attention"
                        if problems
                        else difference[
                            "difference_status"
                        ]
                    ),
                    **difference,
                }
            )

        return {
            "ok": True,
            "cancelled": False,
            "table_name": table_name,
            "path": str(path),
            "file_name": path.name,
            "row_count": len(preview),
            "valid_count": sum(
                1 for item in preview if not item["problems"]
            ),
            "invalid_count": sum(
                1 for item in preview if item["problems"]
            ),
            "new_count": sum(
                1
                for item in preview
                if item.get(
                    "difference_status"
                ) == "New"
            ),
            "changed_count": sum(
                1
                for item in preview
                if item.get(
                    "difference_status"
                ) == "Changed"
            ),
            "unchanged_count": sum(
                1
                for item in preview
                if item.get(
                    "difference_status"
                ) == "Unchanged"
            ),
            "rows": preview,
        }

    def metadata_batch_validate(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        table_name = str(table_name or "").strip()

        if table_name not in {"Clinical", "Surgical"}:
            raise ValueError(
                "Batch import is supported for Clinical and Surgical metadata."
            )

        _dictionary, rules, validator = self._dictionary_context(
            table_name
        )

        validated: list[dict[str, Any]] = []

        for item in rows or []:
            clean = self._normalize_metadata_values(
                dict(item.get("metadata", {}) or {}),
                rules,
            )
            validation = validator.validate_record(
                table_name,
                clean,
            )
            problems = [
                {
                    "field_name": result["field_name"],
                    "status": result["status"],
                    "message": result["message"],
                }
                for result in validation["results"]
                if result["status"] in {
                    "invalid",
                    "missing_required",
                }
            ]

            difference = (
                self._metadata_batch_difference_status(
                    table_name,
                    clean,
                    rules,
                )
            )

            validated.append(
                {
                    **dict(item),
                    "patient_id": str(
                        clean.get("CoCANoT Patient ID", "") or ""
                    ).strip(),
                    "metadata": clean,
                    "problems": problems,
                    "status": (
                        "Needs attention"
                        if problems
                        else difference[
                            "difference_status"
                        ]
                    ),
                    **difference,
                }
            )

        return {
            "ok": not any(
                item["problems"]
                for item in validated
                if bool(item.get("include", True))
                and item.get(
                    "difference_status"
                ) != "Unchanged"
            ),
            "rows": validated,
            "valid_count": sum(
                1 for item in validated if not item["problems"]
            ),
            "invalid_count": sum(
                1 for item in validated if item["problems"]
            ),
            "new_count": sum(
                1
                for item in validated
                if item.get(
                    "difference_status"
                ) == "New"
            ),
            "changed_count": sum(
                1
                for item in validated
                if item.get(
                    "difference_status"
                ) == "Changed"
            ),
            "unchanged_count": sum(
                1
                for item in validated
                if item.get(
                    "difference_status"
                ) == "Unchanged"
            ),
        }

    def metadata_batch_commit(
        self,
        table_name: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        validated = self.metadata_batch_validate(
            table_name,
            rows,
        )

        unchanged = [
            item
            for item in validated["rows"]
            if item.get(
                "difference_status"
            ) == "Unchanged"
        ]

        included = [
            item
            for item in validated["rows"]
            if bool(item.get("include", True))
            and item.get(
                "difference_status"
            ) != "Unchanged"
        ]

        blocked = [
            item
            for item in included
            if item["problems"]
            or bool(
                item.get(
                    "requires_review",
                    False,
                )
            )
            or not bool(
                item.get(
                    "import_allowed",
                    True,
                )
            )
        ]

        if blocked:
            return {
                "ok": False,
                "imported": 0,
                "failed": len(blocked),
                "skipped_unchanged": len(
                    unchanged
                ),
                "rows": validated["rows"],
                "problems": [
                    (
                        f"Row {item['row_number']}: "
                        + (
                            "; ".join(
                                problem["message"]
                                for problem in item["problems"]
                            )
                            if item["problems"]
                            else str(
                                item.get(
                                    "proposed_action",
                                    "Manual review required",
                                )
                            )
                        )
                    )
                    for item in blocked[:20]
                ],
            }

        imported = 0
        created = 0
        updated = 0
        failed = 0
        results: list[dict[str, Any]] = []

        for item in unchanged:
            results.append(
                {
                    "row_number": item[
                        "row_number"
                    ],
                    "status": "Skipped - unchanged",
                    "record_id": str(
                        item.get(
                            "existing_record_id",
                            "",
                        )
                        or ""
                    ),
                    "message": (
                        "No metadata differences were detected."
                    ),
                }
            )

        for item in included:
            try:
                metadata = dict(item["metadata"])

                if table_name == "Clinical":
                    patient_id = str(
                        metadata.get("CoCANoT Patient ID", "") or ""
                    ).strip()
                    saved = self.metadata_save_clinical(
                        patient_id,
                        metadata,
                    )
                else:
                    saved = self.metadata_save_record(
                        "Surgical",
                        metadata,
                    )

                imported += 1

                if item.get(
                    "difference_status"
                ) == "Changed":
                    updated += 1
                    action_status = "Updated"
                else:
                    created += 1
                    action_status = "Created"

                results.append(
                    {
                        "row_number": item["row_number"],
                        "status": action_status,
                        "record_id": str(
                            saved.get(
                                "record_id",
                                saved.get("assessment_id", ""),
                            )
                            or ""
                        ),
                        "message": "",
                    }
                )
            except Exception as exc:
                failed += 1
                results.append(
                    {
                        "row_number": item["row_number"],
                        "status": "Failed",
                        "record_id": "",
                        "message": str(exc),
                    }
                )

        return {
            "ok": failed == 0,
            "imported": imported,
            "created": created,
            "updated": updated,
            "skipped_unchanged": len(
                unchanged
            ),
            "failed": failed,
            "results": results,
        }

    def metadata_import_records(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        table_name = str(
            table_name or ""
        ).strip()

        if table_name not in {
            "Clinical",
            "Surgical",
        }:
            raise ValueError(
                "Bulk import is supported for "
                "Clinical and Surgical metadata."
            )

        if self.window is None:
            return {
                "ok": False,
                "imported": 0,
            }

        selected = self.window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "CSV files (*.csv)",
                "Excel files (*.xlsx;*.xlsm)",
            ),
        )

        if not selected:
            return {
                "ok": False,
                "imported": 0,
            }

        if isinstance(
            selected,
            (
                list,
                tuple,
            ),
        ):
            selected = selected[0]

        path = Path(
            str(
                selected
            )
        ).expanduser()

        rows = self._read_tabular_rows(
            path
        )

        if not rows:
            raise ValueError(
                "The selected file contains no data rows."
            )

        imported = 0
        problems: list[str] = []

        for index, row in enumerate(
            rows,
            start=2,
        ):
            try:
                if table_name == "Clinical":
                    patient_id = str(
                        row.get(
                            "CoCANoT Patient ID",
                            "",
                        )
                        or ""
                    ).strip()
                    self.metadata_save_clinical(
                        patient_id,
                        row,
                    )
                else:
                    self.metadata_save_record(
                        "Surgical",
                        row,
                    )
                imported += 1
            except Exception as exc:
                problems.append(
                    f"Row {index}: {exc}"
                )

        return {
            "ok": imported > 0,
            "imported": imported,
            "failed": len(
                problems
            ),
            "problems": problems[
                :20
            ],
            "path": str(
                path
            ),
        }


    def metadata_delete_records(
        self,
        table_name: str,
        patient_id: str,
        record_ids: list[str],
    ) -> dict[str, Any]:
        table_name = str(
            table_name or ""
        ).strip()
        patient_id = str(
            patient_id or ""
        ).strip()
        record_ids = [
            str(value).strip()
            for value in (
                record_ids or []
            )
            if str(value).strip()
        ]

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID is required."
            )

        if not record_ids:
            return {
                "deleted": [],
                "blocked": [],
            }

        deletion = RecordDeletionService()
        data_links = PatientDataLinkStore()

        deleted: list[str] = []
        blocked: list[dict[str, str]] = []

        for record_id in record_ids:
            if table_name == "Clinical":
                references = (
                    deletion.clinical_assessment_references(
                        self.get_site_id(),
                        patient_id,
                        record_id,
                    )
                )

                if references:
                    counts: dict[str, int] = {}

                    for reference in references:
                        name = str(
                            reference.get(
                                "table_name",
                                "Record",
                            )
                        )
                        counts[
                            name
                        ] = counts.get(
                            name,
                            0,
                        ) + 1

                    detail = ", ".join(
                        f"{name}: {count}"
                        for name, count in sorted(
                            counts.items()
                        )
                    )
                    blocked.append(
                        {
                            "record_id": record_id,
                            "reason": (
                                "Referenced by other records"
                                + (
                                    f" ({detail})"
                                    if detail
                                    else ""
                                )
                            ),
                        }
                    )
                    continue

                if (
                    deletion.clinical_assessment_count(
                        self.get_site_id(),
                        patient_id,
                    )
                    <= 1
                ):
                    blocked.append(
                        {
                            "record_id": record_id,
                            "reason": (
                                "A patient must retain at least "
                                "one Clinical Assessment."
                            ),
                        }
                    )
                    continue

                result = (
                    deletion.delete_clinical_assessment(
                        self.get_site_id(),
                        patient_id,
                        record_id,
                    )
                )

                if result.get(
                    "deleted"
                ):
                    deleted.append(
                        record_id
                    )
                else:
                    blocked.append(
                        {
                            "record_id": record_id,
                            "reason": (
                                "Record could not be found."
                            ),
                        }
                    )

                continue

            if table_name not in {
                "Surgical",
                "Imaging",
                "Electrophysiology",
            }:
                raise ValueError(
                    f"Unsupported metadata table: {table_name}"
                )

            was_deleted = (
                deletion.delete_metadata_record(
                    self.get_site_id(),
                    patient_id,
                    table_name,
                    record_id,
                )
            )

            if not was_deleted:
                blocked.append(
                    {
                        "record_id": record_id,
                        "reason": (
                            "Record could not be found."
                        ),
                    }
                )
                continue

            if table_name in {
                "Imaging",
                "Electrophysiology",
            }:
                data_links.delete_link(
                    self.get_site_id(),
                    patient_id,
                    table_name,
                    record_id,
                )

            deleted.append(
                record_id
            )

        return {
            "deleted": deleted,
            "blocked": blocked,
        }

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    @staticmethod
    def _process_running(
        process: subprocess.Popen | None,
    ) -> bool:
        return (
            process is not None
            and process.poll() is None
        )

    def _ephys_log(self, message: str) -> None:
        self.ephys_logs.append(
            str(message)
        )

    def _imaging_log(self, message: str) -> None:
        self.imaging_logs.append(
            str(message)
        )

    def _start_process(
        self,
        *,
        command: list[str],
        workflow: str,
        description: str,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        current = (
            self.ephys_process
            if workflow == "ephys"
            else self.imaging_process
        )

        if self._process_running(current):
            raise RuntimeError(
                "Another operation is already running."
            )

        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if workflow == "ephys":
            self.ephys_process = process
            self._ephys_log(
                f"Started: {description}"
            )
        else:
            self.imaging_process = process
            self._imaging_log(
                f"Started: {description}"
            )

        thread = threading.Thread(
            target=self._read_process_output,
            args=(
                process,
                workflow,
                description,
                on_success,
            ),
            daemon=True,
        )
        thread.start()

    def _read_process_output(
        self,
        process: subprocess.Popen,
        workflow: str,
        description: str,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                line = line.rstrip("\n")

                if not line:
                    continue

                if workflow == "ephys":
                    self._ephys_log(line)
                else:
                    self._imaging_log(line)

        return_code = process.wait()

        message = (
            f"{description} completed."
            if return_code == 0
            else (
                f"{description} exited with code "
                f"{return_code}."
            )
        )

        if (
            return_code == 0
            and on_success is not None
        ):
            try:
                on_success()
            except Exception as exc:
                if workflow == "ephys":
                    self._ephys_log(
                        "Post-conversion metadata save failed: "
                        f"{exc}"
                    )
                else:
                    self._imaging_log(
                        "Post-conversion action failed: "
                        f"{exc}"
                    )

        if workflow == "ephys":
            self._ephys_log(message)

            if self.ephys_process is process:
                self.ephys_process = None

        else:
            self._imaging_log(message)

            if self.imaging_process is process:
                self.imaging_process = None

    def _stop_process(
        self,
        workflow: str,
    ) -> None:
        process = (
            self.ephys_process
            if workflow == "ephys"
            else self.imaging_process
        )

        if not self._process_running(process):
            return

        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

        if workflow == "ephys":
            self.ephys_process = None
            self._ephys_log(
                "Operation stopped."
            )
        else:
            self.imaging_process = None
            self._imaging_log(
                "Operation stopped."
            )


# ---------------------------------------------------------------------------
# Static React server
# ---------------------------------------------------------------------------

class QuietHandler(
    SimpleHTTPRequestHandler
):
    def log_message(
        self,
        format: str,
        *args,
    ) -> None:
        pass


def start_frontend_server() -> ThreadingHTTPServer:
    if not FRONTEND_DIST.is_dir():
        raise RuntimeError(
            "\nReact build not found.\n\n"
            f"Expected:\n{FRONTEND_DIST}\n\n"
            "Run:\n"
            "  cd react_frontend\n"
            "  npm install\n"
            "  npm run build\n"
        )

    index = FRONTEND_DIST / "index.html"

    if not index.is_file():
        raise RuntimeError(
            f"Missing React build file: {index}"
        )

    def handler(
        *args,
        **kwargs,
    ):
        return QuietHandler(
            *args,
            directory=str(FRONTEND_DIST),
            **kwargs,
        )

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        handler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )
    thread.start()

    return server


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def main() -> None:
    api = CoCANoTAPI()

    server = start_frontend_server()
    port = server.server_address[1]

    window = webview.create_window(
        title="CoCANoT",
        url=f"http://127.0.0.1:{port}/",
        js_api=api,
        width=1320,
        height=920,
        min_size=(980, 720),
    )

    api.window = window

    try:
        webview.start(debug=True)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
