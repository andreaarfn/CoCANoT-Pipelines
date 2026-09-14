"""Electrophysiology metadata form definition."""

from __future__ import annotations

from .form_helpers import build_form_fields, merge_context_and_answers


TABLE_NAME = "Electrophysiology"


def build_ephys_form(dictionary, context=None):
    """Build UI-ready Ephys metadata fields from MR Electrophysiology."""
    return build_form_fields(
        dictionary=dictionary,
        table_name=TABLE_NAME,
        context=context,
    )


def build_ephys_record(context, answers):
    """Combine Ephys pipeline context with user-entered metadata."""
    return merge_context_and_answers(context, answers)
