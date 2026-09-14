"""Normalize uploaded spreadsheet values before validation."""

from __future__ import annotations

import json


def normalize_record(dictionary, table_name, record):
    """Convert uploaded cell values to the types expected by the validator."""
    rules = dictionary["tables"][table_name]["fields"]
    normalized = {}

    for rule in rules:
        field_name = rule["field_name"]

        if field_name not in record:
            continue

        value = record[field_name]

        if rule["input_type"] == "multi_select":
            value = _normalize_multi_select(value)

        normalized[field_name] = value

    # Preserve unknown columns so the validator can report them.
    known_fields = {
        rule["field_name"]
        for rule in rules
    }

    for field_name, value in record.items():
        if field_name not in known_fields:
            normalized[field_name] = value

    return normalized


def _normalize_multi_select(value):
    if value is None:
        return None

    if type(value) is list:
        return value

    if type(value) is not str:
        return value

    text = value.strip()

    if text == "":
        return None

    if text.startswith("["):
        parsed = _read_json_list(text)

        if parsed is not None:
            return parsed

    return [
        item.strip()
        for item in text.split(";")
        if item.strip()
    ]


def _read_json_list(text):
    try:
        value = json.loads(text)
    except Exception:
        return None

    if type(value) is list:
        return value

    return None
