"""Extracción de nota SOAP + entidades clínicas con Qwen3-4B local (QVAC).

Contratos del kickoff (Paso 4):
- JSON validado con Pydantic; retry con feedback del validador (máx 2).
- Refusal explícito: si no se puede validar, NO se inventa medicación.
- Anti-invención: toda medicación (add/change/stop) debe aparecer
  (normalizada) en el transcript; si no, se rechaza con feedback.

Endurecido para Qwen3:
- thinking OFF (`/no_think` + capture_thinking=False)
- response_format json_object (con fallback)
- parser tolerante (fences / thinking / llaves balanceadas)
- retries limpios (sin reinyectar dumps fallidos)
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, ValidationError

from .lexicon import drug_mentioned, resolve_drug_name
from .schemas import ClinicalNote, PatientRecord

logger = logging.getLogger(__name__)

EXTRACT_MODEL_NAME = "QWEN3_4B_INST_Q4_K_M"
MAX_RETRIES = 2
PREDICT_TOKENS = 2048

_THINK_RE = re.compile(
    r"<think>.*?(</think>|$)|<thinking>.*?(</thinking>|$)",
    re.IGNORECASE | re.DOTALL,
)
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

SYSTEM_PROMPT = """Sos un extractor clinico. Tu UNICA salida valida es un objeto JSON.

Schema exacto (todas las claves, sin otras):
{
  "subjetivo": "string",
  "objetivo": "string",
  "evaluacion": "string",
  "plan": "string",
  "cambios_medicacion": [
    {
      "accion": "add",
      "nombre": "propranolol",
      "dosis": "40 mg",
      "frecuencia": "cada 12 horas",
      "via": "oral",
      "evidencia": "cita del transcript"
    }
  ],
  "medicacion_propuesta": [],
  "vitales": {
    "fc": 96,
    "pa": "130/85",
    "sat": null,
    "temperatura": null,
    "peso_kg": null,
    "evidencia": "cita"
  },
  "alergias_mencionadas": [],
  "ordenes": [],
  "seguimiento": {"plazo": "dos semanas", "evidencia": "cita"}
}

Reglas:
- Empeza con { y termina con }. Cero markdown, cero prosa, cero <think>.
- NO inventes datos ausentes del transcript. Usa "" / null / [].
- NO inventes farmacos. Medicacion en cambios_medicacion / medicacion_propuesta SOLO si aparece en el transcript.
- Si te pasan CONTEXTO HC: es referencia de lectura (antecedentes, alergias, meds actuales). NO copies medicacion_actual al plan ni a cambios_medicacion salvo que el transcript la mencione.
- Si hay conflicto transcript vs HC en el plan: preferi el transcript; las reglas de safety se aplican despues.
- cambios_medicacion: SOLO drogas del plan. accion en add|change|stop. Corregi ortografia STT.
- vitales: preferi digitos (FC 96, PA 130/85) si aparecen.
- evidencia = cita textual del transcript (puede estar distorsionada).
- Si el transcript no es consulta medica: {"refusal": "motivo breve"}"""


class _ExtractionPayload(BaseModel):
    """Respuesta del LLM: nota o refusal."""

    refusal: str | None = None
    subjetivo: str = ""
    objetivo: str = ""
    evaluacion: str = ""
    plan: str = ""
    medicacion_propuesta: list[dict] = []
    cambios_medicacion: list[dict] = []
    vitales: dict | None = None
    alergias_mencionadas: list[dict] = []
    ordenes: list[dict] = []
    seguimiento: dict | None = None


def _strip_noise(raw: str) -> str:
    cleaned = _THINK_RE.sub("", raw or "").strip()
    if not cleaned:
        return ""
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    return cleaned


def _balanced_object(text: str) -> str | None:
    """Extrae el primer objeto {...} con llaves balanceadas."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_json(raw: str) -> dict:
    """Parsea JSON tolerando thinking, fences y texto alrededor."""
    cleaned = _strip_noise(raw)
    if not cleaned:
        raise ValueError(
            "la respuesta quedo vacia (probable thinking sin JSON). "
            "Responde SOLO el objeto JSON."
        )

    candidates: list[str] = []
    balanced = _balanced_object(cleaned)
    if balanced:
        candidates.append(balanced)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    candidates.append(cleaned)

    last_err: Exception | None = None
    seen: set[str] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
            raise ValueError("JSON raiz no es un objeto")
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            continue

    raise ValueError(f"la respuesta no contiene un objeto JSON parseable: {last_err}")


def _meds_inventadas(note: ClinicalNote, transcript: str) -> list[str]:
    inventadas: list[str] = []
    nombres: list[str] = [m.nombre for m in note.medicacion_propuesta]
    nombres.extend(c.nombre for c in note.cambios_medicacion)
    for nombre in nombres:
        if not drug_mentioned(nombre, transcript):
            inventadas.append(nombre)
    return inventadas


def _canonizar_drogas(note: ClinicalNote) -> ClinicalNote:
    """Normaliza nombres de droga al canonico del lexico cuando hay match."""
    for m in note.medicacion_propuesta:
        canon = resolve_drug_name(m.nombre)
        if canon:
            m.nombre = canon
    for c in note.cambios_medicacion:
        canon = resolve_drug_name(c.nombre)
        if canon:
            c.nombre = canon
    return note


def _format_hc_context(hc: PatientRecord | None) -> str:
    """HC acotada para el LLM: referencia de lectura, no fuente de invencion."""
    if hc is None:
        return ""
    lines: list[str] = []
    if hc.antecedentes:
        bits = []
        for a in hc.antecedentes:
            bit = a.condicion
            if a.severidad:
                bit += f" ({a.severidad})"
            bits.append(bit)
        lines.append("Antecedentes relevantes: " + "; ".join(bits))
    if hc.alergias:
        lines.append("Alergias conocidas (referencia): " + "; ".join(hc.alergias))
    if hc.medicacion_actual:
        meds = []
        for m in hc.medicacion_actual:
            bit = m.droga
            if m.dosis:
                bit += f" {m.dosis}"
            meds.append(bit)
        lines.append(
            "Medicacion actual en HC (SOLO referencia de lectura; "
            "NO la copies al plan ni a cambios_medicacion a menos que el "
            "transcript la mencione): " + "; ".join(meds)
        )
    if not lines:
        return ""
    return (
        "CONTEXTO HC (acotado; no inventes desde aqui):\n"
        + "\n".join(f"- {ln}" for ln in lines)
        + "\n\n"
    )


def _user_message(
    transcript: str,
    *,
    hc: PatientRecord | None = None,
    strict: bool = False,
) -> str:
    # /no_think: Qwen3 deja de gastar el cupo en cadena de pensamiento.
    from .rules import MARCADOR_CORRECCION

    head = "/no_think\n"
    hc_block = _format_hc_context(hc)
    correccion_hint = ""
    if MARCADOR_CORRECCION in transcript:
        correccion_hint = (
            f"Si aparece {MARCADOR_CORRECCION}, esa seccion manda sobre el plan "
            "y la medicacion. No dejes en cambios_medicacion drogas retractadas "
            "en la correccion.\n\n"
        )
    if strict:
        return (
            head
            + "MODO ESTRICTO: tu respuesta completa debe ser UN objeto JSON. "
            "Primer caracter '{', ultimo '}'. Sin markdown.\n\n"
            + hc_block
            + correccion_hint
            + f"Transcript:\n{transcript}"
        )
    return (
        head
        + "Devolve la nota clinica como JSON segun el schema del system.\n\n"
        + hc_block
        + correccion_hint
        + f"Transcript de la consulta:\n\n{transcript}"
    )


def _content_text(final: object) -> str:
    for attr in ("content_text", "text", "content"):
        val = getattr(final, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


async def _complete_once(transport, model_id: str, history: list[dict]) -> str:
    from tetherto.qvac_sdk import completion

    base_kwargs = dict(
        model_id=model_id,
        history=history,
        generation_params={"temp": 0, "seed": 42, "predict": PREDICT_TOKENS},
        capture_thinking=False,
    )
    # Preferir JSON mode del runtime; si no existe o falla, caer a completion normal.
    try:
        run = completion(
            transport,
            **base_kwargs,
            response_format={"type": "json_object"},
        )
        final = await run.final
        text = _content_text(final)
        if text:
            return text
    except TypeError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("response_format json_object fallo (%s); reintento sin el", exc)

    run = completion(transport, **base_kwargs)
    final = await run.final
    return _content_text(final)


async def extraer_nota(
    transport,
    transcript: str,
    hc: PatientRecord | None = None,
) -> tuple[ClinicalNote | None, str | None]:
    """Extrae la nota. Devuelve (note, None) o (None, motivo_refusal).

    hc es contexto acotado (antecedentes/alergias/meds como referencia).
    La anti-invencion de farmacos sigue anclada al transcript.
    """
    from tetherto.qvac_sdk import load_model, unload_model
    from tetherto.qvac_sdk.models import QWEN3_4B_INST_Q4_K_M

    model_id = await load_model(
        transport,
        model_src=QWEN3_4B_INST_Q4_K_M,
        model_config={"ctx_size": 8192},
    )
    try:
        history: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_message(transcript, hc=hc)},
        ]
        ultimo_error = "sin intentos"

        for intento in range(1 + MAX_RETRIES):
            raw = await _complete_once(transport, model_id, history)
            preview = (raw[:240] + "...") if len(raw) > 240 else raw
            logger.info(
                "extract intento %s/%s raw_len=%s preview=%r",
                intento + 1,
                1 + MAX_RETRIES,
                len(raw),
                preview,
            )

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
                        "No inventes medicacion; incluye solo lo mencionado."
                    )
                return _canonizar_drogas(note), None
            except (ValueError, ValidationError, json.JSONDecodeError) as e:
                ultimo_error = str(e)
                if intento >= MAX_RETRIES:
                    break
                # Retry limpio: no reinyectar el dump fallido (suele ser thinking).
                history = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": _user_message(transcript, hc=hc, strict=True),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Error de validacion: {ultimo_error}\n"
                            "Responde de nuevo SOLO con el JSON corregido."
                        ),
                    },
                ]

        return None, f"no valido tras {1 + MAX_RETRIES} intentos: {ultimo_error}"
    finally:
        await unload_model(transport, model_id)
