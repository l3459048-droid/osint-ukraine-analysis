from __future__ import annotations

import importlib.util
import json
import logging
import mimetypes
import re
import secrets
import shutil
import threading
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .actions import ActionBusyError, ActionManager
from .background import BackgroundLoop
from .config import PERFORMANCE_PROFILES, Settings, load_settings, performance_profile_patch, update_config
from .desktop import open_folder, pick_folder
from .pipeline import LocalPipeline
from .qa import ASK_MODES, ask_documents, ollama_models
from .reader import load_reader
from .search import search_chunks
from .translation import argos_available, installed_pairs, translation_queue_status
from .web_ui import (
    _action_panel,
    _activity_details,
    _ask_form,
    _category_list,
    _chunk_card,
    _classification_badges,
    _document_cards,
    _document_table,
    _domain_filter,
    _e,
    _hero,
    _layout,
    _metadata_grid,
    _page_header,
    _pagination,
    _qa_answer,
    _reader_panel,
    _first,
    _safe_json,
    _search_form,
    _search_hit,
    _settings_panel,
    _system_panel,
    _setup_panel,
    _stat_card,
    _translation_panel,
)

LOG = logging.getLogger("osint_local.web")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class AskManager:
    """Run one local Q&A job in the background so the browser request stays short."""

    def __init__(self, pipeline: LocalPipeline) -> None:
        self.pipeline = pipeline
        self._lock = threading.RLock()
        self._state = {
            "status": "idle",
            "question": "",
            "message": "Ready",
            "html": "",
            "error": "",
            "model": "",
            "mode": "quick",
        }

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, question: str, analysis_mode: str = "quick") -> dict:
        question = question.strip()
        analysis_mode = str(analysis_mode or "quick").strip().casefold()
        if not question:
            raise ValueError("Question is empty")
        if analysis_mode not in ASK_MODES:
            raise ValueError("Unknown Ask mode")
        with self._lock:
            if self._state.get("status") == "running":
                raise ActionBusyError("A question is already being processed")
            self._state = {
                "status": "running",
                "question": question,
                "message": "Ищу релевантные фрагменты…",
                "html": "",
                "error": "",
                "model": "",
                "mode": analysis_mode,
            }
            initial = dict(self._state)
            threading.Thread(
                target=self._worker,
                args=(question, analysis_mode),
                name="osint-local-ask",
                daemon=True,
            ).start()
            return initial

    def _progress(self, stage: str) -> None:
        messages = {
            "searching": "Ищу релевантные фрагменты…",
            "reviewing": "Объединяю и отбираю лучшие источники…",
            "generating": "Ollama формирует ответ…",
            "done": "Готово",
        }
        with self._lock:
            if self._state.get("status") == "running":
                self._state["message"] = messages.get(stage, stage)

    def _worker(self, question: str, analysis_mode: str) -> None:
        try:
            result = ask_documents(
                self.pipeline.db,
                question,
                self.pipeline.settings.search,
                self.pipeline.settings.qa,
                analysis_mode=analysis_mode,
                progress=self._progress,
            )
        except RuntimeError as exc:
            fallback = []
            try:
                fallback = search_chunks(
                    self.pipeline.db,
                    question,
                    self.pipeline.settings.search,
                    limit=int(self.pipeline.settings.qa.get("top_k", 8)),
                    mode="auto",
                )
            except RuntimeError:
                fallback = []
            with self._lock:
                self._state.update(
                    status="failed",
                    message="Не удалось получить ответ",
                    error=str(exc),
                    html=_qa_answer(None, str(exc), fallback),
                )
            return
        except Exception as exc:  # defensive boundary for the background worker
            message = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._state.update(
                    status="failed",
                    message="Не удалось получить ответ",
                    error=message,
                    html=_qa_answer(None, message, []),
                )
            return

        with self._lock:
            self._state.update(
                status="succeeded",
                message="Готово",
                error="",
                model=result.model,
                mode=result.mode,
                html=_qa_answer(result),
            )


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, pipeline: LocalPipeline, *, folder_opener=open_folder, folder_picker=pick_folder, start_background: bool = False):
        super().__init__(address, DashboardHandler)
        self.pipeline = pipeline
        self.settings = pipeline.settings
        self.actions = ActionManager(pipeline)
        self.ask = AskManager(pipeline)
        self.csrf_token = secrets.token_urlsafe(32)
        self.folder_opener = folder_opener
        self.folder_picker = folder_picker
        self.background = None
        if start_background and bool(self.settings.background.get("enabled", True)):
            self.background = BackgroundLoop(
                self.actions,
                interval_seconds=int(self.settings.background.get("interval_seconds", 120)),
                initial_delay=int(self.settings.background.get("initial_delay_seconds", 3)),
            )
            self.background.start()

    def server_close(self) -> None:
        if self.background is not None:
            self.background.stop()
        super().server_close()


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        try:
            if path == "/":
                self._dashboard(query)
            elif path == "/search":
                self._search_page(query)
            elif path == "/documents":
                self._documents_page(query)
            elif path == "/ask":
                self._ask_page(query)
            elif path == "/settings":
                self._settings_page(query)
            elif path == "/system":
                self._system_page(query)
            elif path.startswith("/documents/"):
                self._document_page(path.split("/", 2)[2], query)
            elif path.startswith("/source/"):
                self._source(path.split("/", 2)[2], head_only=False)
            elif path.startswith("/translation/"):
                self._translation_file(path)
            elif path == "/api/search":
                self._api_search(query)
            elif path == "/api/ask-status":
                self._json(self.server.ask.snapshot())
            elif path == "/api/stats":
                self._json(self._stats_payload())
            elif path == "/api/system":
                self._json(self._system_payload())
            elif path == "/api/activity":
                self._json(self._activity_payload())
            else:
                self._error(HTTPStatus.NOT_FOUND, "Page not found")
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        except Exception as exc:  # pragma: no cover - defensive server boundary
            LOG.exception("Web request failed: %s", self.path)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Internal error: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/actions/maintenance":
                self._start_action("maintenance")
            elif path == "/actions/scan":
                self._start_action("scan")
            elif path == "/actions/index":
                self._start_action("index")
            elif path == "/actions/open-folder":
                self._open_folder_action()
            elif path == "/actions/open-translations":
                self._open_translations_action()
            elif path == "/actions/translate":
                self._translate_action()
            elif path == "/api/ask":
                self._start_ask_action()
            elif path == "/settings/input-dir":
                self._set_input_dir_action()
            elif path == "/settings/performance":
                self._set_performance_action()
            elif path == "/settings/pick-folder":
                self._pick_folder_action()
            else:
                self._error(HTTPStatus.NOT_FOUND, "Page not found")
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        except Exception as exc:  # pragma: no cover - defensive server boundary
            LOG.exception("Web POST failed: %s", self.path)
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Internal error: {exc}")

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path.startswith("/source/"):
            self._source(path.split("/", 2)[2], head_only=True)
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        LOG.info("%s - %s", self.client_address[0], fmt % args)

    @property
    def db(self):
        return self.server.pipeline.db

    @property
    def settings(self) -> Settings:
        return self.server.settings

    def _dashboard(self, query: dict[str, list[str]]) -> None:
        q = _first(query, "q")
        if q:
            self._search_page(query)
            return
        stats = self._stats_payload()
        action = self.server.actions.snapshot()
        recent = self.db.list_documents(limit=12)
        semantic_available = importlib.util.find_spec("sentence_transformers") is not None
        semantic_ready = bool(stats["chunks"] and stats["embedding_count"] >= stats["chunks"])
        body = [_hero()]
        if not bool(self.settings.ui.get("setup_complete", True)):
            body.append(_setup_panel(self.server.csrf_token, self.settings.input_dir))
        body.extend([
            _action_panel(
                self.server.csrf_token,
                action,
                semantic_available=semantic_available,
                semantic_ready=semantic_ready,
                semantic_enabled=bool(self.settings.search.get("semantic_enabled", True)),
                embedding_count=stats["embedding_count"],
                chunk_count=stats["chunks"],
                input_dir=self.settings.input_dir,
                background_enabled=bool(self.settings.background.get("enabled", True)),
                background_interval=int(self.settings.background.get("interval_seconds", 60)),
            ),
            '<section class="stats-grid">',
            _stat_card("Documents", stats["documents"]),
            _stat_card("Semantic index", "Ready" if semantic_ready else f'{stats["embedding_count"]}/{stats["chunks"]}'),
            _stat_card("Russian translations", stats["translations_ru"]),
            _stat_card("Errors", stats["errors"]),
            "</section>",
            _search_form("", "auto", 10),
            '<div class="two-col">',
            '<section class="panel"><div class="panel-head"><h2>Categories</h2></div>',
            _category_list(stats["categories"]),
            "</section>",
            '<section class="panel"><div class="panel-head"><h2>Recent documents</h2>'
            '<a href="/documents">View all</a></div>',
            _document_cards(recent, self.db),
            "</section></div>",
            _activity_details(action, self.db.recent_errors(limit=6)),
        ])
        self._html("OSINT Local", "".join(body))

    def _search_page(self, query: dict[str, list[str]]) -> None:
        q = _first(query, "q").strip()
        mode = _first(query, "mode") or "auto"
        if mode not in {"auto", "hybrid", "semantic", "lexical"}:
            mode = "auto"
        try:
            limit = min(100, max(1, int(_first(query, "limit") or 10)))
        except ValueError:
            limit = 10

        hits = []
        error = ""
        if q:
            try:
                hits = search_chunks(self.db, q, self.settings.search, limit=limit, mode=mode)
            except RuntimeError as exc:
                error = str(exc)

        content = [_page_header("Search", "Search extracted document chunks locally."), _search_form(q, mode, limit)]
        if error:
            content.append(f'<div class="alert">{_e(error)}</div>')
        elif q:
            content.append(f'<div class="result-count">{len(hits)} result(s) for <strong>{_e(q)}</strong></div>')
            content.append('<section class="results">')
            if not hits:
                content.append('<div class="empty">No matches. Try lexical mode or a broader query.</div>')
            for hit in hits:
                content.append(_search_hit(hit))
            content.append("</section>")
        self._html(f"Search — {q}" if q else "Search", "".join(content))

    def _ask_page(self, query: dict[str, list[str]]) -> None:
        question = _first(query, "q").strip()
        analysis_mode = _first(query, "mode").strip().casefold() or "quick"
        if analysis_mode not in ASK_MODES:
            analysis_mode = "quick"
        body = [
            _page_header("Ask", "Ask a local model about the entire indexed document library."),
            _ask_form(question, self.server.csrf_token, analysis_mode),
        ]
        self._html("Ask", "".join(body))

    def _documents_page(self, query: dict[str, list[str]]) -> None:
        domain = _first(query, "domain").strip() or None
        try:
            page = max(1, int(_first(query, "page") or 1))
        except ValueError:
            page = 1
        per_page = 50
        offset = (page - 1) * per_page
        docs = self.db.list_documents(limit=per_page, offset=offset, domain=domain)
        total = self.db.document_count(domain=domain)
        categories = self.db.category_counts()

        title = f"Documents — {domain}" if domain else "Documents"
        body = [_page_header(title, f"{total} indexed document(s)."), _domain_filter(categories, domain)]
        body.append('<section class="panel">')
        body.append(_document_table(docs, self.db))
        body.append(_pagination(page, per_page, total, domain))
        body.append("</section>")
        self._html(title, "".join(body))

    def _settings_page(self, query: dict[str, list[str]]) -> None:
        stats = self._stats_payload()
        semantic_available = importlib.util.find_spec("sentence_transformers") is not None
        body = [
            _page_header("Settings", "A few local settings; everything else stays automatic."),
            _settings_panel(
                self.server.csrf_token,
                self.settings.input_dir,
                self.settings.workspace_dir,
                self.settings.translations_dir,
                semantic_available=semantic_available,
                semantic_enabled=bool(self.settings.search.get("semantic_enabled", True)),
                embedding_count=stats["embedding_count"],
                chunk_count=stats["chunks"],
                background_enabled=bool(self.settings.background.get("enabled", True)),
                background_interval=int(self.settings.background.get("interval_seconds", 120)),
                passive_translation=bool(self.settings.translation.get("passive_enabled", True)),
                qa_base_url=str(self.settings.qa.get("base_url") or "http://127.0.0.1:11434"),
                performance_profile=str(self.settings.performance.get("profile") or "economy"),
                performance_profiles=PERFORMANCE_PROFILES,
            ),
        ]
        self._html("Settings", "".join(body))

    def _system_page(self, query: dict[str, list[str]]) -> None:
        status = self._system_payload()
        body = [
            _page_header("System", "Local processing status, queues and runtime dependencies."),
            _system_panel(status, self.server.csrf_token),
            _activity_details(self.server.actions.snapshot(), self.db.recent_errors(limit=8)),
        ]
        self._html("System", "".join(body))

    def _document_page(self, sha256: str, query: dict[str, list[str]]) -> None:
        if not SHA_RE.fullmatch(sha256):
            self._error(HTTPStatus.NOT_FOUND, "Document not found")
            return
        doc = self.db.get_document(sha256)
        if not doc:
            self._error(HTTPStatus.NOT_FOUND, "Document not found")
            return
        classes = self.db.get_classifications(sha256)
        chunks = self.db.chunks_for_document(sha256, limit=1000)
        source_url = f"/source/{quote(sha256)}"
        metadata = _safe_json(doc["metadata_json"])
        try:
            requested_page = int(_first(query, "page")) if _first(query, "page") else None
        except ValueError:
            requested_page = None
        reader = load_reader(self.settings, self.db, sha256, requested_page)

        body = [
            _page_header(doc["source_path"], f"SHA-256 {sha256[:16]}…"),
            '<div class="doc-actions">',
            f'<a class="button" href="{source_url}" target="_blank" rel="noreferrer">Open source file</a>',
            '<a class="button secondary" href="/documents">Back to documents</a>',
            "</div>",
            '<section class="stats-grid doc-stats">',
            _stat_card("Status", doc["status"]),
            _stat_card("Text chars", doc["text_chars"]),
            _stat_card("Chunks", len(chunks)),
            _stat_card("Method", doc["extraction_method"] or "—"),
            "</section>",
            '<section class="panel"><div class="panel-head"><h2>Classifications</h2></div>',
            _classification_badges(classes),
            "</section>",
            '<section class="panel"><div class="panel-head"><h2>Metadata</h2></div>',
            _metadata_grid(metadata, doc),
            "</section>",
            _reader_panel(sha256, reader, source_url),
            _translation_panel(
                self.server.csrf_token,
                sha256,
                self.db.list_translations(sha256),
                available=argos_available(),
                pairs=installed_pairs() if argos_available() else set(),
                action=self.server.actions.snapshot(),
            ),
            '<section class="panel"><div class="panel-head"><h2>Extracted chunks</h2></div>',
        ]
        if not chunks:
            body.append('<div class="empty">No chunks stored for this document. Use Scan on the home page.</div>')
        for chunk in chunks:
            body.append(_chunk_card(chunk, source_url))
        body.append("</section>")
        self._html(doc["source_path"], "".join(body))

    def _api_search(self, query: dict[str, list[str]]) -> None:
        q = _first(query, "q").strip()
        mode = _first(query, "mode") or "auto"
        try:
            limit = min(100, max(1, int(_first(query, "limit") or 10)))
        except ValueError:
            limit = 10
        if not q:
            self._json({"query": q, "results": []})
            return
        try:
            hits = search_chunks(self.db, q, self.settings.search, limit=limit, mode=mode)
        except (RuntimeError, ValueError) as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._json({"query": q, "mode": mode, "results": [asdict(hit) for hit in hits]})

    def _stats_payload(self) -> dict:
        raw = self.db.stats()
        model = str(self.settings.search.get("model") or "")
        return {
            "documents": self.db.document_count(),
            "statuses": raw["statuses"],
            "chunks": raw["chunks"],
            "embedding_count": raw["embeddings"].get(model, 0),
            "embedding_model": model,
            "translations_ru": int(raw.get("translations_ru", 0)),
            "errors": int(raw.get("errors", 0)),
            "categories": self.db.category_counts(),
        }

    def _system_payload(self) -> dict:
        stats = self._stats_payload()
        semantic_available = importlib.util.find_spec("sentence_transformers") is not None
        pairs = installed_pairs() if argos_available() else set()
        queue = translation_queue_status(
            self.settings,
            self.db,
            available_pairs=pairs,
            limit=1000,
        )
        try:
            models = ollama_models(
                str(self.settings.qa.get("base_url") or "http://127.0.0.1:11434"),
                timeout=0.75,
            )
            ollama_reachable = True
            ollama_error = ""
        except RuntimeError as exc:
            models = []
            ollama_reachable = False
            ollama_error = str(exc)
        profile = str(self.settings.performance.get("profile") or "economy")
        profile_info = PERFORMANCE_PROFILES.get(profile, {})
        return {
            **stats,
            "semantic_available": semantic_available,
            "index_pending": max(0, int(stats["chunks"]) - int(stats["embedding_count"])),
            "translation_queue": queue,
            "argos_available": argos_available(),
            "ollama_reachable": ollama_reachable,
            "ollama_error": ollama_error,
            "ollama_models": models,
            "ollama_configured_model": str(self.settings.qa.get("model") or ""),
            "tesseract": shutil.which("tesseract"),
            "background_enabled": bool(self.settings.background.get("enabled", True)),
            "background_interval": int(self.settings.background.get("interval_seconds", 60)),
            "performance_profile": profile,
            "performance_label": profile_info.get("label", profile.title()),
            "action": self.server.actions.snapshot(),
        }

    def _activity_payload(self) -> dict:
        return {
            "action": self.server.actions.snapshot(),
            "stats": self._stats_payload(),
            "errors": self.db.recent_errors(limit=6),
        }

    def _start_action(self, kind: str) -> None:
        data = self._form_data()
        if not self._check_csrf(data):
            self._action_response(
                {"error": "Invalid action token. Refresh the page and try again."},
                status=HTTPStatus.FORBIDDEN,
            )
            return
        try:
            if kind == "maintenance":
                action = self.server.actions.start_maintenance()
            elif kind == "scan":
                action = self.server.actions.start_scan()
            elif kind == "index":
                if importlib.util.find_spec("sentence_transformers") is None:
                    self._action_response(
                        {"error": "Semantic search is not installed. Install the optional search dependencies first."},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                action = self.server.actions.start_index()
            else:
                self._action_response({"error": "Unknown action"}, status=HTTPStatus.NOT_FOUND)
                return
        except ActionBusyError as exc:
            self._action_response({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            return
        self._action_response({"action": action}, status=HTTPStatus.ACCEPTED)

    def _start_ask_action(self) -> None:
        data = self._form_data()
        if not self._check_csrf(data):
            self._json({"error": "Invalid action token. Refresh the page and try again."}, status=HTTPStatus.FORBIDDEN)
            return
        question = data.get("q", "").strip()
        analysis_mode = data.get("mode", "quick").strip().casefold()
        if not question:
            self._json({"error": "Question is empty"}, status=HTTPStatus.BAD_REQUEST)
            return
        if analysis_mode not in ASK_MODES:
            self._json({"error": "Unknown Ask mode"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            state = self.server.ask.start(question, analysis_mode)
        except ActionBusyError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            return
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._json(state, status=HTTPStatus.ACCEPTED)

    def _check_csrf(self, data: dict[str, str]) -> bool:
        token = data.get("csrf", "")
        return bool(token and secrets.compare_digest(token, self.server.csrf_token))

    def _open_folder_action(self) -> None:
        data = self._form_data()
        if not self._check_csrf(data):
            self._action_response({"error": "Invalid action token. Refresh the page and try again."}, status=HTTPStatus.FORBIDDEN)
            return
        try:
            self.server.folder_opener(self.settings.input_dir)
        except Exception as exc:
            self._action_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._action_response({"ok": True}, status=HTTPStatus.OK)

    def _open_translations_action(self) -> None:
        data = self._form_data()
        if not self._check_csrf(data):
            self._action_response({"error": "Invalid action token. Refresh the page and try again."}, status=HTTPStatus.FORBIDDEN)
            return
        self.settings.translations_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.server.folder_opener(self.settings.translations_dir)
        except Exception as exc:
            self._action_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._action_response({"ok": True}, status=HTTPStatus.OK)

    def _translate_action(self) -> None:
        data = self._form_data()
        sha256 = data.get("sha256", "")
        if not self._check_csrf(data):
            self._action_response({"error": "Invalid action token. Refresh the page and try again."}, status=HTTPStatus.FORBIDDEN)
            return
        if not SHA_RE.fullmatch(sha256) or not self.db.get_document(sha256):
            self._action_response({"error": "Document not found"}, status=HTTPStatus.NOT_FOUND)
            return
        source_lang = data.get("source_lang", "auto")
        target_lang = "ru"
        if source_lang not in {"auto", "en", "uk"}:
            self._action_response({"error": "Translation is limited to English/Ukrainian → Russian"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not argos_available():
            self._action_response({"error": "Offline translation is not installed. Install: pip install -e '.[translate]'"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            action = self.server.actions.start_translate(sha256, source_lang, target_lang)
        except ActionBusyError as exc:
            self._action_response({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            return
        if self.headers.get("X-Requested-With") == "fetch":
            self._json({"action": action}, status=HTTPStatus.ACCEPTED)
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/documents/{sha256}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _set_performance_action(self) -> None:
        data = self._form_data()
        if not self._check_csrf(data):
            self._action_response(
                {"error": "Invalid action token. Refresh the page and try again."},
                status=HTTPStatus.FORBIDDEN,
            )
            return
        profile = data.get("profile", "").strip().casefold()
        try:
            patch = performance_profile_patch(profile)
        except ValueError as exc:
            self._action_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        update_config(self.settings.config_path, patch)
        settings = load_settings(self.settings.config_path)
        self.server.pipeline.settings = settings
        self.server.settings = settings
        if self.server.background is not None:
            self.server.background.interval_seconds = max(
                15, int(settings.background.get("interval_seconds", 60))
            )
        payload = {
            "ok": True,
            "profile": profile,
            "label": PERFORMANCE_PROFILES[profile]["label"],
        }
        if self.headers.get("X-Requested-With") == "fetch":
            self._json(payload, status=HTTPStatus.OK)
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/settings")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _set_input_dir_action(self) -> None:
        data = self._form_data()
        if not self._check_csrf(data):
            self._action_response({"error": "Invalid action token. Refresh the page and try again."}, status=HTTPStatus.FORBIDDEN)
            return
        raw = data.get("input_dir", "").strip()
        if not raw:
            self._action_response({"error": "Choose or enter a folder path."}, status=HTTPStatus.BAD_REQUEST)
            return
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (self.settings.project_root / path).resolve()
        else:
            path = path.resolve()
        if not path.is_dir():
            self._action_response({"error": f"Folder does not exist: {path}"}, status=HTTPStatus.BAD_REQUEST)
            return
        if self.server.actions.snapshot().get("status") == "running":
            self._action_response({"error": "Wait for the current action to finish before changing folders."}, status=HTTPStatus.CONFLICT)
            return
        self._apply_input_dir(path)
        self._action_response({"ok": True, "input_dir": str(path)}, status=HTTPStatus.OK)

    def _pick_folder_action(self) -> None:
        data = self._form_data()
        if not self._check_csrf(data):
            self._action_response({"error": "Invalid action token. Refresh the page and try again."}, status=HTTPStatus.FORBIDDEN)
            return
        if self.server.actions.snapshot().get("status") == "running":
            self._action_response({"error": "Wait for the current action to finish before changing folders."}, status=HTTPStatus.CONFLICT)
            return
        try:
            path = self.server.folder_picker(self.settings.input_dir)
        except Exception as exc:
            self._action_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if path is None:
            self._action_response({"ok": True, "cancelled": True}, status=HTTPStatus.OK)
            return
        self._apply_input_dir(Path(path).resolve())
        self._action_response({"ok": True, "input_dir": str(path)}, status=HTTPStatus.OK)

    def _apply_input_dir(self, path: Path) -> None:
        update_config(
            self.settings.config_path,
            {"input_dir": str(path), "ui": {"setup_complete": True}},
        )
        settings = load_settings(self.settings.config_path)
        settings.input_dir.mkdir(parents=True, exist_ok=True)
        self.server.pipeline.settings = settings
        self.server.settings = settings
        if bool(settings.background.get("enabled", True)):
            try:
                if self.server.actions.snapshot().get("status") != "running":
                    self.server.actions.start_maintenance()
            except ActionBusyError:
                pass

    def _form_data(self) -> dict[str, str]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 0 or length > 64 * 1024:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed = parse_qs(raw, keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _action_response(self, data: dict, *, status: HTTPStatus) -> None:
        if self.headers.get("X-Requested-With") == "fetch":
            self._json(data, status=status)
            return
        if status.value < 400:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self._html(str(status.value), _page_header(str(status.value), str(data.get("error") or "Action failed")), status=status)

    def _translation_file(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "translation":
            self._error(HTTPStatus.NOT_FOUND, "Translation not found")
            return
        _, sha256, source_lang, target_lang = parts
        if not SHA_RE.fullmatch(sha256):
            self._error(HTTPStatus.NOT_FOUND, "Translation not found")
            return
        row = self.db.get_translation(sha256, source_lang, target_lang)
        if not row:
            self._error(HTTPStatus.NOT_FOUND, "Translation not found")
            return
        file_path = Path(row["output_path"]).expanduser().resolve()
        try:
            file_path.relative_to(self.settings.translations_dir.resolve())
        except ValueError:
            self._error(HTTPStatus.FORBIDDEN, "Invalid translation path")
            return
        if not file_path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Translation file is missing")
            return
        self._send_file(file_path, head_only=False)

    def _source(self, sha256: str, *, head_only: bool) -> None:
        if not SHA_RE.fullmatch(sha256):
            self._error(HTTPStatus.NOT_FOUND, "File not found")
            return
        doc = self.db.get_document(sha256)
        if not doc:
            self._error(HTTPStatus.NOT_FOUND, "File not found")
            return
        path = (self.settings.input_dir / doc["source_path"]).resolve()
        try:
            path.relative_to(self.settings.input_dir.resolve())
        except ValueError:
            self._error(HTTPStatus.FORBIDDEN, "Invalid source path")
            return
        if not path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Source file is missing on disk")
            return
        self._send_file(path, head_only=head_only)

    def _send_file(self, path: Path, *, head_only: bool) -> None:
        size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, max(0, size - 1)
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header and size:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            first, last = match.groups()
            if first:
                start = int(first)
                end = int(last) if last else size - 1
            elif last:
                suffix = int(last)
                start = max(0, size - suffix)
                end = size - 1
            if start >= size or end < start:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = HTTPStatus.PARTIAL_CONTENT

        length = 0 if size == 0 else end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(path.name)}")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only or not length:
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _html(self, title: str, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = _layout(title, body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, data, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._html(str(status.value), _page_header(str(status.value), message), status=status)


def create_server(
    pipeline: LocalPipeline,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    folder_opener=open_folder,
    folder_picker=pick_folder,
    start_background: bool = False,
) -> DashboardServer:
    return DashboardServer(
        (host, port), pipeline, folder_opener=folder_opener, folder_picker=folder_picker,
        start_background=start_background,
    )


def serve(
    pipeline: LocalPipeline,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    server = create_server(pipeline, host, port, start_background=True)
    stop_file = pipeline.settings.project_root / ".osint-stop"
    try:
        stop_file.unlink()
    except FileNotFoundError:
        pass

    stop_watcher_done = threading.Event()

    def watch_stop_file() -> None:
        while not stop_watcher_done.wait(0.5):
            if not stop_file.exists():
                continue
            try:
                stop_file.unlink()
            except OSError:
                pass
            server.shutdown()
            return

    threading.Thread(
        target=watch_stop_file,
        name="osint-local-stop-watcher",
        daemon=True,
    ).start()

    actual_host, actual_port = server.server_address[:2]
    browser_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    url = f"http://{browser_host}:{actual_port}"
    print(f"OSINT Local Web UI: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop_watcher_done.set()
        try:
            stop_file.unlink()
        except FileNotFoundError:
            pass
        server.server_close()

