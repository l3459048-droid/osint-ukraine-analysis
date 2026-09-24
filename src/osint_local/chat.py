from __future__ import annotations

from dataclasses import dataclass

from .qa import _ollama_chat, ollama_models


@dataclass(frozen=True)
class ChatResult:
    answer: str
    model: str


def chat_local(
    message: str,
    history: list[dict[str, str]],
    qa_config: dict,
) -> ChatResult:
    message = message.strip()
    if not message:
        raise RuntimeError("Message is empty")

    base_url = str(qa_config.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
    model = str(qa_config.get("model") or "").strip()
    if not model:
        models = ollama_models(base_url)
        if not models:
            raise RuntimeError("Ollama is running, but no local model is installed")
        model = models[0]

    system = (
        "Ты локальный универсальный помощник. Отвечай на языке пользователя. "
        "В этом режиме у тебя нет доступа к библиотеке документов и интернету. "
        "Не утверждай, что проверил локальные документы или свежие данные. "
        "Если вопрос требует актуальной информации, прямо скажи, что не можешь её проверить в этом режиме."
    )

    max_history_chars = max(2000, min(20000, int(qa_config.get("chat_history_chars", 9000))))
    selected: list[dict[str, str]] = []
    used = 0
    for item in reversed(history):
        content = str(item.get("content") or "")
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"} or not content:
            continue
        if selected and used + len(content) > max_history_chars:
            break
        selected.append({"role": role, "content": content})
        used += len(content)
    selected.reverse()

    messages = [{"role": "system", "content": system}, *selected, {"role": "user", "content": message}]
    answer = _ollama_chat(base_url, model, messages, qa_config).strip()
    if not answer:
        raise RuntimeError("The local model returned an empty answer")
    return ChatResult(answer=answer, model=model)
