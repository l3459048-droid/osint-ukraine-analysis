from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib import error, request
from urllib.parse import urlparse

from .search import SearchHit, search_chunks


@dataclass(frozen=True)
class QAResult:
    question: str
    answer: str
    model: str
    sources: list[SearchHit]


def ollama_models(base_url: str = "http://127.0.0.1:11434", *, timeout: float = 1.5) -> list[str]:
    _validate_local_url(base_url)
    try:
        with request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama is not reachable on the configured local address") from exc
    return [str(item.get("name") or item.get("model")) for item in payload.get("models", []) if item.get("name") or item.get("model")]


def ask_documents(
    db,
    question: str,
    search_config: dict,
    qa_config: dict,
    *,
    chat_client: Callable[[str, str, list[dict[str, str]]], str] | None = None,
) -> QAResult:
    question = question.strip()
    if not question:
        raise RuntimeError("Question is empty")
    top_k = max(1, min(20, int(qa_config.get("top_k", 8))))
    hits = search_chunks(db, question, search_config, limit=top_k, mode="auto")
    if not hits:
        raise RuntimeError("No relevant document fragments were found")

    base_url = str(qa_config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    _validate_local_url(base_url)
    model = str(qa_config.get("model") or "").strip()
    if not model:
        models = ollama_models(base_url)
        if not models:
            raise RuntimeError("Ollama is running, but no local model is installed")
        model = models[0]

    context_limit = max(2000, int(qa_config.get("max_context_chars", 14000)))
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

    system = (
        "Ты локальный помощник по документальной базе. Отвечай только на основе предоставленных "
        "фрагментов. Не додумывай отсутствующие факты. Ссылайся на источники в формате [1], [2]. "
        "Если данных недостаточно, прямо скажи об этом. Отвечай на языке вопроса."
    )
    user = f"Вопрос:\n{question}\n\nФрагменты документов:\n" + "\n".join(context_parts)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if chat_client is not None:
        answer = chat_client(base_url, model, messages).strip()
    else:
        answer = _ollama_chat(base_url, model, messages, qa_config).strip()
    if not answer:
        raise RuntimeError("The local model returned an empty answer")
    return QAResult(question, answer, model, selected)


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
        with request.urlopen(req, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError("Local Ollama request failed") from exc
    return str((data.get("message") or {}).get("content") or "")


def _validate_local_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Q&A is restricted to a local Ollama endpoint")
