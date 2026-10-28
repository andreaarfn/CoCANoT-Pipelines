
"""React + PyWebView launcher for the unified CoCANoT application."""

from __future__ import annotations

import base64
import csv
import io
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
import webbrowser
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import webview
from MetadataPipeline.storage.identifiers import normalize_patient_id, normalize_record_id
import fitz
from PIL import Image, ImageDraw
import nibabel as nib
import numpy as np
from matplotlib import image as mpl_image

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
METADATA_DICTIONARY_DIR = ROOT / "MetadataPipeline" / "dictionaries"
METADATA_DICTIONARY_PATTERN = re.compile(
    r"^CoCANoT_Metadata_Phase(?P<version>\d+(?:\.\d+)*)\.xlsx$",
    re.IGNORECASE,
)


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)*)", str(value or ""))
    if match is None:
        raise ValueError(f"Could not parse dictionary version: {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def _available_dictionary_files() -> list[tuple[tuple[int, ...], Path]]:
    found: list[tuple[tuple[int, ...], Path]] = []

    if not METADATA_DICTIONARY_DIR.exists():
        return found

    for path in METADATA_DICTIONARY_DIR.iterdir():
        if not path.is_file():
            continue

        match = METADATA_DICTIONARY_PATTERN.fullmatch(path.name)
        if match is None:
            continue

        version = tuple(
            int(part)
            for part in match.group("version").split(".")
        )
        found.append((version, path))

    return sorted(found, key=lambda item: item[0])


def _active_dictionary_path() -> Path:
    available = _available_dictionary_files()

    if not available:
        raise FileNotFoundError(
            "No CoCANoT metadata dictionary was found in "
            f"{METADATA_DICTIONARY_DIR}."
        )

    return available[-1][1]


def _dictionary_path_for_version(dictionary_version: str) -> Path:
    wanted = _version_tuple(dictionary_version)

    for version, path in _available_dictionary_files():
        if version == wanted:
            return path

    raise FileNotFoundError(
        f"No CoCANoT metadata dictionary for version "
        f"{dictionary_version!r} was found in {METADATA_DICTIONARY_DIR}."
    )


def _dictionary_version_from_table(
    dictionary: dict[str, Any],
    table_name: str,
) -> str:
    rules = dictionary["tables"][table_name]["fields"]
    versions = {
        str(rule.get("dictionary_version") or "").strip()
        for rule in rules
        if str(rule.get("dictionary_version") or "").strip()
    }

    if len(versions) != 1:
        raise ValueError(
            f"MR {table_name} must contain exactly one dictionary_version; "
            f"found {sorted(versions)!r}."
        )

    return next(iter(versions))
MRI_SEQUENCE_FIELDS = (
    "MRI Sequence(s) (if applicable)",
    "MRI Sequence(s) - if MRI (multiselect)",
)
MRI_SEQUENCE_MAP = {
    "T1": ("anat", "T1w"),
    "T2": ("anat", "T2w"),
    "FLAIR": ("anat", "FLAIR"),
    "DWI": ("dwi", "dwi"),
    "SWI": ("anat", "SWI"),
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
EPHYS_REVIEW_STATE_FILENAME = "ephys_review_state.json"
PIPELINE_STATE_FILENAME = "imaging_pipeline_state.json"
IMAGING_BIDS_DRAFTS_FILENAME = "imaging_bids_drafts.json"
EDITABLE_HEADER_FIELDS = {"descrip", "aux_file", "intent_name"}
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from MetadataPipeline.forms.clinical_assessment import tracked_clinical_fields
from MetadataPipeline.storage import LocalMetadataStore
from MetadataPipeline.storage.data_link_store import PatientDataLinkStore
from MetadataPipeline.storage.record_deletion import RecordDeletionService
from MetadataPipeline.storage.record_repository import MetadataRepository
from MetadataPipeline.validation import MetadataValidator, load_dictionary
from app.site_access import normalize_site_id

from pipeline_config import (
    PipelineConfigError,
    build_imaging_settings_dict,
    build_settings_dict,
    load_imaging_config,
    load_pipeline_config,
    load_settings_dict,
    save_settings_dict,
    validate_pipeline_config,
)

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
                return normalize_patient_id(candidate)
        return ""

    return normalize_patient_id(value)

def _exclusive_multiselect_conflicts(
    metadata: dict[str, Any],
    rules: list[dict[str, Any]],
) -> list[str]:
    problems: list[str] = []

    for rule in rules:
        if str(
            rule.get(
                "input_type",
                "",
            )
        ).strip().lower() != "multi_select":
            continue

        field_name = str(
            rule.get(
                "field_name",
                "",
            )
            or ""
        ).strip()

        if not field_name:
            continue

        exclusive_values = {
            str(value)
            for value in (
                rule.get(
                    "exclusive_values",
                    [],
                )
                or []
            )
        }

        if not exclusive_values:
            continue

        value = metadata.get(
            field_name
        )

        if isinstance(
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
        elif value in (
            None,
            "",
        ):
            selected = []
        else:
            selected = [
                item.strip()
                for item in re.split(
                    r"[;|]",
                    str(value),
                )
                if item.strip()
            ]

        if len(selected) <= 1:
            continue

        conflict = next(
            (
                item
                for item in selected
                if item in exclusive_values
            ),
            None,
        )

        if conflict:
            problems.append(
                f"{field_name}: "
                f"{conflict} cannot be selected with other values."
            )

    return problems

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

def _normalize_field_key(value: Any) -> str:
    """
    Normalize field-name whitespace for legacy metadata compatibility.

    This collapses embedded newlines/tabs/repeated spaces so historical keys
    such as "Syndrome\\n(multiselect)" can match the current canonical
    dictionary field name "Syndrome (multiselect)".
    """
    return " ".join(
        str(value or "")
        .replace("\u00a0", " ")
        .split()
    )

def _canonicalize_metadata_keys(
    metadata: dict[str, Any],
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    source = dict(
        metadata or {}
    )

    canonical_by_normalized: dict[
        str,
        str,
    ] = {}
    canonical_names: set[str] = set()

    for rule in rules:
        field_name = str(
            rule.get(
                "field_name",
                "",
            )
            or ""
        ).strip()

        if not field_name:
            continue

        canonical_names.add(
            field_name
        )
        canonical_by_normalized[
            _normalize_field_key(
                field_name
            )
        ] = field_name

        for alias in (
            rule.get(
                "legacy_field_names",
                [],
            )
            or []
        ):
            alias_text = str(
                alias
                or ""
            ).strip()

            if not alias_text:
                continue

            canonical_by_normalized[
                _normalize_field_key(
                    alias_text
                )
            ] = field_name

    result: dict[str, Any] = {}

    for key, value in source.items():
        key_text = str(
            key
        )

        if key_text in canonical_names:
            result[
                key_text
            ] = value

    for key, value in source.items():
        key_text = str(
            key
        )

        if key_text in canonical_names:
            continue

        canonical = (
            canonical_by_normalized.get(
                _normalize_field_key(
                    key_text
                )
            )
        )

        if canonical:
            result.setdefault(
                canonical,
                value,
            )
        else:
            result[
                key_text
            ] = value

    return result

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

class CoCANoTAPI:
    """Methods exposed to React through PyWebView."""

    def __init__(self) -> None:
        self._window = None
        self.authenticated_site_id = ""
        self._reporting_session_token = ""
        self._pending_metadata_documents: dict[str, dict[str, Any]] = {}

        self.store = LocalMetadataStore()
        self.repository = MetadataRepository()

        self.ephys_sources: list[str] = []
        self.dicom_input_paths: list[str] = []
        self.nifti_input_paths: list[str] = []

        self.ephys_logs: list[str] = []
        self.imaging_logs: list[str] = []

        self.ephys_process: subprocess.Popen[str] | None = None
        self.imaging_process: subprocess.Popen[str] | None = None

        self.ephys_stage_state = {
            "scrub": "not_started",
            "review": "not_started",
            "metadata_bids": "not_started",
        }
        self.ephys_active_operation = ""
        self.ephys_status = "Ready"

        self.imaging_stage_state = {
            "prepare": "not_started",
            "scrub": "not_started",
            "deface": "not_started",
            "review": "not_started",
            "metadata_bids": "not_started",
        }
        self.imaging_active_operation = ""
        self._imaging_cleanup_context: dict[str, Any] | None = None

        self._load_initial_state()

    def _load_initial_state(self) -> None:
        try:
            settings = load_settings_dict()
        except Exception:
            settings = {}

        ephys = settings.get("electrophysiology", {})
        ephys_inputs = (
            ephys.get("selected_sources")
            or ephys.get("input_dirs")
            or ([ephys.get("input_dir")] if ephys.get("input_dir") else [])
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

    def get_site_id(self) -> str:
        return self.authenticated_site_id

    REPORTING_ENDPOINT = "https://script.google.com/macros/s/AKfycbzSRMdCIybLtilIdpETNNeoOd6vRPSoiu5fCm0GJWblC7EZwpNXIbguCwOr5jFFIsa0/exec"

    def _reporting_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "The requests package is required for online CoCANoT services. "
                "Install it in the app environment and include it in the .pkg build."
            ) from exc

        try:
            response = requests.post(
                self.REPORTING_ENDPOINT,
                json=payload,
                headers={"Accept": "application/json", "User-Agent": "CoCANoT-Desktop/1.0"},
                timeout=(10, 55),
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise RuntimeError(
                "The reporting service did not confirm the request in time. "
                "Your report may already be in GitHub. Retry the same report "
                "without changing its text to safely check its status."
            ) from exc
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise RuntimeError(
                f"Reporting service returned HTTP {status}. Check the web-app deployment."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"Reporting service connection failed ({type(exc).__name__}). "
                "Your report may already have arrived. Retry without editing its text."
            ) from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "The reporting service returned a non-JSON response. "
                "Check its deployment and access permissions."
            ) from exc
        if not isinstance(result, dict):
            raise RuntimeError("The reporting service returned an invalid JSON response.")
        return result

    def submit_bug_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.authenticated_site_id or not self._reporting_session_token:
            return {"ok": False, "message": "Sign in again before submitting a report."}
        summary = str((payload or {}).get("summary") or "").strip()
        description = str((payload or {}).get("description") or "").strip()
        steps = str((payload or {}).get("steps") or "").strip()
        request_id = str((payload or {}).get("requestId") or "").strip()
        if not re.fullmatch(r"[a-f0-9-]{36}", request_id, flags=re.I):
            return {"ok": False, "message": "Invalid report request ID. Restart Help & Support and try again."}
        if not summary or not description:
            return {"ok": False, "message": "Enter a summary and description."}
        if len(summary) > 160 or len(description) > 4000 or len(steps) > 3000:
            return {"ok": False, "message": "One or more fields exceed the permitted length."}
        try:
            result = self._reporting_request({
                "action": "report",
                "requestId": request_id,
                "sessionToken": self._reporting_session_token,
                "summary": summary,
                "description": description,
                "steps": steps,
            })
        except RuntimeError as exc:
            return {"ok": False, "message": str(exc)}
        if result.get("ok") is not True:
            return {"ok": False, "message": str(result.get("error") or "Report was not accepted.")}
        return {
            "ok": True,
            "issueNumber": result.get("issueNumber"),
            "issueUrl": result.get("issueUrl", ""),
        }

    def open_external_url(self, url: str) -> dict[str, Any]:
        target = str(url or "").strip()

        if not target:
            return {"ok": False, "message": "No URL was provided."}

        if not target.startswith(("https://github.com/", "http://github.com/")):
            return {
                "ok": False,
                "message": "Only GitHub links can be opened from Help & Support.",
            }

        try:
            opened = bool(webbrowser.open(target, new=2))
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

        return {
            "ok": opened,
            "message": "" if opened else "The system browser could not be opened.",
        }

    def authenticate_site(
        self,
        site_id: str,
        access_code: str,
    ) -> dict[str, Any]:
        normalized = normalize_site_id(site_id)
        if not normalized or not str(access_code or "").strip():
            return {"ok": False, "site_id": "", "message": "Enter both Site ID and Access Code."}
        self.authenticated_site_id = ""
        self._reporting_session_token = ""
        # The authentication endpoint is a Google Apps Script web app.
        # Use urllib's POST/redirect handling, matching the verified desktop
        # diagnostic and avoiding HTTP-client-specific HTML redirect pages.
        payload = json.dumps({
            "action": "login",
            "siteId": normalized,
            "accessCode": str(access_code).strip(),
        }).encode("utf-8")
        login_request = urllib_request.Request(
            self.REPORTING_ENDPOINT,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "CoCANoT-Desktop/1.0",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(login_request, timeout=25) as response:
                response_body = response.read()
            result = json.loads(response_body)
        except HTTPError as exc:
            return {"ok": False, "site_id": "", "message": f"Authentication service returned HTTP {exc.code}."}
        except (URLError, TimeoutError, OSError) as exc:
            return {"ok": False, "site_id": "", "message": f"Authentication connection failed ({type(exc).__name__})."}
        except (ValueError, UnicodeDecodeError):
            return {"ok": False, "site_id": "", "message": "Authentication service returned non-JSON data. Check the desktop HTTP connection."}
        if not isinstance(result, dict):
            return {"ok": False, "site_id": "", "message": "Invalid authentication service response."}
        if result.get("ok") is not True:
            return {"ok": False, "site_id": "", "message": str(result.get("error") or "Site authentication failed.")}
        returned_site = normalize_site_id(result.get("site_id"))
        token = str(result.get("sessionToken") or "")
        if returned_site != normalized or not token:
            return {"ok": False, "site_id": "", "message": "Invalid authentication service response."}
        saved = self.store.set_site_id(returned_site)
        self.authenticated_site_id = saved
        self._reporting_session_token = token
        return {"ok": True, "site_id": saved, "message": ""}

    def sign_out(self) -> dict[str, bool]:
        self.authenticated_site_id = ""
        self._reporting_session_token = ""
        return {"ok": True}

    def set_site_id(self, site_id: str) -> str:
        raise PermissionError(
            "Site access requires a valid Site ID and Access Code."
        )

    def choose_folder(self) -> str:
        if self._window is None:
            return ""

        result = self._window.create_file_dialog(
            webview.FileDialog.FOLDER,
        )

        if not result:
            return ""

        if isinstance(result, str):
            return result

        return str(result[0]) if result else ""

    def _sync_ephys_scrub_from_disk(self) -> None:
        """Recognize completed EDFs across file, parent, and subfolder selections.

        The most recent manifest is only a hint: earlier staged files remain
        authoritative when their content matches a currently selected source.
        Do not report completion unless both derivative and JSON exist.
        """
        try:
            config = load_pipeline_config()
            staging = config.electrophysiology.derivatives_dir / "_selected_raw"
            scrubbed = config.electrophysiology.scrubbed_dir
            selected = [
                Path(record["edf_path"]).expanduser().resolve()
                for record in _scan_edf_sources(self.ephys_sources)
                if record.get("edf_path") and record.get("include", True)
            ]
            if not selected:
                self.ephys_stage_state["scrub"] = "not_started"
                return
            if not staging.is_dir() or not scrubbed.is_dir():
                self.ephys_stage_state["scrub"] = "not_started"
                return

            manifest = staging / "selection.json"
            known: dict[str, list[Path]] = {}
            if manifest.is_file():
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                for source, relative in zip(
                    payload.get("selected_files") or [],
                    payload.get("staged_files") or [],
                ):
                    staged = (staging / str(relative)).resolve()
                    if staged.is_relative_to(staging.resolve()):
                        known.setdefault(str(Path(source).expanduser().resolve()), []).append(staged)

            staged_by_size: dict[int, list[Path]] = {}
            for candidate in staging.rglob("*.edf"):
                if candidate.is_file():
                    staged_by_size.setdefault(candidate.stat().st_size, []).append(candidate)
            hash_cache: dict[Path, str] = {}

            def file_hash(path: Path) -> str:
                if path not in hash_cache:
                    hash_cache[path] = self._file_hash(path)
                return hash_cache[path]

            def derivative_complete(staged: Path) -> bool:
                relative = staged.relative_to(staging)
                output = scrubbed / relative.parent / f"{staged.stem}_scrubbed.edf"
                sidecar = output.with_suffix(".json")
                if not (output.is_file() and output.stat().st_size > 0 and sidecar.is_file()):
                    return False
                try:
                    return isinstance(json.loads(sidecar.read_text(encoding="utf-8")), dict)
                except (OSError, ValueError, json.JSONDecodeError):
                    return False

            def complete(source: Path) -> bool:
                if not source.is_file():
                    return False
                candidates = known.get(str(source), []) + staged_by_size.get(source.stat().st_size, [])
                seen: set[Path] = set()
                for staged in candidates:
                    if staged in seen or not staged.is_file():
                        continue
                    seen.add(staged)
                    if staged.stat().st_size != source.stat().st_size:
                        continue
                    if derivative_complete(staged) and file_hash(source) == file_hash(staged):
                        return True
                return False

            self.ephys_stage_state["scrub"] = (
                "complete" if all(complete(source) for source in selected)
                else "not_started"
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, PipelineConfigError):
            self.ephys_stage_state["scrub"] = "not_started"

    def ephys_get_state(self) -> dict[str, Any]:
        try:
            settings = load_settings_dict()
        except Exception:
            settings = {}

        ephys = settings.get("electrophysiology", {})

        process_running = self._process_running(self.ephys_process)
        if not process_running:
            self._sync_ephys_scrub_from_disk()
        self._sync_ephys_review_stage()

        return {
            "input_dirs": list(self.ephys_sources),
            "records": _scan_edf_sources(self.ephys_sources),
            "derivatives_dir": str(ephys.get("derivatives_dir", "") or ""),
            "bids_output_dir": str(ephys.get("bids_output_dir", "") or ""),
            "status": self.ephys_status,
            "process_running": process_running,
            "active_operation": self.ephys_active_operation,
            "process_stages": dict(self.ephys_stage_state),
            "logs": list(self.ephys_logs),
        }

    def ephys_choose_files(self) -> dict[str, Any]:
        if self._window is None:
            return self.ephys_get_state()

        selected = self._window.create_file_dialog(
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
        if self._window is None:
            return self.ephys_get_state()

        selected = self._window.create_file_dialog(
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
        electrophysiology["input_dirs"] = list(config_inputs)
        electrophysiology["selected_sources"] = list(sources)

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

            self._sync_ephys_review_stage()
            self.ephys_status = "Ready for EDF review"

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
        staging.mkdir(parents=True, exist_ok=True)

        # Reuse earlier staging paths when the SAME EDF is selected via
        # a parent directory, subfolder, or individual file. This preserves
        # the review-state key and its already-scrubbed derivative.
        existing_by_size: dict[int, list[Path]] = {}
        for prior in staging.rglob("*.edf"):
            if prior.is_file():
                try:
                    existing_by_size.setdefault(prior.stat().st_size, []).append(prior)
                except OSError:
                    pass
        hash_cache: dict[str, str] = {}
        review_state = self._load_ephys_review_state(
            Path(derivatives_dir) / EPHYS_REVIEW_STATE_FILENAME
        )
        selected_files: list[str] = []
        staged_files: list[str] = []
        used_stage_paths: set[str] = set()

        for record in included:
            source = Path(str(record.get("edf_path", ""))).expanduser()
            if not source.is_file():
                continue
            source = source.resolve()
            try:
                candidate_paths = existing_by_size.get(source.stat().st_size, [])
                source_hash = self._file_hash(source)
            except OSError:
                continue
            matches: list[Path] = []
            for candidate in candidate_paths:
                key = str(candidate.resolve())
                if key not in hash_cache:
                    try:
                        hash_cache[key] = self._file_hash(candidate)
                    except OSError:
                        continue
                if hash_cache[key] == source_hash:
                    matches.append(candidate)
            def preferred(candidate: Path) -> tuple[int, int, str]:
                relative = candidate.relative_to(staging)
                old_review = review_state.get(str(relative), {})
                scrubbed_candidate = (
                    scrubbed_dir / relative.parent / f"{candidate.stem}_scrubbed.edf"
                )
                return (
                    0 if old_review.get("status") in {"Accepted", "Rejected - Not Included"} else 1,
                    0 if scrubbed_candidate.is_file() and scrubbed_candidate.with_suffix(".json").is_file() else 1,
                    str(candidate),
                )
            destination = sorted(matches, key=preferred)[0] if matches else None
            if destination is None:
                # Stable across file/folder selection depth and source order.
                source_id = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:16]
                destination = staging / f"edf-{source_id}" / source.name
                # Never overwrite a previously staged, different source.
                if destination.exists() and self._file_hash(destination) != source_hash:
                    destination = staging / f"edf-{source_id}-{source_hash[:12]}" / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    shutil.copy2(source, destination)
                hash_cache[str(destination.resolve())] = source_hash
                existing_by_size.setdefault(source.stat().st_size, []).append(destination)
            relative_staged = str(destination.relative_to(staging))
            if relative_staged in used_stage_paths:
                continue
            used_stage_paths.add(relative_staged)
            selected_files.append(str(source))
            staged_files.append(relative_staged)

        if not selected_files:
            raise ValueError("None of the included EDF source files could be found.")

        selection_log = {
            "source_folders": list(self.ephys_sources),
            "selected_files": selected_files,
            "staged_files": staged_files,
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
            "--selection-manifest",
            str(staging / "selection.json"),
        ]

        if overwrite:
            command.append("--overwrite")

        self.ephys_stage_state["scrub"] = "running"
        self.ephys_active_operation = "scrub"
        self.ephys_status = "Scrubbing EDF metadata"

        def finish_scrub(return_code: int) -> None:
            self.ephys_stage_state["scrub"] = (
                "complete" if return_code == 0 else "failed"
            )
            self.ephys_active_operation = ""
            self.ephys_status = (
                "EDF metadata scrubbing complete"
                if return_code == 0
                else f"EDF metadata scrubbing failed with code {return_code}"
            )

        self._start_process(
            command=command,
            workflow="ephys",
            description="EDF metadata scrubbing",
            on_complete=finish_scrub,
        )

        return {
            "ok": True,
            "status": "EDF metadata scrubbing started",
            "log": f"Staged {len(selected_files)} EDF file(s) in {staging}.",
        }

    @staticmethod
    def _load_ephys_review_state(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _save_ephys_review_state(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    def _sync_ephys_review_stage(self) -> None:
        try:
            pairs = self.ephys_review_get_pairs()
        except Exception:
            return

        if not pairs:
            if self.ephys_stage_state["review"] != "running":
                self.ephys_stage_state["review"] = "not_started"
            return

        terminal = {"Accepted", "Rejected - Not Included", "On Hold"}
        self.ephys_stage_state["review"] = (
            "complete"
            if all(str(pair.get("status", "Pending")) in terminal for pair in pairs)
            else "not_started"
        )

    def ephys_review_get_pairs(self) -> list[dict[str, Any]]:
        settings = load_settings_dict()
        ephys = settings.get(
            "electrophysiology",
            {},
        )

        if not ephys.get("input_dirs"):
            return []

        if not str(
            ephys.get(
                "derivatives_dir",
                "",
            )
            or ""
        ).strip():
            return []

        config = load_pipeline_config()
        input_dir = (
            config.electrophysiology.derivatives_dir
            / "_selected_raw"
        )
        scrubbed_dir = config.electrophysiology.scrubbed_dir
        state_path = (
            config.electrophysiology.derivatives_dir
            / EPHYS_REVIEW_STATE_FILENAME
        )

        if not input_dir.is_dir() or not scrubbed_dir.is_dir():
            return []

        review_state = self._load_ephys_review_state(state_path)
        helpers = _load_ephys_comparison_module()
        result: list[dict[str, Any]] = []
        export_index = self._index_existing_ephys_bids(
            config.electrophysiology.bids_output_dir
        )

        # The staging directory is persistent to preserve processing history.
        # Review only currently included recordings from the latest selection.
        selection_path = input_dir / "selection.json"
        active_keys: set[str] | None = None
        if selection_path.is_file():
            try:
                selection_data = json.loads(selection_path.read_text(encoding="utf-8"))
                values = selection_data.get("staged_files")
                if isinstance(values, list):
                    active_keys = {str(value) for value in values}
            except (OSError, json.JSONDecodeError):
                pass

        for raw_path in helpers.find_edf_files(input_dir):
            relative = raw_path.relative_to(input_dir)
            if active_keys is not None and str(relative) not in active_keys:
                continue
            scrubbed_path = (
                scrubbed_dir
                / relative.parent
                / helpers.scrubbed_filename(raw_path)
            )

            if not scrubbed_path.exists():
                continue

            key = str(relative)
            saved = review_state.get(key, {})
            exported = False
            if str(saved.get("status", "Pending")) == "Accepted":
                matched = self._existing_ephys_bids_export(scrubbed_path, export_index)
                if matched and matched.get("json_path"):
                    identity = matched.get("metadata", {})
                    exported = bool(
                        isinstance(identity, dict)
                        and str(identity.get("CoCANoT Patient ID") or "").strip()
                        and str(identity.get("Recording ID") or "").strip()
                    )
            result.append(
                {
                    "id": str(len(result)),
                    "key": key,
                    "label": key,
                    "status": str(saved.get("status", "Pending")),
                    "exported": exported,
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

        sidecar_path = Path(pair["scrubbed_path"]).with_suffix(".json")
        linked_metadata: dict[str, Any] = {}
        if sidecar_path.is_file():
            try:
                loaded = json.loads(sidecar_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    linked_metadata = loaded
            except (OSError, json.JSONDecodeError):
                pass
        if pair.get("exported"):
            config = load_pipeline_config()
            index = self._index_existing_ephys_bids(
                config.electrophysiology.bids_output_dir
            )
            export = self._existing_ephys_bids_export(
                Path(pair["scrubbed_path"]), index
            )
            if export and export.get("json_path"):
                try:
                    exported_json = json.loads(Path(export["json_path"]).read_text(encoding="utf-8"))
                    if isinstance(exported_json, dict):
                        # Include the full linked recording sidecar; put
                        # CoCANoT dictionary fields after acquisition fields.
                        linked_metadata = {
                            **{k: v for k, v in exported_json.items() if k != "CoCANoTMetadata"},
                            **({"CoCANoTMetadata": exported_json["CoCANoTMetadata"]}
                               if isinstance(exported_json.get("CoCANoTMetadata"), dict) else {}),
                        }
                except (OSError, json.JSONDecodeError):
                    pass

        return {
            **pair,
            "linked_metadata": linked_metadata,
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

    def ephys_review_set_status(
        self,
        pair_id: str | int,
        status: str,
    ) -> dict[str, Any]:
        pairs = self.ephys_review_get_pairs()

        try:
            index = int(pair_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid EDF review pair.")

        if index < 0 or index >= len(pairs):
            raise ValueError("EDF review pair not found.")

        normalized = str(status or "").strip()
        allowed = {"Accepted", "Rejected - Not Included", "On Hold", "Pending"}

        if normalized not in allowed:
            raise ValueError("Invalid EDF review status.")

        pair = pairs[index]
        config = load_pipeline_config()
        state_path = (
            config.electrophysiology.derivatives_dir
            / EPHYS_REVIEW_STATE_FILENAME
        )
        review_state = self._load_ephys_review_state(state_path)
        review_state[pair["key"]] = {
            "status": normalized,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_ephys_review_state(state_path, review_state)
        self._sync_ephys_review_stage()
        self._ephys_log(
            f"EDF review status updated: {pair['label']} -> {normalized}"
        )

        return self.ephys_review_get_pair(index)

    def ephys_review_save_pair(
        self,
        pair_id: str | int,
        scrubbed_header: dict[str, Any],
        scrubbed_annotations: list[dict[str, Any]],
        linked_metadata: dict[str, Any] | None = None,
        save_mode: str = "all",
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

        if save_mode not in {"all", "header", "annotations", "metadata"}:
            raise ValueError("Unsupported EDF save section.")
        if save_mode in {"all", "header", "annotations"}:
            existing = helpers.read_review_data(Path(pair["scrubbed_path"]))
            header_to_write = scrubbed_header if save_mode in {"all", "header"} else existing["header"]
            annotations_to_write = scrubbed_annotations if save_mode in {"all", "annotations"} else existing["annotations"]
            helpers.rewrite_scrubbed_edf(
                Path(pair["scrubbed_path"]), header_to_write, annotations_to_write
            )

        if save_mode in {"all", "metadata"} and linked_metadata is not None:
            if not isinstance(linked_metadata, dict):
                raise ValueError("Linked EDF metadata must be a JSON object.")
            # Do not silently change the already-exported final file.
            # Step 5 must explicitly re-export after EDF or metadata edits.
            sidecar_path = Path(pair["scrubbed_path"]).with_suffix(".json")
            temporary_sidecar = sidecar_path.with_suffix(".json.tmp")
            temporary_sidecar.write_text(
                json.dumps(linked_metadata, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            temporary_sidecar.replace(sidecar_path)

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
            "exclusive_values": [
                str(value)
                for value in (
                    rule.get(
                        "exclusive_values",
                        [],
                    )
                    or []
                )
            ],
            "repeat_for_each_field": str(
                rule.get(
                    "repeat_for_each_field"
                )
                or ""
            ),
            "repeat_exclude_values": [
                str(value)
                for value in (
                    rule.get(
                        "repeat_exclude_values",
                        [],
                    )
                    or []
                )
            ],
            "repeat_special_values": [
                str(value)
                for value in (
                    rule.get(
                        "repeat_special_values",
                        [],
                    )
                    or []
                )
            ],
            "repeat_prompt_template": str(
                rule.get(
                    "repeat_prompt_template"
                )
                or ""
            ),
            "available_after_surgery_months": (
                int(
                    rule.get(
                        "available_after_surgery_months"
                    )
                )
                if rule.get(
                    "available_after_surgery_months"
                )
                not in (
                    None,
                    "",
                )
                else None
            ),
        }

    def _dictionary_context(
        self,
        table_name: str,
        dictionary_version: str = "",
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        MetadataValidator,
    ]:
        path = (
            _dictionary_path_for_version(dictionary_version)
            if str(dictionary_version or "").strip()
            else _active_dictionary_path()
        )
        dictionary = load_dictionary(path)
        rules = dictionary[
            "tables"
        ][
            table_name
        ][
            "fields"
        ]
        _dictionary_version_from_table(
            dictionary,
            table_name,
        )
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
        normalized = _canonicalize_metadata_keys(
            dict(
                metadata or {}
            ),
            rules,
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

            elif rule.get(
                "repeat_for_each_field"
            ):
                parent_name = str(
                    rule.get(
                        "repeat_for_each_field"
                    )
                    or ""
                )
                parent_value = normalized.get(
                    parent_name
                )

                if isinstance(
                    parent_value,
                    list,
                ):
                    selected = [
                        str(item)
                        for item in parent_value
                    ]
                elif parent_value in (
                    None,
                    "",
                ):
                    selected = []
                else:
                    selected = [
                        str(parent_value)
                    ]

                excluded = {
                    str(item)
                    for item in (
                        rule.get(
                            "repeat_exclude_values",
                            [],
                        )
                        or []
                    )
                }
                applicable = [
                    item
                    for item in selected
                    if item not in excluded
                ]

                if value in (
                    None,
                    "",
                ):
                    repeated = {}
                elif isinstance(
                    value,
                    dict,
                ):
                    repeated = {
                        str(key): str(item).strip()
                        for key, item in value.items()
                        if str(key) in applicable
                        and str(item).strip()
                    }
                elif isinstance(
                    value,
                    str,
                ):
                    text = value.strip()
                    parsed = None

                    if text.startswith(
                        "{"
                    ):
                        try:
                            candidate = json.loads(
                                text
                            )
                        except json.JSONDecodeError:
                            candidate = None

                        if isinstance(
                            candidate,
                            dict,
                        ):
                            parsed = {
                                str(key): str(item).strip()
                                for key, item in candidate.items()
                                if str(key) in applicable
                                and str(item).strip()
                            }

                    if parsed is not None:
                        repeated = parsed
                    elif (
                        text
                        and len(
                            applicable
                        )
                        == 1
                    ):
                        repeated = {
                            applicable[
                                0
                            ]: text
                        }
                    else:
                        repeated = value
                else:
                    repeated = value

                normalized[
                    field_name
                ] = repeated

            elif value is None:
                normalized[
                    field_name
                ] = ""

        if "CoCANoT Patient ID" in normalized:
            normalized["CoCANoT Patient ID"] = normalize_patient_id(normalized["CoCANoT Patient ID"])
        for table, field in (("Surgical", "Surgery ID"), ("Imaging", "Image ID"), ("Electrophysiology", "Recording ID")):
            if field in normalized:
                normalized[field] = normalize_record_id(table, normalized[field])
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

    def _index_existing_ephys_bids(
        self,
        output_dir: Path,
    ) -> dict[int, list[dict[str, Any]]]:
        index: dict[int, list[dict[str, Any]]] = {}

        if not output_dir.exists():
            return index

        for path in output_dir.rglob("*.edf"):
            if not path.is_file():
                continue

            try:
                file_size = path.stat().st_size
            except OSError:
                continue

            sidecar_path = path.with_suffix(".json")
            metadata_path = path.with_name(
                f"{path.stem}_cocanot.json"
            )
            cocanot_metadata: dict[str, Any] = {}

            for candidate in (metadata_path, sidecar_path):
                if not candidate.is_file():
                    continue

                try:
                    payload = json.loads(
                        candidate.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    continue

                if not isinstance(payload, dict):
                    continue

                nested = payload.get("CoCANoTMetadata")
                if isinstance(nested, dict):
                    cocanot_metadata = dict(nested)
                    break

            index.setdefault(file_size, []).append(
                {
                    "edf_path": str(path.resolve()),
                    "json_path": (
                        str(sidecar_path.resolve())
                        if sidecar_path.is_file()
                        else ""
                    ),
                    "cocanot_metadata_path": (
                        str(metadata_path.resolve())
                        if metadata_path.is_file()
                        else ""
                    ),
                    "metadata": cocanot_metadata,
                    "sha256": "",
                }
            )

        return index

    def _existing_ephys_bids_export(
        self,
        path: Path,
        index: dict[int, list[dict[str, Any]]],
    ) -> dict[str, Any] | None:
        try:
            file_size = path.stat().st_size
        except OSError:
            return None

        candidates = index.get(file_size, [])
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
                            str(candidate["edf_path"])
                        )
                    )
                except OSError:
                    continue

                candidate["sha256"] = candidate_hash

            if candidate_hash == source_hash:
                return dict(candidate)

        return None

    def ephys_bids_get_state(
        self,
    ) -> dict[str, Any]:
        settings = load_settings_dict()
        ephys = settings.get(
            "electrophysiology",
            {},
        )

        if not ephys.get("input_dirs"):
            raise ValueError(
                "Configure the electrophysiology workflow first."
            )

        config = load_pipeline_config()
        scrubbed_dir = config.electrophysiology.scrubbed_dir
        output_dir = config.electrophysiology.bids_output_dir

        if not scrubbed_dir.exists():
            raise ValueError(
                "No scrubbed EDF directory exists. "
                "Run the scrubber first."
            )

        pairs = self.ephys_review_get_pairs()
        accepted_pairs = [
            pair
            for pair in pairs
            if str(pair.get("status", "")) == "Accepted"
        ]
        edf_files = [
            Path(pair["scrubbed_path"])
            for pair in accepted_pairs
            if Path(pair["scrubbed_path"]).is_file()
        ]
        pair_by_scrubbed = {
            _resolve_text(Path(pair["scrubbed_path"])): pair
            for pair in accepted_pairs
            if Path(pair["scrubbed_path"]).is_file()
        }

        if not edf_files:
            raise ValueError(
                "No accepted EDF recordings are available for Metadata & BIDS."
            )

        _dictionary, rules, _validator = (
            self._dictionary_context(
                "Electrophysiology"
            )
        )
        existing_bids_by_size = (
            self._index_existing_ephys_bids(
                output_dir
            )
        )
        records: list[dict[str, Any]] = []

        for index, edf_path in enumerate(
            edf_files,
            start=1,
        ):
            edf_path = edf_path.expanduser().resolve()
            sidecar = edf_path.with_suffix(".json")
            pair = pair_by_scrubbed.get(
                _resolve_text(edf_path),
                {},
            )
            derivative_paths = [
                str(Path(value).expanduser().resolve())
                for value in (
                    pair.get("raw_path", ""),
                    pair.get("scrubbed_path", ""),
                    str(sidecar.resolve()) if sidecar.exists() else "",
                )
                if str(value).strip()
                and Path(str(value)).expanduser().exists()
            ]
            existing_export = (
                self._existing_ephys_bids_export(
                    edf_path,
                    existing_bids_by_size,
                )
            )
            # Completion is scoped to the CURRENT configured BIDS output folder.
            # A legacy PatientDataLinkStore path in another folder is useful
            # for recovery, but cannot mark this output directory complete.
            if existing_export is not None:
                exported_path = Path(str(existing_export.get("edf_path", ""))).expanduser()
                try:
                    in_current_output = exported_path.resolve().is_relative_to(output_dir.resolve())
                except (OSError, ValueError):
                    in_current_output = False
                if (
                    not in_current_output
                    or not exported_path.is_file()
                    or not Path(str(existing_export.get("json_path", ""))).is_file()
                ):
                    existing_export = None

            project = ""
            project_description = ""
            session_id = ""
            record_state = "step5_pending"
            cocanot_metadata: dict[str, Any] = {
                "Recording Duration (hours)": (
                    self._recording_duration_hours(
                        edf_path
                    )
                ),
            }

            if existing_export is not None:
                stored_metadata = existing_export.get(
                    "metadata",
                    {},
                )
                if not isinstance(stored_metadata, dict):
                    stored_metadata = {}

                patient_id = str(
                    stored_metadata.get(
                        "CoCANoT Patient ID",
                        "",
                    )
                    or ""
                ).strip()
                recording_id = str(
                    stored_metadata.get(
                        "Recording ID",
                        "",
                    )
                    or ""
                ).strip()

                local_record = None
                if patient_id and recording_id:
                    local_record = self.repository.get_record(
                        self.get_site_id(),
                        "Electrophysiology",
                        recording_id,
                        patient_id=patient_id,
                    )

                existing_path = Path(
                    str(existing_export["edf_path"])
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

                if project:
                    dataset_description = (
                        output_dir
                        / project
                        / "dataset_description.json"
                    )
                    if dataset_description.is_file():
                        try:
                            dataset_payload = json.loads(
                                dataset_description.read_text(
                                    encoding="utf-8"
                                )
                            )
                        except (OSError, json.JSONDecodeError):
                            dataset_payload = {}

                        if isinstance(dataset_payload, dict):
                            project_description = str(
                                dataset_payload.get(
                                    "Description",
                                    "",
                                )
                                or ""
                            )

                if local_record is not None:
                    record_state = "completed_recorded"
                    local_metadata = local_record.get(
                        "metadata",
                        {},
                    )
                    if isinstance(local_metadata, dict):
                        cocanot_metadata.update(
                            local_metadata
                        )

                    local_context = local_record.get(
                        "context",
                        {},
                    )
                    if isinstance(local_context, dict):
                        project = str(
                            local_context.get(
                                "project",
                                project,
                            )
                            or project
                        )
                        project_description = str(
                            local_context.get(
                                "project_description",
                                project_description,
                            )
                            or project_description
                        )
                        session_id = str(
                            local_context.get(
                                "session_id",
                                session_id,
                            )
                            or session_id
                        )
                else:
                    record_state = "output_record_deleted"
                    if stored_metadata:
                        cocanot_metadata.update(
                            stored_metadata
                        )

            records.append(
                {
                    "id": f"record-{index}",
                    "include": record_state == "step5_pending",
                    "edf_path": str(edf_path),
                    "sidecar_path": (
                        str(sidecar.resolve())
                        if sidecar.exists()
                        else ""
                    ),
                    "derivatives_root": str(
                        config.electrophysiology.derivatives_dir
                    ),
                    "derivative_paths": derivative_paths,
                    "source_label": str(
                        edf_path.relative_to(
                            scrubbed_dir
                        )
                    ),
                    "project": project,
                    "project_description": project_description,
                    "session_id": session_id,
                    "cocanot_metadata": cocanot_metadata,
                    "existing_export": existing_export,
                    "record_state": record_state,
                    "metadata_preloaded_from_output": (
                        record_state == "output_record_deleted"
                        and bool(cocanot_metadata)
                    ),
                    "metadata_source_path": (
                        str(
                            existing_export.get(
                                "cocanot_metadata_path",
                                "",
                            )
                            or existing_export.get(
                                "json_path",
                                "",
                            )
                        )
                        if existing_export is not None
                        else ""
                    ),
                    "metadata_confirmed": (
                        record_state == "completed_recorded"
                    ),
                    "status": {
                        "completed_recorded": "Completed & recorded",
                        "output_record_deleted": "Output exists, record deleted",
                        "step5_pending": "Ready for Step 5",
                    }[record_state],
                }
            )

        all_completed_recorded = (
            bool(records)
            and all(
                record.get("record_state") == "completed_recorded"
                for record in records
            )
        )

        if all_completed_recorded:
            self.ephys_stage_state[
                "metadata_bids"
            ] = "complete"
            self.ephys_status = (
                "Metadata & BIDS export already exists"
            )
        elif (
            self._process_running(self.ephys_process)
            and self.ephys_active_operation == "bids"
        ):
            self.ephys_stage_state[
                "metadata_bids"
            ] = "running"
        elif self.ephys_stage_state.get(
            "metadata_bids"
        ) != "failed":
            self.ephys_stage_state[
                "metadata_bids"
            ] = "not_started"

        return {
            "site_id": self.get_site_id(),
            "records": records,
            "rules": [
                self._rule_payload(rule)
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
                output_dir
            ),
            "process_stages": dict(
                self.ephys_stage_state
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
        missing_clinical_assessments: list[
            dict[str, str]
        ] = []
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

                    if not any(
                        item.get("patient_id") == patient_id
                        for item in missing_clinical_assessments
                    ):
                        missing_clinical_assessments.append(
                            {
                                "patient_id": patient_id,
                                "source_label": source_label,
                            }
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
            "missing_clinical_assessments": (
                missing_clinical_assessments
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
                    "derivatives_root": str(
                        config.electrophysiology.derivatives_dir
                    ),
                    "derivative_paths": list(
                        record.get(
                            "derivative_paths",
                            [],
                        )
                        or []
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
                    "sidecar_metadata": record.get("sidecar_metadata", {}),
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

        self.ephys_stage_state["metadata_bids"] = "running"
        self.ephys_active_operation = "bids"
        self.ephys_status = "Creating final BIDS-compatible output"

        def finish_bids(return_code: int) -> None:
            self.ephys_stage_state["metadata_bids"] = (
                "complete" if return_code == 0 else "failed"
            )
            self.ephys_active_operation = ""
            self.ephys_status = (
                "Metadata & BIDS export complete"
                if return_code == 0
                else f"Metadata & BIDS export failed with code {return_code}"
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
            on_complete=finish_bids,
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

    def _refresh_imaging_review_stage(self) -> None:
        if self.imaging_stage_state.get("deface") != "complete":
            return

        try:
            items, _ = self._imaging_review_items()
        except Exception:
            return

        if not items:
            if self.imaging_stage_state.get("review") not in {
                "running",
                "failed",
                "stopped",
            }:
                self.imaging_stage_state["review"] = "not_started"
            return

        final_statuses = {
            "Accepted",
            "Accepted - External",
            "Rejected - Not Included",
            "On Hold - Needs Defaced Replacement",
        }
        statuses = [
            str(item.get("status", "Pending") or "Pending")
            for item in items
        ]

        if statuses and all(status in final_statuses for status in statuses):
            self.imaging_stage_state["review"] = "complete"
        elif any(status != "Pending" for status in statuses):
            self.imaging_stage_state["review"] = "running"
        elif self.imaging_stage_state.get("review") not in {
            "running",
            "failed",
            "stopped",
        }:
            self.imaging_stage_state["review"] = "not_started"

    def imaging_get_state(self) -> dict[str, Any]:
        try:
            settings = load_settings_dict()
        except Exception:
            settings = {}

        imaging = settings.get("imaging", {})
        awareness = {"source": "unavailable", "note": ""}

        try:
            config = load_imaging_config()
            awareness = self._sync_imaging_stage_state_from_disk(config)
        except Exception:
            self._refresh_imaging_review_stage()

        process_running = self._process_running(
            self.imaging_process
        )

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
                f"Running: {self.imaging_active_operation}"
                if process_running and self.imaging_active_operation
                else "Running"
                if process_running
                else "Ready"
            ),
            "process_running": process_running,
            "active_operation": self.imaging_active_operation,
            "process_stages": dict(self.imaging_stage_state),
            "awareness": awareness,
            "pipeline_state_path": (
                str(Path(str(imaging.get("derivatives_dir", "") or "")) / PIPELINE_STATE_FILENAME)
                if str(imaging.get("derivatives_dir", "") or "").strip()
                else ""
            ),
            "logs": list(self.imaging_logs),
        }

    def _select_files(
        self,
        *,
        kind: str,
    ) -> list[str]:
        if self._window is None:
            return []

        file_types = (
            ("NIfTI files (*.nii;*.gz)", "All files (*.*)")
            if kind == "nifti"
            else ("DICOM files (*.dcm)", "All files (*.*)")
        )

        selected = self._window.create_file_dialog(
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
        if self._window is None:
            return []

        selected = self._window.create_file_dialog(
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
            "pipeline_state": derivatives / PIPELINE_STATE_FILENAME,
            "bids_drafts": derivatives / IMAGING_BIDS_DRAFTS_FILENAME,
        }

    def _create_imaging_stage_dirs(
        self,
        config,
    ) -> None:
        stages = self._imaging_stage_paths(config)

        for name, path in stages.items():
            if name in {"review_state", "pipeline_state", "bids_drafts"}:
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

    @staticmethod
    def _imaging_source_fingerprint(path: Path) -> dict[str, Any]:
        path = path.expanduser()

        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        if resolved.is_file():
            try:
                stat = resolved.stat()
            except OSError:
                return {"path": str(resolved), "kind": "missing"}

            return {
                "path": str(resolved),
                "kind": "file",
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }

        if resolved.is_dir():
            entries: list[dict[str, Any]] = []

            try:
                candidates = sorted(
                    child
                    for child in resolved.rglob("*")
                    if child.is_file()
                    and not child.name.startswith(".")
                )
            except (OSError, PermissionError):
                candidates = []

            for child in candidates:
                try:
                    stat = child.stat()
                    relative = str(child.relative_to(resolved))
                except (OSError, ValueError):
                    continue

                entries.append(
                    {
                        "path": relative,
                        "size": int(stat.st_size),
                        "mtime_ns": int(stat.st_mtime_ns),
                    }
                )

            return {
                "path": str(resolved),
                "kind": "directory",
                "entries": entries,
            }

        return {"path": str(resolved), "kind": "missing"}

    def _imaging_selection_fingerprint(self) -> dict[str, Any]:
        return {
            "dicom": [
                self._imaging_source_fingerprint(Path(value))
                for value in self.dicom_input_paths
            ],
            "nifti": [
                self._imaging_source_fingerprint(Path(value))
                for value in self.nifti_input_paths
            ],
        }

    def _imaging_selection_signature(self) -> str:
        payload = json.dumps(
            self._imaging_selection_fingerprint(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _load_imaging_pipeline_state(state_path: Path) -> dict[str, Any]:
        if not state_path.exists():
            return {}

        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return payload if isinstance(payload, dict) else {}

    def _imaging_completion_history_path(self, config) -> Path:
        return config.imaging.derivatives_dir / "imaging_selection_history.json"

    def _read_imaging_completion_history(self, config) -> dict[str, Any]:
        path = self._imaging_completion_history_path(config)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _record_imaging_completion_history(self, config) -> None:
        """Preserve stage completions for each selection across removal/re-add."""
        signature = self._imaging_selection_signature()
        if not self.dicom_input_paths and not self.nifti_input_paths:
            return
        history = self._read_imaging_completion_history(config)
        previous = history.get(signature, {})
        if not isinstance(previous, dict):
            previous = {}
        stages = self._imaging_stage_paths(config)
        recorded = dict(previous.get("stages", {}))
        for key in ("prepare", "scrub", "deface"):
            if self.imaging_stage_state.get(key) == "complete":
                recorded[key] = "complete"
        # Record actual derivative paths when possible. Also preserve
        # previously recorded paths, because selecting fewer sources
        # should not overwrite their records.
        prepared = (
            self._matched_selected_nifti_derivatives(stages["converted"])
            if self.nifti_input_paths and not self.dicom_input_paths
            else self._matched_selected_dicom_derivatives(stages)
            if self.dicom_input_paths and not self.nifti_input_paths
            else []
        )
        if prepared:
            recorded_paths = [
                str(p.relative_to(stages["converted"])) for p in prepared
            ]
        else:
            recorded_paths = list(previous.get("prepared_files", []))
        # The process itself knows which new outputs it produced even when
        # legacy directory names cannot be inferred from the source path.
        context = self._imaging_cleanup_context or {}
        if context.get("operation") == "prepare":
            root_key = _resolve_text(stages["converted"])
            before = set(context.get("before", {}).get(root_key, set()))
            produced = [
                str(p.relative_to(stages["converted"]))
                for p in self._all_nifti_files(stages["converted"])
                if _resolve_text(p) not in before
            ]
            if produced:
                recorded_paths = produced
        history[signature] = {
            "sources": self._imaging_selection_fingerprint(),
            "stages": recorded,
            "prepared_files": recorded_paths,
        }
        path = self._imaging_completion_history_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")

    def _restore_imaging_completion_history(
        self, config, stages: dict[str, Path],
    ) -> tuple[bool, bool, bool] | None:
        """Restore one or several independently completed source selections.

        A multi-source selection is complete at a stage only when EVERY
        selected source has matching, verified outputs at that stage.
        """
        history = self._read_imaging_completion_history(config)
        fingerprint = self._imaging_selection_fingerprint()
        selected_sources = [
            (kind, item)
            for kind in ("dicom", "nifti")
            for item in fingerprint.get(kind, [])
        ]
        if not selected_sources:
            return None

        # Reconstruct multi-source completion from any combination of saved
        # groups, independent of selection order and folder depth.  Entries
        # contribute only the input files they actually covered; never infer
        # completion of a new source from a different processed source.
        def file_ids(sources: dict[str, Any]) -> set[tuple[str, str, int, int]] | None:
            identities: set[tuple[str, str, int, int]] = set()
            try:
                for kind in ("dicom", "nifti"):
                    for item in sources.get(kind, []):
                        root = Path(str(item["path"])).expanduser()
                        if item.get("kind") == "file":
                            files = [(root, item)]
                        elif item.get("kind") == "directory":
                            files = []
                            for child in item.get("entries", []):
                                relative = Path(str(child["path"]))
                                if relative.is_absolute() or ".." in relative.parts:
                                    return None
                                files.append((root / relative, child))
                        else:
                            return None
                        for path, details in files:
                            # Match real input identity; a renamed folder alone
                            # must not invalidate a completed series.
                            identities.add((
                                kind, str(path.resolve()),
                                int(details["size"]), int(details["mtime_ns"]),
                            ))
            except (KeyError, TypeError, ValueError, OSError):
                return None
            return identities or None

        selected_ids = file_ids(fingerprint)
        if selected_ids:
            converted_root = stages["converted"].resolve()
            covered = {"prepare": set(), "scrub": set(), "deface": set()}
            for entry in history.values():
                if not isinstance(entry, dict) or not isinstance(entry.get("sources"), dict):
                    continue
                entry_ids = file_ids(entry["sources"])
                if not entry_ids or not entry_ids.issubset(selected_ids):
                    continue
                names = entry.get("prepared_files", [])
                recorded = entry.get("stages", {})
                if not isinstance(names, list) or not names or not isinstance(recorded, dict):
                    continue
                prepared = []
                for name in names:
                    candidate = (converted_root / str(name)).resolve()
                    if not candidate.is_relative_to(converted_root) or not (
                        candidate.is_file() and _is_nifti(candidate)
                        and candidate.stat().st_size > 0
                    ):
                        break
                    prepared.append(candidate)
                else:
                    if recorded.get("prepare") != "complete":
                        continue
                    covered["prepare"].update(entry_ids)
                    scrubbed = []
                    for source in prepared:
                        relative = source.relative_to(converted_root)
                        base = self._strip_nifti_suffix(source)
                        options = (
                            stages["scrubbed"] / relative.parent / f"{base}_scrubbed.nii.gz",
                            stages["scrubbed"] / relative.parent / f"{base}_scrubbed.nii",
                        )
                        match = next((p for p in options if p.is_file() and p.stat().st_size > 0), None)
                        if match is None:
                            break
                        scrubbed.append(match)
                    if recorded.get("scrub") != "complete" or len(scrubbed) != len(prepared):
                        continue
                    covered["scrub"].update(entry_ids)
                    for source in scrubbed:
                        relative = source.relative_to(stages["scrubbed"])
                        base = self._strip_nifti_suffix(source)
                        options = (
                            stages["defaced"] / relative.parent / f"{base}_defaced.nii.gz",
                            stages["defaced"] / relative.parent / f"{base}_defaced.nii",
                        )
                        if not any(p.is_file() and p.stat().st_size > 0 for p in options):
                            break
                    else:
                        if recorded.get("deface") == "complete":
                            covered["deface"].update(entry_ids)
            if selected_ids.issubset(covered["prepare"]):
                return (
                    True,
                    selected_ids.issubset(covered["scrub"]),
                    selected_ids.issubset(covered["deface"]),
                )

        def source_key(kind: str, item: dict[str, Any]) -> str:
            return json.dumps([kind, item], sort_keys=True, separators=(",", ":"))

        def entry_sources(entry: dict[str, Any]) -> list[str]:
            saved = entry.get("sources", {})
            if not isinstance(saved, dict):
                return []
            return [
                source_key(kind, item)
                for kind in ("dicom", "nifti")
                for item in saved.get(kind, [])
                if isinstance(item, dict)
            ]

        exact = history.get(self._imaging_selection_signature())
        selected_keys = [source_key(kind, item) for kind, item in selected_sources]
        selected_set = set(selected_keys)
        records_to_check: list[dict[str, Any]] = []
        if (
            isinstance(exact, dict)
            and len(entry_sources(exact)) == len(selected_keys)
            and set(entry_sources(exact)) == selected_set
            and isinstance(exact.get("prepared_files"), list)
            and bool(exact.get("prepared_files"))
            and exact.get("stages", {}).get("prepare") == "complete"
        ):
            records_to_check = [exact]
        else:
            # A parent folder and its only child folder may contain exactly
            # the same source files. Treat them as the same selection using
            # absolute file identities, not their container paths.
            def expanded_files(sources: dict[str, Any]) -> list[tuple[str, str, int, int]] | None:
                identities = []
                for kind in ("dicom", "nifti"):
                    for item in sources.get(kind, []):
                        if not isinstance(item, dict):
                            return None
                        root = Path(str(item.get("path", ""))).expanduser()
                        if item.get("kind") == "file":
                            files = [(root, item)]
                        elif item.get("kind") == "directory":
                            files = []
                            for child in item.get("entries", []):
                                if not isinstance(child, dict):
                                    return None
                                rel = Path(str(child.get("path", "")))
                                if rel.is_absolute() or ".." in rel.parts:
                                    return None
                                files.append((root / rel, child))
                        else:
                            return None
                        for file_path, detail in files:
                            # Include all files, not merely NIfTI/DICOM suffixes:
                            # selecting an extra source must not inherit a
                            # completion record for a smaller selection.
                            identities.append((
                                kind, str(file_path.resolve()),
                                int(detail.get("size", -1)),
                                int(detail.get("mtime_ns", -1)),
                            ))
                return sorted(identities) if identities else None

            selected_files = expanded_files(fingerprint)
            equivalent = [
                entry for entry in history.values()
                if isinstance(entry, dict)
                and isinstance(entry.get("sources"), dict)
                and selected_files is not None
                and expanded_files(entry["sources"]) == selected_files
                and entry.get("stages", {}).get("prepare") == "complete"
                and isinstance(entry.get("prepared_files"), list)
                and bool(entry["prepared_files"])
            ]
            if equivalent:
                # Equivalent history records may exist for both the parent
                # and child selection. Verify every candidate's actual
                # derivative paths below; don't rely on selection labels.
                records_to_check = [equivalent[-1]]
            else:
                # Older history records were keyed to the entire selection.
                # Find a completed single-source record for each currently
                # selected source without depending on selection order.
                for kind, item in selected_sources:
                    key = source_key(kind, item)
                    matching = [
                        entry for entry in history.values()
                        if isinstance(entry, dict) and entry_sources(entry) == [key]
                        and isinstance(entry.get("prepared_files"), list)
                        and entry.get("prepared_files")
                    ]
                    if len(matching) == 1:
                        records_to_check.append(matching[0])
                        continue

                    # An individually selected file and its containing folder
                    # have different selection signatures. Expand the folder
                    # into its imaging files and combine their saved records.
                    # Never consider a folder complete if even one input is
                    # missing from the history.
                    if item.get("kind") != "directory":
                        return None
                    folder = Path(str(item.get("path", "")))
                    children = []
                    for child in item.get("entries", []):
                        if not isinstance(child, dict):
                            continue
                        relative = Path(str(child.get("path", "")))
                        if relative.is_absolute() or ".." in relative.parts:
                            return None
                        suffix = (folder / relative).suffix.lower()
                        if kind == "nifti":
                            valid = str(relative).lower().endswith((".nii", ".nii.gz"))
                        else:
                            valid = suffix in {".dcm", ".ima", ""}
                        if not valid:
                            continue
                        child_item = {
                            "path": str(folder / relative),
                            "kind": "file",
                            "size": child.get("size"),
                            "mtime_ns": child.get("mtime_ns"),
                        }
                        children.append(source_key(kind, child_item))
                    if not children:
                        return None
                    for child_key in children:
                        child_matches = [
                            entry for entry in history.values()
                            if isinstance(entry, dict)
                            and entry_sources(entry) == [child_key]
                            and isinstance(entry.get("prepared_files"), list)
                            and entry.get("prepared_files")
                        ]
                        if len(child_matches) != 1:
                            return None
                        records_to_check.append(child_matches[0])

        converted = stages["converted"].resolve()

        def paired(paths: list[Path], input_root: Path,
                   output_root: Path, suffix: str) -> list[Path]:
            result = []
            for source in paths:
                relative = source.relative_to(input_root)
                base = self._strip_nifti_suffix(source)
                match = next((p for p in (
                    output_root / relative.parent / f"{base}_{suffix}.nii.gz",
                    output_root / relative.parent / f"{base}_{suffix}.nii",
                ) if p.is_file() and p.stat().st_size > 0), None)
                if match is None:
                    return []
                result.append(match)
            return result

        stage_results = []
        for entry in records_to_check:
            records = entry.get("stages", {})
            names = entry.get("prepared_files", [])
            if not isinstance(records, dict) or not isinstance(names, list) or not names:
                return None
            prepared = []
            for name in names:
                candidate = (converted / str(name)).resolve()
                if not candidate.is_relative_to(converted) or not (
                    candidate.is_file() and _is_nifti(candidate)
                    and candidate.stat().st_size > 0
                ):
                    return None
                prepared.append(candidate)
            if records.get("prepare") != "complete":
                return None
            scrubbed = paired(prepared, stages["converted"], stages["scrubbed"], "scrubbed")
            scrub_ok = (
                records.get("scrub") == "complete"
                and len(scrubbed) == len(prepared)
            )
            defaced = (
                paired(scrubbed, stages["scrubbed"], stages["defaced"], "defaced")
                if scrub_ok else []
            )
            deface_ok = (
                records.get("deface") == "complete"
                and scrub_ok and len(defaced) == len(scrubbed)
            )
            stage_results.append((True, scrub_ok, deface_ok))

        return tuple(all(row[index] for row in stage_results) for index in range(3))

    def _save_imaging_pipeline_state(
        self,
        config,
        *,
        note: str = "",
    ) -> None:
        stages = self._imaging_stage_paths(config)
        state_path = stages["pipeline_state"]

        payload = {
            "version": 1,
            "selection_signature": self._imaging_selection_signature(),
            "sources": self._imaging_selection_fingerprint(),
            "derivatives_dir": str(config.imaging.derivatives_dir),
            "final_output_dir": str(config.imaging.bids_output_dir),
            "stages": dict(self.imaging_stage_state),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if note:
            payload["note"] = str(note)

        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _all_nifti_files(root: Path) -> list[Path]:
        if not root.exists():
            return []

        return sorted(
            path
            for path in root.rglob("*")
            if _is_nifti(path)
        )

    def _expected_prepared_nifti_paths(
        self,
        converted_dir: Path,
    ) -> list[Path] | None:
        if self.dicom_input_paths:
            return None

        expected: list[Path] = []

        for source_index, source_text in enumerate(
            self.nifti_input_paths,
            start=1,
        ):
            source = Path(source_text).expanduser()

            if source.is_file():
                if _is_nifti(source):
                    expected.append(
                        converted_dir
                        / f"nifti-file-{source_index:03d}"
                        / source.name
                    )
                continue

            if not source.is_dir():
                continue

            for nifti_path in sorted(
                path
                for path in source.rglob("*")
                if _is_nifti(path)
            ):
                expected.append(
                    converted_dir
                    / f"nifti-source-{source_index:03d}"
                    / nifti_path.relative_to(source)
                )

        return expected

    @staticmethod
    def _files_match_for_imaging_resume(source: Path, prepared: Path) -> bool:
        """Verify copied NIfTI contents, not merely a matching filename."""
        if not source.is_file() or not prepared.is_file():
            return False
        if source.stat().st_size != prepared.stat().st_size:
            return False
        for path in (source, prepared):
            if not path.is_file():
                return False
        digests = []
        for path in (source, prepared):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digests.append(digest.digest())
        return digests[0] == digests[1]

    def _matched_selected_nifti_derivatives(self, converted_dir: Path) -> list[Path]:
        """Locate selected NIfTI sources by content, independent of source index.

        Source indices change as folders are added/reordered. Compare the
        selected images with staged derivatives instead of relying on their
        former nifti-file-001 or nifti-source-001 directories.
        """
        if self.dicom_input_paths or not self.nifti_input_paths:
            return []
        sources: list[Path] = []
        for text in self.nifti_input_paths:
            source = Path(text).expanduser()
            if source.is_file() and _is_nifti(source):
                sources.append(source)
            elif source.is_dir():
                sources.extend(sorted(p for p in source.rglob("*") if _is_nifti(p)))
            else:
                return []
        if not sources:
            return []
        candidates = self._all_nifti_files(converted_dir)
        matches: list[Path] = []
        used: set[Path] = set()
        for source in sources:
            for staged in candidates:
                if staged in used:
                    continue
                # The staged filename may have changed; a verified byte match
                # is stronger than requiring the original name.
                if self._files_match_for_imaging_resume(source, staged):
                    matches.append(staged)
                    used.add(staged)
                    break
            else:
                return []
        return matches

    def _verify_selected_nifti_copies(self, converted_dir: Path) -> bool:
        return bool(self._matched_selected_nifti_derivatives(converted_dir))

    def _verify_selected_nifti_stages(self, stages: dict[str, Path]) -> tuple[bool, bool, bool]:
        prepared = self._matched_selected_nifti_derivatives(stages["converted"])
        if not prepared:
            return False, False, False
        scrubbed: list[Path] = []
        for path in prepared:
            relative = path.relative_to(stages["converted"])
            base = self._strip_nifti_suffix(path)
            next_path = next((p for p in (
                stages["scrubbed"] / relative.parent / f"{base}_scrubbed.nii.gz",
                stages["scrubbed"] / relative.parent / f"{base}_scrubbed.nii",
            ) if p.is_file() and p.stat().st_size > 0), None)
            if next_path is None:
                return True, False, False
            scrubbed.append(next_path)
        for path in scrubbed:
            relative = path.relative_to(stages["scrubbed"])
            base = self._strip_nifti_suffix(path)
            if not any(p.is_file() and p.stat().st_size > 0 for p in (
                stages["defaced"] / relative.parent / f"{base}_defaced.nii.gz",
                stages["defaced"] / relative.parent / f"{base}_defaced.nii",
            )):
                return True, True, False
        return True, True, True

    def _matched_selected_dicom_derivatives(
        self, stages: dict[str, Path],
    ) -> list[Path]:
        """Find conversion outputs without depending on Step 1 list indices.

        Prefer the converter's exact relative layout, then legacy roots
        from prior selections. Duplicate paths are ignored. A candidate
        must contain real non-empty NIfTI files.
        """
        if not self.dicom_input_paths or self.nifti_input_paths:
            return []
        roots = [Path(v).expanduser().resolve() for v in self.dicom_input_paths]
        if not roots or any(not root.is_dir() for root in roots):
            return []
        converted = stages["converted"]
        output_roots = [converted] + sorted(
            p for p in converted.glob("source-[0-9][0-9][0-9]")
            if p.is_dir()
        )
        # For a selected SER/OBJ folder, previous conversions may have been
        # launched from its parent SER folder (or directly from OBJ).
        # Historical mappings are safer than guessing which source-NNN
        # output belongs to a similarly named patient series.
        history = self._read_imaging_completion_history(
            load_imaging_config()
        )
        current_fingerprint = self._imaging_selection_fingerprint()

        def dicom_identity(fingerprint: dict[str, Any]) -> list[tuple[str, int, int]]:
            result = []
            for item in fingerprint.get("dicom", []):
                if not isinstance(item, dict):
                    continue
                base = Path(str(item.get("path", "")))
                entries = (
                    [(base, item)] if item.get("kind") == "file"
                    else [
                        (base / str(child.get("path", "")), child)
                        for child in item.get("entries", [])
                        if isinstance(child, dict)
                    ] if item.get("kind") == "directory" else []
                )
                for file_path, detail in entries:
                    if file_path.suffix.lower() not in {".dcm", ".ima", ""}:
                        continue
                    result.append((
                        str(file_path.resolve()),
                        int(detail.get("size", -1)),
                        int(detail.get("mtime_ns", -1)),
                    ))
            return sorted(set(result))

        selected_identity = dicom_identity(current_fingerprint)
        historical_prepared = []
        if selected_identity:
            for entry in history.values():
                if not isinstance(entry, dict):
                    continue
                sources = entry.get("sources", {})
                if not isinstance(sources, dict) or sources.get("nifti"):
                    continue
                if dicom_identity(sources) != selected_identity:
                    continue
                if entry.get("stages", {}).get("prepare") != "complete":
                    continue
                prepared_files = entry.get("prepared_files", [])
                if not isinstance(prepared_files, list) or not prepared_files:
                    continue
                candidates = []
                for relative_text in prepared_files:
                    candidate = (converted / str(relative_text)).resolve()
                    if not candidate.is_relative_to(converted.resolve()) or not (
                        candidate.is_file() and _is_nifti(candidate)
                        and candidate.stat().st_size > 0
                    ):
                        break
                    candidates.append(candidate)
                else:
                    historical_prepared = candidates
                    break
        if historical_prepared:
            return historical_prepared

        def outputs(directory: Path) -> list[Path]:
            if not directory.is_dir():
                return []
            return sorted(
                p for p in directory.iterdir()
                if p.is_file() and _is_nifti(p) and p.stat().st_size > 0
            )

        selected: list[Path] = []
        for root in roots:
            dicom_dirs: list[Path] = []
            for directory in [root, *sorted(p for p in root.rglob("*") if p.is_dir())]:
                try:
                    contains_dicom = any(
                        p.is_file() and not p.name.startswith(".")
                        and p.suffix.lower() in {".dcm", ".ima", ""}
                        for p in directory.iterdir()
                    )
                except (OSError, PermissionError):
                    return []
                if contains_dicom:
                    dicom_dirs.append(directory)
            if not dicom_dirs:
                return []
            for folder in dicom_dirs:
                relative = folder.relative_to(root)
                # Try the current converter layout first. Re-addition can
                # change the source-NNN prefix or select a nested ancestor.
                suffixes = [relative]
                for count in range(1, len(folder.parts) + 1):
                    candidate = Path(*folder.parts[-count:])
                    if candidate not in suffixes:
                        suffixes.append(candidate)
                matches = []
                for suffix in suffixes:
                    for output_root in output_roots:
                        destination = output_root / suffix
                        files = outputs(destination)
                        if files and destination not in [m[0] for m in matches]:
                            matches.append((destination, files, len(suffix.parts)))
                if not matches:
                    return []
                # Prefer the longest distinctive relative path. If multiple
                # former numbered roots match that path, their files must
                # be uniquely attributable; do not guess between them.
                highest = max(score for _, _, score in matches)
                best = [item for item in matches if item[2] == highest]
                if len(best) != 1:
                    return []
                selected.extend(best[0][1])
        return list(dict.fromkeys(selected))

    def _verify_selected_dicom_stages(
        self, stages: dict[str, Path],
    ) -> tuple[bool, bool, bool]:
        prepared = self._matched_selected_dicom_derivatives(stages)
        if not prepared:
            return False, False, False
        scrubbed = []
        for path in prepared:
            relative = path.relative_to(stages["converted"])
            base = self._strip_nifti_suffix(path)
            found = next((p for p in (
                stages["scrubbed"] / relative.parent / f"{base}_scrubbed.nii.gz",
                stages["scrubbed"] / relative.parent / f"{base}_scrubbed.nii",
            ) if p.is_file() and p.stat().st_size > 0), None)
            if found is None:
                return True, False, False
            scrubbed.append(found)
        for path in scrubbed:
            relative = path.relative_to(stages["scrubbed"])
            base = self._strip_nifti_suffix(path)
            if not any(p.is_file() and p.stat().st_size > 0 for p in (
                stages["defaced"] / relative.parent / f"{base}_defaced.nii.gz",
                stages["defaced"] / relative.parent / f"{base}_defaced.nii",
            )):
                return True, True, False
        return True, True, True

    def _verify_prepare_outputs(
        self,
        stages: dict[str, Path],
    ) -> bool:
        expected = self._expected_prepared_nifti_paths(
            stages["converted"]
        )

        if expected is not None:
            return bool(expected) and all(
                path.is_file()
                for path in expected
            )

        return bool(
            self._all_nifti_files(stages["converted"])
        )

    def _verify_scrub_outputs(
        self,
        stages: dict[str, Path],
    ) -> bool:
        converted = self._all_nifti_files(
            stages["converted"]
        )
        if not converted:
            return False

        for input_path in converted:
            relative = input_path.relative_to(stages["converted"])
            base = self._strip_nifti_suffix(input_path)
            candidates = [
                stages["scrubbed"]
                / relative.parent
                / f"{base}_scrubbed.nii.gz",
                stages["scrubbed"]
                / relative.parent
                / f"{base}_scrubbed.nii",
            ]
            if not any(candidate.is_file() for candidate in candidates):
                return False

        return True

    def _verify_deface_outputs(
        self,
        stages: dict[str, Path],
    ) -> bool:
        scrubbed = self._all_nifti_files(
            stages["scrubbed"]
        )
        if not scrubbed:
            return False

        for input_path in scrubbed:
            relative = input_path.relative_to(stages["scrubbed"])
            base = self._strip_nifti_suffix(input_path)
            candidates = [
                stages["defaced"]
                / relative.parent
                / f"{base}_defaced.nii.gz",
                stages["defaced"]
                / relative.parent
                / f"{base}_defaced.nii",
            ]
            if not any(candidate.is_file() for candidate in candidates):
                return False

        return True

    def _verify_review_complete(self) -> bool:
        try:
            items, _ = self._imaging_review_items()
        except Exception:
            return False

        if not items:
            return False

        final_statuses = {
            "Accepted",
            "Accepted - External",
            "Rejected - Not Included",
            "On Hold - Needs Defaced Replacement",
        }

        return all(
            str(item.get("status", "Pending") or "Pending")
            in final_statuses
            for item in items
        )

    def _verify_bids_complete(self, config) -> bool:
        try:
            accepted = self.imaging_get_accepted_files().get("files", [])
        except Exception:
            return False

        if not accepted:
            return False

        index = self._index_existing_bids(
            config.imaging.bids_output_dir
        )

        try:
            state = self.imaging_bids_get_state()
        except Exception:
            return False

        records = state.get("records", [])
        output_dir = config.imaging.bids_output_dir
        if not output_dir.is_dir() or not any(
            _is_nifti(path) for path in output_dir.rglob("*") if path.is_file()
        ):
            return False
        return bool(records) and all(
            record.get("record_state") == "completed_recorded"
            and isinstance(record.get("existing_export"), dict)
            and Path(str(record["existing_export"].get("nifti_path", ""))).is_file()
            and _matching_json(Path(str(record["existing_export"]["nifti_path"]))) is not None
            for record in records
        )

    def _sync_imaging_stage_state_from_disk(
        self,
        config,
    ) -> dict[str, Any]:
        if self._process_running(self.imaging_process):
            return {"source": "running", "note": ""}

        stages = self._imaging_stage_paths(config)
        manifest = self._load_imaging_pipeline_state(
            stages["pipeline_state"]
        )
        current_signature = self._imaging_selection_signature()
        manifest_signature = str(
            manifest.get("selection_signature", "") or ""
        )

        same_context = (
            bool(manifest_signature)
            and manifest_signature == current_signature
            and str(manifest.get("derivatives_dir", ""))
            == str(config.imaging.derivatives_dir)
            and str(manifest.get("final_output_dir", ""))
            == str(config.imaging.bids_output_dir)
        )

        saved_stages = manifest.get("stages", {})
        if not isinstance(saved_stages, dict):
            saved_stages = {}

        def unresolved_state(stage: str) -> str:
            saved = str(saved_stages.get(stage, "not_started"))
            if saved in {"failed", "stopped"}:
                return saved
            return "not_started"

        restored_history = self._restore_imaging_completion_history(config, stages)
        if restored_history is not None:
            prepare_complete, scrub_complete, deface_complete = restored_history
            self.imaging_stage_state = {
                "prepare": "complete" if prepare_complete else "not_started",
                "scrub": "complete" if scrub_complete else "not_started",
                "deface": "complete" if deface_complete else "not_started",
                "review": "not_started",
                "metadata_bids": "not_started",
            }
            if deface_complete:
                self._refresh_imaging_review_stage()
            self._save_imaging_pipeline_state(
                config, note="Restored previously completed imaging stages for this selection."
            )
            return {"source": "selection_history",
                    "note": "Existing imaging outputs were matched to the saved source selection."}

        # A removal or reordering changes the combined selection signature.
        # Verify ONLY the currently selected sources against real derivatives,
        # without requiring the original group to remain selected. This is
        # especially important for subsets of previously processed groups.
        if not same_context and (
            bool(self.nifti_input_paths) != bool(self.dicom_input_paths)
        ):
            if self.nifti_input_paths:
                verified = self._verify_selected_nifti_stages(stages)
            else:
                verified = self._verify_selected_dicom_stages(stages)
            if any(verified):
                prepare_complete, scrub_complete, deface_complete = verified
                self.imaging_stage_state = {
                    "prepare": "complete" if prepare_complete else "not_started",
                    "scrub": "complete" if scrub_complete else "not_started",
                    "deface": "complete" if deface_complete else "not_started",
                    "review": "not_started",
                    "metadata_bids": "not_started",
                }
                if deface_complete:
                    self._refresh_imaging_review_stage()
                self._save_imaging_pipeline_state(
                    config, note="Verified remaining selected sources against existing derivatives."
                )
                return {
                    "source": "selected_derivatives",
                    "note": "Step 3 checked only the currently selected files and folders.",
                }

        if same_context:
            if not self.dicom_input_paths and self.nifti_input_paths:
                prepare_complete, scrub_complete, deface_complete = (
                    self._verify_selected_nifti_stages(stages)
                )
            elif self.dicom_input_paths and not self.nifti_input_paths:
                prepare_complete, scrub_complete, deface_complete = (
                    self._verify_selected_dicom_stages(stages)
                )
                # A successfully completed conversion in this exact
                # selection is authoritative when output files exist.
                # Folder-layout heuristics must not reset 3A to unstarted.
                if (
                    not prepare_complete
                    and saved_stages.get("prepare") == "complete"
                    and bool(self._all_nifti_files(stages["converted"]))
                ):
                    prepare_complete = True
                if prepare_complete and saved_stages.get("scrub") == "complete":
                    scrub_complete = (
                        scrub_complete or self._verify_scrub_outputs(stages)
                    )
                if scrub_complete and saved_stages.get("deface") == "complete":
                    deface_complete = (
                        deface_complete or self._verify_deface_outputs(stages)
                    )
            else:
                prepare_complete = (
                    saved_stages.get("prepare") == "complete"
                    and self._verify_prepare_outputs(stages)
                )
                scrub_complete = (
                    prepare_complete and saved_stages.get("scrub") == "complete"
                    and self._verify_scrub_outputs(stages)
                )
                deface_complete = (
                    scrub_complete and saved_stages.get("deface") == "complete"
                    and self._verify_deface_outputs(stages)
                )
            review_complete = (
                deface_complete
                and saved_stages.get("review") == "complete"
                and self._verify_review_complete()
            )
            bids_complete = (
                review_complete
                and saved_stages.get("metadata_bids") == "complete"
                and self._verify_bids_complete(config)
            )

            self.imaging_stage_state = {
                "prepare": (
                    "complete"
                    if prepare_complete
                    else unresolved_state("prepare")
                ),
                "scrub": (
                    "complete"
                    if scrub_complete
                    else unresolved_state("scrub")
                ),
                "deface": (
                    "complete"
                    if deface_complete
                    else unresolved_state("deface")
                ),
                "review": (
                    "complete"
                    if review_complete
                    else unresolved_state("review")
                ),
                "metadata_bids": (
                    "complete"
                    if bids_complete
                    else unresolved_state("metadata_bids")
                ),
            }

            if (
                deface_complete
                and not review_complete
                and self.imaging_stage_state["review"] == "not_started"
            ):
                try:
                    items, _ = self._imaging_review_items()
                except Exception:
                    items = []

                if items and any(
                    str(item.get("status", "Pending") or "Pending")
                    != "Pending"
                    for item in items
                ):
                    self.imaging_stage_state["review"] = "running"

            if (
                review_complete
                and not bids_complete
                and str(saved_stages.get("metadata_bids", "")) == "running"
            ):
                self.imaging_stage_state["metadata_bids"] = "running"

            if prepare_complete:
                try:
                    self._record_imaging_completion_history(config)
                except (OSError, ValueError):
                    pass
            self._save_imaging_pipeline_state(
                config,
                note=(
                    "Restored this imaging selection and verified its existing "
                    "derivative outputs from disk."
                ),
            )
            return {
                "source": "manifest",
                "note": (
                    "Existing derivative outputs were re-verified for the "
                    "current imaging selection."
                ),
            }

        # Restore completed NIfTI processing stages from matching files even
        # when the last run manifest belongs to another selection.
        try:
            prepare_complete, scrub_complete, deface_complete = (
                self._verify_selected_nifti_stages(stages)
            )
        except (OSError, ValueError):
            prepare_complete = scrub_complete = deface_complete = False

        if not prepare_complete and self.dicom_input_paths and not self.nifti_input_paths:
            try:
                prepare_complete, scrub_complete, deface_complete = (
                    self._verify_selected_dicom_stages(stages)
                )
            except (OSError, ValueError):
                prepare_complete = scrub_complete = deface_complete = False

        if prepare_complete:
            review_complete = deface_complete and self._verify_review_complete()
            self.imaging_stage_state = {
                "prepare": "complete",
                "scrub": "complete" if scrub_complete else "not_started",
                "deface": "complete" if deface_complete else "not_started",
                "review": "complete" if review_complete else "not_started",
                "metadata_bids": "not_started",
            }
            if deface_complete and not review_complete:
                self._refresh_imaging_review_stage()
            note = (
                "Verified selected NIfTI source copies against derivative files; "
                "restored completed processing stages from matching outputs."
            )
            try:
                self._record_imaging_completion_history(config)
            except (OSError, ValueError):
                pass
            self._save_imaging_pipeline_state(config, note=note)
            return {"source": "verified_outputs", "note": note}

        self.imaging_stage_state = {
            "prepare": "not_started",
            "scrub": "not_started",
            "deface": "not_started",
            "review": "not_started",
            "metadata_bids": "not_started",
        }

        # Never adopt files from an earlier cycle merely because the same
        # derivatives directory is reused. The previous manifest may belong
        # to another input set; keep its files but start this selection fresh.
        if manifest:
            note = (
                "Imaging sources or output folders changed. Step completion "
                "was reset for this selection; existing files were preserved."
            )
            self._save_imaging_pipeline_state(config, note=note)
            return {"source": "selection_changed", "note": note}

        note = "No matching imaging run manifest was found. Process this selection from Step 1."
        self._save_imaging_pipeline_state(config, note=note)
        return {"source": "new", "note": note}

    @staticmethod
    def _snapshot_imaging_files(
        roots: Iterable[Path],
    ) -> dict[str, set[str]]:
        snapshot: dict[str, set[str]] = {}

        for root in roots:
            root = Path(root)
            files: set[str] = set()

            if root.exists():
                for path in root.rglob("*"):
                    if path.is_file():
                        files.add(_resolve_text(path))

            snapshot[_resolve_text(root)] = files

        return snapshot

    def _begin_imaging_stage(
        self,
        operation: str,
        cleanup_roots: Iterable[Path],
    ) -> None:
        reset_after = {
            "prepare": ("scrub", "deface", "review", "metadata_bids"),
            "scrub": ("deface", "review", "metadata_bids"),
            "deface": ("review", "metadata_bids"),
            "review": ("metadata_bids",),
            "metadata_bids": (),
        }

        for later in reset_after.get(operation, ()):
            self.imaging_stage_state[later] = "not_started"

        self.imaging_stage_state[operation] = "running"
        self.imaging_active_operation = operation
        self._imaging_cleanup_context = {
            "operation": operation,
            "roots": [
                _resolve_text(Path(root))
                for root in cleanup_roots
            ],
            "before": self._snapshot_imaging_files(
                Path(root)
                for root in cleanup_roots
            ),
        }

        try:
            self._save_imaging_pipeline_state(load_imaging_config())
        except Exception:
            pass

    def _finish_imaging_stage(
        self,
        operation: str,
        return_code: int = 0,
    ) -> None:
        if self.imaging_stage_state.get(operation) == "stopped":
            return

        self.imaging_stage_state[operation] = (
            "complete"
            if return_code == 0
            else "failed"
        )

        if self.imaging_active_operation == operation:
            self.imaging_active_operation = ""

        try:
            config = load_imaging_config()
            if return_code == 0 and operation in {"prepare", "scrub", "deface"}:
                self._record_imaging_completion_history(config)
            self._save_imaging_pipeline_state(config)
        except Exception:
            pass

        if (
            self._imaging_cleanup_context
            and self._imaging_cleanup_context.get("operation") == operation
        ):
            self._imaging_cleanup_context = None

    def _fail_imaging_stage(
        self,
        operation: str,
    ) -> None:
        self.imaging_stage_state[operation] = "failed"

        if self.imaging_active_operation == operation:
            self.imaging_active_operation = ""

        if (
            self._imaging_cleanup_context
            and self._imaging_cleanup_context.get("operation") == operation
        ):
            self._imaging_cleanup_context = None

        try:
            self._save_imaging_pipeline_state(load_imaging_config())
        except Exception:
            pass

    def _cleanup_stopped_imaging_stage(
        self,
        operation: str,
    ) -> int:
        context = self._imaging_cleanup_context

        if not context or context.get("operation") != operation:
            return 0

        before = context.get("before", {})
        removed = 0

        for root_text in context.get("roots", []):
            root = Path(root_text)
            previous = set(before.get(root_text, set()))

            if not root.exists():
                continue

            current_files = [
                path
                for path in root.rglob("*")
                if path.is_file()
            ]

            for path in current_files:
                if _resolve_text(path) in previous:
                    continue

                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass

            directories = sorted(
                (
                    path
                    for path in root.rglob("*")
                    if path.is_dir()
                ),
                key=lambda path: len(path.parts),
                reverse=True,
            )

            for directory in directories:
                try:
                    directory.rmdir()
                except OSError:
                    pass

        self._imaging_cleanup_context = None
        return removed

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
            metadata_path = path.with_name(
                f"{self._strip_nifti_suffix(path)}_cocanot.json"
            )
            metadata: dict[str, Any] = {}
            cocanot_metadata: dict[str, Any] = {}

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

            if metadata_path.is_file():
                try:
                    loaded_cocanot = json.loads(
                        metadata_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    loaded_cocanot = {}

                if isinstance(loaded_cocanot, dict):
                    nested = loaded_cocanot.get(
                        "CoCANoTMetadata"
                    )
                    if isinstance(nested, dict):
                        cocanot_metadata = dict(
                            nested
                        )

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
                    "cocanot_metadata": cocanot_metadata,
                    "cocanot_metadata_path": (
                        str(metadata_path.resolve())
                        if metadata_path.is_file()
                        else ""
                    ),
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

    def _imaging_local_record_for_accepted_source(
        self,
        image: dict[str, Any],
        nifti_path: Path,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """
        Find the local Imaging record and durable PatientDataLinkStore entry
        associated with an accepted Step 4 image.

        A successful Imaging export writes a patient_data_links row keyed by
        site + patient + Imaging + Image ID. That link is the authoritative
        record of the derivative and final BIDS files, so Step 5 should use it
        instead of trying to rediscover completion from hashes alone.
        """
        site_id = self.get_site_id()
        source_key = str(
            image.get("source_key", "")
            or ""
        ).strip()
        source_label = str(
            image.get("file_name", "")
            or ""
        ).strip()

        try:
            accepted_path = nifti_path.expanduser().resolve()
        except OSError:
            accepted_path = nifti_path.expanduser()

        data_links = PatientDataLinkStore()

        try:
            patient_ids = self.repository.patient_ids_for_site(
                site_id
            )
        except Exception:
            return None, {}

        fallback_record = None
        fallback_link: dict[str, Any] = {}

        for patient_id in patient_ids:
            try:
                summary = self.repository.patient_summary(
                    site_id,
                    patient_id,
                )
            except Exception:
                continue

            imaging_records = (
                summary.get("Imaging", [])
                if isinstance(summary, dict)
                else []
            )

            for record in imaging_records:
                if not isinstance(record, dict):
                    continue

                metadata = record.get(
                    "metadata",
                    {},
                )
                if not isinstance(metadata, dict):
                    metadata = {}

                record_id = str(
                    record.get(
                        "record_id",
                        "",
                    )
                    or metadata.get(
                        "Image ID",
                        "",
                    )
                    or ""
                ).strip()

                link = (
                    data_links.get_link(
                        site_id,
                        patient_id,
                        "Imaging",
                        record_id,
                    )
                    if record_id
                    else {}
                )
                if not isinstance(link, dict):
                    link = {}

                linked_paths = (
                    data_links.paths_from_payload(
                        link
                    )
                    if link
                    else {
                        "derivative_paths": [],
                        "final_paths": [],
                        "derivatives_roots": [],
                        "final_output_roots": [],
                    }
                )

                for linked_path_text in linked_paths.get(
                    "derivative_paths",
                    [],
                ):
                    try:
                        linked_path = Path(
                            linked_path_text
                        ).expanduser().resolve()
                    except OSError:
                        linked_path = Path(
                            linked_path_text
                        ).expanduser()

                    if linked_path == accepted_path:
                        return record, link

                context = record.get(
                    "context",
                    {},
                )
                if not isinstance(context, dict):
                    context = {}

                stored_source_key = str(
                    context.get(
                        "source_key",
                        "",
                    )
                    or ""
                ).strip()

                stored_nifti = str(
                    context.get(
                        "nifti_path",
                        "",
                    )
                    or ""
                ).strip()

                stored_source_label = str(
                    context.get(
                        "source_label",
                        "",
                    )
                    or ""
                ).strip()

                context_matches = False

                if (
                    source_key
                    and stored_source_key
                    and stored_source_key == source_key
                ):
                    context_matches = True

                if not context_matches and stored_nifti:
                    try:
                        stored_path = Path(
                            stored_nifti
                        ).expanduser().resolve()
                    except OSError:
                        stored_path = Path(
                            stored_nifti
                        ).expanduser()

                    if stored_path == accepted_path:
                        context_matches = True

                if (
                    not context_matches
                    and source_label
                    and stored_source_label
                    and stored_source_label == source_label
                ):
                    context_matches = True

                if context_matches:
                    if link:
                        return record, link

                    fallback_record = record
                    fallback_link = link

        return fallback_record, fallback_link

    def _existing_bids_export_from_data_link(
        self,
        link: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """
        Build an existing-export payload from PatientDataLinkStore.

        Only an existing NIfTI in final_paths counts as a completed BIDS export.
        """
        if not isinstance(link, dict) or not link:
            return None

        data_links = PatientDataLinkStore()
        paths = data_links.paths_from_payload(
            link
        )

        candidates = list(
            paths.get(
                "final_paths",
                [],
            )
        )

        for value in candidates:
            path = Path(
                str(value)
            ).expanduser()

            if not _is_nifti(path):
                continue

            try:
                resolved = path.resolve()
            except OSError:
                resolved = path

            json_path = _matching_json(
                resolved
            )
            metadata_path = resolved.with_name(
                f"{self._strip_nifti_suffix(resolved)}_cocanot.json"
            )

            metadata: dict[str, Any] = {}
            cocanot_metadata: dict[str, Any] = {}

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

                if isinstance(
                    loaded,
                    dict,
                ):
                    metadata = loaded

            if metadata_path.is_file():
                try:
                    loaded_cocanot = json.loads(
                        metadata_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    loaded_cocanot = {}

                if isinstance(
                    loaded_cocanot,
                    dict,
                ):
                    nested = loaded_cocanot.get(
                        "CoCANoTMetadata"
                    )
                    if isinstance(
                        nested,
                        dict,
                    ):
                        cocanot_metadata = dict(
                            nested
                        )

            # Consolidated exports store CoCANoT metadata in the ordinary
            # imaging JSON. Older exports may still have a separate sidecar.
            if not cocanot_metadata and isinstance(metadata.get("CoCANoTMetadata"), dict):
                cocanot_metadata = dict(metadata["CoCANoTMetadata"])

            return {
                "nifti_path": str(
                    resolved
                ),
                "json_path": (
                    str(
                        json_path.resolve()
                    )
                    if json_path is not None
                    else ""
                ),
                "metadata": metadata,
                "cocanot_metadata": cocanot_metadata,
                "cocanot_metadata_path": (
                    str(
                        metadata_path.resolve()
                    )
                    if metadata_path.is_file()
                    else str(json_path.resolve()) if json_path is not None else ""
                ),
                "sha256": "",
            }

        return None

    def _find_bids_export_for_local_record(
        self,
        record: dict[str, Any] | None,
        current_output_dir: Path,
        link: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Resolve an exported BIDS NIfTI from every durable location we know.

        This intentionally does not depend on the Step 5 draft. Successful
        exports can outlive drafts, configuration changes, and regenerated
        accepted derivatives.
        """
        if not isinstance(record, dict):
            return None

        metadata = record.get(
            "metadata",
            {},
        )
        if not isinstance(metadata, dict):
            metadata = {}

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
            or record.get(
                "record_id",
                "",
            )
            or ""
        ).strip()

        if not patient_id or not image_id:
            return None

        # First use any direct final paths recorded in PatientDataLinkStore.
        direct = self._existing_bids_export_from_data_link(
            link
        )
        if direct is not None:
            return direct

        context = record.get(
            "context",
            {},
        )
        if not isinstance(context, dict):
            context = {}

        direct_candidates: list[str] = []

        for field in (
            "bids_data_path",
            "nifti_bids_path",
            "output_path",
        ):
            value = str(
                context.get(
                    field,
                    "",
                )
                or ""
            ).strip()
            if value:
                direct_candidates.append(
                    value
                )

        for value in (
            context.get(
                "final_paths",
                [],
            )
            or []
        ):
            value_text = str(
                value or ""
            ).strip()
            if value_text:
                direct_candidates.append(
                    value_text
                )

        for value in direct_candidates:
            path = Path(
                value
            ).expanduser()

            if not _is_nifti(path):
                continue

            try:
                resolved = path.resolve()
            except OSError:
                resolved = path

            json_path = _matching_json(
                resolved
            )
            metadata_path = resolved.with_name(
                f"{self._strip_nifti_suffix(resolved)}_cocanot.json"
            )

            sidecar: dict[str, Any] = {}
            stored_cocanot: dict[str, Any] = {}

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
                    sidecar = loaded

            if metadata_path.is_file():
                try:
                    loaded_metadata = json.loads(
                        metadata_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    loaded_metadata = {}

                if isinstance(
                    loaded_metadata,
                    dict,
                ):
                    nested = loaded_metadata.get(
                        "CoCANoTMetadata"
                    )
                    if isinstance(
                        nested,
                        dict,
                    ):
                        stored_cocanot = dict(
                            nested
                        )

            return {
                "nifti_path": str(
                    resolved
                ),
                "json_path": (
                    str(
                        json_path.resolve()
                    )
                    if json_path is not None
                    else ""
                ),
                "metadata": sidecar,
                "cocanot_metadata": stored_cocanot,
                "cocanot_metadata_path": (
                    str(
                        metadata_path.resolve()
                    )
                    if metadata_path.is_file()
                    else ""
                ),
                "sha256": "",
            }

        # Then scan every output root persisted by either the record context or
        # PatientDataLinkStore and match by CoCANoT Patient ID + Image ID.
        roots: list[Path] = [
            current_output_dir
        ]

        for field in (
            "bids_output_dir",
            "final_output_root",
        ):
            value = str(
                context.get(
                    field,
                    "",
                )
                or ""
            ).strip()
            if value:
                roots.append(
                    Path(value).expanduser()
                )

        if isinstance(link, dict) and link:
            data_links = PatientDataLinkStore()
            linked = data_links.paths_from_payload(
                link
            )
            roots.extend(
                Path(value).expanduser()
                for value in linked.get(
                    "final_output_roots",
                    [],
                )
                if str(value).strip()
            )

        seen: set[str] = set()

        for root in roots:
            try:
                resolved_root = root.resolve()
            except OSError:
                resolved_root = root

            root_key = str(
                resolved_root
            )
            if root_key in seen:
                continue
            seen.add(
                root_key
            )

            if not resolved_root.exists():
                continue

            index = self._index_existing_bids(
                resolved_root
            )
            match = (
                self._existing_bids_export_by_identity(
                    index,
                    patient_id,
                    image_id,
                )
            )
            if match is not None:
                return match

        return None

    def _existing_bids_export_from_nifti_path(
        self,
        nifti_path: Path,
    ) -> dict[str, Any] | None:
        """
        Build the Step 5 existing-export payload from a NIfTI path that has
        already been resolved by the same logic used by Patient Data Review.
        """
        path = Path(
            nifti_path
        ).expanduser()

        if not _is_nifti(path):
            return None

        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        json_path = _matching_json(
            resolved
        )
        metadata_path = resolved.with_name(
            f"{self._strip_nifti_suffix(resolved)}_cocanot.json"
        )

        sidecar: dict[str, Any] = {}
        cocanot_metadata: dict[str, Any] = {}

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

            if isinstance(
                loaded,
                dict,
            ):
                sidecar = loaded

        if metadata_path.is_file():
            try:
                loaded_cocanot = json.loads(
                    metadata_path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                OSError,
                json.JSONDecodeError,
            ):
                loaded_cocanot = {}

            if isinstance(
                loaded_cocanot,
                dict,
            ):
                nested = loaded_cocanot.get(
                    "CoCANoTMetadata"
                )
                if isinstance(
                    nested,
                    dict,
                ):
                    cocanot_metadata = dict(
                        nested
                    )

        return {
            "nifti_path": str(
                resolved
            ),
            "json_path": (
                str(
                    json_path.resolve()
                )
                if json_path is not None
                else ""
            ),
            "metadata": sidecar,
            "cocanot_metadata": cocanot_metadata,
            "cocanot_metadata_path": (
                str(
                    metadata_path.resolve()
                )
                if metadata_path.is_file()
                else ""
            ),
            "sha256": "",
        }

    def _existing_bids_export_from_record_context(
        self,
        record: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """
        Recover an existing BIDS export directly from the saved Imaging context.

        nifti_to_bids.py stores bids_data_path and final_paths after writing the
        export. This remains authoritative even if the currently configured BIDS
        output directory later changes.
        """
        if not isinstance(record, dict):
            return None

        context = record.get(
            "context",
            {},
        )
        if not isinstance(context, dict):
            return None

        candidates: list[str] = []

        bids_data_path = str(
            context.get(
                "bids_data_path",
                "",
            )
            or ""
        ).strip()
        if bids_data_path:
            candidates.append(
                bids_data_path
            )

        for value in (
            context.get(
                "final_paths",
                [],
            )
            or []
        ):
            value_text = str(
                value or ""
            ).strip()
            if value_text:
                candidates.append(
                    value_text
                )

        for value in candidates:
            path = Path(
                value
            ).expanduser()

            if not _is_nifti(path):
                continue

            try:
                resolved = path.resolve()
            except OSError:
                resolved = path

            json_path = _matching_json(
                resolved
            )
            metadata_path = resolved.with_name(
                f"{self._strip_nifti_suffix(resolved)}_cocanot.json"
            )

            metadata: dict[str, Any] = {}
            cocanot_metadata: dict[str, Any] = {}

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

                if isinstance(
                    loaded,
                    dict,
                ):
                    metadata = loaded

            if metadata_path.is_file():
                try:
                    loaded_cocanot = json.loads(
                        metadata_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    loaded_cocanot = {}

                if isinstance(
                    loaded_cocanot,
                    dict,
                ):
                    nested = loaded_cocanot.get(
                        "CoCANoTMetadata"
                    )
                    if isinstance(
                        nested,
                        dict,
                    ):
                        cocanot_metadata = dict(
                            nested
                        )

            return {
                "nifti_path": str(
                    resolved
                ),
                "json_path": (
                    str(
                        json_path.resolve()
                    )
                    if json_path is not None
                    else ""
                ),
                "metadata": metadata,
                "cocanot_metadata": cocanot_metadata,
                "cocanot_metadata_path": (
                    str(
                        metadata_path.resolve()
                    )
                    if metadata_path.is_file()
                    else ""
                ),
                "sha256": "",
            }

        return None

    @staticmethod
    def _existing_bids_export_by_identity(
        index: dict[int, list[dict[str, Any]]],
        patient_id: str,
        image_id: str,
    ) -> dict[str, Any] | None:
        """
        Find a previously exported Imaging file by its stable CoCANoT identity.

        SHA-256 remains the preferred match because it proves the exported NIfTI
        is byte-for-byte identical to the accepted file. This identity fallback
        is used when the accepted derivative has since been regenerated but the
        BIDS output and its CoCANoT sidecar still identify the same patient/image.
        """
        patient_id = str(patient_id or "").strip()
        image_id = str(image_id or "").strip()

        if not patient_id or not image_id:
            return None

        for candidates in index.values():
            for candidate in candidates:
                stored_cocanot = candidate.get(
                    "cocanot_metadata",
                    {},
                )
                if not isinstance(stored_cocanot, dict):
                    stored_cocanot = {}

                sidecar = candidate.get(
                    "metadata",
                    {},
                )
                if not isinstance(sidecar, dict):
                    sidecar = {}

                candidate_patient = str(
                    stored_cocanot.get(
                        "CoCANoT Patient ID",
                        "",
                    )
                    or sidecar.get(
                        "CoCANoTPatientID",
                        "",
                    )
                    or ""
                ).strip()

                candidate_image = str(
                    stored_cocanot.get(
                        "Image ID",
                        "",
                    )
                    or sidecar.get(
                        "ImageID",
                        "",
                    )
                    or ""
                ).strip()

                if (
                    candidate_patient == patient_id
                    and candidate_image == image_id
                ):
                    return dict(candidate)

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
        return CoCANoTAPI._rule_payload(
            rule
        )

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
            _active_dictionary_path()
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

    @staticmethod
    def _load_imaging_bids_drafts(path: Path) -> dict[str, dict[str, Any]]:
        if not path.is_file():
            return {}

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _save_imaging_bids_drafts(
        path: Path,
        payload: dict[str, dict[str, Any]],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def imaging_bids_save_draft(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        source_key = str(payload.get("source_key", "") or "").strip()
        if not source_key:
            raise ValueError("Imaging source key is required.")

        config = load_imaging_config()
        state_path = self._imaging_stage_paths(config)["bids_drafts"]
        drafts = self._load_imaging_bids_drafts(state_path)
        drafts[source_key] = {
            "include": bool(payload.get("include", False)),
            "project": str(payload.get("project", "") or ""),
            "project_description": str(
                payload.get("project_description", "") or ""
            ),
            "session_id": str(payload.get("session_id", "") or ""),
            "cocanot_metadata": dict(
                payload.get("cocanot_metadata", {}) or {}
            ),
            "sidecar_metadata": dict(payload.get("sidecar_metadata", {}) or {}),
        }
        self._save_imaging_bids_drafts(state_path, drafts)
        return {"ok": True}

    def _purge_stale_deleted_imaging_step5_item(
        self,
        source_key: str,
    ) -> None:
        """
        Remove stale Step 4/Step 5 state for an Imaging item whose patient
        record and BIDS export have already been deleted.

        This is primarily a recovery path for records deleted before the newer
        delete cleanup logic was installed.
        """
        source_key = str(
            source_key or ""
        ).strip()

        if not source_key:
            return

        config = load_imaging_config()
        stages = self._imaging_stage_paths(
            config
        )

        review_state_path = stages[
            "review_state"
        ]
        review_state = self._load_review_state(
            review_state_path
        )

        if source_key in review_state:
            review_state.pop(
                source_key,
                None,
            )
            self._save_review_state(
                review_state_path,
                review_state,
            )

        draft_path = stages[
            "bids_drafts"
        ]
        drafts = self._load_imaging_bids_drafts(
            draft_path
        )

        if source_key in drafts:
            drafts.pop(
                source_key,
                None,
            )
            self._save_imaging_bids_drafts(
                draft_path,
                drafts,
            )

        try:
            self._refresh_imaging_review_stage()
        except Exception:
            pass

    def imaging_bids_get_state(self) -> dict[str, Any]:
        _dictionary, rules, _validator = (
            self._imaging_dictionary_context()
        )

        try:
            config = load_imaging_config()
        except PipelineConfigError:
            return {
                "site_id": self.get_site_id(),
                "records": [],
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
                "held_count": 0,
                "bids_output_dir": "",
                "local_database": {
                    "site_id": self.get_site_id(),
                    "connected": bool(
                        self.get_site_id()
                    ),
                },
            }

        accepted_payload = self.imaging_get_accepted_files()
        accepted = accepted_payload["files"]

        if not accepted:
            # Never imply "all rejected" without checking the review state.
            try:
                review_items, _ = self._imaging_review_items()
                review_statuses = [str(item.get("status", "Pending")) for item in review_items]
            except Exception:
                review_statuses = []
            missing_outputs = sum(
                1 for status in review_statuses
                if status in {"Accepted", "Accepted - External"}
            )
            if missing_outputs:
                accepted_warning = (
                    f"{missing_outputs} image(s) were accepted in Step 4, but their accepted "
                    "NIfTI files could not be found in the configured derivatives folder. "
                    "Check your Step 2 folder and the imaging processing log."
                )
            elif not review_statuses:
                accepted_warning = (
                    "No Step 4 review items were found in the configured derivatives folder. "
                    "Check that Step 2 still points to the folder used for this run."
                )
            else:
                accepted_warning = (
                    "No images are currently accepted for export. "
                    "Return to Step 4 if you intended to include an image."
                )
            return {
                "accepted_warning": accepted_warning,
                "site_id": self.get_site_id(),
                "records": [],
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
                    config.imaging.bids_output_dir
                ),
                "local_database": {
                    "site_id": self.get_site_id(),
                    "connected": bool(
                        self.get_site_id()
                    ),
                },
            }

        output_dir = config.imaging.bids_output_dir
        drafts = self._load_imaging_bids_drafts(
            self._imaging_stage_paths(config)["bids_drafts"]
        )

        existing_bids_by_size = self._index_existing_bids(
            output_dir
        )

        records: list[dict[str, Any]] = []

        for index, image in enumerate(
            accepted,
            start=1,
        ):
            source_key = str(
                image.get("source_key", "")
                or ""
            ).strip()

            nifti_path = Path(
                str(
                    image["nifti_path"]
                )
            ).expanduser().resolve()

            draft = drafts.get(
                source_key,
                {},
            )
            if not isinstance(draft, dict):
                draft = {}

            # Prefer the scrubbed sidecar (never the raw DICOM-derived JSON).
            # A NIfTI-only upload receives a generated JSON in the scrub step.
            sidecar_candidates = [
                Path(str(value)) for value in self._imaging_derivative_paths_for_export(
                    {"nifti_path": str(nifti_path), "source_key": source_key}, config
                ) if "_scrubbed" in Path(str(value)).name.lower()
                and "_defaced" not in Path(str(value)).name.lower()
            ]
            sidecar_candidates.append(nifti_path)
            source_sidecar = None
            for source_candidate in sidecar_candidates:
                candidate_json = _matching_json(source_candidate)
                if candidate_json is not None:
                    source_sidecar = candidate_json
                    break
            sidecar_metadata = {}
            if source_sidecar is not None:
                try:
                    loaded_sidecar = json.loads(source_sidecar.read_text(encoding="utf-8"))
                    if isinstance(loaded_sidecar, dict):
                        sidecar_metadata = loaded_sidecar
                except (OSError, json.JSONDecodeError):
                    pass
            if "sidecar_metadata" in draft:
                sidecar_metadata = dict(draft.get("sidecar_metadata") or {})

            draft_metadata = draft.get(
                "cocanot_metadata",
                {},
            )
            if not isinstance(draft_metadata, dict):
                draft_metadata = {}

            draft_patient_id = str(
                draft_metadata.get(
                    "CoCANoT Patient ID",
                    "",
                )
                or ""
            ).strip()
            draft_image_id = str(
                draft_metadata.get(
                    "Image ID",
                    "",
                )
                or ""
            ).strip()

            (
                local_source_record,
                local_source_link,
            ) = self._imaging_local_record_for_accepted_source(
                image,
                nifti_path,
            )

            # IMPORTANT: source context can be overwritten when the same
            # Patient ID + Image ID is used again. Step 5 must therefore also
            # resolve the durable record/link directly from the stable metadata
            # identity, not only from source_key/source_label/nifti_path.
            if (
                draft_patient_id
                and draft_image_id
            ):
                identity_record = self.repository.get_record(
                    self.get_site_id(),
                    "Imaging",
                    draft_image_id,
                    patient_id=draft_patient_id,
                )

                identity_link = PatientDataLinkStore().get_link(
                    self.get_site_id(),
                    draft_patient_id,
                    "Imaging",
                    draft_image_id,
                )

                if (
                    local_source_record is None
                    and identity_record is not None
                ):
                    local_source_record = identity_record

                if (
                    not local_source_link
                    and isinstance(identity_link, dict)
                    and identity_link
                ):
                    local_source_link = identity_link

            # Preferred completion signal: a durable PatientDataLinkStore
            # entry for this Patient ID + Image ID whose final NIfTI still
            # exists. This is authoritative even if the accepted derivative or
            # source context changed after export.
            existing_export = None

            if (
                local_source_record is not None
                and local_source_link
            ):
                existing_export = (
                    self._existing_bids_export_from_data_link(
                        local_source_link
                    )
                )

            # Fallback: exact file identity against the currently configured
            # BIDS output tree.
            if existing_export is None:
                existing_export = self._existing_bids_export(
                    nifti_path,
                    existing_bids_by_size,
                )

            # Recovery path 1: once we know the local Imaging record, resolve
            # its export from all persisted paths/output roots. This works for
            # current exports as well as older records created before the latest
            # Step 5 draft/link behavior.
            if (
                existing_export is None
                and local_source_record is not None
            ):
                existing_export = (
                    self._find_bids_export_for_local_record(
                        local_source_record,
                        output_dir,
                        local_source_link,
                    )
                )

            # Recovery path 2: a successful converter run writes a durable
            # PatientDataLinkStore entry. Keep this as a direct fallback.
            if existing_export is None:
                existing_export = (
                    self._existing_bids_export_from_data_link(
                        local_source_link
                    )
                )

            # Recovery path 3: recover patient/Image identity from the saved
            # Imaging record linked to this accepted source.
            if (
                existing_export is None
                and local_source_record is not None
            ):
                local_source_metadata = (
                    local_source_record.get(
                        "metadata",
                        {},
                    )
                )
                if not isinstance(
                    local_source_metadata,
                    dict,
                ):
                    local_source_metadata = {}

                existing_export = (
                    self._existing_bids_export_by_identity(
                        existing_bids_by_size,
                        local_source_metadata.get(
                            "CoCANoT Patient ID",
                            "",
                        ),
                        local_source_metadata.get(
                            "Image ID",
                            "",
                        ),
                    )
                )

                # The configured output directory can change after export. The
                # converter stores the actual BIDS path in the patient record,
                # so use that saved path as a second authoritative recovery.
                if existing_export is None:
                    existing_export = (
                        self._existing_bids_export_from_record_context(
                            local_source_record
                        )
                    )

            # Recovery path 4: while a draft still exists, use its stable
            # patient/Image identity as another way to locate the BIDS output.
            if existing_export is None:
                existing_export = (
                    self._existing_bids_export_by_identity(
                        existing_bids_by_size,
                        draft_metadata.get(
                            "CoCANoT Patient ID",
                            "",
                        ),
                        draft_metadata.get(
                            "Image ID",
                            "",
                        ),
                    )
                )

            # Recovery path 5: Patient Data Review already has a proven,
            # independent resolver for Imaging files. If that resolver can open
            # the NIfTI for this exact local Imaging record, Step 5 must treat
            # that same file as an existing BIDS export instead of claiming the
            # output is missing.
            if (
                existing_export is None
                and local_source_record is not None
            ):
                try:
                    linked_nifti = (
                        self._metadata_find_imaging_file(
                            local_source_record
                        )
                    )
                except (
                    FileNotFoundError,
                    OSError,
                    ValueError,
                ):
                    linked_nifti = None

                if linked_nifti is not None:
                    existing_export = (
                        self._existing_bids_export_from_nifti_path(
                            linked_nifti
                        )
                    )

            project = ""
            project_description = ""
            session_id = ""
            participant_id = ""
            include = False
            record_state = "step5_pending"
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
                stored_cocanot = existing_export.get(
                    "cocanot_metadata",
                    {},
                )
                if not isinstance(stored_cocanot, dict):
                    stored_cocanot = {}

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

                if stored_cocanot:
                    export_metadata = dict(
                        stored_cocanot
                    )
                else:
                    export_metadata = (
                        self._cocanot_metadata_from_existing_bids(
                            existing_metadata,
                            rules,
                        )
                    )

                patient_id = str(
                    export_metadata.get(
                        "CoCANoT Patient ID",
                        "",
                    )
                    or ""
                ).strip()
                image_id = str(
                    export_metadata.get(
                        "Image ID",
                        "",
                    )
                    or ""
                ).strip()

                local_record = None
                if patient_id and image_id:
                    local_record = self.repository.get_record(
                        self.get_site_id(),
                        "Imaging",
                        image_id,
                        patient_id=patient_id,
                    )

                if (
                    local_record is None
                    and local_source_record is not None
                ):
                    local_record = local_source_record

                    linked_metadata = local_source_record.get(
                        "metadata",
                        {},
                    )
                    if isinstance(
                        linked_metadata,
                        dict,
                    ):
                        if not patient_id:
                            patient_id = str(
                                linked_metadata.get(
                                    "CoCANoT Patient ID",
                                    "",
                                )
                                or ""
                            ).strip()

                        if not image_id:
                            image_id = str(
                                linked_metadata.get(
                                    "Image ID",
                                    "",
                                )
                                or ""
                            ).strip()

                participant_id = patient_id

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

                if local_record is not None:
                    record_state = "completed_recorded"
                    local_metadata = local_record.get(
                        "metadata",
                        {},
                    )
                    if isinstance(local_metadata, dict):
                        cocanot_metadata = dict(
                            local_metadata
                        )

                    local_context = local_record.get(
                        "context",
                        {},
                    )
                    if isinstance(local_context, dict):
                        project = str(
                            local_context.get(
                                "project",
                                project,
                            )
                            or project
                        )
                        project_description = str(
                            local_context.get(
                                "project_description",
                                project_description,
                            )
                            or project_description
                        )
                        session_id = str(
                            local_context.get(
                                "session_id",
                                session_id,
                            )
                            or session_id
                        )
                else:
                    record_state = "output_record_deleted"
                    cocanot_metadata = dict(
                        export_metadata
                    )
                    participant_id = patient_id

            else:
                # No BIDS output was found. Restore the draft first.
                include = bool(
                    draft.get(
                        "include",
                        False,
                    )
                )
                project = str(
                    draft.get(
                        "project",
                        "",
                    )
                    or ""
                )
                project_description = str(
                    draft.get(
                        "project_description",
                        "",
                    )
                    or ""
                )
                session_id = str(
                    draft.get(
                        "session_id",
                        "",
                    )
                    or ""
                )
                cocanot_metadata = dict(
                    draft_metadata
                )

                patient_id = str(
                    cocanot_metadata.get(
                        "CoCANoT Patient ID",
                        "",
                    )
                    or ""
                ).strip()
                image_id = str(
                    cocanot_metadata.get(
                        "Image ID",
                        "",
                    )
                    or ""
                ).strip()
                participant_id = patient_id

                # If metadata exists in the patient database but there is no
                # matching BIDS output, report that state explicitly instead of
                # incorrectly saying the image is simply "Ready for Step 5".
                local_record = local_source_record

                if (
                    local_record is None
                    and patient_id
                    and image_id
                ):
                    local_record = self.repository.get_record(
                        self.get_site_id(),
                        "Imaging",
                        image_id,
                        patient_id=patient_id,
                    )

                # Preserve Step 4 review decisions regardless of Step 5
                # recovery status. Missing exports or a failed Step 5 stage
                # must not erase an Accepted decision and turn it Pending.
                # Explicit record deletion handles its own cleanup.
                if local_record is not None:
                    record_state = "recorded_export_missing"

                    local_metadata = local_record.get(
                        "metadata",
                        {},
                    )
                    if isinstance(local_metadata, dict):
                        cocanot_metadata = dict(
                            local_metadata
                        )

                    local_context = local_record.get(
                        "context",
                        {},
                    )
                    if isinstance(local_context, dict):
                        project = str(
                            local_context.get(
                                "project",
                                project,
                            )
                            or project
                        )
                        project_description = str(
                            local_context.get(
                                "project_description",
                                project_description,
                            )
                            or project_description
                        )
                        session_id = str(
                            local_context.get(
                                "session_id",
                                session_id,
                            )
                            or session_id
                        )

            records.append(
                {
                    "id": f"image-{index}",
                    "include": (
                        include
                        if record_state == "step5_pending"
                        else False
                    ),
                    "nifti_path": str(nifti_path),
                    "source_label": image["file_name"],
                    "source_key": source_key,
                    "defacing_source": image["defacing_source"],
                    "project": project,
                    "project_description": project_description,
                    "session_id": session_id,
                    "participant_id": self._derive_bids_subject(
                        participant_id
                    ),
                    "cocanot_metadata": cocanot_metadata,
                    "sidecar_metadata": sidecar_metadata,
                    "sidecar_source_name": source_sidecar.name if source_sidecar else "No JSON sidecar found",
                    "datatype": "",
                    "suffix": "",
                    "existing_export": existing_export,
                    "record_state": record_state,
                    "metadata_preloaded_from_output": (
                        record_state == "output_record_deleted"
                        and bool(cocanot_metadata)
                    ),
                    "metadata_source_path": (
                        str(
                            existing_export.get(
                                "cocanot_metadata_path",
                                "",
                            )
                            or existing_export.get(
                                "json_path",
                                "",
                            )
                        )
                        if existing_export is not None
                        else ""
                    ),
                    "metadata_confirmed": (
                        record_state == "completed_recorded"
                    ),
                    "status": {
                        "completed_recorded": "Already exported",
                        "output_record_deleted": (
                            "BIDS output exists; patient record missing"
                        ),
                        "recorded_export_missing": (
                            "Patient record exists; BIDS output missing"
                        ),
                        "step5_pending": "Ready for Step 5",
                    }[record_state],
                }
            )

        all_completed_recorded = (
            bool(records)
            and all(
                record.get("record_state")
                == "completed_recorded"
                for record in records
            )
        )

        has_real_problem = any(
            record.get("record_state")
            in {
                "output_record_deleted",
                "recorded_export_missing",
            }
            for record in records
        )

        if all_completed_recorded:
            self.imaging_stage_state[
                "metadata_bids"
            ] = "complete"
        elif (
            self._process_running(
                self.imaging_process
            )
            and self.imaging_active_operation
            == "metadata_bids"
        ):
            self.imaging_stage_state[
                "metadata_bids"
            ] = "running"
        elif has_real_problem:
            self.imaging_stage_state[
                "metadata_bids"
            ] = "failed"
        elif records:
            # Having accepted images that still need metadata/export is normal
            # workflow progress, not an error condition.
            self.imaging_stage_state[
                "metadata_bids"
            ] = "running"
        else:
            self.imaging_stage_state[
                "metadata_bids"
            ] = "not_started"

        try:
            self._save_imaging_pipeline_state(
                config
            )
        except Exception:
            pass

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
                    False,
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
            if bool(record.get("include", False))
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
        missing_clinical_assessments: list[dict[str, str]] = []
        normalized_records: list[dict[str, Any]] = []

        seen_image_ids: dict[tuple[str, str], str] = {}

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

            image_id = str(metadata.get("Image ID") or "").strip()
            if patient_id and image_id:
                identity = (patient_id, image_id)
                if identity in seen_image_ids:
                    problems.append(
                        f"{source_label}: Patient {patient_id}, Image ID {image_id} "
                        f"is also assigned to {seen_image_ids[identity]}. "
                        "Each selected image must have a unique Image ID for the patient."
                    )
                    continue
                seen_image_ids[identity] = source_label

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

                    if not any(
                        item["patient_id"] == patient_id
                        for item in missing_clinical_assessments
                    ):
                        missing_clinical_assessments.append(
                            {
                                "patient_id": patient_id,
                                "source_label": source_label,
                            }
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
            sidecar_edits = record.get("sidecar_metadata", {})
            if not isinstance(sidecar_edits, dict):
                problems.append(f"{source_label}: Linked metadata must be a JSON object.")
                continue
            normalized["sidecar_metadata"] = sidecar_edits
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
            "missing_clinical_assessments": missing_clinical_assessments,
        }

    def _imaging_derivative_paths_for_export(
        self,
        record: dict[str, Any],
        config,
    ) -> list[str]:
        stages = self._imaging_stage_paths(config)
        source_key = str(
            record.get(
                "source_key",
                "",
            )
            or ""
        ).strip()
        accepted_path = Path(
            str(
                record.get(
                    "nifti_path",
                    "",
                )
            )
        ).expanduser()

        candidates: list[Path] = []

        if source_key:
            relative = Path(source_key)
            prepared = stages["converted"] / relative
            candidates.append(prepared)

            prepared_base = self._strip_nifti_suffix(
                prepared
            )
            candidates.extend(
                [
                    stages["scrubbed"]
                    / relative.parent
                    / f"{prepared_base}_scrubbed.nii.gz",
                    stages["scrubbed"]
                    / relative.parent
                    / f"{prepared_base}_scrubbed.nii",
                    stages["defaced"]
                    / relative.parent
                    / f"{prepared_base}_scrubbed_defaced.nii.gz",
                    stages["defaced"]
                    / relative.parent
                    / f"{prepared_base}_scrubbed_defaced.nii",
                ]
            )

        if accepted_path.is_file():
            candidates.append(accepted_path)

        expanded: list[Path] = []
        seen: set[str] = set()

        for candidate in candidates:
            if not candidate.is_file():
                continue

            companions = [
                candidate,
                *(
                    [json_path]
                    if (json_path := _matching_json(candidate)) is not None
                    else []
                ),
                *_matching_extra_sidecars(candidate),
            ]

            for path in companions:
                resolved = _resolve_text(path)
                if resolved in seen:
                    continue
                seen.add(resolved)
                expanded.append(path)

        return [
            _resolve_text(path)
            for path in expanded
        ]

    def _imaging_header_annotations_for_export(self, source_key: str, config) -> dict[str, str]:
        """Read review-only header notes without modifying NIfTI headers."""
        state_path = self._imaging_stage_paths(config)["review_state"]
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(state, dict):
            return {}
        entry = state.get(source_key, {})
        if not isinstance(entry, dict):
            return {}
        notes = entry.get("header_annotations", entry.get("header_review_overrides", {}))
        if not isinstance(notes, dict):
            return {}
        return {
            str(field): str(note)
            for field, note in notes.items()
            if str(field).strip() and str(note).strip()
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
                    "source_key": str(
                        record.get(
                            "source_key",
                            "",
                        )
                        or ""
                    ),
                    "header_annotations": self._imaging_header_annotations_for_export(
                        str(record.get("source_key", "") or ""), config
                    ),
                    "source_label": str(
                        record.get(
                            "source_label",
                            "",
                        )
                        or ""
                    ),
                    "derivatives_root": str(
                        config.imaging.derivatives_dir
                    ),
                    "derivative_paths": self._imaging_derivative_paths_for_export(
                        record,
                        config,
                    ),
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
                    "sidecar_metadata": record.get("sidecar_metadata", {}),
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

        # The worker owns the final export and saves authoritative patient
        # links only AFTER the renamed NIfTI and JSON have been written.
        # Do not create a metadata-only "completed" record before export.

        def clear_drafts_after_success() -> None:
            # A zero exit code must also correspond to an actual final
            # export for EACH selected image, not just a saved patient record.
            links = PatientDataLinkStore()
            for record in included:
                metadata = record["cocanot_metadata"]
                patient_id = str(metadata.get("CoCANoT Patient ID") or "").strip()
                image_id = str(metadata.get("Image ID") or "").strip()
                link = links.get_link(self.get_site_id(), patient_id, "Imaging", image_id) or {}
                path_text = str(link.get("bids_data_path") or "")
                final_path = Path(path_text) if path_text else None
                if final_path is None or not final_path.is_file():
                    raise RuntimeError(f"Final BIDS NIfTI missing for patient {patient_id}, image {image_id}")
                if not final_path.resolve().is_relative_to(output_dir.resolve()):
                    raise RuntimeError(f"Final BIDS image is outside the selected output folder: {final_path}")
                sidecar_path = _matching_json(final_path)
                if sidecar_path is None:
                    raise RuntimeError(f"Final BIDS sidecar missing: {final_path}")
                payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
                embedded = payload.get("CoCANoTMetadata")
                if not isinstance(embedded, dict) or str(embedded.get("Image ID") or "") != image_id or str(embedded.get("CoCANoT Patient ID") or "") != patient_id:
                    raise RuntimeError(f"Final JSON is missing correct CoCANoTMetadata: {sidecar_path}")
            self._imaging_log(f"Verified {len(included)} renamed BIDS image(s), matching JSON sidecars and CoCANoTMetadata.")
            draft_path = self._imaging_stage_paths(
                config
            )["bids_drafts"]
            drafts = self._load_imaging_bids_drafts(
                draft_path
            )

            for record in included:
                source_key = str(
                    record.get(
                        "source_key",
                        "",
                    )
                    or ""
                ).strip()
                if source_key:
                    drafts.pop(
                        source_key,
                        None,
                    )

            self._save_imaging_bids_drafts(
                draft_path,
                drafts,
            )

        self._begin_imaging_stage(
            "metadata_bids",
            [output_dir],
        )

        try:
            self._start_process(
                command=command,
                workflow="imaging",
                description="Imaging BIDS / CoCANoT conversion",
                on_success=clear_drafts_after_success,
                on_complete=lambda return_code: self._finish_imaging_stage(
                    "metadata_bids",
                    return_code,
                ),
            )
        except Exception:
            self._fail_imaging_stage(
                "metadata_bids"
            )
            raise

        return {
            "ok": True,
            "state": "running",
            "status": "Imaging BIDS / CoCANoT conversion started",
            "process_stages": dict(self.imaging_stage_state),
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

        if (
            operation in {"prepare", "scrub", "deface", "review"}
            and self._process_running(self.imaging_process)
        ):
            raise RuntimeError(
                "Wait for the current Imaging step to finish or stop it before starting another step."
            )

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
            if not overwrite:
                try:
                    if self.dicom_input_paths and not self.nifti_input_paths:
                        already_prepared = self._verify_selected_dicom_stages(stages)[0]
                    elif self.nifti_input_paths and not self.dicom_input_paths:
                        already_prepared = self._verify_selected_nifti_stages(stages)[0]
                    else:
                        already_prepared = False
                except (OSError, ValueError):
                    already_prepared = False
                if already_prepared:
                    self._sync_imaging_stage_state_from_disk(config)
                    self._imaging_log(
                        "Selected imaging sources already have verified "
                        "derivative outputs; skipping NIfTI preparation."
                    )
                    return {
                        "ok": True,
                        "state": "complete",
                        "status": "Existing prepared NIfTI outputs verified",
                        "process_stages": dict(self.imaging_stage_state),
                        "active_operation": self.imaging_active_operation,
                    }
            cleanup_roots = [
                stages["converted"],
                config.imaging.derivatives_dir
                / "selected_dicom_files",
            ]
            self._begin_imaging_stage(
                "prepare",
                cleanup_roots,
            )

            try:
                result = self._prepare_imaging(
                    config=config,
                    stages=stages,
                    overwrite=overwrite,
                )
            except Exception:
                self._fail_imaging_stage(
                    "prepare"
                )
                raise

            if result.get("state") == "complete":
                self._finish_imaging_stage(
                    "prepare",
                    0,
                )

            return {
                **result,
                "process_stages": dict(
                    self.imaging_stage_state
                ),
                "active_operation": self.imaging_active_operation,
            }

        if operation == "scrub":
            if self.imaging_stage_state.get("prepare") != "complete":
                raise ValueError(
                    "Complete Prepare NIfTI before starting header scrubbing."
                )

            if not IMAGING_HEADER_SCRUBBER.is_file():
                raise FileNotFoundError(
                    f"NIfTI header scrubber not found: {IMAGING_HEADER_SCRUBBER}"
                )

            self._begin_imaging_stage(
                "scrub",
                [stages["scrubbed"]],
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

            try:
                self._start_process(
                    command=command,
                    workflow="imaging",
                    description="NIfTI header scrubbing",
                    on_complete=lambda return_code: self._finish_imaging_stage(
                        "scrub",
                        return_code,
                    ),
                )
            except Exception:
                self._fail_imaging_stage(
                    "scrub"
                )
                raise

            return {
                "ok": True,
                "state": "running",
                "status": "NIfTI header scrubbing started",
                "process_stages": dict(
                    self.imaging_stage_state
                ),
                "active_operation": self.imaging_active_operation,
            }

        if operation == "deface":
            if self.imaging_stage_state.get("scrub") != "complete":
                raise ValueError(
                    "Complete Scrub Headers before starting defacing."
                )

            if not IMAGING_DEFACER.is_file():
                raise FileNotFoundError(
                    f"PyDeface script not found: {IMAGING_DEFACER}"
                )

            self._begin_imaging_stage(
                "deface",
                [
                    stages["defaced"],
                    stages["logs"] / "pydeface",
                ],
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

            try:
                self._start_process(
                    command=command,
                    workflow="imaging",
                    description="NIfTI defacing",
                    on_complete=lambda return_code: self._finish_imaging_stage(
                        "deface",
                        return_code,
                    ),
                )
            except Exception:
                self._fail_imaging_stage(
                    "deface"
                )
                raise

            return {
                "ok": True,
                "state": "running",
                "status": "NIfTI defacing started",
                "process_stages": dict(
                    self.imaging_stage_state
                ),
                "active_operation": self.imaging_active_operation,
            }

        if operation == "review":
            if self.imaging_stage_state.get("deface") != "complete":
                raise ValueError(
                    "Complete Deface before opening Imaging review."
                )

            try:
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

                self.imaging_stage_state["review"] = "running"
                self.imaging_active_operation = ""
                self._refresh_imaging_review_stage()

                return {
                    "ok": True,
                    "state": self.imaging_stage_state["review"],
                    "status": "Imaging review in progress",
                    "log": "Opening React imaging review.",
                    "process_stages": dict(
                        self.imaging_stage_state
                    ),
                    "active_operation": "",
                }
            except Exception:
                self._fail_imaging_stage(
                    "review"
                )
                raise

        if operation == "bids":
            if self.imaging_stage_state.get("review") != "complete":
                raise ValueError(
                    "Complete Imaging review before opening Metadata & BIDS."
                )

            if self.imaging_stage_state.get("metadata_bids") != "complete":
                self.imaging_stage_state["metadata_bids"] = "running"

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
                "state": self.imaging_stage_state["metadata_bids"],
                "status": "Imaging metadata review in progress",
                "accepted_files": accepted,
                "held_count": held_count,
                "process_stages": dict(self.imaging_stage_state),
                "log": (
                    f"Loaded {len(accepted)} accepted image"
                    f"{'' if len(accepted) == 1 else 's'} "
                    "for Metadata & BIDS."
                ),
            }

        raise ValueError(
            f"Unknown Imaging operation: {operation}"
        )

    def _completed_dicom_series_for_prepare(
        self, config, stages: dict[str, Path],
    ) -> set[Path]:
        """DICOM leaf folders covered by verified successful preparations."""
        converted = stages["converted"].resolve()
        completed_files: set[tuple[str, int, int]] = set()
        for entry in self._read_imaging_completion_history(config).values():
            if not isinstance(entry, dict) or entry.get("stages", {}).get("prepare") != "complete":
                continue
            names = entry.get("prepared_files", [])
            if not isinstance(names, list) or not names:
                continue
            if not all(
                (converted / str(name)).resolve().is_relative_to(converted)
                and (converted / str(name)).is_file()
                and _is_nifti(converted / str(name))
                and (converted / str(name)).stat().st_size > 0
                for name in names
            ):
                continue
            sources = entry.get("sources", {})
            if not isinstance(sources, dict):
                continue
            for item in sources.get("dicom", []):
                if not isinstance(item, dict):
                    continue
                root = Path(str(item.get("path", ""))).expanduser()
                if item.get("kind") == "file":
                    pairs = [(root, item)]
                elif item.get("kind") == "directory":
                    pairs = [
                        (root / str(child.get("path", "")), child)
                        for child in item.get("entries", [])
                        if isinstance(child, dict)
                    ]
                else:
                    continue
                for file_path, detail in pairs:
                    if file_path.suffix.lower() not in {".dcm", ".ima", ""}:
                        continue
                    try:
                        completed_files.add((
                            str(file_path.resolve()),
                            int(detail["size"]), int(detail["mtime_ns"]),
                        ))
                    except (KeyError, TypeError, ValueError):
                        pass

        selected_dirs: set[Path] = set()
        for source_text in self.dicom_input_paths:
            root = Path(source_text).expanduser()
            directories = [root] if root.is_file() else [
                root, *sorted(p for p in root.rglob("*") if p.is_dir())
            ] if root.is_dir() else []
            for folder in directories:
                if not folder.is_dir():
                    continue
                try:
                    files = [
                        p for p in folder.iterdir()
                        if p.is_file() and not p.name.startswith(".")
                        and p.suffix.lower() in {".dcm", ".ima", ""}
                    ]
                    if files and all((
                        str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns
                    ) in completed_files for p in files):
                        selected_dirs.add(folder.resolve())
                except (OSError, PermissionError):
                    continue
        return selected_dirs

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
                "state": "complete",
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
        if not overwrite:
            skipped_dicom = self._completed_dicom_series_for_prepare(config, stages)
            for series_dir in sorted(skipped_dicom):
                command.extend(["--skip-dicom-dir", str(series_dir)])
            if skipped_dicom:
                self._imaging_log(
                    f"Skipping {len(skipped_dicom)} previously prepared DICOM series; "
                    "converting only series not already verified."
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
            on_complete=lambda return_code: self._finish_imaging_stage(
                "prepare",
                return_code,
            ),
        )

        return {
            "ok": True,
            "state": "running",
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

                if not overwrite and any(
                    self._files_match_for_imaging_resume(nifti_path, staged)
                    for staged in self._all_nifti_files(converted_dir)
                ):
                    self._imaging_log(
                        f"Skipping previously staged NIfTI source: {nifti_path}"
                    )
                    continue

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
        exported_keys: set[str] = set()
        try:
            config = load_imaging_config()
            output_root = config.imaging.bids_output_dir.resolve()
            # Reuse Step 5's authoritative source-to-record resolution rather
            # than matching a similarly named NIfTI to a different image.
            bids_records = self.imaging_bids_get_state().get("records", [])
            for record in bids_records:
                if record.get("record_state") != "completed_recorded":
                    continue
                exported = record.get("existing_export")
                if not isinstance(exported, dict):
                    continue
                image_path = Path(str(exported.get("nifti_path") or "")).expanduser()
                try:
                    image_path = image_path.resolve()
                    if not image_path.is_relative_to(output_root) or not image_path.is_file():
                        continue
                    sidecar_path = _matching_json(image_path)
                    if sidecar_path is None:
                        continue
                    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                    if not isinstance(sidecar, dict):
                        continue
                    identity = sidecar.get("CoCANoTMetadata")
                    if not isinstance(identity, dict):
                        identity = exported.get("cocanot_metadata")
                    if not isinstance(identity, dict):
                        continue
                    expected = record.get("cocanot_metadata")
                    if not isinstance(expected, dict):
                        continue
                    if not all(
                        str(identity.get(field) or "").strip()
                        and str(identity.get(field) or "").strip()
                        == str(expected.get(field) or "").strip()
                        for field in ("CoCANoT Patient ID", "Image ID")
                    ):
                        continue
                    key = str(record.get("source_key") or "")
                    if key:
                        exported_keys.add(key)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        except Exception:
            # The review sidebar must remain available if Step 5 is unconfigured
            # or its export index cannot be read.
            pass
        return [
            {
                "id": item["id"],
                "key": item["key"],
                "status": item["status"],
                "defacing_source": item["defacing_source"],
                "exported": (
                    item["status"] in {"Accepted", "Accepted - External"}
                    and item["key"] in exported_keys
                ),
            }
            for item in items
        ]

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
        mpl_image.imsave(buffer, array, cmap="gray", vmin=low, vmax=high, format="png", origin="upper")
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

        if len(raw_image.shape) not in {3, 4} or len(defaced_image.shape) not in {3, 4}:
            raise ValueError("Only 3D and 4D NIfTI images are supported.")
        if raw_image.shape != defaced_image.shape:
            raise ValueError(f"Raw and defaced image shapes do not match: {raw_image.shape} vs {defaced_image.shape}")
        if not np.allclose(raw_image.affine, defaced_image.affine, rtol=1e-5, atol=1e-3):
            raise ValueError(
                "Raw and defaced NIfTI affines do not match. Review spatial alignment "
                "before comparing slices; rotating a preview cannot repair an affine mismatch."
            )

        # Normalize temporary review images to nearest RAS+ so storage-axis order
        # cannot be mistaken for sagittal/coronal/axial anatomical orientation.
        # No file is written or modified by this display transformation.
        # Record suspicious spatial metadata instead of silently trusting an
        # anatomical plane assignment from potentially inconsistent headers.
        spatial_warnings = []
        for name, image in (("Raw", raw_image), ("Defaced", defaced_image)):
            matrix = np.asarray(image.affine, dtype=float)
            if not np.all(np.isfinite(matrix)):
                raise ValueError(f"{name} NIfTI has a non-finite spatial affine.")
            linear = matrix[:3, :3]
            if abs(float(np.linalg.det(linear))) < 1e-9:
                raise ValueError(f"{name} NIfTI has a singular spatial affine; anatomical slice identification is unreliable.")
            qform, qcode = image.get_qform(coded=True)
            sform, scode = image.get_sform(coded=True)
            if int(qcode) > 0 and int(scode) > 0 and not np.allclose(qform, sform, rtol=1e-4, atol=1e-2):
                spatial_warnings.append(f"{name}: qform and sform disagree; verify anatomical orientation in a trusted viewer.")
            if int(qcode) == 0 and int(scode) == 0:
                spatial_warnings.append(f"{name}: no coded qform or sform; anatomical orientation is not reliably established.")
            lengths = np.linalg.norm(linear, axis=0)
            if np.any(lengths <= 0):
                raise ValueError(f"{name} NIfTI has invalid voxel spacing.")
            directions = linear / lengths
            if np.max(np.abs(directions), axis=0).min() < 0.98:
                spatial_warnings.append(f"{name}: oblique acquisition; preview resampled into exact anatomical planes (display only).")

        # Build one shared world-aligned RAS+ review grid. Oblique voxel
        # coordinates are resampled into true anatomical planes for DISPLAY
        # ONLY; no image, affine, or stored metadata is rewritten.
        from scipy.ndimage import map_coordinates

        image_corners = np.array([
            [i, j, k, 1.0]
            for i in (-0.5, raw_image.shape[0] - 0.5)
            for j in (-0.5, raw_image.shape[1] - 0.5)
            for k in (-0.5, raw_image.shape[2] - 0.5)
        ], dtype=float).T
        world_corners = (raw_image.affine @ image_corners)[:3]
        world_min = world_corners.min(axis=1)
        world_max = world_corners.max(axis=1)
        voxel_sizes = np.linalg.norm(raw_image.affine[:3, :3], axis=0)
        spacing = float(np.min(voxel_sizes))
        if not np.isfinite(spacing) or spacing <= 0:
            raise ValueError("Invalid imaging voxel spacing for anatomical review.")
        # Cap the number of review coordinates to avoid huge memory demand
        # on images with wide oblique bounding boxes.
        axis_lengths = world_max - world_min
        spacing = max(spacing, float(np.max(axis_lengths) / 511.0))
        shape = tuple(max(2, int(np.ceil(length / spacing)) + 1) for length in axis_lengths)
        world_origin = world_min + 0.5 * spacing

        x_index = self._clamp_review_index(shape[0] // 2 if x is None else x, shape[0])
        y_index = self._clamp_review_index(shape[1] // 2 if y is None else y, shape[1])
        z_index = self._clamp_review_index(shape[2] // 2 if z is None else z, shape[2])
        volume_count = raw_image.shape[3] if len(raw_image.shape) == 4 else 1
        volume_index = self._clamp_review_index(0 if volume is None else volume, volume_count)

        inverse_affine = np.linalg.inv(raw_image.affine)
        coordinate_axes = [
            world_origin[axis] + np.arange(shape[axis], dtype=float) * spacing
            for axis in range(3)
        ]

        def anatomical_slice(data, plane):
            if plane == "axial":
                xx, yy = np.meshgrid(coordinate_axes[0], coordinate_axes[1], indexing="ij")
                zz = np.full_like(xx, coordinate_axes[2][z_index])
            elif plane == "coronal":
                xx, zz = np.meshgrid(coordinate_axes[0], coordinate_axes[2], indexing="ij")
                yy = np.full_like(xx, coordinate_axes[1][y_index])
            else:
                yy, zz = np.meshgrid(coordinate_axes[1], coordinate_axes[2], indexing="ij")
                xx = np.full_like(yy, coordinate_axes[0][x_index])
            world = np.stack((xx, yy, zz), axis=0).reshape(3, -1)
            source = inverse_affine[:3, :3] @ world + inverse_affine[:3, 3, None]
            sampled = map_coordinates(
                data, source, order=1, mode="constant", cval=0.0,
                prefilter=False,
            )
            view = np.rot90(sampled.reshape(xx.shape))
            # Anatomical sagittal convention: anterior on screen-left.
            return np.fliplr(view) if plane == "sagittal" else view

        raw = self._volume_array(raw_image, volume_index)
        clean = self._volume_array(defaced_image, volume_index)
        low, high = self._intensity_limits(raw, clean)
        views = {
            f"{name}_{plane}": anatomical_slice(data, plane)
            for name, data in (("raw", raw), ("defaced", clean))
            for plane in ("axial", "coronal", "sagittal")
        }
        # All resampled views use RAS+ world coordinates.
        display_raw = nib.as_closest_canonical(raw_image)
        display_defaced = nib.as_closest_canonical(defaced_image)

        raw_header = self._header_dict(prepared_path)
        scrubbed_header = self._header_dict(scrubbed_path)
        saved_review = self._load_review_state(self._imaging_review_items()[1]).get(item["key"], {})
        review_overrides = {**saved_review.get("header_review_overrides", {}), **saved_review.get("header_annotations", {})}
        header_rows = [
            {
                "field": key,
                "raw": raw_header.get(key, ""),
                "scrubbed": scrubbed_header.get(key, ""),
                "editable": key in scrubbed_header and key not in {"shape", "affine"},
                "review_only": key in {"shape", "affine"},
                "review_override": review_overrides.get(key),
            }
            for key in sorted(set(raw_header) | set(scrubbed_header))
        ]

        # np.rot90 followed by imsave(origin="upper") renders the second
        # slice axis positive toward screen-up. Match orientation markers
        # to the actual PNG pixel mapping, not just the stored voxel axes.
        def orientation_edges(image):
            try:
                codes = nib.aff2axcodes(image.affine)
                opposite = {"R": "L", "L": "R", "A": "P", "P": "A", "S": "I", "I": "S"}
                if len(codes) < 3 or any(code not in opposite for code in codes[:3]):
                    return {}
                def edges(first, second):
                    return {
                        "left": opposite[codes[first]],
                        "right": codes[first],
                        "top": codes[second],
                        "bottom": opposite[codes[second]],
                    }
                return {
                    "axial": edges(0, 1),
                    "coronal": edges(0, 2),
                    "sagittal": {**edges(1, 2), "left": codes[1], "right": opposite[codes[1]]},
                }
            except (ValueError, TypeError, np.linalg.LinAlgError):
                return {}

        raw_orientation = orientation_edges(display_raw)
        defaced_orientation = orientation_edges(display_defaced)

        return {
            "id": item["id"],
            "key": item["key"],
            "status": item["status"],
            "defacing_source": item["defacing_source"],
            "direction_annotations": self._load_review_state(self._imaging_review_items()[1]).get(item["key"], {}).get("direction_annotations", {}),
            "orientation_labels": {
                **{"raw_" + plane: labels for plane, labels in raw_orientation.items()},
                **{"defaced_" + plane: labels for plane, labels in defaced_orientation.items()},
            },
            "shape": list(shape),
            "ndim": len(shape),
            "is_4d": len(shape) == 4,
            "spatial_warnings": spatial_warnings,
            "display_orientation": {
                "raw_original": list(nib.aff2axcodes(raw_image.affine)),
                "defaced_original": list(nib.aff2axcodes(defaced_image.affine)),
                "canonical": list(nib.aff2axcodes(display_raw.affine)),
                "reoriented_for_display": not np.allclose(raw_image.affine, display_raw.affine),
            },
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

    def imaging_review_save_direction_annotations(self, item_id: str | int, panel: str, edits: dict[str, Any]) -> dict[str, Any]:
        items, state_path = self._imaging_review_items()
        index = int(item_id)
        if index < 0 or index >= len(items):
            raise ValueError("Imaging review item not found.")
        if panel not in {"raw_axial", "raw_coronal", "raw_sagittal", "defaced_axial", "defaced_coronal", "defaced_sagittal"}:
            raise ValueError("Invalid imaging panel.")
        if not isinstance(edits, dict):
            raise ValueError("Invalid direction annotation.")
        marker_values = {"", "R", "L", "A", "P", "S", "I"}
        labels = edits.get("manualLabels")
        if labels is not None:
            if not isinstance(labels, dict) or any(k not in {"left", "right", "top", "bottom"} or v not in marker_values for k, v in labels.items()):
                raise ValueError("Invalid anatomical direction labels.")
        rotation = edits.get("rotation", 0)
        if type(rotation) is not int or rotation not in {0, 90, 180, 270}:
            raise ValueError("Rotation must be 0, 90, 180, or 270 degrees.")
        state = self._load_review_state(state_path)
        entry = dict(state.get(items[index]["key"], {}))
        annotations = dict(entry.get("direction_annotations", {}))
        if type(edits.get("flipHorizontal", False)) is not bool or type(edits.get("flipVertical", False)) is not bool:
            raise ValueError("Display flip settings must be booleans.")
        annotations[panel] = {
            "manualLabels": labels,
            "rotation": rotation,
            "flipHorizontal": edits.get("flipHorizontal", False),
            "flipVertical": edits.get("flipVertical", False),
        }
        entry["direction_annotations"] = annotations
        state[items[index]["key"]] = entry
        self._save_review_state(state_path, state)
        return {"ok": True, "direction_annotations": annotations}

    def imaging_review_save_header(self, item_id: str | int, field: str, value: str) -> dict[str, Any]:
        import ast

        field = str(field or "").strip()
        items, _ = self._imaging_review_items()
        index = int(item_id)
        if index < 0 or index >= len(items):
            raise ValueError("Imaging review item not found.")
        item = items[index]
        scrubbed_path = Path(item["scrubbed_path"])
        image = nib.load(str(scrubbed_path))
        header = image.header.copy()
        # Derived properties are not independently serialized header fields.
        # Every actual header field is eligible for a validated edit; nothing
        # is silently made annotation-only merely because of its name.
        if field not in header:
            raise ValueError(
                f"{field} is a derived or unsupported property, not a writable "
                "NIfTI header entry. It cannot be changed independently."
            )

        original_shape = tuple(image.shape)
        original_affine = np.array(image.affine, copy=True)
        original_dtype = image.get_data_dtype()
        original_qform, original_qcode = image.get_qform(coded=True)
        original_sform, original_scode = image.get_sform(coded=True)

        current = np.asarray(header[field])
        try:
            if current.dtype.kind in {"S", "U"}:
                header[field] = str(value or "").encode("utf-8")
            else:
                parsed = ast.literal_eval(str(value).strip())
                candidate = np.asarray(parsed)
                if candidate.shape != current.shape:
                    raise ValueError(f"Expected a value with shape {current.shape}, got {candidate.shape}.")
                if current.dtype.kind in {"i", "u"}:
                    numeric = np.asarray(candidate, dtype=np.float64)
                    if not np.all(np.isfinite(numeric)) or not np.all(numeric == np.floor(numeric)):
                        raise ValueError("Integer fields require finite whole numbers.")
                    limits = np.iinfo(current.dtype)
                    if np.any(numeric < limits.min) or np.any(numeric > limits.max):
                        raise ValueError("Integer header value is out of range.")
                if current.dtype.kind == "f" and not np.all(np.isfinite(np.asarray(candidate, dtype=float))):
                    raise ValueError("Numeric header fields must contain finite values.")
                header[field] = np.asarray(candidate, dtype=current.dtype)
        except (SyntaxError, TypeError, OverflowError, ValueError) as exc:
            raise ValueError(f"Invalid value for NIfTI header field {field}: {exc}") from exc

        updated = nib.Nifti1Image(np.asanyarray(image.dataobj), original_affine, header)
        updated.set_qform(original_qform, int(original_qcode))
        updated.set_sform(original_sform, int(original_scode))
        if (tuple(updated.shape) != original_shape or
                not np.allclose(updated.affine, original_affine, atol=1e-6, rtol=1e-6) or
                updated.get_data_dtype() != original_dtype):
            raise ValueError("This edit would change image geometry or voxel data type. It was not saved.")

        # Validate through a round-trip on a temporary NIfTI before replacing
        # the original, so invalid edits cannot corrupt the scrubbed image.
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".nii.gz" if str(scrubbed_path).endswith(".gz") else ".nii",
            prefix=".header_edit_", dir=str(scrubbed_path.parent), delete=False
        ) as temporary:
            temp_path = Path(temporary.name)
        try:
            nib.save(updated, str(temp_path))
            checked = nib.load(str(temp_path))
            if (tuple(checked.shape) != original_shape or
                    not np.allclose(checked.affine, original_affine, atol=1e-6, rtol=1e-6) or
                    checked.get_data_dtype() != original_dtype):
                raise ValueError(
                    "Cannot edit this field: it would alter image geometry or voxel type."
                )
            # Reject fields that the NIfTI writer normalizes, ignores, or
            # cannot round-trip safely. Do not report success for a no-op.
            intended = np.asarray(header[field])
            actual = np.asarray(checked.header[field])
            if not np.array_equal(intended, actual):
                raise ValueError(
                    f"Cannot edit {field}: the NIfTI format recalculates or "
                    "normalizes this value when the image is saved."
                )
            os.replace(temp_path, scrubbed_path)
        finally:
            temp_path.unlink(missing_ok=True)
        # The accepted PyDeface output was created before this review edit.
        # Mirror the safe header field into that derivative so Step 5 exports
        # the reviewed value, while leaving voxel geometry unchanged.
        defaced_path = Path(item["automated_defaced_path"])
        if defaced_path.is_file():
            defaced = nib.load(str(defaced_path))
            defaced_header = defaced.header.copy()
            defaced_header[field] = header[field]
            defaced_affine = np.array(defaced.affine, copy=True)
            dqform, dqcode = defaced.get_qform(coded=True)
            dsform, dscode = defaced.get_sform(coded=True)
            defaced_updated = nib.Nifti1Image(
                np.asanyarray(defaced.dataobj), defaced_affine, defaced_header
            )
            defaced_updated.set_qform(dqform, int(dqcode))
            defaced_updated.set_sform(dsform, int(dscode))
            with tempfile.NamedTemporaryFile(
                suffix=".nii.gz" if str(defaced_path).endswith(".gz") else ".nii",
                prefix=".header_edit_", dir=str(defaced_path.parent), delete=False
            ) as temporary:
                defaced_temp = Path(temporary.name)
            try:
                nib.save(defaced_updated, str(defaced_temp))
                check = nib.load(str(defaced_temp))
                if (check.shape != defaced.shape
                        or check.get_data_dtype() != defaced.get_data_dtype()
                        or not np.allclose(check.affine, defaced_affine, atol=1e-6, rtol=1e-6)):
                    raise ValueError("Defaced header synchronization failed integrity checks.")
                os.replace(defaced_temp, defaced_path)
            finally:
                defaced_temp.unlink(missing_ok=True)
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
        self._refresh_imaging_review_stage()
        try:
            self._save_imaging_pipeline_state(load_imaging_config())
        except Exception:
            pass
        self._imaging_log(f"Imaging review status: {item['key']} -> {status}")
        return {
            "ok": True,
            "id": item["id"],
            "key": item["key"],
            "status": status,
            "review_stage": self.imaging_stage_state.get("review", "running"),
        }

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

        if self._window is None:
            return {"ok": False}

        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "NIfTI files (*.nii;*.gz)",
                "All files (*.*)",
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

        self._refresh_imaging_review_stage()
        try:
            self._save_imaging_pipeline_state(load_imaging_config())
        except Exception:
            pass

        return {
            "ok": True,
            "status": "Pending External Review",
            "path": str(destination.resolve()),
            "review_stage": self.imaging_stage_state.get("review", "running"),
        }

    def imaging_stop_operation(self) -> dict[str, Any]:
        operation = self.imaging_active_operation

        if not operation:
            return {
                "ok": True,
                "status": "Nothing is currently running.",
                "process_stages": dict(
                    self.imaging_stage_state
                ),
                "active_operation": "",
                "process_running": False,
            }

        self.imaging_stage_state[operation] = "stopped"
        self._stop_process("imaging")
        removed = self._cleanup_stopped_imaging_stage(
            operation
        )
        self.imaging_active_operation = ""

        try:
            self._save_imaging_pipeline_state(load_imaging_config())
        except Exception:
            pass

        cleanup_message = (
            f"Stopped {operation}. Removed {removed} partial derivative "
            f"file{'' if removed == 1 else 's'} created by this step."
        )
        self._imaging_log(
            cleanup_message
        )

        return {
            "ok": True,
            "status": "Stopped",
            "cleanup_message": cleanup_message,
            "process_stages": dict(
                self.imaging_stage_state
            ),
            "active_operation": "",
            "process_running": False,
        }

    @staticmethod
    def _surgical_followup_database_path() -> Path:
        path = (
            Path.home()
            / ".cocanot"
            / "local_tracking"
            / "surgical_followup.sqlite3"
        )
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        return path

    def _surgical_followup_connection(
        self,
    ) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._surgical_followup_database_path()
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS surgical_followup_dates (
                site_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                surgery_id TEXT NOT NULL,
                real_surgery_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (
                    site_id,
                    patient_id,
                    surgery_id
                )
            )
            """
        )
        return connection

    def _validated_tracking_identity(
        self,
        site_id: str,
        patient_id: str,
        surgery_id: str,
    ) -> tuple[str, str, str]:
        active_site = normalize_site_id(
            self.get_site_id()
        )
        requested_site = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()
        surgery_id = str(
            surgery_id or ""
        ).strip()

        if not active_site:
            raise PermissionError(
                "Sign in to a site before accessing local surgery tracking."
            )

        if requested_site != active_site:
            raise PermissionError(
                "The requested site does not match the active site."
            )

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID is required."
            )

        if not surgery_id:
            raise ValueError(
                "Surgery ID is required."
            )

        return (
            active_site,
            patient_id,
            surgery_id,
        )

    def metadata_get_real_surgery_date(
        self,
        site_id: str,
        patient_id: str,
        surgery_id: str,
    ) -> dict[str, str]:
        site_id, patient_id, surgery_id = (
            self._validated_tracking_identity(
                site_id,
                patient_id,
                surgery_id,
            )
        )

        with self._surgical_followup_connection() as connection:
            row = connection.execute(
                """
                SELECT real_surgery_date
                FROM surgical_followup_dates
                WHERE site_id = ?
                  AND patient_id = ?
                  AND surgery_id = ?
                """,
                (
                    site_id,
                    patient_id,
                    surgery_id,
                ),
            ).fetchone()

        return {
            "real_surgery_date": (
                str(
                    row["real_surgery_date"]
                )
                if row is not None
                else ""
            )
        }

    def metadata_save_real_surgery_date(
        self,
        site_id: str,
        patient_id: str,
        surgery_id: str,
        real_surgery_date: str,
    ) -> dict[str, str]:
        site_id, patient_id, surgery_id = (
            self._validated_tracking_identity(
                site_id,
                patient_id,
                surgery_id,
            )
        )

        real_surgery_date = str(
            real_surgery_date or ""
        ).strip()

        if not real_surgery_date:
            raise ValueError(
                "Actual Surgery Date is required."
            )

        try:
            parsed_date = datetime.strptime(
                real_surgery_date,
                "%Y-%m-%d",
            ).date()
        except ValueError as exc:
            raise ValueError(
                "Actual Surgery Date must use YYYY-MM-DD."
            ) from exc

        normalized_date = parsed_date.isoformat()
        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self._surgical_followup_connection() as connection:
            connection.execute(
                """
                INSERT INTO surgical_followup_dates (
                    site_id,
                    patient_id,
                    surgery_id,
                    real_surgery_date,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    site_id,
                    patient_id,
                    surgery_id
                )
                DO UPDATE SET
                    real_surgery_date = excluded.real_surgery_date,
                    updated_at = excluded.updated_at
                """,
                (
                    site_id,
                    patient_id,
                    surgery_id,
                    normalized_date,
                    now,
                    now,
                ),
            )

            saved = connection.execute(
                """
                SELECT real_surgery_date
                FROM surgical_followup_dates
                WHERE site_id = ?
                  AND patient_id = ?
                  AND surgery_id = ?
                """,
                (
                    site_id,
                    patient_id,
                    surgery_id,
                ),
            ).fetchone()

        if saved is None:
            raise RuntimeError(
                "Actual Surgery Date could not be read back after saving."
            )

        return {
            "real_surgery_date": str(
                saved["real_surgery_date"]
            )
        }

    def _delete_real_surgery_date(
        self,
        site_id: str,
        patient_id: str,
        surgery_id: str,
    ) -> None:
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()
        surgery_id = str(
            surgery_id or ""
        ).strip()

        if not site_id or not patient_id or not surgery_id:
            return

        with self._surgical_followup_connection() as connection:
            connection.execute(
                """
                DELETE FROM surgical_followup_dates
                WHERE site_id = ?
                  AND patient_id = ?
                  AND surgery_id = ?
                """,
                (
                    site_id,
                    patient_id,
                    surgery_id,
                ),
            )


    @staticmethod
    def _metadata_document_root() -> Path:
        path = (
            Path.home()
            / ".cocanot"
            / "local_documents"
        )
        path.mkdir(
            parents=True,
            exist_ok=True,
        )
        return path

    @classmethod
    def _metadata_document_database_path(cls) -> Path:
        return cls._metadata_document_root() / "attachments.sqlite3"

    def _metadata_document_connection(
        self,
    ) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._metadata_document_database_path()
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata_documents (
                document_id TEXT PRIMARY KEY,
                site_id TEXT NOT NULL,
                patient_id TEXT NOT NULL,
                table_name TEXT NOT NULL,
                record_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                sanitized_path TEXT NOT NULL,
                document_types TEXT NOT NULL DEFAULT '[]',
                attachment_state TEXT NOT NULL DEFAULT 'attached',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(metadata_documents)"
            ).fetchall()
        }
        if "document_types" not in columns:
            connection.execute("ALTER TABLE metadata_documents ADD COLUMN document_types TEXT NOT NULL DEFAULT '[]'")
        if "attachment_state" not in columns:
            connection.execute("ALTER TABLE metadata_documents ADD COLUMN attachment_state TEXT NOT NULL DEFAULT 'attached'")
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_metadata_documents_record
            ON metadata_documents (
                site_id,
                patient_id,
                table_name,
                record_id
            )
            """
        )
        return connection

    def _validated_metadata_document_identity(
        self,
        patient_id: str,
        table_name: str,
        record_id: str,
    ) -> tuple[str, str, str, str]:
        site_id = normalize_site_id(
            self.get_site_id()
        )
        patient_id = str(
            patient_id or ""
        ).strip()
        table_name = str(
            table_name or ""
        ).strip()
        record_id = str(
            record_id or ""
        ).strip()

        if not site_id:
            raise PermissionError(
                "Sign in to a site before accessing associated documents."
            )

        if table_name not in {
            "Clinical",
            "Surgical",
        }:
            raise ValueError(
                "Associated documents are supported only for "
                "Clinical and Surgical metadata."
            )

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID is required."
            )

        if not record_id:
            raise ValueError(
                "A metadata record must be selected before attaching a document."
            )

        patient = self.metadata_get_patient(
            site_id,
            patient_id,
        )
        record_group = (
            patient.get("clinical", [])
            if table_name == "Clinical"
            else patient.get("surgical", [])
        )
        record_ids = {
            str(record.get("record_id", "")).strip()
            for record in record_group
        }

        if record_id not in record_ids:
            raise ValueError(
                f"{table_name} record {record_id} was not found for "
                f"patient {patient_id} at the active site."
            )

        return (
            site_id,
            patient_id,
            table_name,
            record_id,
        )

    @staticmethod
    def _document_data_url(
        image_bytes: bytes,
        mime_type: str = "image/png",
    ) -> str:
        encoded = base64.b64encode(
            image_bytes
        ).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _render_metadata_document_pages(
        self,
        path: Path,
    ) -> list[dict[str, Any]]:
        suffix = path.suffix.lower()
        pages: list[dict[str, Any]] = []

        if suffix == ".pdf":
            document = fitz.open(
                str(path)
            )
            try:
                matrix = fitz.Matrix(
                    1.5,
                    1.5,
                )
                for index, page in enumerate(document):
                    pixmap = page.get_pixmap(
                        matrix=matrix,
                        alpha=False,
                    )
                    image_bytes = pixmap.tobytes(
                        "png"
                    )
                    pages.append(
                        {
                            "page_index": index,
                            "width": pixmap.width,
                            "height": pixmap.height,
                            "image_data_url": self._document_data_url(
                                image_bytes
                            ),
                        }
                    )
            finally:
                document.close()

            return pages

        with Image.open(path) as image:
            image.seek(0)
            preview = image.convert("RGB")
            buffer = io.BytesIO()
            preview.save(
                buffer,
                format="PNG",
            )
            pages.append(
                {
                    "page_index": 0,
                    "width": preview.width,
                    "height": preview.height,
                    "image_data_url": self._document_data_url(
                        buffer.getvalue()
                    ),
                }
            )

        return pages

    @staticmethod
    def _normalized_redaction_boxes(
        redactions: Any,
        page_index: int,
    ) -> list[dict[str, float]]:
        if not isinstance(
            redactions,
            dict,
        ):
            return []

        raw_boxes = redactions.get(
            str(page_index),
            [],
        )
        if not isinstance(
            raw_boxes,
            list,
        ):
            return []

        boxes: list[dict[str, float]] = []

        for raw_box in raw_boxes:
            if not isinstance(
                raw_box,
                dict,
            ):
                continue

            try:
                x = float(
                    raw_box.get("x", 0)
                )
                y = float(
                    raw_box.get("y", 0)
                )
                width = float(
                    raw_box.get("width", 0)
                )
                height = float(
                    raw_box.get("height", 0)
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            x = max(
                0.0,
                min(1.0, x),
            )
            y = max(
                0.0,
                min(1.0, y),
            )
            width = max(
                0.0,
                min(1.0 - x, width),
            )
            height = max(
                0.0,
                min(1.0 - y, height),
            )

            if width <= 0 or height <= 0:
                continue

            boxes.append(
                {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                }
            )

        return boxes

    def _save_redacted_pdf(
        self,
        source_path: Path,
        destination_path: Path,
        redactions: Any,
    ) -> None:
        document = fitz.open(
            str(source_path)
        )

        try:
            for page_index, page in enumerate(document):
                page_rect = page.rect
                boxes = self._normalized_redaction_boxes(
                    redactions,
                    page_index,
                )

                for box in boxes:
                    x0 = page_rect.x0 + (
                        box["x"] * page_rect.width
                    )
                    y0 = page_rect.y0 + (
                        box["y"] * page_rect.height
                    )
                    x1 = x0 + (
                        box["width"] * page_rect.width
                    )
                    y1 = y0 + (
                        box["height"] * page_rect.height
                    )

                    page.add_redact_annot(
                        fitz.Rect(
                            x0,
                            y0,
                            x1,
                            y1,
                        ),
                        fill=(0, 0, 0),
                    )

                if boxes:
                    page.apply_redactions()

            destination_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            document.save(
                str(destination_path),
                garbage=4,
                deflate=True,
                clean=True,
            )
        finally:
            document.close()

    def _save_redacted_image(
        self,
        source_path: Path,
        destination_path: Path,
        redactions: Any,
    ) -> None:
        with Image.open(source_path) as source_image:
            image = source_image.convert("RGB")

        draw = ImageDraw.Draw(
            image
        )
        boxes = self._normalized_redaction_boxes(
            redactions,
            0,
        )

        for box in boxes:
            x0 = int(
                round(
                    box["x"] * image.width
                )
            )
            y0 = int(
                round(
                    box["y"] * image.height
                )
            )
            x1 = int(
                round(
                    (box["x"] + box["width"])
                    * image.width
                )
            )
            y1 = int(
                round(
                    (box["y"] + box["height"])
                    * image.height
                )
            )
            draw.rectangle(
                (
                    x0,
                    y0,
                    x1,
                    y1,
                ),
                fill="black",
            )

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if destination_path.suffix.lower() in {
            ".jpg",
            ".jpeg",
        }:
            image.save(
                destination_path,
                format="JPEG",
                quality=95,
            )
        else:
            image.save(
                destination_path,
                format="PNG",
            )

    @staticmethod
    def _metadata_document_filename_part(
        value: Any,
    ) -> str:
        value = str(
            value or ""
        ).strip()
        value = re.sub(
            r"[^A-Za-z0-9_-]+",
            "-",
            value,
        )
        return value.strip("-_") or "unknown"

    @classmethod
    def _metadata_document_output_name(
        cls,
        patient_id: str,
        record_id: str,
        document_types: list[str],
        suffix: str,
    ) -> str:
        patient_part = cls._metadata_document_filename_part(
            patient_id
        )
        record_part = cls._metadata_document_filename_part(
            record_id
        )
        type_part = "-".join(
            cls._metadata_document_filename_part(value).lower()
            for value in document_types
        )
        if not type_part:
            type_part = "supporting-document"

        return (
            f"{patient_part}_{record_part}_"
            f"{type_part}_supporting-document{suffix}"
        )

    def metadata_document_list(
        self,
        patient_id: str,
        table_name: str,
        record_id: str,
    ) -> list[dict[str, Any]]:
        (
            site_id,
            patient_id,
            table_name,
            record_id,
        ) = self._validated_metadata_document_identity(
            patient_id,
            table_name,
            record_id,
        )

        with self._metadata_document_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    document_id,
                    file_name,
                    document_types,
                    status,
                    created_at,
                    updated_at
                FROM metadata_documents
                WHERE site_id = ?
                  AND patient_id = ?
                  AND table_name = ?
                  AND record_id = ?
                  AND attachment_state = 'attached'
                ORDER BY created_at DESC
                """,
                (
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                ),
            ).fetchall()

        return [
            {
                "document_id": str(row["document_id"]),
                "file_name": str(row["file_name"]),
                "document_types": json.loads(
                    str(row["document_types"] or "[]")
                ),
                "status": str(row["status"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def metadata_document_get_preview(
        self,
        patient_id: str,
        table_name: str,
        record_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        (
            site_id,
            patient_id,
            table_name,
            record_id,
        ) = self._validated_metadata_document_identity(
            patient_id,
            table_name,
            record_id,
        )
        document_id = str(
            document_id or ""
        ).strip()

        if not document_id:
            raise ValueError(
                "Document ID is required."
            )

        with self._metadata_document_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    document_id,
                    file_name,
                    document_types,
                    sanitized_path,
                    status
                FROM metadata_documents
                WHERE document_id = ?
                  AND site_id = ?
                  AND patient_id = ?
                  AND table_name = ?
                  AND record_id = ?
                  AND attachment_state = 'attached'
                """,
                (
                    document_id,
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                ),
            ).fetchone()

        if row is None:
            raise ValueError(
                "The associated document was not found for this patient record."
            )

        path = Path(
            str(row["sanitized_path"])
        ).expanduser().resolve()
        root = self._metadata_document_root().resolve()

        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PermissionError(
                "The stored document path is outside the local document repository."
            ) from exc

        if not path.is_file():
            raise FileNotFoundError(
                "The sanitized associated document is missing from local storage."
            )

        return {
            "document_id": str(row["document_id"]),
            "file_name": str(row["file_name"]),
            "document_types": json.loads(
                str(row["document_types"] or "[]")
            ),
            "status": str(row["status"]),
            "pages": self._render_metadata_document_pages(
                path
            ),
        }


    def metadata_document_begin_edit(
        self,
        patient_id: str,
        table_name: str,
        record_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        (
            site_id,
            patient_id,
            table_name,
            record_id,
        ) = self._validated_metadata_document_identity(
            patient_id,
            table_name,
            record_id,
        )
        document_id = str(
            document_id or ""
        ).strip()

        if not document_id:
            raise ValueError(
                "Document ID is required."
            )

        with self._metadata_document_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    document_id,
                    file_name,
                    document_types,
                    sanitized_path,
                    status
                FROM metadata_documents
                WHERE document_id = ?
                  AND site_id = ?
                  AND patient_id = ?
                  AND table_name = ?
                  AND record_id = ?
                  AND attachment_state = 'attached'
                """,
                (
                    document_id,
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                ),
            ).fetchone()

        if row is None:
            raise ValueError(
                "The associated document was not found for this patient record."
            )

        source_path = Path(
            str(row["sanitized_path"])
        ).expanduser().resolve()
        root = self._metadata_document_root().resolve()

        try:
            source_path.relative_to(root)
        except ValueError as exc:
            raise PermissionError(
                "The stored document path is outside the local document repository."
            ) from exc

        if not source_path.is_file():
            raise FileNotFoundError(
                "The sanitized associated document is missing from local storage."
            )

        document_types = json.loads(
            str(row["document_types"] or "[]")
        )

        pages = self._render_metadata_document_pages(
            source_path
        )
        if not pages:
            raise ValueError(
                "The associated document could not be rendered for editing."
            )

        self._pending_metadata_documents[
            document_id
        ] = {
            "document_id": document_id,
            "site_id": site_id,
            "patient_id": patient_id,
            "table_name": table_name,
            "record_id": record_id,
            "source_path": str(source_path),
            "source_suffix": source_path.suffix.lower(),
            "document_types": document_types,
            "edit_existing": True,
            "existing_sanitized_path": str(source_path),
            "existing_file_name": str(row["file_name"]),
        }

        return {
            "document_id": document_id,
            "file_name": str(row["file_name"]),
            "status": "Editing",
            "document_types": document_types,
            "pages": pages,
            "edit_existing": True,
        }

    def metadata_document_choose(
        self,
        patient_id: str,
        table_name: str,
        record_id: str,
        document_types: list[str] | None = None,
    ) -> dict[str, Any] | None:
        (
            site_id,
            patient_id,
            table_name,
            record_id,
        ) = self._validated_metadata_document_identity(
            patient_id,
            table_name,
            record_id,
        )

        document_types = [
            str(value).strip()
            for value in (document_types or [])
            if str(value).strip()
        ]
        if not document_types:
            raise ValueError(
                "Select at least one supporting document type."
            )

        if self._window is None:
            return None

        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Supported documents (*.pdf;*.png;*.jpg;*.jpeg)",
                "PDF files (*.pdf)",
                "Image files (*.png;*.jpg;*.jpeg)",
            ),
        )

        if not selected:
            return None

        if isinstance(
            selected,
            (
                list,
                tuple,
            ),
        ):
            selected = selected[0]

        source_path = Path(
            str(selected)
        ).expanduser().resolve()

        if not source_path.is_file():
            raise FileNotFoundError(
                "The selected document could not be found."
            )

        if source_path.suffix.lower() not in {
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
        }:
            raise ValueError(
                "Choose a PDF, PNG, JPG, or JPEG document."
            )

        document_id = uuid.uuid4().hex
        pages = self._render_metadata_document_pages(
            source_path
        )

        if not pages:
            raise ValueError(
                "The selected document could not be rendered for review."
            )

        self._pending_metadata_documents[
            document_id
        ] = {
            "document_id": document_id,
            "site_id": site_id,
            "patient_id": patient_id,
            "table_name": table_name,
            "record_id": record_id,
            "source_path": str(source_path),
            "source_suffix": source_path.suffix.lower(),
            "document_types": document_types,
        }

        return {
            "document_id": document_id,
            "file_name": source_path.name,
            "status": "Needs Review",
            "document_types": document_types,
            "pages": pages,
        }

    def metadata_document_save_redactions(
        self,
        document_id: str,
        redactions: Any,
    ) -> dict[str, Any]:
        document_id = str(
            document_id or ""
        ).strip()

        pending = self._pending_metadata_documents.get(
            document_id
        )

        if pending is None:
            raise ValueError(
                "This document review is no longer active. "
                "Choose the document again before saving."
            )

        active_site = normalize_site_id(
            self.get_site_id()
        )
        if not active_site or active_site != pending["site_id"]:
            raise PermissionError(
                "The active site does not match this document review."
            )

        source_path = Path(
            pending["source_path"]
        )

        if not source_path.is_file():
            raise FileNotFoundError(
                "The original local document is no longer available."
            )

        source_suffix = str(
            pending["source_suffix"]
        ).lower()
        output_suffix = (
            ".pdf"
            if source_suffix == ".pdf"
            else ".jpg"
            if source_suffix in {
                ".jpg",
                ".jpeg",
            }
            else ".png"
        )

        record_key = hashlib.sha256(
            (
                f"{pending['site_id']}|"
                f"{pending['patient_id']}|"
                f"{pending['table_name']}|"
                f"{pending['record_id']}"
            ).encode("utf-8")
        ).hexdigest()[:24]

        destination_dir = (
            self._metadata_document_root()
            / "sanitized"
            / record_key
        )
        output_name = self._metadata_document_output_name(
            pending["patient_id"],
            pending["record_id"],
            pending.get("document_types", []),
            output_suffix,
        )
        destination_path = (
            destination_dir
            / output_name
        )

        editing_existing = bool(
            pending.get("edit_existing")
        )

        if editing_existing:
            existing_path = Path(
                str(
                    pending.get(
                        "existing_sanitized_path",
                        source_path,
                    )
                )
            ).expanduser().resolve()

            destination_path = existing_path
            working_output_path = existing_path.with_name(
                f".{existing_path.stem}.{uuid.uuid4().hex}.tmp{existing_path.suffix}"
            )
        else:
            if destination_path.exists():
                destination_path = (
                    destination_dir
                    / (
                        f"{destination_path.stem}_"
                        f"{document_id[:8]}"
                        f"{destination_path.suffix}"
                    )
                )
            working_output_path = destination_path

        try:
            if source_suffix == ".pdf":
                self._save_redacted_pdf(
                    source_path,
                    working_output_path,
                    redactions,
                )
            else:
                self._save_redacted_image(
                    source_path,
                    working_output_path,
                    redactions,
                )

            if editing_existing:
                working_output_path.replace(
                    destination_path
                )
        except Exception:
            if editing_existing:
                working_output_path.unlink(
                    missing_ok=True
                )
            raise

        now = datetime.now(
            timezone.utc
        ).isoformat()
        file_name = (
            str(
                pending.get(
                    "existing_file_name",
                    "",
                )
            ).strip()
            if editing_existing
            else destination_path.name
        )
        if not file_name:
            file_name = destination_path.name

        try:
            with self._metadata_document_connection() as connection:
                if editing_existing:
                    connection.execute(
                        """
                        UPDATE metadata_documents
                        SET
                            file_name = ?,
                            sanitized_path = ?,
                            document_types = ?,
                            attachment_state = 'attached',
                            status = 'Attached',
                            updated_at = ?
                        WHERE document_id = ?
                          AND site_id = ?
                          AND patient_id = ?
                          AND table_name = ?
                          AND record_id = ?
                          AND attachment_state = 'attached'
                        """,
                        (
                            file_name,
                            str(destination_path),
                            json.dumps(pending.get("document_types", [])),
                            now,
                            document_id,
                            pending["site_id"],
                            pending["patient_id"],
                            pending["table_name"],
                            pending["record_id"],
                        ),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO metadata_documents (
                            document_id,
                            site_id,
                            patient_id,
                            table_name,
                            record_id,
                            file_name,
                            sanitized_path,
                            document_types,
                            attachment_state,
                            status,
                            created_at,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            pending["site_id"],
                            pending["patient_id"],
                            pending["table_name"],
                            pending["record_id"],
                            file_name,
                            str(destination_path),
                            json.dumps(pending.get("document_types", [])),
                            "staged",
                            "Redaction Reviewed",
                            now,
                            now,
                        ),
                    )
        except Exception:
            destination_path.unlink(
                missing_ok=True
            )
            raise

        self._pending_metadata_documents.pop(
            document_id,
            None,
        )

        return {
            "ok": True,
            "document_id": document_id,
            "file_name": file_name,
            "document_types": pending.get("document_types", []),
            "status": (
                "Attached"
                if editing_existing
                else "Redaction Reviewed"
            ),
            "edit_existing": editing_existing,
        }

    def metadata_document_attach(self, patient_id: str, table_name: str, record_id: str, document_ids: list[str]) -> dict[str, Any]:
        site_id, patient_id, table_name, record_id = self._validated_metadata_document_identity(patient_id, table_name, record_id)
        ids = [str(value).strip() for value in (document_ids or []) if str(value).strip()]
        if not ids:
            raise ValueError("Select at least one reviewed document to attach.")
        now = datetime.now(timezone.utc).isoformat()
        attached = []
        with self._metadata_document_connection() as connection:
            for document_id in ids:
                row = connection.execute("SELECT document_id FROM metadata_documents WHERE document_id = ? AND site_id = ? AND patient_id = ? AND table_name = ? AND record_id = ? AND attachment_state = 'staged'", (document_id, site_id, patient_id, table_name, record_id)).fetchone()
                if row is None:
                    raise ValueError(f"Reviewed document {document_id} is not available for this patient record.")
                connection.execute("UPDATE metadata_documents SET attachment_state = 'attached', status = 'Attached', updated_at = ? WHERE document_id = ?", (now, document_id))
                attached.append(document_id)
        return {"ok": True, "attached": attached}

    def metadata_document_delete(
        self,
        document_id: str,
    ) -> dict[str, Any]:
        document_id = str(
            document_id or ""
        ).strip()

        if not document_id:
            raise ValueError(
                "Document ID is required."
            )

        active_site = normalize_site_id(
            self.get_site_id()
        )
        if not active_site:
            raise PermissionError(
                "Sign in to a site before removing associated documents."
            )

        with self._metadata_document_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    site_id,
                    sanitized_path
                FROM metadata_documents
                WHERE document_id = ?
                """,
                (
                    document_id,
                ),
            ).fetchone()

            if row is None:
                return {
                    "ok": True,
                    "deleted": False,
                }

            if normalize_site_id(
                str(row["site_id"])
            ) != active_site:
                raise PermissionError(
                    "This document belongs to a different site."
                )

            sanitized_path = Path(
                str(row["sanitized_path"])
            )

            connection.execute(
                """
                DELETE FROM metadata_documents
                WHERE document_id = ?
                  AND site_id = ?
                """,
                (
                    document_id,
                    active_site,
                ),
            )

        root = self._metadata_document_root().resolve()
        try:
            resolved_path = sanitized_path.resolve()
            resolved_path.relative_to(
                root
            )
        except (
            OSError,
            ValueError,
        ):
            resolved_path = None

        if resolved_path is not None:
            resolved_path.unlink(
                missing_ok=True
            )

        return {
            "ok": True,
            "deleted": True,
        }

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
        patient_id = self._resolve_existing_patient_id(patient_id)

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

        def canonicalize_records(
            table_name: str,
            records: list[dict[str, Any]],
        ) -> list[dict[str, Any]]:
            normalized_records: list[
                dict[str, Any]
            ] = []

            for record in records:
                row = dict(
                    record
                    or {}
                )

                dictionary_version = (
                    str(
                        row.get(
                            "dictionary_version",
                            "",
                        )
                        or ""
                    ).strip()
                    if table_name == "Clinical"
                    else ""
                )

                _dictionary, rules, _validator = (
                    self._dictionary_context(
                        table_name,
                        dictionary_version,
                    )
                )

                row["metadata"] = (
                    self._normalize_metadata_values(
                        dict(
                            row.get(
                                "metadata",
                                {},
                            )
                            or {}
                        ),
                        rules,
                    )
                )

                normalized_records.append(
                    row
                )

            return normalized_records

        result["clinical"] = canonicalize_records(
            "Clinical",
            list(
                summary.get(
                    "Clinical",
                    [],
                )
            ),
        )
        result["surgical"] = canonicalize_records(
            "Surgical",
            list(
                summary.get(
                    "Surgical",
                    [],
                )
            ),
        )
        result["imaging"] = canonicalize_records(
            "Imaging",
            list(
                summary.get(
                    "Imaging",
                    [],
                )
            ),
        )
        result["electrophysiology"] = canonicalize_records(
            "Electrophysiology",
            list(
                summary.get(
                    "Electrophysiology",
                    [],
                )
            ),
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
        # Prioritize the final Step 5 BIDS export, not the original Step 3
        # prepared/defaced NIfTI or its dcm2niix JSON sidecar.
        context = dict(record.get("context", {}) or {})
        metadata = dict(record.get("metadata", {}) or {})
        expected_patient = str(metadata.get("CoCANoT Patient ID", "") or "").strip()
        expected_image = str(metadata.get("Image ID", "") or "").strip()

        def matches_export(candidate: Path) -> bool:
            if not candidate.is_file() or not _is_nifti(candidate):
                return False
            sidecar = _matching_json(candidate)
            if sidecar is None:
                return False
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            if not isinstance(payload, dict):
                return False
            embedded = payload.get("CoCANoTMetadata", {})
            if not isinstance(embedded, dict):
                embedded = {}
            patient = str(payload.get("CoCANoTPatientID") or embedded.get("CoCANoT Patient ID") or "").strip()
            image_id = str(payload.get("ImageID") or embedded.get("Image ID") or "").strip()
            return bool(expected_patient and expected_image and patient == expected_patient and image_id == expected_image)

        # The export worker writes authoritative final paths into the data
        # link store, which may be newer than the patient record context.
        link = {}
        if expected_patient and expected_image:
            try:
                link = PatientDataLinkStore().get_link(
                    self.get_site_id(), expected_patient, "Imaging", expected_image
                ) or {}
            except (OSError, ValueError):
                link = {}
        explicit_link = link.get("bids_data_path")
        if explicit_link:
            candidate = Path(str(explicit_link)).expanduser()
            if matches_export(candidate):
                return candidate.resolve()
        for candidate_text in link.get("final_paths", []) or []:
            candidate = Path(str(candidate_text)).expanduser()
            if matches_export(candidate):
                return candidate.resolve()

        explicit = context.get("bids_data_path", "")
        if explicit:
            candidate = Path(str(explicit)).expanduser()
            if matches_export(candidate):
                return candidate.resolve()

        config = load_imaging_config()
        output_roots = []
        for value in (
            link.get("final_output_root"),
            context.get("final_output_root"),
            context.get("bids_output_dir"),
            str(config.imaging.bids_output_dir),
        ):
            if not value:
                continue
            root = Path(str(value)).expanduser()
            if root not in output_roots:
                output_roots.append(root)

        # A patient record can have been exported to a previous destination.
        # Search its recorded final output folder before the current default.
        for output_dir in output_roots:
            if output_dir.is_dir() and expected_patient and expected_image:
                for candidate in sorted(output_dir.rglob("*.nii.gz")) + sorted(output_dir.rglob("*.nii")):
                    if matches_export(candidate):
                        return candidate.resolve()

        # Older patient records may predate the BIDS link or complete sidecar.
        # Permit their explicitly linked image for review, but never claim it
        # is a Step 5 export. The frontend displays its actual source status.
        for candidate in self._metadata_record_file_candidates(record, kind="imaging"):
            if candidate.is_file() and _is_nifti(candidate):
                return candidate.resolve()

        raise FileNotFoundError(
            "No accessible linked imaging file was found for "
            f"CoCANoT Patient ID {expected_patient or '(missing)'} and "
            f"Image ID {expected_image or '(missing)'}. "
            "Complete or repeat Step 5 BIDS export, then reopen Review Linked Image. "
            "The original Step 3 image is deliberately not substituted here."
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

        # Match Step 4: display isotropic, world-aligned anatomical slices.
        # This prevents anisotropic voxel grids from looking squashed.
        from scipy.ndimage import map_coordinates

        original_shape = tuple(int(value) for value in image.shape)
        is_4d = len(original_shape) == 4
        corners = np.array([
            [i, j, k, 1.0]
            for i in (-0.5, original_shape[0] - 0.5)
            for j in (-0.5, original_shape[1] - 0.5)
            for k in (-0.5, original_shape[2] - 0.5)
        ], dtype=float).T
        world_corners = (image.affine @ corners)[:3]
        world_min = world_corners.min(axis=1)
        world_max = world_corners.max(axis=1)
        voxel_sizes = np.linalg.norm(image.affine[:3, :3], axis=0)
        spacing = float(np.min(voxel_sizes))
        if not np.isfinite(spacing) or spacing <= 0:
            raise ValueError("Invalid imaging voxel spacing for anatomical review.")
        lengths = world_max - world_min
        spacing = max(spacing, float(np.max(lengths) / 511.0))
        shape3d = tuple(max(2, int(np.ceil(length / spacing)) + 1) for length in lengths)
        shape = shape3d + (original_shape[3],) if is_4d else shape3d
        origin = world_min + 0.5 * spacing
        axes = [origin[axis] + np.arange(shape3d[axis]) * spacing for axis in range(3)]
        x_index = self._clamp_review_index(shape3d[0] // 2 if x is None else x, shape3d[0])
        y_index = self._clamp_review_index(shape3d[1] // 2 if y is None else y, shape3d[1])
        z_index = self._clamp_review_index(shape3d[2] // 2 if z is None else z, shape3d[2])
        volume_count = original_shape[3] if is_4d else 1
        volume_index = self._clamp_review_index(0 if volume is None else volume, volume_count)
        data = self._volume_array(image, volume_index)
        low, high = self._intensity_limits(data, data)
        inverse = np.linalg.inv(image.affine)

        def anatomical_slice(plane):
            if plane == "axial":
                xx, yy = np.meshgrid(axes[0], axes[1], indexing="ij")
                zz = np.full_like(xx, axes[2][z_index])
            elif plane == "coronal":
                xx, zz = np.meshgrid(axes[0], axes[2], indexing="ij")
                yy = np.full_like(xx, axes[1][y_index])
            else:
                yy, zz = np.meshgrid(axes[1], axes[2], indexing="ij")
                xx = np.full_like(yy, axes[0][x_index])
            world = np.stack((xx, yy, zz), axis=0).reshape(3, -1)
            source = inverse[:3, :3] @ world + inverse[:3, 3, None]
            sampled = map_coordinates(data, source, order=1, mode="constant", cval=0.0, prefilter=False)
            view = np.rot90(sampled.reshape(xx.shape))
            return np.fliplr(view) if plane == "sagittal" else view

        views = {plane: anatomical_slice(plane) for plane in ("axial", "coronal", "sagittal")}
        direction_labels = {
            "axial": {"left": "L", "right": "R", "top": "A", "bottom": "P"},
            "coronal": {"left": "L", "right": "R", "top": "S", "bottom": "I"},
            "sagittal": {"left": "A", "right": "P", "top": "S", "bottom": "I"},
        }
        config_for_preview = load_imaging_config()
        try:
            linked_is_bids_export = any(
                path.resolve().is_relative_to(root.resolve())
                for root in (
                    config_for_preview.imaging.bids_output_dir,
                    Path(str((record.get("context") or {}).get("bids_output_dir") or config_for_preview.imaging.bids_output_dir)),
                )
            )
        except (OSError, ValueError):
            linked_is_bids_export = False
        linked_header = self._header_dict(path)
        sidecar_path = _matching_json(path)
        sidecar = None
        sidecar_error = None
        if sidecar_path and sidecar_path.is_file():
            try:
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                sidecar_error = str(exc)

        review_annotations = {}
        try:
            review_items, review_state_path = self._imaging_review_items()
            review_state = self._load_review_state(review_state_path)
            resolved = path.resolve()
            for candidate in review_items:
                linked_paths = [
                    candidate.get("prepared_path"), candidate.get("scrubbed_path"),
                    candidate.get("review_defaced_path"), candidate.get("accepted_defaced_path")
                ]
                if any(p and Path(p).resolve() == resolved for p in linked_paths):
                    review_annotations = review_state.get(candidate["key"], {}).get("direction_annotations", {})
                    break
        except (OSError, ValueError, KeyError):
            pass

        return {
            "orientation_labels": direction_labels,
            "direction_annotations": review_annotations,
            "linked_is_bids_export": linked_is_bids_export,
            "linked_json_has_cocanot_metadata": isinstance(sidecar, dict) and isinstance(sidecar.get("CoCANoTMetadata"), dict),
            "record_cocanot_metadata": dict(record.get("metadata") or {}),
            "linked_header": linked_header,
            "linked_json": sidecar,
            "linked_json_path": str(sidecar_path) if sidecar_path else "",
            "linked_json_error": sidecar_error,
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
        # Match Imaging: prefer an authoritative final export for this
        # patient and Recording ID, not an older scrubbed derivative.
        metadata = dict(record.get("metadata", {}) or {})
        patient_id = str(metadata.get("CoCANoT Patient ID") or "").strip()
        recording_id = str(metadata.get("Recording ID") or "").strip()
        context = dict(record.get("context", {}) or {})
        try:
            link = PatientDataLinkStore().get_link(
                self.get_site_id(), patient_id, "Electrophysiology", recording_id
            ) or {}
        except (OSError, ValueError):
            link = {}

        def is_linked_final(path: Path) -> bool:
            if not path.is_file() or path.suffix.lower() != ".edf":
                return False
            sidecar = path.with_suffix(".json")
            if not sidecar.is_file():
                return False
            try:
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            if not isinstance(payload, dict):
                return False
            cocanot = payload.get("CoCANoTMetadata")
            return (
                isinstance(cocanot, dict)
                and str(cocanot.get("CoCANoT Patient ID") or "").strip() == patient_id
                and str(cocanot.get("Recording ID") or "").strip() == recording_id
            )

        for candidate_text in [
            link.get("bids_data_path"), context.get("bids_data_path"),
            *(link.get("final_paths") or []),
        ]:
            if candidate_text:
                candidate = Path(str(candidate_text)).expanduser()
                if is_linked_final(candidate):
                    return candidate.resolve()

        for root_text in [
            link.get("final_output_root"), context.get("bids_output_dir"),
        ]:
            if root_text:
                root = Path(str(root_text)).expanduser()
                if root.is_dir():
                    for candidate in root.rglob("*.edf"):
                        if is_linked_final(candidate):
                            return candidate.resolve()

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

    def ephys_review_signal_preview(
        self, pair_id: str | int, source: str = "scrubbed",
        start_seconds: float = 0.0, window_seconds: float = 10.0,
        channels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Read waveform windows from the selected Step 4 EDF, without modifying it."""
        pairs = self.ephys_review_get_pairs()
        try:
            index = int(pair_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid EDF review selection.") from exc
        if index < 0 or index >= len(pairs):
            raise ValueError("EDF review pair not found.")
        if source not in {"raw", "scrubbed"}:
            raise ValueError("Select raw or scrubbed EDF.")
        path = Path(pairs[index][f"{source}_path"])
        # The preview method resolves explicitly linked EDF paths.
        return self.metadata_get_ephys_signal_preview(
            {"context": {"edf_path": str(path)}, "metadata": {}},
            start_seconds, window_seconds, channels,
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

            sidecar_metadata = {}
            sidecar_path = path.with_suffix(".json")
            if sidecar_path.is_file():
                try:
                    sidecar_value = json.loads(sidecar_path.read_text(encoding="utf-8"))
                    if isinstance(sidecar_value, dict):
                        sidecar_metadata = {
                            **{key: value for key, value in sidecar_value.items()
                               if key != "CoCANoTMetadata"},
                            **({"CoCANoTMetadata": sidecar_value["CoCANoTMetadata"]}
                               if isinstance(sidecar_value.get("CoCANoTMetadata"), dict)
                               else {}),
                        }
                except (OSError, json.JSONDecodeError):
                    pass
            try:
                header = reader.getHeader()
                header = {
                    str(key): (value.isoformat() if hasattr(value, "isoformat") else str(value))
                    for key, value in header.items()
                }
            except Exception:
                header = {}

            try:
                annotation_onsets, annotation_durations, annotation_descriptions = reader.readAnnotations()
                annotations = [
                    {
                        "onset": float(onset),
                        "duration": float(duration),
                        "description": str(description),
                    }
                    for onset, duration, description in zip(
                        annotation_onsets, annotation_durations, annotation_descriptions
                    )
                ]
            except Exception:
                annotations = []

            return {
                "path": str(
                    path
                ),
                "file_name": path.name,
                "header": header,
                "annotations": annotations,
                "linked_metadata": sidecar_metadata,
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
        patient_id = normalize_patient_id(patient_id)

        if not site_id:
            raise ValueError("Site ID is required.")

        if not patient_id:
            raise ValueError("Patient ID is required.")

        # Use an existing legacy spelling rather than creating a second patient.
        patient_id = self._resolve_existing_patient_id(patient_id) or patient_id

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
        dictionary_version: str = "",
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
                table_name,
                dictionary_version,
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
        assessment_id: str = "",
    ) -> dict[str, Any]:
        patient_id = str(
            patient_id or ""
        ).strip()

        if patient_id:
            patient_id = (
                self._resolve_existing_patient_id(
                    patient_id
                )
                or patient_id
            )

        assessment_id = str(
            assessment_id or ""
        ).strip().upper()

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID is required."
            )

        site_id = self.get_site_id()
        latest = self.store.latest_clinical_assessment(
            site_id,
            patient_id,
        )

        target = (
            self.store.clinical_assessment(
                site_id,
                patient_id,
                assessment_id,
            )
            if assessment_id
            else None
        )

        if assessment_id and target is None:
            raise ValueError(
                f"Clinical Assessment {assessment_id} was not found."
            )

        historical = bool(
            target is not None
            and latest is not None
            and int(
                target[
                    "assessment_number"
                ]
            )
            < int(
                latest[
                    "assessment_number"
                ]
            )
        )

        target_version = (
            str(
                target.get(
                    "dictionary_version",
                    "",
                )
                or ""
            ).strip()
            if historical
            else ""
        )

        dictionary, rules, _validator = (
            self._dictionary_context(
                "Clinical",
                target_version,
            )
        )
        dictionary_version = (
            _dictionary_version_from_table(
                dictionary,
                "Clinical",
            )
        )

        clean = self._normalize_metadata_values(
            dict(
                metadata or {}
            ),
            rules,
        )
        clean[
            "CoCANoT Patient ID"
        ] = patient_id

        if historical:
            clean[
                "Clinical Assessment ID"
            ] = assessment_id
        elif latest is not None:
            clean[
                "Clinical Assessment ID"
            ] = str(
                latest.get(
                    "assessment_id",
                    "",
                )
                or ""
            ).strip().upper()
        else:
            clean[
                "Clinical Assessment ID"
            ] = "CA-001"

        exclusive_problems = (
            _exclusive_multiselect_conflicts(
                clean,
                rules,
            )
        )

        if exclusive_problems:
            raise ValueError(
                "\n".join(
                    exclusive_problems[
                        :20
                    ]
                )
            )

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

        if historical:
            saved = (
                self.store.update_historical_clinical_assessment(
                    site_id,
                    patient_id,
                    assessment_id,
                    clean,
                )
            )
        else:
            tracked = tracked_clinical_fields(
                dictionary
            )
            saved = (
                self.store.save_clinical_assessment(
                    site_id,
                    patient_id,
                    clean,
                    tracked,
                    dictionary_version=dictionary_version,
                )
            )

        self.repository.create_patient(
            site_id,
            patient_id,
        )

        return dict(
            saved
        )

    def _sync_edited_imaging_export(
        self, metadata: dict[str, Any], existing: dict[str, Any] | None, original_id: str = ""
    ) -> dict[str, Any] | None:
        """Update an already exported image and matching JSON after metadata edits.

        Only operate on a verified final export with a sidecar matching this
        patient and Image ID. Never rename original/derivative NIfTI files.
        """
        if not existing:
            return None
        patient = str(metadata.get("CoCANoT Patient ID") or "").strip()
        image_id = str(metadata.get("Image ID") or "").strip()
        link_store = PatientDataLinkStore()
        link = link_store.get_link(self.get_site_id(), patient, "Imaging", original_id or image_id) or {}
        old_context = dict(existing.get("context") or {})
        candidate_text = str(link.get("bids_data_path") or old_context.get("bids_data_path") or "")
        if not candidate_text:
            return None
        old_path = Path(candidate_text).expanduser()
        old_json = _matching_json(old_path)
        if not old_path.is_file() or old_json is None:
            return None
        sidecar = json.loads(old_json.read_text(encoding="utf-8"))
        embedded = sidecar.get("CoCANoTMetadata")
        if not isinstance(embedded, dict) or (
            str(embedded.get("CoCANoT Patient ID") or "") != patient
            or str(embedded.get("Image ID") or "") != (original_id or image_id)
        ):
            raise ValueError("Saved imaging sidecar identity does not match the patient record; export was not renamed.")
        modality = str(metadata.get("Imaging Modality") or "").strip()
        if modality == "CT":
            suffix, datatype = "ct", "ct"
        elif modality == "MRI":
            sequence = self._imaging_sequence_value(metadata)
            mapping = {"T1": ("anat", "T1w"), "T2": ("anat", "T2w"),
                       "FLAIR": ("anat", "FLAIR"), "DWI": ("dwi", "dwi"),
                       "SWI": ("anat", "SWI")}
            if sequence not in mapping:
                raise ValueError("Cannot rename MRI export: unsupported sequence.")
            datatype, suffix = mapping[sequence]
        else:
            raise ValueError("Cannot rename imaging export: unsupported modality.")
        old_base = self._strip_nifti_suffix(old_path)
        session_match = re.search(r"(?:^|_)ses-([A-Za-z0-9+]+)(?:_|$)", old_base)
        run_match = re.search(r"(?:^|_)run-(\d+)(?:_|$)", old_base)
        acq_match = re.search(r"(?:^|_)acq-([A-Za-z0-9+]+)(?:_|$)", old_base)
        # Mirror Step 5 export naming: include the stable CoCANoT Image ID.
        # Keep the original ID (with punctuation) in the sidecar/record.
        filename_image_id = re.sub(r"[^A-Za-z0-9]+", "", image_id)
        if not filename_image_id:
            raise ValueError("Cannot rename imaging export without a valid Image ID.")
        parts = [f"sub-{self._derive_bids_subject(patient)}", filename_image_id]
        if session_match:
            parts.append(f"ses-{session_match.group(1)}")
        if acq_match:
            parts.append(f"acq-{acq_match.group(1)}")
        if run_match:
            parts.append(f"run-{run_match.group(1)}")
        parts.append(suffix)
        # SWI retains its acquisition identity in the BIDS basename while
        # using the established anatomical T2starw representation.
        # Do not append a duplicate acq label if one already exists.
        if modality == "MRI" and sequence == "SWI":
            parts = [part for part in parts if part != "acq-SWI"]
        new_base = "_".join(parts)
        # Keep the same project and optional session directories; move only
        # the final datatype directory if the sequence/modality changes.
        target_dir = old_path.parent if old_path.parent.name == datatype else old_path.parent.parent / datatype
        extension = ".nii.gz" if old_path.name.endswith(".nii.gz") else ".nii"
        new_path = target_dir / f"{new_base}{extension}"
        new_json = target_dir / f"{new_base}.json"
        old_extra = old_path.with_name(f"{old_base}_cocanot.json")
        new_extra = target_dir / f"{new_base}_cocanot.json"
        # DWI requires genuine gradients: a metadata edit cannot derive them
        # from an anatomical scan. Fail before touching the existing export.
        old_bval = old_path.with_name(f"{old_base}.bval")
        old_bvec = old_path.with_name(f"{old_base}.bvec")
        if datatype == "dwi":
            if not old_bval.is_file() or not old_bvec.is_file():
                raise ValueError(
                    "Cannot reclassify this anatomical export as DWI: matching "
                    ".bval and .bvec gradient files are missing. Reprocess the "
                    "original diffusion acquisition in Imaging Step 3/5 to "
                    "recover genuine gradient information."
                )
            try:
                import nibabel as nib
                import numpy as np
                count = len(old_bval.read_text(encoding="utf-8").split())
                gradient_rows = [
                    row.split() for row in old_bvec.read_text(encoding="utf-8").splitlines()
                    if row.strip()
                ]
                volumes = int(nib.load(str(old_path)).shape[3]) if len(nib.load(str(old_path)).shape) > 3 else 1
                if count != volumes or len(gradient_rows) != 3 or any(len(row) != volumes for row in gradient_rows):
                    raise ValueError(
                        f"gradient counts do not match NIfTI volumes ({volumes})"
                    )
                bvals = np.asarray([float(v) for v in old_bval.read_text().split()])
                bvecs = np.asarray([[float(v) for v in row] for row in gradient_rows])
                if not np.isfinite(bvals).all() or not np.isfinite(bvecs).all():
                    raise ValueError("gradient data contain non-finite values")
            except (OSError, ValueError, IndexError) as exc:
                raise ValueError(f"Cannot reclassify as DWI: invalid gradient files: {exc}") from exc
        movements = [(old_path, new_path), (old_json, new_json)]
        # CoCANoT metadata is embedded in the canonical JSON sidecar.
        # Diffusion sidecars belong exclusively to DWI exports.
        for suffix_ext in (".bval", ".bvec"):
            old_associated = old_path.with_name(f"{old_base}{suffix_ext}")
            if datatype == "dwi" and old_associated.is_file():
                movements.append((old_associated, target_dir / f"{new_base}{suffix_ext}"))
        # Never turn a mislabeled or incomplete export into a new SWI link.
        # Check source image integrity before making any filesystem changes.
        if modality == "MRI" and sequence == "SWI":
            try:
                import nibabel as nib
                image = nib.load(str(old_path))
                if len(image.shape) < 3 or any(dim < 1 for dim in image.shape[:3]):
                    raise ValueError("Invalid SWI image dimensions.")
            except Exception as exc:
                raise ValueError(
                    f"Cannot export SWI: the existing NIfTI cannot be read: {exc}"
                ) from exc
        for source, destination in movements:
            if source != destination and destination.exists():
                raise ValueError(f"Edited imaging filename already exists: {destination}")
        sidecar["CoCANoTMetadata"] = dict(metadata)
        sidecar["CoCANoTPatientID"] = patient
        sidecar["ImageID"] = image_id
        sidecar["ClinicalAssessmentID"] = metadata.get("Clinical Assessment ID")
        sidecar["ImagingModality"] = modality
        if modality == "MRI":
            sidecar["MRISequence"] = self._imaging_sequence_value(metadata)
        else:
            sidecar.pop("MRISequence", None)
        for field_name, json_key in (
            ("Purpose of Imaging (multiselect)", "PurposeOfImaging"),
            ("Timing Relative to Surgery", "TimingRelativeToSurgery"),
            ("Imaging Findings (multiselect)", "ImagingFindings"),
            ("Other Imaging Findings (if applicable; free text)", "OtherImagingFindings"),
            ("Other Purpose of Imaging (if applicable; free text)", "OtherPurposeOfImaging"),
            ("Comments (free text)", "Comments"),
        ):
            if field_name in metadata:
                sidecar[json_key] = metadata[field_name]
        surgery_id = str(metadata.get("Surgery ID") or "").strip()
        if surgery_id:
            sidecar["SurgeryID"] = surgery_id
        else:
            sidecar.pop("SurgeryID", None)
        target_dir.mkdir(parents=True, exist_ok=True)
        moved = []
        try:
            for source, destination in movements:
                if source != destination:
                    source.rename(destination)
                    moved.append((source, destination))
            new_json.write_text(json.dumps(sidecar, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        except Exception:
            for source, destination in reversed(moved):
                if destination.exists():
                    destination.rename(source)
            raise
        # Only after the new image and JSON have been written successfully,
        # remove obsolete gradients when converting DWI to anatomical/CT.
        if datatype != "dwi":
            for obsolete in (old_bval, old_bvec):
                obsolete.unlink(missing_ok=True)
        if modality == "MRI" and sequence == "SWI":
            # Confirm the new export resolves before changing patient links.
            if not new_path.is_file() or not new_json.is_file():
                raise RuntimeError("SWI export verification failed: NIfTI or JSON missing.")
            verified_sidecar = json.loads(new_json.read_text(encoding="utf-8"))
            if (verified_sidecar.get("MRISequence") != "SWI"
                or verified_sidecar.get("ImageID") != image_id):
                raise RuntimeError("SWI export verification failed: metadata mismatch.")
        updated = {**old_context, **link, "bids_data_path": str(new_path.resolve()),
                   "bids_sidecar_path": str(new_json.resolve()),
                   "final_output_root": str(Path(link.get("final_output_root") or old_context.get("bids_output_dir") or new_path.parent.parent).resolve()),
                   "final_paths": [str(dest.resolve()) for _, dest in movements]}
        # New exports use the consolidated JSON; older dual-file exports
        # retain their own metadata path until explicitly migrated.
        updated["cocanot_metadata_path"] = str(new_json.resolve())
        # The unified JSON has been written successfully; retire obsolete legacy metadata.
        if old_extra.is_file() and old_extra != new_json:
            old_extra.unlink()
        link_store.save_link(self.get_site_id(), patient, "Imaging", image_id, updated)
        if original_id and original_id != image_id:
            link_store.delete_link(self.get_site_id(), patient, "Imaging", original_id)
        return updated

    def _sync_edited_ephys_export(
        self, metadata: dict[str, Any], existing: dict[str, Any] | None, original_id: str = ""
    ) -> dict[str, Any] | None:
        """Rename the existing final EDF and sidecars in place after metadata edits."""
        if not existing:
            return None
        patient = str(metadata.get("CoCANoT Patient ID") or "").strip()
        recording_id = str(metadata.get("Recording ID") or "").strip()
        if not patient or not recording_id:
            return None
        store = PatientDataLinkStore()
        link = store.get_link(self.get_site_id(), patient, "Electrophysiology", original_id or recording_id) or {}
        old_context = dict(existing.get("context") or {})
        candidate = link.get("bids_data_path") or old_context.get("bids_data_path")
        if not candidate:
            return None
        old_edf = Path(str(candidate)).expanduser()
        old_json = old_edf.with_suffix(".json")
        if not old_edf.is_file() or not old_json.is_file():
            return None
        payload = json.loads(old_json.read_text(encoding="utf-8"))
        embedded = payload.get("CoCANoTMetadata") if isinstance(payload, dict) else None
        if not isinstance(embedded, dict) or (
            str(embedded.get("CoCANoT Patient ID") or "").strip() != patient
            or str(embedded.get("Recording ID") or "").strip() != (original_id or recording_id)
        ):
            raise ValueError("Final EDF JSON identity does not match this patient and recording; no files were renamed.")

        from ElectrophysiologyPipeline.scripts.convert_edf_to_bids import (
            RECORDING_MODALITY_TO_DATATYPE,
        )
        modality = str(metadata.get("Recording Modality") or "").strip()
        datatype = RECORDING_MODALITY_TO_DATATYPE.get(modality)
        if not datatype or datatype == "meg":
            raise ValueError(f"Unsupported EDF recording modality: {modality!r}")
        normalized_id = re.sub(r"[^A-Za-z0-9]+", "", recording_id)
        if normalized_id.upper().startswith("EPHYS"):
            normalized_id = "EPHYS-" + normalized_id[5:]
        filename_parts = [f"sub-{self._derive_bids_subject(patient)}", normalized_id]
        session = re.search(r"(?:^|_)ses-([A-Za-z0-9]+)(?:_|$)", old_edf.stem)
        run = re.search(r"(?:^|_)run-([A-Za-z0-9]+)(?:_|$)", old_edf.stem)
        if session:
            filename_parts.append("ses-" + session.group(1))
        if run:
            filename_parts.append("run-" + run.group(1))
        filename_parts.append(datatype)
        new_base = "_".join(filename_parts)
        new_dir = old_edf.parent if old_edf.parent.name == datatype else old_edf.parent.parent / datatype
        old_base = old_edf.stem
        moves = [
            (old_edf, new_dir / f"{new_base}.edf"),
            (old_json, new_dir / f"{new_base}.json"),
        ]
        for suffix in ("_channels.tsv", "_events.tsv", "_electrodes.tsv", "_coordsystem.json", "_cocanot.json"):
            old_file = old_edf.with_name(old_base + suffix)
            if old_file.is_file():
                moves.append((old_file, new_dir / (new_base + suffix)))
        for source, target in moves:
            if source != target and target.exists():
                raise ValueError(f"Cannot rename EDF export: destination exists: {target}")
        payload = {
            **{key: value for key, value in payload.items() if key != "CoCANoTMetadata"},
            "CoCANoTMetadata": dict(metadata),
            "CoCANoTPatientID": patient,
            "RecordingID": recording_id,
            "RecordingModality": modality,
        }
        new_dir.mkdir(parents=True, exist_ok=True)
        moved = []
        try:
            for source, target in moves:
                if source != target:
                    source.rename(target)
                    moved.append((source, target))
            moves[1][1].write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        except Exception:
            for source, target in reversed(moved):
                if target.exists():
                    target.rename(source)
            raise
        updated = {
            **old_context, **link,
            "bids_data_path": str(moves[0][1].resolve()),
            "bids_sidecar_path": str(moves[1][1].resolve()),
            "cocanot_metadata_path": str(moves[1][1].resolve()),
            "final_paths": [str(target.resolve()) for _, target in moves],
        }
        if "final_output_root" not in updated:
            updated["final_output_root"] = str(new_dir.parent.parent.resolve())
        store.save_link(self.get_site_id(), patient, "Electrophysiology", recording_id, updated)
        if original_id and original_id != recording_id:
            store.delete_link(self.get_site_id(), patient, "Electrophysiology", original_id)
        return updated

    def metadata_save_record(
        self,
        table_name: str,
        metadata: dict[str, Any],
        context: dict[str, Any] | None = None,
        local_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        table_name = str(
            table_name or ""
        ).strip()

        metadata = dict(
            metadata or {}
        )

        incoming_patient_id = str(
            metadata.get(
                "CoCANoT Patient ID",
                "",
            )
            or ""
        ).strip()

        if incoming_patient_id:
            resolved_patient_id = (
                self._resolve_existing_patient_id(
                    incoming_patient_id
                )
            )

            if resolved_patient_id:
                metadata[
                    "CoCANoT Patient ID"
                ] = resolved_patient_id

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
        if table_name == "Imaging" and str(clean.get("Imaging Modality") or "").strip() != "MRI":
            # MRI-only dictionary fields may remain from an earlier editor
            # selection; they must not block a valid CT record.
            for key in list(clean):
                if key.startswith("MRI Sequence(s)"):
                    clean.pop(key, None)
        # Preserve links to pre-normalization patient keys until a database migration.
        if clean.get("CoCANoT Patient ID"):
            clean["CoCANoT Patient ID"] = self._resolve_existing_patient_id(clean["CoCANoT Patient ID"])

        exclusive_problems = (
            _exclusive_multiselect_conflicts(
                clean,
                rules,
            )
        )

        if exclusive_problems:
            raise ValueError(
                "\n".join(
                    exclusive_problems[
                        :20
                    ]
                )
            )

        validation_context: dict[str, Any] = {}

        if table_name == "Surgical":
            actual_surgery_date = str(
                (
                    local_context
                    or {}
                ).get(
                    "actual_surgery_date",
                    "",
                )
                or ""
            ).strip()

            if not actual_surgery_date:
                patient_id = str(
                    clean.get(
                        "CoCANoT Patient ID",
                        "",
                    )
                    or ""
                ).strip()
                surgery_id = str(
                    clean.get(
                        "Surgery ID",
                        "",
                    )
                    or ""
                ).strip()

                if patient_id and surgery_id:
                    tracking = (
                        self.metadata_get_real_surgery_date(
                            self.get_site_id(),
                            patient_id,
                            surgery_id,
                        )
                    )
                    actual_surgery_date = str(
                        tracking.get(
                            "real_surgery_date",
                            "",
                        )
                        or ""
                    ).strip()

            validation_context[
                "actual_surgery_date"
            ] = actual_surgery_date

        validation = (
            validator.validate_record(
                table_name,
                clean,
                context=validation_context,
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

        # Do not silently merge or duplicate records whose older IDs
        # would collide with the new canonical format. Migrate them explicitly.
        identifier_field = {
            "Surgical": "Surgery ID",
            "Imaging": "Image ID",
            "Electrophysiology": "Recording ID",
        }[table_name]
        canonical_record_id = str(clean.get(identifier_field, "")).strip()
        for existing in self.repository.records_for_patient(
            self.get_site_id(), clean.get("CoCANoT Patient ID", ""), table_name
        ):
            legacy_id = str(existing.get("record_id", "")).strip()
            if (legacy_id != canonical_record_id
                    and normalize_record_id(table_name, legacy_id) == canonical_record_id):
                raise ValueError(
                    f"Existing {table_name} record {legacy_id} conflicts with "
                    f"{canonical_record_id}. Review and migrate legacy record IDs "
                    "before importing this record to avoid losing associations."
                )

        original_id = str((local_context or {}).get("original_record_id") or "").strip()
        patient_key = clean.get("CoCANoT Patient ID", "")
        if original_id and original_id != canonical_record_id:
            if self.repository.get_record(self.get_site_id(), table_name, canonical_record_id, patient_id=patient_key):
                raise ValueError("Destination record ID already exists; cannot rename.")
        saved_context = dict(context or {})
        if table_name == "Imaging":
            existing_record = self.repository.get_record(
                self.get_site_id(), "Imaging", original_id or canonical_record_id,
                patient_id=clean.get("CoCANoT Patient ID", "")
            )
            if original_id and original_id != canonical_record_id and not existing_record:
                raise ValueError("Original patient record could not be found; rename was cancelled to avoid duplicates.")
            synced = self._sync_edited_imaging_export(clean, existing_record, original_id)
            if synced is not None:
                saved_context.update(synced)
            elif existing_record:
                saved_context = {**dict(existing_record.get("context") or {}), **saved_context}
        if table_name == "Electrophysiology":
            existing_record = self.repository.get_record(
                self.get_site_id(), "Electrophysiology", original_id or canonical_record_id,
                patient_id=clean.get("CoCANoT Patient ID", "")
            )
            if original_id and original_id != canonical_record_id and not existing_record:
                raise ValueError("Original patient record could not be found; rename was cancelled to avoid duplicates.")
            synced = self._sync_edited_ephys_export(clean, existing_record, original_id)
            if synced is not None:
                saved_context.update(synced)
            elif existing_record:
                saved_context = {**dict(existing_record.get("context") or {}), **saved_context}
        saved = self.repository.save_record(
            self.get_site_id(), table_name, clean,
            source="metadata_dashboard", context=saved_context,
        )
        if original_id and original_id != canonical_record_id and table_name in {"Imaging", "Electrophysiology"}:
            RecordDeletionService().delete_metadata_record(self.get_site_id(), patient_key, table_name, original_id)
        return saved

    def metadata_validate_record(
        self,
        table_name: str,
        metadata: dict[str, Any],
        local_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

        _dictionary, rules, validator = (
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

        field_errors: dict[str, str] = {}

        for problem in _exclusive_multiselect_conflicts(
            clean,
            rules,
        ):
            field_name, _, message = problem.partition(":")
            field_errors[
                field_name.strip() or "Metadata"
            ] = (
                message.strip()
                or problem
            )

        validation_context: dict[str, Any] = {}

        if table_name == "Surgical":
            validation_context[
                "actual_surgery_date"
            ] = str(
                (
                    local_context
                    or {}
                ).get(
                    "actual_surgery_date",
                    "",
                )
                or ""
            ).strip()

        validation = validator.validate_record(
            table_name,
            clean,
            context=validation_context,
        )

        for result in validation[
            "results"
        ]:
            if result[
                "status"
            ] not in {
                "invalid",
                "missing_required",
            }:
                continue

            field_errors[
                str(
                    result.get(
                        "field_name",
                        "Metadata",
                    )
                    or "Metadata"
                )
            ] = str(
                result.get(
                    "message",
                    "Needs review.",
                )
                or "Needs review."
            )

        return {
            "ok": not field_errors,
            "field_errors": field_errors,
            "metadata": clean,
        }

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
    def _canonical_patient_id_for_comparison(
        value: Any,
    ) -> str:
        """
        Compare numeric-only patient IDs without leading-zero differences.

        Examples:
        002 == 2
        0007 == 7

        Alphanumeric IDs are preserved apart from surrounding whitespace.
        """
        text = str(
            value
            if value is not None
            else ""
        ).strip()

        if not text:
            return ""

        if text.isdigit():
            return str(
                int(text)
            )

        return text

    def _resolve_existing_patient_id(
        self,
        patient_id: str,
    ) -> str:
        """
        Resolve an uploaded patient ID to the locally stored representation.

        This lets a spreadsheet value such as 2 match an existing patient
        stored as 002, without rewriting the existing database identifier.
        """
        requested = str(
            patient_id or ""
        ).strip()

        if not requested:
            return ""

        target = (
            self._canonical_patient_id_for_comparison(
                requested
            )
        )

        try:
            patient_ids = (
                self.repository.patient_ids_for_site(
                    self.get_site_id()
                )
            )
        except Exception:
            return requested

        exact = next(
            (
                str(value)
                for value in patient_ids
                if str(value).strip()
                == requested
            ),
            None,
        )

        if exact is not None:
            return exact

        equivalent = [
            str(value)
            for value in patient_ids
            if (
                self._canonical_patient_id_for_comparison(
                    value
                )
                == target
            )
        ]

        if len(equivalent) == 1:
            return equivalent[0]

        return normalize_patient_id(requested)

    @staticmethod
    def _comparison_value(
        field_name: str,
        value: Any,
    ) -> Any:
        """
        Normalize values for semantic equality checks only.

        This intentionally does not modify the data that is saved.
        """
        field_name = str(
            field_name or ""
        ).strip()

        if field_name == "CoCANoT Patient ID":
            return CoCANoTAPI._canonical_patient_id_for_comparison(
                value
            )

        if value is None:
            return ""

        if isinstance(
            value,
            (list, tuple, set),
        ):
            normalized = [
                CoCANoTAPI._comparison_value(
                    "",
                    item,
                )
                for item in value
                if str(item).strip()
            ]

            # Multi-select order should not make two assessments different.
            return sorted(
                normalized,
                key=lambda item: str(item),
            )

        if isinstance(
            value,
            bool,
        ):
            return value

        if isinstance(
            value,
            (int, float),
        ):
            if (
                isinstance(value, float)
                and value.is_integer()
            ):
                return str(
                    int(value)
                )

            return str(value)

        text = " ".join(
            str(value)
            .replace("\u00a0", " ")
            .split()
        )

        if not text:
            return ""

        # Excel/openpyxl may give a whole number as "14.0" while the stored
        # metadata contains "14". Treat those as the same for comparison.
        if re.fullmatch(
            r"[+-]?\d+\.0+",
            text,
        ):
            try:
                return str(
                    int(
                        float(text)
                    )
                )
            except ValueError:
                pass

        return text

    def _metadata_comparison_projection(
        self,
        metadata: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Compare only MR-defined, non-system-generated fields.

        This prevents Clinical Assessment ID and other generated values from
        making an otherwise identical upload look changed.
        """
        metadata = _canonicalize_metadata_keys(
            dict(
                metadata or {}
            ),
            rules,
        )

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

            projection[
                field_name
            ] = self._comparison_value(
                field_name,
                value,
            )

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

        resolved_patient_id = (
            self._resolve_existing_patient_id(
                patient_id
            )
        )

        base = {
            "existing_record_id": "",
            "has_changes": True,
            "requires_review": False,
            "immutable": False,
            "import_allowed": True,
            "resolved_patient_id": (
                resolved_patient_id
                if resolved_patient_id
                else patient_id
            ),
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
                _active_dictionary_path()
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
                    resolved_patient_id,
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
                    if key
                    != "CoCANoT Patient ID"
                }

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
                            "difference_status": "Duplicate",
                            "proposed_action": "Skip duplicate",
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

            exact_match = next(
                (
                    pair
                    for pair in projections
                    if {
                        **pair[1],
                        "CoCANoT Patient ID":
                            self._canonical_patient_id_for_comparison(
                                pair[1].get(
                                    "CoCANoT Patient ID",
                                    "",
                                )
                            ),
                    }
                    == {
                        **incoming_projection,
                        "CoCANoT Patient ID":
                            self._canonical_patient_id_for_comparison(
                                incoming_projection.get(
                                    "CoCANoT Patient ID",
                                    "",
                                )
                            ),
                    }
                ),
                None,
            )

            if exact_match is not None:
                record = exact_match[
                    0
                ]
                return {
                    **base,
                    "difference_status": "Duplicate",
                    "proposed_action": "Skip duplicate",
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
                patient_id=resolved_patient_id,
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
                    "Duplicate"
                    if unchanged
                    else "Changed"
                ),
                "proposed_action": (
                    "Skip duplicate"
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

    @staticmethod
    def _batch_validation_problems(
        validation: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return only user-actionable batch validation problems."""
        system_generated_fields = {
            str(rule.get("field_name", "") or "").strip()
            for rule in rules
            if bool(rule.get("system_generated", False))
        }

        problems: list[dict[str, Any]] = []

        for result in validation.get("results", []):
            status = str(result.get("status", "") or "").strip()

            if status not in {
                "invalid",
                "missing_required",
            }:
                continue

            field_name = str(
                result.get("field_name", "") or ""
            ).strip()

            if (
                status == "missing_required"
                and field_name in system_generated_fields
            ):
                continue

            problems.append(
                {
                    "field_name": field_name,
                    "status": status,
                    "message": str(
                        result.get("message", "") or ""
                    ),
                }
            )

        return problems

    def _flag_surgical_batch_duplicates(
        self,
        rows: list[dict[str, Any]],
        rules: list[dict[str, Any]],
    ) -> None:
        """Detect duplicate and conflicting surgery IDs within one upload.

        A repeated row with equivalent metadata is a duplicate; different
        metadata using the same surgery ID is a conflict requiring review.
        Existing stored-record comparisons remain the first check.
        """
        seen: dict[tuple[str, str], tuple[dict[str, Any], int, dict[str, Any]]] = {}
        for row in rows:
            metadata = dict(row.get("metadata") or {})
            patient_id = self._canonical_patient_id_for_comparison(
                metadata.get("CoCANoT Patient ID", "")
            )
            surgery_id = normalize_record_id(
                "Surgical", metadata.get("Surgery ID", "")
            )
            if not patient_id or not surgery_id:
                continue
            key = (patient_id, surgery_id)
            projection = self._metadata_comparison_projection(metadata, rules)
            row_number = int(row.get("row_number") or 0)
            if key not in seen:
                seen[key] = (projection, row_number, row)
                continue

            first_projection, first_number, first_row = seen[key]
            if first_projection == projection:
                row["difference_status"] = "Duplicate"
                row["status"] = "Duplicate"
                row["proposed_action"] = f"Skip duplicate of row {first_number}"
                row["has_changes"] = False
                row["import_allowed"] = False
                row["include"] = False
            else:
                detail = (
                    f"Conflicts with row {first_number}: both use Surgery ID "
                    f"{surgery_id} for the same patient but contain different metadata."
                )
                # Neither conflicting row is safe to import until reviewed.
                first_row["difference_status"] = "Needs Review"
                first_row["status"] = "Needs attention"
                first_row["proposed_action"] = "Resolve conflicting surgery IDs"
                first_row["requires_review"] = True
                first_row["import_allowed"] = False
                first_row["include"] = False
                if not any(
                    item.get("field_name") == "Surgery ID"
                    and "Conflicting Surgery ID" in item.get("message", "")
                    for item in first_row.get("problems", [])
                ):
                    first_row.setdefault("problems", []).append({
                        "field_name": "Surgery ID",
                        "status": "invalid",
                        "message": f"Conflicting Surgery ID {surgery_id} in row {row_number}.",
                    })
                row["difference_status"] = "Needs Review"
                row["status"] = "Needs attention"
                row["proposed_action"] = "Resolve conflicting surgery IDs"
                row["requires_review"] = True
                row["import_allowed"] = False
                row["include"] = False
                row.setdefault("problems", []).append({
                    "field_name": "Surgery ID",
                    "status": "invalid",
                    "message": detail,
                })

    def metadata_batch_choose_file(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        table_name = str(table_name or "").strip()

        if table_name not in {"Clinical", "Surgical"}:
            raise ValueError(
                "Batch import is supported for Clinical and Surgical metadata."
            )

        if self._window is None:
            return {"ok": False, "cancelled": True}

        selected = self._window.create_file_dialog(
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

            uploaded_patient_id = str(
                clean.get(
                    "CoCANoT Patient ID",
                    "",
                )
                or ""
            ).strip()

            resolved_patient_id = (
                self._resolve_existing_patient_id(
                    uploaded_patient_id
                )
            )

            if resolved_patient_id:
                clean[
                    "CoCANoT Patient ID"
                ] = resolved_patient_id

            validation = validator.validate_record(
                table_name,
                clean,
            )
            problems = self._batch_validation_problems(
                validation,
                rules,
            )

            problems.extend(
                {
                    "field_name": problem.split(
                        ":",
                        1,
                    )[0],
                    "status": "invalid",
                    "message": problem.split(
                        ":",
                        1,
                    )[1].strip(),
                }
                for problem in _exclusive_multiselect_conflicts(
                    clean,
                    rules,
                )
            )

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
                    "uploaded_patient_id": uploaded_patient_id,
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

        if table_name == "Surgical":
            self._flag_surgical_batch_duplicates(preview, rules)

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
                ) == "Duplicate"
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

            uploaded_patient_id = str(
                item.get(
                    "uploaded_patient_id",
                    clean.get(
                        "CoCANoT Patient ID",
                        "",
                    ),
                )
                or ""
            ).strip()

            resolved_patient_id = (
                self._resolve_existing_patient_id(
                    str(
                        clean.get(
                            "CoCANoT Patient ID",
                            "",
                        )
                        or ""
                    ).strip()
                )
            )

            if resolved_patient_id:
                clean[
                    "CoCANoT Patient ID"
                ] = resolved_patient_id

            validation = validator.validate_record(
                table_name,
                clean,
            )
            problems = self._batch_validation_problems(
                validation,
                rules,
            )

            problems.extend(
                {
                    "field_name": problem.split(
                        ":",
                        1,
                    )[0],
                    "status": "invalid",
                    "message": problem.split(
                        ":",
                        1,
                    )[1].strip(),
                }
                for problem in _exclusive_multiselect_conflicts(
                    clean,
                    rules,
                )
            )

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
                    "uploaded_patient_id": uploaded_patient_id,
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

        if table_name == "Surgical":
            self._flag_surgical_batch_duplicates(validated, rules)

        return {
            "ok": not any(
                item["problems"]
                for item in validated
                if bool(item.get("include", True))
                and item.get(
                    "difference_status"
                ) != "Duplicate"
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
                ) == "Duplicate"
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
            ) == "Duplicate"
        ]

        included = [
            item
            for item in validated["rows"]
            if bool(item.get("include", True))
            and item.get(
                "difference_status"
            ) != "Duplicate"
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
                    "status": "Skipped - duplicate",
                    "record_id": str(
                        item.get(
                            "existing_record_id",
                            "",
                        )
                        or ""
                    ),
                    "message": (
                        "Duplicate metadata already exists."
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

        if self._window is None:
            return {
                "ok": False,
                "imported": 0,
            }

        selected = self._window.create_file_dialog(
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

    @staticmethod
    def _remove_empty_parent_directories(
        path: Path,
        stop_roots: list[Path],
    ) -> None:
        roots = []
        for root in stop_roots:
            try:
                roots.append(root.expanduser().resolve())
            except OSError:
                roots.append(root.expanduser())

        current = path.parent
        while current and current != current.parent:
            try:
                resolved = current.resolve()
            except OSError:
                resolved = current

            if resolved in roots:
                break

            if roots and not any(
                root == resolved or root in resolved.parents
                for root in roots
            ):
                break

            try:
                current.rmdir()
            except OSError:
                break

            current = current.parent

    def _delete_linked_processed_files(
        self,
        data_links: PatientDataLinkStore,
        patient_id: str,
        table_name: str,
        record_id: str,
    ) -> dict[str, Any]:
        link = data_links.get_link(
            self.get_site_id(),
            patient_id,
            table_name,
            record_id,
        )
        linked = data_links.paths_from_payload(
            link
        )

        derivative_roots = [
            Path(value)
            for value in linked["derivatives_roots"]
        ]
        final_roots = [
            Path(value)
            for value in linked["final_output_roots"]
        ]

        deleted_paths: list[str] = []
        skipped_shared: list[str] = []
        missing_paths: list[str] = []
        errors: list[str] = []

        groups = (
            (
                linked["derivative_paths"],
                derivative_roots,
            ),
            (
                linked["final_paths"],
                final_roots,
            ),
        )

        for values, roots in groups:
            for value in values:
                path = Path(value).expanduser()

                if data_links.path_is_referenced_elsewhere(
                    self.get_site_id(),
                    patient_id,
                    table_name,
                    record_id,
                    path,
                ):
                    skipped_shared.append(
                        _resolve_text(path)
                    )
                    continue

                if not path.exists():
                    missing_paths.append(
                        _resolve_text(path)
                    )
                    continue

                if not path.is_file():
                    errors.append(
                        f"Tracked processed path is not a file: {path}"
                    )
                    continue

                if roots:
                    try:
                        resolved = path.resolve()
                    except OSError:
                        resolved = path

                    allowed = False
                    for root in roots:
                        try:
                            root_resolved = root.expanduser().resolve()
                        except OSError:
                            root_resolved = root.expanduser()

                        if (
                            resolved == root_resolved
                            or root_resolved in resolved.parents
                        ):
                            allowed = True
                            break

                    if not allowed:
                        errors.append(
                            f"Tracked file is outside its recorded output folder: {path}"
                        )
                        continue

                try:
                    path.unlink()
                    deleted_paths.append(
                        _resolve_text(path)
                    )
                    self._remove_empty_parent_directories(
                        path,
                        roots,
                    )
                except OSError as exc:
                    errors.append(
                        f"Could not delete {path}: {exc}"
                    )

        return {
            "deleted_paths": deleted_paths,
            "skipped_shared": skipped_shared,
            "missing_paths": missing_paths,
            "errors": errors,
        }

    def _delete_imaging_workflow_artifacts(
        self,
        record: dict[str, Any] | None,
    ) -> dict[str, list[str]]:
        """
        Remove the complete Imaging workflow footprint for a deleted record.

        When the user chooses "delete record and processed files", this removes:
        - Step 4 review state
        - Step 5 draft state
        - derivative files for the exact reviewed image
        - the matching final BIDS NIfTI and its sidecars from the selected
          final-output folder

        All file deletion is restricted to the currently configured derivatives
        and BIDS output roots (or recorded roots for the same record).
        """
        result = {
            "deleted_paths": [],
            "missing_paths": [],
            "errors": [],
        }

        if not isinstance(record, dict):
            return result

        metadata = record.get(
            "metadata",
            {},
        )
        if not isinstance(metadata, dict):
            metadata = {}

        context = record.get(
            "context",
            {},
        )
        if not isinstance(context, dict):
            context = {}

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
            or record.get(
                "record_id",
                "",
            )
            or ""
        ).strip()

        source_key = str(
            context.get(
                "source_key",
                "",
            )
            or ""
        ).strip()

        stored_nifti = str(
            context.get(
                "nifti_path",
                "",
            )
            or ""
        ).strip()

        config = load_imaging_config()
        stages = self._imaging_stage_paths(
            config
        )

        derivatives_root = (
            config.imaging.derivatives_dir
            .expanduser()
        )
        bids_root = (
            config.imaging.bids_output_dir
            .expanduser()
        )

        try:
            derivatives_root = (
                derivatives_root.resolve()
            )
        except OSError:
            pass

        try:
            bids_root = bids_root.resolve()
        except OSError:
            pass

        # --------------------------------------------------------------
        # 1. Find the exact Step 4 review item for this record.
        # --------------------------------------------------------------
        review_items, review_state_path = (
            self._imaging_review_items()
        )

        target_item = None

        stored_path = None
        if stored_nifti:
            stored_path = Path(
                stored_nifti
            ).expanduser()
            try:
                stored_path = (
                    stored_path.resolve()
                )
            except OSError:
                pass

        for item in review_items:
            item_key = str(
                item.get(
                    "key",
                    "",
                )
                or ""
            ).strip()

            if (
                source_key
                and item_key == source_key
            ):
                target_item = item
                break

            if stored_path is not None:
                for field in (
                    "accepted_defaced_path",
                    "review_defaced_path",
                    "automated_defaced_path",
                    "scrubbed_path",
                    "prepared_path",
                ):
                    candidate_text = str(
                        item.get(
                            field,
                            "",
                        )
                        or ""
                    ).strip()

                    if not candidate_text:
                        continue

                    candidate = Path(
                        candidate_text
                    ).expanduser()

                    try:
                        candidate = (
                            candidate.resolve()
                        )
                    except OSError:
                        pass

                    if candidate == stored_path:
                        target_item = item
                        break

                if target_item is not None:
                    break

        review_key = (
            str(
                target_item.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
            if isinstance(
                target_item,
                dict,
            )
            else source_key
        )

        # --------------------------------------------------------------
        # 2. Remove Step 4 review state and Step 5 draft state.
        # --------------------------------------------------------------
        review_state = self._load_review_state(
            review_state_path
        )

        if review_key:
            review_state.pop(
                review_key,
                None,
            )

        if (
            source_key
            and source_key != review_key
        ):
            review_state.pop(
                source_key,
                None,
            )

        self._save_review_state(
            review_state_path,
            review_state,
        )

        draft_path = stages[
            "bids_drafts"
        ]
        drafts = self._load_imaging_bids_drafts(
            draft_path
        )

        if review_key:
            drafts.pop(
                review_key,
                None,
            )

        if (
            source_key
            and source_key != review_key
        ):
            drafts.pop(
                source_key,
                None,
            )

        self._save_imaging_bids_drafts(
            draft_path,
            drafts,
        )

        # --------------------------------------------------------------
        # Utility: safely delete a file and its directly-associated sidecars,
        # but only when it is under one of the supplied allowed roots.
        # --------------------------------------------------------------
        seen: set[str] = set()

        def under_allowed_root(
            path: Path,
            roots: list[Path],
        ) -> bool:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path

            for root in roots:
                try:
                    root_resolved = (
                        root.expanduser().resolve()
                    )
                except OSError:
                    root_resolved = (
                        root.expanduser()
                    )

                try:
                    resolved.relative_to(
                        root_resolved
                    )
                    return True
                except ValueError:
                    continue

            return False

        def delete_one(
            path: Path,
            roots: list[Path],
        ) -> None:
            path = path.expanduser()

            try:
                resolved = path.resolve()
            except OSError:
                resolved = path

            key = str(
                resolved
            )

            if key in seen:
                return

            seen.add(
                key
            )

            if not under_allowed_root(
                resolved,
                roots,
            ):
                result[
                    "errors"
                ].append(
                    "Refused to delete file outside the selected "
                    f"Imaging output folders: {resolved}"
                )
                return

            if not resolved.exists():
                result[
                    "missing_paths"
                ].append(
                    str(resolved)
                )
                return

            if not resolved.is_file():
                result[
                    "errors"
                ].append(
                    f"Tracked Imaging path is not a file: {resolved}"
                )
                return

            try:
                resolved.unlink()
                result[
                    "deleted_paths"
                ].append(
                    str(resolved)
                )
            except OSError as exc:
                result[
                    "errors"
                ].append(
                    f"Could not delete {resolved}: {exc}"
                )

        # --------------------------------------------------------------
        # 3. Delete the derivative chain for this exact reviewed image.
        # --------------------------------------------------------------
        derivative_paths: list[Path] = []

        if isinstance(
            target_item,
            dict,
        ):
            for field in (
                "accepted_defaced_path",
                "review_defaced_path",
                "automated_defaced_path",
                "scrubbed_path",
                "prepared_path",
            ):
                value = str(
                    target_item.get(
                        field,
                        "",
                    )
                    or ""
                ).strip()

                if value:
                    derivative_paths.append(
                        Path(
                            value
                        )
                    )

        if stored_nifti:
            derivative_paths.append(
                Path(
                    stored_nifti
                )
            )

        for path in derivative_paths:
            if not under_allowed_root(
                path,
                [
                    derivatives_root,
                ],
            ):
                continue

            delete_one(
                path,
                [
                    derivatives_root,
                ],
            )

            # Remove same-base metadata/gradient files in derivatives too.
            base_path = path.expanduser()
            related = []

            sidecar = _matching_json(
                base_path
            )
            if sidecar is not None:
                related.append(
                    sidecar
                )

            related.extend(
                _matching_extra_sidecars(
                    base_path
                )
            )

            cocanot_sidecar = base_path.with_name(
                f"{self._strip_nifti_suffix(base_path)}_cocanot.json"
            )
            if cocanot_sidecar.exists():
                related.append(
                    cocanot_sidecar
                )

            for candidate in related:
                delete_one(
                    candidate,
                    [
                        derivatives_root,
                    ],
                )

        # --------------------------------------------------------------
        # 4. Delete the final BIDS output for this record.
        #
        # Prefer recorded/link paths. If this is an older record without a
        # durable link, locate the BIDS file in the selected output folder by
        # stable CoCANoT Patient ID + Image ID.
        # --------------------------------------------------------------
        final_candidates: list[Path] = []
        final_roots: list[Path] = [
            bids_root,
        ]

        for field in (
            "bids_output_dir",
            "final_output_root",
        ):
            value = str(
                context.get(
                    field,
                    "",
                )
                or ""
            ).strip()

            if value:
                final_roots.append(
                    Path(
                        value
                    ).expanduser()
                )

        for field in (
            "bids_data_path",
            "nifti_bids_path",
            "output_path",
        ):
            value = str(
                context.get(
                    field,
                    "",
                )
                or ""
            ).strip()

            if value:
                final_candidates.append(
                    Path(
                        value
                    ).expanduser()
                )

        for value in (
            context.get(
                "final_paths",
                [],
            )
            or []
        ):
            value_text = str(
                value or ""
            ).strip()
            if value_text:
                final_candidates.append(
                    Path(
                        value_text
                    ).expanduser()
                )

        data_links = PatientDataLinkStore()

        if patient_id and image_id:
            link = data_links.get_link(
                self.get_site_id(),
                patient_id,
                "Imaging",
                image_id,
            )

            if isinstance(
                link,
                dict,
            ) and link:
                linked = (
                    data_links.paths_from_payload(
                        link
                    )
                )

                final_candidates.extend(
                    Path(value).expanduser()
                    for value in linked.get(
                        "final_paths",
                        [],
                    )
                    if str(value).strip()
                )

                final_roots.extend(
                    Path(value).expanduser()
                    for value in linked.get(
                        "final_output_roots",
                        [],
                    )
                    if str(value).strip()
                )

        # Legacy recovery: scan the selected BIDS output folder and match this
        # exact patient/image identity.
        if (
            patient_id
            and image_id
            and bids_root.exists()
        ):
            try:
                bids_index = (
                    self._index_existing_bids(
                        bids_root
                    )
                )
                matched = (
                    self._existing_bids_export_by_identity(
                        bids_index,
                        patient_id,
                        image_id,
                    )
                )
            except Exception:
                matched = None

            if isinstance(
                matched,
                dict,
            ):
                matched_nifti = str(
                    matched.get(
                        "nifti_path",
                        "",
                    )
                    or ""
                ).strip()

                if matched_nifti:
                    final_candidates.append(
                        Path(
                            matched_nifti
                        )
                    )

        # Delete each final NIfTI and all same-base BIDS sidecars.
        for path in final_candidates:
            if not _is_nifti(
                path
            ):
                continue

            allowed_roots = [
                root
                for root in final_roots
                if str(root).strip()
            ]

            if not under_allowed_root(
                path,
                allowed_roots,
            ):
                continue

            delete_one(
                path,
                allowed_roots,
            )

            base_path = path.expanduser()

            sidecar = _matching_json(
                base_path
            )
            if sidecar is not None:
                delete_one(
                    sidecar,
                    allowed_roots,
                )

            for candidate in (
                _matching_extra_sidecars(
                    base_path
                )
            ):
                delete_one(
                    candidate,
                    allowed_roots,
                )

            cocanot_sidecar = base_path.with_name(
                f"{self._strip_nifti_suffix(base_path)}_cocanot.json"
            )
            if cocanot_sidecar.exists():
                delete_one(
                    cocanot_sidecar,
                    allowed_roots,
                )

        # --------------------------------------------------------------
        # 5. Remove empty per-image/per-session directories, but never remove
        # the selected output roots themselves.
        # --------------------------------------------------------------
        for deleted_text in list(
            result[
                "deleted_paths"
            ]
        ):
            deleted_path = Path(
                deleted_text
            )

            roots = (
                [
                    derivatives_root,
                ]
                if under_allowed_root(
                    deleted_path,
                    [
                        derivatives_root,
                    ],
                )
                else final_roots
            )

            try:
                self._remove_empty_parent_directories(
                    deleted_path,
                    roots,
                )
            except Exception:
                pass

        # Recalculate workflow state after the source was intentionally removed.
        try:
            self._refresh_imaging_review_stage()
        except Exception:
            pass

        self.imaging_stage_state[
            "metadata_bids"
        ] = "not_started"

        try:
            self._save_imaging_pipeline_state(
                config
            )
        except Exception:
            pass

        return result

    def metadata_delete_records(
        self,
        table_name: str,
        patient_id: str,
        record_ids: list[str],
        delete_processed_files: bool = False,
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
                "file_cleanup": {
                    "deleted_count": 0,
                    "skipped_shared_count": 0,
                    "missing_count": 0,
                },
            }

        deletion = RecordDeletionService()
        data_links = PatientDataLinkStore()

        deleted: list[str] = []
        blocked: list[dict[str, str]] = []
        cleanup_deleted: list[str] = []
        cleanup_shared: list[str] = []
        cleanup_missing: list[str] = []

        for record_id in record_ids:
            existing_record = None

            if table_name in {
                "Imaging",
                "Electrophysiology",
                "Surgical",
            }:
                existing_record = self.repository.get_record(
                    self.get_site_id(),
                    table_name,
                    record_id,
                    patient_id=patient_id,
                )

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

            if (
                delete_processed_files
                and table_name in {
                    "Imaging",
                    "Electrophysiology",
                }
            ):
                cleanup = self._delete_linked_processed_files(
                    data_links,
                    patient_id,
                    table_name,
                    record_id,
                )
                cleanup_deleted.extend(
                    cleanup["deleted_paths"]
                )
                cleanup_shared.extend(
                    cleanup["skipped_shared"]
                )
                cleanup_missing.extend(
                    cleanup["missing_paths"]
                )

                if cleanup["errors"]:
                    blocked.append(
                        {
                            "record_id": record_id,
                            "reason": "; ".join(
                                cleanup["errors"][:3]
                            ),
                        }
                    )
                    continue

                if table_name == "Imaging":
                    workflow_cleanup = (
                        self._delete_imaging_workflow_artifacts(
                            existing_record
                        )
                    )
                    cleanup_deleted.extend(
                        workflow_cleanup[
                            "deleted_paths"
                        ]
                    )
                    cleanup_missing.extend(
                        workflow_cleanup[
                            "missing_paths"
                        ]
                    )

                    if workflow_cleanup[
                        "errors"
                    ]:
                        blocked.append(
                            {
                                "record_id": record_id,
                                "reason": "; ".join(
                                    workflow_cleanup[
                                        "errors"
                                    ][:3]
                                ),
                            }
                        )
                        continue

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

            if table_name == "Surgical":
                self._delete_real_surgery_date(
                    self.get_site_id(),
                    patient_id,
                    record_id,
                )

            deleted.append(
                record_id
            )

        return {
            "deleted": deleted,
            "blocked": blocked,
            "file_cleanup": {
                "deleted_count": len(
                    cleanup_deleted
                ),
                "skipped_shared_count": len(
                    cleanup_shared
                ),
                "missing_count": len(
                    cleanup_missing
                ),
            },
        }

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
        on_complete: Callable[[int], None] | None = None,
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
                on_complete,
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
        on_complete: Callable[[int], None] | None = None,
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

        # Report the final outcome only after post-processing verification.
        # A process returning zero is not necessarily a valid final export.

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
                return_code = 1

        message = (
            f"{description} completed and verified."
            if return_code == 0
            else f"{description} FAILED (exit code {return_code}). Check the processing log; no completed export was confirmed."
        )

        if on_complete is not None:
            try:
                on_complete(
                    return_code
                )
            except Exception as exc:
                if workflow == "ephys":
                    self._ephys_log(
                        f"Process completion callback failed: {exc}"
                    )
                else:
                    self._imaging_log(
                        f"Process completion callback failed: {exc}"
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

    api._window = window

    try:
        webview.start(debug=False)
    finally:
        server.shutdown()
        server.server_close()

if __name__ == "__main__":
    main()
