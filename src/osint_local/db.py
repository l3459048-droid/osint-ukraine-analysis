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
    metadata_json TEXT NOT NULL DEFAULT '{}',
    pipeline_version INTEGER NOT NULL DEFAULT 2
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

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_sha256 TEXT NOT NULL,
    page INTEGER,
    chunk_index INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(document_sha256, chunk_index),
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_sha256);
CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks(page);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (chunk_id, model),
    FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(documents)").fetchall()}
        if "pipeline_version" not in columns:
            self.conn.execute(
                "ALTER TABLE documents ADD COLUMN pipeline_version INTEGER NOT NULL DEFAULT 1"
            )
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()


    def get_document(self, sha256: str):
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM documents WHERE sha256=?", (sha256,)
            ).fetchone()

    def get_classifications(self, sha256: str) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT domain, score FROM classifications
                   WHERE document_sha256=? ORDER BY score DESC, domain""",
                (sha256,),
            ).fetchall()

    def category_counts(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                """SELECT domain, COUNT(DISTINCT document_sha256) AS documents
                   FROM classifications GROUP BY domain
                   ORDER BY documents DESC, domain"""
            ).fetchall()
        return [{"domain": row["domain"], "documents": int(row["documents"])} for row in rows]

    def document_count(self, *, domain: str | None = None) -> int:
        with self._lock:
            if domain:
                row = self.conn.execute(
                    """SELECT COUNT(DISTINCT d.sha256) AS n FROM documents d
                       JOIN classifications c ON c.document_sha256=d.sha256
                       WHERE d.status='done' AND c.domain=?""",
                    (domain,),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT COUNT(*) AS n FROM documents WHERE status='done'"
                ).fetchone()
        return int(row["n"])

    def list_documents(
        self, *, limit: int = 50, offset: int = 0, domain: str | None = None
    ) -> list[sqlite3.Row]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))
        with self._lock:
            if domain:
                return self.conn.execute(
                    """SELECT DISTINCT d.* FROM documents d
                       JOIN classifications c ON c.document_sha256=d.sha256
                       WHERE d.status='done' AND c.domain=?
                       ORDER BY d.processed_at DESC, d.source_path
                       LIMIT ? OFFSET ?""",
                    (domain, limit, offset),
                ).fetchall()
            return self.conn.execute(
                """SELECT * FROM documents WHERE status='done'
                   ORDER BY processed_at DESC, source_path LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

    def chunks_for_document(self, sha256: str, *, limit: int = 1000) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT id, document_sha256, page, chunk_index, start_char, end_char, text
                   FROM chunks WHERE document_sha256=?
                   ORDER BY chunk_index LIMIT ?""",
                (sha256, max(1, min(10000, int(limit)))),
            ).fetchall()

    def chunk_count(self) -> int:
        with self._lock:
            row = self.conn.execute(
                """SELECT COUNT(*) AS n FROM chunks c
                   JOIN documents d ON d.sha256=c.document_sha256
                   WHERE d.status='done'"""
            ).fetchone()
        return int(row["n"])

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
                     AND pipeline_version >= 2
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
        classifications: list[tuple[str, int]], chunks: list
    ) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE documents SET status='done', extraction_method=?, text_chars=?,
                   processed_at=?, error=NULL, metadata_json=?, pipeline_version=2 WHERE sha256=?""",
                (extraction_method, text_chars, processed_at, metadata_json, sha256),
            )
            self.conn.execute(
                "DELETE FROM classifications WHERE document_sha256=?", (sha256,)
            )
            self.conn.executemany(
                "INSERT INTO classifications(document_sha256, domain, score) VALUES (?, ?, ?)",
                [(sha256, domain, score) for domain, score in classifications],
            )
            # Replacing chunks also cascades removal of stale embeddings.
            self.conn.execute("DELETE FROM chunks WHERE document_sha256=?", (sha256,))
            self.conn.executemany(
                """INSERT INTO chunks
                   (document_sha256, page, chunk_index, start_char, end_char, text)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (
                        sha256,
                        chunk.page,
                        chunk.chunk_index,
                        chunk.start_char,
                        chunk.end_char,
                        chunk.text,
                    )
                    for chunk in chunks
                ],
            )
            self.conn.commit()

    def mark_error(self, sha256: str, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE documents SET status='error', error=? WHERE sha256=?",
                (error, sha256),
            )
            self.conn.commit()

    def chunks_for_embedding(
        self, model: str, *, force: bool = False, document_sha256: str | None = None
    ) -> list[sqlite3.Row]:
        with self._lock:
            where = []
            params: list[Any] = [model]
            if not force:
                where.append("e.chunk_id IS NULL")
            if document_sha256:
                where.append("c.document_sha256 = ?")
                params.append(document_sha256)
            clause = " WHERE " + " AND ".join(where) if where else ""
            return self.conn.execute(
                f"""SELECT c.id, c.document_sha256, c.text
                    FROM chunks c
                    LEFT JOIN embeddings e ON e.chunk_id = c.id AND e.model = ?
                    {clause}
                    ORDER BY c.id""",
                params,
            ).fetchall()

    def save_embeddings(self, rows: list[tuple[int, str, int, bytes]]) -> None:
        with self._lock:
            self.conn.executemany(
                """INSERT INTO embeddings(chunk_id, model, dimension, vector)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(chunk_id, model) DO UPDATE SET
                     dimension=excluded.dimension,
                     vector=excluded.vector""",
                rows,
            )
            self.conn.commit()

    def embedding_count(self, model: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM embeddings WHERE model=?", (model,)
            ).fetchone()
            return int(row["n"])

    def iter_embeddings(self, model: str) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT c.document_sha256, d.source_path, c.page, c.chunk_index,
                          c.text, e.vector, e.dimension
                   FROM embeddings e
                   JOIN chunks c ON c.id = e.chunk_id
                   JOIN documents d ON d.sha256 = c.document_sha256
                   WHERE e.model=? AND d.status='done'
                   ORDER BY c.id""",
                (model,),
            ).fetchall()

    def iter_chunks(self) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT c.document_sha256, d.source_path, c.page, c.chunk_index, c.text
                   FROM chunks c
                   JOIN documents d ON d.sha256 = c.document_sha256
                   WHERE d.status='done'
                   ORDER BY c.id"""
            ).fetchall()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
            ).fetchall()
            chunk_count = int(self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
            embedding_rows = self.conn.execute(
                "SELECT model, COUNT(*) AS n FROM embeddings GROUP BY model"
            ).fetchall()
        statuses = {row["status"]: row["n"] for row in rows}
        return {
            "total": sum(statuses.values()),
            "statuses": statuses,
            "chunks": chunk_count,
            "embeddings": {row["model"]: row["n"] for row in embedding_rows},
        }
