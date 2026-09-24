from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib import error, request
from urllib.parse import urlparse

from .search import SearchHit, search_chunks


ASK_MODES = {
    "quick": {
        "label": "Быстро",
        "instruction": (
            "Дай прямой и компактный ответ. Сначала ответь по существу, затем при необходимости "
            "добавь 2–4 ключевых пункта."
        ),
    },
    "deep": {
        "label": "Глубокий анализ",
        "instruction": (
            "Сделай более глубокий синтез нескольких фрагментов. Отделяй устойчиво повторяющиеся "
            "наблюдения от единичных утверждений, отмечай неопределённость и ограничения источников."
        ),
    },
    "compare": {
        "label": "Сравнить документы",
        "instruction": (
            "Сравни сведения между разными документами. Покажи сходства и различия по существу, "
            "ссылаясь на обе стороны сравнения. Если независимых документов недостаточно, прямо скажи об этом."
        ),
    },
    "contradictions": {
        "label": "Найти противоречия",
        "instruction": (
            "Ищи только содержательные несовместимые утверждения между источниками. Не называй обычные "
            "различия формулировок противоречием. Для каждого найденного расхождения приводи ссылки на обе стороны; "
            "если явных противоречий нет, так и скажи."
        ),
    },
}


@dataclass(frozen=True)
class QAResult:
    question: str
    answer: str
    model: str
    sources: list[SearchHit]
    mode: str = "quick"


def ollama_models(base_url: str = "http://127.0.0.1:11434", *, timeout: float = 1.5) -> list[str]:
    _validate_local_url(base_url)
    try:
        with request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama is not reachable on the configured local address") from exc
    return [
        str(item.get("name") or item.get("model"))
        for item in payload.get("models", [])
        if item.get("name") or item.get("model")
    ]


def ask_documents(
    db,
    question: str,
    search_config: dict,
    qa_config: dict,
    *,
    analysis_mode: str = "quick",
    chat_client: Callable[[str, str, list[dict[str, str]]], str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> QAResult:
    question = question.strip()
    if not question:
        raise RuntimeError("Question is empty")
    analysis_mode = str(analysis_mode or "quick").strip().casefold()
    if analysis_mode not in ASK_MODES:
        raise RuntimeError(f"Unknown Ask mode: {analysis_mode}")

    base_top_k = max(1, min(20, int(qa_config.get("top_k", 6))))
    base_context = max(2000, int(qa_config.get("max_context_chars", 8000)))
    top_k, context_limit, max_per_document = _mode_limits(
        analysis_mode, base_top_k, base_context
    )

    if progress:
        progress("searching")
    candidate_limit = min(30, max(top_k, top_k * 2 if analysis_mode != "quick" else top_k))
    hits = search_chunks(
        db,
        question,
        search_config,
        limit=candidate_limit,
        mode="auto",
    )
    if not hits:
        raise RuntimeError("No relevant document fragments were found")

    if progress:
        progress("reviewing")
    hits = _diversify_hits(hits, top_k, max_per_document=max_per_document)

    base_url = str(qa_config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    _validate_local_url(base_url)
    model = str(qa_config.get("model") or "").strip()
    if not model:
        models = ollama_models(base_url)
        if not models:
            raise RuntimeError("Ollama is running, but no local model is installed")
        model = models[0]

    context_parts: list[str] = []
    used = 0
    selected: list[SearchHit] = []
    for index, hit in enumerate(hits, 1):
        location = hit.source_path + (f", page {hit.page}" if hit.page is not None else "")
        block = f"[{index}] {location}\n{hit.text.strip()}\n"
        if selected and used + len(block) > context_limit:
            break
        context_parts.append(block)
        selected.append(hit)
        used += len(block)

    mode_instruction = ASK_MODES[analysis_mode]["instruction"]
    system = (
        "Ты локальный помощник по документальной базе. Отвечай только на основе предоставленных "
        "фрагментов. Не додумывай отсутствующие факты и не превращай предположения источников в установленные факты. "
        "Ссылайся на источники в формате [1], [2]. Если данных недостаточно, прямо скажи об этом. "
        "Отвечай на языке вопроса. "
        + mode_instruction
    )
    user = (
        f"Режим анализа: {ASK_MODES[analysis_mode]['label']}\n"
        f"Вопрос:\n{question}\n\nФрагменты документов:\n"
        + "\n".join(context_parts)
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    if progress:
        progress("generating")
    if chat_client is not None:
        answer = chat_client(base_url, model, messages).strip()
    else:
        answer = _ollama_chat(base_url, model, messages, qa_config).strip()
    if not answer:
        raise RuntimeError("The local model returned an empty answer")
    if progress:
        progress("done")
    return QAResult(question, answer, model, selected, analysis_mode)


def _mode_limits(mode: str, base_top_k: int, base_context: int) -> tuple[int, int, int]:
    if mode == "quick":
        return base_top_k, base_context, 3
    if mode == "deep":
        return min(16, max(8, base_top_k + 4)), min(18000, max(12000, base_context)), 3
    if mode == "compare":
        return min(18, max(10, base_top_k + 6)), min(18000, max(14000, base_context)), 2
    if mode == "contradictions":
        return min(18, max(10, base_top_k + 6)), min(18000, max(14000, base_context)), 2
    raise RuntimeError(f"Unknown Ask mode: {mode}")


def _diversify_hits(
    hits: list[SearchHit],
    limit: int,
    *,
    max_per_document: int,
) -> list[SearchHit]:
    if limit <= 0:
        return []
    selected: list[SearchHit] = []
    per_document: dict[str, int] = {}
    deferred: list[SearchHit] = []

    for hit in hits:
        count = per_document.get(hit.document_sha256, 0)
        if count < max_per_document:
            selected.append(hit)
            per_document[hit.document_sha256] = count + 1
            if len(selected) >= limit:
                return selected
        else:
            deferred.append(hit)

    for hit in deferred:
        selected.append(hit)
        if len(selected) >= limit:
            break
    return selected


def _ollama_chat(base_url: str, model: str, messages: list[dict[str, str]], qa_config: dict) -> str:
    num_ctx = max(2048, int(qa_config.get("num_ctx", 4096)))
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "think": bool(qa_config.get("think", False)),
        "keep_alive": qa_config.get("keep_alive", 0),
        "options": {"num_ctx": num_ctx},
    }).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=240) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("Local Ollama request failed") from exc
    return str((data.get("message") or {}).get("content") or "")


def _validate_local_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Q&A is restricted to a local Ollama endpoint")
