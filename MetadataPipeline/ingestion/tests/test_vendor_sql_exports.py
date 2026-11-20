"""Supported SQL text-export dialect fixtures; scripts must never be executed."""
import tempfile
import unittest
from pathlib import Path

from MetadataPipeline.ingestion.sql_sources import list_source_tables, read_source_table


class VendorSqlExportTests(unittest.TestCase):
    def _read(self, sql):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.sql"
            path.write_text(sql, encoding="utf-8")
            tables = list_source_tables(path)
            self.assertEqual(len(tables), 1)
            return read_source_table(path, tables[0]["name"])

    def test_postgresql_copy_text_rows(self):
        sql = (
            "COPY public.clinical (patient_id, note) FROM stdin;\n"
            "001\tPatient\\tstable\n"
            "002\t\\N\n"
            "\\.\n"
        )
        rows = self._read(sql)
        self.assertEqual(rows, [
            {"patient_id": "001", "note": "Patient\tstable"},
            {"patient_id": "002", "note": None},
        ])

    def test_mysql_extended_insert_and_engine(self):
        rows = self._read(
            "SET NAMES utf8mb4;\n"
            "CREATE TABLE \`clinical\` (\`id\` varchar(20), \`note\` text) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
            "INSERT INTO \`clinical\` VALUES ('001','stable'),('002','followup');"
        )
        self.assertEqual(rows[1]["id"], "002")

    def test_sql_server_dbo_unicode_and_go(self):
        rows = self._read(
            "SET ANSI_NULLS ON\nGO\n"
            "SET QUOTED_IDENTIFIER ON\nGO\n"
            "SET IDENTITY_INSERT [dbo].[clinical] ON;\n"
            "INSERT INTO [dbo].[clinical] ([id], [note]) VALUES (N'001', N'Hello');\n"
            "GO\nSET IDENTITY_INSERT [dbo].[clinical] OFF;\n"
        )
        self.assertEqual(rows, [{"id": "001", "note": "Hello"}])

    def test_oracle_simple_insert_all(self):
        rows = self._read(
            "INSERT ALL\n"
            " INTO clinical (id, visit) VALUES ('001', 'V1')\n"
            " INTO clinical (id, visit) VALUES ('002', 'V2')\n"
            " SELECT 1 FROM DUAL;\n"
            "/\n"
        )
        self.assertEqual(len(rows), 2)

    def test_no_execution_and_fail_closed(self):
        for script in (
            "DROP TABLE clinical;",
            "INSERT INTO clinical (id) VALUES (NOW());",
            "COPY clinical (id) FROM '/etc/passwd';",
            "INSERT INTO clinical (id) SELECT id FROM users;",
        ):
            with self.subTest(script=script), self.assertRaises(ValueError):
                self._read(script)


if __name__ == "__main__":
    unittest.main()
