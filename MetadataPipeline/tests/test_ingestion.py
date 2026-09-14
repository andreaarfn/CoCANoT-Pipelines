from pathlib import Path

import csv
import openpyxl
import pytest

from MetadataPipeline.ingestion import (
    TableDetectionError,
    detect_upload_table,
    load_metadata_file,
    normalize_record,
    validate_uploaded_metadata,
)
from MetadataPipeline.validation.dictionary_loader import load_dictionary


DICTIONARY = (
    Path(__file__).resolve().parents[1]
    / "dictionaries"
    / "CoCANoT_Metadata_Phase1.xlsx"
)


def load_rules():
    return load_dictionary(DICTIONARY)


def clinical_record():
    return {
        "CoCANoT Patient ID": "CCN-001",
        "Clinical Assessment ID": "CA-001",
        "Race": "White",
        "Ethnicity": "Not Hispanic or Latino",
        "Sex": "Female",
        "Primary Payer": "Private",
        "Epilepsy Type": "Focal",
        "Etiology (multiselect)": "Genetic or presumed genetic",
        "Seizure Types (multiselect)": "Unclassified",
        "Syndrome\n(multiselect)": "None",
        "Age at Diagosis (years)": "12",
    }


def surgical_record():
    return {
        "CoCANoT Patient ID": "CCN-001",
        "Surgery ID": "SURG-001",
        "Clinical Assessment ID": "CA-001",
        "Previous treatment surgery - including neuromodulation": "No",
        "Age at Surgery (years)": 20,
        "Intent of Surgery\n(multiselect)": "Curative",
        "Extraoperative Intracranial EEG (multiselect)": "None",
        "Intraoperative ECOG": "No",
        "Location of resection or device placement (multiselect)": "N/A",
        "Laterality of resection or device placement (multiselect)": "N/A",
        "Type(s) of surgery - non device (multiselect)": "N/A (device only)",
        "Type(s) of surgery (multiselect)": "Intracranial EEG",
        "Complications from surgery (multiselect)": "None",
        "Preoperative Baseline Observation Period (months)": 12,
        "Preoperative Baseline Total Seizure Count": 24,
    }


def write_csv(path, record):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(record))
        writer.writeheader()
        writer.writerow(record)


def write_xlsx(path, record):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Metadata"

    columns = list(record)
    sheet.append(columns)
    sheet.append([record[column] for column in columns])

    workbook.save(path)


def test_csv_loader_preserves_columns_and_rows(tmp_path):
    path = tmp_path / "clinical.csv"
    record = clinical_record()
    write_csv(path, record)

    loaded = load_metadata_file(path)

    assert loaded["columns"] == list(record)
    assert len(loaded["rows"]) == 1


def test_xlsx_loader_preserves_columns_and_rows(tmp_path):
    path = tmp_path / "surgical.xlsx"
    record = surgical_record()
    write_xlsx(path, record)

    loaded = load_metadata_file(path)

    assert loaded["columns"] == list(record)
    assert len(loaded["rows"]) == 1


def test_detects_clinical_upload():
    dictionary = load_rules()
    columns = list(clinical_record())

    assert detect_upload_table(dictionary, columns) == "Clinical"


def test_detects_surgical_upload():
    dictionary = load_rules()
    columns = list(surgical_record())

    assert detect_upload_table(dictionary, columns) == "Surgical"


def test_normalizes_semicolon_multiselect():
    dictionary = load_rules()
    record = clinical_record()
    record["Etiology (multiselect)"] = "Structural;Genetic or presumed genetic"

    normalized = normalize_record(
        dictionary,
        "Clinical",
        record,
    )

    assert normalized["Etiology (multiselect)"] == [
        "Structural",
        "Genetic or presumed genetic",
    ]


def test_normalizes_json_multiselect():
    dictionary = load_rules()
    record = clinical_record()
    record["Seizure Types (multiselect)"] = '["Unclassified"]'

    normalized = normalize_record(
        dictionary,
        "Clinical",
        record,
    )

    assert normalized["Seizure Types (multiselect)"] == ["Unclassified"]


def test_clinical_csv_runs_through_validator(tmp_path):
    dictionary = load_rules()
    path = tmp_path / "clinical.csv"
    write_csv(path, clinical_record())

    result = validate_uploaded_metadata(
        dictionary,
        path,
    )

    assert result["table_name"] == "Clinical"
    assert result["row_count"] == 1
    assert result["rows"][0]["validation"]["passes_automatic_validation"] is True


def test_surgical_xlsx_runs_through_validator(tmp_path):
    dictionary = load_rules()
    path = tmp_path / "surgical.xlsx"
    write_xlsx(path, surgical_record())

    result = validate_uploaded_metadata(
        dictionary,
        path,
    )

    assert result["table_name"] == "Surgical"
    assert result["row_count"] == 1
    assert result["rows"][0]["validation"]["passes_automatic_validation"] is True


def test_imaging_is_not_a_normal_upload_table():
    dictionary = load_rules()

    imaging_columns = [
        rule["field_name"]
        for rule in dictionary["tables"]["Imaging"]["fields"]
        if rule["required"]
    ]

    with pytest.raises(TableDetectionError):
        detect_upload_table(
            dictionary,
            imaging_columns,
        )
