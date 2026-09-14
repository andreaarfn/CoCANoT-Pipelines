from pathlib import Path

from MetadataPipeline.forms import (
    build_ephys_form,
    build_imaging_form,
    field_is_visible,
)
from MetadataPipeline.validation.dictionary_loader import load_dictionary


DICTIONARY = (
    Path(__file__).resolve().parents[1]
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)


def load_rules():
    return load_dictionary(DICTIONARY)


def find_field(fields, field_name):
    return next(
        field for field in fields
        if field["field_name"] == field_name
    )


def test_imaging_form_uses_mr_imaging_rules():
    dictionary = load_rules()

    fields = build_imaging_form(dictionary)

    assert len(fields) == 12
    assert fields[0]["field_name"] == "CoCANoT Patient ID"
    assert fields[-1]["field_name"] == "Comments (free text)"


def test_imaging_context_prefills_and_locks_known_values():
    dictionary = load_rules()
    context = {
        "CoCANoT Patient ID": "CCN-001",
        "Image ID": "IMG-001",
    }

    fields = build_imaging_form(dictionary, context)
    patient = find_field(fields, "CoCANoT Patient ID")
    image = find_field(fields, "Image ID")

    assert patient["prefilled_value"] == "CCN-001"
    assert patient["read_only"] is True
    assert image["prefilled_value"] == "IMG-001"
    assert image["read_only"] is True


def test_mri_sequences_only_show_when_modality_is_mri():
    dictionary = load_rules()
    fields = build_imaging_form(dictionary)
    mri_sequences = find_field(
        fields,
        "MRI Sequence(s) (if applicable)",
    )

    assert field_is_visible(
        mri_sequences,
        {"Imaging Modality": "MRI"},
    ) is True

    assert field_is_visible(
        mri_sequences,
        {"Imaging Modality": "CT"},
    ) is False


def test_ephys_form_uses_mr_electrophysiology_rules():
    dictionary = load_rules()

    fields = build_ephys_form(dictionary)

    assert len(fields) == 36
    assert fields[0]["field_name"] == "CoCANoT Patient ID"
    assert fields[-1]["field_name"] == "Comments (free text)"


def test_thalamic_fields_only_show_when_thalamus_recorded():
    dictionary = load_rules()
    fields = build_ephys_form(dictionary)
    field = find_field(
        fields,
        "Thalamic Nuclei Recorded (if applicable; multiselect)",
    )

    assert field_is_visible(
        field,
        {"Thalamus Recorded": "Yes"},
    ) is True

    assert field_is_visible(
        field,
        {"Thalamus Recorded": "No"},
    ) is False
