"""Non-executing, data-only text export readers.

Profiles: PostgreSQL plain pg_dump COPY text; MySQL/MariaDB complete-column
INSERT VALUES text. Any unsupported command aborts the entire preview.
"""
from __future__ import annotations
import re
from pathlib import Path
from .sql_sources import (
    MAX_ROWS, MAX_COLUMNS, MAX_SQL_BYTES, TABLE_IDENTIFIER,
    _table_name, _identifier, _split_items, _split_statements, _literal,
)

COPY = re.compile(rf"^COPY\s+{TABLE_IDENTIFIER}\s*\((.*?)\)\s+FROM\s+stdin\s*;$", re.I)
PG_SETTINGS = re.compile(r"^SET\s+(?:statement_timeout|lock_timeout|idle_in_transaction_session_timeout|transaction_timeout|client_encoding|standard_conforming_strings|check_function_bodies|xmloption|client_min_messages|row_security|search_path|default_tablespace|default_table_access_method)\s*=\s*.+$", re.I | re.S)
PG_SETCFG = re.compile(r"^SELECT\s+pg_catalog\.set_config\s*\(\s*'search_path'\s*,\s*'[^']*'\s*,\s*false\s*\)$", re.I)
PG_SETVAL = re.compile(r"^SELECT\s+pg_catalog\.setval\s*\(\s*'[^']+'\s*,\s*\d+\s*,\s*(?:true|false)\s*\)$", re.I)
MYSQL_NAME = r"(?:\x60(?:[^\x60]|\x60\x60)+\x60|[A-Za-z_][A-Za-z_0-9]*)"
MYSQL_INSERT = re.compile(rf"^INSERT\s+INTO\s+({MYSQL_NAME})\s*\((.*?)\)\s*VALUES\s*(.+)$", re.I | re.S)


def _read(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("SQL export file does not exist.")
    if path.stat().st_size > MAX_SQL_BYTES:
        raise ValueError("SQL file exceeds the 20 MB safe preview limit.")
    return path.read_text(encoding="utf-8-sig")


def _append(tables, schemas, name, columns, values):
    if not columns or len(columns) > MAX_COLUMNS or len(columns) != len(set(columns)):
        raise ValueError("Invalid SQL export column names.")
    if len(columns) != len(values):
        raise ValueError("SQL export row/column mismatch.")
    if name in schemas and schemas[name] != columns:
        raise ValueError("SQL table column layout changed within one export.")
    schemas[name] = columns
    tables.setdefault(name, []).append(dict(zip(columns, values)))
    if sum(len(rows) for rows in tables.values()) > MAX_ROWS:
        raise ValueError("SQL script contains over 10,000 rows; split the import.")


def _pg_text(value):
    if value == r"\N":
        return None
    controls = {"b": "\b", "f": "\f", "n": "\n", "r": "\r",
                "t": "\t", "v": "\v", "\\": "\\"}
    out, i = [], 0
    while i < len(value):
        if value[i] != "\\":
            out.append(value[i])
            i += 1
            continue
        i += 1
        if i == len(value):
            raise ValueError("Invalid PostgreSQL COPY escape.")
        c = value[i]
        if c in controls:
            out.append(controls[c])
            i += 1
        elif c in "01234567":
            match = re.match(r"[0-7]{1,3}", value[i:])
            out.append(chr(int(match.group(), 8)))
            i += len(match.group())
        elif c == "x":
            match = re.match(r"[0-9a-fA-F]{1,2}", value[i + 1:])
            if not match:
                raise ValueError("Invalid COPY hex escape.")
            out.append(chr(int(match.group(), 16)))
            i += 1 + len(match.group())
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_postgres_data_only(path):
    """Read PostgreSQL plain-text data-only COPY blocks; reject all DDL."""
    lines = _read(path).splitlines()
    tables, schemas, outside = {}, {}, []
    i = 0
    restriction = None
    while i < len(lines):
        directive = re.fullmatch(r"\\(restrict|unrestrict)\s+([A-Za-z0-9]+)", lines[i].strip())
        if directive:
            kind, token = directive.groups()
            if kind == "restrict":
                if restriction is not None:
                    raise ValueError("Nested PostgreSQL dump restriction.")
                restriction = token
            else:
                if token != restriction:
                    raise ValueError("Mismatched PostgreSQL dump restriction marker.")
                restriction = None
            i += 1
            continue
        match = COPY.fullmatch(lines[i].strip())
        if not match:
            outside.append(lines[i])
            i += 1
            continue
        name = _table_name(match.group(1))
        columns = [_identifier(x) for x in _split_items(match.group(2))]
        i += 1
        terminated = False
        while i < len(lines):
            line = lines[i]
            i += 1
            if line == r"\.":
                terminated = True
                break
            _append(tables, schemas, name, columns,
                    [_pg_text(x) for x in line.split("\t")])
        if not terminated:
            raise ValueError("Unterminated PostgreSQL COPY block.")
    if restriction is not None:
        raise ValueError("Unterminated PostgreSQL dump restriction marker.")
    for statement in _split_statements("\n".join(outside)):
        if (PG_SETTINGS.fullmatch(statement) or PG_SETCFG.fullmatch(statement)
                or PG_SETVAL.fullmatch(statement)
                or re.fullmatch(r"(?:BEGIN|COMMIT)", statement, re.I)):
            continue
        raise ValueError("Unsupported PostgreSQL data-only dump command: "
                         + statement[:100])
    if not tables:
        raise ValueError("No PostgreSQL COPY records found.")
    return tables


MYSQL_ESCAPES = {"0": "\0", "b": "\b", "n": "\n", "r": "\r",
                 "t": "\t", "Z": "\x1a", "\\": "\\", "'": "'", '"': '"'}


def _mysql_value(value):
    value = value.strip()
    if not (value.startswith("'") and value.endswith("'")):
        return _literal(value)
    text = value[1:-1]
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\":
            i += 1
            if i == len(text) or text[i] not in MYSQL_ESCAPES:
                raise ValueError("Unsupported MySQL string escape.")
            out.append(MYSQL_ESCAPES[text[i]])
        elif text[i] == "'" and i + 1 < len(text) and text[i + 1] == "'":
            out.append("'")
            i += 1
        else:
            out.append(text[i])
        i += 1
    return "".join(out)


def _mysql_split(text, separator=";"):
    """Split MySQL dump tokens without stripping escaped characters.

    Keep escape sequences intact for the MySQL value decoder. Reject executable
    comments (which can contain commands that cannot be silently discarded).
    """
    parts, buffer = [], []
    quote = None
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ""
        if quote:
            buffer.append(c)
            if c == "\\" and n:
                buffer.append(n)
                i += 2
                continue
            if c == quote:
                if n == quote:
                    buffer.append(n)
                    i += 2
                    continue
                quote = None
        elif c in ("'", '"', "\x60"):
            quote = c
            buffer.append(c)
        elif c == "-" and n == "-" and (i + 2 == len(text) or text[i + 2].isspace()):
            i = text.find("\n", i)
            if i == -1:
                break
            buffer.append(" ")
            continue
        elif c == "#":
            i = text.find("\n", i)
            if i == -1:
                break
            buffer.append(" ")
            continue
        elif c == "/" and n == "*":
            if text[i:i + 3] == "/*!":
                raise ValueError("Executable MySQL dump comments are not supported.")
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError("Unterminated MySQL comment.")
            buffer.append(" ")
            i = end + 2
            continue
        elif c == "(":
            depth += 1
            buffer.append(c)
        elif c == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced MySQL parentheses.")
            buffer.append(c)
        elif c == separator and depth == 0:
            if "".join(buffer).strip():
                parts.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(c)
        i += 1
    if quote or depth:
        raise ValueError("Unterminated MySQL string or unbalanced tuple.")
    if "".join(buffer).strip():
        parts.append("".join(buffer).strip())
    return parts


def parse_mysql_data_only(path):
    """Read explicit-column INSERT statements from compact data-only mysqldump."""
    tables, schemas = {}, {}
    for statement in _mysql_split(_read(path)):
        match = MYSQL_INSERT.fullmatch(statement)
        if not match:
            raise ValueError("Unsupported MySQL data-only dump command: "
                             + statement[:100])
        name = _identifier(match.group(1))
        columns = [_identifier(x) for x in _split_items(match.group(2))]
        for item in _mysql_split(match.group(3), ","):
            if not item.startswith("(") or not item.endswith(")"):
                raise ValueError("Malformed MySQL INSERT VALUES tuple.")
            _append(tables, schemas, name, columns,
                    [_mysql_value(x) for x in _mysql_split(item[1:-1], ",")])
    if not tables:
        raise ValueError("No MySQL INSERT records found.")
    return tables
