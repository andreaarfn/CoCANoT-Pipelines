from pathlib import Path

from MetadataPipeline.validation.dictionary_loader import load_dictionary
from MetadataPipeline.validation.validator import MetadataValidator


DICTIONARY = (
    Path(__file__).resolve().parents[1]
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)


def make_validator():
    dictionary = load_dictionary(DICTIONARY)
    return MetadataValidator(dictionary)


def find_result(validation, field_name):
    return next(
        result for result in validation["results"]
        if result["field_name"] == field_name
    )


def valid_imaging_record():
    return {
        "CoCANoT Patient ID": "CCN-001",
        "Image ID": "IMG-001",
        "Clinical Assessment ID": "CA-001",
        "Imaging Modality": "CT",
        "Purpose of Imaging (multiselect)": ["Diagnostic evaluation"],
        "Timing Relative to Surgery": "Preoperative",
        "Imaging Findings (multiselect)": ["No structural abnormality identified"],
    }


def valid_clinical_record():
    return {
        "CoCANoT Patient ID": "CCN-001",
        "Clinical Assessment ID": "CA-001",
        "Race": "White",
        "Ethnicity": "Not Hispanic or Latino",
        "Sex": "Female",
        "Primary Payer": "Private",
        "Epilepsy Type": "Focal",
        "Etiology (multiselect)": ["Genetic or presumed genetic"],
        "Seizure Types (multiselect)": ["Unclassified"],
        "Syndrome\n(multiselect)": ["None"],
        "Age at Diagosis (years)": 12,
    }


def valid_surgical_record():
    return {
        "CoCANoT Patient ID": "CCN-001",
        "Surgery ID": "SURG-001",
        "Clinical Assessment ID": "CA-001",
        "Previous treatment surgery - including neuromodulation": "No",
        "Age at Surgery (years)": 20,
        "Intent of Surgery\n(multiselect)": ["Curative"],
        "Extraoperative Intracranial EEG (multiselect)": ["None"],
        "Intraoperative ECOG": "No",
        "Location of resection or device placement (multiselect)": ["N/A"],
        "Laterality of resection or device placement (multiselect)": ["N/A"],
        "Type(s) of surgery - non device (multiselect)": ["N/A (device only)"],
        "Type(s) of surgery (multiselect)": ["Intracranial EEG"],
        "Complications from surgery (multiselect)": ["None"],
        "Preoperative Baseline Observation Period (months)": 12,
        "Preoperative Baseline Total Seizure Count": 24,
    }


def test_valid_imaging_record_passes_automatic_validation():
    validator = make_validator()

    result = validator.validate_record("Imaging", valid_imaging_record())

    assert result["passes_automatic_validation"] is True
    assert result["requires_manual_review"] is False
    assert result["ready_for_approval"] is True


def test_conditional_field_is_not_applicable_when_trigger_is_false():
    validator = make_validator()

    result = validator.validate_record("Imaging", valid_imaging_record())
    field = find_result(
        result,
        "MRI Sequence(s) (if applicable)",
    )

    assert field["status"] == "not_applicable"


def test_conditional_field_becomes_required_when_trigger_is_true():
    validator = make_validator()
    record = valid_imaging_record()
    record["Imaging Modality"] = "MRI"

    result = validator.validate_record("Imaging", record)
    field = find_result(
        result,
        "MRI Sequence(s) (if applicable)",
    )

    assert field["status"] == "missing_required"


def test_valid_conditional_mri_sequence_passes():
    validator = make_validator()
    record = valid_imaging_record()
    record["Imaging Modality"] = "MRI"
    record["MRI Sequence(s) (if applicable)"] = "T1"

    result = validator.validate_record("Imaging", record)
    field = find_result(
        result,
        "MRI Sequence(s) (if applicable)",
    )

    assert field["status"] == "valid"


def test_invalid_single_select_fails():
    validator = make_validator()
    record = valid_imaging_record()
    record["Imaging Modality"] = "PET"

    result = validator.validate_record("Imaging", record)
    field = find_result(result, "Imaging Modality")

    assert field["status"] == "invalid"
    assert field["code"] == "INVALID_SELECTION"


def test_invalid_multiselect_value_fails():
    validator = make_validator()
    record = valid_imaging_record()
    record["Imaging Findings (multiselect)"] = [
        "No structural abnormality identified",
        "Made-up finding",
    ]

    result = validator.validate_record("Imaging", record)
    field = find_result(result, "Imaging Findings (multiselect)")

    assert field["status"] == "invalid"
    assert "Made-up finding" in field["message"]


def test_multiselect_must_be_a_list():
    validator = make_validator()
    record = valid_imaging_record()
    record["Purpose of Imaging (multiselect)"] = "Diagnostic evaluation"

    result = validator.validate_record("Imaging", record)
    field = find_result(result, "Purpose of Imaging (multiselect)")

    assert field["status"] == "invalid"
    assert field["code"] == "MULTI_SELECT_MUST_BE_LIST"


def test_missing_required_field_is_reported():
    validator = make_validator()
    record = valid_imaging_record()
    del record["Image ID"]

    result = validator.validate_record("Imaging", record)
    field = find_result(result, "Image ID")

    assert field["status"] == "missing_required"
    assert result["passes_automatic_validation"] is False


def test_free_text_is_sent_to_manual_review():
    validator = make_validator()
    record = valid_imaging_record()
    record["Purpose of Imaging (multiselect)"] = ["Other"]
    record["Other Purpose of Imaging (if applicable; free text)"] = "Research protocol"

    result = validator.validate_record("Imaging", record)
    field = find_result(
        result,
        "Other Purpose of Imaging (if applicable; free text)",
    )

    assert field["status"] == "manual_review"
    assert result["passes_automatic_validation"] is True
    assert result["requires_manual_review"] is True
    assert result["ready_for_approval"] is False


def test_conditional_free_text_is_required_when_other_is_selected():
    validator = make_validator()
    record = valid_imaging_record()
    record["Purpose of Imaging (multiselect)"] = ["Other"]

    result = validator.validate_record("Imaging", record)
    field = find_result(
        result,
        "Other Purpose of Imaging (if applicable; free text)",
    )

    assert field["status"] == "missing_required"


def test_value_is_rejected_when_conditional_field_does_not_apply():
    validator = make_validator()
    record = valid_imaging_record()
    record["Other Purpose of Imaging (if applicable; free text)"] = "Should not be here"

    result = validator.validate_record("Imaging", record)
    field = find_result(
        result,
        "Other Purpose of Imaging (if applicable; free text)",
    )

    assert field["status"] == "invalid"
    assert field["code"] == "VALUE_NOT_APPLICABLE"


def test_unknown_column_is_rejected():
    validator = make_validator()
    record = valid_imaging_record()
    record["Mystery Column"] = "abc"

    result = validator.validate_record("Imaging", record)
    field = find_result(result, "Mystery Column")

    assert field["status"] == "invalid"
    assert field["code"] == "UNKNOWN_FIELD"


def test_numeric_string_is_accepted():
    validator = make_validator()
    record = valid_clinical_record()
    record["Age at Diagosis (years)"] = "12.5"

    result = validator.validate_record("Clinical", record)
    field = find_result(result, "Age at Diagosis (years)")

    assert field["status"] == "valid"


def test_non_numeric_value_is_rejected():
    validator = make_validator()
    record = valid_clinical_record()
    record["Age at Diagosis (years)"] = "twelve"

    result = validator.validate_record("Clinical", record)
    field = find_result(result, "Age at Diagosis (years)")

    assert field["status"] == "invalid"
    assert field["code"] == "INVALID_NUMBER"


def test_clinical_nested_dependency_is_enforced():
    validator = make_validator()
    record = valid_clinical_record()
    record["Etiology (multiselect)"] = ["Structural"]

    result = validator.validate_record("Clinical", record)
    field = find_result(result, "Structural Etiology (multiselect)")

    assert field["status"] == "missing_required"


def test_valid_engel_subtype_passes_for_parent_outcome():
    validator = make_validator()
    record = valid_surgical_record()
    record["12-Month Engel Outcome"] = "II"
    record["12-Month Engel Outcome Subtype (if available)"] = "IIA"

    result = validator.validate_record("Surgical", record)
    field = find_result(
        result,
        "12-Month Engel Outcome Subtype (if available)",
    )

    assert field["status"] == "valid"


def test_wrong_engel_subtype_fails_for_parent_outcome():
    validator = make_validator()
    record = valid_surgical_record()
    record["12-Month Engel Outcome"] = "II"
    record["12-Month Engel Outcome Subtype (if available)"] = "IVA"

    result = validator.validate_record("Surgical", record)
    field = find_result(
        result,
        "12-Month Engel Outcome Subtype (if available)",
    )

    assert field["status"] == "invalid"
    assert field["code"] == "INVALID_CONDITIONAL_SELECTION"
    assert field["allowed_values"] == ["IIA", "IIB", "IIC", "IID"]


def test_death_has_no_engel_subtype_options():
    validator = make_validator()
    record = valid_surgical_record()
    record["12-Month Engel Outcome"] = "Death"
    record["12-Month Engel Outcome Subtype (if available)"] = "IA"

    result = validator.validate_record("Surgical", record)
    field = find_result(
        result,
        "12-Month Engel Outcome Subtype (if available)",
    )

    assert field["status"] == "invalid"
    assert field["allowed_values"] == []


def test_optional_blank_engel_subtype_is_allowed():
    validator = make_validator()
    record = valid_surgical_record()
    record["12-Month Engel Outcome"] = "II"

    result = validator.validate_record("Surgical", record)
    field = find_result(
        result,
        "12-Month Engel Outcome Subtype (if available)",
    )

    assert field["status"] == "valid"
    assert field["code"] == "OPTIONAL_BLANK"


def test_summary_counts_statuses():
    validator = make_validator()
    record = valid_imaging_record()

    result = validator.validate_record("Imaging", record)

    assert result["summary"]["invalid"] == 0
    assert result["summary"]["missing_required"] == 0
    assert result["summary"]["not_applicable"] >= 1
