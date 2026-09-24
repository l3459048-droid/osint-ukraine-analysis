from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .config import Settings
from .pipeline import LocalPipeline
from .search import search_chunks
from .web_ui import (
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
    _first,
    _safe_json,
    _search_form,
    _search_hit,
    _stat_card,
)

LOG = logging.getLogger("osint_local.web")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, pipeline: LocalPipeline):
        super().__init__(address, DashboardHandler)
        self.pipeline = pipeline
        self.settings = pipeline.settings


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
            elif path.startswith("/documents/"):
                self._document_page(path.split("/", 2)[2])
            elif path.startswith("/source/"):
                self._source(path.split("/", 2)[2], head_only=False)
            elif path == "/api/search":
                self._api_search(query)
            elif path == "/api/stats":
                self._json(self._stats_payload())
            else:
                self._error(HTTPStatus.NOT_FOUND, "Page not found")
        except BrokenPipeError:
            return
        except Exception as exc:  # pragma: no cover - defensive server boundary
            LOG.exception("Web request failed: %s", self.path)
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
        recent = self.db.list_documents(limit=12)
        body = [
            _hero(),
            '<section class="stats-grid">',
            _stat_card("Documents", stats["documents"]),
            _stat_card("Chunks", stats["chunks"]),
            _stat_card("Embeddings", stats["embedding_count"]),
            _stat_card("Categories", len(stats["categories"])),
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
        ]
        self._html("OSINT Local", "".join(body))

    def _search_page(self, query: dict[str, list[str]]) -> None:
        q = _first(query, "q").strip()
        mode = _first(query, "mode") or "auto"
        if mode not in {"auto", "semantic", "lexical"}:
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

    def _document_page(self, sha256: str) -> None:
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
            '<section class="panel"><div class="panel-head"><h2>Extracted chunks</h2></div>',
        ]
        if not chunks:
            body.append('<div class="empty">No chunks stored for this document. Run osint-local scan.</div>')
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
            "documents": raw["total"],
            "statuses": raw["statuses"],
            "chunks": raw["chunks"],
            "embedding_count": raw["embeddings"].get(model, 0),
            "embedding_model": model,
            "categories": self.db.category_counts(),
        }

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


def create_server(pipeline: LocalPipeline, host: str = "127.0.0.1", port: int = 8080) -> DashboardServer:
    return DashboardServer((host, port), pipeline)


def serve(
    pipeline: LocalPipeline,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    server = create_server(pipeline, host, port)
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
        server.server_close()

