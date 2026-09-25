from __future__ import annotations

import hashlib
import json
import math
import re
from array import array
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from .qa import _ollama_chat


STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "are", "was",
    "were", "has", "have", "had", "not", "but", "its", "their", "about", "document",
    "page", "pages", "section", "table", "figure", "report", "information",
    "для", "это", "как", "что", "или", "при", "его", "она", "они", "также", "был",
    "была", "были", "есть", "данных", "документ", "страница", "раздел", "таблица",
    "информация", "который", "которая", "которые", "этот",
    "це", "як", "що", "або", "його", "вони", "також", "було", "були", "даних",
    "сторінка", "розділ", "інформація", "який", "яка", "які", "цей", "цієї", "та",
}

TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ][\\w'’-]{2,}", re.UNICODE)


def taxonomy_available(db, search_config: dict) -> bool:
    model = str(search_config.get("model") or "")
    return bool(model and db.embedding_count(model) > 0)


def taxonomy_is_stale(db, search_config: dict) -> bool:
    model = str(search_config.get("model") or "")
    latest = db.latest_taxonomy_run()
    if not latest:
        return True
    return (
        str(latest["model"] or "") != model
        or int(latest["document_count"] or 0) != db.document_count()
        or int(latest["embedding_count"] or 0) != db.embedding_count(model)
    )


def build_adaptive_taxonomy(
    db,
    search_config: dict,
    taxonomy_config: dict,
    qa_config: dict,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    labeler: Callable[[str, list[dict[str, Any]]], dict[str, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    model = str(search_config.get("model") or "").strip()
    if not model:
        raise RuntimeError("Semantic embedding model is not configured")

    document_count = db.document_count()
    embedding_count = db.embedding_count(model)
    min_documents = max(2, int(taxonomy_config.get("min_documents", 8) or 8))
    if document_count < min_documents:
        raise RuntimeError(
            f"Adaptive taxonomy needs at least {min_documents} processed documents"
        )
    if embedding_count <= 0:
        raise RuntimeError("Adaptive taxonomy requires a semantic index")

    started_at = _now()
    run_id = db.begin_taxonomy_run(
        started_at=started_at,
        model=model,
        document_count=document_count,
        embedding_count=embedding_count,
    )
    try:
        if progress:
            progress(0, 6, "Building document semantic vectors…")
        documents = _document_vectors(db, model)
        if len(documents) < min_documents:
            raise RuntimeError(
                f"Only {len(documents)} documents have semantic embeddings; "
                f"{min_documents} are required"
            )

        topic_threshold = float(taxonomy_config.get("topic_similarity", 0.64))
        topic_merge = float(taxonomy_config.get("topic_merge_similarity", 0.82))
        min_topic_docs = max(2, int(taxonomy_config.get("min_topic_documents", 2) or 2))
        max_topics = max(4, int(taxonomy_config.get("max_topics", 80) or 80))

        if progress:
            progress(1, 6, "Discovering semantic topics…")
        raw_topics = _cluster_items(
            documents,
            similarity_threshold=topic_threshold,
            merge_threshold=topic_merge,
            max_clusters=max_topics,
        )
        topic_clusters = [
            cluster for cluster in raw_topics
            if len(cluster["members"]) >= min_topic_docs
        ]
        if not topic_clusters:
            topic_clusters = sorted(
                raw_topics,
                key=lambda item: len(item["members"]),
                reverse=True,
            )[: min(max_topics, max(1, len(raw_topics)))]

        if progress:
            progress(2, 6, "Naming discovered topics…")
        topic_records = _materialize_topics(
            topic_clusters,
            documents,
            taxonomy_config,
            qa_config,
            labeler=labeler,
        )

        if progress:
            progress(3, 6, "Grouping topics into broader categories…")
        category_threshold = float(taxonomy_config.get("category_similarity", 0.48))
        category_merge = float(taxonomy_config.get("category_merge_similarity", 0.70))
        max_categories = max(2, int(taxonomy_config.get("max_categories", 24) or 24))
        category_items = [
            {
                "id": topic["key"],
                "vector": topic["vector"],
                "weight": max(1, int(topic["document_count"])),
                "text": " ".join(topic["keywords"]),
                "source_path": topic["name"],
            }
            for topic in topic_records
        ]
        raw_categories = _cluster_items(
            category_items,
            similarity_threshold=category_threshold,
            merge_threshold=category_merge,
            max_clusters=max_categories,
            weighted=True,
        )
        category_records = _materialize_categories(
            raw_categories,
            topic_records,
            taxonomy_config,
            qa_config,
            labeler=labeler,
        )

        category_by_topic: dict[str, str] = {}
        category_lookup = {item["key"]: item for item in category_records}
        for category in category_records:
            for topic_key in category["topic_keys"]:
                category_by_topic[topic_key] = category["key"]
        for topic in topic_records:
            topic["category_key"] = category_by_topic.get(topic["key"])

        if progress:
            progress(4, 6, "Assigning documents to topics and categories…")
        topic_assignments: list[tuple[str, str, float]] = []
        category_scores: dict[tuple[str, str], float] = {}
        assigned_documents: set[str] = set()
        for topic in topic_records:
            for member in topic["cluster"]["members"]:
                sha256 = str(member["id"])
                score = max(0.0, _dot(member["vector"], topic["vector"]))
                topic_assignments.append((sha256, topic["key"], score))
                assigned_documents.add(sha256)
                category_key = topic.get("category_key")
                if category_key:
                    category = category_lookup[category_key]
                    category_score = max(
                        0.0,
                        _dot(member["vector"], category["vector"]),
                    )
                    key = (sha256, category_key)
                    category_scores[key] = max(
                        category_scores.get(key, 0.0),
                        category_score,
                    )

        category_assignments = [
            (sha256, category_key, score)
            for (sha256, category_key), score in sorted(category_scores.items())
        ]

        if progress:
            progress(5, 6, "Saving adaptive taxonomy…")
        finished_at = _now()
        category_payload = [
            {
                "key": item["key"],
                "name": item["name"],
                "description": item["description"],
                "keywords_json": json.dumps(item["keywords"], ensure_ascii=False),
                "centroid": _vector_to_blob(item["vector"]),
                "dimension": len(item["vector"]),
                "document_count": item["document_count"],
                "topic_count": len(item["topic_keys"]),
                "source": "discovered",
            }
            for item in category_records
        ]
        topic_payload = [
            {
                "key": item["key"],
                "category_key": item.get("category_key"),
                "name": item["name"],
                "description": item["description"],
                "keywords_json": json.dumps(item["keywords"], ensure_ascii=False),
                "centroid": _vector_to_blob(item["vector"]),
                "dimension": len(item["vector"]),
                "document_count": item["document_count"],
                "source": "discovered",
            }
            for item in topic_records
        ]
        details = {
            "documents_with_vectors": len(documents),
            "assigned_documents": len(assigned_documents),
            "unassigned_documents": max(0, len(documents) - len(assigned_documents)),
            "coverage": round(len(assigned_documents) / max(1, len(documents)), 4),
            "topic_similarity": topic_threshold,
            "topic_merge_similarity": topic_merge,
            "category_similarity": category_threshold,
            "category_merge_similarity": category_merge,
            "min_topic_documents": min_topic_docs,
        }
        db.replace_taxonomy(
            run_id=run_id,
            finished_at=finished_at,
            categories=category_payload,
            topics=topic_payload,
            category_assignments=category_assignments,
            topic_assignments=topic_assignments,
            details_json=json.dumps(details, ensure_ascii=False),
        )
        if progress:
            progress(6, 6, "Adaptive taxonomy ready")
        return {
            "run_id": run_id,
            "model": model,
            "documents": len(documents),
            "assigned_documents": len(assigned_documents),
            "categories": len(category_records),
            "topics": len(topic_records),
            **details,
        }
    except Exception as exc:
        db.fail_taxonomy_run(run_id, finished_at=_now(), error=str(exc))
        raise


def _document_vectors(db, model: str) -> list[dict[str, Any]]:
    grouped_vectors: dict[str, list[list[float]]] = defaultdict(list)
    grouped_text: dict[str, list[str]] = defaultdict(list)
    paths: dict[str, str] = {}

    for row in db.iter_embeddings(model):
        sha256 = str(row["document_sha256"])
        grouped_vectors[sha256].append(_blob_to_vector(row["vector"]))
        if len(grouped_text[sha256]) < 5:
            text = str(row["text"] or "").strip()
            if text:
                grouped_text[sha256].append(text[:1200])
        paths[sha256] = str(row["source_path"] or "")

    documents: list[dict[str, Any]] = []
    for sha256 in sorted(grouped_vectors):
        vectors = grouped_vectors[sha256]
        if not vectors:
            continue
        dimension = len(vectors[0])
        if not dimension or any(len(vector) != dimension for vector in vectors):
            continue
        centroid = _normalize(
            [
                sum(vector[index] for vector in vectors) / len(vectors)
                for index in range(dimension)
            ]
        )
        documents.append(
            {
                "id": sha256,
                "vector": centroid,
                "weight": 1,
                "source_path": paths.get(sha256, ""),
                "text": "\n".join(grouped_text.get(sha256, [])),
            }
        )
    return documents


def _cluster_items(
    items: list[dict[str, Any]],
    *,
    similarity_threshold: float,
    merge_threshold: float,
    max_clusters: int,
    weighted: bool = False,
) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: str(value["id"])):
        best_index = -1
        best_score = -1.0
        for index, cluster in enumerate(clusters):
            score = _dot(item["vector"], cluster["vector"])
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0 and (
            best_score >= similarity_threshold
            or len(clusters) >= max_clusters
        ):
            clusters[best_index]["members"].append(item)
            _refresh_cluster(clusters[best_index], weighted=weighted)
        else:
            clusters.append({"members": [item], "vector": list(item["vector"])})

    while len(clusters) > 1:
        best_pair: tuple[int, int] | None = None
        best_score = merge_threshold
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                score = _dot(clusters[left]["vector"], clusters[right]["vector"])
                if score >= best_score:
                    best_score = score
                    best_pair = (left, right)
        if best_pair is None:
            break
        left, right = best_pair
        clusters[left]["members"].extend(clusters[right]["members"])
        _refresh_cluster(clusters[left], weighted=weighted)
        del clusters[right]

    return sorted(
        clusters,
        key=lambda cluster: (
            -len(cluster["members"]),
            str(cluster["members"][0]["id"]),
        ),
    )


def _refresh_cluster(cluster: dict[str, Any], *, weighted: bool) -> None:
    members = cluster["members"]
    dimension = len(members[0]["vector"])
    total_weight = sum(
        max(1, int(member.get("weight", 1))) if weighted else 1
        for member in members
    )
    values = [0.0] * dimension
    for member in members:
        weight = max(1, int(member.get("weight", 1))) if weighted else 1
        for index, value in enumerate(member["vector"]):
            values[index] += float(value) * weight
    cluster["vector"] = _normalize(
        [value / max(1, total_weight) for value in values]
    )


def _materialize_topics(
    clusters: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    taxonomy_config: dict,
    qa_config: dict,
    *,
    labeler=None,
) -> list[dict[str, Any]]:
    document_by_id = {str(item["id"]): item for item in documents}
    candidates: list[dict[str, Any]] = []
    for cluster in clusters:
        member_ids = sorted(str(item["id"]) for item in cluster["members"])
        key = "topic-" + hashlib.sha1("\n".join(member_ids).encode("utf-8")).hexdigest()[:12]
        representatives = sorted(
            cluster["members"],
            key=lambda item: _dot(item["vector"], cluster["vector"]),
            reverse=True,
        )[:3]
        texts = [
            document_by_id[str(item["id"])]["text"]
            for item in representatives
            if document_by_id[str(item["id"])]["text"]
        ]
        keywords = _keywords(texts)
        candidates.append(
            {
                "key": key,
                "name": _fallback_name(keywords, "Discovered Topic"),
                "description": _fallback_description("topic", len(member_ids), keywords),
                "keywords": keywords,
                "vector": list(cluster["vector"]),
                "document_count": len(member_ids),
                "representatives": [
                    str(item.get("source_path") or item["id"])
                    for item in representatives
                ],
                "snippets": [text[:600] for text in texts[:3]],
                "cluster": cluster,
            }
        )

    labels = _labels(
        "topic",
        candidates,
        taxonomy_config,
        qa_config,
        labeler=labeler,
    )
    _apply_labels(candidates, labels)
    return candidates


def _materialize_categories(
    clusters: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    taxonomy_config: dict,
    qa_config: dict,
    *,
    labeler=None,
) -> list[dict[str, Any]]:
    topic_by_key = {topic["key"]: topic for topic in topics}
    candidates: list[dict[str, Any]] = []
    for cluster in clusters:
        topic_keys = sorted(str(item["id"]) for item in cluster["members"])
        key = "category-" + hashlib.sha1("\n".join(topic_keys).encode("utf-8")).hexdigest()[:12]
        member_topics = [topic_by_key[item] for item in topic_keys]
        keywords = _keywords(
            [
                " ".join(topic["keywords"]) + " " + topic["name"]
                for topic in member_topics
            ]
        )
        documents = {
            str(member["id"])
            for topic in member_topics
            for member in topic["cluster"]["members"]
        }
        candidates.append(
            {
                "key": key,
                "name": _fallback_name(keywords, "Discovered Category"),
                "description": _fallback_description("category", len(documents), keywords),
                "keywords": keywords,
                "vector": list(cluster["vector"]),
                "document_count": len(documents),
                "topic_keys": topic_keys,
                "representatives": [topic["name"] for topic in member_topics[:6]],
                "snippets": [topic["description"][:400] for topic in member_topics[:6]],
            }
        )

    labels = _labels(
        "category",
        candidates,
        taxonomy_config,
        qa_config,
        labeler=labeler,
    )
    _apply_labels(candidates, labels)
    return candidates


def _labels(
    kind: str,
    candidates: list[dict[str, Any]],
    taxonomy_config: dict,
    qa_config: dict,
    *,
    labeler=None,
) -> dict[str, dict[str, str]]:
    if not candidates:
        return {}
    if labeler is not None:
        try:
            return labeler(kind, candidates) or {}
        except Exception:
            return {}
    if not bool(taxonomy_config.get("label_with_ollama", True)):
        return {}
    try:
        return _ollama_labels(kind, candidates, taxonomy_config, qa_config)
    except Exception:
        return {}


def _ollama_labels(
    kind: str,
    candidates: list[dict[str, Any]],
    taxonomy_config: dict,
    qa_config: dict,
) -> dict[str, dict[str, str]]:
    base_url = str(qa_config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    model = str(qa_config.get("model") or "").strip()
    if not model:
        return {}

    max_labels = max(1, int(taxonomy_config.get("max_llm_labels", 60) or 60))
    batch_size = max(1, min(12, int(taxonomy_config.get("label_batch_size", 8) or 8)))
    language = str(taxonomy_config.get("label_language") or "en").strip().casefold()
    output: dict[str, dict[str, str]] = {}

    selected = candidates[:max_labels]
    for offset in range(0, len(selected), batch_size):
        batch = selected[offset:offset + batch_size]
        payload = [
            {
                "id": item["key"],
                "keywords": item["keywords"][:8],
                "representatives": item.get("representatives", [])[:4],
                "snippets": item.get("snippets", [])[:3],
                "documents": item.get("document_count", 0),
            }
            for item in batch
        ]
        level = "broad category" if kind == "category" else "specific topic"
        system = (
            "You label clusters in a local document corpus. Return ONLY a valid JSON array. "
            "Each object must contain id, name, description. Keep names concise, neutral, "
            f"non-duplicative, and suitable as a {level}. "
            f"Use {'Russian' if language == 'ru' else 'English'} names and descriptions. "
            "Do not add facts that are not supported by the supplied keywords/snippets."
        )
        response = _ollama_chat(
            base_url,
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            {**qa_config, "think": False, "keep_alive": qa_config.get("keep_alive", 0)},
        )
        values = _parse_json_array(response)
        allowed = {item["key"] for item in batch}
        for value in values:
            key = str(value.get("id") or "")
            if key not in allowed:
                continue
            name = _clean_label(value.get("name"), 80)
            description = _clean_label(value.get("description"), 280)
            if name:
                output[key] = {"name": name, "description": description}
    return output


def _parse_json_array(value: str) -> list[dict[str, Any]]:
    value = str(value or "").strip()
    start = value.find("[")
    end = value.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(value[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _apply_labels(
    candidates: list[dict[str, Any]],
    labels: dict[str, dict[str, str]],
) -> None:
    used: Counter[str] = Counter()
    for item in candidates:
        label = labels.get(item["key"]) or {}
        name = _clean_label(label.get("name"), 80) or item["name"]
        description = _clean_label(label.get("description"), 280) or item["description"]
        normalized = name.casefold()
        used[normalized] += 1
        if used[normalized] > 1:
            name = f"{name} {used[normalized]}"
        item["name"] = name
        item["description"] = description


def _keywords(texts: Sequence[str], limit: int = 10) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        seen: set[str] = set()
        for token in TOKEN_RE.findall(str(text or "")):
            value = token.casefold().strip("'’-")
            if len(value) < 3 or value in STOPWORDS or value.isdigit():
                continue
            counter[value] += 1 if value in seen else 2
            seen.add(value)
    return [token for token, _ in counter.most_common(max(1, int(limit)))]


def _fallback_name(keywords: Sequence[str], default: str) -> str:
    values = [str(value).strip() for value in keywords[:3] if str(value).strip()]
    if not values:
        return default
    return " · ".join(value[:1].upper() + value[1:] for value in values)


def _fallback_description(kind: str, document_count: int, keywords: Sequence[str]) -> str:
    keyword_text = ", ".join(keywords[:8]) if keywords else "no stable keywords"
    return (
        f"Automatically discovered {kind} across {document_count} document(s). "
        f"Representative keywords: {keyword_text}."
    )


def _clean_label(value: Any, limit: int) -> str:
    text = re.sub(r"\\s+", " ", str(value or "")).strip(" -–—:;")
    return text[:limit].strip()


def _blob_to_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def _vector_to_blob(vector: Sequence[float]) -> bytes:
    return array("f", [float(value) for value in vector]).tobytes()


def _normalize(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        return values
    return [value / norm for value in values]


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        return -1.0
    return sum(float(a) * float(b) for a, b in zip(left, right))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
