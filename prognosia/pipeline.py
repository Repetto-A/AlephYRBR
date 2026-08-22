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

from .rules import (
    MARCADOR_CORRECCION,
    buscar_betabloqueante,
    decidir_status,
    evaluar_safety,
    filtrar_nota_por_correccion,
    texto_consulta_efectivo,
)
from .schemas import (
    ClinicalNote,
    ClinicalOrder,
    FollowUp,
    MedChange,
    PatientRecord,
    ProposedMed,
    RunResult,
    TranscriptCorrection,
    VitalSigns,
)

ProgressFn = Callable[[dict[str, Any]], None]


def _emit(progress: ProgressFn | None, stage: str, message: str, **extra: Any) -> None:
    if progress is not None:
        progress({"stage": stage, "message": message, **extra})


def _nota_demo(transcript: str) -> ClinicalNote:
    """Nota mínima para la UI cuando se saltea el LLM (--fast).

    Refleja drogas y entidades del corpus demo para ejercitar propuesta HCE
    y approve. La decisión de safety sigue viniendo de rules.py sobre el
    transcript crudo.
    """
    preview = " ".join(transcript.split())[:220]
    low = transcript.lower()
    cambios: list[MedChange] = []
    vitales: VitalSigns | None = None
    ordenes: list[ClinicalOrder] = []
    seguimiento: FollowUp | None = None

    if buscar_betabloqueante(transcript):
        cambios.append(
            MedChange(
                accion="add",
                nombre="propranolol",
                dosis="40 mg",
                frecuencia="cada 12 horas",
                via="oral",
                evidencia="propranolol cuarenta miligramos cada doce horas",
            )
        )
        vitales = VitalSigns(fc=96, pa="130/85", evidencia="frecuencia cardíaca noventa y seis")
        seguimiento = FollowUp(plazo="2 semanas", evidencia="control clínico en dos semanas")
    elif "enalapril" in low:
        # Misma dosis que HC-B → add (propose marca "Confirmar ya en HC").
        cambios.append(
            MedChange(
                accion="add",
                nombre="enalapril",
                dosis="10 mg",
                frecuencia="1 vez al día",
                via="oral",
                evidencia="continuar enalapril diez miligramos por día",
            )
        )
        vitales = VitalSigns(fc=72, pa="128/82", evidencia="tensión arterial ciento veintiocho")
        if "laboratorio" in low:
            ordenes.append(
                ClinicalOrder(
                    tipo="lab",
                    detalle="laboratorio de rutina",
                    evidencia="control en tres meses con laboratorio de rutina",
                )
            )
        seguimiento = FollowUp(plazo="3 meses", evidencia="control en tres meses")

    meds = [
        ProposedMed(
            nombre=c.nombre,
            dosis=c.dosis,
            frecuencia=c.frecuencia,
            via=c.via,
            evidencia=c.evidencia,
        )
        for c in cambios
        if c.accion == "add"
    ]

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
        cambios_medicacion=cambios,
        vitales=vitales,
        ordenes=ordenes,
        seguimiento=seguimiento,
    )


async def run_pipeline(
    hc_path: Path,
    audio_path: Path | None = None,
    transcript_path: Path | None = None,
    progress: ProgressFn | None = None,
    *,
    skip_extract: bool = False,
    hc_override: PatientRecord | None = None,
    prior_transcript: str | None = None,
) -> RunResult:
    """Corre el pipeline completo y devuelve el RunResult.

    Exactamente uno de audio_path / transcript_path debe estar presente.
    Con skip_extract=True no se llama al LLM (ni se abre el Client si hay transcript).
    hc_override: HC ya mergeada (p.ej. overlay post-approve) en lugar de leer el path.
    prior_transcript: si hay, audio/texto son una corrección del plan (revalidar).
    """
    if (audio_path is None) == (transcript_path is None):
        raise ValueError("Pasar exactamente uno de audio_path o transcript_path")

    if hc_override is not None:
        hc = hc_override
    else:
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
    transcript_raw: str | None = None
    transcript_corrections: list[TranscriptCorrection] = []

    def _apply_lexicon(raw: str, source_label: str) -> str:
        nonlocal transcript_raw, transcript_corrections
        from .lexicon import corregir_transcript

        lexed = corregir_transcript(raw)
        transcript_raw = lexed.raw if lexed.changed else None
        transcript_corrections = [
            TranscriptCorrection(
                kind=c.kind,  # type: ignore[arg-type]
                original=c.original,
                replacement=c.replacement,
            )
            for c in lexed.corrections
        ]
        if lexed.changed:
            _emit(
                progress,
                "lexicon",
                f"      léxico clínico: {len(lexed.corrections)} corrección(es) "
                f"({source_label})",
            )
        return lexed.text

    correccion_texto: str | None = None

    def _anexar_si_correccion(t: str) -> str:
        nonlocal correccion_texto
        if not prior_transcript:
            return t
        correccion_texto = t
        wrapped = (
            f"{prior_transcript.rstrip()}\n\n{MARCADOR_CORRECCION}: {t}"
        )
        _emit(
            progress,
            "correct",
            "[2b/4] Corrección del médico anexada; se revalida el plan",
        )
        return wrapped

    if audio_path is not None:
        from tetherto.qvac_sdk import Client

        from .transcribe import STT_MODEL_NAME, transcribir

        async with Client() as client:
            _emit(progress, "stt", "[2/4] Transcribiendo audio (Whisper local)...")
            raw_transcript, latencia_stt = await transcribir(
                client.transport, audio_path
            )
            transcript_source = "audio"
            modelo_stt = STT_MODEL_NAME
            transcript = _anexar_si_correccion(
                _apply_lexicon(raw_transcript, "post-STT")
            )
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
                note = _nota_demo(correccion_texto or transcript)
                modelo_extraccion = "omitido (--fast)"
                latencia_extraccion = 0.0
            else:
                from .extract import EXTRACT_MODEL_NAME, extraer_nota

                _emit(progress, "extract", "[3/4] Extrayendo nota SOAP (Qwen3-4B local)...")
                t0 = time.perf_counter()
                note, note_refusal = await extraer_nota(
                    client.transport, transcript, hc=hc
                )
                latencia_extraccion = time.perf_counter() - t0
                modelo_extraccion = EXTRACT_MODEL_NAME
                if note is None:
                    note_status = "refused"
                    _emit(progress, "extract", f"      extracción rechazada: {note_refusal}")
                else:
                    _emit(progress, "extract", f"      listo en {latencia_extraccion:.1f}s")
    else:
        assert transcript_path is not None
        raw_transcript = transcript_path.read_text(encoding="utf-8").strip()
        transcript_source = "texto"
        transcript = _anexar_si_correccion(_apply_lexicon(raw_transcript, "texto"))
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
            note = _nota_demo(correccion_texto or transcript)
            modelo_extraccion = "omitido (--fast)"
            latencia_extraccion = 0.0
        else:
            from tetherto.qvac_sdk import Client

            from .extract import EXTRACT_MODEL_NAME, extraer_nota

            async with Client() as client:
                _emit(progress, "extract", "[3/4] Extrayendo nota SOAP (Qwen3-4B local)...")
                t0 = time.perf_counter()
                note, note_refusal = await extraer_nota(
                    client.transport, transcript, hc=hc
                )
                latencia_extraccion = time.perf_counter() - t0
                modelo_extraccion = EXTRACT_MODEL_NAME
                if note is None:
                    note_status = "refused"
                    _emit(progress, "extract", f"      extracción rechazada: {note_refusal}")
                else:
                    _emit(progress, "extract", f"      listo en {latencia_extraccion:.1f}s")

    _emit(progress, "rules", "[4/4] Aplicando reglas deterministas de seguridad...")
    safety_text = transcript
    if correccion_texto:
        safety_text = texto_consulta_efectivo(
            prior_transcript or "", correccion_texto
        )
        note = filtrar_nota_por_correccion(note, correccion_texto)
    findings = evaluar_safety(hc, safety_text, note)
    from .evidence import attach_local_evidence

    attach_local_evidence(findings)
    status = decidir_status(findings)
    if status == "safe" and note is None:
        status = "escalate"

    return RunResult(
        status=status,
        patient_id=hc.patient_id,
        transcript=transcript,
        transcript_source=transcript_source,
        transcript_raw=transcript_raw,
        transcript_corrections=transcript_corrections,
        transcript_correccion=correccion_texto,
        note=note,
        note_status=note_status,
        note_refusal_motivo=note_refusal,
        findings=findings,
        modelo_extraccion=modelo_extraccion,
        modelo_stt=modelo_stt,
        latencia_stt_s=latencia_stt,
        latencia_extraccion_s=latencia_extraccion,
    )
