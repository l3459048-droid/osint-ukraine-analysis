from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    source_path TEXT NOT NULL,
    source_size INTEGER NOT NULL,
    source_mtime_ns INTEGER NOT NULL,
    extension TEXT NOT NULL,
    status TEXT NOT NULL,
    extraction_method TEXT,
    text_chars INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_documents_source_path ON documents(source_path);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

CREATE TABLE IF NOT EXISTS classifications (
    document_sha256 TEXT NOT NULL,
    domain TEXT NOT NULL,
    score INTEGER NOT NULL,
    PRIMARY KEY (document_sha256, domain),
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256) ON DELETE CASCADE
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Watchdog callbacks may run on worker/timer threads. A single connection is
        # shared deliberately and serialized with an RLock.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def find_by_hash(self, sha256: str):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
            ).fetchone()

    def find_current_source(self, source_path: str, size: int, mtime_ns: int):
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM documents
                   WHERE source_path = ? AND source_size = ? AND source_mtime_ns = ?
                   ORDER BY id DESC LIMIT 1""",
                (source_path, size, mtime_ns),
            ).fetchone()

    def upsert_processing(
        self, *, sha256: str, source_path: str, source_size: int,
        source_mtime_ns: int, extension: str
    ) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO documents
                  (sha256, source_path, source_size, source_mtime_ns, extension, status)
                VALUES (?, ?, ?, ?, ?, 'processing')
                ON CONFLICT(sha256) DO UPDATE SET
                  source_path=excluded.source_path,
                  source_size=excluded.source_size,
                  source_mtime_ns=excluded.source_mtime_ns,
                  extension=excluded.extension,
                  status='processing',
                  error=NULL
                """,
                (sha256, source_path, source_size, source_mtime_ns, extension),
            )
            self.conn.commit()

    def mark_done(
        self, *, sha256: str, extraction_method: str, text_chars: int,
        processed_at: str, metadata_json: str,
        classifications: list[tuple[str, int]]
    ) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE documents SET status='done', extraction_method=?, text_chars=?,
                   processed_at=?, error=NULL, metadata_json=? WHERE sha256=?""",
                (extraction_method, text_chars, processed_at, metadata_json, sha256),
            )
            self.conn.execute(
                "DELETE FROM classifications WHERE document_sha256=?", (sha256,)
            )
            self.conn.executemany(
                "INSERT INTO classifications(document_sha256, domain, score) VALUES (?, ?, ?)",
                [(sha256, domain, score) for domain, score in classifications],
            )
            self.conn.commit()

    def mark_error(self, sha256: str, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE documents SET status='error', error=? WHERE sha256=?",
                (error, sha256),
            )
            self.conn.commit()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
            ).fetchall()
        statuses = {row["status"]: row["n"] for row in rows}
        return {"total": sum(statuses.values()), "statuses": statuses}
