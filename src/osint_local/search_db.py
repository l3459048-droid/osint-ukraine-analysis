from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .chunking import build_chunks
from .config import Settings

SEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_documents (
    document_sha256 TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    text_size INTEGER NOT NULL,
    text_mtime_ns INTEGER NOT NULL,
    indexed_at TEXT NOT NULL,
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS search_chunks (
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
CREATE INDEX IF NOT EXISTS idx_search_chunks_document ON search_chunks(document_sha256);
CREATE INDEX IF NOT EXISTS idx_search_chunks_page ON search_chunks(page);
CREATE TABLE IF NOT EXISTS search_embeddings (
    chunk_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY (chunk_id, model),
    FOREIGN KEY(chunk_id) REFERENCES search_chunks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_search_embeddings_model ON search_embeddings(model);
"""


class SearchDatabase:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(settings.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SEARCH_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def sync_chunks(self, force: bool = False) -> dict[str, int]:
        self.conn.execute(
            """DELETE FROM search_documents WHERE document_sha256 NOT IN
               (SELECT sha256 FROM documents WHERE status='done')"""
        )
        rows = self.conn.execute(
            "SELECT sha256, source_path FROM documents WHERE status='done' ORDER BY id"
        ).fetchall()
        changed = 0
        chunks_written = 0
        for row in rows:
            text_path = self.settings.text_dir / f"{row['sha256']}.txt"
            if not text_path.exists():
                continue
            stat = text_path.stat()
            current = self.conn.execute(
                "SELECT * FROM search_documents WHERE document_sha256=?", (row["sha256"],)
            ).fetchone()
            if not force and current and current["text_size"] == stat.st_size and current["text_mtime_ns"] == stat.st_mtime_ns:
                continue
            chunks = build_chunks(text_path.read_text(encoding="utf-8", errors="replace"), self.settings.search)
            self.conn.execute("DELETE FROM search_chunks WHERE document_sha256=?", (row["sha256"],))
            self.conn.executemany(
                """INSERT INTO search_chunks
                   (document_sha256, page, chunk_index, start_char, end_char, text)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(row["sha256"], c.page, c.chunk_index, c.start_char, c.end_char, c.text) for c in chunks],
            )
            self.conn.execute(
                """INSERT INTO search_documents
                   (document_sha256, source_path, text_size, text_mtime_ns, indexed_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(document_sha256) DO UPDATE SET
                     source_path=excluded.source_path, text_size=excluded.text_size,
                     text_mtime_ns=excluded.text_mtime_ns, indexed_at=excluded.indexed_at""",
                (row["sha256"], row["source_path"], stat.st_size, stat.st_mtime_ns, datetime.now(timezone.utc).isoformat()),
            )
            changed += 1
            chunks_written += len(chunks)
        self.conn.commit()
        return {"documents_reindexed": changed, "chunks_written": chunks_written}

    def missing_embedding_rows(self, model: str, force: bool):
        if force:
            return self.conn.execute("SELECT id, text FROM search_chunks ORDER BY id").fetchall()
        return self.conn.execute(
            """SELECT c.id, c.text FROM search_chunks c
               LEFT JOIN search_embeddings e ON e.chunk_id=c.id AND e.model=?
               WHERE e.chunk_id IS NULL ORDER BY c.id""", (model,)
        ).fetchall()

    def store_embeddings(self, model: str, payload: list[tuple[int, int, bytes]]) -> None:
        self.conn.executemany(
            """INSERT INTO search_embeddings(chunk_id, model, dimension, vector)
               VALUES (?, ?, ?, ?) ON CONFLICT(chunk_id, model) DO UPDATE SET
               dimension=excluded.dimension, vector=excluded.vector""",
            [(chunk_id, model, dimension, vector) for chunk_id, dimension, vector in payload],
        )
        self.conn.commit()

    def semantic_rows(self, model: str):
        return self.conn.execute(
            """SELECT c.document_sha256, d.source_path, c.page, c.chunk_index, c.text, e.vector
               FROM search_embeddings e JOIN search_chunks c ON c.id=e.chunk_id
               JOIN documents d ON d.sha256=c.document_sha256
               WHERE e.model=? AND d.status='done'""", (model,)
        ).fetchall()

    def lexical_rows(self):
        return self.conn.execute(
            """SELECT c.document_sha256, d.source_path, c.page, c.chunk_index, c.text
               FROM search_chunks c JOIN documents d ON d.sha256=c.document_sha256
               WHERE d.status='done'"""
        ).fetchall()

    def chunk_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM search_chunks").fetchone()[0])

    def embedding_count(self, model: str) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM search_embeddings WHERE model=?", (model,)).fetchone()[0])

    def stats(self, model: str) -> dict:
        return {
            "indexed_documents": int(self.conn.execute("SELECT COUNT(*) FROM search_documents").fetchone()[0]),
            "chunks": self.chunk_count(),
            "semantic_model": model,
            "embeddings": self.embedding_count(model),
        }
