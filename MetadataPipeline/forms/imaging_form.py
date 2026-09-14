"""Imaging metadata form definition."""

from __future__ import annotations

from .form_helpers import build_form_fields, merge_context_and_answers


TABLE_NAME = "Imaging"


def build_imaging_form(dictionary, context=None):
    """Build UI-ready Imaging metadata fields from MR Imaging."""
    return build_form_fields(
        dictionary=dictionary,
        table_name=TABLE_NAME,
        context=context,
    )


def build_imaging_record(context, answers):
    """Combine Imaging pipeline context with user-entered metadata."""
    return merge_context_and_answers(context, answers)
