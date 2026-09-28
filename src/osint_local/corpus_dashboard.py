from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

SUPPORTED_TRANSLATION_SOURCES = {"en", "uk"}


def build_corpus_dashboard(settings, db) -> dict[str, Any]:
    """Build a read-only operational snapshot from persisted corpus metadata."""
    documents = db.corpus_dashboard_documents()
    translations = db.corpus_dashboard_translations(target_lang="ru")
    raw_stats = db.stats()

    done = [row for row in documents if str(row["status"] or "") == "done"]
    done_shas = {str(row["sha256"]) for row in done}
    status_counts = Counter(str(row["status"] or "unknown") for row in documents)
    language_counts = Counter(_language_label(row["language"]) for row in done)
    file_type_counts = Counter(_file_type_label(row["extension"]) for row in done)
    extraction_counts = Counter(
        str(row["extraction_method"] or "unknown") for row in done
    )

    page_count = 0
    ocr_checked_pages = 0
    ocr_pages = 0
    ocr_documents: set[str] = set()
    layout_pages = 0
    low_quality_pages = 0
    low_quality_documents: set[str] = set()
    quality_threshold = float(settings.ocr.get("quality_threshold", 0.72))

    attention: dict[str, dict[str, Any]] = {}

    for row in done:
        sha256 = str(row["sha256"])
        source_path = str(row["source_path"] or sha256)
        metadata = _safe_json(row["metadata_json"])
        pages = metadata.get("pages") or []
        if not isinstance(pages, list):
            pages = []

        document_low_quality = False
        document_used_ocr = False
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_count += 1
            if bool(page.get("ocr_checked")):
                ocr_checked_pages += 1
            if str(page.get("method") or "") == "ocr":
                ocr_pages += 1
                document_used_ocr = True
            if bool(page.get("layout_used")):
                layout_pages += 1

            score = page.get("quality_score")
            try:
                low_quality = score is not None and float(score) < quality_threshold
            except (TypeError, ValueError):
                low_quality = False
            if low_quality:
                low_quality_pages += 1
                document_low_quality = True

        if document_used_ocr:
            ocr_documents.add(sha256)
        if document_low_quality:
            low_quality_documents.add(sha256)
            _add_attention(
                attention,
                sha256=sha256,
                source_path=source_path,
                reason="Low extraction quality",
                priority=2,
            )

    for row in documents:
        if str(row["status"] or "") != "error":
            continue
        _add_attention(
            attention,
            sha256=str(row["sha256"]),
            source_path=str(row["source_path"] or row["sha256"]),
            reason=str(row["error"] or "Processing error"),
            priority=3,
        )

    translated_shas: set[str] = set()
    engine_counts: Counter[str] = Counter()
    quality_warnings = 0
    quality_warning_documents: set[str] = set()
    quality_retries = 0
    quality_fallbacks = 0
    literal_fallbacks = 0

    for row in translations:
        sha256 = str(row["document_sha256"])
        if sha256 not in done_shas:
            continue
        translated_shas.add(sha256)
        engine_counts[str(row["engine"] or "unknown")] += 1
        metadata = _translation_metadata(row["output_path"])
        warnings = _count_value(metadata.get("quality_warnings"))
        quality_warnings += warnings
        quality_retries += _count_value(metadata.get("quality_retries"))
        quality_fallbacks += _count_value(metadata.get("quality_fallbacks"))
        literal_fallbacks += _count_value(metadata.get("literal_segment_fallbacks"))
        literal_fallbacks += _count_value(
            metadata.get("quality_literal_segment_fallbacks")
        )
        if warnings:
            quality_warning_documents.add(sha256)
            source_path = next(
                (
                    str(doc["source_path"])
                    for doc in done
                    if str(doc["sha256"]) == sha256
                ),
                sha256,
            )
            _add_attention(
                attention,
                sha256=sha256,
                source_path=source_path,
                reason=f"Translation quality warnings: {warnings}",
                priority=1,
            )

    eligible_shas = {
        str(row["sha256"])
        for row in done
        if str(row["language"] or "").casefold() in SUPPORTED_TRANSLATION_SOURCES
    }
    translated_eligible = eligible_shas & translated_shas

    model = str(settings.search.get("model") or "")
    chunks = int(raw_stats.get("chunks") or 0)
    embedding_count = int((raw_stats.get("embeddings") or {}).get(model, 0))

    attention_rows = sorted(
        attention.values(),
        key=lambda item: (-int(item["priority"]), str(item["source_path"]).casefold()),
    )[:20]

    return {
        "documents": len(done),
        "statuses": dict(status_counts),
        "pages": page_count,
        "chunks": chunks,
        "embedding_count": embedding_count,
        "semantic_coverage": _coverage(embedding_count, chunks),
        "languages": _sorted_counts(language_counts),
        "file_types": _sorted_counts(file_type_counts),
        "extraction_methods": _sorted_counts(extraction_counts),
        "ocr_checked_pages": ocr_checked_pages,
        "ocr_pages": ocr_pages,
        "ocr_documents": len(ocr_documents),
        "layout_pages": layout_pages,
        "low_quality_pages": low_quality_pages,
        "low_quality_documents": len(low_quality_documents),
        "errors": int(status_counts.get("error", 0)),
        "translation_eligible_documents": len(eligible_shas),
        "translated_documents": len(translated_shas),
        "translated_eligible_documents": len(translated_eligible),
        "translation_coverage": _coverage(
            len(translated_eligible),
            len(eligible_shas),
        ),
        "translation_engines": _sorted_counts(engine_counts),
        "translation_quality_warnings": quality_warnings,
        "translation_warning_documents": len(quality_warning_documents),
        "translation_quality_retries": quality_retries,
        "translation_quality_fallbacks": quality_fallbacks,
        "literal_segment_fallbacks": literal_fallbacks,
        "attention": attention_rows,
    }


def _safe_json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _translation_metadata(output_path: Any) -> dict[str, Any]:
    try:
        path = Path(str(output_path))
        meta_path = path.with_suffix(path.suffix + ".json")
        if not meta_path.is_file():
            return {}
        return _safe_json(meta_path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _count_value(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _coverage(complete: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(min(1.0, max(0.0, float(complete) / float(total))), 4)


def _language_label(value: Any) -> str:
    code = str(value or "").strip().casefold()
    return {
        "en": "English",
        "uk": "Ukrainian",
        "ru": "Russian",
    }.get(code, code.upper() if code else "Unknown")


def _file_type_label(value: Any) -> str:
    suffix = str(value or "").strip().casefold().lstrip(".")
    return suffix.upper() if suffix else "Unknown"


def _sorted_counts(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"name": name, "count": int(count)}
        for name, count in sorted(
            counter.items(),
            key=lambda item: (-int(item[1]), str(item[0]).casefold()),
        )
    ]


def _add_attention(
    attention: dict[str, dict[str, Any]],
    *,
    sha256: str,
    source_path: str,
    reason: str,
    priority: int,
) -> None:
    current = attention.get(sha256)
    if current is None:
        attention[sha256] = {
            "sha256": sha256,
            "source_path": source_path,
            "reasons": [reason],
            "priority": priority,
        }
        return
    if reason not in current["reasons"]:
        current["reasons"].append(reason)
    current["priority"] = max(int(current["priority"]), int(priority))
