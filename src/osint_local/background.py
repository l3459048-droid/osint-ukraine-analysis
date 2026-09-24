from __future__ import annotations

import threading

from .actions import ActionBusyError, ActionManager


class BackgroundLoop:
    """Periodically asks ActionManager for one serialized passive maintenance cycle."""

    def __init__(self, manager: ActionManager, *, interval_seconds: int = 120, initial_delay: int = 8):
        self.manager = manager
        self.interval_seconds = max(15, int(interval_seconds))
        self.initial_delay = max(1, int(initial_delay))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="osint-local-background", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        if self._stop.wait(self.initial_delay):
            return
        while not self._stop.is_set():
            try:
                if self.manager.snapshot().get("status") != "running":
                    self.manager.start_maintenance()
            except ActionBusyError:
                pass
            if self._stop.wait(self.interval_seconds):
                break
