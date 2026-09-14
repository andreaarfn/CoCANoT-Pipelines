"""Local SQLite storage for CoCANoT development bug reports."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from MetadataPipeline.storage.local_database import (
    default_database_path,
)


CREATE_BUG_REPORTS = """
CREATE TABLE IF NOT EXISTS bug_reports (
    bug_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    workflow TEXT NOT NULL,
    summary TEXT NOT NULL,
    description TEXT NOT NULL,
    expected_behavior TEXT NOT NULL,
    technical_details_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'Saved Locally'
)
"""


class BugStore:
    def __init__(self, database_path=None):
        self.database_path = (
            database_path
            or default_database_path()
        )

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.database_path)

    def _initialize(self):
        with self._connect() as connection:
            connection.execute(CREATE_BUG_REPORTS)
            connection.commit()

    def save_report(
        self,
        site_id,
        workflow,
        summary,
        description,
        expected_behavior,
        technical_details,
    ):
        bug_id = "BUG-" + uuid.uuid4().hex[:10].upper()
        created_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO bug_reports (
                    bug_id,
                    site_id,
                    created_at,
                    workflow,
                    summary,
                    description,
                    expected_behavior,
                    technical_details_json,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bug_id,
                    site_id,
                    created_at,
                    workflow,
                    summary,
                    description,
                    expected_behavior,
                    json.dumps(
                        technical_details or {},
                        sort_keys=True,
                    ),
                    "Saved Locally",
                ),
            )
            connection.commit()

        return {
            "bug_id": bug_id,
            "created_at": created_at,
        }

    def update_status(self, bug_id, status):
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE bug_reports
                SET status = ?
                WHERE bug_id = ?
                """,
                (status, bug_id),
            )
            connection.commit()
