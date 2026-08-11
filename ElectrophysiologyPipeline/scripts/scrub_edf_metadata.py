#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
from datetime import date, datetime
import json
import os
import tempfile

import pyedflib


DUMMY_STARTDATE = datetime(2000, 1, 1, 0, 0, 0)


SENSITIVE_HEADER_FIELDS = (
    "technician",
    "recording_additional",
    "patientname",
    "patient_additional",
    "patientcode",
    "equipment",
    "admincode",
    "birthdate",
)


class EDFScrubbingError(RuntimeError):
    """Raised when an EDF file cannot be safely scrubbed or verified."""


def scrubbed_filename(input_path: Path) -> str:
    """Return the filename used for the scrubbed EDF."""
    if input_path.name.lower().endswith(".edf"):
        return input_path.name[:-4] + "_scrubbed.edf"

    return input_path.stem + "_scrubbed.edf"


def sidecar_path(output_path: Path) -> Path:
    """Return the JSON sidecar path for a scrubbed EDF."""
    return output_path.with_suffix(".json")


def find_edf_files(input_dir: Path) -> list[Path]:
    """
    Recursively find EDF files.

    Existing scrubbed EDF files are ignored so they are not scrubbed again.
    """
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() == ".edf"
        and not path.name.lower().endswith("_scrubbed.edf")
    )


def normalize_text(value: Any) -> str:
    """Convert a value to stripped text."""
    if value is None:
        return ""

    return str(value).strip()


def normalize_sex(value: Any) -> str:
    """
    Normalize sex values.

    Returns a compact de-identified value or an empty string.
    """
    text = normalize_text(value).lower()

    if not text:
        return ""

    mapping = {
        "m": "Male",
        "male": "Male",
        "1": "Male",
        "f": "Female",
        "female": "Female",
        "0": "Female",
        "other": "O",
        "unknown": "Unknown",
        "nonbinary": "Non-Binary",
    }

    return mapping.get(text, "X")


def parse_birthdate(value: Any) -> date | None:
    """
    Parse common EDF birthdate representations.

    The birthdate is used temporarily to calculate age. It is never written
    to the scrubbed EDF or JSON sidecar.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = normalize_text(value)

    if not text:
        return None

    supported_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d-%b-%Y",
        "%d %B %Y",
    )

    for date_format in supported_formats:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue

    return None


def calculate_age(
    birthdate_value: Any,
    recording_start: datetime | date | None,
) -> int | None:
    """
    Calculate age at the time of recording.

    Implausible ages are discarded.
    """
    birthdate = parse_birthdate(birthdate_value)

    if birthdate is None or recording_start is None:
        return None

    if isinstance(recording_start, datetime):
        recording_date = recording_start.date()
    else:
        recording_date = recording_start

    if birthdate > recording_date:
        return None

    age = recording_date.year - birthdate.year

    if (recording_date.month, recording_date.day) < (
        birthdate.month,
        birthdate.day,
    ):
        age -= 1

    if age < 0 or age > 125:
        return None

    return age


def clean_single_line(value: Any) -> str:
    """
    Normalize a technical text value into one line.

    This is used only for non-patient technical fields.
    """
    return " ".join(normalize_text(value).split())


def build_signal_headers(
    reader: pyedflib.EdfReader,
) -> list[dict[str, Any]]:
    """
    Build clean signal headers using an explicit allowlist.

    Retained:
        - channel label
        - physical dimension
        - sample frequency
        - physical and digital ranges

    Removed:
        - transducer information
        - prefilter free text

    Transducer and prefilter fields are removed because vendors may place
    arbitrary free text in those fields.
    """
    signal_headers: list[dict[str, Any]] = []

    for index in range(reader.signals_in_file):
        signal_headers.append(
            {
                "label": clean_single_line(reader.getLabel(index)),
                "dimension": clean_single_line(
                    reader.getPhysicalDimension(index)
                ),
                "sample_frequency": reader.getSampleFrequency(index),
                "physical_min": reader.getPhysicalMinimum(index),
                "physical_max": reader.getPhysicalMaximum(index),
                "digital_min": reader.getDigitalMinimum(index),
                "digital_max": reader.getDigitalMaximum(index),
                "transducer": "",
                "prefilter": "",
            }
        )

    return signal_headers


def count_annotations(reader: pyedflib.EdfReader) -> int:
    """
    Count source annotations without logging or retaining their descriptions.
    """
    try:
        annotation_onsets, _, _ = reader.readAnnotations()
        return len(annotation_onsets)
    except Exception:
        return 0


def read_source_edf(input_path: Path) -> dict[str, Any]:
    """
    Read signals and approved technical information from an EDF.

    Annotation text is never returned or printed.
    """
    try:
        reader = pyedflib.EdfReader(str(input_path))
    except Exception as exc:
        raise EDFScrubbingError(
            f"Could not open EDF file: {input_path}"
        ) from exc

    try:
        channel_count = reader.signals_in_file

        if channel_count <= 0:
            raise EDFScrubbingError(
                f"EDF contains no signal channels: {input_path}"
            )

        original_header = reader.getHeader()

        startdate = original_header.get("startdate")
        birthdate = original_header.get("birthdate")

        age = calculate_age(birthdate, startdate)
        sex = normalize_sex(original_header.get("sex"))

        signals = [
            reader.readSignal(channel_index)
            for channel_index in range(channel_count)
        ]

        return {
            "channel_count": channel_count,
            "signals": signals,
            "signal_headers": build_signal_headers(reader),
            "datarecord_duration": float(reader.datarecord_duration),
            "recording_duration_seconds": float(reader.file_duration),
            "annotation_count_removed": count_annotations(reader),
            "age": age,
            "sex": sex or None,
        }

    finally:
        reader.close()


def build_scrubbed_header() -> dict[str, Any]:
    """
    Construct a minimal EDF header.

    Nothing from the source EDF header is copied into these fields.
    """
    return {
        "technician": "",
        "recording_additional": "",
        "patientname": "",
        "patient_additional": "",
        "patientcode": "",
        "equipment": "",
        "admincode": "",
        "sex": "",
        "birthdate": "",
        "startdate": DUMMY_STARTDATE,
    }


def write_scrubbed_edf(
    output_path: Path,
    source_data: dict[str, Any],
) -> None:
    """
    Write the scrubbed EDF.

    No annotations are written. PyEDFlib creates any EDF+ structural timing
    information required by the output format.
    """
    writer = pyedflib.EdfWriter(
        str(output_path),
        n_channels=source_data["channel_count"],
        file_type=pyedflib.FILETYPE_EDFPLUS,
    )

    try:
        writer.setDatarecordDuration(
            source_data["datarecord_duration"]
        )
        writer.setSignalHeaders(source_data["signal_headers"])
        writer.setHeader(build_scrubbed_header())
        writer.writeSamples(source_data["signals"])

        # Deliberately do not call writer.writeAnnotation().
        # Every original annotation is therefore removed.

    finally:
        writer.close()


def header_value_is_empty(value: Any) -> bool:
    """
    Determine whether a header value is effectively empty.

    Some EDF readers represent blank values as empty strings, None, or spaces.
    """
    if value is None:
        return True

    return not normalize_text(value)


def verify_scrubbed_edf(
    output_path: Path,
    expected_channel_count: int,
) -> None:
    """
    Verify output validity, header scrubbing, and annotation removal.
    """
    try:
        reader = pyedflib.EdfReader(str(output_path))
    except Exception as exc:
        raise EDFScrubbingError(
            f"Scrubbed EDF failed to open: {output_path}"
        ) from exc

    try:
        if reader.signals_in_file != expected_channel_count:
            raise EDFScrubbingError(
                "Channel-count verification failed for "
                f"{output_path}: expected {expected_channel_count}, "
                f"found {reader.signals_in_file}."
            )

        if reader.file_duration <= 0:
            raise EDFScrubbingError(
                f"Scrubbed EDF has an invalid duration: {output_path}"
            )

        output_header = reader.getHeader()

        patient_name = normalize_text(
            output_header.get("patientname")
        )
        patient_code = normalize_text(
            output_header.get("patientcode")
        )

        if patient_name not in {"", "X"}:
            raise EDFScrubbingError(
                f"Patient name was not scrubbed: {output_path}"
            )

        if patient_code not in {"", "X"}:
            raise EDFScrubbingError(
                f"Patient code was not scrubbed: {output_path}"
            )

        for field_name in SENSITIVE_HEADER_FIELDS:
            if field_name in {"patientname", "patientcode"}:
                continue

            field_value = output_header.get(field_name)

            if not header_value_is_empty(field_value):
                raise EDFScrubbingError(
                    f"Sensitive EDF header field {field_name!r} "
                    f"was not cleared in {output_path}."
                )

        annotation_total = count_annotations(reader)

        if annotation_total != 0:
            raise EDFScrubbingError(
                f"Annotation removal failed for {output_path}: "
                f"{annotation_total} annotation(s) remain."
            )

        for channel_index in range(reader.signals_in_file):
            transducer = normalize_text(
                reader.getTransducer(channel_index)
            )
            prefilter = normalize_text(
                reader.getPrefilter(channel_index)
            )

            if transducer:
                raise EDFScrubbingError(
                    "Signal transducer metadata was not cleared for "
                    f"channel {channel_index + 1} in {output_path}."
                )

            if prefilter:
                raise EDFScrubbingError(
                    "Signal prefilter metadata was not cleared for "
                    f"channel {channel_index + 1} in {output_path}."
                )

    finally:
        reader.close()


def build_sidecar_data(source_data: dict[str, Any]) -> dict[str, Any]:
    """
    Build a minimal non-PHI recording metadata sidecar.

    This sidecar intentionally does not contain source filenames, original
    header values, dates, annotation descriptions, patient identifiers, or
    internal deidentification audit information.
    """
    duration_minutes = round(
        source_data["recording_duration_seconds"] / 60.0,
        6,
    )

    return {
        "recording": {
            "age_at_recording": source_data["age"],
            "sex": source_data["sex"],
            "recording_duration_minutes": duration_minutes,
            "number_of_signal_channels": source_data["channel_count"],
        }
    }

def write_json_atomic(
    path: Path,
    payload: dict[str, Any],
) -> None:
    """Write JSON atomically so a partial file is never installed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json.tmp",
        prefix=f".{path.stem}_",
        dir=path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_file.name)

    try:
        with temporary_file:
            json.dump(
                payload,
                temporary_file,
                indent=2,
                sort_keys=True,
            )
            temporary_file.write("\n")

        os.replace(temporary_path, path)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_json_sidecar(
    output_path: Path,
    source_data: dict[str, Any],
) -> None:
    """Write the minimal non-PHI JSON sidecar."""
    write_json_atomic(
        sidecar_path(output_path),
        build_sidecar_data(source_data),
    )


def scrub_edf_metadata(
    input_path: Path,
    output_path: Path,
) -> None:
    """
    Scrub one EDF and create its minimal JSON sidecar.

    The final EDF is installed only after validation succeeds.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if input_path.resolve() == output_path.resolve():
        raise EDFScrubbingError(
            "Input and output paths must be different."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    source_data = read_source_edf(input_path)

    temporary_file = tempfile.NamedTemporaryFile(
        suffix=".edf",
        prefix=f".{output_path.stem}_",
        dir=output_path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    temporary_file.close()

    try:
        write_scrubbed_edf(
            temporary_path,
            source_data,
        )

        verify_scrubbed_edf(
            temporary_path,
            expected_channel_count=source_data["channel_count"],
        )

        os.replace(temporary_path, output_path)

        write_json_sidecar(
            output_path,
            source_data,
        )

    except Exception:
        temporary_path.unlink(missing_ok=True)

        # Avoid leaving an EDF without its corresponding sidecar when sidecar
        # creation fails.
        if output_path.exists() and not sidecar_path(output_path).exists():
            output_path.unlink(missing_ok=True)

        raise

    print(f"Scrubbed EDF saved to: {output_path}")
    print(f"JSON sidecar saved to: {sidecar_path(output_path)}")
    print(
        "Annotations removed:",
        source_data["annotation_count_removed"],
    )


def require_directory(path: Path, label: str) -> None:
    """Raise a clear error when a required directory is unavailable."""
    if not path.exists():
        raise SystemExit(f"ERROR: {label} does not exist: {path}")

    if not path.is_dir():
        raise SystemExit(f"ERROR: {label} is not a directory: {path}")


def output_paths(
    input_path: Path,
    input_dir: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Return the scrubbed EDF and JSON paths for one source EDF."""
    relative_path = input_path.relative_to(input_dir)
    output_path = (
        output_dir
        / relative_path.parent
        / scrubbed_filename(input_path)
    )
    return output_path, sidecar_path(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove potentially identifying EDF header metadata and "
            "all EDF annotations."
        )
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Folder containing raw EDF files.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Folder where scrubbed EDF files are saved.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing scrubbed EDF and JSON files.",
    )

    args = parser.parse_args()

    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    print("Input EDF folder:", input_dir, flush=True)
    print("Output scrubbed folder:", output_dir, flush=True)

    require_directory(input_dir, "Input folder")
    output_dir.mkdir(parents=True, exist_ok=True)

    edf_files = find_edf_files(input_dir)

    print(f"Found {len(edf_files)} EDF file(s).", flush=True)

    if not edf_files:
        raise SystemExit("No .edf files found.")

    successful = 0
    skipped = 0
    failed = 0

    for index, input_path in enumerate(edf_files, start=1):
        relative_path = input_path.relative_to(input_dir)

        output_path, json_path = output_paths(
            input_path,
            input_dir,
            output_dir,
        )

        print("\n--------------------", flush=True)
        print(
            f"[{index}/{len(edf_files)}] Input: {relative_path}",
            flush=True,
        )
        print(
            "Output:",
            output_path.relative_to(output_dir),
            flush=True,
        )

        output_exists = output_path.exists()
        sidecar_exists = json_path.exists()

        if (output_exists or sidecar_exists) and not args.overwrite:
            print(
                "Skipping: output already exists. "
                "Use --overwrite to replace it.",
                flush=True,
            )
            skipped += 1
            continue

        if args.overwrite:
            output_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)

        try:
            scrub_edf_metadata(
                input_path,
                output_path,
            )
            successful += 1

        except Exception as exc:
            failed += 1
            print(f"ERROR: {exc}", flush=True)

    print("\nEDF metadata scrubbing complete.", flush=True)
    print("Successful:", successful, flush=True)
    print("Skipped:", skipped, flush=True)
    print("Failed:", failed, flush=True)

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()