"""Load Clinical or Surgical metadata from CSV or XLSX files."""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl


SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}


class MetadataFileError(ValueError):
    """Raised when an uploaded metadata file cannot be read safely."""


def load_metadata_file(file_path):
    """Load a CSV or XLSX file into a list of row dictionaries.

    The loader preserves column names exactly because the active dictionary
    controls the metadata schema.
    """
    path = Path(file_path)

    if not path.exists():
        raise MetadataFileError(f"Metadata file does not exist: {path}")

    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise MetadataFileError(
            "Metadata uploads must be .csv or .xlsx files."
        )

    if extension == ".csv":
        return _load_csv(path)

    return _load_xlsx(path)


def _load_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise MetadataFileError("CSV file does not contain a header row.")

        rows = []

        for row in reader:
            if _row_is_blank(row):
                continue

            rows.append(
                _clean_row(row)
            )

    return {
        "source_file": str(path),
        "sheet_name": None,
        "columns": list(reader.fieldnames),
        "rows": rows,
    }


def _load_xlsx(path):
    workbook = openpyxl.load_workbook(
        path,
        read_only=True,
        data_only=True,
    )

    try:
        sheet_names = workbook.sheetnames

        if len(sheet_names) != 1:
            raise MetadataFileError(
                "Metadata upload XLSX files must contain exactly one worksheet."
            )

        sheet = workbook[sheet_names[0]]

        headers = [
            cell.value
            for cell in sheet[1]
        ]

        while headers and headers[-1] is None:
            headers.pop()

        if not headers:
            raise MetadataFileError(
                "XLSX file does not contain a header row."
            )

        if any(header is None or str(header).strip() == "" for header in headers):
            raise MetadataFileError(
                "XLSX header row contains a blank column name."
            )

        columns = [
            str(header).strip()
            for header in headers
        ]

        rows = []

        for values in sheet.iter_rows(
            min_row=2,
            max_col=len(columns),
            values_only=True,
        ):
            row = dict(zip(columns, values))

            if _row_is_blank(row):
                continue

            rows.append(
                _clean_row(row)
            )

        return {
            "source_file": str(path),
            "sheet_name": sheet.title,
            "columns": columns,
            "rows": rows,
        }
    finally:
        workbook.close()


def _clean_row(row):
    clean = {}

    for key, value in row.items():
        if type(value) is str:
            value = value.strip()

        clean[key] = value

    return clean


def _row_is_blank(row):
    for value in row.values():
        if value is None:
            continue

        if type(value) is str and value.strip() == "":
            continue

        return False

    return True
