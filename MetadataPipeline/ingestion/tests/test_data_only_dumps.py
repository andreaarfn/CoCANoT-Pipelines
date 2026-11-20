"""Data-only vendor profiles: discovery and reads must agree, with no SQL execution."""
import tempfile
import unittest
from pathlib import Path
from MetadataPipeline.ingestion.sql_sources import list_source_tables, read_source_table
from MetadataPipeline.ingestion.file_loader import load_metadata_file


class DataOnlyDumpTests(unittest.TestCase):
    def source(self, root, name, sql):
        path = root / name
        path.write_text(sql, encoding="utf-8")
        return path

    def test_postgres_copy_with_nulls_unicode_and_escapes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(Path(folder), "clinical.pg.sql",
                "-- PostgreSQL database dump\n"
                "SET client_encoding = 'UTF8';\n"
                "SELECT pg_catalog.set_config('search_path', '', false);\n"
                "COPY public.clinical (patient_id, note) FROM stdin;\n"
                "001\tJosé\\tstable\n"
                "002\t\\N\n"
                "\\.\n"
                "SELECT pg_catalog.setval('clinical_id_seq', 2, true);\n")
            self.assertEqual(list_source_tables(path),
                             [{"name": "clinical", "row_count": 2}])
            self.assertEqual(read_source_table(path, "clinical"), [
                {"patient_id": "001", "note": "José\tstable"},
                {"patient_id": "002", "note": None}])
            self.assertEqual(len(load_metadata_file(path, "clinical")["rows"]), 2)

    def test_mysql_explicit_columns_multivalue_and_escapes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(Path(folder), "clinical.mysql.sql",
                "-- MySQL dump\n"
                "INSERT INTO \x60clinical\x60 (\x60patient_id\x60, \x60note\x60) VALUES "
                "('001', 'a\\'b'), ('002', NULL), ('003', 'line\\nnext');\n")
            self.assertEqual(list_source_tables(path),
                             [{"name": "clinical", "row_count": 3}])
            self.assertEqual(read_source_table(path, "clinical"), [
                {"patient_id": "001", "note": "a'b"},
                {"patient_id": "002", "note": None},
                {"patient_id": "003", "note": "line\nnext"}])

    def test_standard_dump_headers_trigger_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pg = self.source(root, "export.sql",
                "-- PostgreSQL database dump\\n"
                "COPY public.clinical (id) FROM stdin;\\n001\\n\\\\.\\n")
            self.assertEqual(read_source_table(pg, "clinical"), [{"id": "001"}])
            my = self.source(root, "export.sql",
                "-- MySQL dump 10.13\\n"
                "INSERT INTO clinical (id) VALUES ('001');")
            self.assertEqual(read_source_table(my, "clinical"), [{"id": "001"}])

    def test_multiple_postgres_tables_selected_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.source(Path(folder), "data.pg.sql",
                "COPY public.clinical (id) FROM stdin;\n001\n\\.\n"
                "COPY public.surgical (id) FROM stdin;\nS001\n\\.\n")
            self.assertEqual({x["name"] for x in list_source_tables(path)},
                             {"clinical", "surgical"})
            self.assertEqual(read_source_table(path, "surgical"), [{"id": "S001"}])

    def test_fail_closed_on_commands_or_bad_rows(self):
        samples = [
            ("bad.pg.sql", "COPY public.clinical (id) FROM stdin;\n001\n\\.\nDROP TABLE clinical;"),
            ("bad.pg.sql", "COPY public.clinical (id, note) FROM stdin;\n001\n\\.\n"),
            ("bad.mysql.sql", "INSERT INTO clinical (id) VALUES ('001'); DELETE FROM clinical;"),
            ("bad.mysql.sql", "INSERT INTO clinical (id) VALUES (NOW());"),
            ("bad.mysql.sql", "CREATE TABLE clinical (id TEXT);"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            for name, sql in samples:
                with self.subTest(sql=sql):
                    path = self.source(Path(folder), name, sql)
                    with self.assertRaises(ValueError):
                        list_source_tables(path)


if __name__ == "__main__":
    unittest.main()
