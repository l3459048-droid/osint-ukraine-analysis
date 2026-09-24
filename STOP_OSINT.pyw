from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PIDFILE = ROOT / ".osint-server.pid"
STOPFILE = ROOT / ".osint-stop"
URL = "http://127.0.0.1:8080"


def server_ready() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=0.4) as response:
            return response.status < 500
    except Exception:
        return False


def main() -> None:
    STOPFILE.write_text("stop\n", encoding="ascii")

    for _ in range(20):
        if not server_ready():
            break
        time.sleep(0.5)

    if server_ready() and PIDFILE.is_file():
        try:
            pid = int(PIDFILE.read_text(encoding="ascii").strip())
        except Exception:
            pid = 0
        if pid > 0 and os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                check=False,
            )

    for path in (PIDFILE, STOPFILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
