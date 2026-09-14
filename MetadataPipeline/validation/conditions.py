"""Small, reusable helpers for conditional metadata rules."""

from __future__ import annotations

import json


def is_blank(value):
    """Return True when a metadata value should be treated as empty."""
    if value is None:
        return True

    if type(value) is str and value.strip() == "":
        return True

    if type(value) is list and len(value) == 0:
        return True

    return False


def condition_matches(record, parent_field, operator, trigger_value):
    """Evaluate one machine-readable dependency rule."""
    parent_value = record.get(parent_field)

    if is_blank(parent_value):
        return False

    if operator == "equals":
        return parent_value == trigger_value

    if operator == "contains":
        return _contains(parent_value, trigger_value)

    if operator == "does_not_contain":
        return not _contains(parent_value, trigger_value)

    if operator == "contains_any":
        choices = _read_json_list(trigger_value)
        return any(_contains(parent_value, choice) for choice in choices)

    if operator == "in":
        choices = _read_json_list(trigger_value)
        return parent_value in choices

    return False


def _contains(value, expected):
    if type(value) is list:
        return expected in value

    if type(value) is str:
        return expected in value

    return False


def _read_json_list(value):
    if type(value) is list:
        return value

    try:
        parsed = json.loads(value)
    except Exception:
        return []

    if type(parsed) is list:
        return parsed

    return []
