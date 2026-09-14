"""Validate metadata records against the active CoCANoT dictionary."""

from __future__ import annotations

from .conditions import condition_matches, is_blank
from .dictionary_schema import validate_dictionary_schema
from .models import (
    INVALID,
    MANUAL_REVIEW,
    MISSING_REQUIRED,
    NOT_APPLICABLE,
    VALID,
    field_result,
)


class MetadataValidator:
    """Validate metadata using rules from the machine-readable dictionary."""

    def __init__(self, dictionary):
        validate_dictionary_schema(dictionary)
        self.dictionary = dictionary

    def validate_record(self, table_name, record):
        if table_name not in self.dictionary["tables"]:
            raise ValueError(f"Unknown metadata table '{table_name}'.")

        table = self.dictionary["tables"][table_name]
        rules = table["fields"]
        results = []

        for rule in rules:
            results.append(
                self._validate_field(rule, rules, record)
            )

        results.extend(
            self._check_unknown_fields(rules, record)
        )

        blocking = {"invalid", "missing_required"}

        has_error = any(
            result["status"] in blocking
            for result in results
        )

        needs_review = any(
            result["status"] == MANUAL_REVIEW
            for result in results
        )

        return {
            "table_name": table_name,
            "passes_automatic_validation": not has_error,
            "requires_manual_review": needs_review,
            "ready_for_approval": not has_error and not needs_review,
            "results": results,
            "summary": self._build_summary(results),
        }

    def _validate_field(self, rule, rules, record):
        field_name = rule["field_name"]
        value = record.get(field_name)

        condition_active = self._condition_is_active(rule, record)

        if rule.get("required_if_field") and not condition_active:
            if is_blank(value):
                return field_result(
                    field_name,
                    value,
                    NOT_APPLICABLE,
                    "NOT_APPLICABLE",
                    "This field does not apply based on the related metadata.",
                )

            return field_result(
                field_name,
                value,
                INVALID,
                "VALUE_NOT_APPLICABLE",
                "A value was provided even though this field does not apply.",
            )

        required = rule["required"] or condition_active

        if is_blank(value):
            if required:
                return field_result(
                    field_name,
                    value,
                    MISSING_REQUIRED,
                    "MISSING_REQUIRED",
                    "A value is required for this field.",
                )

            return field_result(
                field_name,
                value,
                VALID,
                "OPTIONAL_BLANK",
                "This optional field is blank.",
            )

        method = rule["validation_method"]

        if method == "identifier":
            return self._valid(field_name, value)

        if method == "numeric":
            return self._validate_numeric(field_name, value)

        if method == "allowed_values":
            return self._validate_allowed_values(rule, value)

        if method == "conditional_allowed_values":
            return self._validate_conditional_allowed_values(
                rule,
                rules,
                record,
                value,
            )

        if method == "manual_review":
            return field_result(
                field_name,
                value,
                MANUAL_REVIEW,
                "MANUAL_REVIEW_REQUIRED",
                "Review this free-text value before approving the record.",
            )

        return field_result(
            field_name,
            value,
            INVALID,
            "UNSUPPORTED_VALIDATION_METHOD",
            f"Validation method '{method}' is not supported.",
        )

    def _condition_is_active(self, rule, record):
        parent = rule.get("required_if_field")

        if not parent:
            return False

        return condition_matches(
            record,
            parent,
            rule["required_if_operator"],
            rule["required_if_value"],
        )

    def _validate_numeric(self, field_name, value):
        if type(value) is bool:
            return self._invalid_number(field_name, value)

        if type(value) in (int, float):
            return self._valid(field_name, value)

        if type(value) is str:
            try:
                float(value.strip())
                return self._valid(field_name, value)
            except ValueError:
                pass

        return self._invalid_number(field_name, value)

    def _validate_allowed_values(self, rule, value):
        field_name = rule["field_name"]
        allowed = rule["allowed_values"]

        if rule["input_type"] == "single_select":
            if value in allowed:
                return self._valid(field_name, value)

            return field_result(
                field_name,
                value,
                INVALID,
                "INVALID_SELECTION",
                f"'{value}' is not an allowed selection.",
                allowed,
            )

        if rule["input_type"] == "multi_select":
            if type(value) is not list:
                return field_result(
                    field_name,
                    value,
                    INVALID,
                    "MULTI_SELECT_MUST_BE_LIST",
                    "Multi-select values must be provided as a list.",
                    allowed,
                )

            invalid_values = [
                selection
                for selection in value
                if selection not in allowed
            ]

            if invalid_values:
                return field_result(
                    field_name,
                    value,
                    INVALID,
                    "INVALID_SELECTION",
                    "One or more selections are not allowed: "
                    + ", ".join(str(item) for item in invalid_values)
                    + ".",
                    allowed,
                )

            return self._valid(field_name, value)

        return field_result(
            field_name,
            value,
            INVALID,
            "INVALID_SELECT_CONFIGURATION",
            "Allowed-value validation requires a select field.",
        )

    def _validate_conditional_allowed_values(
        self,
        rule,
        rules,
        record,
        value,
    ):
        field_name = rule["field_name"]
        mapping = rule["conditional_allowed_values"]

        parent_rule = self._find_conditional_parent(
            rule,
            rules,
            mapping,
        )

        if parent_rule is None:
            return field_result(
                field_name,
                value,
                INVALID,
                "CONDITIONAL_PARENT_NOT_FOUND",
                "The dictionary does not contain a unique parent field "
                "for this conditional allowed-value rule.",
            )

        parent_field = parent_rule["field_name"]
        parent_value = record.get(parent_field)
        allowed = mapping.get(str(parent_value))

        if allowed is None:
            return field_result(
                field_name,
                value,
                INVALID,
                "NO_CONDITIONAL_OPTIONS",
                f"No allowed values are defined when "
                f"'{parent_field}' is '{parent_value}'.",
            )

        if value in allowed:
            return self._valid(field_name, value)

        return field_result(
            field_name,
            value,
            INVALID,
            "INVALID_CONDITIONAL_SELECTION",
            f"'{value}' is not allowed when "
            f"'{parent_field}' is '{parent_value}'.",
            allowed,
        )

    def _find_conditional_parent(self, child_rule, rules, mapping):
        """Find the parent rule from existing dictionary information.

        A conditional mapping's keys are parent values. We look backward from
        the child field and find the nearest earlier field whose allowed values
        contain every mapping key. This keeps the workbook unchanged and keeps
        the validator generic.
        """
        mapping_keys = set(str(key) for key in mapping)

        earlier_rules = [
            rule
            for rule in rules
            if rule["field_order"] < child_rule["field_order"]
        ]

        candidates = []

        for rule in earlier_rules:
            allowed = rule.get("allowed_values", [])
            allowed_as_text = set(str(value) for value in allowed)

            if mapping_keys and mapping_keys.issubset(allowed_as_text):
                candidates.append(rule)

        if not candidates:
            return None

        candidates.sort(
            key=lambda rule: rule["field_order"],
            reverse=True,
        )

        return candidates[0]

    def _check_unknown_fields(self, rules, record):
        known_fields = {
            rule["field_name"]
            for rule in rules
        }

        unknown = [
            field_name
            for field_name in record
            if field_name not in known_fields
        ]

        return [
            field_result(
                field_name,
                record[field_name],
                INVALID,
                "UNKNOWN_FIELD",
                "This field is not defined in the active metadata dictionary.",
            )
            for field_name in unknown
        ]

    def _build_summary(self, results):
        statuses = [
            VALID,
            INVALID,
            MISSING_REQUIRED,
            MANUAL_REVIEW,
            NOT_APPLICABLE,
        ]

        return {
            status: sum(
                result["status"] == status
                for result in results
            )
            for status in statuses
        }

    def _valid(self, field_name, value):
        return field_result(
            field_name,
            value,
            VALID,
            "VALID",
            "Value passed automatic validation.",
        )

    def _invalid_number(self, field_name, value):
        return field_result(
            field_name,
            value,
            INVALID,
            "INVALID_NUMBER",
            "Enter a numeric value without units.",
        )
