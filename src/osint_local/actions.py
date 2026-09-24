from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .pipeline import LocalPipeline, ProcessResult
from .search import build_embeddings
from .translation import translate_document


class ActionBusyError(RuntimeError):
    pass


@dataclass
class ActionState:
    kind: str = ""
    status: str = "idle"
    current: int = 0
    total: int = 0
    message: str = "Ready"
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionManager:
    """Serialize long-running UI actions and expose small progress snapshots."""

    def __init__(
        self,
        pipeline: LocalPipeline,
        *,
        index_builder: Callable[..., int] = build_embeddings,
    ) -> None:
        self.pipeline = pipeline
        self.index_builder = index_builder
        self._lock = threading.RLock()
        self._state = ActionState()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._state.as_dict()

    def start_scan(self) -> dict[str, Any]:
        return self._start("scan", self._run_scan)

    def start_index(self) -> dict[str, Any]:
        return self._start("index", self._run_index)

    def start_translate(self, sha256: str, source_lang: str, target_lang: str) -> dict[str, Any]:
        return self._start("translate", lambda: self._run_translate(sha256, source_lang, target_lang))

    def _start(self, kind: str, target: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if self._state.status == "running":
                raise ActionBusyError(f"{self._state.kind} is already running")
            self._state = ActionState(
                kind=kind,
                status="running",
                message="Starting…",
                started_at=_now(),
            )
            self._thread = threading.Thread(
                target=self._worker,
                args=(target,),
                name=f"osint-local-{kind}",
                daemon=True,
            )
            self._thread.start()
            return self._state.as_dict()

    def _worker(self, target: Callable[[], dict[str, Any]]) -> None:
        try:
            result = target()
        except Exception as exc:  # defensive boundary: surfaced to the UI
            with self._lock:
                self._state.status = "failed"
                self._state.message = "Action failed"
                self._state.error = f"{type(exc).__name__}: {exc}"
                self._state.finished_at = _now()
            return
        with self._lock:
            self._state.status = "succeeded"
            labels = {"scan": "Scan complete", "index": "Index complete", "translate": "Translation complete"}
            self._state.message = labels.get(self._state.kind, "Action complete")
            self._state.result = result
            self._state.finished_at = _now()
            if self._state.total and self._state.current < self._state.total:
                self._state.current = self._state.total

    def _run_scan(self) -> dict[str, Any]:
        counts: dict[str, int] = {}

        def progress(current: int, total: int, result: ProcessResult | None) -> None:
            if result is not None:
                counts[result.status] = counts.get(result.status, 0) + 1
                label = result.path.name
            else:
                label = "Preparing scan…"
            self._progress(current, total, label)

        results = self.pipeline.scan(progress=progress)
        if not results:
            self._progress(0, 0, "No supported files found")
        return {"counts": counts, "files_seen": len(results)}

    def _run_index(self) -> dict[str, Any]:
        def progress(current: int, total: int) -> None:
            self._progress(current, total, "Building semantic index…")

        count = self.index_builder(
            self.pipeline.db,
            self.pipeline.settings.search,
            progress=progress,
        )
        if count == 0:
            self._progress(0, 0, "Semantic index is already up to date")
        return {
            "embedded_chunks": count,
            "model": self.pipeline.settings.search.get("model"),
        }

    def _run_translate(self, sha256: str, source_lang: str, target_lang: str) -> dict[str, Any]:
        def progress(current: int, total: int, message: str) -> None:
            self._progress(current, total, message)

        return translate_document(
            self.pipeline.settings,
            self.pipeline.db,
            sha256,
            source_lang=source_lang,
            target_lang=target_lang,
            progress=progress,
        )

    def _progress(self, current: int, total: int, message: str) -> None:
        with self._lock:
            self._state.current = max(0, int(current))
            self._state.total = max(0, int(total))
            self._state.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
