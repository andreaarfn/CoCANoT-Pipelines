"""Conservative, non-executing adapters for common vendor SQL *text* exports.

This is not a general SQL engine or native database backup reader.
Unrecognized SQL is deliberately rejected by the strict common parser.
"""
from __future__ import annotations

import re
from pathlib import Path

from .sql_sources import (
    IDENTIFIER, TABLE_IDENTIFIER, MAX_ROWS, MAX_SQL_BYTES,
    _identifier, _split_items, _table_name, _parse_sql_text,
)

COPY_HEADER = re.compile(
    rf"^COPY\s+{TABLE_IDENTIFIER}\s*\(([^)\n]+)\)\s+FROM\s+stdin\s*;\s*$",
    re.IGNORECASE,
)
INSERT_ALL = re.compile(r"^INSERT\s+ALL\s+(.+?)\s+SELECT\s+1\s+FROM\s+DUAL$", re.I | re.S)
INTO_CLAUSE = re.compile(
    rf"\s*INTO\s+({IDENTIFIER}(?:\.{IDENTIFIER})?)\s*"
    rf"(\([^)]*\))\s*VALUES\s*(\([^)]*\))",
    re.I | re.S,
)
# Boilerplate is ignored, never executed. Do not broadly discard SELECT or DDL.
IGNORED = [
    re.compile(r"^SET\s+(?:ANSI_NULLS|QUOTED_IDENTIFIER|ANSI_PADDING|NOCOUNT)\s+(?:ON|OFF)$", re.I),
    re.compile(r"^SET\s+IDENTITY_INSERT\s+\S+\s+(?:ON|OFF)$", re.I),
    re.compile(r"^SET\s+(?:NAMES|CHARACTER_SET_CLIENT|CHARACTER_SET_RESULTS|COLLATION_CONNECTION)\s+.+$", re.I | re.S),
    re.compile(r"^SET\s+(?:statement_timeout|lock_timeout|idle_in_transaction_session_timeout|client_encoding|standard_conforming_strings|check_function_bodies|xmloption|client_min_messages|row_security|search_path)\s*=\s*.+$", re.I | re.S),
    re.compile(r"^(?:LOCK TABLES\s+.+|UNLOCK TABLES)$", re.I | re.S),
    re.compile(r"^SELECT\s+pg_catalog\.set_config\s*\(\s*'search_path'\s*,\s*'[^']*'\s*,\s*false\s*\)$", re.I),
]


def _copy_cell(cell: str):
    if cell == r"\N":
        return None
    # PostgreSQL COPY text escape sequences; reject unsupported escapes.
    escape_map = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}
    output = []
    index = 0
    while index < len(cell):
        if cell[index] == "\\":
            index += 1
            if index >= len(cell) or cell[index] not in escape_map:
                raise ValueError("Unsupported PostgreSQL COPY escape.")
            output.append(escape_map[cell[index]])
        else:
            output.append(cell[index])
        index += 1
    return "".join(output)


def _quote_sql(value):
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _expand_copy(script: str) -> str:
    """Convert only well-formed PostgreSQL COPY FROM stdin blocks to literal INSERTs."""
    output = []
    lines = script.splitlines()
    index = 0
    copied = 0
    while index < len(lines):
        line = lines[index]
        match = COPY_HEADER.fullmatch(line.strip())
        if not match:
            output.append(line)
            index += 1
            continue
        table = match.group(1)
        columns = [_identifier(x) for x in _split_items(match.group(2))]
        if not columns or len(set(columns)) != len(columns):
            raise ValueError("Invalid PostgreSQL COPY columns.")
        index += 1
        terminated = False
        while index < len(lines):
            line = lines[index]
            index += 1
            if line == r"\.":
                terminated = True
                break
            values = [_copy_cell(x) for x in line.split("\t")]
            if len(values) != len(columns):
                raise ValueError("PostgreSQL COPY column/value count mismatch.")
            copied += 1
            if copied > MAX_ROWS:
                raise ValueError("SQL script contains over 10,000 rows; split the import.")
            col_sql = ", ".join('"' + col.replace('"', '""') + '"' for col in columns)
            val_sql = ", ".join(_quote_sql(v) for v in values)
            output.append(f"INSERT INTO {table} ({col_sql}) VALUES ({val_sql});")
        if not terminated:
            raise ValueError("Unterminated PostgreSQL COPY block.")
    return "\n".join(output)


def _expand_oracle_insert_all(statement: str) -> list[str] | None:
    match = INSERT_ALL.fullmatch(statement)
    if match is None:
        return None
    body = match.group(1)
    converted = []
    position = 0
    while position < len(body):
        item = INTO_CLAUSE.match(body, position)
        if not item:
            raise ValueError("Unsupported Oracle INSERT ALL clause.")
        converted.append(f"INSERT INTO {item.group(1)} {item.group(2)} VALUES {item.group(3)}")
        position = item.end()
    if not converted:
        raise ValueError("Oracle INSERT ALL contains no rows.")
    return converted


def _adapt_statement(statement: str) -> list[str]:
    statement = statement.strip()
    if not statement:
        return []
    if any(pattern.fullmatch(statement) for pattern in IGNORED):
        return []
    if re.fullmatch(r"(?:GO|/)", statement, re.I):
        return []
    oracle = _expand_oracle_insert_all(statement)
    if oracle is not None:
        return oracle
    # T-SQL Unicode literals, only outside of string content (quoted SQL text
    # never gets evaluated). This matches the common N'...' export form.
    if re.match(r"^INSERT\s+INTO\b", statement, re.I):
        statement = re.sub(r"(?<![A-Za-z0-9_'\\])N'(?=(?:[^']|'')*')", "'", statement)
    # Vendor-qualified table names, restricted to one optional schema.
    statement = re.sub(
        rf"^((?:INSERT\s+INTO|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+)"
        rf"({IDENTIFIER})\.({IDENTIFIER})(?=\s|\()",
        lambda match: match.group(1) + match.group(3)
        if _identifier(match.group(2)).lower() in {"dbo", "public", "main"}
        else match.group(0),
        statement, flags=re.I,
    )
    # MySQL's ENGINE/CHARSET table suffix does not affect imported data.
    statement = re.sub(
        r"(\)\s*)ENGINE\s*=\s*\w+(?:\s+DEFAULT)?(?:\s+CHARSET\s*=\s*[\w\d]+)?\s*$",
        r"\1", statement, flags=re.I,
    )
    return [statement]


def parse_sql_export(path: Path) -> dict[str, list[dict]]:
    """Parse text exports from selected SQL dialects; execute no commands."""
    path = Path(path)
    if path.stat().st_size > MAX_SQL_BYTES:
        raise ValueError("SQL file exceeds the 20 MB safe preview limit.")
    script = path.read_text(encoding="utf-8-sig")
    script = _expand_copy(script)
    # GO and Oracle slash are standalone batch delimiters, not SQL.
    script = re.sub(r"(?im)^\s*(?:GO|/)\s*$", "", script)
    # Explicitly reject unsupported COPY forms; no silent partial imports.
    from .sql_sources import _split_statements
    normalized = []
    for statement in _split_statements(script):
        normalized.extend(_adapt_statement(statement))
    return _parse_sql_text("\n".join(item + ";" for item in normalized))
