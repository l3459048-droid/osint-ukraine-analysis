from __future__ import annotations

import hashlib
import json
import math
import re
import time
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

TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ][\w'’-]{2,}", re.UNICODE)


def _wait_while_paused(
    should_pause: Callable[[], bool] | None,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    if should_pause is None:
        return
    announced = False
    while should_pause():
        if progress is not None and not announced:
            progress(0, 0, "Taxonomy paused for Chat/Ask…")
            announced = True
        time.sleep(0.2)


def taxonomy_available(db, search_config: dict) -> bool:
    model = str(search_config.get("model") or "")
    return bool(model and db.embedding_count(model) > 0)


def taxonomy_is_stale(db, search_config: dict) -> bool:
    model = str(search_config.get("model") or "")
    latest = db.latest_taxonomy_run()
    if not latest:
        return True
    try:
        details = json.loads(str(latest["details_json"] or "{}"))
    except (TypeError, json.JSONDecodeError):
        details = {}
    return (
        str(latest["model"] or "") != model
        or int(latest["document_count"] or 0) != db.document_count()
        or int(latest["embedding_count"] or 0) != db.embedding_count(model)
        or str(details.get("embedding_signature") or "")
            != db.embedding_signature(model)
    )


def build_adaptive_taxonomy(
    db,
    search_config: dict,
    taxonomy_config: dict,
    qa_config: dict,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
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
        documents = _document_vectors(
            db,
            model,
            should_pause=should_pause,
            progress=progress,
        )
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
        _wait_while_paused(should_pause, progress)
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
        previous_topics = db.list_taxonomy_topics(limit=5000)
        topic_overrides = db.list_taxonomy_label_overrides(
            kind="topic",
            limit=5000,
        )
        topic_records = _materialize_topics(
            topic_clusters,
            documents,
            taxonomy_config,
            qa_config,
            previous=previous_topics,
            overrides=topic_overrides,
            labeler=labeler,
            should_pause=should_pause,
            progress=progress,
        )

        if progress:
            progress(3, 6, "Grouping topics into broader categories…")
        _wait_while_paused(should_pause, progress)
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
        previous_categories = db.list_taxonomy_categories(limit=1000)
        category_overrides = db.list_taxonomy_label_overrides(
            kind="category",
            limit=1000,
        )
        category_records = _materialize_categories(
            raw_categories,
            topic_records,
            taxonomy_config,
            qa_config,
            previous=previous_categories,
            overrides=category_overrides,
            labeler=labeler,
            should_pause=should_pause,
            progress=progress,
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
        _wait_while_paused(should_pause, progress)
        primary_topic: dict[str, str] = {}
        for topic in topic_records:
            for member in topic["cluster"]["members"]:
                primary_topic[str(member["id"])] = topic["key"]

        assignments = _assign_documents_to_taxonomy(
            documents,
            topic_records,
            category_records,
            taxonomy_config,
            primary_topic=primary_topic,
        )
        topic_assignments = assignments["topic_assignments"]
        category_assignments = assignments["category_assignments"]
        assigned_documents = assignments["assigned_documents"]
        topic_document_counts = assignments["topic_document_counts"]
        category_document_counts = assignments["category_document_counts"]
        assignment_threshold = assignments["assignment_threshold"]
        max_topics_per_document = assignments["max_topics_per_document"]

        for topic in topic_records:
            topic["document_count"] = topic_document_counts.get(topic["key"], 0)
        for category in category_records:
            category["document_count"] = category_document_counts.get(
                category["key"],
                0,
            )

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
                "source": item.get("label_source", "discovered"),
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
                "source": item.get("label_source", "discovered"),
            }
            for item in topic_records
        ]
        growth_trigger, unassigned_trigger = _discovery_thresholds(
            document_count=len(documents),
            discovery_document_count=len(documents),
            taxonomy_config=taxonomy_config,
        )
        details = {
            "embedding_signature": db.embedding_signature(model),
            "discovery_embedding_signature": db.embedding_signature(model),
            "discovery_document_count": len(documents),
            "last_refresh_mode": "full",
            "last_full_rebuild_at": finished_at,
            "incremental_refreshes_since_discovery": 0,
            "incremental_refresh_limit": max(
                1,
                int(
                    taxonomy_config.get(
                        "full_rebuild_after_incremental_refreshes",
                        20,
                    )
                    or 20
                ),
            ),
            "growth_trigger": growth_trigger,
            "unassigned_trigger": unassigned_trigger,
            "documents_with_vectors": len(documents),
            "assigned_documents": len(assigned_documents),
            "unassigned_documents": max(0, len(documents) - len(assigned_documents)),
            "coverage": round(len(assigned_documents) / max(1, len(documents)), 4),
            "topic_similarity": topic_threshold,
            "topic_merge_similarity": topic_merge,
            "category_similarity": category_threshold,
            "category_merge_similarity": category_merge,
            "min_topic_documents": min_topic_docs,
            "topic_assignment_similarity": assignment_threshold,
            "max_topics_per_document": max_topics_per_document,
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
        for item in topic_records:
            old_key = str(item.get("manual_override_source_key") or "")
            if old_key:
                db.rekey_taxonomy_label_override(
                    kind="topic",
                    old_key=old_key,
                    new_key=item["key"],
                    centroid=_vector_to_blob(item["vector"]),
                    dimension=len(item["vector"]),
                    updated_at=finished_at,
                )
        for item in category_records:
            old_key = str(item.get("manual_override_source_key") or "")
            if old_key:
                db.rekey_taxonomy_label_override(
                    kind="category",
                    old_key=old_key,
                    new_key=item["key"],
                    centroid=_vector_to_blob(item["vector"]),
                    dimension=len(item["vector"]),
                    updated_at=finished_at,
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


def _discovery_thresholds(
    *,
    document_count: int,
    discovery_document_count: int,
    taxonomy_config: dict,
) -> tuple[int, int]:
    min_growth = max(
        1,
        int(taxonomy_config.get("full_rebuild_min_growth", 30) or 30),
    )
    growth_ratio = max(
        0.0,
        float(taxonomy_config.get("full_rebuild_growth_ratio", 0.10) or 0.10),
    )
    growth_trigger = max(
        min_growth,
        int(math.ceil(max(1, discovery_document_count) * growth_ratio)),
    )

    min_unassigned = max(
        1,
        int(taxonomy_config.get("discovery_min_unassigned", 8) or 8),
    )
    unassigned_ratio = max(
        0.0,
        float(taxonomy_config.get("discovery_unassigned_ratio", 0.03) or 0.03),
    )
    unassigned_trigger = max(
        min_unassigned,
        int(math.ceil(max(1, document_count) * unassigned_ratio)),
    )
    return growth_trigger, unassigned_trigger


def refresh_adaptive_taxonomy(
    db,
    search_config: dict,
    taxonomy_config: dict,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Refresh document assignments and request full discovery only when needed."""
    model = str(search_config.get("model") or "").strip()
    latest = db.latest_taxonomy_run()
    if not model or not latest:
        return {
            "mode": "incremental",
            "needs_rebuild": True,
            "reason": "taxonomy_missing",
        }
    if str(latest["model"] or "") != model:
        return {
            "mode": "incremental",
            "needs_rebuild": True,
            "reason": "embedding_model_changed",
        }

    topic_rows = db.list_taxonomy_topics(limit=5000)
    category_rows = db.list_taxonomy_categories(limit=1000)
    if not topic_rows or not category_rows:
        return {
            "mode": "incremental",
            "needs_rebuild": True,
            "reason": "taxonomy_empty",
        }

    if progress:
        progress(0, 3, "Refreshing taxonomy assignments…")
    documents = _document_vectors(
        db,
        model,
        should_pause=should_pause,
        progress=progress,
    )
    topic_records = [
        {
            "key": str(row["topic_key"]),
            "category_key": str(row["category_key"] or "") or None,
            "vector": _blob_to_vector(row["centroid"]),
        }
        for row in topic_rows
        if row["centroid"]
    ]
    category_records = [
        {
            "key": str(row["category_key"]),
            "vector": _blob_to_vector(row["centroid"]),
        }
        for row in category_rows
        if row["centroid"]
    ]
    if not topic_records or not category_records:
        return {
            "mode": "incremental",
            "needs_rebuild": True,
            "reason": "taxonomy_centroids_missing",
        }

    _wait_while_paused(should_pause, progress)
    assignments = _assign_documents_to_taxonomy(
        documents,
        topic_records,
        category_records,
        taxonomy_config,
    )
    assigned = len(assignments["assigned_documents"])
    unassigned = max(0, len(documents) - assigned)

    try:
        details = json.loads(str(latest["details_json"] or "{}"))
    except (TypeError, json.JSONDecodeError):
        details = {}
    discovery_count = max(
        1,
        int(
            details.get("discovery_document_count")
            or latest["document_count"]
            or len(documents)
            or 1
        ),
    )
    growth = max(0, len(documents) - discovery_count)
    shrink = max(0, discovery_count - len(documents))
    growth_trigger, unassigned_trigger = _discovery_thresholds(
        document_count=len(documents),
        discovery_document_count=discovery_count,
        taxonomy_config=taxonomy_config,
    )
    refresh_limit = max(
        1,
        int(
            taxonomy_config.get(
                "full_rebuild_after_incremental_refreshes",
                20,
            )
            or 20
        ),
    )
    refresh_count = int(
        details.get("incremental_refreshes_since_discovery") or 0
    ) + 1

    needs_rebuild = (
        growth >= growth_trigger
        or shrink >= growth_trigger
        or unassigned >= unassigned_trigger
        or refresh_count >= refresh_limit
    )
    reason = ""
    if growth >= growth_trigger:
        reason = "corpus_growth"
    elif shrink >= growth_trigger:
        reason = "corpus_shrink"
    elif unassigned >= unassigned_trigger:
        reason = "novel_documents"
    elif refresh_count >= refresh_limit:
        reason = "periodic_refresh_limit"

    result = {
        "mode": "incremental",
        "needs_rebuild": needs_rebuild,
        "reason": reason,
        "documents": len(documents),
        "assigned_documents": assigned,
        "unassigned_documents": unassigned,
        "coverage": round(assigned / max(1, len(documents)), 4),
        "growth_since_discovery": growth,
        "shrink_since_discovery": shrink,
        "growth_trigger": growth_trigger,
        "unassigned_trigger": unassigned_trigger,
        "incremental_refreshes_since_discovery": refresh_count,
        "incremental_refresh_limit": refresh_limit,
        "topics": len(topic_records),
        "categories": len(category_records),
    }
    if needs_rebuild:
        if progress:
            progress(1, 3, "New semantic areas detected; full discovery required")
        return result

    if progress:
        progress(1, 3, "Updating existing taxonomy assignments…")
    refreshed_at = _now()
    details.update(
        {
            "embedding_signature": db.embedding_signature(model),
            "documents_with_vectors": len(documents),
            "assigned_documents": assigned,
            "unassigned_documents": unassigned,
            "coverage": result["coverage"],
            "last_refresh_mode": "incremental",
            "last_incremental_at": refreshed_at,
            "growth_since_discovery": growth,
            "shrink_since_discovery": shrink,
            "growth_trigger": growth_trigger,
            "unassigned_trigger": unassigned_trigger,
            "incremental_refreshes_since_discovery": refresh_count,
            "incremental_refresh_limit": refresh_limit,
        }
    )
    db.refresh_taxonomy_assignments(
        run_id=int(latest["id"]),
        refreshed_at=refreshed_at,
        document_count=db.document_count(),
        embedding_count=db.embedding_count(model),
        category_assignments=assignments["category_assignments"],
        topic_assignments=assignments["topic_assignments"],
        category_document_counts=assignments["category_document_counts"],
        topic_document_counts=assignments["topic_document_counts"],
        details_json=json.dumps(details, ensure_ascii=False),
    )
    if progress:
        progress(3, 3, "Existing taxonomy updated incrementally")
    return result


def _assign_documents_to_taxonomy(
    documents: list[dict[str, Any]],
    topic_records: list[dict[str, Any]],
    category_records: list[dict[str, Any]],
    taxonomy_config: dict,
    *,
    primary_topic: dict[str, str] | None = None,
) -> dict[str, Any]:
    topic_assignments: list[tuple[str, str, float]] = []
    category_scores: dict[tuple[str, str], float] = {}
    assigned_documents: set[str] = set()
    topic_documents: dict[str, set[str]] = defaultdict(set)
    category_documents: dict[str, set[str]] = defaultdict(set)
    assignment_threshold = float(
        taxonomy_config.get("topic_assignment_similarity", 0.68)
    )
    max_topics_per_document = max(
        1,
        int(taxonomy_config.get("max_topics_per_document", 4) or 4),
    )
    topic_lookup = {topic["key"]: topic for topic in topic_records}
    category_lookup = {
        category["key"]: category
        for category in category_records
    }
    primary_topic = primary_topic or {}

    for document in documents:
        sha256 = str(document["id"])
        scored_topics = sorted(
            (
                (_dot(document["vector"], topic["vector"]), topic)
                for topic in topic_records
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        selected: list[tuple[float, dict[str, Any]]] = [
            (score, topic)
            for score, topic in scored_topics
            if score >= assignment_threshold
        ][:max_topics_per_document]

        primary_key = primary_topic.get(sha256)
        if primary_key and all(
            topic["key"] != primary_key for _, topic in selected
        ):
            primary = topic_lookup.get(primary_key)
            if primary is not None:
                selected.append(
                    (_dot(document["vector"], primary["vector"]), primary)
                )

        for score, topic in selected:
            score = max(0.0, float(score))
            topic_assignments.append((sha256, topic["key"], score))
            topic_documents[topic["key"]].add(sha256)
            assigned_documents.add(sha256)

            category_key = topic.get("category_key")
            category = category_lookup.get(category_key)
            if category_key and category is not None:
                category_score = max(
                    0.0,
                    _dot(document["vector"], category["vector"]),
                )
                key = (sha256, category_key)
                category_scores[key] = max(
                    category_scores.get(key, 0.0),
                    category_score,
                )
                category_documents[category_key].add(sha256)

    category_assignments = [
        (sha256, category_key, score)
        for (sha256, category_key), score in sorted(category_scores.items())
    ]
    return {
        "topic_assignments": topic_assignments,
        "category_assignments": category_assignments,
        "assigned_documents": assigned_documents,
        "topic_document_counts": {
            topic["key"]: len(topic_documents.get(topic["key"], set()))
            for topic in topic_records
        },
        "category_document_counts": {
            category["key"]: len(
                category_documents.get(category["key"], set())
            )
            for category in category_records
        },
        "assignment_threshold": assignment_threshold,
        "max_topics_per_document": max_topics_per_document,
    }


def _document_vectors(
    db,
    model: str,
    *,
    should_pause: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}

    for batch in db.embedding_batches(model, batch_size=500):
        _wait_while_paused(should_pause, progress)
        for row in batch:
            vector = _blob_to_vector(row["vector"])
            if not vector:
                continue

            sha256 = str(row["document_sha256"])
            state = aggregates.get(sha256)
            if state is None:
                state = {
                    "sum": [0.0] * len(vector),
                    "count": 0,
                    "texts": [],
                    "source_path": str(row["source_path"] or ""),
                }
                aggregates[sha256] = state

            if len(state["sum"]) != len(vector):
                # Ignore a malformed/mixed-dimension row without poisoning the
                # entire document centroid.
                continue

            for index, value in enumerate(vector):
                state["sum"][index] += float(value)
            state["count"] += 1

            text = str(row["text"] or "").strip()
            if text and len(state["texts"]) < 5:
                state["texts"].append(text[:1200])

    documents: list[dict[str, Any]] = []
    for sha256 in sorted(aggregates):
        state = aggregates[sha256]
        count = int(state["count"])
        if count <= 0:
            continue
        centroid = _normalize(
            [value / count for value in state["sum"]]
        )
        documents.append(
            {
                "id": sha256,
                "vector": centroid,
                "weight": 1,
                "source_path": state["source_path"],
                "text": "\n".join(state["texts"]),
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
    previous=(),
    overrides=(),
    labeler=None,
    should_pause: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
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

    _apply_manual_overrides(
        candidates,
        overrides,
        threshold=float(
            taxonomy_config.get("topic_manual_override_similarity", 0.90)
        ),
    )
    _reuse_previous_labels(
        candidates,
        previous,
        threshold=float(
            taxonomy_config.get("topic_label_reuse_similarity", 0.88)
        ),
    )
    labels = _labels(
        "topic",
        candidates,
        taxonomy_config,
        qa_config,
        labeler=labeler,
        should_pause=should_pause,
        progress=progress,
    )
    _apply_labels(candidates, labels)
    return candidates


def _materialize_categories(
    clusters: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    taxonomy_config: dict,
    qa_config: dict,
    *,
    previous=(),
    overrides=(),
    labeler=None,
    should_pause: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
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

    _apply_manual_overrides(
        candidates,
        overrides,
        threshold=float(
            taxonomy_config.get("category_manual_override_similarity", 0.86)
        ),
    )
    _reuse_previous_labels(
        candidates,
        previous,
        threshold=float(
            taxonomy_config.get("category_label_reuse_similarity", 0.82)
        ),
    )
    labels = _labels(
        "category",
        candidates,
        taxonomy_config,
        qa_config,
        labeler=labeler,
        should_pause=should_pause,
        progress=progress,
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
    should_pause: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, dict[str, str]]:
    pending = [
        item for item in candidates
        if not bool(item.get("label_locked"))
    ]
    if not pending:
        return {}
    if labeler is not None:
        try:
            _wait_while_paused(should_pause, progress)
            return labeler(kind, pending) or {}
        except Exception:
            return {}
    if not bool(taxonomy_config.get("label_with_ollama", True)):
        return {}
    try:
        return _ollama_labels(
            kind,
            pending,
            taxonomy_config,
            qa_config,
            should_pause=should_pause,
            progress=progress,
        )
    except Exception:
        return {}


def _ollama_labels(
    kind: str,
    candidates: list[dict[str, Any]],
    taxonomy_config: dict,
    qa_config: dict,
    *,
    should_pause: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
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
        _wait_while_paused(should_pause, progress)
        batch = selected[offset:offset + batch_size]
        payload = [
            {
                "id": item["key"],
                "keywords": item["keywords"][:8],
                "representatives": item.get("representatives", [])[:4],
                "snippets": [
                    str(value)[:350]
                    for value in item.get("snippets", [])[:2]
                ],
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


def _apply_manual_overrides(
    candidates: list[dict[str, Any]],
    overrides,
    *,
    threshold: float,
) -> None:
    override_items = []
    for row in overrides or []:
        blob = row["centroid"]
        if not blob:
            continue
        vector = _blob_to_vector(blob)
        if not vector:
            continue
        override_items.append(
            {
                "name": str(row["name"] or ""),
                "description": str(row["description"] or ""),
                "vector": vector,
                "source_key": str(row["source_key"] or ""),
            }
        )

    used: set[int] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: int(item.get("document_count") or 0),
        reverse=True,
    ):
        best_index = -1
        best_score = float(threshold)
        for index, override in enumerate(override_items):
            if index in used:
                continue
            score = _dot(candidate["vector"], override["vector"])
            if score > best_score or (
                best_index < 0 and score >= best_score
            ):
                best_score = score
                best_index = index
        if best_index < 0:
            continue

        override = override_items[best_index]
        if override["name"]:
            candidate["name"] = override["name"]
        if override["description"]:
            candidate["description"] = override["description"]
        candidate["label_locked"] = True
        candidate["label_source"] = "manual"
        candidate["manual_override_source_key"] = override["source_key"]
        candidate["manual_override_score"] = round(best_score, 4)
        used.add(best_index)


def _reuse_previous_labels(
    candidates: list[dict[str, Any]],
    previous,
    *,
    threshold: float,
) -> None:
    previous_items = []
    for row in previous or []:
        blob = row["centroid"]
        if not blob:
            continue
        vector = _blob_to_vector(blob)
        if not vector:
            continue
        previous_items.append(
            {
                "name": str(row["name"] or ""),
                "description": str(row["description"] or ""),
                "vector": vector,
            }
        )

    used_previous: set[int] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: int(item.get("document_count") or 0),
        reverse=True,
    ):
        if bool(candidate.get("label_locked")):
            continue
        best_index = -1
        best_score = float(threshold)
        for index, old in enumerate(previous_items):
            if index in used_previous:
                continue
            score = _dot(candidate["vector"], old["vector"])
            if score >= best_score:
                best_score = score
                best_index = index
        if best_index < 0:
            continue
        old = previous_items[best_index]
        if old["name"]:
            candidate["name"] = old["name"]
            candidate["description"] = (
                old["description"] or candidate["description"]
            )
            candidate["label_locked"] = True
            candidate["label_reuse_score"] = round(best_score, 4)
            used_previous.add(best_index)


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
    text = re.sub(r"\s+", " ", str(value or "")).strip(" -–—:;")
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
