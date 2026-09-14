from MetadataPipeline.validation.conditions import condition_matches


def test_equals_operator():
    record = {"Imaging Modality": "MRI"}

    assert condition_matches(
        record,
        "Imaging Modality",
        "equals",
        "MRI",
    ) is True


def test_contains_operator_with_multiselect():
    record = {"Purpose": ["Diagnostic", "Other"]}

    assert condition_matches(
        record,
        "Purpose",
        "contains",
        "Other",
    ) is True


def test_does_not_contain_operator():
    record = {"Type of device": ["RNS placement"]}

    assert condition_matches(
        record,
        "Type of device",
        "does_not_contain",
        "No device",
    ) is True


def test_contains_any_operator():
    record = {"Surgery": ["Laser Corpus callosotomy"]}

    assert condition_matches(
        record,
        "Surgery",
        "contains_any",
        '["Open Corpus callosotomy", "Laser Corpus callosotomy"]',
    ) is True


def test_in_operator():
    record = {"Outcome": "II"}

    assert condition_matches(
        record,
        "Outcome",
        "in",
        '["I", "II", "III", "IV"]',
    ) is True
