"""Read-only SQLite inspection and non-executing SQL INSERT data extraction.

No uploaded SQL is executed. Parsed data is fed into the ordinary Clinical /
Surgical MR dictionary mapping, validation and batch commit workflow.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

MAX_ROWS = 10000
MAX_COLUMNS = 250
MAX_SQL_BYTES = 20 * 1024 * 1024
MAX_DATABASE_BYTES = 250 * 1024 * 1024
IDENTIFIER = r'(?:"(?:[^"]|"")*"|\x60(?:[^\x60]|\x60\x60)*\x60|\[[^\]]+\]|[A-Za-z_][A-Za-z_0-9]*)'
TABLE_IDENTIFIER = rf'({IDENTIFIER}(?:\.{IDENTIFIER})?)'
INSERT_PATTERN = re.compile(
    rf'^INSERT\s+INTO\s+{TABLE_IDENTIFIER}\s*(.*)$', re.I | re.S
)
CREATE_PATTERN = re.compile(
    rf'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{TABLE_IDENTIFIER}\s*\((.*)\)$',
    re.I | re.S,
)


def _identifier(value: str) -> str:
    value = value.strip()
    if value[:1] == value[-1:] and value.startswith(('"', '`')):
        return value[1:-1].replace(value[0] * 2, value[0])
    if value.startswith("[") and value.endswith("]"):
        return value[1:-1]
    if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
        return value
    raise ValueError("SQL contains an unsupported identifier.")


def _table_name(value: str) -> str:
    # Only simple table names and the optional main/public qualifier.
    parts = value.split(".")
    if len(parts) == 2 and _identifier(parts[0]).lower() in {"main", "public"}:
        return _identifier(parts[1])
    if len(parts) == 1:
        return _identifier(parts[0])
    raise ValueError("SQL cross-database table references are not supported.")


def _split_statements(text: str) -> list[str]:
    """Split semicolon-delimited SQL while respecting quoted strings/comments."""
    result, buf = [], []
    quote_char = None
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        ch = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if ch == "\n":
                line_comment = False
                buf.append(" ")
            index += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote_char:
            buf.append(ch)
            if ch == quote_char:
                if nxt == quote_char:
                    buf.append(nxt)
                    index += 2
                    continue
                quote_char = None
            elif ch == "\\" and nxt:
                buf.append(nxt)
                index += 2
                continue
        elif ch == "'" or ch == '"' or ch == "`":
            quote_char = ch
            buf.append(ch)
        elif ch == "-" and nxt == "-":
            line_comment = True
            index += 2
            continue
        elif ch == "/" and nxt == "*":
            block_comment = True
            index += 2
            continue
        elif ch == ";":
            if "".join(buf).strip():
                result.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        index += 1
    if quote_char or block_comment:
        raise ValueError("SQL script contains an unterminated quote or comment.")
    if "".join(buf).strip():
        result.append("".join(buf).strip())
    return result


def _split_items(text: str) -> list[str]:
    result, buf, depth, quote_char = [], [], 0, None
    index = 0
    while index < len(text):
        ch = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if quote_char:
            buf.append(ch)
            if ch == quote_char:
                if nxt == quote_char:
                    buf.append(nxt)
                    index += 2
                    continue
                quote_char = None
            elif ch == "\\" and nxt:
                buf.append(nxt)
                index += 2
                continue
        elif ch in ("'", '"', "`"):
            quote_char = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced SQL values.")
            buf.append(ch)
        elif ch == "," and depth == 0:
            result.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        index += 1
    if depth or quote_char:
        raise ValueError("Unbalanced SQL values or quote.")
    result.append("".join(buf).strip())
    return result


def _literal(value: str):
    value = value.strip()
    if value.upper() == "NULL":
        return None
    if value.upper() == "TRUE":
        return True
    if value.upper() == "FALSE":
        return False
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'").replace("\\'", "'")
    if re.fullmatch(r"[-+]?[0-9]+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?", value):
        return float(value)
    # Never evaluate SQL expressions, functions, hex blobs or subqueries.
    raise ValueError(f"Unsupported SQL value {value[:40]!r}; only literal INSERT values can be imported.")


def _parse_sql(path: Path) -> dict[str, list[dict]]:
    if path.stat().st_size > MAX_SQL_BYTES:
        raise ValueError("SQL file exceeds the 20 MB safe preview limit.")
    script = path.read_text(encoding="utf-8-sig")
    tables = {}
    schemas = {}
    for statement in _split_statements(script):
        first = statement.split(None, 1)[0].upper()
        # Standard SQLite .dump files wrap inserts in BEGIN TRANSACTION.
        # These wrappers are ignored; never executed.
        if re.fullmatch(r"(?:BEGIN(?:\s+TRANSACTION)?|COMMIT|END|ROLLBACK)", statement, re.I):
            continue
        if first == "CREATE":
            match = CREATE_PATTERN.fullmatch(statement)
            if match is None:
                raise ValueError("Only simple CREATE TABLE and INSERT INTO statements are supported in SQL scripts.")
            name = _table_name(match.group(1))
            columns = []
            for definition in _split_items(match.group(2)):
                if re.match(r"^(?:PRIMARY|UNIQUE|FOREIGN|CHECK|CONSTRAINT)\b", definition, re.I):
                    continue
                candidate = re.match(rf"^({IDENTIFIER})(?:\s|$)", definition)
                if not candidate:
                    raise ValueError("Could not determine a SQL table column.")
                columns.append(_identifier(candidate.group(1)))
            if not columns or len(columns) > MAX_COLUMNS:
                raise ValueError("SQL table contains too many or no columns.")
            schemas[name] = columns
            tables.setdefault(name, [])
            continue
        if first != "INSERT":
            raise ValueError(f"SQL {first} statements are not supported for safe import.")
        match = INSERT_PATTERN.fullmatch(statement)
        if not match:
            raise ValueError("Only INSERT INTO ... VALUES statements are supported.")
        name = _table_name(match.group(1))
        rest = match.group(2).strip()
        columns = schemas.get(name)
        if rest.startswith("("):
            closing = rest.find(")")
            if closing < 0:
                raise ValueError("Malformed SQL INSERT column list.")
            columns = [_identifier(item) for item in _split_items(rest[1:closing])]
            rest = rest[closing + 1:].strip()
        if not columns or len(columns) > MAX_COLUMNS or len(set(columns)) != len(columns):
            raise ValueError(f"INSERT for {name} needs valid column names or a CREATE TABLE declaration.")
        if not re.match(r"^VALUES\b", rest, re.I):
            raise ValueError("Only literal SQL INSERT ... VALUES rows are supported.")
        rows_text = re.sub(r"^VALUES\s*", "", rest, count=1, flags=re.I)
        tuples = _split_items(rows_text)
        for row_text in tuples:
            if not row_text.startswith("(") or not row_text.endswith(")"):
                raise ValueError("Each SQL row must be a parenthesized VALUES tuple.")
            values = [_literal(item) for item in _split_items(row_text[1:-1])]
            if len(values) != len(columns):
                raise ValueError(f"SQL column/value count mismatch for {name}.")
            tables.setdefault(name, []).append(dict(zip(columns, values)))
            if sum(len(items) for items in tables.values()) > MAX_ROWS:
                raise ValueError("SQL script contains over 10,000 rows; split the import.")
    return {name: rows for name, rows in tables.items() if rows}


def list_source_tables(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".sql":
        tables = _parse_sql(path)
        return [{"name": name, "row_count": len(rows)} for name, rows in sorted(tables.items())]
    if suffix not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("Choose a SQL script or SQLite database.")
    if path.stat().st_size > MAX_DATABASE_BYTES:
        raise ValueError("SQLite database exceeds the 250 MB safe preview limit.")
    connection = _connect_readonly(path)
    try:
        names = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [{"name": name, "row_count": None} for (name,) in names]
    finally:
        connection.close()


def _connect_readonly(path: Path):
    connection = sqlite3.connect("file:" + quote(str(path.resolve())) + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def read_source_table(path: Path, table_name: str) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".sql":
        tables = _parse_sql(path)
        if table_name not in tables:
            raise ValueError("The selected SQL table is unavailable.")
        return tables[table_name]
    available = {item["name"] for item in list_source_tables(path)}
    if table_name not in available:
        raise ValueError("The selected SQLite table is unavailable.")
    connection = _connect_readonly(path)
    try:
        cursor = connection.execute(
            'SELECT * FROM "' + table_name.replace('"', '""') + '" LIMIT ?',
            (MAX_ROWS + 1,),
        )
        if len(cursor.description or []) > MAX_COLUMNS:
            raise ValueError("SQLite table has too many columns.")
        keys = [column[0] for column in cursor.description]
        rows = [dict(zip(keys, values)) for values in cursor.fetchall()]
        if len(rows) > MAX_ROWS:
            raise ValueError("SQLite table exceeds 10,000 rows; split the import.")
        if any(any(isinstance(value, bytes) for value in row.values()) for row in rows):
            raise ValueError("Binary SQLite columns cannot be imported as metadata.")
        return rows
    finally:
        connection.close()
