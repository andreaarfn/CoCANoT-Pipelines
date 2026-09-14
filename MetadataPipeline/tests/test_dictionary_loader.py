from pathlib import Path

import pytest

from MetadataPipeline.validation.dictionary_loader import (
    DictionaryLoadError,
    load_dictionary,
)


DICTIONARY = (
    Path(__file__).resolve().parents[1]
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)


def test_loads_only_expected_machine_readable_tables():
    dictionary = load_dictionary(DICTIONARY)

    assert list(dictionary["tables"]) == [
        "Clinical",
        "Surgical",
        "Electrophysiology",
        "Imaging",
    ]

    assert dictionary["machine_readable_sheets"] == [
        "MR Clinical",
        "MR Surgical",
        "MR Electrophysiology",
        "MR Imaging",
    ]


def test_human_readable_sheets_are_ignored_as_rules():
    dictionary = load_dictionary(DICTIONARY)

    assert "Clinical Metadata Dictionary Ph" in dictionary["human_readable_sheets"]
    assert "Clinical Metadata Dictionary Ph" not in dictionary["tables"]


def test_json_allowed_values_are_parsed():
    dictionary = load_dictionary(DICTIONARY)

    imaging_fields = dictionary["tables"]["Imaging"]["fields"]
    modality = next(
        field for field in imaging_fields
        if field["field_name"] == "Imaging Modality"
    )

    assert modality["allowed_values"] == ["MRI", "CT"]
    assert isinstance(modality["allowed_values"], list)


def test_conditional_allowed_values_are_parsed():
    dictionary = load_dictionary(DICTIONARY)

    surgical_fields = dictionary["tables"]["Surgical"]["fields"]
    subtype = next(
        field for field in surgical_fields
        if field["field_name"] == "12-Month Engel Outcome Subtype (if available)"
    )

    assert subtype["conditional_allowed_values"]["I"] == ["IA", "IB", "IC", "ID"]
    assert subtype["conditional_allowed_values"]["III"] == ["IIIA", "IIIB"]
    assert subtype["conditional_allowed_values"]["Death"] == []


def test_dependency_columns_are_preserved_exactly():
    dictionary = load_dictionary(DICTIONARY)

    imaging_fields = dictionary["tables"]["Imaging"]["fields"]
    mri_sequences = next(
        field for field in imaging_fields
        if field["field_name"] == "MRI Sequence(s) (if applicable)"
    )

    assert mri_sequences["required"] is False
    assert mri_sequences["required_if_field"] == "Imaging Modality"
    assert mri_sequences["required_if_operator"] == "equals"
    assert mri_sequences["required_if_value"] == "MRI"


def test_workbook_location_is_retained_for_clear_errors():
    dictionary = load_dictionary(DICTIONARY)

    first_field = dictionary["tables"]["Clinical"]["fields"][0]

    assert first_field["_sheet_name"] == "MR Clinical"
    assert first_field["_excel_row"] == 2


def test_missing_file_fails_cleanly(tmp_path):
    missing = tmp_path / "does_not_exist.xlsx"

    with pytest.raises(DictionaryLoadError, match="does not exist"):
        load_dictionary(missing)
