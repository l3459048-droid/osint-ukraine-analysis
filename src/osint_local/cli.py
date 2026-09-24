from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import shutil
from dataclasses import asdict
from pathlib import Path

from .config import load_settings, update_config, write_default_config
from .pipeline import LocalPipeline
from .search import build_embeddings, search_chunks
from .translation import argos_available, installed_pairs, translate_document


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
    sub.add_parser("status", help="Show processing and index statistics")
    sub.add_parser("doctor", help="Check local runtime, OCR and semantic-search dependencies")

    index = sub.add_parser("index", help="Build local semantic embeddings for indexed chunks")
    index.add_argument("--force", action="store_true", help="Rebuild embeddings even if they exist")

    search = sub.add_parser("search", help="Search indexed document chunks")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--mode", choices=["auto", "semantic", "lexical"], default="auto")
    search.add_argument("--json", action="store_true", dest="as_json")

    translate_cmd = sub.add_parser("translate", help="Translate one processed document offline")
    translate_cmd.add_argument("sha256")
    translate_cmd.add_argument("--from", dest="source_lang", choices=["auto", "en", "ru", "uk"], default="auto")
    translate_cmd.add_argument("--to", dest="target_lang", choices=["en", "ru", "uk"], required=True)

    serve_cmd = sub.add_parser("serve", help="Run the local Web UI")
    serve_cmd.add_argument("--host", default=None, help="Bind address (default from config)")
    serve_cmd.add_argument("--port", type=int, default=None, help="Port (default from config)")
    serve_cmd.add_argument("--no-open", action="store_true", help="Do not open a browser automatically")
    serve_cmd.add_argument("--allow-network", action="store_true", help="Allow binding beyond localhost")

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

    if args.command == "serve" and not config_path.exists():
        write_default_config(config_path)
        update_config(config_path, {"ui": {"setup_complete": False}})

    settings = load_settings(config_path)
    configure_logging(settings.logs_dir, args.verbose)
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
            print(json.dumps(pipeline.db.stats(), ensure_ascii=False, indent=2))
            return 0

        if args.command == "index":
            try:
                count = build_embeddings(pipeline.db, settings.search, force=args.force)
            except RuntimeError as exc:
                print(str(exc))
                return 2
            print(json.dumps({"embedded_chunks": count, "model": settings.search.get("model")}, indent=2))
            return 0

        if args.command == "search":
            try:
                hits = search_chunks(
                    pipeline.db,
                    args.query,
                    settings.search,
                    limit=args.limit,
                    mode=args.mode,
                )
            except RuntimeError as exc:
                print(str(exc))
                return 2
            if args.as_json:
                print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
            else:
                _print_hits(hits)
            return 0

        if args.command == "translate":
            try:
                result = translate_document(
                    settings, pipeline.db, args.sha256,
                    source_lang=args.source_lang, target_lang=args.target_lang,
                )
            except RuntimeError as exc:
                print(str(exc))
                return 2
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "serve":
            from .web import serve

            host = args.host or str(settings.web.get("host", "127.0.0.1"))
            port = args.port if args.port is not None else int(settings.web.get("port", 8080))
            if host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_network:
                print("Refusing non-local bind without --allow-network. Use --host 127.0.0.1 for local-only access.")
                return 2
            open_browser = bool(settings.web.get("open_browser", True)) and not args.no_open
            serve(pipeline, host=host, port=port, open_browser=open_browser)
            return 0

        if args.command == "doctor":
            model = str(settings.search.get("model"))
            info = {
                "input_dir_exists": settings.input_dir.exists(),
                "workspace_writable": _writable(settings.workspace_dir),
                "tesseract": shutil.which("tesseract"),
                "ocr_enabled": bool(settings.ocr.get("enabled", True)),
                "sentence_transformers_installed": importlib.util.find_spec("sentence_transformers") is not None,
                "semantic_model": model,
                "semantic_embeddings": pipeline.db.embedding_count(model),
                "indexed_chunks": pipeline.db.chunk_count(),
                "web_host": str(settings.web.get("host", "127.0.0.1")),
                "web_port": int(settings.web.get("port", 8080)),
                "argos_translate_installed": argos_available(),
                "translation_pairs": [f"{a}->{b}" for a, b in sorted(installed_pairs())] if argos_available() else [],
                "translations_dir": str(settings.translations_dir),
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
        snippet = " ".join(hit.text.split())
        print(snippet[:900])
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
