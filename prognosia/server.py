"""Shell web local de Prognosia (fase 2A).

Sirve la UI estática de prognosia/web/ y expone la misma pipeline que el
CLI vía API JSON. Todo local: no hay llamadas de red salvo 127.0.0.1.

    python -m prognosia serve            # http://127.0.0.1:8787
    python -m prognosia serve --fast     # transcript + sin LLM (~1 s)

API:
    GET  /api/config         → {"fast": bool, "stack": {...}}  (QVAC visible)
    GET  /api/cases          → casos demo (A near-miss, B control negativo) + HC
    POST /api/run            → {"case": "a"|"b", "source": "audio"|"transcript"}
                               arranca la pipeline en background, devuelve run_id
    GET  /api/run/{run_id}   → {state, steps, result, proposal}
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
from .propose import build_proposal
from .schemas import PatientRecord

_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = _ROOT / "corpus" / "clinic"
_WEB = Path(__file__).resolve().parent / "web"

# Lo setea cli._cmd_serve cuando pasás --fast.
FAST_MODE: bool = False

CASES: dict[str, dict[str, Any]] = {
    "a": {
        "titulo": "Ana López",
        "descripcion": "Palpitaciones y temblor",
        "hc": _CORPUS / "hc-a.json",
        "audio": _CORPUS / "consulta-a.wav",
        "transcript": _CORPUS / "consulta-a.txt",
    },
    "b": {
        "titulo": "Jorge Díaz",
        "descripcion": "Control de presión",
        "hc": _CORPUS / "hc-b.json",
        "audio": None,
        "transcript": _CORPUS / "consulta-b.txt",
    },
}

# Pacientes registrados desde la UI (demo local): las HC generadas viven en
# out/patients/ (gitignoreado) y solo duran lo que dura el proceso.
_PATIENTS = _ROOT / "out" / "patients"

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
            "track": "qvac",
            "stack": {
                "runtime": "tetherto-qvac-sdk",
                "stt": "WHISPER_BASE_Q8_0 + VAD_SILERO",
                "llm": "QWEN3_4B_INST_Q4_K_M",
                "safety": "deterministic rules (no LLM)",
                "hce_agent": "local propose (no LLM, pending_human)",
                "cloud_inference": False,
            },
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


async def _execute(
    run_id: str,
    hc_path: Path,
    audio_path: Path | None,
    transcript_path: Path | None,
) -> None:
    run = RUNS[run_id]

    def on_progress(event: dict[str, Any]) -> None:
        run["steps"].append(event["message"])
        if "transcript" in event:
            run["transcript"] = event["transcript"]

    try:
        async with _pipeline_lock:
            run["started_at"] = time.time()
            result = await run_pipeline(
                hc_path=hc_path,
                audio_path=audio_path,
                transcript_path=transcript_path,
                progress=on_progress,
                skip_extract=FAST_MODE,
            )
        hc = PatientRecord.model_validate(
            json.loads(hc_path.read_text(encoding="utf-8"))
        )
        proposal = build_proposal(hc, result)
        run["state"] = "done"
        run["result"] = result.model_dump(mode="json")
        run["proposal"] = proposal.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 — la UI muestra el error tal cual
        run["state"] = "error"
        run["error"] = f"{type(exc).__name__}: {exc}"


def _lista(body: dict[str, Any], campo: str) -> list[str]:
    """Acepta lista o string separado por comas; devuelve strings limpios."""
    raw = body.get(campo) or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [s.strip() for s in raw if str(s).strip()]


async def post_patient(request: Request) -> JSONResponse:
    body = await request.json()
    nombre = str(body.get("nombre") or "").strip()
    if not nombre:
        return JSONResponse({"error": "El nombre es obligatorio"}, status_code=400)

    seq = len(CASES) + 1
    case_id = f"p{seq}-{uuid.uuid4().hex[:6]}"
    edad_raw = str(body.get("edad") or "").strip()
    hc = {
        "patient_id": f"HC-{seq:03d}",
        "nombre": nombre,
        "edad": int(edad_raw) if edad_raw.isdigit() else None,
        "sexo": str(body.get("sexo") or "").strip() or None,
        "antecedentes": [{"condicion": a} for a in _lista(body, "antecedentes")],
        "medicacion_actual": [{"droga": m} for m in _lista(body, "medicacion")],
        "alergias": _lista(body, "alergias"),
        "nota": "Paciente de prueba registrado desde la demo. No es una persona real.",
    }
    _PATIENTS.mkdir(parents=True, exist_ok=True)
    hc_path = _PATIENTS / f"hc-{case_id}.json"
    hc_path.write_text(json.dumps(hc, ensure_ascii=False, indent=2), encoding="utf-8")

    motivo = str(body.get("motivo") or "").strip() or "Consulta"
    CASES[case_id] = {
        "titulo": nombre,
        "descripcion": motivo,
        "hc": hc_path,
        "audio": None,
        "transcript": None,
    }
    return JSONResponse(
        {
            "id": case_id,
            "titulo": nombre,
            "descripcion": motivo,
            "tiene_audio": False,
            "hc": hc,
        },
        status_code=201,
    )


async def post_run(request: Request) -> JSONResponse:
    body = await request.json()
    case_id = body.get("case")
    case = CASES.get(case_id)
    if case is None:
        return JSONResponse({"error": f"Caso desconocido: {case_id!r}"}, status_code=400)

    texto = str(body.get("texto") or "").strip()
    audio_path: Path | None = None
    transcript_path: Path | None = None

    if texto:
        # Consulta escrita/pegada desde la UI: se corre igual que un transcript.
        _PATIENTS.mkdir(parents=True, exist_ok=True)
        transcript_path = _PATIENTS / f"consulta-{uuid.uuid4().hex[:8]}.txt"
        transcript_path.write_text(texto, encoding="utf-8")
        source = "texto"
    else:
        # En --fast siempre transcript (aunque el cliente pida audio).
        if FAST_MODE:
            source = "transcript"
        else:
            source = body.get(
                "source", "audio" if case["audio"] is not None else "transcript"
            )
        if source not in ("audio", "transcript"):
            return JSONResponse({"error": f"Fuente inválida: {source!r}"}, status_code=400)
        if source == "audio":
            if case["audio"] is None:
                return JSONResponse(
                    {"error": f"El caso {case_id!r} no tiene audio en el corpus"},
                    status_code=400,
                )
            audio_path = case["audio"]
        else:
            if case["transcript"] is None:
                return JSONResponse(
                    {"error": "Este paciente no tiene consulta de ejemplo: escribí lo que se habló."},
                    status_code=400,
                )
            transcript_path = case["transcript"]

    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {
        "state": "running",
        "case": case_id,
        "source": source,
        "steps": [],
        "transcript": None,
        "result": None,
        "proposal": None,
        "error": None,
    }
    asyncio.get_running_loop().create_task(
        _execute(run_id, case["hc"], audio_path, transcript_path)
    )
    return JSONResponse({"run_id": run_id}, status_code=202)


async def get_run(request: Request) -> JSONResponse:
    run = RUNS.get(request.path_params["run_id"])
    if run is None:
        return JSONResponse({"error": "run_id desconocido"}, status_code=404)
    return JSONResponse(
        {
            k: run[k]
            for k in (
                "state",
                "case",
                "source",
                "steps",
                "transcript",
                "result",
                "proposal",
                "error",
            )
        }
    )


app = Starlette(
    routes=[
        Route("/api/config", get_config, methods=["GET"]),
        Route("/api/cases", get_cases, methods=["GET"]),
        Route("/api/patients", post_patient, methods=["POST"]),
        Route("/api/run", post_run, methods=["POST"]),
        Route("/api/run/{run_id}", get_run, methods=["GET"]),
        Mount("/", StaticFiles(directory=_WEB, html=True)),
    ]
)
