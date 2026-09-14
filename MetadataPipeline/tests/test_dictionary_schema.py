from copy import deepcopy
from pathlib import Path

import pytest

from MetadataPipeline.validation.dictionary_loader import load_dictionary
from MetadataPipeline.validation.dictionary_schema import (
    DictionarySchemaError,
    validate_dictionary_schema,
)


DICTIONARY = (
    Path(__file__).resolve().parents[1]
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)


def load_valid_dictionary():
    return load_dictionary(DICTIONARY)


def find_field(dictionary, table_name, field_name):
    fields = dictionary["tables"][table_name]["fields"]
    return next(
        field for field in fields
        if field["field_name"] == field_name
    )


def test_current_dictionary_schema_passes():
    dictionary = load_valid_dictionary()

    result = validate_dictionary_schema(dictionary)

    assert result is dictionary


def test_every_field_has_every_expected_machine_column():
    dictionary = load_valid_dictionary()

    required_columns = {
        "dictionary_version",
        "table_name",
        "field_order",
        "field_name",
        "ui_prompt",
        "help_text",
        "input_type",
        "validation_method",
        "allowed_values_json",
        "conditional_allowed_values_json",
        "required",
        "required_if_field",
        "required_if_operator",
        "required_if_value",
        "manual_review_required",
        "system_generated",
    }

    for table_name, table in dictionary["tables"].items():
        assert required_columns.issubset(set(table["columns"]))

        for field in table["fields"]:
            for column in required_columns:
                assert column in field

        if table_name == "Clinical":
            assert "creates_new_clinical_assessment_if_changed" in table["columns"]


def test_rejects_bad_input_type():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(dictionary, "Imaging", "Imaging Modality")
    field["input_type"] = "singel_select"

    with pytest.raises(DictionarySchemaError, match="unsupported input_type"):
        validate_dictionary_schema(dictionary)


def test_rejects_bad_validation_method():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(dictionary, "Imaging", "Imaging Modality")
    field["validation_method"] = "manual_review"

    with pytest.raises(DictionarySchemaError, match="cannot use validation_method"):
        validate_dictionary_schema(dictionary)


def test_rejects_non_boolean_required():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(dictionary, "Imaging", "Imaging Modality")
    field["required"] = "TRUE"

    with pytest.raises(DictionarySchemaError, match="must be TRUE or FALSE"):
        validate_dictionary_schema(dictionary)


def test_rejects_missing_dependency_parent():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(
        dictionary,
        "Imaging",
        "MRI Sequence(s) (if applicable)",
    )
    field["required_if_field"] = "MRI Modality"

    with pytest.raises(DictionarySchemaError, match="does not exist"):
        validate_dictionary_schema(dictionary)


def test_rejects_incomplete_dependency_rule():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(
        dictionary,
        "Imaging",
        "MRI Sequence(s) (if applicable)",
    )
    field["required_if_value"] = None

    with pytest.raises(DictionarySchemaError, match="must either all be filled"):
        validate_dictionary_schema(dictionary)


def test_rejects_bad_dependency_operator():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(
        dictionary,
        "Imaging",
        "MRI Sequence(s) (if applicable)",
    )
    field["required_if_operator"] = "is_equal_to"

    with pytest.raises(DictionarySchemaError, match="unsupported required_if_operator"):
        validate_dictionary_schema(dictionary)


def test_rejects_duplicate_field_name():
    dictionary = deepcopy(load_valid_dictionary())
    fields = dictionary["tables"]["Imaging"]["fields"]
    fields[1]["field_name"] = fields[0]["field_name"]

    with pytest.raises(DictionarySchemaError, match="duplicate field_name"):
        validate_dictionary_schema(dictionary)


def test_rejects_duplicate_allowed_values():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(dictionary, "Imaging", "Imaging Modality")
    field["allowed_values"].append("MRI")

    with pytest.raises(DictionarySchemaError, match="duplicate value"):
        validate_dictionary_schema(dictionary)


def test_rejects_empty_allowed_values_for_select_field():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(dictionary, "Imaging", "Imaging Modality")
    field["allowed_values"] = []

    with pytest.raises(DictionarySchemaError, match="must define at least one allowed value"):
        validate_dictionary_schema(dictionary)


def test_rejects_inconsistent_dictionary_versions():
    dictionary = deepcopy(load_valid_dictionary())
    field = dictionary["tables"]["Imaging"]["fields"][0]
    field["dictionary_version"] = "Phase 2"

    with pytest.raises(DictionarySchemaError, match="same dictionary_version"):
        validate_dictionary_schema(dictionary)


def test_rejects_wrong_table_name():
    dictionary = deepcopy(load_valid_dictionary())
    field = dictionary["tables"]["Imaging"]["fields"][0]
    field["table_name"] = "Clinical"

    with pytest.raises(DictionarySchemaError, match="table_name must be 'Imaging'"):
        validate_dictionary_schema(dictionary)


def test_rejects_bad_conditional_allowed_mapping():
    dictionary = deepcopy(load_valid_dictionary())
    field = find_field(
        dictionary,
        "Surgical",
        "12-Month Engel Outcome Subtype (if available)",
    )
    field["conditional_allowed_values"]["I"] = "IA"

    with pytest.raises(DictionarySchemaError, match="must be a JSON list"):
        validate_dictionary_schema(dictionary)
