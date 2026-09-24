from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .pipeline import LocalPipeline

LOG = logging.getLogger("osint_local")

class IngestHandler(FileSystemEventHandler):
    def __init__(self, pipeline: LocalPipeline, settle_seconds: float = 1.0):
        self.pipeline = pipeline
        self.settle_seconds = settle_seconds
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(Path(event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self._schedule(Path(event.dest_path))

    def _schedule(self, path: Path) -> None:
        if path.suffix.lower() not in self.pipeline.settings.allowed_extensions:
            return
        key = str(path.resolve())
        with self._lock:
            previous = self._timers.pop(key, None)
            if previous:
                previous.cancel()
            timer = threading.Timer(self.settle_seconds, self._process, args=(path, key))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _process(self, path: Path, key: str) -> None:
        try:
            last = None
            stable = 0
            for _ in range(10):
                if not path.exists():
                    return
                stat = path.stat()
                current = (stat.st_size, stat.st_mtime_ns)
                stable = stable + 1 if current == last else 0
                if stable >= 2:
                    break
                last = current
                time.sleep(0.5)
            result = self.pipeline.process_file(path)
            LOG.info("Watcher: %s -> %s", path.name, result.status)
        finally:
            with self._lock:
                self._timers.pop(key, None)


def watch(pipeline: LocalPipeline) -> None:
    handler = IngestHandler(pipeline)
    observer = Observer()
    observer.schedule(handler, str(pipeline.settings.input_dir), recursive=True)
    observer.start()
    LOG.info("Watching %s", pipeline.settings.input_dir)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("Stopping watcher")
    finally:
        observer.stop()
        observer.join()
