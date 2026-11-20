"""End-to-end SQL export parity checks using real pg_dump and mysqldump files.

All records are synthetic. Never use real patient identifiers or PHI in CI.
"""
import json
import sys
import unittest
from pathlib import Path

from MetadataPipeline.ingestion.sql_sources import list_source_tables, read_source_table
from MetadataPipeline.ingestion.record_normalizer import normalize_record
from MetadataPipeline.validation.dictionary_loader import load_dictionary
from MetadataPipeline.validation.validator import MetadataValidator

ROOT = Path(__file__).resolve().parents[3]
DICTIONARY = ROOT / "MetadataPipeline/dictionaries/CoCANoT_Metadata_Phase1.0.xlsx"
DATA_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".test-sql-exports"

EXPECTED = {
    "clinical": [
        {"CoCANoT Patient ID": "000123", "Race": "Other",
         "Other Race (if applicable; free text)": "Synthetic label, O'Brien; \n日本語",
         "Etiology (multiselect)": "Structural",
         "Structural Etiology (multiselect)": "Stroke"},
        {"CoCANoT Patient ID": "000124", "Race": "White",
         "Other Race (if applicable; free text)": None,
         "Etiology (multiselect)": "Unknown",
         "Structural Etiology (multiselect)": None},
    ],
    "surgical": [
        {"CoCANoT Patient ID": "000123", "Surgery ID": "SUR-001",
         "Location of resection or device placement (multiselect)": "Frontal",
         "Laterality of resection or device placement (multiselect)": "Left"},
        {"CoCANoT Patient ID": "000124", "Surgery ID": "SUR-002",
         "Location of resection or device placement (multiselect)": "N/A",
         "Laterality of resection or device placement (multiselect)": None},
    ],
}


class RealExportParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dictionary = load_dictionary(DICTIONARY)
        cls.validator = MetadataValidator(cls.dictionary)

    def check_export(self, path):
        self.assertTrue(path.is_file(), f"Missing official database export: {path}")
        tables = list_source_tables(path)
        self.assertEqual({x["name"] for x in tables}, set(EXPECTED))
        for name, expected in EXPECTED.items():
            with self.subTest(path=path.name, table=name):
                self.assertEqual(next(x["row_count"] for x in tables if x["name"] == name), len(expected))
                parsed = read_source_table(path, name)
                self.assertEqual(parsed, expected,
                    "Data differs from authoritative synthetic source: " + path.name)
                table = "Clinical" if name == "clinical" else "Surgical"
                for record in parsed:
                    normalized = normalize_record(self.dictionary, table, record)
                    validation = self.validator.validate_record(table, normalized)
                    results = {x["field_name"]: x for x in validation["results"]}
                    if name == "clinical":
                        other = "Other Race (if applicable; free text)"
                        structural = "Structural Etiology (multiselect)"
                        if record["Race"] == "Other":
                            self.assertEqual(results[other]["status"], "manual_review")
                            self.assertNotEqual(results[structural]["status"], "missing_required")
                        else:
                            self.assertEqual(results[other]["status"], "not_applicable")
                            self.assertEqual(results[structural]["status"], "not_applicable")
                    else:
                        laterality = "Laterality of resection or device placement (multiselect)"
                        if record["Location of resection or device placement (multiselect)"] == "N/A":
                            self.assertEqual(results[laterality]["status"], "not_applicable")
                        else:
                            self.assertNotEqual(results[laterality]["status"], "missing_required")

    def test_postgres_export_parity(self):
        self.check_export(DATA_DIR / "postgres.pg.sql")

    def test_mysql_export_parity(self):
        self.check_export(DATA_DIR / "mysql.mysql.sql")

    def test_validation_conditions_change_outcome(self):
        clinical = "Clinical"
        r = {
            "CoCANoT Patient ID": "000123",
            "Race": "Other",
            "Etiology (multiselect)": ["Structural"],
        }
        results = self.validator.validate_record(clinical, r)["results"]
        statuses = {x["field_name"]: x["status"] for x in results}
        self.assertEqual(statuses["Other Race (if applicable; free text)"], "missing_required")
        self.assertEqual(statuses["Structural Etiology (multiselect)"], "missing_required")

        r["Other Race (if applicable; free text)"] = "Synthetic other"
        r["Structural Etiology (multiselect)"] = ["Stroke"]
        results = self.validator.validate_record(clinical, r)["results"]
        statuses = {x["field_name"]: x["status"] for x in results}
        self.assertEqual(statuses["Other Race (if applicable; free text)"], "manual_review")
        self.assertEqual(statuses["Structural Etiology (multiselect)"], "valid")

        surgical = "Surgical"
        s = {"CoCANoT Patient ID": "000123", "Surgery ID": "SUR-001",
             "Location of resection or device placement (multiselect)": ["Frontal"]}
        status = {x["field_name"]: x["status"] for x in
                  self.validator.validate_record(surgical, s)["results"]}
        self.assertEqual(status["Laterality of resection or device placement (multiselect)"], "missing_required")
        s["Location of resection or device placement (multiselect)"] = ["N/A"]
        status = {x["field_name"]: x["status"] for x in
                  self.validator.validate_record(surgical, s)["results"]}
        self.assertEqual(status["Laterality of resection or device placement (multiselect)"], "not_applicable")


if __name__ == "__main__":
    # Not part of the generic unittest discovery; runs after real dumps are created.
    unittest.main(argv=[sys.argv[0]], verbosity=2)
