from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .chunking import build_chunks
from .classifier import classify
from .config import Settings
from .db import Database
from .extractors import extract
from .translation import detect_language

LOG = logging.getLogger("osint_local")


@dataclass
class ProcessResult:
    path: Path
    status: str
    sha256: str | None = None
    message: str = ""


class LocalPipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._prepare_dirs()
        self.db = Database(settings.db_path)
        self._backfill_languages()

    def close(self) -> None:
        self.db.close()

    def scan(
        self,
        force: bool = False,
        progress: Callable[[int, int, ProcessResult | None], None] | None = None,
    ) -> list[ProcessResult]:
        paths = [
            path
            for path in sorted(self.settings.input_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in self.settings.allowed_extensions
        ]
        results: list[ProcessResult] = []
        if progress:
            progress(0, len(paths), None)
        for index, path in enumerate(paths, start=1):
            result = self.process_file(path, force=force)
            results.append(result)
            if progress:
                progress(index, len(paths), result)
        return results

    def process_file(self, path: str | Path, force: bool = False) -> ProcessResult:
        path = Path(path).expanduser().resolve()
        if not self._is_inside(path, self.settings.input_dir):
            return ProcessResult(path, "ignored", message="outside input directory")
        if not path.is_file() or path.suffix.lower() not in self.settings.allowed_extensions:
            return ProcessResult(path, "ignored", message="unsupported file")

        stat = path.stat()
        source_path = str(path.relative_to(self.settings.input_dir))
        if not force and self.db.find_current_source(source_path, stat.st_size, stat.st_mtime_ns):
            return ProcessResult(path, "skipped", message="unchanged")

        sha256 = sha256_file(path)
        existing = self.db.find_by_hash(sha256)
        if (
            existing
            and existing["status"] == "done"
            and int(existing["pipeline_version"] or 1) >= 2
            and not force
        ):
            return ProcessResult(path, "duplicate", sha256, "content already processed")

        self.db.upsert_processing(
            sha256=sha256,
            source_path=source_path,
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            extension=path.suffix.lower(),
        )

        try:
            extracted = extract(path, self.settings.ocr)
            classes = classify(extracted.text, self.settings.classification)
            language = detect_language(extracted.text) if extracted.text.strip() else None
            chunks = build_chunks(extracted.text, self.settings.search)
            now = datetime.now(timezone.utc).isoformat()
            page_metadata = [
                {key: value for key, value in page.items() if key != "text"}
                for page in extracted.pages
            ]
            metadata = {
                "document_id": sha256,
                "source_path": source_path,
                "source_size": stat.st_size,
                "source_mtime_ns": stat.st_mtime_ns,
                "extension": path.suffix.lower(),
                "processed_at": now,
                "extraction_method": extracted.method,
                "text_chars": len(extracted.text),
                "language": language,
                "pages": page_metadata,
                "chunks": len(chunks),
                "classifications": [
                    {"domain": domain, "score": score} for domain, score in classes
                ],
            }

            self._atomic_write_text(self.settings.text_dir / f"{sha256}.txt", extracted.text)
            self._atomic_write_text(
                self.settings.metadata_dir / f"{sha256}.json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
            )
            self.db.mark_done(
                sha256=sha256,
                extraction_method=extracted.method,
                text_chars=len(extracted.text),
                processed_at=now,
                metadata_json=json.dumps(metadata, ensure_ascii=False),
                language=language,
                classifications=classes,
                chunks=chunks,
            )

            if bool(self.settings.search.get("auto_embed", False)):
                from .search import build_embeddings

                build_embeddings(
                    self.db,
                    self.settings.search,
                    document_sha256=sha256,
                )

            LOG.info("Processed %s -> %s (%s chunks)", source_path, sha256[:12], len(chunks))
            return ProcessResult(path, "processed", sha256)
        except Exception as exc:
            self.db.mark_error(sha256, f"{type(exc).__name__}: {exc}")
            LOG.exception("Failed processing %s", source_path)
            return ProcessResult(path, "error", sha256, str(exc))

    def _backfill_languages(self) -> None:
        for row in self.db.documents_missing_language(limit=5000):
            text_path = self.settings.text_dir / f"{row['sha256']}.txt"
            if not text_path.is_file():
                continue
            text = text_path.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                continue
            self.db.update_document_language(row["sha256"], detect_language(text))

    def _prepare_dirs(self) -> None:
        for p in (
            self.settings.input_dir,
            self.settings.workspace_dir,
            self.settings.text_dir,
            self.settings.metadata_dir,
            self.settings.logs_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _is_inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root.resolve())
            return True
        except ValueError:
            return False


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
