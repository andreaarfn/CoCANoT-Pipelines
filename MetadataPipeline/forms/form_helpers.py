"""Shared helpers for Imaging and Electrophysiology metadata forms.

These helpers do not render a specific UI framework. They prepare clean,
UI-ready field definitions from the active machine-readable dictionary.

Imaging and Ephys keep separate form modules so each pipeline can control its
own layout and workflow without duplicating dictionary logic.
"""

from __future__ import annotations

from MetadataPipeline.validation.conditions import condition_matches


def build_form_fields(dictionary, table_name, context=None):
    """Return ordered, UI-ready field definitions for one metadata table."""
    context = context or {}

    if table_name not in dictionary["tables"]:
        raise ValueError(f"Unknown metadata table '{table_name}'.")

    rules = dictionary["tables"][table_name]["fields"]

    fields = []

    for rule in rules:
        fields.append(
            _build_field(rule, context)
        )

    return fields


def visible_form_fields(fields, answers):
    """Return only fields that currently apply based on existing answers."""
    visible = []

    for field in fields:
        if field_is_visible(field, answers):
            visible.append(field)

    return visible


def field_is_visible(field, answers):
    """Determine whether a conditionally applicable field should be shown."""
    parent = field.get("required_if_field")

    if not parent:
        return True

    return condition_matches(
        answers,
        parent,
        field["required_if_operator"],
        field["required_if_value"],
    )


def merge_context_and_answers(context, answers):
    """Combine pipeline-provided values with user-entered form answers."""
    record = {}

    for key, value in (context or {}).items():
        record[key] = value

    for key, value in (answers or {}).items():
        record[key] = value

    return record


def _build_field(rule, context):
    field_name = rule["field_name"]

    return {
        "field_order": rule["field_order"],
        "field_name": field_name,
        "label": rule["ui_prompt"],
        "help_text": rule.get("help_text") or "",
        "input_type": rule["input_type"],
        "allowed_values": list(rule.get("allowed_values", [])),
        "required": rule["required"],
        "required_if_field": rule.get("required_if_field"),
        "required_if_operator": rule.get("required_if_operator"),
        "required_if_value": rule.get("required_if_value"),
        "manual_review_required": rule["manual_review_required"],
        "system_generated": rule["system_generated"],
        "prefilled_value": context.get(field_name),
        "read_only": field_name in context or rule["system_generated"],
    }
