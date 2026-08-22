"""Shell web local de ClinicGuard (fase 2A).

Sirve la UI estática de clinicguard/web/ y expone la misma pipeline que el
CLI vía API JSON. Todo local: no hay llamadas de red salvo 127.0.0.1.

    python -m clinicguard serve            # http://127.0.0.1:8787
    python -m clinicguard serve --fast     # transcript + sin LLM (~1 s)

API:
    GET  /api/config         → {"fast": bool}  (modo demo rápida)
    GET  /api/cases          → casos demo (A near-miss, B control negativo) + HC
    POST /api/run            → {"case": "a"|"b", "source": "audio"|"transcript"}
                               arranca la pipeline en background, devuelve run_id
    GET  /api/run/{run_id}   → {"state": "running"|"done"|"error", steps, result}
                               (polling; STT+LLM tarda 20–45 s; --fast ~1 s)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .pipeline import run_pipeline

_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = _ROOT / "corpus" / "clinic"
_WEB = Path(__file__).resolve().parent / "web"

# Lo setea cli._cmd_serve cuando pasás --fast.
FAST_MODE: bool = False

CASES: dict[str, dict[str, Any]] = {
    "a": {
        "titulo": "Paciente A · demo near-miss",
        "descripcion": "Ambulatorio · taquicardia / temblor",
        "hc": _CORPUS / "hc-a.json",
        "audio": _CORPUS / "consulta-a.wav",
        "transcript": _CORPUS / "consulta-a.txt",
    },
    "b": {
        "titulo": "Paciente B · control negativo",
        "descripcion": "Ambulatorio · control HTA",
        "hc": _CORPUS / "hc-b.json",
        "audio": None,
        "transcript": _CORPUS / "consulta-b.txt",
    },
}

# Estado en memoria de las corridas (demo local, un solo usuario).
RUNS: dict[str, dict[str, Any]] = {}
# El worker QVAC carga modelos a RAM: una pipeline a la vez.
_pipeline_lock = asyncio.Lock()


async def get_config(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "fast": FAST_MODE,
            "hint": (
                "Modo rápido: transcript gold + reglas, sin Whisper ni LLM"
                if FAST_MODE
                else "Modo completo: STT + extracción LLM local"
            ),
        }
    )


async def get_cases(request: Request) -> JSONResponse:
    out = []
    for case_id, case in CASES.items():
        # En --fast no ofrecemos audio: el botón principal es transcript.
        tiene_audio = case["audio"] is not None and not FAST_MODE
        out.append(
            {
                "id": case_id,
                "titulo": case["titulo"],
                "descripcion": case["descripcion"],
                "tiene_audio": tiene_audio,
                "hc": json.loads(case["hc"].read_text(encoding="utf-8")),
            }
        )
    return JSONResponse(out)


async def _execute(run_id: str, case: dict[str, Any], source: str) -> None:
    run = RUNS[run_id]

    def on_progress(event: dict[str, Any]) -> None:
        run["steps"].append(event["message"])
        if "transcript" in event:
            run["transcript"] = event["transcript"]

    try:
        async with _pipeline_lock:
            run["started_at"] = time.time()
            result = await run_pipeline(
                hc_path=case["hc"],
                audio_path=case["audio"] if source == "audio" else None,
                transcript_path=case["transcript"] if source == "transcript" else None,
                progress=on_progress,
                skip_extract=FAST_MODE,
            )
        run["state"] = "done"
        run["result"] = result.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 — la UI muestra el error tal cual
        run["state"] = "error"
        run["error"] = f"{type(exc).__name__}: {exc}"


async def post_run(request: Request) -> JSONResponse:
    body = await request.json()
    case_id = body.get("case")
    case = CASES.get(case_id)
    if case is None:
        return JSONResponse({"error": f"Caso desconocido: {case_id!r}"}, status_code=400)

    # En --fast siempre transcript (aunque el cliente pida audio).
    if FAST_MODE:
        source = "transcript"
    else:
        source = body.get(
            "source", "audio" if case["audio"] is not None else "transcript"
        )
    if source not in ("audio", "transcript"):
        return JSONResponse({"error": f"Fuente inválida: {source!r}"}, status_code=400)
    if source == "audio" and case["audio"] is None:
        return JSONResponse(
            {"error": f"El caso {case_id!r} no tiene audio en el corpus"},
            status_code=400,
        )

    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {
        "state": "running",
        "case": case_id,
        "source": source,
        "steps": [],
        "transcript": None,
        "result": None,
        "error": None,
    }
    asyncio.get_running_loop().create_task(_execute(run_id, case, source))
    return JSONResponse({"run_id": run_id}, status_code=202)


async def get_run(request: Request) -> JSONResponse:
    run = RUNS.get(request.path_params["run_id"])
    if run is None:
        return JSONResponse({"error": "run_id desconocido"}, status_code=404)
    return JSONResponse(
        {k: run[k] for k in ("state", "case", "source", "steps", "transcript", "result", "error")}
    )


app = Starlette(
    routes=[
        Route("/api/config", get_config, methods=["GET"]),
        Route("/api/cases", get_cases, methods=["GET"]),
        Route("/api/run", post_run, methods=["POST"]),
        Route("/api/run/{run_id}", get_run, methods=["GET"]),
        Mount("/", StaticFiles(directory=_WEB, html=True)),
    ]
)
