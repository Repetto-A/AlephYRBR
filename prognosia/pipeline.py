"""Pipeline interno de Prognosia, reutilizable desde el CLI y el shell web.

Misma lógica que corría en cli._run: HC → transcript (audio o texto) →
extracción SOAP local → reglas deterministas. La decisión de safety sigue
siendo determinista sobre el transcript crudo (rules.py); acá no se decide nada.

Con skip_extract=True (flag --fast): saltea el LLM y usa una nota demo.
El caller en modo fast además fuerza source=transcript (sin STT).
Útil para ensayar la demo sin esperar 20–45 s.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .rules import decidir_status, evaluar_safety
from .schemas import ClinicalNote, PatientRecord, RunResult

# Recibe eventos {"stage": str, "message": str, ...extras}
ProgressFn = Callable[[dict[str, Any]], None]


def _emit(progress: ProgressFn | None, stage: str, message: str, **extra: Any) -> None:
    if progress is not None:
        progress({"stage": stage, "message": message, **extra})


def _nota_demo(transcript: str) -> ClinicalNote:
    """Nota mínima para la UI cuando se saltea el LLM (--fast).

    Si el transcript menciona una droga del corpus demo, la refleja en
    medicacion_propuesta para que la propuesta HCE muestre write actions
    (blocked_by_safety / pending_human). La decisión de safety sigue
    viniendo de rules.py sobre el transcript crudo.
    """
    from .schemas import ProposedMed

    preview = " ".join(transcript.split())[:220]
    low = transcript.lower()
    meds: list[ProposedMed] = []
    if "propranolol" in low:
        meds.append(
            ProposedMed(
                nombre="propranolol",
                dosis="40 mg",
                frecuencia="cada 12 horas",
                via="oral",
                evidencia="propranolol",
            )
        )
    elif "enalapril" in low:
        meds.append(
            ProposedMed(
                nombre="enalapril",
                dosis="10 mg",
                frecuencia="1 vez al día",
                via="oral",
                evidencia="enalapril",
            )
        )
    return ClinicalNote(
        subjetivo=f"{preview}…",
        objetivo="(a completar en la revisión)",
        evaluacion="(a completar en la revisión)",
        plan=(
            "(a completar en la revisión; la verificación de seguridad ya corrió)"
            if not meds
            else f"Se menciona {meds[0].nombre}. (a completar en la revisión; la verificación de seguridad ya corrió)"
        ),
        medicacion_propuesta=meds,
    )


async def run_pipeline(
    hc_path: Path,
    audio_path: Path | None = None,
    transcript_path: Path | None = None,
    progress: ProgressFn | None = None,
    *,
    skip_extract: bool = False,
) -> RunResult:
    """Corre el pipeline completo y devuelve el RunResult.

    Exactamente uno de audio_path / transcript_path debe estar presente.
    Con skip_extract=True no se llama al LLM (ni se abre el Client si hay transcript).
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
    modelo_extraccion = None
    latencia_extraccion = None

    if audio_path is not None:
        from tetherto.qvac_sdk import Client

        from .transcribe import STT_MODEL_NAME, transcribir

        async with Client() as client:
            _emit(progress, "stt", "[2/4] Transcribiendo audio (Whisper local)...")
            transcript, latencia_stt = await transcribir(client.transport, audio_path)
            transcript_source = "audio"
            modelo_stt = STT_MODEL_NAME
            _emit(
                progress,
                "transcript",
                f"[2/4] Transcript listo en {latencia_stt:.1f}s",
                transcript=transcript,
            )

            if skip_extract:
                _emit(
                    progress,
                    "extract",
                    "[3/4] Extracción omitida (--fast): nota demo + reglas sobre transcript",
                )
                note = _nota_demo(transcript)
                modelo_extraccion = "omitido (--fast)"
                latencia_extraccion = 0.0
            else:
                from .extract import EXTRACT_MODEL_NAME, extraer_nota

                _emit(progress, "extract", "[3/4] Extrayendo nota SOAP (Qwen3-4B local)...")
                t0 = time.perf_counter()
                note, note_refusal = await extraer_nota(client.transport, transcript)
                latencia_extraccion = time.perf_counter() - t0
                modelo_extraccion = EXTRACT_MODEL_NAME
                if note is None:
                    note_status = "refused"
                    _emit(progress, "extract", f"      extracción rechazada: {note_refusal}")
                else:
                    _emit(progress, "extract", f"      listo en {latencia_extraccion:.1f}s")
    else:
        assert transcript_path is not None
        transcript = transcript_path.read_text(encoding="utf-8").strip()
        transcript_source = "texto"
        _emit(
            progress,
            "transcript",
            "[2/4] Transcript cargado de texto (sin STT)",
            transcript=transcript,
        )

        if skip_extract:
            _emit(
                progress,
                "extract",
                "[3/4] Extracción omitida (--fast): nota demo + reglas sobre transcript",
            )
            note = _nota_demo(transcript)
            modelo_extraccion = "omitido (--fast)"
            latencia_extraccion = 0.0
        else:
            from tetherto.qvac_sdk import Client

            from .extract import EXTRACT_MODEL_NAME, extraer_nota

            async with Client() as client:
                _emit(progress, "extract", "[3/4] Extrayendo nota SOAP (Qwen3-4B local)...")
                t0 = time.perf_counter()
                note, note_refusal = await extraer_nota(client.transport, transcript)
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
