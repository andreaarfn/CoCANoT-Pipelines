"""Read and write reviewable CoCANoT metadata records."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .local_database import default_database_path, normalize_site_id


TABLES = {
    "Surgical": "Surgical",
    "Imaging": "Imaging",
    "Electrophysiology": "Electrophysiology",
}

IDENTIFIER_FIELDS = {
    "Surgical": "Surgery ID",
    "Imaging": "Image ID",
    "Electrophysiology": "Recording ID",
}


class MetadataRepository:
    """Repository used by the Metadata Dashboard."""

    def __init__(self, database_path=None):
        self.database_path = Path(
            database_path or default_database_path()
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
                CREATE TABLE IF NOT EXISTS patients (
                    site_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        site_id,
                        patient_id
                    )
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata_records (
                    site_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
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

            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(metadata_records)"
                ).fetchall()
            }

            if "context_json" not in columns:
                connection.execute(
                    """
                    ALTER TABLE metadata_records
                    ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'
                    """
                )

            table_info = connection.execute(
                "PRAGMA table_info(metadata_records)"
            ).fetchall()

            primary_key = [
                row["name"]
                for row in sorted(
                    (
                        row
                        for row in table_info
                        if int(row["pk"]) > 0
                    ),
                    key=lambda row: int(
                        row["pk"]
                    ),
                )
            ]

            expected_primary_key = [
                "site_id",
                "patient_id",
                "table_name",
                "record_id",
            ]

            if primary_key != expected_primary_key:
                connection.execute(
                    """
                    ALTER TABLE metadata_records
                    RENAME TO metadata_records_legacy
                    """
                )

                connection.execute(
                    """
                    CREATE TABLE metadata_records (
                        site_id TEXT NOT NULL,
                        patient_id TEXT NOT NULL,
                        table_name TEXT NOT NULL,
                        record_id TEXT NOT NULL,
                        data_json TEXT NOT NULL,
                        context_json TEXT NOT NULL DEFAULT '{}',
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
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

                connection.execute(
                    """
                    INSERT INTO metadata_records (
                        site_id,
                        patient_id,
                        table_name,
                        record_id,
                        data_json,
                        context_json,
                        source,
                        created_at,
                        updated_at
                    )
                    SELECT
                        site_id,
                        patient_id,
                        table_name,
                        record_id,
                        data_json,
                        COALESCE(
                            context_json,
                            '{}'
                        ),
                        source,
                        created_at,
                        updated_at
                    FROM metadata_records_legacy
                    """
                )

                connection.execute(
                    """
                    DROP TABLE metadata_records_legacy
                    """
                )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                metadata_records_patient_lookup
                ON metadata_records (
                    site_id,
                    patient_id,
                    table_name
                )
                """
            )

    def patient_summary(
        self,
        site_id,
        patient_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()

        return {
            "Clinical": self.clinical_assessments(
                site_id,
                patient_id,
            ),
            "Surgical": self.records_for_patient(
                site_id,
                patient_id,
                "Surgical",
            ),
            "Imaging": self.records_for_patient(
                site_id,
                patient_id,
                "Imaging",
            ),
            "Electrophysiology": self.records_for_patient(
                site_id,
                patient_id,
                "Electrophysiology",
            ),
        }

    def patient_ids_for_site(
        self,
        site_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO patients (
                    site_id,
                    patient_id,
                    created_at,
                    updated_at
                )
                SELECT
                    UPPER(site_id),
                    patient_id,
                    ?,
                    ?
                FROM clinical_assessments
                WHERE UPPER(site_id) = ?
                """,
                (
                    now,
                    now,
                    site_id,
                ),
            )

            connection.execute(
                """
                INSERT OR IGNORE INTO patients (
                    site_id,
                    patient_id,
                    created_at,
                    updated_at
                )
                SELECT
                    UPPER(site_id),
                    patient_id,
                    ?,
                    ?
                FROM metadata_records
                WHERE UPPER(site_id) = ?
                """,
                (
                    now,
                    now,
                    site_id,
                ),
            )

            rows = connection.execute(
                """
                SELECT patient_id
                FROM patients
                WHERE UPPER(site_id) = ?
                ORDER BY patient_id
                """,
                (
                    site_id,
                ),
            ).fetchall()

        return [
            str(
                row["patient_id"]
            )
            for row in rows
        ]

    def patient_exists(
        self,
        site_id,
        patient_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()

        if not site_id or not patient_id:
            return False

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM patients
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                LIMIT 1
                """,
                (
                    site_id,
                    patient_id,
                ),
            ).fetchone()

        return row is not None

    def create_patient(
        self,
        site_id,
        patient_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()

        if not site_id:
            raise ValueError(
                "Site ID cannot be blank."
            )

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID cannot be blank."
            )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO patients (
                    site_id,
                    patient_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT (
                    site_id,
                    patient_id
                )
                DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (
                    site_id,
                    patient_id,
                    now,
                    now,
                ),
            )

        return patient_id

    def clinical_assessments(
        self,
        site_id,
        patient_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    site_id,
                    patient_id,
                    assessment_number,
                    assessment_id,
                    dictionary_version,
                    data_json,
                    created_at,
                    updated_at
                FROM clinical_assessments
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                ORDER BY assessment_number DESC
                """,
                (
                    site_id,
                    patient_id,
                ),
            ).fetchall()

        return [
            {
                "table_name": "Clinical",
                "record_id": row[
                    "assessment_id"
                ],
                "site_id": normalize_site_id(
                    row["site_id"]
                ),
                "patient_id": row[
                    "patient_id"
                ],
                "dictionary_version": str(
                    row["dictionary_version"]
                    or ""
                ),
                "metadata": json.loads(
                    row["data_json"]
                ),
                "created_at": row[
                    "created_at"
                ],
                "updated_at": row[
                    "updated_at"
                ],
                "source": "clinical_assessments",
            }
            for row in rows
        ]

    def records_for_patient(
        self,
        site_id,
        patient_id,
        table_name,
    ):
        self._require_table(
            table_name
        )

        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                    data_json,
                    context_json,
                    source,
                    created_at,
                    updated_at
                FROM metadata_records
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND table_name = ?
                ORDER BY updated_at DESC, record_id
                """,
                (
                    site_id,
                    patient_id,
                    table_name,
                ),
            ).fetchall()

        return [
            self._row_to_record(
                row
            )
            for row in rows
        ]

    def get_record(
        self,
        site_id,
        table_name,
        record_id,
        patient_id=None,
    ):
        self._require_table(
            table_name
        )

        site_id = normalize_site_id(
            site_id
        )
        record_id = str(
            record_id or ""
        ).strip()
        patient_id = str(
            patient_id or ""
        ).strip()

        with self._connect() as connection:
            if patient_id:
                row = connection.execute(
                    """
                    SELECT
                        site_id,
                        patient_id,
                        table_name,
                        record_id,
                        data_json,
                        context_json,
                        source,
                        created_at,
                        updated_at
                    FROM metadata_records
                    WHERE UPPER(site_id) = ?
                      AND patient_id = ?
                      AND table_name = ?
                      AND record_id = ?
                    LIMIT 1
                    """,
                    (
                        site_id,
                        patient_id,
                        table_name,
                        record_id,
                    ),
                ).fetchone()
            else:
                rows = connection.execute(
                    """
                    SELECT
                        site_id,
                        patient_id,
                        table_name,
                        record_id,
                        data_json,
                        context_json,
                        source,
                        created_at,
                        updated_at
                    FROM metadata_records
                    WHERE UPPER(site_id) = ?
                      AND table_name = ?
                      AND record_id = ?
                    ORDER BY patient_id
                    """,
                    (
                        site_id,
                        table_name,
                        record_id,
                    ),
                ).fetchall()

                if len(rows) > 1:
                    raise ValueError(
                        f"{record_id} exists for more than one patient. "
                        "Provide patient_id when retrieving this record."
                    )

                row = (
                    rows[0]
                    if rows
                    else None
                )

        if row is None:
            return None

        return self._row_to_record(
            row
        )

    def save_record(
        self,
        site_id,
        table_name,
        metadata,
        source="metadata_dashboard",
        context=None,
    ):
        self._require_table(
            table_name
        )

        site_id = normalize_site_id(
            site_id
        )
        clean_metadata = dict(
            metadata or {}
        )
        clean_context = dict(
            context or {}
        )

        patient_id = str(
            clean_metadata.get(
                "CoCANoT Patient ID"
            )
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

        self.create_patient(
            site_id,
            patient_id,
        )

        identifier_field = (
            IDENTIFIER_FIELDS[
                table_name
            ]
        )
        record_id = str(
            clean_metadata.get(
                identifier_field
            )
            or ""
        ).strip()

        if not record_id:
            raise ValueError(
                f"{identifier_field} cannot be blank."
            )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        existing = self.get_record(
            site_id,
            table_name,
            record_id,
            patient_id=patient_id,
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata_records (
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                    data_json,
                    context_json,
                    source,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    site_id,
                    patient_id,
                    table_name,
                    record_id
                )
                DO UPDATE SET
                    data_json = excluded.data_json,
                    context_json = excluded.context_json,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    site_id,
                    patient_id,
                    table_name,
                    record_id,
                    self._dump(
                        clean_metadata
                    ),
                    self._dump(
                        clean_context
                    ),
                    str(
                        source or ""
                    ).strip()
                    or "metadata_dashboard",
                    (
                        existing[
                            "created_at"
                        ]
                        if existing
                        else now
                    ),
                    now,
                ),
            )

        return self.get_record(
            site_id,
            table_name,
            record_id,
            patient_id=patient_id,
        )

    def save_records(
        self,
        site_id,
        table_name,
        records,
        source="metadata_dashboard",
    ):
        saved = []

        for item in records:
            if (
                type(item) is dict
                and "metadata" in item
            ):
                metadata = item["metadata"]
                context = item.get(
                    "context",
                    {},
                )
            else:
                metadata = item
                context = {}

            saved.append(
                self.save_record(
                    site_id,
                    table_name,
                    metadata,
                    source=source,
                    context=context,
                )
            )

        return saved

    @staticmethod
    def _dump(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _row_to_record(row):
        return {
            "site_id": normalize_site_id(
                row["site_id"]
            ),
            "patient_id": row[
                "patient_id"
            ],
            "table_name": row[
                "table_name"
            ],
            "record_id": row[
                "record_id"
            ],
            "metadata": json.loads(
                row["data_json"]
            ),
            "context": json.loads(
                row["context_json"]
            ),
            "source": row[
                "source"
            ],
            "created_at": row[
                "created_at"
            ],
            "updated_at": row[
                "updated_at"
            ],
        }

    @staticmethod
    def _require_table(table_name):
        if table_name not in TABLES:
            raise ValueError(
                f"Unsupported metadata table: {table_name}"
            )
