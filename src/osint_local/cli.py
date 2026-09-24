from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import shutil
from dataclasses import asdict
from pathlib import Path

from .config import load_settings, write_default_config
from .pipeline import LocalPipeline
from .search import SearchIndex


def configure_logging(log_dir: Path | None = None, verbose: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "osint-local.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-first OSINT document ingestion and search")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create config and local directories")
    scan = sub.add_parser("scan", help="Process all supported files in the input directory")
    scan.add_argument("--force", action="store_true")
    sub.add_parser("watch", help="Continuously watch the input directory")
    sub.add_parser("status", help="Show processing and search-index statistics")
    sub.add_parser("doctor", help="Check OCR and semantic-search dependencies")

    index = sub.add_parser("index", help="Build/update local chunks and semantic embeddings")
    index.add_argument("--force", action="store_true")
    index.add_argument("--chunks-only", action="store_true")

    search = sub.add_parser("search", help="Search document chunks")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--mode", choices=["auto", "semantic", "lexical"], default="auto")
    search.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()
    config_path = Path(args.config).expanduser().resolve()

    if args.command == "init":
        write_default_config(config_path)
        settings = load_settings(config_path)
        pipeline = LocalPipeline(settings)
        pipeline.close()
        print(f"Config: {config_path}")
        print(f"Input:  {settings.input_dir}")
        print(f"Data:   {settings.workspace_dir}")
        return 0

    settings = load_settings(config_path)
    configure_logging(settings.logs_dir, args.verbose)

    if args.command == "index":
        with SearchIndex(settings) as search_index:
            chunk_stats = search_index.sync_chunks(force=args.force)
            embedded = 0
            if not args.chunks_only:
                try:
                    embedded = search_index.build_embeddings(force=args.force)
                except RuntimeError as exc:
                    print(str(exc))
                    print(json.dumps(chunk_stats, ensure_ascii=False, indent=2))
                    return 2
            print(json.dumps({**chunk_stats, "embedded_chunks": embedded}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "search":
        with SearchIndex(settings) as search_index:
            try:
                hits = search_index.search(args.query, limit=args.limit, mode=args.mode)
            except RuntimeError as exc:
                print(str(exc))
                return 2
            if args.as_json:
                print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
            else:
                _print_hits(hits)
        return 0

    pipeline = LocalPipeline(settings)
    try:
        if args.command == "scan":
            results = pipeline.scan(force=args.force)
            counts: dict[str, int] = {}
            for result in results:
                counts[result.status] = counts.get(result.status, 0) + 1
            print(json.dumps(counts, ensure_ascii=False, indent=2))
            return 1 if counts.get("error", 0) else 0

        if args.command == "watch":
            from .watcher import watch

            pipeline.scan()
            watch(pipeline)
            return 0

        if args.command == "status":
            with SearchIndex(settings) as search_index:
                status = {
                    "ingestion": pipeline.db.stats(),
                    "search": search_index.stats(),
                }
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0

        if args.command == "doctor":
            with SearchIndex(settings) as search_index:
                search_stats = search_index.stats()
            info = {
                "input_dir_exists": settings.input_dir.exists(),
                "workspace_writable": _writable(settings.workspace_dir),
                "tesseract": shutil.which("tesseract"),
                "ocr_enabled": bool(settings.ocr.get("enabled", True)),
                "sentence_transformers_installed": importlib.util.find_spec("sentence_transformers") is not None,
                "semantic_model": settings.search.get("model"),
                "search_index": search_stats,
            }
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0 if info["workspace_writable"] else 1
    finally:
        pipeline.close()
    return 0


def _print_hits(hits) -> None:
    if not hits:
        print("No matches.")
        return
    for index, hit in enumerate(hits, 1):
        location = hit.source_path
        if hit.page is not None:
            location += f" — page {hit.page}"
        print(f"[{index}] {hit.score:.4f} {hit.backend} | {location}")
        print(" ".join(hit.text.split())[:900])
        print()


def _writable(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
