"""Safe local SQLite persistence scaffold without secret storage."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class BatchRepository:
    """Owns local batch metadata only; secrets and raw document content are excluded."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    provider TEXT NOT NULL,
                    document_count INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft'
                )
                """
            )

    def create_draft(self, provider: str, document_count: int) -> int:
        with sqlite3.connect(self._database_path) as connection:
            cursor = connection.execute(
                "INSERT INTO batches (provider, document_count) VALUES (?, ?)",
                (provider, document_count),
            )
            return int(cursor.lastrowid)
