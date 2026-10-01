"""Local persistent storage for Site ID and Clinical Assessments."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# These values describe the patient rather than one point in the
# patient's longitudinal Clinical Assessment history.
#
# If one of these values is corrected, the corrected value is
# synchronized across every Clinical Assessment for that patient.
#
# IMPORTANT:
# Field names must exactly match the Clinical metadata dictionary.
PATIENT_LEVEL_CLINICAL_FIELDS = {
    "Race",
    "Other Race (if applicable; free text)",
    "Ethnicity",
    "Sex",
    "Age at Diagosis (years)",
}


def default_database_path():
    override = os.environ.get(
        "COCANOT_METADATA_DB",
        "",
    ).strip()

    if override:
        return Path(
            override
        ).expanduser()

    return (
        Path.home()
        / ".cocanot"
        / "metadata"
        / "cocanot_metadata.sqlite3"
    )


def normalize_site_id(site_id):
    return str(
        site_id or ""
    ).strip().upper()


class LocalMetadataStore:
    """Small SQLite store used by the locally installed dashboards."""

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
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

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
                CREATE TABLE IF NOT EXISTS clinical_assessments (
                    site_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    assessment_number INTEGER NOT NULL,
                    assessment_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        site_id,
                        patient_id,
                        assessment_number
                    )
                )
                """
            )

            clinical_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(clinical_assessments)"
                ).fetchall()
            }

            if "dictionary_version" not in clinical_columns:
                connection.execute(
                    """
                    ALTER TABLE clinical_assessments
                    ADD COLUMN dictionary_version TEXT NOT NULL DEFAULT ''
                    """
                )

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                clinical_assessment_id_unique
                ON clinical_assessments (
                    site_id,
                    patient_id,
                    assessment_id
                )
                """
            )

            now = datetime.now(
                timezone.utc
            ).isoformat()

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
                """,
                (
                    now,
                    now,
                ),
            )

            metadata_table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'metadata_records'
                """
            ).fetchone()

            if metadata_table is not None:
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
                    """,
                    (
                        now,
                        now,
                    ),
                )

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

    def patient_ids_for_site(
        self,
        site_id,
    ):
        site_id = normalize_site_id(
            site_id
        )

        with self._connect() as connection:
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

    def get_site_id(self):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT value
                FROM app_config
                WHERE key = 'site_id'
                """
            ).fetchone()

        if row is None:
            return ""

        return normalize_site_id(
            row["value"]
        )

    def set_site_id(
        self,
        site_id,
    ):
        value = normalize_site_id(
            site_id
        )

        if not value:
            raise ValueError(
                "Site ID cannot be blank."
            )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_config (
                    key,
                    value
                )
                VALUES (
                    'site_id',
                    ?
                )
                ON CONFLICT(key)
                DO UPDATE SET
                    value = excluded.value
                """,
                (
                    value,
                ),
            )

        return value

    def latest_clinical_assessment(
        self,
        site_id,
        patient_id,
    ):
        with self._connect() as connection:
            row = connection.execute(
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
                LIMIT 1
                """,
                (
                    normalize_site_id(
                        site_id
                    ),
                    str(
                        patient_id
                    ).strip(),
                ),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_assessment(
            row
        )

    def clinical_assessments_for_patient(
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
                ORDER BY assessment_number ASC
                """,
                (
                    site_id,
                    patient_id,
                ),
            ).fetchall()

        return [
            self._row_to_assessment(
                row
            )
            for row in rows
        ]

    def clinical_assessment(
        self,
        site_id,
        patient_id,
        assessment_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()
        assessment_id = str(
            assessment_id or ""
        ).strip().upper()

        if (
            not site_id
            or not patient_id
            or not assessment_id
        ):
            return None

        with self._connect() as connection:
            row = connection.execute(
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
                  AND UPPER(assessment_id) = ?
                LIMIT 1
                """,
                (
                    site_id,
                    patient_id,
                    assessment_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_assessment(
            row
        )

    def clinical_assessment_id_exists(
        self,
        site_id,
        patient_id,
        assessment_id,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()
        assessment_id = str(
            assessment_id or ""
        ).strip().upper()

        if (
            not site_id
            or not patient_id
            or not assessment_id
        ):
            return False

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM clinical_assessments
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND UPPER(assessment_id) = ?
                LIMIT 1
                """,
                (
                    site_id,
                    patient_id,
                    assessment_id,
                ),
            ).fetchone()

        return row is not None

    def import_clinical_assessments(
        self,
        site_id,
        patient_id,
        records,
        replace_existing_ids=None,
        dictionary_version="",
    ):
        """
        Insert or intentionally replace explicit Clinical Assessment IDs.

        After the import, the newest Clinical Assessment is treated as
        authoritative for patient-level fields such as Race and Sex.
        Those values are synchronized across the patient's complete
        Clinical Assessment history.
        """
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

        dictionary_version = str(
            dictionary_version or ""
        ).strip()

        replace_existing_ids = {
            str(
                assessment_id
            ).strip().upper()
            for assessment_id in (
                replace_existing_ids
                or []
            )
            if str(
                assessment_id
            ).strip()
        }

        prepared = []
        seen_ids = set()
        seen_numbers = set()

        for metadata in records:
            clean_metadata = dict(
                metadata
            )

            assessment_id = str(
                clean_metadata.get(
                    "Clinical Assessment ID"
                )
                or ""
            ).strip().upper()

            match = re.fullmatch(
                r"CA-(\d+)",
                assessment_id,
            )

            if match is None:
                raise ValueError(
                    "Clinical Assessment ID must use the "
                    "format CA-001, CA-002, and so on."
                )

            assessment_number = int(
                match.group(1)
            )

            if assessment_number < 1:
                raise ValueError(
                    "Clinical Assessment ID numbering must "
                    "start at CA-001."
                )

            canonical_id = self._assessment_id(
                assessment_number
            )

            if canonical_id != assessment_id:
                raise ValueError(
                    f"{assessment_id} is not a canonical Clinical "
                    f"Assessment ID. Use {canonical_id}."
                )

            if assessment_id in seen_ids:
                raise ValueError(
                    f"Duplicate Clinical Assessment ID "
                    f"{assessment_id} is selected for Patient "
                    f"{patient_id}."
                )

            if assessment_number in seen_numbers:
                raise ValueError(
                    f"Duplicate Clinical Assessment number "
                    f"{assessment_number} is selected for Patient "
                    f"{patient_id}."
                )

            seen_ids.add(
                assessment_id
            )
            seen_numbers.add(
                assessment_number
            )

            clean_metadata[
                "CoCANoT Patient ID"
            ] = patient_id

            clean_metadata[
                "Clinical Assessment ID"
            ] = assessment_id

            prepared.append(
                (
                    assessment_number,
                    assessment_id,
                    clean_metadata,
                )
            )

        if not prepared:
            return []

        self.create_patient(
            site_id,
            patient_id,
        )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self._connect() as connection:
            # First make sure there are no conflicting IDs or numbers.
            for (
                assessment_number,
                assessment_id,
                clean_metadata,
            ) in prepared:
                existing = connection.execute(
                    """
                    SELECT assessment_id
                    FROM clinical_assessments
                    WHERE UPPER(site_id) = ?
                      AND patient_id = ?
                      AND (
                          assessment_number = ?
                          OR UPPER(assessment_id) = ?
                      )
                    LIMIT 1
                    """,
                    (
                        site_id,
                        patient_id,
                        assessment_number,
                        assessment_id,
                    ),
                ).fetchone()

                if existing is not None:
                    if (
                        assessment_id
                        not in replace_existing_ids
                    ):
                        raise ValueError(
                            f"Clinical Assessment ID "
                            f"{assessment_id} already exists "
                            f"for Patient {patient_id}."
                        )

                    existing_id = str(
                        existing[
                            "assessment_id"
                        ]
                    ).strip().upper()

                    if existing_id != assessment_id:
                        raise ValueError(
                            f"Clinical Assessment number "
                            f"{assessment_number} already belongs "
                            f"to {existing['assessment_id']} for "
                            f"Patient {patient_id}."
                        )

            # Insert or replace the selected records.
            for (
                assessment_number,
                assessment_id,
                clean_metadata,
            ) in prepared:
                if (
                    assessment_id
                    in replace_existing_ids
                ):
                    connection.execute(
                        """
                        UPDATE clinical_assessments
                        SET data_json = ?,
                            updated_at = ?
                        WHERE UPPER(site_id) = ?
                          AND patient_id = ?
                          AND assessment_number = ?
                          AND UPPER(assessment_id) = ?
                        """,
                        (
                            self._dump(
                                clean_metadata
                            ),
                            now,
                            site_id,
                            patient_id,
                            assessment_number,
                            assessment_id,
                        ),
                    )

                    continue

                connection.execute(
                    """
                    INSERT INTO clinical_assessments (
                        site_id,
                        patient_id,
                        assessment_number,
                        assessment_id,
                        dictionary_version,
                        data_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        site_id,
                        patient_id,
                        assessment_number,
                        assessment_id,
                        dictionary_version,
                        self._dump(
                            clean_metadata
                        ),
                        now,
                        now,
                    ),
                )

            # The newest Clinical Assessment is authoritative for
            # patient-level fields after a longitudinal import.
            newest = connection.execute(
                """
                SELECT data_json
                FROM clinical_assessments
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                ORDER BY assessment_number DESC
                LIMIT 1
                """,
                (
                    site_id,
                    patient_id,
                ),
            ).fetchone()

            if newest is not None:
                authoritative_metadata = json.loads(
                    newest[
                        "data_json"
                    ]
                )

                self._synchronize_patient_level_fields(
                    connection,
                    site_id,
                    patient_id,
                    authoritative_metadata,
                    now,
                )

        return [
            {
                "assessment_number": assessment_number,
                "assessment_id": assessment_id,
                "metadata": clean_metadata,
            }
            for (
                assessment_number,
                assessment_id,
                clean_metadata,
            ) in prepared
        ]

    def update_historical_clinical_assessment(
        self,
        site_id,
        patient_id,
        assessment_id,
        metadata,
    ):
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id or ""
        ).strip()
        assessment_id = str(
            assessment_id or ""
        ).strip().upper()

        if not site_id:
            raise ValueError(
                "Site ID cannot be blank."
            )

        if not patient_id:
            raise ValueError(
                "CoCANoT Patient ID cannot be blank."
            )

        if not assessment_id:
            raise ValueError(
                "Clinical Assessment ID cannot be blank."
            )

        target = self.clinical_assessment(
            site_id,
            patient_id,
            assessment_id,
        )

        if target is None:
            raise ValueError(
                f"Clinical Assessment {assessment_id} was not found."
            )

        latest = self.latest_clinical_assessment(
            site_id,
            patient_id,
        )

        if latest is None:
            raise ValueError(
                "No Clinical Assessments were found for this patient."
            )

        if int(
            target[
                "assessment_number"
            ]
        ) >= int(
            latest[
                "assessment_number"
            ]
        ):
            raise ValueError(
                "Historical Clinical Assessment updates can only "
                "modify an assessment older than the current one."
            )

        clean_metadata = dict(
            metadata or {}
        )
        clean_metadata[
            "CoCANoT Patient ID"
        ] = patient_id
        clean_metadata[
            "Clinical Assessment ID"
        ] = assessment_id

        now = datetime.now(
            timezone.utc
        ).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE clinical_assessments
                SET data_json = ?,
                    updated_at = ?
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND assessment_number = ?
                  AND UPPER(assessment_id) = ?
                """,
                (
                    self._dump(
                        clean_metadata
                    ),
                    now,
                    site_id,
                    patient_id,
                    int(
                        target[
                            "assessment_number"
                        ]
                    ),
                    assessment_id,
                ),
            )

        saved = self.clinical_assessment(
            site_id,
            patient_id,
            assessment_id,
        )

        return {
            "action": "corrected_historical",
            "assessment_id": assessment_id,
            "metadata": (
                saved[
                    "metadata"
                ]
                if saved is not None
                else clean_metadata
            ),
            "dictionary_version": str(
                target.get(
                    "dictionary_version",
                    "",
                )
                or ""
            ),
            "dictionary_version_changed": False,
            "changed_tracked_fields": [],
            "changed_patient_level_fields": [],
        }

    def save_clinical_assessment(
        self,
        site_id,
        patient_id,
        metadata,
        tracked_fields,
        dictionary_version="",
    ):
        """
        Save the patient's current Clinical Assessment.

        A new Clinical Assessment ID is created when one or more
        dictionary-defined tracked fields changes.

        Patient-level fields are handled differently. If a value such
        as Race is corrected, that correction is synchronized across
        every Clinical Assessment belonging to the patient.
        """
        site_id = normalize_site_id(
            site_id
        )
        patient_id = str(
            patient_id
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

        clean_metadata = dict(
            metadata
        )
        dictionary_version = str(
            dictionary_version or ""
        ).strip()

        clean_metadata[
            "CoCANoT Patient ID"
        ] = patient_id

        latest = self.latest_clinical_assessment(
            site_id,
            patient_id,
        )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        # --------------------------------------------------
        # First Clinical Assessment
        # --------------------------------------------------

        if latest is None:
            assessment_number = 1

            assessment_id = self._assessment_id(
                assessment_number
            )

            clean_metadata[
                "Clinical Assessment ID"
            ] = assessment_id

            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO clinical_assessments (
                        site_id,
                        patient_id,
                        assessment_number,
                        assessment_id,
                        dictionary_version,
                        data_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        site_id,
                        patient_id,
                        assessment_number,
                        assessment_id,
                        dictionary_version,
                        self._dump(
                            clean_metadata
                        ),
                        now,
                        now,
                    ),
                )

            return {
                "action": "created",
                "assessment_id": assessment_id,
                "metadata": clean_metadata,
                "dictionary_version": dictionary_version,
                "dictionary_version_changed": False,
                "changed_tracked_fields": [],
                "changed_patient_level_fields": [],
            }

        # --------------------------------------------------
        # Determine which tracked fields changed.
        #
        # These fields continue to come from the existing
        # machine-readable dictionary.
        # --------------------------------------------------

        changed_tracked_fields = [
            field_name
            for field_name in tracked_fields
            if self._normalized(
                latest[
                    "metadata"
                ].get(
                    field_name
                )
            )
            != self._normalized(
                clean_metadata.get(
                    field_name
                )
            )
        ]

        dictionary_version_changed = (
            bool(dictionary_version)
            and dictionary_version
            != str(
                latest.get(
                    "dictionary_version",
                    "",
                )
                or ""
            ).strip()
        )

        # --------------------------------------------------
        # Determine whether a patient-level field was
        # corrected.
        # --------------------------------------------------

        changed_patient_level_fields = [
            field_name
            for field_name
            in PATIENT_LEVEL_CLINICAL_FIELDS
            if self._normalized(
                latest[
                    "metadata"
                ].get(
                    field_name
                )
            )
            != self._normalized(
                clean_metadata.get(
                    field_name
                )
            )
        ]

        with self._connect() as connection:
            # ----------------------------------------------
            # A tracked clinical change creates a new CA.
            # ----------------------------------------------

            if (
                changed_tracked_fields
                or dictionary_version_changed
            ):
                assessment_number = (
                    int(
                        latest[
                            "assessment_number"
                        ]
                    )
                    + 1
                )

                assessment_id = self._assessment_id(
                    assessment_number
                )

                clean_metadata[
                    "Clinical Assessment ID"
                ] = assessment_id

                connection.execute(
                    """
                    INSERT INTO clinical_assessments (
                        site_id,
                        patient_id,
                        assessment_number,
                        assessment_id,
                        dictionary_version,
                        data_json,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        site_id,
                        patient_id,
                        assessment_number,
                        assessment_id,
                        dictionary_version,
                        self._dump(
                            clean_metadata
                        ),
                        now,
                        now,
                    ),
                )

                action = (
                    "created_new_assessment"
                )

            # ----------------------------------------------
            # No tracked field changed.
            #
            # Keep the existing CA ID and update the latest
            # assessment if any metadata changed.
            # ----------------------------------------------

            else:
                assessment_number = int(
                    latest[
                        "assessment_number"
                    ]
                )

                assessment_id = latest[
                    "assessment_id"
                ]

                clean_metadata[
                    "Clinical Assessment ID"
                ] = assessment_id

                if self._normalized(
                    latest[
                        "metadata"
                    ]
                ) != self._normalized(
                    clean_metadata
                ):
                    connection.execute(
                        """
                        UPDATE clinical_assessments
                        SET data_json = ?,
                            updated_at = ?
                        WHERE UPPER(site_id) = ?
                          AND patient_id = ?
                          AND assessment_number = ?
                        """,
                        (
                            self._dump(
                                clean_metadata
                            ),
                            now,
                            site_id,
                            patient_id,
                            assessment_number,
                        ),
                    )

                    action = (
                        "corrected_existing"
                    )

                else:
                    action = "kept_existing"

            # ----------------------------------------------
            # If a patient-level field was corrected, apply
            # the corrected value retrospectively to every
            # Clinical Assessment for this patient.
            # ----------------------------------------------

            if changed_patient_level_fields:
                self._synchronize_patient_level_fields(
                    connection,
                    site_id,
                    patient_id,
                    clean_metadata,
                    now,
                    fields=(
                        changed_patient_level_fields
                    ),
                )

        saved = self.clinical_assessment(
            site_id,
            patient_id,
            assessment_id,
        )

        return {
            "action": action,
            "assessment_id": assessment_id,
            "metadata": (
                saved[
                    "metadata"
                ]
                if saved is not None
                else clean_metadata
            ),
            "dictionary_version": (
                saved.get(
                    "dictionary_version",
                    dictionary_version,
                )
                if saved is not None
                else dictionary_version
            ),
            "dictionary_version_changed": (
                dictionary_version_changed
            ),
            "changed_tracked_fields": (
                changed_tracked_fields
            ),
            "changed_patient_level_fields": (
                changed_patient_level_fields
            ),
        }

    def _synchronize_patient_level_fields(
        self,
        connection,
        site_id,
        patient_id,
        authoritative_metadata,
        now,
        fields=None,
    ):
        """
        Synchronize patient-level values across every Clinical Assessment.

        authoritative_metadata contains the values that should become
        authoritative for the patient.

        If fields is supplied, only those patient-level fields are
        synchronized. Otherwise, every configured patient-level field
        is synchronized.
        """
        if fields is None:
            fields = (
                PATIENT_LEVEL_CLINICAL_FIELDS
            )

        fields = [
            field_name
            for field_name in fields
            if field_name
            in PATIENT_LEVEL_CLINICAL_FIELDS
        ]

        if not fields:
            return

        rows = connection.execute(
            """
            SELECT
                assessment_number,
                assessment_id,
                data_json
            FROM clinical_assessments
            WHERE UPPER(site_id) = ?
              AND patient_id = ?
            ORDER BY assessment_number ASC
            """,
            (
                site_id,
                patient_id,
            ),
        ).fetchall()

        for row in rows:
            historical_metadata = json.loads(
                row[
                    "data_json"
                ]
            )

            changed = False

            for field_name in fields:
                authoritative_value = (
                    authoritative_metadata.get(
                        field_name
                    )
                )

                if self._normalized(
                    historical_metadata.get(
                        field_name
                    )
                ) != self._normalized(
                    authoritative_value
                ):
                    historical_metadata[
                        field_name
                    ] = authoritative_value

                    changed = True

            if not changed:
                continue

            # Never change which patient or Clinical Assessment
            # this historical row belongs to.
            historical_metadata[
                "CoCANoT Patient ID"
            ] = patient_id

            historical_metadata[
                "Clinical Assessment ID"
            ] = row[
                "assessment_id"
            ]

            connection.execute(
                """
                UPDATE clinical_assessments
                SET data_json = ?,
                    updated_at = ?
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND assessment_number = ?
                """,
                (
                    self._dump(
                        historical_metadata
                    ),
                    now,
                    site_id,
                    patient_id,
                    row[
                        "assessment_number"
                    ],
                ),
            )

    @staticmethod
    def _assessment_id(
        number,
    ):
        return (
            f"CA-{int(number):03d}"
        )

    @staticmethod
    def _dump(
        value,
    ):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _normalized(
        value,
    ):
        if type(value) is dict:
            return {
                key: (
                    LocalMetadataStore._normalized(
                        item
                    )
                )
                for key, item
                in sorted(
                    value.items()
                )
            }

        if type(value) is list:
            normalized = [
                LocalMetadataStore._normalized(
                    item
                )
                for item in value
            ]

            return sorted(
                normalized,
                key=lambda item: str(
                    item
                ),
            )

        if type(value) is str:
            return value.strip()

        return value

    @staticmethod
    def _row_to_assessment(
        row,
    ):
        return {
            "site_id": row[
                "site_id"
            ],
            "patient_id": row[
                "patient_id"
            ],
            "assessment_number": row[
                "assessment_number"
            ],
            "assessment_id": row[
                "assessment_id"
            ],
            "dictionary_version": row[
                "dictionary_version"
            ],
            "metadata": json.loads(
                row[
                    "data_json"
                ]
            ),
            "created_at": row[
                "created_at"
            ],
            "updated_at": row[
                "updated_at"
            ],
        }