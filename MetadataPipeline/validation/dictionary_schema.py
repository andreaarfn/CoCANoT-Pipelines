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

OPTIONAL_RULE_COLUMNS = {
    "exclusive_values_json",
    "repeat_for_each_field",
    "repeat_exclude_values_json",
    "repeat_special_values_json",
    "repeat_prompt_template",
    "legacy_field_names_json",
    "available_after_surgery_months",
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
    "is_blank",
    "is_not_blank",
}

EXPECTED_METHODS = {
    "identifier": {"identifier"},
    "single_select": {
        "allowed_values",
        "conditional_allowed_values",
    },
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
        _check_table(
            table_name,
            table,
            versions,
            errors,
        )

    if len(versions) > 1:
        errors.append(
            "All machine-readable sheets must use the same dictionary_version. "
            f"Found: {', '.join(sorted(versions))}."
        )

    if errors:
        raise DictionarySchemaError(
            "Dictionary schema validation failed:\n- "
            + "\n- ".join(errors)
        )

    return dictionary


def _check_table(
    table_name,
    table,
    versions,
    errors,
):
    sheet_name = table.get(
        "sheet_name",
        f"MR {table_name}",
    )
    columns = table.get("columns", [])
    fields = table.get("fields", [])

    missing = sorted(
        REQUIRED_COLUMNS - set(columns)
    )

    if missing:
        errors.append(
            f"{sheet_name}: missing required column(s): "
            + ", ".join(missing)
            + "."
        )

    if (
        table_name == "Clinical"
        and CLINICAL_ONLY_COLUMN not in columns
    ):
        errors.append(
            f"{sheet_name}: missing required Clinical column "
            f"'{CLINICAL_ONLY_COLUMN}'."
        )

    if type(fields) is not list or not fields:
        errors.append(
            f"{sheet_name}: no metadata fields were found."
        )
        return

    names = []
    orders = []

    for field in fields:
        _check_field(
            table_name,
            sheet_name,
            field,
            fields,
            versions,
            errors,
        )

        if field.get("field_name"):
            names.append(
                field["field_name"]
            )

        if field.get("field_order") is not None:
            orders.append(
                field["field_order"]
            )

    _check_duplicates(
        sheet_name,
        "field_name",
        names,
        errors,
    )
    _check_duplicates(
        sheet_name,
        "field_order",
        orders,
        errors,
    )


def _check_field(
    table_name,
    sheet_name,
    field,
    all_fields,
    versions,
    errors,
):
    row = field.get("_excel_row", "?")
    location = f"{sheet_name}, row {row}"

    for column in [
        "dictionary_version",
        "table_name",
        "field_name",
        "input_type",
        "validation_method",
    ]:
        if (
            field.get(column) is None
            or str(
                field.get(column)
            ).strip() == ""
        ):
            errors.append(
                f"{location}: '{column}' cannot be blank."
            )

    version = field.get(
        "dictionary_version"
    )

    if version:
        versions.add(
            str(version)
        )

    if field.get("table_name") != table_name:
        errors.append(
            f"{location}: table_name must be '{table_name}', "
            f"found '{field.get('table_name')}'."
        )

    _check_field_order(
        field,
        location,
        errors,
    )
    _check_input_type(
        field,
        location,
        errors,
    )
    _check_validation_method(
        field,
        location,
        errors,
    )
    _check_booleans(
        table_name,
        field,
        location,
        errors,
    )
    _check_allowed_values(
        field,
        location,
        errors,
    )
    _check_dependency(
        field,
        all_fields,
        location,
        errors,
    )
    _check_conditional_mapping(
        field,
        location,
        errors,
    )
    _check_exclusive_values(
        field,
        location,
        errors,
    )
    _check_repeat_rule(
        field,
        all_fields,
        location,
        errors,
    )
    _check_legacy_field_names(
        field,
        all_fields,
        location,
        errors,
    )
    _check_surgery_month_threshold(
        table_name,
        field,
        location,
        errors,
    )


def _check_field_order(
    field,
    location,
    errors,
):
    value = field.get(
        "field_order"
    )

    if type(value) is not int or value < 1:
        errors.append(
            f"{location}: field_order must be an integer "
            "of 1 or greater."
        )


def _check_input_type(
    field,
    location,
    errors,
):
    value = field.get(
        "input_type"
    )

    if value not in SUPPORTED_INPUT_TYPES:
        errors.append(
            f"{location}: unsupported input_type '{value}'."
        )


def _check_validation_method(
    field,
    location,
    errors,
):
    input_type = field.get(
        "input_type"
    )
    method = field.get(
        "validation_method"
    )

    if method not in SUPPORTED_VALIDATION_METHODS:
        errors.append(
            f"{location}: unsupported validation_method '{method}'."
        )
        return

    expected = EXPECTED_METHODS.get(
        input_type,
        set(),
    )

    if expected and method not in expected:
        errors.append(
            f"{location}: input_type '{input_type}' cannot use "
            f"validation_method '{method}'."
        )


def _check_booleans(
    table_name,
    field,
    location,
    errors,
):
    columns = [
        "required",
        "manual_review_required",
        "system_generated",
    ]

    if table_name == "Clinical":
        columns.append(
            CLINICAL_ONLY_COLUMN
        )

    for column in columns:
        if type(field.get(column)) is not bool:
            errors.append(
                f"{location}: '{column}' must be TRUE or FALSE."
            )


def _check_allowed_values(
    field,
    location,
    errors,
):
    allowed = field.get(
        "allowed_values"
    )
    input_type = field.get(
        "input_type"
    )

    if type(allowed) is not list:
        errors.append(
            f"{location}: allowed_values_json must contain "
            "a JSON list."
        )
        return

    if (
        input_type
        in {
            "single_select",
            "multi_select",
        }
        and not allowed
    ):
        errors.append(
            f"{location}: {input_type} fields must define "
            "at least one allowed value."
        )

    duplicates = _duplicates(
        allowed
    )

    if duplicates:
        errors.append(
            f"{location}: allowed_values_json contains duplicate value(s): "
            + ", ".join(
                str(value)
                for value in duplicates
            )
            + "."
        )


def _check_dependency(
    field,
    all_fields,
    location,
    errors,
):
    parent = field.get(
        "required_if_field"
    )
    operator = field.get(
        "required_if_operator"
    )
    trigger = field.get(
        "required_if_value"
    )

    unary = operator in {
        "is_blank",
        "is_not_blank",
    }

    if unary:
        filled = [
            parent not in (
                None,
                "",
            ),
            operator not in (
                None,
                "",
            ),
        ]

        if not all(filled):
            errors.append(
                f"{location}: required_if_field and "
                "required_if_operator must both be filled."
            )
            return
    else:
        values = [
            parent,
            operator,
            trigger,
        ]
        filled = [
            value not in (
                None,
                "",
            )
            for value in values
        ]

        if any(filled) and not all(filled):
            errors.append(
                f"{location}: required_if_field, required_if_operator, and "
                "required_if_value must either all be filled or all be blank."
            )
            return

        if not any(filled):
            return

    names = [
        item.get(
            "field_name"
        )
        for item in all_fields
    ]

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

    if operator in {
        "contains_any",
        "in",
    }:
        parsed = _json_list(
            trigger
        )

        if parsed is None:
            errors.append(
                f"{location}: required_if_value must contain a JSON list "
                f"when required_if_operator is '{operator}'."
            )


def _check_conditional_mapping(
    field,
    location,
    errors,
):
    method = field.get(
        "validation_method"
    )
    mapping = field.get(
        "conditional_allowed_values"
    )

    if type(mapping) is not dict:
        errors.append(
            f"{location}: conditional_allowed_values_json must contain "
            "a JSON object or be blank."
        )
        return

    if (
        method == "conditional_allowed_values"
        and not mapping
    ):
        errors.append(
            f"{location}: conditional_allowed_values validation requires "
            "conditional_allowed_values_json."
        )

    for parent_value, allowed_values in mapping.items():
        if type(allowed_values) is not list:
            errors.append(
                f"{location}: conditional_allowed_values_json"
                f"['{parent_value}'] must be a JSON list."
            )


def _check_exclusive_values(
    field,
    location,
    errors,
):
    values = field.get(
        "exclusive_values",
        [],
    )

    if type(values) is not list:
        errors.append(
            f"{location}: exclusive_values_json must contain "
            "a JSON list or be blank."
        )
        return

    if values and field.get(
        "input_type"
    ) != "multi_select":
        errors.append(
            f"{location}: exclusive_values_json can only be used "
            "with multi_select fields."
        )

    allowed = field.get(
        "allowed_values",
        [],
    )

    unknown = [
        value
        for value in values
        if value not in allowed
    ]

    if unknown:
        errors.append(
            f"{location}: exclusive_values_json contains value(s) "
            "not present in allowed_values_json: "
            + ", ".join(
                str(value)
                for value in unknown
            )
            + "."
        )

    duplicates = _duplicates(
        values
    )

    if duplicates:
        errors.append(
            f"{location}: exclusive_values_json contains duplicate value(s): "
            + ", ".join(
                str(value)
                for value in duplicates
            )
            + "."
        )


def _check_repeat_rule(
    field,
    all_fields,
    location,
    errors,
):
    parent_name = field.get(
        "repeat_for_each_field"
    )
    excluded = field.get(
        "repeat_exclude_values",
        [],
    )
    special = field.get(
        "repeat_special_values",
        [],
    )
    template = field.get(
        "repeat_prompt_template"
    )

    if type(excluded) is not list:
        errors.append(
            f"{location}: repeat_exclude_values_json must contain "
            "a JSON list or be blank."
        )
        return

    if type(special) is not list:
        errors.append(
            f"{location}: repeat_special_values_json must contain "
            "a JSON list or be blank."
        )
        return

    configured = any(
        [
            parent_name not in (
                None,
                "",
            ),
            bool(excluded),
            bool(special),
            template not in (
                None,
                "",
            ),
        ]
    )

    if not configured:
        return

    if not parent_name:
        errors.append(
            f"{location}: repeat_for_each_field is required when "
            "repeat rule columns are used."
        )
        return

    if field.get(
        "input_type"
    ) != "free_text":
        errors.append(
            f"{location}: repeated response fields currently require "
            "input_type 'free_text'."
        )

    parent = next(
        (
            item
            for item in all_fields
            if item.get(
                "field_name"
            )
            == parent_name
        ),
        None,
    )

    if parent is None:
        errors.append(
            f"{location}: repeat_for_each_field '{parent_name}' does not "
            "exist in the same machine-readable table."
        )
        return

    if parent.get(
        "input_type"
    ) not in {
        "single_select",
        "multi_select",
    }:
        errors.append(
            f"{location}: repeat_for_each_field must reference a "
            "single_select or multi_select field."
        )

    if (
        parent.get(
            "field_order",
            0,
        )
        >= field.get(
            "field_order",
            0,
        )
    ):
        errors.append(
            f"{location}: repeat_for_each_field must reference an "
            "earlier field."
        )

    parent_allowed = parent.get(
        "allowed_values",
        [],
    )

    unknown_exclusions = [
        value
        for value in excluded
        if value not in parent_allowed
    ]

    if unknown_exclusions:
        errors.append(
            f"{location}: repeat_exclude_values_json contains value(s) "
            "not allowed by the parent field: "
            + ", ".join(
                str(value)
                for value in unknown_exclusions
            )
            + "."
        )

    if template in (
        None,
        "",
    ):
        errors.append(
            f"{location}: repeat_prompt_template is required for "
            "a repeated response field."
        )
    elif "{selection}" not in str(
        template
    ):
        errors.append(
            f"{location}: repeat_prompt_template must include "
            "'{selection}'."
        )

    for label, values in (
        (
            "repeat_exclude_values_json",
            excluded,
        ),
        (
            "repeat_special_values_json",
            special,
        ),
    ):
        duplicates = _duplicates(
            values
        )

        if duplicates:
            errors.append(
                f"{location}: {label} contains duplicate value(s): "
                + ", ".join(
                    str(value)
                    for value in duplicates
                )
                + "."
            )


def _check_legacy_field_names(
    field,
    all_fields,
    location,
    errors,
):
    aliases = field.get(
        "legacy_field_names",
        [],
    )

    if type(aliases) is not list:
        errors.append(
            f"{location}: legacy_field_names_json must contain "
            "a JSON list or be blank."
        )
        return

    aliases = [
        str(value).strip()
        for value in aliases
        if str(value).strip()
    ]

    duplicates = _duplicates(
        aliases
    )

    if duplicates:
        errors.append(
            f"{location}: legacy_field_names_json contains duplicate value(s): "
            + ", ".join(duplicates)
            + "."
        )

    current_name = str(
        field.get(
            "field_name",
            "",
        )
        or ""
    ).strip()

    if current_name in aliases:
        errors.append(
            f"{location}: legacy_field_names_json must not include "
            "the current field_name."
        )

    canonical_names = {
        str(
            item.get(
                "field_name",
                "",
            )
            or ""
        ).strip()
        for item in all_fields
    }

    collisions = [
        alias
        for alias in aliases
        if alias in canonical_names
        and alias != current_name
    ]

    if collisions:
        errors.append(
            f"{location}: legacy_field_names_json collides with current "
            "field_name(s): "
            + ", ".join(collisions)
            + "."
        )


def _check_surgery_month_threshold(
    table_name,
    field,
    location,
    errors,
):
    value = field.get(
        "available_after_surgery_months"
    )

    if value in (
        None,
        "",
    ):
        return

    if table_name != "Surgical":
        errors.append(
            f"{location}: available_after_surgery_months can only be used "
            "in MR Surgical."
        )
        return

    if type(value) is not int or value < 1:
        errors.append(
            f"{location}: available_after_surgery_months must be "
            "an integer of 1 or greater."
        )


def _json_list(value):
    if type(value) is list:
        return value

    try:
        parsed = json.loads(
            value
        )
    except Exception:
        return None

    if type(parsed) is list:
        return parsed

    return None


def _duplicates(values):
    duplicates = []

    for value in values:
        if (
            values.count(value) > 1
            and value not in duplicates
        ):
            duplicates.append(
                value
            )

    return duplicates


def _check_duplicates(
    sheet_name,
    label,
    values,
    errors,
):
    duplicates = _duplicates(
        values
    )

    if duplicates:
        errors.append(
            f"{sheet_name}: duplicate {label} values: "
            + ", ".join(
                str(value)
                for value in duplicates
            )
            + "."
        )
