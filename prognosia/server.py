"""Shell web local de Prognosia (fase 2A).

Sirve la UI estática de prognosia/web/ y expone la misma pipeline que el
CLI vía API JSON. Todo local: no hay llamadas de red salvo 127.0.0.1.

    python -m prognosia serve            # http://127.0.0.1:8787
    python -m prognosia serve --fast     # transcript + sin LLM (~1 s)

API:
    GET  /api/config
    GET  /api/cases
    POST /api/patients
    POST /api/run            → source audio|transcript|texto
    GET  /api/run/{run_id}
    POST /api/run/{run_id}/correct → revalida un run blocked (audio o texto)
    POST /api/approve        → writes pending_human + HC overlay local
    GET  /api/encounters/{patient_id}
"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
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
from .schemas import PatientRecord, RunResult
from .store import apply_approval, list_encounters, load_hc_overlay

_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = _ROOT / "corpus" / "clinic"
_WEB = Path(__file__).resolve().parent / "web"
_TMP = Path(tempfile.mkdtemp(prefix="prognosia-mic-"))

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

# Pacientes registrados desde la UI (demo local).
_PATIENTS = _ROOT / "out" / "patients"

RUNS: dict[str, dict[str, Any]] = {}
_pipeline_lock = asyncio.Lock()


def _base_hc(case: dict[str, Any]) -> PatientRecord:
    return PatientRecord.model_validate(
        json.loads(case["hc"].read_text(encoding="utf-8"))
    )


def _effective_hc(case: dict[str, Any]) -> PatientRecord:
    base = _base_hc(case)
    return load_hc_overlay(base.patient_id, base)


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
                "stt": "WHISPER_BASE_Q8_0 + VAD_SILERO + lexicon post-STT",
                "llm": "QWEN3_4B_INST_Q4_K_M",
                "safety": "deterministic rules (no LLM)",
                "evidence": "local_rag BM25 guidelines (+ evidence.json fallback)",
                "lexicon": "corpus/clinic/lexicon.json",
                "hce_agent": "local propose + approve store (no LLM)",
                "cloud_inference": False,
            },
        }
    )


async def get_cases(request: Request) -> JSONResponse:
    out = []
    for case_id, case in CASES.items():
        tiene_audio = case["audio"] is not None and not FAST_MODE
        hc = _effective_hc(case)
        encounters = list_encounters(hc.patient_id)
        out.append(
            {
                "id": case_id,
                "titulo": case["titulo"],
                "descripcion": case["descripcion"],
                "tiene_audio": tiene_audio,
                "hc": hc.model_dump(mode="json"),
                "encounters_count": len(encounters),
            }
        )
    return JSONResponse(out)


def _save_mic_wav(run_id: str, audio_wav_b64: str) -> Path:
    raw = base64.b64decode(audio_wav_b64, validate=False)
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("audio_wav_b64 no es un WAV válido (RIFF/WAVE)")
    path = _TMP / f"{run_id}.wav"
    path.write_bytes(raw)
    return path


async def _execute(
    run_id: str,
    case: dict[str, Any],
    audio_path: Path | None,
    transcript_path: Path | None,
    *,
    prior_transcript: str | None = None,
    cleanup_paths: list[Path] | None = None,
) -> None:
    run = RUNS[run_id]

    def on_progress(event: dict[str, Any]) -> None:
        run["steps"].append(event["message"])
        if "transcript" in event:
            run["transcript"] = event["transcript"]

    try:
        hc = _effective_hc(case)
        async with _pipeline_lock:
            run["started_at"] = time.time()
            result = await run_pipeline(
                hc_path=case["hc"],
                audio_path=audio_path,
                transcript_path=transcript_path,
                progress=on_progress,
                skip_extract=FAST_MODE,
                hc_override=hc,
                prior_transcript=prior_transcript,
            )
        proposal = build_proposal(hc, result)
        run["elapsed_s"] = round(time.time() - run["started_at"], 2)
        run["state"] = "done"
        run["result"] = result.model_dump(mode="json")
        run["proposal"] = proposal.model_dump(mode="json")
        run["patient_id"] = hc.patient_id
    except Exception as exc:  # noqa: BLE001
        run["state"] = "error"
        run["error"] = f"{type(exc).__name__}: {exc}"
        if run.get("started_at"):
            run["elapsed_s"] = round(time.time() - run["started_at"], 2)
    finally:
        for path in cleanup_paths or []:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _lista(body: dict[str, Any], campo: str) -> list[str]:
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
        "estudios": [],
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
            "encounters_count": 0,
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
        _PATIENTS.mkdir(parents=True, exist_ok=True)
        transcript_path = _PATIENTS / f"consulta-{uuid.uuid4().hex[:8]}.txt"
        transcript_path.write_text(texto, encoding="utf-8")
        source = "texto"
    else:
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
                    {
                        "error": "Este paciente no tiene consulta de ejemplo: "
                        "escribí lo que se habló."
                    },
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
        "elapsed_s": None,
        "started_at": None,
        "patient_id": None,
        "approved": None,
        "parent_run_id": None,
    }
    asyncio.get_running_loop().create_task(
        _execute(run_id, case, audio_path, transcript_path)
    )
    return JSONResponse({"run_id": run_id}, status_code=202)


async def get_run(request: Request) -> JSONResponse:
    run = RUNS.get(request.path_params["run_id"])
    if run is None:
        return JSONResponse({"error": "run_id desconocido"}, status_code=404)
    elapsed = run.get("elapsed_s")
    if elapsed is None and run.get("started_at"):
        elapsed = round(time.time() - run["started_at"], 2)
    payload = {
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
            "approved",
            "parent_run_id",
        )
    }
    payload["elapsed_s"] = elapsed
    return JSONResponse(payload)


async def post_correct(request: Request) -> JSONResponse:
    parent_id = request.path_params["run_id"]
    parent = RUNS.get(parent_id)
    if parent is None:
        return JSONResponse({"error": "run_id desconocido"}, status_code=404)
    if parent["state"] != "done" or not parent.get("result"):
        return JSONResponse(
            {"error": "El run aún no está listo para corregir"}, status_code=409
        )
    if parent["result"].get("status") != "blocked":
        return JSONResponse(
            {
                "error": "Solo se corrige una nota retenida por contradicción "
                "con la historia clínica."
            },
            status_code=400,
        )

    case = CASES.get(parent["case"])
    if case is None:
        return JSONResponse({"error": "Caso del run desconocido"}, status_code=400)

    body = await request.json()
    texto = str(body.get("texto") or "").strip()
    b64 = body.get("audio_wav_b64")
    prior = str(parent["result"].get("transcript") or "").strip()
    if not prior:
        return JSONResponse(
            {"error": "El run no tiene transcript para anexar la corrección"},
            status_code=400,
        )

    run_id = uuid.uuid4().hex[:12]
    audio_path: Path | None = None
    transcript_path: Path | None = None
    cleanup: list[Path] = []
    source = "texto"

    if texto:
        _PATIENTS.mkdir(parents=True, exist_ok=True)
        transcript_path = _PATIENTS / f"correccion-{run_id}.txt"
        transcript_path.write_text(texto, encoding="utf-8")
        cleanup.append(transcript_path)
        source = "texto"
    elif b64 and isinstance(b64, str) and not FAST_MODE:
        try:
            audio_path = _save_mic_wav(run_id, b64)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"WAV inválido: {type(exc).__name__}: {exc}"},
                status_code=400,
            )
        cleanup.append(audio_path)
        source = "audio"
    else:
        if FAST_MODE:
            return JSONResponse(
                {
                    "error": "En modo rápido escribí la corrección del plan "
                    "(sin audio Whisper)."
                },
                status_code=400,
            )
        return JSONResponse(
            {
                "error": "Hace falta el audio de la corrección o el texto "
                "del plan corregido."
            },
            status_code=400,
        )

    RUNS[run_id] = {
        "state": "running",
        "case": parent["case"],
        "source": source,
        "steps": [],
        "transcript": None,
        "result": None,
        "proposal": None,
        "error": None,
        "elapsed_s": None,
        "started_at": None,
        "patient_id": None,
        "approved": None,
        "parent_run_id": parent_id,
    }
    asyncio.get_running_loop().create_task(
        _execute(
            run_id,
            case,
            audio_path,
            transcript_path,
            prior_transcript=prior,
            cleanup_paths=cleanup,
        )
    )
    return JSONResponse({"run_id": run_id}, status_code=202)


async def post_approve(request: Request) -> JSONResponse:
    body = await request.json()
    run_id = body.get("run_id")
    run = RUNS.get(run_id)
    if run is None:
        return JSONResponse({"error": "run_id desconocido"}, status_code=404)
    if run["state"] != "done" or not run.get("result") or not run.get("proposal"):
        return JSONResponse(
            {"error": "El run aún no está listo para aprobar"}, status_code=409
        )
    if run.get("approved"):
        return JSONResponse(
            {"error": "Este run ya fue aprobado", "approved": run["approved"]},
            status_code=409,
        )

    case = CASES.get(run["case"])
    if case is None:
        return JSONResponse({"error": "Caso del run desconocido"}, status_code=400)

    result = RunResult.model_validate(run["result"])
    try:
        applied = apply_approval(
            patient_id=result.patient_id,
            run_id=run_id,
            base_hc=_base_hc(case),
            result=result,
            proposal=run["proposal"],
            edited_soap=body.get("edited_soap"),
            action_ids=body.get("action_ids"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    run["approved"] = applied
    return JSONResponse({"ok": True, **applied})


async def get_encounters(request: Request) -> JSONResponse:
    patient_id = request.path_params["patient_id"]
    return JSONResponse(
        {
            "patient_id": patient_id,
            "encounters": list_encounters(patient_id),
        }
    )


app = Starlette(
    routes=[
        Route("/api/config", get_config, methods=["GET"]),
        Route("/api/cases", get_cases, methods=["GET"]),
        Route("/api/patients", post_patient, methods=["POST"]),
        Route("/api/run", post_run, methods=["POST"]),
        Route("/api/run/{run_id}", get_run, methods=["GET"]),
        Route("/api/run/{run_id}/correct", post_correct, methods=["POST"]),
        Route("/api/approve", post_approve, methods=["POST"]),
        Route("/api/encounters/{patient_id}", get_encounters, methods=["GET"]),
        Mount("/", StaticFiles(directory=_WEB, html=True)),
    ]
)
