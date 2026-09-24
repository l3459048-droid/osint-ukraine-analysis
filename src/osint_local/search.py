from __future__ import annotations

import math
import re
from array import array
from dataclasses import dataclass
from typing import Protocol, Sequence

from .chunking import split_pages as _split_pages
from .config import Settings
from .search_db import SearchDatabase

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class SentenceTransformerEncoder:
    def __init__(self, model_name_or_path: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Semantic search requires optional dependencies. "
                "Install them with: pip install -e '.[search]'"
            ) from exc
        self.model = SentenceTransformer(model_name_or_path)

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return self.model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)


@dataclass(frozen=True)
class SearchHit:
    score: float
    backend: str
    document_sha256: str
    source_path: str
    page: int | None
    chunk_index: int
    text: str


class SearchIndex:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = SearchDatabase(settings)

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def sync_chunks(self, force: bool = False) -> dict[str, int]:
        return self.db.sync_chunks(force=force)

    def build_embeddings(self, force: bool = False, encoder: Encoder | None = None) -> int:
        self.sync_chunks()
        model = str(self.settings.search.get("model") or DEFAULT_MODEL)
        rows = self.db.missing_embedding_rows(model, force)
        if not rows:
            return 0
        encoder = encoder or SentenceTransformerEncoder(model)
        batch_size = max(1, int(self.settings.search.get("batch_size", 32)))
        written = 0
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset:offset + batch_size]
            vectors = encoder.encode([row["text"] for row in batch])
            if len(vectors) != len(batch):
                raise RuntimeError("Embedding encoder returned an unexpected number of vectors")
            payload = []
            for row, vector in zip(batch, vectors):
                normalized = _normalize_vector(vector)
                payload.append((row["id"], len(normalized), _vector_to_blob(normalized)))
            self.db.store_embeddings(model, payload)
            written += len(payload)
        return written

    def search(self, query: str, limit: int = 10, mode: str = "auto", encoder: Encoder | None = None) -> list[SearchHit]:
        self.sync_chunks()
        query = query.strip()
        if not query:
            return []
        if mode not in {"auto", "semantic", "lexical"}:
            raise ValueError(f"Unknown search mode: {mode}")
        model = str(self.settings.search.get("model") or DEFAULT_MODEL)
        chunks = self.db.chunk_count()
        embeddings = self.db.embedding_count(model)
        semantic_ready = chunks > 0 and embeddings == chunks
        if mode in {"auto", "semantic"} and bool(self.settings.search.get("semantic_enabled", True)):
            if semantic_ready:
                try:
                    return self._semantic_search(query, limit, model, encoder)
                except RuntimeError:
                    if mode == "semantic":
                        raise
            elif mode == "semantic":
                raise RuntimeError(
                    f"Semantic index is incomplete ({embeddings}/{chunks} chunks). Run: osint-local index"
                )
        return self._lexical_search(query, limit)

    def stats(self) -> dict:
        model = str(self.settings.search.get("model") or DEFAULT_MODEL)
        return self.db.stats(model)

    def _semantic_search(self, query: str, limit: int, model: str, encoder: Encoder | None) -> list[SearchHit]:
        encoder = encoder or SentenceTransformerEncoder(model)
        query_vector = _normalize_vector(encoder.encode([query])[0])
        hits = [_hit(row, _dot(query_vector, _blob_to_vector(row["vector"])), "semantic") for row in self.db.semantic_rows(model)]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:max(1, limit)]

    def _lexical_search(self, query: str, limit: int) -> list[SearchHit]:
        terms = _terms(query)
        if not terms:
            return []
        hits: list[SearchHit] = []
        for row in self.db.lexical_rows():
            lowered = row["text"].casefold()
            counts = [lowered.count(term) for term in terms]
            matched = sum(bool(count) for count in counts)
            if not matched:
                continue
            coverage = matched / len(terms)
            density = sum(counts) / max(1.0, math.sqrt(len(lowered)))
            hits.append(_hit(row, coverage + min(0.5, density), "lexical"))
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:max(1, limit)]


def _terms(text: str) -> list[str]:
    return list(dict.fromkeys(token.casefold() for token in re.findall(r"[\w-]{2,}", text, flags=re.UNICODE)))


def _hit(row, score: float, backend: str) -> SearchHit:
    return SearchHit(float(score), backend, row["document_sha256"], row["source_path"], row["page"], row["chunk_index"], row["text"])


def _normalize_vector(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    return values if not norm else [value / norm for value in values]


def _vector_to_blob(vector: Sequence[float]) -> bytes:
    return array("f", vector).tobytes()


def _blob_to_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return -1.0
    return sum(a * b for a, b in zip(left, right))
