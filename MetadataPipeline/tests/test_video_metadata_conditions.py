"""Regression tests for conditional fields in MR Video Step 4."""

from MetadataPipeline.validation.conditions import prune_inapplicable_fields


def rules():
    # Representative MR Video dictionary rows; field names are not embedded in
    # pruning logic and may change with a future dictionary version.
    return [
        {"field_name": "Seizure Captured (if applicable)"},
        {
            "field_name": "Number of Seizures Captured (if applicable)",
            "required_if_field": "Seizure Captured (if applicable)",
            "required_if_operator": "equals",
            "required_if_value": "Yes",
        },
        {
            "field_name": "Seizure Start Times (seconds; repeated)",
            "required_if_field": "Seizure Captured (if applicable)",
            "required_if_operator": "equals",
            "required_if_value": "Yes",
        },
        {
            "field_name": "Seizure End Times (seconds; repeated)",
            "required_if_field": "Seizure Captured (if applicable)",
            "required_if_operator": "equals",
            "required_if_value": "Yes",
        },
        {"field_name": "Comments (free text)"},
    ]


def test_no_seizure_clears_all_inactive_seizure_details():
    record = {
        "Seizure Captured (if applicable)": "No",
        "Number of Seizures Captured (if applicable)": "2",
        "Seizure Start Times (seconds; repeated)": ["10", "20"],
        "Seizure End Times (seconds; repeated)": ["12", "22"],
        "Comments (free text)": "Unrelated comment",
    }
    result = prune_inapplicable_fields(record, rules())
    assert result == {
        "Seizure Captured (if applicable)": "No",
        "Comments (free text)": "Unrelated comment",
    }
    assert "Number of Seizures Captured (if applicable)" in record


def test_yes_preserves_applicable_seizure_values():
    record = {
        "Seizure Captured (if applicable)": "Yes",
        "Number of Seizures Captured (if applicable)": "2",
    }
    assert prune_inapplicable_fields(record, rules()) == record


def test_chained_conditions_are_pruned_until_stable():
    chained = [
        {
            "field_name": "Grandchild",
            "required_if_field": "Child",
            "required_if_operator": "equals",
            "required_if_value": "Yes",
        },
        {
            "field_name": "Child",
            "required_if_field": "Parent",
            "required_if_operator": "equals",
            "required_if_value": "Yes",
        },
        {"field_name": "Parent"},
    ]
    assert prune_inapplicable_fields(
        {"Parent": "No", "Child": "Yes", "Grandchild": "persisted"},
        chained,
    ) == {"Parent": "No"}


def test_repeat_for_each_clears_when_no_applicable_choices_remain():
    ruleset = [
        {"field_name": "Selections"},
        {
            "field_name": "Repeated",
            "repeat_for_each_field": "Selections",
            "repeat_exclude_values": ["Unknown"],
        },
    ]
    assert prune_inapplicable_fields(
        {"Selections": ["Unknown"], "Repeated": {"Other": "stale"}},
        ruleset,
    ) == {"Selections": ["Unknown"]}
