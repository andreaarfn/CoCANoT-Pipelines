"""Local-only surgical follow-up tracking.

This module deliberately stores real surgery dates in a separate SQLite
database from CoCANoT consortium metadata. Nothing in this module adds the
real surgery date to metadata_records or clinical_assessments.
"""

from __future__ import annotations

import calendar
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from MetadataPipeline.storage.local_database import (
    default_database_path,
    normalize_site_id,
)


MILESTONES = (12, 24, 36, 48, 60)
DUE_SOON_DAYS = 30


def default_followup_database_path():
    override = os.environ.get(
        "COCANOT_LOCAL_FOLLOWUP_DB",
        "",
    ).strip()

    if override:
        return Path(override).expanduser()

    return (
        Path.home()
        / ".cocanot"
        / "local_tracking"
        / "surgical_followup.sqlite3"
    )


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(
        value.day,
        calendar.monthrange(year, month)[1],
    )
    return date(year, month, day)


class SurgicalFollowupStore:
    """Stores real surgery dates locally and derives attention items."""

    def __init__(
        self,
        database_path=None,
        metadata_database_path=None,
    ):
        self.database_path = Path(
            database_path
            or default_followup_database_path()
        ).expanduser()

        self.metadata_database_path = Path(
            metadata_database_path
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

    def _metadata_connect(self):
        connection = sqlite3.connect(
            self.metadata_database_path
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS surgical_followup_tracking (
                    site_id TEXT NOT NULL,
                    patient_id TEXT NOT NULL,
                    surgery_id TEXT NOT NULL,
                    real_surgery_date TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        site_id,
                        patient_id,
                        surgery_id
                    )
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                surgical_followup_due_lookup
                ON surgical_followup_tracking (
                    site_id,
                    real_surgery_date
                )
                """
            )

    def save_real_surgery_date(
        self,
        site_id,
        patient_id,
        surgery_id,
        real_surgery_date,
    ):
        site_id = normalize_site_id(site_id)
        patient_id = str(patient_id or "").strip()
        surgery_id = str(surgery_id or "").strip()
        date_text = str(real_surgery_date or "").strip()

        if not site_id:
            raise ValueError("Site ID cannot be blank.")
        if not patient_id:
            raise ValueError("CoCANoT Patient ID cannot be blank.")
        if not surgery_id:
            raise ValueError("Surgery ID cannot be blank.")
        if not date_text:
            raise ValueError("Actual surgery date cannot be blank.")

        try:
            parsed = date.fromisoformat(date_text)
        except ValueError as exc:
            raise ValueError(
                "Actual surgery date must use YYYY-MM-DD."
            ) from exc

        canonical_date = parsed.isoformat()
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT created_at
                FROM surgical_followup_tracking
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND surgery_id = ?
                """,
                (site_id, patient_id, surgery_id),
            ).fetchone()

            connection.execute(
                """
                INSERT INTO surgical_followup_tracking (
                    site_id,
                    patient_id,
                    surgery_id,
                    real_surgery_date,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    site_id,
                    patient_id,
                    surgery_id
                )
                DO UPDATE SET
                    real_surgery_date = excluded.real_surgery_date,
                    updated_at = excluded.updated_at
                """,
                (
                    site_id,
                    patient_id,
                    surgery_id,
                    canonical_date,
                    (
                        existing["created_at"]
                        if existing is not None
                        else now
                    ),
                    now,
                ),
            )

            saved = connection.execute(
                """
                SELECT
                    site_id,
                    patient_id,
                    surgery_id,
                    real_surgery_date,
                    created_at,
                    updated_at
                FROM surgical_followup_tracking
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND surgery_id = ?
                LIMIT 1
                """,
                (site_id, patient_id, surgery_id),
            ).fetchone()

        if saved is None:
            raise RuntimeError(
                "Actual surgery date could not be read back after saving."
            )

        result = dict(saved)

        if result["real_surgery_date"] != canonical_date:
            raise RuntimeError(
                "Actual surgery date changed unexpectedly while saving."
            )

        return result

    def get_real_surgery_date(
        self,
        site_id,
        patient_id,
        surgery_id,
    ):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    site_id,
                    patient_id,
                    surgery_id,
                    real_surgery_date,
                    created_at,
                    updated_at
                FROM surgical_followup_tracking
                WHERE UPPER(site_id) = ?
                  AND patient_id = ?
                  AND surgery_id = ?
                LIMIT 1
                """,
                (
                    normalize_site_id(site_id),
                    str(patient_id or "").strip(),
                    str(surgery_id or "").strip(),
                ),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def needs_attention(
        self,
        site_id,
        today=None,
    ):
        site_id = normalize_site_id(site_id)
        today = today or date.today()
        items = []

        with self._metadata_connect() as metadata_connection:
            surgical_rows = metadata_connection.execute(
                """
                SELECT
                    patient_id,
                    record_id,
                    data_json
                FROM metadata_records
                WHERE UPPER(site_id) = ?
                  AND table_name = 'Surgical'
                ORDER BY patient_id, record_id
                """,
                (site_id,),
            ).fetchall()

        with self._connect() as local_connection:
            tracking_rows = local_connection.execute(
                """
                SELECT
                    patient_id,
                    surgery_id,
                    real_surgery_date
                FROM surgical_followup_tracking
                WHERE UPPER(site_id) = ?
                """,
                (site_id,),
            ).fetchall()

        tracking = {
            (
                str(row["patient_id"]),
                str(row["surgery_id"]),
            ): str(row["real_surgery_date"])
            for row in tracking_rows
        }

        for row in surgical_rows:
            patient_id = str(row["patient_id"])
            surgery_id = str(row["record_id"])
            metadata = json.loads(row["data_json"])
            real_date_text = tracking.get(
                (patient_id, surgery_id)
            )

            if not real_date_text:
                items.append(
                    {
                        "attention_id": (
                            f"{patient_id}:{surgery_id}:real-date"
                        ),
                        "patient_id": patient_id,
                        "surgery_id": surgery_id,
                        "category": "Surgical",
                        "status": "missing",
                        "milestone_months": None,
                        "message": (
                            "Add the local actual surgery date "
                            "to enable follow-up reminders."
                        ),
                    }
                )
                continue

            surgery_date = date.fromisoformat(real_date_text)

            for months in MILESTONES:
                due_date = _add_months(
                    surgery_date,
                    months,
                )

                if self._milestone_complete(
                    metadata,
                    months,
                ):
                    continue

                days_until = (
                    due_date - today
                ).days

                if days_until > DUE_SOON_DAYS:
                    continue

                if days_until < 0:
                    status = "overdue"
                    message = (
                        f"{months}-month surgical outcomes "
                        f"overdue by {abs(days_until)} day(s)."
                    )
                elif days_until == 0:
                    status = "due"
                    message = (
                        f"{months}-month surgical outcomes "
                        "due today."
                    )
                else:
                    status = "due_soon"
                    message = (
                        f"{months}-month surgical outcomes "
                        f"due in {days_until} day(s)."
                    )

                items.append(
                    {
                        "attention_id": (
                            f"{patient_id}:{surgery_id}:{months}"
                        ),
                        "patient_id": patient_id,
                        "surgery_id": surgery_id,
                        "category": "Surgical",
                        "status": status,
                        "milestone_months": months,
                        "due_date": due_date.isoformat(),
                        "message": message,
                    }
                )

        priority = {
            "overdue": 0,
            "due": 1,
            "due_soon": 2,
            "missing": 3,
        }

        return sorted(
            items,
            key=lambda item: (
                priority.get(item["status"], 9),
                item.get("due_date") or "9999-12-31",
                item["patient_id"],
                item["surgery_id"],
            ),
        )

    @staticmethod
    def _milestone_complete(
        metadata,
        months,
    ):
        prefix = f"{months}-Month"

        count = metadata.get(
            f"{prefix} Postoperative Seizure Frequency Count"
        )
        period = str(
            metadata.get(
                f"{prefix} Postoperative Seizure Frequency Period"
            )
            or ""
        ).strip()
        other_period = str(
            metadata.get(
                f"{prefix} Other Postoperative Seizure Frequency Period (if applicable; free text)"
            )
            or ""
        ).strip()
        engel = str(
            metadata.get(
                f"{prefix} Engel Outcome"
            )
            or ""
        ).strip()
        ilae = str(
            metadata.get(
                f"{prefix} ILAE"
            )
            or ""
        ).strip()

        if not period or not engel or not ilae:
            return False

        if period == "Other" and not other_period:
            return False

        if (
            period != "Unable to quantify"
            and str(count ?? "").strip() == ""
        ):
            return False

        return True
