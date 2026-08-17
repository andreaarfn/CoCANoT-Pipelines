#!/usr/bin/env python3
"""
Local EDF review interface.

This app compares each raw EDF with its matching scrubbed EDF and shows:
- the complete main EDF header, raw versus scrubbed
- all raw EDF+ annotations
- all scrubbed EDF+ annotations

The scrubbed header and scrubbed annotations can be edited and saved.
The raw EDF is always read-only.

The app binds only to 127.0.0.1 and is intended for local review of files
that may contain protected health information.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import tempfile
import threading
import webbrowser
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError as exc:
    raise SystemExit(
        "Flask is required. Install it with:\n\n"
        "    python -m pip install flask\n"
    ) from exc

try:
    import pyedflib
except ImportError as exc:
    raise SystemExit(
        "PyEDFlib is required. Install it with:\n\n"
        "    python -m pip install pyedflib\n"
    ) from exc


EDITABLE_HEADER_FIELDS = (
    "technician",
    "recording_additional",
    "patientname",
    "patient_additional",
    "patientcode",
    "equipment",
    "admincode",
    "sex",
    "birthdate",
    "startdate",
)


def scrubbed_filename(raw_path: Path) -> str:
    if raw_path.name.lower().endswith(".edf"):
        return raw_path.name[:-4] + "_scrubbed.edf"
    return raw_path.stem + "_scrubbed.edf"


def find_edf_files(input_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() == ".edf"
        and not path.name.lower().endswith("_scrubbed.edf")
    )


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): normalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_value(v) for v in value]
    return str(value)


def annotation_rows(reader: pyedflib.EdfReader) -> list[dict[str, Any]]:
    try:
        onsets, durations, descriptions = reader.readAnnotations()
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for onset, duration, description in zip(onsets, durations, descriptions):
        rows.append(
            {
                "onset": float(onset),
                "duration": float(duration),
                "description": str(description),
            }
        )
    return rows


def read_review_data(edf_path: Path) -> dict[str, Any]:
    reader = pyedflib.EdfReader(str(edf_path))
    try:
        return {
            "path": str(edf_path),
            "header": normalize_value(reader.getHeader()),
            "annotations": annotation_rows(reader),
            "annotation_count": int(reader.annotations_in_file),
            "signals_in_file": int(reader.signals_in_file),
            "file_duration_seconds": float(reader.file_duration),
            "signal_headers": normalize_value(reader.getSignalHeaders()),
        }
    finally:
        reader.close()


def parse_datetime(value: Any, field_name: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must use ISO format, for example 2000-01-01T00:00:00."
        ) from exc


def parse_birthdate(value: Any) -> date | str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError("birthdate must use YYYY-MM-DD or be empty.") from exc


def clean_header_for_writer(original_header: dict[str, Any], edited: dict[str, Any]) -> dict[str, Any]:
    header = copy.deepcopy(original_header)

    for field in EDITABLE_HEADER_FIELDS:
        if field in edited:
            header[field] = edited[field]

    header["startdate"] = parse_datetime(header.get("startdate"), "startdate") or datetime(2000, 1, 1)
    header["birthdate"] = parse_birthdate(header.get("birthdate"))

    for field in (
        "technician",
        "recording_additional",
        "patientname",
        "patient_additional",
        "patientcode",
        "equipment",
        "admincode",
        "sex",
    ):
        value = header.get(field)
        header[field] = "" if value is None else str(value)

    # PyEDFlib's high-level reader may attach annotations to the header.
    # We write annotations explicitly below instead.
    header.pop("annotations", None)
    return header


def validate_annotations(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("annotations must be a JSON list.")

    cleaned: list[dict[str, Any]] = []
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Annotation {index} must be an object.")
        try:
            onset = float(row.get("onset", 0))
            duration = float(row.get("duration", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Annotation {index} has an invalid onset or duration.") from exc

        description = str(row.get("description", ""))
        cleaned.append(
            {
                "onset": onset,
                "duration": duration,
                "description": description,
            }
        )
    return cleaned


def rewrite_scrubbed_edf(
    edf_path: Path,
    edited_header: dict[str, Any],
    edited_annotations: list[dict[str, Any]],
) -> None:
    """Atomically rewrite only the scrubbed EDF while preserving digital signals."""
    reader = pyedflib.EdfReader(str(edf_path))
    try:
        original_header = reader.getHeader()
        signal_headers = reader.getSignalHeaders()
        signals = [
            reader.readSignal(channel_index, digital=True)
            for channel_index in range(reader.signals_in_file)
        ]
        file_type = int(reader.filetype)
        datarecord_duration = float(reader.datarecord_duration)
    finally:
        reader.close()

    header = clean_header_for_writer(original_header, edited_header)
    annotations = validate_annotations(edited_annotations)

    temp_handle = tempfile.NamedTemporaryFile(
        suffix=edf_path.suffix,
        prefix=f".{edf_path.stem}_editing_",
        dir=edf_path.parent,
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()

    try:
        writer = pyedflib.EdfWriter(
            str(temp_path),
            n_channels=len(signal_headers),
            file_type=file_type,
        )
        try:
            writer.setSignalHeaders(signal_headers)
            writer.setHeader(header)

            # Preserve the original EDF data-record duration.
            # PyEDFlib expects this value in seconds and accepts 0.001 to 60 seconds.
            if 0.001 <= datarecord_duration <= 60:
                writer.setDatarecordDuration(datarecord_duration)
            else:
                raise ValueError(
                    "Invalid EDF data-record duration "
                    f"{datarecord_duration!r} seconds; expected 0.001 to 60 seconds."
                )

            writer.writeSamples(signals, digital=True)
            for row in annotations:
                writer.writeAnnotation(
                    row["onset"],
                    row["duration"],
                    row["description"],
                )
        finally:
            writer.close()

        # Verify that the replacement can be opened before installing it.
        verification = pyedflib.EdfReader(str(temp_path))
        try:
            if verification.signals_in_file != len(signal_headers):
                raise RuntimeError("Channel count changed during save.")
        finally:
            verification.close()

        os.replace(temp_path, edf_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


PAGE_TEMPLATE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDF Header and Annotation Review</title>
<style>
:root { font-family: Arial, sans-serif; color: #1f2933; background: #f6f7f9; }
* { box-sizing: border-box; }
body { margin: 0; }
.layout { display: grid; grid-template-columns: 270px minmax(0, 1fr); min-height: 100vh; }
aside { position: sticky; top: 0; height: 100vh; overflow-y: auto; padding: 18px 12px; background: #17212b; color: white; }
aside h1 { margin: 0 8px 16px; font-size: 18px; }
.patient-link { display: block; width: 100%; margin: 3px 0; padding: 10px; border: 0; border-radius: 6px; color: #dce5ed; background: transparent; text-align: left; cursor: pointer; overflow-wrap: anywhere; }
.patient-link:hover, .patient-link.active { background: #2a3a49; color: white; }
main { padding: 24px; overflow: hidden; }
.notice { margin-bottom: 18px; padding: 12px 14px; border-left: 4px solid #b7791f; background: #fff8dc; }
.file-title { margin: 0; font-size: 22px; overflow-wrap: anywhere; }
.paths { margin: 8px 0 20px; color: #586675; font-size: 13px; overflow-wrap: anywhere; }
section { margin: 18px 0; padding: 18px; border: 1px solid #d9dee5; border-radius: 9px; background: white; }
h2 { margin: 0 0 12px; font-size: 17px; }
.comparison { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 14px; }
.panel h3 { margin: 0 0 8px; font-size: 14px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px; border: 1px solid #d9dee5; vertical-align: top; text-align: left; overflow-wrap: anywhere; }
th { background: #f1f3f5; }
.changed { background: #fff8d8; }
input, textarea { width: 100%; padding: 7px; border: 1px solid #c9d0d8; border-radius: 4px; font: inherit; }
textarea { min-height: 58px; resize: vertical; }
.readonly { white-space: pre-wrap; }
.annotation-table input { min-width: 90px; }
.annotation-table textarea { min-width: 220px; min-height: 48px; }
.toolbar { position: sticky; bottom: 0; display: flex; align-items: center; gap: 12px; margin-top: 18px; padding: 12px; border: 1px solid #d9dee5; border-radius: 8px; background: rgba(255,255,255,.96); }
button.action { padding: 9px 14px; border: 0; border-radius: 6px; background: #1f5f99; color: white; cursor: pointer; }
button.secondary { background: #667786; }
button.remove { border: 0; background: transparent; color: #a61b1b; cursor: pointer; }
#message { font-size: 13px; }
.empty { padding: 14px; color: #647180; background: #f7f8fa; border-radius: 6px; }
.error { color: #9b1c1c; }
@media (max-width: 850px) {
  .layout { grid-template-columns: 1fr; }
  aside { position: static; height: auto; max-height: 230px; }
  .comparison { grid-template-columns: 1fr; }
  main { padding: 14px; }
}
</style>
</head>
<body>
<div class="layout">
  <aside>
    <h1>Patients / EDF files</h1>
    <div id="patient-list"></div>
  </aside>
  <main>
    <div class="notice"><strong>Local PHI review:</strong> raw headers and annotation text may contain identifying information. This app is available only on this computer.</div>
    <div id="content"><div class="empty">Select a file from the side menu.</div></div>
  </main>
</div>
<script>
const files = {{ files_json | safe }};
let currentId = null;
let currentData = null;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function valueText(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function buildMenu() {
  const list = document.getElementById('patient-list');
  list.innerHTML = files.map(file => `
    <button class="patient-link" data-id="${file.id}" onclick="loadFile(${file.id})">
      ${esc(file.label)}
    </button>`).join('');
}

function markActive(id) {
  document.querySelectorAll('.patient-link').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.id) === id);
  });
}

function headerRows(rawHeader, scrubbedHeader) {
  const keys = [...new Set([...Object.keys(rawHeader || {}), ...Object.keys(scrubbedHeader || {})])].sort();
  return keys.map(key => {
    const raw = valueText(rawHeader?.[key]);
    const scrubbed = valueText(scrubbedHeader?.[key]);
    const changed = raw !== scrubbed ? 'changed' : '';
    const editable = {{ editable_fields_json | safe }}.includes(key);
    const scrubbedCell = editable
      ? `<textarea data-header-field="${esc(key)}">${esc(scrubbed)}</textarea>`
      : `<div class="readonly">${esc(scrubbed)}</div>`;
    return `<tr class="${changed}"><th>${esc(key)}</th><td class="readonly">${esc(raw)}</td><td>${scrubbedCell}</td></tr>`;
  }).join('');
}

function readonlyAnnotations(rows) {
  if (!rows.length) return '<div class="empty">No annotations detected.</div>';
  return `<div class="table-wrap"><table><thead><tr><th>#</th><th>Onset</th><th>Duration</th><th>Description</th></tr></thead><tbody>${rows.map((row, i) => `
    <tr><td>${i + 1}</td><td>${esc(row.onset)}</td><td>${esc(row.duration)}</td><td class="readonly">${esc(row.description)}</td></tr>`).join('')}</tbody></table></div>`;
}

function editableAnnotations(rows) {
  if (!rows.length) return '<div class="empty" id="empty-scrubbed-annotations">No annotations detected in the scrubbed EDF.</div><tbody id="scrubbed-annotation-body"></tbody>';
  return `<div class="table-wrap"><table class="annotation-table"><thead><tr><th>Onset</th><th>Duration</th><th>Description</th><th></th></tr></thead><tbody id="scrubbed-annotation-body">${rows.map(annotationRow).join('')}</tbody></table></div>`;
}

function annotationRow(row = {onset: 0, duration: 0, description: ''}) {
  return `<tr>
    <td><input data-ann="onset" type="number" step="any" value="${esc(row.onset)}"></td>
    <td><input data-ann="duration" type="number" step="any" value="${esc(row.duration)}"></td>
    <td><textarea data-ann="description">${esc(row.description)}</textarea></td>
    <td><button class="remove" onclick="this.closest('tr').remove()">Remove</button></td>
  </tr>`;
}

function addAnnotation() {
  const empty = document.getElementById('empty-scrubbed-annotations');
  if (empty) {
    empty.outerHTML = '<div class="table-wrap"><table class="annotation-table"><thead><tr><th>Onset</th><th>Duration</th><th>Description</th><th></th></tr></thead><tbody id="scrubbed-annotation-body"></tbody></table></div>';
  }
  document.getElementById('scrubbed-annotation-body').insertAdjacentHTML('beforeend', annotationRow());
}

async function loadFile(id) {
  currentId = id;
  markActive(id);
  document.getElementById('content').innerHTML = '<div class="empty">Loading…</div>';
  const response = await fetch(`/api/file/${id}`);
  const data = await response.json();
  if (!response.ok) {
    document.getElementById('content').innerHTML = `<div class="error">${esc(data.error || 'Could not load file.')}</div>`;
    return;
  }
  currentData = data;
  renderFile(data);
}

function renderFile(data) {
  const raw = data.raw;
  const scrubbed = data.scrubbed;
  document.getElementById('content').innerHTML = `
    <h1 class="file-title">${esc(data.label)}</h1>
    <div class="paths"><div><strong>Raw:</strong> ${esc(raw.path)}</div><div><strong>Scrubbed:</strong> ${esc(scrubbed.path)}</div></div>

    <section>
      <h2>Complete EDF header</h2>
      <div class="table-wrap"><table><thead><tr><th>Field</th><th>Raw EDF</th><th>Scrubbed EDF</th></tr></thead><tbody>${headerRows(raw.header, scrubbed.header)}</tbody></table></div>
    </section>

    <section>
      <h2>Annotations</h2>
      <div class="comparison">
        <div class="panel"><h3>Raw EDF — ${raw.annotations.length}</h3>${readonlyAnnotations(raw.annotations)}</div>
        <div class="panel"><h3>Scrubbed EDF — ${scrubbed.annotations.length}</h3>${editableAnnotations(scrubbed.annotations)}<p><button class="action secondary" onclick="addAnnotation()">Add annotation</button></p></div>
      </div>
    </section>

    <div class="toolbar"><button class="action" onclick="saveFile()">Save scrubbed EDF</button><span id="message"></span></div>`;
}

function collectAnnotations() {
  const body = document.getElementById('scrubbed-annotation-body');
  if (!body) return [];
  return [...body.querySelectorAll('tr')].map(row => ({
    onset: Number(row.querySelector('[data-ann="onset"]').value),
    duration: Number(row.querySelector('[data-ann="duration"]').value),
    description: row.querySelector('[data-ann="description"]').value,
  }));
}

async function saveFile() {
  const message = document.getElementById('message');
  message.textContent = 'Saving…';
  message.className = '';

  const header = {...currentData.scrubbed.header};
  document.querySelectorAll('[data-header-field]').forEach(field => {
    header[field.dataset.headerField] = field.value;
  });

  const response = await fetch(`/api/file/${currentId}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({header, annotations: collectAnnotations()}),
  });
  const result = await response.json();
  if (!response.ok) {
    message.textContent = result.error || 'Save failed.';
    message.className = 'error';
    return;
  }
  message.textContent = 'Saved.';
  await loadFile(currentId);
}

buildMenu();
if (files.length) loadFile(files[0].id);
</script>
</body>
</html>
"""


def create_app(input_dir: Path, scrubbed_dir: Path) -> Flask:
    app = Flask(__name__)

    pairs: list[dict[str, Any]] = []
    for raw_path in find_edf_files(input_dir):
        relative_path = raw_path.relative_to(input_dir)
        scrubbed_path = scrubbed_dir / relative_path.parent / scrubbed_filename(raw_path)
        if scrubbed_path.exists():
            pairs.append(
                {
                    "id": len(pairs),
                    "label": str(relative_path),
                    "raw_path": raw_path.resolve(),
                    "scrubbed_path": scrubbed_path.resolve(),
                }
            )

    @app.get("/")
    def index():
        menu = [{"id": p["id"], "label": p["label"]} for p in pairs]
        return render_template_string(
            PAGE_TEMPLATE,
            files_json=json.dumps(menu),
            editable_fields_json=json.dumps(list(EDITABLE_HEADER_FIELDS)),
        )

    def get_pair(file_id: int) -> dict[str, Any]:
        if file_id < 0 or file_id >= len(pairs):
            raise KeyError("Unknown file.")
        return pairs[file_id]

    @app.get("/api/file/<int:file_id>")
    def get_file(file_id: int):
        try:
            pair = get_pair(file_id)
            return jsonify(
                {
                    "id": file_id,
                    "label": pair["label"],
                    "raw": read_review_data(pair["raw_path"]),
                    "scrubbed": read_review_data(pair["scrubbed_path"]),
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.post("/api/file/<int:file_id>")
    def save_file(file_id: int):
        try:
            pair = get_pair(file_id)
            payload = request.get_json(force=True)
            header = payload.get("header")
            annotations = payload.get("annotations", [])
            if not isinstance(header, dict):
                raise ValueError("header must be an object.")
            rewrite_scrubbed_edf(pair["scrubbed_path"], header, annotations)
            return jsonify({"saved": True})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    app.config["EDF_PAIR_COUNT"] = len(pairs)
    return app


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    pipeline_dir = script_dir.parent

    parser = argparse.ArgumentParser(
        description="Open a local interface for comparing and editing scrubbed EDF headers and annotations."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=pipeline_dir / "sample_data",
        help="Folder containing raw EDF files. Default: sample_data/",
    )
    parser.add_argument(
        "--scrubbed-dir",
        type=Path,
        default=pipeline_dir / "derivatives" / "scrubbed",
        help="Folder containing scrubbed EDF files. Default: derivatives/scrubbed/",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    scrubbed_dir = args.scrubbed_dir.resolve()

    if not input_dir.is_dir():
        raise SystemExit(f"Raw EDF folder does not exist: {input_dir}")
    if not scrubbed_dir.is_dir():
        raise SystemExit(f"Scrubbed EDF folder does not exist: {scrubbed_dir}")

    app = create_app(input_dir, scrubbed_dir)
    pair_count = app.config["EDF_PAIR_COUNT"]
    if pair_count == 0:
        raise SystemExit("No matching raw and scrubbed EDF pairs were found.")

    url = f"http://127.0.0.1:{args.port}"
    print(f"Found {pair_count} EDF pair(s).")
    print(f"Opening local review interface: {url}")
    print("Press Ctrl+C in this terminal when finished.")

    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
