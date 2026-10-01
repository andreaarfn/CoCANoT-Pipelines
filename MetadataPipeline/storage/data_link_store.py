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


PATH_LIST_FIELDS = {
    "derivative_paths",
    "final_paths",
}
ROOT_LIST_FIELDS = {
    "derivatives_roots",
    "final_output_roots",
}
LEGACY_PATH_FIELDS = {
    "bids_data_path",
    "bids_sidecar_path",
    "bids_channels_path",
    "bids_electrodes_path",
    "bids_coordsystem_path",
    "cocanot_metadata_path",
}


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

    @staticmethod
    def _normalized_path(value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        path = Path(text).expanduser()
        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    @classmethod
    def _merge_path_values(cls, *values) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()

        for value in values:
            if value is None:
                continue

            items = value if isinstance(value, (list, tuple, set)) else [value]
            for item in items:
                normalized = cls._normalized_path(item)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                merged.append(normalized)

        return merged

    @classmethod
    def paths_from_payload(cls, payload) -> dict[str, list[str]]:
        payload = dict(payload or {})

        derivative_paths = cls._merge_path_values(
            payload.get("derivative_paths", [])
        )
        final_paths = cls._merge_path_values(
            payload.get("final_paths", []),
            *(
                payload.get(field, "")
                for field in LEGACY_PATH_FIELDS
            ),
        )

        derivatives_roots = cls._merge_path_values(
            payload.get("derivatives_roots", []),
            payload.get("derivatives_root", ""),
        )
        final_output_roots = cls._merge_path_values(
            payload.get("final_output_roots", []),
            payload.get("final_output_root", ""),
        )

        return {
            "derivative_paths": derivative_paths,
            "final_paths": final_paths,
            "derivatives_roots": derivatives_roots,
            "final_output_roots": final_output_roots,
        }

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
        existing = self.get_link(
            site_id,
            patient_id,
            table_name,
            record_id,
        )

        existing_paths = self.paths_from_payload(existing)
        new_paths = self.paths_from_payload(payload)

        for field in PATH_LIST_FIELDS | ROOT_LIST_FIELDS:
            payload[field] = self._merge_path_values(
                existing_paths.get(field, []),
                new_paths.get(field, []),
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

    def path_is_referenced_elsewhere(
        self,
        site_id,
        patient_id,
        table_name,
        record_id,
        path,
    ) -> bool:
        site_id = normalize_site_id(site_id)
        target = self._normalized_path(path)

        if not target:
            return False

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    patient_id,
                    table_name,
                    record_id,
                    data_json
                FROM patient_data_links
                WHERE UPPER(site_id) = ?
                """,
                (site_id,),
            ).fetchall()

        for row in rows:
            if (
                str(row["patient_id"]) == str(patient_id or "").strip()
                and str(row["table_name"]) == str(table_name or "").strip()
                and str(row["record_id"]) == str(record_id or "").strip()
            ):
                continue

            try:
                payload = json.loads(row["data_json"])
            except json.JSONDecodeError:
                continue

            linked = self.paths_from_payload(payload)
            if target in linked["derivative_paths"] or target in linked["final_paths"]:
                return True

        return False
