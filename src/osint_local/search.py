from __future__ import annotations

import math
import re
from array import array
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .db import Database

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class SentenceTransformerEncoder:
    def __init__(self, model_name_or_path: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Semantic search requires the optional search dependencies. "
                "Install them with: pip install -e '.[search]'"
            ) from exc
        self.model = SentenceTransformer(model_name_or_path)

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return self.model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )


@dataclass(frozen=True)
class SearchHit:
    score: float
    backend: str
    document_sha256: str
    source_path: str
    page: int | None
    chunk_index: int
    text: str


def build_embeddings(
    db: Database,
    config: dict,
    *,
    force: bool = False,
    encoder: Encoder | None = None,
    document_sha256: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    model = str(config.get("model") or DEFAULT_MODEL)
    rows = db.chunks_for_embedding(model, force=force, document_sha256=document_sha256)
    if not rows:
        return 0

    encoder = encoder or SentenceTransformerEncoder(model)
    batch_size = max(1, int(config.get("batch_size", 32)))
    written = 0
    if progress:
        progress(0, len(rows))
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        vectors = encoder.encode([row["text"] for row in batch])
        if len(vectors) != len(batch):
            raise RuntimeError("Embedding encoder returned an unexpected number of vectors")
        payload = []
        for row, vector in zip(batch, vectors):
            normalized = _normalize_vector(vector)
            payload.append((row["id"], model, len(normalized), _vector_to_blob(normalized)))
        db.save_embeddings(payload)
        written += len(payload)
        if progress:
            progress(written, len(rows))
    return written


def search_chunks(
    db: Database,
    query: str,
    config: dict,
    *,
    limit: int = 10,
    mode: str = "auto",
    encoder: Encoder | None = None,
) -> list[SearchHit]:
    query = query.strip()
    if not query:
        return []
    limit = max(1, limit)
    model = str(config.get("model") or DEFAULT_MODEL)
    semantic_enabled = bool(config.get("semantic_enabled", True))

    if mode not in {"auto", "hybrid", "semantic", "lexical"}:
        raise ValueError(f"Unknown search mode: {mode}")

    embedded = db.embedding_count(model)
    total_chunks = db.chunk_count()
    semantic_ready = total_chunks > 0 and embedded >= total_chunks

    if mode in {"auto", "hybrid"} and semantic_enabled and semantic_ready:
        try:
            candidate_multiplier = max(2, min(8, int(config.get("hybrid_candidate_multiplier", 3))))
            candidate_limit = max(limit * candidate_multiplier, min(30, total_chunks))
            semantic_hits = _semantic_search(
                db, query, model, candidate_limit, encoder=encoder
            )
            lexical_hits = _lexical_search(db, query, candidate_limit)
            return _hybrid_rerank(query, semantic_hits, lexical_hits, limit, config)
        except RuntimeError:
            if mode == "hybrid":
                raise

    if mode == "semantic" and semantic_enabled and semantic_ready:
        return _semantic_search(db, query, model, limit, encoder=encoder)

    if mode in {"semantic", "hybrid"}:
        if not semantic_enabled:
            detail = "Semantic search is disabled."
        elif embedded == 0:
            detail = "No semantic embeddings are indexed for the configured model."
        else:
            detail = f"Semantic index is incomplete ({embedded}/{total_chunks} chunks embedded)."
        raise RuntimeError(detail + " Run: osint-local index")

    return _lexical_search(db, query, limit)


def _semantic_search(
    db: Database,
    query: str,
    model: str,
    limit: int,
    *,
    encoder: Encoder | None = None,
) -> list[SearchHit]:
    encoder = encoder or SentenceTransformerEncoder(model)
    query_vector = _normalize_vector(encoder.encode([query])[0])
    scored: list[SearchHit] = []
    for row in db.iter_embeddings(model):
        vector = _blob_to_vector(row["vector"])
        score = _dot(query_vector, vector)
        scored.append(_hit(row, score, "semantic"))
    return sorted(scored, key=lambda hit: hit.score, reverse=True)[:limit]


def _lexical_search(db: Database, query: str, limit: int) -> list[SearchHit]:
    terms = _terms(query)
    if not terms:
        return []
    hits: list[SearchHit] = []
    for row in db.iter_chunks():
        lowered = row["text"].casefold()
        matched = 0
        frequency = 0
        for term in terms:
            count = lowered.count(term)
            if count:
                matched += 1
                frequency += count
        if not matched:
            continue
        coverage = matched / len(terms)
        density = frequency / max(1.0, math.sqrt(len(lowered)))
        score = coverage + min(0.5, density)
        hits.append(_hit(row, score, "lexical"))
    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]


def _hybrid_rerank(
    query: str,
    semantic_hits: list[SearchHit],
    lexical_hits: list[SearchHit],
    limit: int,
    config: dict,
) -> list[SearchHit]:
    """Fuse semantic and lexical rankings, then apply a cheap exact-match rerank."""
    rrf_k = max(10, min(200, int(config.get("hybrid_rrf_k", 60))))
    semantic_weight = max(0.0, float(config.get("hybrid_semantic_weight", 1.0)))
    lexical_weight = max(0.0, float(config.get("hybrid_lexical_weight", 1.0)))
    terms = _terms(query)
    phrase = query.casefold().strip()

    scores: dict[tuple[str, int | None, int], float] = {}
    hits: dict[tuple[str, int | None, int], SearchHit] = {}

    for rank, hit in enumerate(semantic_hits, 1):
        key = _hit_key(hit)
        hits[key] = hit
        scores[key] = scores.get(key, 0.0) + semantic_weight / (rrf_k + rank)

    for rank, hit in enumerate(lexical_hits, 1):
        key = _hit_key(hit)
        hits[key] = hit
        scores[key] = scores.get(key, 0.0) + lexical_weight / (rrf_k + rank)

    for key, hit in hits.items():
        lowered = hit.text.casefold()
        if terms:
            coverage = sum(1 for term in terms if term in lowered) / len(terms)
            scores[key] += 0.01 * coverage
        if len(phrase) >= 4 and phrase in lowered:
            scores[key] += 0.012

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return []

    top_score = ranked[0][1] or 1.0
    output: list[SearchHit] = []
    for key, raw_score in ranked[:limit]:
        hit = hits[key]
        output.append(
            SearchHit(
                score=float(raw_score / top_score),
                backend="hybrid",
                document_sha256=hit.document_sha256,
                source_path=hit.source_path,
                page=hit.page,
                chunk_index=hit.chunk_index,
                text=hit.text,
            )
        )
    return output


def _hit_key(hit: SearchHit) -> tuple[str, int | None, int]:
    return (hit.document_sha256, hit.page, hit.chunk_index)


def _terms(text: str) -> list[str]:
    return list(dict.fromkeys(token.casefold() for token in re.findall(r"[\w-]{2,}", text, flags=re.UNICODE)))


def _hit(row, score: float, backend: str) -> SearchHit:
    return SearchHit(
        score=float(score),
        backend=backend,
        document_sha256=row["document_sha256"],
        source_path=row["source_path"],
        page=row["page"],
        chunk_index=row["chunk_index"],
        text=row["text"],
    )


def _normalize_vector(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        return values
    return [value / norm for value in values]


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
