from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_folder(path: str | Path) -> None:
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(f"Folder does not exist: {path}")
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def pick_folder(initial: str | Path) -> Path | None:
    """Open a small native-ish directory chooser in a child process.

    A child process keeps GUI toolkits away from the threaded HTTP server. If
    tkinter is unavailable (common on some Linux installs), callers can fall
    back to the manual path field in the Web UI.
    """
    initial = Path(initial).expanduser().resolve()
    code = r'''
import sys
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except Exception:
    pass
chosen = filedialog.askdirectory(initialdir=sys.argv[1], mustexist=True)
print(chosen or "")
root.destroy()
'''
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, str(initial)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Folder chooser is unavailable: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "tkinter is unavailable").strip().splitlines()[-1]
        raise RuntimeError(f"Folder chooser is unavailable: {detail}")
    chosen = result.stdout.strip().splitlines()
    if not chosen or not chosen[-1].strip():
        return None
    path = Path(chosen[-1].strip()).expanduser().resolve()
    return path if path.is_dir() else None
