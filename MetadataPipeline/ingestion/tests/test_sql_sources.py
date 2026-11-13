"""Safe SQL and SQLite metadata bulk import regression tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from MetadataPipeline.ingestion.sql_sources import list_source_tables, read_source_table


class SqlMetadataImportTests(unittest.TestCase):
    def test_sql_script_extracts_values_without_executing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "should_not_exist"
            sql = root / "clinical.sql"
            sql.write_text(
                "CREATE TABLE clinical (\"CoCANoT Patient ID\" TEXT, \"Clinical Assessment ID\" TEXT);\n"
                "BEGIN TRANSACTION;\n"
                "INSERT INTO clinical VALUES ('001', 'CA-001'), ('002', 'CA-002');\n"
                "COMMIT;\n",
                encoding="utf-8",
            )
            self.assertEqual(list_source_tables(sql), [{"name": "clinical", "row_count": 2}])
            rows = read_source_table(sql, "clinical")
            self.assertEqual(rows[0]["CoCANoT Patient ID"], "001")
            self.assertEqual(rows[1]["Clinical Assessment ID"], "CA-002")
            self.assertFalse(marker.exists())

    def test_sql_script_rejects_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            sql = Path(directory) / "unsafe.sql"
            sql.write_text("DROP TABLE clinical;", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not supported"):
                list_source_tables(sql)

    def test_sql_script_rejects_expressions(self):
        with tempfile.TemporaryDirectory() as directory:
            sql = Path(directory) / "functions.sql"
            sql.write_text("INSERT INTO clinical (id) VALUES (random());", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_source_table(sql, "clinical")

    def test_sql_script_handles_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            sql = Path(directory) / "quotes.sql"
            sql.write_text(
                "-- imported records\n"
                "INSERT INTO clinical (\"Patient ID\", note) VALUES ('001', 'Patient''s note; no execute');",
                encoding="utf-8",
            )
            self.assertEqual(
                read_source_table(sql, "clinical")[0]["note"],
                "Patient's note; no execute",
            )

    def test_sqlite_reads_without_mutating_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clinical.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE clinical ("CoCANoT Patient ID" TEXT, id TEXT)')
                db.execute('INSERT INTO clinical VALUES (?, ?)', ("001", "CA-001"))
                db.execute('CREATE TABLE surgical (id TEXT)')
            self.assertEqual(
                {entry["name"] for entry in list_source_tables(path)},
                {"clinical", "surgical"},
            )
            self.assertEqual(read_source_table(path, "clinical")[0]["id"], "CA-001")
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM clinical").fetchone()[0], 1)

    def test_sqlite_rejects_unknown_table(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clinical.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE clinical (id TEXT)")
            with self.assertRaisesRegex(ValueError, "unavailable"):
                read_source_table(path, "does_not_exist")


if __name__ == "__main__":
    unittest.main()
