from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

from .config import load_settings, write_default_config
from .pipeline import LocalPipeline
from .watcher import watch


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
    parser = argparse.ArgumentParser(description="Local-first OSINT document ingestion")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create config and local directories")
    scan = sub.add_parser("scan", help="Process all supported files in the input directory")
    scan.add_argument("--force", action="store_true")
    sub.add_parser("watch", help="Continuously watch the input directory")
    sub.add_parser("status", help="Show processing statistics")
    sub.add_parser("doctor", help="Check local runtime and optional OCR")

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
    pipeline = LocalPipeline(settings)
    try:
        if args.command == "scan":
            results = pipeline.scan(force=args.force)
            counts: dict[str, int] = {}
            for r in results:
                counts[r.status] = counts.get(r.status, 0) + 1
            print(json.dumps(counts, ensure_ascii=False, indent=2))
            return 1 if counts.get("error", 0) else 0
        if args.command == "watch":
            pipeline.scan()
            watch(pipeline)
            return 0
        if args.command == "status":
            print(json.dumps(pipeline.db.stats(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "doctor":
            info = {
                "input_dir_exists": settings.input_dir.exists(),
                "workspace_writable": _writable(settings.workspace_dir),
                "tesseract": shutil.which("tesseract"),
                "ocr_enabled": bool(settings.ocr.get("enabled", True)),
            }
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0 if info["workspace_writable"] else 1
    finally:
        pipeline.close()
    return 0


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
