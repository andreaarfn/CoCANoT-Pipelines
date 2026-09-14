"""Detect Clinical or Surgical metadata tables from their columns."""

from __future__ import annotations


USER_UPLOAD_TABLES = (
    "Clinical",
    "Surgical",
)


class TableDetectionError(ValueError):
    """Raised when an uploaded file cannot be matched to one user upload table."""


def detect_upload_table(dictionary, columns):
    """Identify whether an uploaded file is Clinical or Surgical metadata.

    Imaging and Electrophysiology are intentionally excluded from the normal
    upload path because users complete those forms inside their pipelines.
    """
    uploaded = set(columns)
    matches = []

    for table_name in USER_UPLOAD_TABLES:
        rules = dictionary["tables"][table_name]["fields"]
        known_fields = {
            rule["field_name"]
            for rule in rules
        }

        required_fields = {
            rule["field_name"]
            for rule in rules
            if rule["required"]
        }

        if not required_fields.issubset(uploaded):
            continue

        if not uploaded.issubset(known_fields):
            continue

        matches.append(table_name)

    if len(matches) == 1:
        return matches[0]

    if not matches:
        raise TableDetectionError(
            "The uploaded columns do not match the Clinical or Surgical "
            "metadata dictionary."
        )

    raise TableDetectionError(
        "The uploaded columns match more than one metadata table."
    )
