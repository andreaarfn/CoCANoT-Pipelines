"""Format-specific metadata readers behind one small, extensible registry.

Readers only parse source data. Dictionary mapping, validation, preview and
commit remain in their existing shared pipelines.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class MetadataReader(ABC):
    """Contract shared by every supported import source."""

    extensions: tuple[str, ...] = ()

    @abstractmethod
    def read(self, path: Path, table_name: str | None = None) -> dict:
        """Return source_file, sheet_name, columns and rows."""

    def list_tables(self, path: Path) -> list[dict]:
        """Optional table discovery for sources containing multiple tables."""
        return []


class CSVReader(MetadataReader):
    extensions = (".csv",)

    def read(self, path: Path, table_name: str | None = None) -> dict:
        from .file_loader import _load_csv
        return _load_csv(path)


class XLSXReader(MetadataReader):
    extensions = (".xlsx", ".xlsm")

    def read(self, path: Path, table_name: str | None = None) -> dict:
        from .file_loader import _load_xlsx
        return _load_xlsx(path)


def _table_result(path: Path, rows: list[dict], table_name: str) -> dict:
    columns = list(dict.fromkeys(key for row in rows for key in row.keys()))
    return {
        "source_file": str(path),
        "sheet_name": None,
        "source_table": table_name,
        "columns": columns,
        "rows": rows,
    }


class SQLReader(MetadataReader):
    extensions = (".sql",)

    def list_tables(self, path: Path) -> list[dict]:
        from .sql_sources import _parse_sql
        tables = _parse_sql(path)
        return [{"name": name, "row_count": len(rows)}
                for name, rows in sorted(tables.items())]

    def read(self, path: Path, table_name: str | None = None) -> dict:
        from .sql_sources import _parse_sql
        if not table_name:
            raise ValueError("Select a SQL source table before importing.")
        tables = _parse_sql(path)
        if table_name not in tables:
            raise ValueError("The selected SQL table is unavailable.")
        return _table_result(path, tables[table_name], table_name)


class SQLiteReader(MetadataReader):
    extensions = (".sqlite", ".sqlite3", ".db")

    def list_tables(self, path: Path) -> list[dict]:
        from .sql_sources import _list_sqlite_tables
        return _list_sqlite_tables(path)

    def read(self, path: Path, table_name: str | None = None) -> dict:
        from .sql_sources import _read_sqlite_table
        if not table_name:
            raise ValueError("Select a SQLite source table before importing.")
        return _table_result(path, _read_sqlite_table(path, table_name), table_name)


_READERS = (CSVReader(), XLSXReader(), SQLReader(), SQLiteReader())
_READER_BY_EXTENSION = {
    extension: reader
    for reader in _READERS
    for extension in reader.extensions
}


def get_reader(path: str | Path) -> MetadataReader:
    """Choose a parser by extension; never interpret uploaded data as code."""
    suffix = Path(path).suffix.lower()
    try:
        return _READER_BY_EXTENSION[suffix]
    except KeyError:
        supported = ", ".join(sorted(_READER_BY_EXTENSION))
        raise ValueError(f"Unsupported metadata file type. Accepted: {supported}.") from None
