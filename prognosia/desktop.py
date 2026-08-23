"""Launcher de escritorio para el ejecutable empaquetado (PyInstaller).

Levanta el shell web en modo demo (--fast) y abre el navegador.
El pipeline completo (QVAC SDK) sigue siendo `python -m prognosia serve`
desde el repo; el ejecutable es la demo distribuible sin dependencias.
"""

from __future__ import annotations

import socket
import threading
import webbrowser


def _pick_port(preferred: int = 8787) -> int:
    for port in (preferred, 8788, 8789, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def main() -> int:
    import uvicorn

    from . import server

    server.FAST_MODE = True
    port = _pick_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Prognosia → {url}  (cerrá esta ventana para salir)", flush=True)
    threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
