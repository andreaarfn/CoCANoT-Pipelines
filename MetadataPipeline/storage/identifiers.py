"""Canonical identifiers for CoCANoT patient and modality records.

Normalize numeric identifiers without changing alphanumeric IDs.
Never silently truncate IDs with more than three digits.
"""
from __future__ import annotations

import re

PREFIXES = {
    "Surgical": "SURG",
    "Imaging": "IMG",
    "Electrophysiology": "EPHYS",
}


def normalize_patient_id(value: object) -> str:
    text = str(value if value is not None else "").strip()
    if text.isdecimal() and text.isascii():
        return text.zfill(3)
    return text


def normalize_record_id(table_name: str, value: object) -> str:
    text = str(value if value is not None else "").strip()
    prefix = PREFIXES.get(table_name)
    if not prefix or not text:
        return text
    # Existing prefixed and numeric IDs refer to the same record.
    match = re.fullmatch(rf"(?i)(?:{prefix}-)?([0-9]+)", text)
    if match:
        return f"{prefix}-{match.group(1).zfill(3)}"
    return text
