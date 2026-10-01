"""Small, reusable helpers for conditional metadata rules."""

from __future__ import annotations

import json


def is_blank(value):
    if value is None:
        return True

    if type(value) is str and value.strip() == "":
        return True

    if type(value) in (list, dict) and len(value) == 0:
        return True

    return False


def condition_matches(record, parent_field, operator, trigger_value):
    parent_value = record.get(parent_field)

    if operator == "is_blank":
        return is_blank(parent_value)

    if operator == "is_not_blank":
        return not is_blank(parent_value)

    if is_blank(parent_value):
        return False

    if operator == "equals":
        return parent_value == trigger_value

    if operator == "contains":
        return _contains(parent_value, trigger_value)

    if operator == "does_not_contain":
        return not _contains(parent_value, trigger_value)

    if operator == "contains_any":
        choices = _read_json_list(trigger_value)
        return any(
            _contains(parent_value, choice)
            for choice in choices
        )

    if operator == "in":
        choices = _read_json_list(trigger_value)
        return parent_value in choices

    return False


def applicable_repeat_selections(rule, record):
    parent = rule.get("repeat_for_each_field")

    if not parent:
        return []

    parent_value = record.get(parent)

    if is_blank(parent_value):
        return []

    selected = (
        list(parent_value)
        if type(parent_value) is list
        else [parent_value]
    )

    excluded = {
        str(value)
        for value in rule.get(
            "repeat_exclude_values",
            [],
        )
    }

    return [
        str(value)
        for value in selected
        if str(value) not in excluded
    ]


def _contains(value, expected):
    if type(value) is list:
        return expected in value

    if type(value) is str:
        return expected in value

    return False


def _read_json_list(value):
    if type(value) is list:
        return value

    try:
        parsed = json.loads(value)
    except Exception:
        return []

    if type(parsed) is list:
        return parsed

    return []


def completed_calendar_months(
    start_date,
    as_of_date=None,
):
    from datetime import date, datetime

    text = str(
        start_date or ""
    ).strip()

    if not text:
        return None

    try:
        start = datetime.strptime(
            text,
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return None

    if as_of_date is None:
        current = date.today()
    elif isinstance(
        as_of_date,
        datetime,
    ):
        current = as_of_date.date()
    elif isinstance(
        as_of_date,
        date,
    ):
        current = as_of_date
    else:
        try:
            current = datetime.strptime(
                str(as_of_date),
                "%Y-%m-%d",
            ).date()
        except ValueError:
            return None

    months = (
        current.year - start.year
    ) * 12 + (
        current.month - start.month
    )

    if current.day < start.day:
        months -= 1

    return max(
        months,
        0,
    )


def surgery_month_rule_is_available(
    rule,
    context=None,
):
    threshold = rule.get(
        "available_after_surgery_months"
    )

    if threshold in (
        None,
        "",
    ):
        return True

    actual_date = str(
        (context or {}).get(
            "actual_surgery_date",
            "",
        )
        or ""
    ).strip()

    if not actual_date:
        return False

    completed = completed_calendar_months(
        actual_date
    )

    if completed is None:
        return False

    return completed >= int(
        threshold
    )
