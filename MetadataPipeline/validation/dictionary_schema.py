"""Validate the machine-readable CoCANoT dictionary before using it."""

from __future__ import annotations

import json


REQUIRED_COLUMNS = {
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

CLINICAL_ONLY_COLUMN = "creates_new_clinical_assessment_if_changed"

SUPPORTED_INPUT_TYPES = {
    "identifier",
    "single_select",
    "multi_select",
    "free_text",
    "numeric",
}

SUPPORTED_VALIDATION_METHODS = {
    "identifier",
    "allowed_values",
    "conditional_allowed_values",
    "manual_review",
    "numeric",
}

SUPPORTED_OPERATORS = {
    "equals",
    "contains",
    "does_not_contain",
    "contains_any",
    "in",
}

EXPECTED_METHODS = {
    "identifier": {"identifier"},
    "single_select": {"allowed_values", "conditional_allowed_values"},
    "multi_select": {"allowed_values"},
    "free_text": {"manual_review"},
    "numeric": {"numeric"},
}


class DictionarySchemaError(ValueError):
    """Raised when machine-readable dictionary rules are invalid."""


def validate_dictionary_schema(dictionary):
    errors = []

    if dictionary is None or dictionary.get("tables") is None:
        raise DictionarySchemaError(
            "Dictionary schema validation failed:\n"
            "- Loaded dictionary must contain 'tables'."
        )

    versions = set()

    for table_name, table in dictionary["tables"].items():
        _check_table(table_name, table, versions, errors)

    if len(versions) > 1:
        errors.append(
            "All machine-readable sheets must use the same dictionary_version. "
            f"Found: {', '.join(sorted(versions))}."
        )

    if errors:
        raise DictionarySchemaError(
            "Dictionary schema validation failed:\n- " + "\n- ".join(errors)
        )

    return dictionary


def _check_table(table_name, table, versions, errors):
    sheet_name = table.get("sheet_name", f"MR {table_name}")
    columns = table.get("columns", [])
    fields = table.get("fields", [])

    missing = sorted(REQUIRED_COLUMNS - set(columns))
    if missing:
        errors.append(
            f"{sheet_name}: missing required column(s): {', '.join(missing)}."
        )

    if table_name == "Clinical" and CLINICAL_ONLY_COLUMN not in columns:
        errors.append(
            f"{sheet_name}: missing required Clinical column "
            f"'{CLINICAL_ONLY_COLUMN}'."
        )

    if type(fields) is not list or not fields:
        errors.append(f"{sheet_name}: no metadata fields were found.")
        return

    names = []
    orders = []

    for field in fields:
        _check_field(table_name, sheet_name, field, fields, versions, errors)

        if field.get("field_name"):
            names.append(field["field_name"])

        if field.get("field_order") is not None:
            orders.append(field["field_order"])

    _check_duplicates(sheet_name, "field_name", names, errors)
    _check_duplicates(sheet_name, "field_order", orders, errors)


def _check_field(table_name, sheet_name, field, all_fields, versions, errors):
    row = field.get("_excel_row", "?")
    location = f"{sheet_name}, row {row}"

    for column in [
        "dictionary_version",
        "table_name",
        "field_name",
        "input_type",
        "validation_method",
    ]:
        if field.get(column) is None or str(field.get(column)).strip() == "":
            errors.append(f"{location}: '{column}' cannot be blank.")

    version = field.get("dictionary_version")
    if version:
        versions.add(str(version))

    if field.get("table_name") != table_name:
        errors.append(
            f"{location}: table_name must be '{table_name}', "
            f"found '{field.get('table_name')}'."
        )

    _check_field_order(field, location, errors)
    _check_input_type(field, location, errors)
    _check_validation_method(field, location, errors)
    _check_booleans(table_name, field, location, errors)
    _check_allowed_values(field, location, errors)
    _check_dependency(field, all_fields, location, errors)
    _check_conditional_mapping(field, location, errors)


def _check_field_order(field, location, errors):
    value = field.get("field_order")

    if type(value) is not int or value < 1:
        errors.append(
            f"{location}: field_order must be an integer of 1 or greater."
        )


def _check_input_type(field, location, errors):
    value = field.get("input_type")

    if value not in SUPPORTED_INPUT_TYPES:
        errors.append(
            f"{location}: unsupported input_type '{value}'."
        )


def _check_validation_method(field, location, errors):
    input_type = field.get("input_type")
    method = field.get("validation_method")

    if method not in SUPPORTED_VALIDATION_METHODS:
        errors.append(
            f"{location}: unsupported validation_method '{method}'."
        )
        return

    expected = EXPECTED_METHODS.get(input_type, set())
    if expected and method not in expected:
        errors.append(
            f"{location}: input_type '{input_type}' cannot use "
            f"validation_method '{method}'."
        )


def _check_booleans(table_name, field, location, errors):
    columns = [
        "required",
        "manual_review_required",
        "system_generated",
    ]

    if table_name == "Clinical":
        columns.append(CLINICAL_ONLY_COLUMN)

    for column in columns:
        if type(field.get(column)) is not bool:
            errors.append(
                f"{location}: '{column}' must be TRUE or FALSE."
            )


def _check_allowed_values(field, location, errors):
    allowed = field.get("allowed_values")
    input_type = field.get("input_type")

    if type(allowed) is not list:
        errors.append(
            f"{location}: allowed_values_json must contain a JSON list."
        )
        return

    if input_type in {"single_select", "multi_select"} and not allowed:
        errors.append(
            f"{location}: {input_type} fields must define "
            "at least one allowed value."
        )

    duplicates = _duplicates(allowed)
    if duplicates:
        errors.append(
            f"{location}: allowed_values_json contains duplicate value(s): "
            + ", ".join(str(value) for value in duplicates)
            + "."
        )


def _check_dependency(field, all_fields, location, errors):
    parent = field.get("required_if_field")
    operator = field.get("required_if_operator")
    trigger = field.get("required_if_value")

    values = [parent, operator, trigger]
    filled = [value not in (None, "") for value in values]

    if any(filled) and not all(filled):
        errors.append(
            f"{location}: required_if_field, required_if_operator, and "
            "required_if_value must either all be filled or all be blank."
        )
        return

    if not any(filled):
        return

    names = [item.get("field_name") for item in all_fields]

    if parent not in names:
        errors.append(
            f"{location}: required_if_field '{parent}' does not exist "
            "in the same machine-readable table."
        )

    if operator not in SUPPORTED_OPERATORS:
        errors.append(
            f"{location}: unsupported required_if_operator '{operator}'."
        )
        return

    if operator in {"contains_any", "in"}:
        try:
            parsed = json.loads(trigger)
        except Exception:
            parsed = None

        if type(parsed) is not list:
            errors.append(
                f"{location}: required_if_value must contain a JSON list "
                f"when required_if_operator is '{operator}'."
            )


def _check_conditional_mapping(field, location, errors):
    method = field.get("validation_method")
    mapping = field.get("conditional_allowed_values")

    if type(mapping) is not dict:
        errors.append(
            f"{location}: conditional_allowed_values_json must contain "
            "a JSON object or be blank."
        )
        return

    if method == "conditional_allowed_values" and not mapping:
        errors.append(
            f"{location}: conditional_allowed_values validation requires "
            "conditional_allowed_values_json."
        )

    for parent_value, allowed_values in mapping.items():
        if type(allowed_values) is not list:
            errors.append(
                f"{location}: conditional_allowed_values_json['{parent_value}'] "
                "must be a JSON list."
            )


def _duplicates(values):
    duplicates = []

    for value in values:
        if values.count(value) > 1 and value not in duplicates:
            duplicates.append(value)

    return duplicates


def _check_duplicates(sheet_name, label, values, errors):
    duplicates = _duplicates(values)

    if duplicates:
        errors.append(
            f"{sheet_name}: duplicate {label} values: "
            + ", ".join(str(value) for value in duplicates)
            + "."
        )
