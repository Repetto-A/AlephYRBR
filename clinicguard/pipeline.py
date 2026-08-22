"""Pipeline interno de ClinicGuard, reutilizable desde el CLI y el shell web.

Misma lógica que corría en cli._run: HC → transcript (audio o texto) →
extracción SOAP local → reglas deterministas. La decisión de safety sigue
siendo determinista sobre el transcript crudo (rules.py); acá no se decide nada.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from tetherto.qvac_sdk import Client

from .rules import decidir_status, evaluar_safety
from .schemas import PatientRecord, RunResult

# Recibe eventos {"stage": str, "message": str, ...extras}
ProgressFn = Callable[[dict[str, Any]], None]


def _emit(progress: ProgressFn | None, stage: str, message: str, **extra: Any) -> None:
    if progress is not None:
        progress({"stage": stage, "message": message, **extra})


async def run_pipeline(
    hc_path: Path,
    audio_path: Path | None = None,
    transcript_path: Path | None = None,
    progress: ProgressFn | None = None,
) -> RunResult:
    """Corre el pipeline completo y devuelve el RunResult.

    Exactamente uno de audio_path / transcript_path debe estar presente.
    """
    if (audio_path is None) == (transcript_path is None):
        raise ValueError("Pasar exactamente uno de audio_path o transcript_path")

    hc = PatientRecord.model_validate(
        json.loads(Path(hc_path).read_text(encoding="utf-8"))
    )
    _emit(progress, "hc", f"[1/4] HC cargada: {hc.nombre} ({hc.patient_id})")

    modelo_stt = None
    latencia_stt = None
    note = None
    note_status = "ok"
    note_refusal = None

    async with Client() as client:
        t = client.transport

        if audio_path is not None:
            from .transcribe import STT_MODEL_NAME, transcribir

            _emit(progress, "stt", "[2/4] Transcribiendo audio (Whisper local)...")
            transcript, latencia_stt = await transcribir(t, audio_path)
            transcript_source = "audio"
            modelo_stt = STT_MODEL_NAME
            _emit(
                progress,
                "transcript",
                f"[2/4] Transcript listo en {latencia_stt:.1f}s",
                transcript=transcript,
            )
        else:
            transcript = transcript_path.read_text(encoding="utf-8").strip()
            transcript_source = "texto"
            _emit(
                progress,
                "transcript",
                "[2/4] Transcript cargado de texto (sin STT)",
                transcript=transcript,
            )

        from .extract import EXTRACT_MODEL_NAME, extraer_nota

        _emit(progress, "extract", "[3/4] Extrayendo nota SOAP (Qwen3-4B local)...")
        t0 = time.perf_counter()
        note, note_refusal = await extraer_nota(t, transcript)
        latencia_extraccion = time.perf_counter() - t0
        modelo_extraccion = EXTRACT_MODEL_NAME
        if note is None:
            note_status = "refused"
            _emit(progress, "extract", f"      extracción rechazada: {note_refusal}")
        else:
            _emit(progress, "extract", f"      listo en {latencia_extraccion:.1f}s")

    _emit(progress, "rules", "[4/4] Aplicando reglas deterministas de seguridad...")
    findings = evaluar_safety(hc, transcript, note)
    status = decidir_status(findings)
    if status == "safe" and note is None:
        # Sin nota validada no se puede afirmar que el plan es seguro.
        status = "escalate"

    return RunResult(
        status=status,
        patient_id=hc.patient_id,
        transcript=transcript,
        transcript_source=transcript_source,
        note=note,
        note_status=note_status,
        note_refusal_motivo=note_refusal,
        findings=findings,
        modelo_extraccion=modelo_extraccion,
        modelo_stt=modelo_stt,
        latencia_stt_s=latencia_stt,
        latencia_extraccion_s=latencia_extraccion,
    )
