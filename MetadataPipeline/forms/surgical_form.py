"""Surgical metadata form definition."""

from __future__ import annotations

from .form_helpers import build_form_fields, merge_context_and_answers


TABLE_NAME = "Surgical"


def build_surgical_form(dictionary, context=None):
    """Build UI-ready Surgical metadata fields from MR Surgical."""
    return build_form_fields(
        dictionary=dictionary,
        table_name=TABLE_NAME,
        context=context,
    )


def build_surgical_record(context, answers):
    """Combine existing context with user-entered Surgical metadata."""
    return merge_context_and_answers(
        context,
        answers,
    )
