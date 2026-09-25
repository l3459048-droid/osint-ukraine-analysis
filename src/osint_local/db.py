from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

PIPELINE_VERSION = 5

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
    language TEXT,
    pipeline_version INTEGER NOT NULL DEFAULT 5
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
CREATE TABLE IF NOT EXISTS translations (
    document_sha256 TEXT NOT NULL,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    output_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    engine TEXT NOT NULL,
    PRIMARY KEY (document_sha256, source_lang, target_lang),
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_translations_document ON translations(document_sha256);

CREATE TABLE IF NOT EXISTS taxonomy_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    model TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    embedding_count INTEGER NOT NULL DEFAULT 0,
    topic_count INTEGER NOT NULL DEFAULT 0,
    category_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_taxonomy_runs_status ON taxonomy_runs(status, id);

CREATE TABLE IF NOT EXISTS taxonomy_categories (
    category_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    centroid BLOB,
    dimension INTEGER NOT NULL DEFAULT 0,
    document_count INTEGER NOT NULL DEFAULT 0,
    topic_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'discovered',
    updated_at TEXT NOT NULL,
    run_id INTEGER,
    FOREIGN KEY(run_id) REFERENCES taxonomy_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_taxonomy_categories_count
    ON taxonomy_categories(document_count DESC, name);

CREATE TABLE IF NOT EXISTS taxonomy_topics (
    topic_key TEXT PRIMARY KEY,
    category_key TEXT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    keywords_json TEXT NOT NULL DEFAULT '[]',
    centroid BLOB,
    dimension INTEGER NOT NULL DEFAULT 0,
    document_count INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'discovered',
    updated_at TEXT NOT NULL,
    run_id INTEGER,
    FOREIGN KEY(category_key) REFERENCES taxonomy_categories(category_key) ON DELETE SET NULL,
    FOREIGN KEY(run_id) REFERENCES taxonomy_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_taxonomy_topics_category
    ON taxonomy_topics(category_key, document_count DESC, name);

CREATE TABLE IF NOT EXISTS document_taxonomy_topics (
    document_sha256 TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY(document_sha256, topic_key),
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256) ON DELETE CASCADE,
    FOREIGN KEY(topic_key) REFERENCES taxonomy_topics(topic_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_document_taxonomy_topics_topic
    ON document_taxonomy_topics(topic_key, score DESC);

CREATE TABLE IF NOT EXISTS document_taxonomy_categories (
    document_sha256 TEXT NOT NULL,
    category_key TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY(document_sha256, category_key),
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256) ON DELETE CASCADE,
    FOREIGN KEY(category_key) REFERENCES taxonomy_categories(category_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_document_taxonomy_categories_category
    ON document_taxonomy_categories(category_key, score DESC);

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
        changed = False
        if "pipeline_version" not in columns:
            self.conn.execute(
                "ALTER TABLE documents ADD COLUMN pipeline_version INTEGER NOT NULL DEFAULT 1"
            )
            changed = True
        if "language" not in columns:
            self.conn.execute("ALTER TABLE documents ADD COLUMN language TEXT")
            changed = True
        if changed:
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
        limit = max(1, min(5000, int(limit)))
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

    def find_current_source(
        self,
        source_path: str,
        size: int,
        mtime_ns: int,
        *,
        min_pipeline_version: int = 2,
    ):
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM documents
                   WHERE source_path = ? AND source_size = ? AND source_mtime_ns = ?
                     AND pipeline_version >= ? AND status='done'
                   ORDER BY id DESC LIMIT 1""",
                (source_path, size, mtime_ns, max(1, int(min_pipeline_version))),
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
        processed_at: str, metadata_json: str, language: str | None,
        classifications: list[tuple[str, int]], chunks: list
    ) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE documents SET status='done', extraction_method=?, text_chars=?,
                   processed_at=?, error=NULL, metadata_json=?, language=?, pipeline_version=? WHERE sha256=?""",
                (extraction_method, text_chars, processed_at, metadata_json, language, PIPELINE_VERSION, sha256),
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

    def embedding_signature(self, model: str) -> str:
        with self._lock:
            row = self.conn.execute(
                """SELECT COUNT(*) AS n,
                          COALESCE(SUM(e.chunk_id), 0) AS id_sum,
                          COALESCE(MAX(e.chunk_id), 0) AS id_max
                   FROM embeddings e
                   JOIN chunks c ON c.id=e.chunk_id
                   JOIN documents d ON d.sha256=c.document_sha256
                   WHERE e.model=? AND d.status='done'""",
                (model,),
            ).fetchone()
        return f"{int(row['n'])}:{int(row['id_sum'])}:{int(row['id_max'])}"

    def iter_embeddings(self, model: str, filters: dict | None = None) -> list[sqlite3.Row]:
        clause, params = self._document_filter_clause(filters, alias="d")
        with self._lock:
            return self.conn.execute(
                f"""SELECT c.document_sha256, d.source_path, c.page, c.chunk_index,
                           c.text, e.vector, e.dimension
                    FROM embeddings e
                    JOIN chunks c ON c.id = e.chunk_id
                    JOIN documents d ON d.sha256 = c.document_sha256
                    WHERE e.model=? AND d.status='done'{clause}
                    ORDER BY c.id""",
                [model, *params],
            ).fetchall()

    def iter_chunks(self, filters: dict | None = None) -> list[sqlite3.Row]:
        clause, params = self._document_filter_clause(filters, alias="d")
        with self._lock:
            return self.conn.execute(
                f"""SELECT c.document_sha256, d.source_path, c.page, c.chunk_index, c.text
                    FROM chunks c
                    JOIN documents d ON d.sha256 = c.document_sha256
                    WHERE d.status='done'{clause}
                    ORDER BY c.id""",
                params,
            ).fetchall()

    def update_document_language(self, sha256: str, language: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE documents SET language=? WHERE sha256=?",
                (language, sha256),
            )
            self.conn.commit()

    def documents_missing_language(self, *, limit: int = 5000) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT sha256, source_path FROM documents
                   WHERE status='done' AND (language IS NULL OR language='')
                   ORDER BY id LIMIT ?""",
                (max(1, min(5000, int(limit))),),
            ).fetchall()

    def folder_choices(self) -> list[str]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT source_path FROM documents WHERE status='done' ORDER BY source_path"
            ).fetchall()
        folders: set[str] = set()
        for row in rows:
            parts = str(row["source_path"]).replace("\\", "/").split("/")
            if len(parts) <= 1:
                continue
            current: list[str] = []
            for part in parts[:-1]:
                current.append(part)
                folders.add("/".join(current))
        return sorted(folders, key=lambda value: value.casefold())

    @staticmethod
    def _document_filter_clause(filters: dict | None, *, alias: str = "d") -> tuple[str, list[Any]]:
        if not filters:
            return "", []
        conditions: list[str] = []
        params: list[Any] = []

        language = str(filters.get("language") or "").strip().casefold()
        if language in {"en", "uk", "ru"}:
            conditions.append(f"{alias}.language=?")
            params.append(language)

        domain = str(filters.get("domain") or "").strip()
        if domain:
            conditions.append(
                f"""EXISTS (
                    SELECT 1 FROM classifications cf
                    WHERE cf.document_sha256={alias}.sha256 AND cf.domain=?
                )"""
            )
            params.append(domain)

        prefix = str(filters.get("source_prefix") or "").strip().replace("\\", "/").strip("/")
        if prefix:
            conditions.append(
                f"(REPLACE({alias}.source_path, '\\', '/')=? OR REPLACE({alias}.source_path, '\\', '/') LIKE ?)"
            )
            params.extend([prefix, prefix + "/%"])

        shas = [
            str(value).strip()
            for value in (filters.get("document_sha256s") or [])
            if str(value).strip()
        ]
        if shas:
            placeholders = ",".join("?" for _ in shas)
            conditions.append(f"{alias}.sha256 IN ({placeholders})")
            params.extend(shas)

        date_from_ns = filters.get("date_from_ns")
        if date_from_ns is not None:
            conditions.append(f"{alias}.source_mtime_ns>=?")
            params.append(int(date_from_ns))

        date_to_ns = filters.get("date_to_ns")
        if date_to_ns is not None:
            conditions.append(f"{alias}.source_mtime_ns<?")
            params.append(int(date_to_ns))

        if not conditions:
            return "", []
        return " AND " + " AND ".join(conditions), params


    def begin_taxonomy_run(
        self,
        *,
        started_at: str,
        model: str,
        document_count: int,
        embedding_count: int,
    ) -> int:
        with self._lock:
            cursor = self.conn.execute(
                """INSERT INTO taxonomy_runs
                   (started_at, status, model, document_count, embedding_count)
                   VALUES (?, 'running', ?, ?, ?)""",
                (started_at, model, int(document_count), int(embedding_count)),
            )
            self.conn.commit()
            return int(cursor.lastrowid)

    def fail_taxonomy_run(self, run_id: int, *, finished_at: str, error: str) -> None:
        import json

        with self._lock:
            self.conn.execute(
                """UPDATE taxonomy_runs
                   SET status='failed', finished_at=?, details_json=?
                   WHERE id=?""",
                (
                    finished_at,
                    json.dumps({"error": str(error)}, ensure_ascii=False),
                    int(run_id),
                ),
            )
            self.conn.commit()

    def replace_taxonomy(
        self,
        *,
        run_id: int,
        finished_at: str,
        categories: list[dict[str, Any]],
        topics: list[dict[str, Any]],
        category_assignments: list[tuple[str, str, float]],
        topic_assignments: list[tuple[str, str, float]],
        details_json: str,
    ) -> None:
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute("DELETE FROM document_taxonomy_topics")
                self.conn.execute("DELETE FROM document_taxonomy_categories")
                self.conn.execute("DELETE FROM taxonomy_topics")
                self.conn.execute("DELETE FROM taxonomy_categories")

                self.conn.executemany(
                    """INSERT INTO taxonomy_categories
                       (category_key, name, description, keywords_json, centroid,
                        dimension, document_count, topic_count, source, updated_at, run_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            item["key"],
                            item["name"],
                            item.get("description", ""),
                            item.get("keywords_json", "[]"),
                            item.get("centroid"),
                            int(item.get("dimension") or 0),
                            int(item.get("document_count") or 0),
                            int(item.get("topic_count") or 0),
                            item.get("source", "discovered"),
                            finished_at,
                            int(run_id),
                        )
                        for item in categories
                    ],
                )
                self.conn.executemany(
                    """INSERT INTO taxonomy_topics
                       (topic_key, category_key, name, description, keywords_json,
                        centroid, dimension, document_count, source, updated_at, run_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            item["key"],
                            item.get("category_key"),
                            item["name"],
                            item.get("description", ""),
                            item.get("keywords_json", "[]"),
                            item.get("centroid"),
                            int(item.get("dimension") or 0),
                            int(item.get("document_count") or 0),
                            item.get("source", "discovered"),
                            finished_at,
                            int(run_id),
                        )
                        for item in topics
                    ],
                )
                self.conn.executemany(
                    """INSERT INTO document_taxonomy_categories
                       (document_sha256, category_key, score)
                       VALUES (?, ?, ?)""",
                    [
                        (sha256, key, float(score))
                        for sha256, key, score in category_assignments
                    ],
                )
                self.conn.executemany(
                    """INSERT INTO document_taxonomy_topics
                       (document_sha256, topic_key, score)
                       VALUES (?, ?, ?)""",
                    [
                        (sha256, key, float(score))
                        for sha256, key, score in topic_assignments
                    ],
                )
                self.conn.execute(
                    """UPDATE taxonomy_runs
                       SET status='done', finished_at=?, topic_count=?,
                           category_count=?, details_json=?
                       WHERE id=?""",
                    (
                        finished_at,
                        len(topics),
                        len(categories),
                        details_json,
                        int(run_id),
                    ),
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def latest_taxonomy_run(self):
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM taxonomy_runs
                   WHERE status='done'
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()

    def taxonomy_counts(self) -> dict[str, int]:
        with self._lock:
            categories = int(
                self.conn.execute("SELECT COUNT(*) FROM taxonomy_categories").fetchone()[0]
            )
            topics = int(
                self.conn.execute("SELECT COUNT(*) FROM taxonomy_topics").fetchone()[0]
            )
            assigned = int(
                self.conn.execute(
                    "SELECT COUNT(DISTINCT document_sha256) FROM document_taxonomy_topics"
                ).fetchone()[0]
            )
        return {
            "categories": categories,
            "topics": topics,
            "assigned_documents": assigned,
        }

    def list_taxonomy_categories(self, *, limit: int = 200) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM taxonomy_categories
                   ORDER BY document_count DESC, name
                   LIMIT ?""",
                (max(1, min(1000, int(limit))),),
            ).fetchall()

    def list_taxonomy_topics(
        self,
        *,
        category_key: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        with self._lock:
            if category_key:
                return self.conn.execute(
                    """SELECT * FROM taxonomy_topics
                       WHERE category_key=?
                       ORDER BY document_count DESC, name
                       LIMIT ?""",
                    (category_key, max(1, min(5000, int(limit)))),
                ).fetchall()
            return self.conn.execute(
                """SELECT * FROM taxonomy_topics
                   ORDER BY document_count DESC, name
                   LIMIT ?""",
                (max(1, min(5000, int(limit))),),
            ).fetchall()

    def taxonomy_for_document(self, sha256: str) -> dict[str, list[sqlite3.Row]]:
        with self._lock:
            categories = self.conn.execute(
                """SELECT c.*, dc.score
                   FROM document_taxonomy_categories dc
                   JOIN taxonomy_categories c ON c.category_key=dc.category_key
                   WHERE dc.document_sha256=?
                   ORDER BY dc.score DESC, c.name""",
                (sha256,),
            ).fetchall()
            topics = self.conn.execute(
                """SELECT t.*, dt.score
                   FROM document_taxonomy_topics dt
                   JOIN taxonomy_topics t ON t.topic_key=dt.topic_key
                   WHERE dt.document_sha256=?
                   ORDER BY dt.score DESC, t.name""",
                (sha256,),
            ).fetchall()
        return {"categories": categories, "topics": topics}

    def taxonomy_documents(
        self,
        *,
        category_key: str | None = None,
        topic_key: str | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        limit = max(1, min(5000, int(limit)))
        with self._lock:
            if topic_key:
                return self.conn.execute(
                    """SELECT d.*, dt.score AS taxonomy_score
                       FROM document_taxonomy_topics dt
                       JOIN documents d ON d.sha256=dt.document_sha256
                       WHERE dt.topic_key=? AND d.status='done'
                       ORDER BY dt.score DESC, d.source_path
                       LIMIT ?""",
                    (topic_key, limit),
                ).fetchall()
            if category_key:
                return self.conn.execute(
                    """SELECT d.*, dc.score AS taxonomy_score
                       FROM document_taxonomy_categories dc
                       JOIN documents d ON d.sha256=dc.document_sha256
                       WHERE dc.category_key=? AND d.status='done'
                       ORDER BY dc.score DESC, d.source_path
                       LIMIT ?""",
                    (category_key, limit),
                ).fetchall()
            return []

    def recent_errors(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                """SELECT source_path, error, processed_at FROM documents
                   WHERE status='error' AND error IS NOT NULL
                   ORDER BY id DESC LIMIT ?""",
                (max(1, min(100, int(limit))),),
            ).fetchall()
        return [
            {
                "source_path": row["source_path"],
                "error": row["error"],
                "processed_at": row["processed_at"],
            }
            for row in rows
        ]

    def save_translation(self, *, sha256: str, source_lang: str, target_lang: str, output_path: str, created_at: str, engine: str) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO translations(document_sha256, source_lang, target_lang, output_path, created_at, engine)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(document_sha256, source_lang, target_lang) DO UPDATE SET
                     output_path=excluded.output_path, created_at=excluded.created_at, engine=excluded.engine""",
                (sha256, source_lang, target_lang, output_path, created_at, engine),
            )
            self.conn.commit()

    def translation_document_count(self, *, target_lang: str = "ru") -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(DISTINCT document_sha256) AS n FROM translations WHERE target_lang=?",
                (target_lang,),
            ).fetchone()
        return int(row["n"])

    def error_count(self) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM documents WHERE status='error'"
            ).fetchone()
        return int(row["n"])

    def list_translations(self, sha256: str) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM translations WHERE document_sha256=? ORDER BY created_at DESC", (sha256,)
            ).fetchall()

    def get_translation(self, sha256: str, source_lang: str, target_lang: str):
        with self._lock:
            return self.conn.execute(
                """SELECT * FROM translations
                   WHERE document_sha256=? AND source_lang=? AND target_lang=?""",
                (sha256, source_lang, target_lang),
            ).fetchone()

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
            "translations_ru": self.translation_document_count(target_lang="ru"),
            "errors": self.error_count(),
        }
