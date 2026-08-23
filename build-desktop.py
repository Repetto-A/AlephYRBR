"""Build del ejecutable de escritorio (demo --fast) con PyInstaller.

Uso:  python build-desktop.py
Deja el binario en dist/Prognosia (o dist/Prognosia.exe en Windows).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sep = ";" if sys.platform == "win32" else ":"

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm", "--onefile", "--name", "Prognosia",
    "--console",
    "--add-data", f"prognosia/web{sep}prognosia/web",
    "--add-data", f"corpus/clinic{sep}corpus/clinic",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan.on",
    "--exclude-module", "tetherto",
    "run_desktop.py",
]
raise SystemExit(subprocess.call(cmd, cwd=ROOT))
