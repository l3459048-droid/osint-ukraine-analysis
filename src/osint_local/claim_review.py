from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from .qa import _ollama_chat, _validate_local_url


STRUCTURAL_STATUSES = {"clear_claim", "not_claim", "uncertain"}
CLAIM_TYPES = {"assertion", "attributed", "forecast", "recommendation", "other"}
CERTAINTIES = {"asserted", "hedged", "planned", "recommended", "unknown"}
METHOD = "qwen-structural-v1"


def review_claim_candidate(
    db,
    evidence_id: int,
    qa_config: dict,
    analysis_config: dict | None = None,
    *,
    chat_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    row = db.get_evidence_item(int(evidence_id))
    if not row or row["kind"] != "claim":
        raise RuntimeError("Claim candidate not found")

    config = dict(analysis_config or {})
    base_url = str(
        config.get("claim_review_base_url")
        or qa_config.get("base_url")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    _validate_local_url(base_url)
    model = str(
        config.get("claim_review_model")
        or qa_config.get("model")
        or ""
    ).strip()
    if not model:
        raise RuntimeError("Claim review model is not configured")

    max_chars = max(
        300,
        min(4000, int(config.get("claim_review_max_chars", 1600) or 1600)),
    )
    candidate = str(row["value"] or "").strip()[:max_chars]
    context = str(row["context"] or "").strip()[:max_chars]
    if not candidate:
        raise RuntimeError("Claim candidate is empty")

    messages = [
        {
            "role": "system",
            "content": (
                "You review the STRUCTURE of a candidate claim extracted from a document. "
                "Do not fact-check it. Do not decide whether it is true or false. "
                "Do not use outside knowledge. Use only the supplied candidate/context. "
                "Return ONLY one valid JSON object with exactly these string fields: "
                "structural_status, claim_type, canonical_claim, subject, predicate, "
                "object, certainty, rationale. "
                "structural_status must be clear_claim, not_claim, or uncertain. "
                "claim_type must be assertion, attributed, forecast, recommendation, or other. "
                "certainty must be asserted, hedged, planned, recommended, or unknown. "
                "canonical_claim should preserve the candidate's meaning without adding facts. "
                "subject/predicate/object may be empty when unclear. "
                "rationale must briefly explain only the structural classification."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "candidate": candidate,
                    "context": context,
                    "heuristic_subtype": str(row["subtype"] or ""),
                    "heuristic_confidence": float(row["confidence"] or 0.0),
                },
                ensure_ascii=False,
            ),
        },
    ]

    call = chat_fn or _ollama_chat
    raw = call(
        base_url,
        model,
        messages,
        {
            **qa_config,
            "think": False,
            "keep_alive": qa_config.get("keep_alive", 0),
        },
    )
    parsed = _parse_review_json(raw)
    reviewed_at = datetime.now(timezone.utc).isoformat()
    db.save_claim_review(
        evidence_id=int(evidence_id),
        structural_status=parsed["structural_status"],
        claim_type=parsed["claim_type"],
        canonical_claim=parsed["canonical_claim"],
        subject=parsed["subject"],
        predicate=parsed["predicate"],
        object_text=parsed["object"],
        certainty=parsed["certainty"],
        rationale=parsed["rationale"],
        model=model,
        method=METHOD,
        reviewed_at=reviewed_at,
        details_json=json.dumps(
            {
                "heuristic_subtype": str(row["subtype"] or ""),
                "heuristic_confidence": float(row["confidence"] or 0.0),
            },
            ensure_ascii=False,
        ),
    )
    return {
        "evidence_id": int(evidence_id),
        "model": model,
        "method": METHOD,
        "reviewed_at": reviewed_at,
        **parsed,
    }


def review_claim_candidates(
    db,
    qa_config: dict,
    analysis_config: dict | None = None,
    *,
    limit: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
    chat_fn: Callable[..., str] | None = None,
) -> dict[str, Any]:
    config = dict(analysis_config or {})
    batch_limit = max(
        1,
        min(
            50,
            int(
                limit
                if limit is not None
                else config.get("claim_review_batch_size", 8)
                or 8
            ),
        ),
    )
    min_confidence = max(
        0.0,
        min(
            1.0,
            float(config.get("claim_review_min_confidence", 0.62) or 0.62),
        ),
    )
    rows = db.unreviewed_claims(
        limit=batch_limit,
        min_confidence=min_confidence,
    )
    total = len(rows)
    reviewed: list[int] = []
    failed: list[dict[str, Any]] = []

    if progress:
        progress(0, max(1, total), "Preparing structural claim review…")

    for index, row in enumerate(rows, start=1):
        while should_pause and should_pause():
            if progress:
                progress(
                    index - 1,
                    max(1, total),
                    "Claim review paused for interactive work",
                )
            import time
            time.sleep(0.5)

        try:
            review_claim_candidate(
                db,
                int(row["id"]),
                qa_config,
                config,
                chat_fn=chat_fn,
            )
            reviewed.append(int(row["id"]))
        except Exception as exc:
            failed.append(
                {
                    "evidence_id": int(row["id"]),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if progress:
            progress(
                index,
                max(1, total),
                f"Claim structure review · {index}/{total}",
            )

    return {
        "requested": batch_limit,
        "eligible": total,
        "reviewed": len(reviewed),
        "reviewed_ids": reviewed,
        "failed": failed,
        "remaining": db.unreviewed_claim_count(
            min_confidence=min_confidence,
        ),
    }


def _parse_review_json(raw: str) -> dict[str, str]:
    value = str(raw or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)

    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Claim review returned invalid JSON")
    try:
        parsed = json.loads(value[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Claim review returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Claim review returned invalid JSON")

    structural_status = _enum(
        parsed.get("structural_status"),
        STRUCTURAL_STATUSES,
        "structural_status",
    )
    claim_type = _enum(
        parsed.get("claim_type"),
        CLAIM_TYPES,
        "claim_type",
    )
    certainty = _enum(
        parsed.get("certainty"),
        CERTAINTIES,
        "certainty",
    )
    return {
        "structural_status": structural_status,
        "claim_type": claim_type,
        "canonical_claim": _clean(parsed.get("canonical_claim"), 900),
        "subject": _clean(parsed.get("subject"), 240),
        "predicate": _clean(parsed.get("predicate"), 240),
        "object": _clean(parsed.get("object"), 500),
        "certainty": certainty,
        "rationale": _clean(parsed.get("rationale"), 500),
    }


def _enum(value: Any, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in allowed:
        raise RuntimeError(f"Claim review returned invalid {field}")
    return normalized


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
