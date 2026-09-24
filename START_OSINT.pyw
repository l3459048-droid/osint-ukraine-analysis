from __future__ import annotations

import os
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PIDFILE = ROOT / ".osint-server.pid"
OUTLOG = ROOT / ".osint-server.out.log"
ERRLOG = ROOT / ".osint-server.err.log"
URL = "http://127.0.0.1:8080"


def server_ready() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=0.5) as response:
            return response.status < 500
    except Exception:
        return False


def main() -> None:
    if server_ready():
        webbrowser.open(URL)
        return

    if not PYTHON.is_file():
        import tkinter.messagebox as messagebox
        messagebox.showerror(
            "OSINT Local",
            "Virtual environment not found. Run the project installation first.",
        )
        return

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    with OUTLOG.open("ab") as stdout, ERRLOG.open("ab") as stderr:
        process = subprocess.Popen(
            [str(PYTHON), "-m", "osint_local.cli", "serve", "--no-open"],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
            startupinfo=startupinfo,
            close_fds=True,
        )

    PIDFILE.write_text(str(process.pid), encoding="ascii")

    for _ in range(30):
        if server_ready():
            webbrowser.open(URL)
            return
        if process.poll() is not None:
            break
        time.sleep(0.5)

    import tkinter.messagebox as messagebox
    messagebox.showerror(
        "OSINT Local",
        "Server did not start. Check .osint-server.err.log in the project folder.",
    )


if __name__ == "__main__":
    main()
