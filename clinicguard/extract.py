"""Extracción de nota SOAP con Qwen3-4B local (QVAC).

Contratos del kickoff (Paso 4):
- JSON validado con Pydantic; retry con feedback del validador (máx 2).
- Refusal explícito: si no se puede validar, NO se inventa medicación.
- Anti-invención: toda medicación propuesta debe aparecer textualmente
  (normalizada) en el transcript, si no se rechaza con feedback.
"""

from __future__ import annotations

import json
import re
import unicodedata

from pydantic import BaseModel, ValidationError
from tetherto.qvac_sdk import completion, load_model, unload_model
from tetherto.qvac_sdk.models import QWEN3_4B_INST_Q4_K_M

from .schemas import ClinicalNote

EXTRACT_MODEL_NAME = "QWEN3_4B_INST_Q4_K_M"
MAX_RETRIES = 2

_THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.IGNORECASE | re.DOTALL)

SYSTEM_PROMPT = """Sos un asistente de documentación clínica. Recibís el transcript de una consulta médica (puede venir de un reconocedor de voz con errores ortográficos) y devolvés una nota SOAP estructurada.

Respondé SOLO con un objeto JSON válido, sin markdown ni texto adicional, con exactamente estas claves:
{
  "subjetivo": "motivo de consulta y síntomas relatados",
  "objetivo": "hallazgos del examen físico y signos vitales",
  "evaluacion": "impresión diagnóstica",
  "plan": "conducta indicada",
  "medicacion_propuesta": [
    {"nombre": "droga en minúsculas", "dosis": "...", "frecuencia": "...", "via": "...", "evidencia": "cita textual del transcript"}
  ]
}

Reglas estrictas:
- NO inventes información que no esté en el transcript.
- Incluí una medicación en medicacion_propuesta SOLO si el transcript la menciona como indicación nueva del plan. Corregí la ortografía del nombre de la droga si el reconocedor la distorsionó.
- "evidencia" debe ser una cita textual (puede estar distorsionada) del transcript.
- Si un dato no está, usá "" (string vacío) o null, nunca lo completes con suposiciones.
- Si el transcript es ininteligible o no corresponde a una consulta médica, respondé exactamente: {"refusal": "motivo breve"}"""


class _ExtractionPayload(BaseModel):
    """Respuesta del LLM: o una nota SOAP o un refusal."""

    refusal: str | None = None
    subjetivo: str = ""
    objetivo: str = ""
    evaluacion: str = ""
    plan: str = ""
    medicacion_propuesta: list[dict] = []


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _parse_json(raw: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta (tolera texto alrededor)."""
    cleaned = _THINK_RE.sub("", raw).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("la respuesta no contiene un objeto JSON")
    return json.loads(cleaned[start : end + 1])


def _meds_inventadas(note: ClinicalNote, transcript: str) -> list[str]:
    """Drogas propuestas cuyo nombre no aparece (ni aproximado) en el transcript."""
    normalizado = _normalize(transcript)
    inventadas = []
    for med in note.medicacion_propuesta:
        nombre = _normalize(med.nombre)
        # Tolera distorsión de STT: alcanza con que el prefijo (>=6 chars) aparezca.
        prefijo = nombre[: max(6, len(nombre) - 3)]
        if nombre not in normalizado and prefijo not in normalizado:
            inventadas.append(med.nombre)
    return inventadas


async def extraer_nota(
    transport, transcript: str
) -> tuple[ClinicalNote | None, str | None]:
    """Extrae la nota SOAP. Devuelve (note, None) o (None, motivo_refusal)."""
    # Sin ctx_size explícito el worker usa un contexto chico y el prompt
    # desborda (ContextOverflowError).
    model_id = await load_model(
        transport, model_src=QWEN3_4B_INST_Q4_K_M, model_config={"ctx_size": 8192}
    )
    try:
        history = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript de la consulta:\n\n{transcript}"},
        ]
        ultimo_error = "sin intentos"
        for intento in range(1 + MAX_RETRIES):
            run = completion(
                transport,
                model_id=model_id,
                history=history,
                generation_params={"temp": 0, "seed": 42, "predict": 1024},
                capture_thinking=True,
            )
            final = await run.final
            raw = final.content_text

            try:
                payload = _ExtractionPayload.model_validate(_parse_json(raw))
                if payload.refusal:
                    return None, payload.refusal
                note = ClinicalNote.model_validate(
                    payload.model_dump(exclude={"refusal"})
                )
                inventadas = _meds_inventadas(note, transcript)
                if inventadas:
                    raise ValueError(
                        f"estas drogas no aparecen en el transcript: {inventadas}. "
                        "No inventes medicación; incluí solo lo mencionado."
                    )
                return note, None
            except (ValueError, ValidationError, json.JSONDecodeError) as e:
                ultimo_error = str(e)
                if intento < MAX_RETRIES:
                    # Retry con feedback del validador.
                    history = history + [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "Tu respuesta no validó contra el schema: "
                                f"{ultimo_error}\nRespondé de nuevo SOLO con el JSON "
                                "corregido, sin texto adicional."
                            ),
                        },
                    ]
        return None, f"no validó tras {1 + MAX_RETRIES} intentos: {ultimo_error}"
    finally:
        await unload_model(transport, model_id)
