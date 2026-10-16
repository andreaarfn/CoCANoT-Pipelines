"""Regression tests for ATLAS patient and modality ID normalization."""
from MetadataPipeline.storage.identifiers import normalize_patient_id, normalize_record_id


def test_patient_id_zero_padding():
    for incoming in ("3", "03", "003", "0003", 3):
        assert normalize_patient_id(incoming) == "003"
    assert normalize_patient_id("12") == "012"
    assert normalize_patient_id("123") == "123"
    assert normalize_patient_id("1234") == "1234"


def test_modality_id_prefix_and_zero_padding():
    for table, prefix in (
        ("Surgical", "SURG"),
        ("Imaging", "IMG"),
        ("Electrophysiology", "EPHYS"),
    ):
        for raw in ("3", "03", "003", "0003", f"{prefix}-3", f"{prefix.lower()}-003"):
            assert normalize_record_id(table, raw) == f"{prefix}-003"
        assert normalize_record_id(table, "12") == f"{prefix}-012"
        assert normalize_record_id(table, "123") == f"{prefix}-123"


def test_preserve_non_numeric_identifiers():
    assert normalize_patient_id("PAT-A") == "PAT-A"
    assert normalize_record_id("Surgical", "SURG-LEFT") == "SURG-LEFT"
    assert normalize_record_id("Clinical", "CA-003") == "CA-003"
