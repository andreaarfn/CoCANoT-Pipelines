"""Regression coverage for the shared metadata reader registry."""
import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from MetadataPipeline.ingestion.file_loader import load_metadata_file
from MetadataPipeline.ingestion.readers import (
    CSVReader, XLSXReader, SQLReader, SQLiteReader, get_reader,
)
from MetadataPipeline.ingestion.sql_sources import list_source_tables, read_source_table


class MetadataReaderTests(unittest.TestCase):
    def test_extension_registry(self):
        cases = {
            "clinical.CSV": CSVReader,
            "clinical.xlsx": XLSXReader,
            "clinical.xlsm": XLSXReader,
            "clinical.sql": SQLReader,
            "clinical.db": SQLiteReader,
            "clinical.sqlite": SQLiteReader,
            "clinical.sqlite3": SQLiteReader,
        }
        for name, reader_type in cases.items():
            with self.subTest(name=name):
                self.assertIsInstance(get_reader(name), reader_type)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            get_reader("clinical.exe")

    def test_csv_and_excel_share_output_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            csv_path = root / "clinical.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Patient ID", "Visit"])
                writer.writerow(["001", "V1"])
                writer.writerow(["", ""])
            xlsx_path = root / "clinical.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Patient ID", "Visit"])
            sheet.append(["001", "V1"])
            sheet.append([None, None])
            workbook.save(xlsx_path)

            for path in (csv_path, xlsx_path):
                with self.subTest(path=path.name):
                    loaded = load_metadata_file(path)
                    self.assertEqual(loaded["columns"], ["Patient ID", "Visit"])
                    self.assertEqual(loaded["rows"], [{"Patient ID": "001", "Visit": "V1"}])
                    self.assertEqual(loaded["source_file"], str(path))
                    self.assertIn("sheet_name", loaded)

    def test_sql_and_sqlite_share_output_contract_and_table_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sql_path = root / "clinical.sql"
            sql_path.write_text(
                "INSERT INTO clinical (id, visit) VALUES ('001', 'V1');",
                encoding="utf-8",
            )
            sqlite_path = root / "clinical.sqlite"
            with sqlite3.connect(sqlite_path) as connection:
                connection.execute("CREATE TABLE clinical (id TEXT, visit TEXT)")
                connection.execute("INSERT INTO clinical VALUES (?, ?)", ("001", "V1"))
            for path in (sql_path, sqlite_path):
                with self.subTest(path=path.name):
                    self.assertEqual(list_source_tables(path)[0]["name"], "clinical")
                    self.assertEqual(
                        read_source_table(path, "clinical"),
                        [{"id": "001", "visit": "V1"}],
                    )
                    loaded = load_metadata_file(path, table_name="clinical")
                    self.assertEqual(loaded["columns"], ["id", "visit"])
                    self.assertEqual(loaded["rows"], [{"id": "001", "visit": "V1"}])
                    self.assertEqual(loaded["source_table"], "clinical")
                    with self.assertRaises(ValueError):
                        load_metadata_file(path)

    def test_sql_unsafe_statements_are_rejected_through_reader(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unsafe.sql"
            path.write_text("DROP TABLE clinical;", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not supported"):
                get_reader(path).list_tables(path)


if __name__ == "__main__":
    unittest.main()
