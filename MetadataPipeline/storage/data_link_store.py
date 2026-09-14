"""Store links between CoCANoT records and final local BIDS files."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .local_database import (
    default_database_path,
    normalize_site_id,
)


class PatientDataLinkStore:
    """Persist final local data paths without placing binary data in SQLite."""

    def __init__(
        self,
        database_path=None,
    ):
        self.database_path = Path(
            database_path
            or default_database_path()
        ).expanduser()
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS patient_data_links (
                    site_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        site_id,
                        patient_id,
                        table_name,
                        record_id
                    )
                )
                """
            )

    def save_link(
        self,
        site_id,
        patient_id,
        table_name,
        record_id,
        data,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id
            or ""
        ).strip()
        table_name = str(
            table_name
            or ""
        ).strip()
        record_id = str(
            record_id
            or ""
        ).strip()

        if not site_id:
            raise ValueError(
                "Site ID cannot be blank."
            )

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID cannot be blank."
            )

        if table_name not in {
            "Imaging",
            "Electrophysiology",
        }:
            raise ValueError(
                f"Unsupported linked data table: {table_name}"
            )

        if not record_id:
            raise ValueError(
                "Record ID cannot be blank."
            )

        payload = dict(
            data
            or {}
        )
        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO patient_data_links (
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                    data_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    site_id,
                    patient_id,
                    table_name,
                    record_id
                )
                DO UPDATE SET
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                ),
            )

    def delete_link(
        self,
        site_id,
        patient_id,
        table_name,
        record_id,
    ):
        site_id = normalize_site_id(
            site_id
        )

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM patient_data_links
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND table_name = ?
                  AND record_id = ?
                """,
                (
                    site_id,
                    str(
                        patient_id
                        or ""
                    ).strip(),
                    str(
                        table_name
                        or ""
                    ).strip(),
                    str(
                        record_id
                        or ""
                    ).strip(),
                ),
            )

        return cursor.rowcount > 0

    def get_link(
        self,
        site_id,
        patient_id,
        table_name,
        record_id,
    ):
        site_id = normalize_site_id(
            site_id
        )

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT data_json
                FROM patient_data_links
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND table_name = ?
                  AND record_id = ?
                LIMIT 1
                """,
                (
                    site_id,
                    str(
                        patient_id
                        or ""
                    ).strip(),
                    str(
                        table_name
                        or ""
                    ).strip(),
                    str(
                        record_id
                        or ""
                    ).strip(),
                ),
            ).fetchone()

        if row is None:
            return {}

        try:
            payload = json.loads(
                row[
                    "data_json"
                ]
            )
        except json.JSONDecodeError:
            return {}

        return (
            payload
            if type(payload) is dict
            else {}
        )
