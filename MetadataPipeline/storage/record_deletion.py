"""Safe deletion helpers for locally stored CoCANoT records."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .local_database import (
    default_database_path,
    normalize_site_id,
)


class RecordDeletionService:
    """Delete local database records while protecting linked assessments."""

    def __init__(
        self,
        database_path=None,
    ):
        self.database_path = Path(
            database_path
            or default_database_path()
        ).expanduser()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path
        )
        connection.row_factory = sqlite3.Row
        return connection

    def delete_metadata_record(
        self,
        site_id,
        patient_id,
        table_name,
        record_id,
    ):
        site_id = normalize_site_id(
            site_id
        )

        if table_name not in {
            "Surgical",
            "Imaging",
            "Electrophysiology",
        }:
            raise ValueError(
                f"Unsupported metadata table: {table_name}"
            )

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM metadata_records
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
                    table_name,
                    str(
                        record_id
                        or ""
                    ).strip(),
                ),
            )

        return cursor.rowcount > 0

    def clinical_assessment_references(
        self,
        site_id,
        patient_id,
        assessment_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id
            or ""
        ).strip()
        assessment_id = str(
            assessment_id
            or ""
        ).strip()

        references = []

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    table_name,
                    record_id,
                    data_json
                FROM metadata_records
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND table_name IN (
                      'Surgical',
                      'Imaging',
                      'Electrophysiology'
                  )
                ORDER BY table_name, record_id
                """,
                (
                    site_id,
                    patient_id,
                ),
            ).fetchall()

        for row in rows:
            try:
                metadata = json.loads(
                    row[
                        "data_json"
                    ]
                )
            except json.JSONDecodeError:
                continue

            if type(metadata) is not dict:
                continue

            linked_assessment = str(
                metadata.get(
                    "Clinical Assessment ID",
                    "",
                )
                or ""
            ).strip()

            if linked_assessment == assessment_id:
                references.append({
                    "table_name": row[
                        "table_name"
                    ],
                    "record_id": row[
                        "record_id"
                    ],
                })

        return references

    def clinical_assessment_count(
        self,
        site_id,
        patient_id,
    ):
        site_id = normalize_site_id(
            site_id
        )

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM clinical_assessments
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                """,
                (
                    site_id,
                    str(
                        patient_id
                        or ""
                    ).strip(),
                ),
            ).fetchone()

        return int(
            row[
                "count"
            ]
            if row is not None
            else 0
        )

    def delete_clinical_assessment(
        self,
        site_id,
        patient_id,
        assessment_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id
            or ""
        ).strip()
        assessment_id = str(
            assessment_id
            or ""
        ).strip()

        references = self.clinical_assessment_references(
            site_id,
            patient_id,
            assessment_id,
        )

        if references:
            return {
                "deleted": False,
                "reason": "referenced",
                "references": references,
            }

        if self.clinical_assessment_count(
            site_id,
            patient_id,
        ) <= 1:
            return {
                "deleted": False,
                "reason": "only_assessment",
                "references": [],
            }

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM clinical_assessments
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND assessment_id = ?
                """,
                (
                    site_id,
                    patient_id,
                    assessment_id,
                ),
            )

        return {
            "deleted": (
                cursor.rowcount > 0
            ),
            "reason": (
                ""
                if cursor.rowcount > 0
                else "not_found"
            ),
            "references": [],
        }
