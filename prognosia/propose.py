"""Propuesta de registro en HCE — capa de 'agente ops' determinista.

No usa LLM. A partir de HC + RunResult arma:
  - delta SOAP a persistir
  - acciones de escritura (add/change/stop + SOAP + alerts)
  - gaps vs visitas previas y vs lo extraído del transcript

La safety ya decidió en rules.py; acá solo se traduce a un plan de
write-back auditable. Nada se escribe solo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .schemas import ClinicalNote, MedChange, PatientRecord, RunResult

_ROOT = Path(__file__).resolve().parent.parent
_PRIORS_PATH = _ROOT / "corpus" / "clinic" / "priors.json"


class WriteAction(BaseModel):
    action_id: str
    target: str  # p.ej. "encounter.note.soap", "meds.active.add"
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending_human", "blocked_by_safety", "skipped"] = "pending_human"


class ClinicalGap(BaseModel):
    gap_id: str
    severity: Literal["info", "warning"]
    title: str
    detail: str
    source: str  # "prior_visit" | "hc" | "guideline_local" | "transcript"


class HceProposal(BaseModel):
    """Salida del agente ops local (mock de write-back HCE)."""

    mode: Literal["local_qvac"] = "local_qvac"
    patient_id: str
    encounter_summary: str
    soap_delta: dict[str, str]
    write_actions: list[WriteAction] = Field(default_factory=list)
    gaps: list[ClinicalGap] = Field(default_factory=list)
    safety_gate: Literal["open", "closed"]
    human_required: bool = True
    note: str = (
        "Propuesta local. Ningún dato sale de la máquina ni se escribe en HCE "
        "sin aprobación humana explícita."
    )


HCEProposal = HceProposal


def _prior_from_encounter(enc: dict[str, Any]) -> dict[str, str]:
    fecha = (enc.get("approved_at") or "")[:10] or "s/f"
    soap = enc.get("soap") or {}
    bits: list[str] = []
    for key, label in (("A", "Eval"), ("P", "Plan")):
        val = (soap.get(key) or "").strip()
        if val:
            bits.append(f"{label}: {val[:140]}")
    if enc.get("vitales"):
        bits.append("Vitales registrados")
    ordenes = enc.get("ordenes") or []
    if ordenes:
        bits.append(f"Ordenes: {len(ordenes)}")
    seguimiento = enc.get("seguimiento") or {}
    plazo = (seguimiento.get("plazo") or "").strip()
    if plazo:
        bits.append(f"Seguimiento: {plazo}")
    if not bits:
        bits.append("Encuentro aprobado (sin detalle clinico adicional).")
    return {
        "fecha": fecha,
        "titulo": "Consulta previa",
        "hallazgo": " · ".join(bits),
    }


def _load_corpus_priors(patient_id: str) -> list[dict[str, str]]:
    if not _PRIORS_PATH.exists():
        return []
    try:
        data = json.loads(_PRIORS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    items = data.get(patient_id) or []
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fecha = str(item.get("fecha") or "s/f")
        titulo = str(item.get("titulo") or "Visita previa")
        hallazgo = str(item.get("hallazgo") or "").strip()
        if not hallazgo:
            continue
        out.append({"fecha": fecha, "titulo": titulo, "hallazgo": hallazgo})
    return out


def load_prior_visits(patient_id: str) -> list[dict[str, str]]:
    """Encuentros locales del paciente, o corpus/priors.json, o lista vacia."""
    from .store import list_encounters

    encounters = list_encounters(patient_id)
    if encounters:
        return [_prior_from_encounter(e) for e in encounters[-5:]]
    return _load_corpus_priors(patient_id)


def _soap_delta(note: ClinicalNote | None) -> dict[str, str]:
    if note is None:
        return {}
    return {
        "S": note.subjetivo or "",
        "O": note.objetivo or "",
        "A": note.evaluacion or "",
        "P": note.plan or "",
    }


def _iter_med_changes(note: ClinicalNote) -> list[MedChange]:
    if note.cambios_medicacion:
        return list(note.cambios_medicacion)
    # Compat: medicacion_propuesta → add
    return [
        MedChange(
            accion="add",
            nombre=m.nombre,
            dosis=m.dosis,
            frecuencia=m.frecuencia,
            via=m.via,
            evidencia=m.evidencia,
        )
        for m in note.medicacion_propuesta
        if m.nombre.strip()
    ]


def _med_actions(hc: PatientRecord, result: RunResult) -> list[WriteAction]:
    actions: list[WriteAction] = []
    note = result.note
    if note is None:
        return actions

    actuales = {m.droga.lower(): m for m in hc.medicacion_actual}
    blocked = result.status == "blocked"

    for i, cambio in enumerate(_iter_med_changes(note)):
        nombre = cambio.nombre.strip()
        if not nombre:
            continue
        key = nombre.lower()
        already = key in actuales
        aid = f"med-{i+1}"

        if cambio.accion == "stop":
            actions.append(
                WriteAction(
                    action_id=aid,
                    target="meds.active.stop",
                    summary=(
                        f"No suspender {nombre} (bloqueado por safety)"
                        if blocked
                        else (
                            f"Suspender {nombre}"
                            if already
                            else f"Suspender {nombre} (no está en HC — revisar)"
                        )
                    ),
                    payload=cambio.model_dump(),
                    status="blocked_by_safety" if blocked else "pending_human",
                )
            )
            continue

        if cambio.accion == "change":
            actions.append(
                WriteAction(
                    action_id=aid,
                    target="meds.active.change",
                    summary=(
                        f"No ajustar {nombre} (bloqueado por safety)"
                        if blocked
                        else (
                            f"Ajustar {nombre} a {cambio.dosis or '?'} "
                            f"{cambio.frecuencia or ''}".strip()
                            if already
                            else f"Ajustar {nombre} (no está en HC — tratar como alta)"
                        )
                    ),
                    payload=cambio.model_dump(),
                    status="blocked_by_safety" if blocked else "pending_human",
                )
            )
            continue

        # add
        actions.append(
            WriteAction(
                action_id=aid,
                target="meds.active.add",
                summary=(
                    f"No agregar {nombre}: retenido por seguridad"
                    if blocked
                    else (
                        f"Confirmar {nombre} ya en HC"
                        if already
                        else f"Agregar {nombre} a medicación activa"
                    )
                ),
                payload=cambio.model_dump(),
                status="blocked_by_safety" if blocked else "pending_human",
            )
        )
    return actions


def _gaps_for(hc: PatientRecord, result: RunResult) -> list[ClinicalGap]:
    gaps: list[ClinicalGap] = []
    pid = hc.patient_id
    note = result.note
    low = (result.transcript or "").lower()

    for i, prior in enumerate(load_prior_visits(pid)):
        gaps.append(
            ClinicalGap(
                gap_id=f"prior-{i+1}",
                severity="warning",
                title=f"Visita {prior['fecha']}: {prior['titulo']}",
                detail=prior["hallazgo"],
                source="prior_visit",
            )
        )

    if any(a.condicion.lower().startswith("asma") for a in hc.antecedentes):
        tiene_peak_pendiente = any(
            "peak" in (e.detalle or "").lower()
            and e.estado in ("pedido", "pendiente_resultado")
            for e in hc.estudios
        )
        gaps.append(
            ClinicalGap(
                gap_id="asma-peakflow",
                severity="warning",
                title="Peak flow / control funcional",
                detail=(
                    "HC documenta asma severa; hay peak flow pedido sin resultado."
                    if tiene_peak_pendiente
                    else (
                        "HC documenta asma severa; no hay peak flow ni espirometría "
                        "citada en esta consulta."
                    )
                ),
                source="hc",
            )
        )
        if result.status == "blocked":
            gaps.append(
                ClinicalGap(
                    gap_id="asma-bb-alert",
                    severity="warning",
                    title="Alerta de medicación no reflejada en HC",
                    detail=(
                        "Se detectó un riesgo con betabloqueantes. Si corregís el "
                        "plan, conviene dejar anotada la contraindicación en la HC."
                    ),
                    source="guideline_local",
                )
            )

    if any("hipertens" in a.condicion.lower() for a in hc.antecedentes):
        gaps.append(
            ClinicalGap(
                gap_id="hta-home-bp",
                severity="info",
                title="PA domiciliaria",
                detail="Útil pedir registro de PA en domicilio antes del próximo control.",
                source="hc",
            )
        )

    if hc.alergias:
        gaps.append(
            ClinicalGap(
                gap_id="allergies-ack",
                severity="info",
                title="Alergias en HC",
                detail="Confirmadas en HC: " + "; ".join(hc.alergias),
                source="hc",
            )
        )

    pendientes = [
        e
        for e in hc.estudios
        if e.estado in ("pedido", "pendiente_resultado")
    ]
    for i, est in enumerate(pendientes[:3]):
        gaps.append(
            ClinicalGap(
                gap_id=f"estudio-pendiente-{i+1}",
                severity="warning",
                title=f"Estudio sin resultado: {est.detalle}",
                detail=(
                    f"Estado «{est.estado}»"
                    + (f" · pedido {est.pedido_en}" if est.pedido_en else "")
                    + ". Cargar resultado o cancelar en la próxima revisión."
                ),
                source="hc",
            )
        )

    # Gaps derivados del transcript / extracción (no solo _PRIOR).
    if note is not None:
        v = note.vitales
        has_vitals = v is not None and any(
            [v.fc, v.pa, v.sat, v.temperatura, v.peso_kg]
        )
        mentions_vitals = any(
            k in low
            for k in (
                "frecuencia",
                "tensión",
                "tension",
                "presión",
                "presion",
                "mmhg",
                "saturación",
                "saturacion",
            )
        )
        if mentions_vitals and not has_vitals:
            gaps.append(
                ClinicalGap(
                    gap_id="vitals-unstructured",
                    severity="info",
                    title="Vitales en transcript sin estructurar",
                    detail=(
                        "El transcript menciona signos vitales pero no quedaron "
                        "parseados en vitales{}."
                    ),
                    source="transcript",
                )
            )

        if note.seguimiento is None or not (note.seguimiento.plazo or "").strip():
            if any(k in low for k in ("control", "semanas", "meses", "seguimiento")):
                gaps.append(
                    ClinicalGap(
                        gap_id="followup-missing",
                        severity="info",
                        title="Seguimiento no estructurado",
                        detail=(
                            "Se habla de control/seguimiento en el transcript pero "
                            "seguimiento.plazo quedó vacío."
                        ),
                        source="transcript",
                    )
                )

        if not note.ordenes and any(
            k in low for k in ("laboratorio", "lab ", "espirometría", "espirometria", "deriv")
        ):
            gaps.append(
                ClinicalGap(
                    gap_id="orders-missing",
                    severity="info",
                    title="Órdenes posibles no estructuradas",
                    detail=(
                        "El transcript sugiere labs/estudios/derivación sin entradas "
                        "en ordenes[]."
                    ),
                    source="transcript",
                )
            )
    elif any(k in low for k in ("laboratorio", "control en", "tensión", "tension")):
        gaps.append(
            ClinicalGap(
                gap_id="extract-empty",
                severity="warning",
                title="Sin nota estructurada",
                detail="Hay señales clínicas en el transcript pero la extracción falló.",
                source="transcript",
            )
        )

    return gaps


def build_proposal(hc: PatientRecord, result: RunResult) -> HceProposal:
    """Arma la propuesta HCE a partir de HC + resultado del pipeline."""
    gate: Literal["open", "closed"] = (
        "closed" if result.status == "blocked" else "open"
    )
    soap = _soap_delta(result.note)

    write_actions: list[WriteAction] = [
        WriteAction(
            action_id="soap-1",
            target="encounter.note.soap",
            summary="Guardar la nota de esta consulta",
            payload=soap,
            status="pending_human" if soap else "skipped",
        )
    ]
    write_actions.extend(_med_actions(hc, result))

    if result.note and result.note.alergias_mencionadas:
        known = {a.lower() for a in hc.alergias}
        for i, al in enumerate(result.note.alergias_mencionadas):
            sustancia = (al.sustancia or "").strip()
            if not sustancia:
                continue
            already = sustancia.lower() in known or any(
                sustancia.lower() in k for k in known
            )
            write_actions.append(
                WriteAction(
                    action_id=f"allergy-{i+1}",
                    target="allergies.add",
                    summary=(
                        f"Confirmar alergia ya en HC: {sustancia}"
                        if already
                        else f"Agregar alergia a HC: {sustancia}"
                    ),
                    payload=al.model_dump(),
                    status="pending_human",
                )
            )

    if result.note and result.note.ordenes:
        for i, order in enumerate(result.note.ordenes):
            write_actions.append(
                WriteAction(
                    action_id=f"order-{i+1}",
                    target=f"orders.{order.tipo}",
                    summary=f"Registrar orden ({order.tipo}): {order.detalle}",
                    payload=order.model_dump(),
                    status="pending_human",
                )
            )

    if result.note and result.note.seguimiento and result.note.seguimiento.plazo:
        write_actions.append(
            WriteAction(
                action_id="followup-1",
                target="encounter.followup",
                summary=f"Agendar control: {result.note.seguimiento.plazo}",
                payload=result.note.seguimiento.model_dump(),
                status="pending_human",
            )
        )

    if result.note and result.note.vitales:
        v = result.note.vitales
        if any([v.fc, v.pa, v.sat, v.temperatura, v.peso_kg]):
            write_actions.append(
                WriteAction(
                    action_id="vitals-1",
                    target="encounter.vitals",
                    summary="Persistir signos vitales de la consulta",
                    payload=v.model_dump(),
                    status="pending_human",
                )
            )

    if result.findings:
        write_actions.append(
            WriteAction(
                action_id="safety-1",
                target="encounter.alerts",
                summary="Dejar registrada la alerta de seguridad en la evolución",
                payload={
                    "status": result.status,
                    "findings": [f.model_dump() for f in result.findings],
                },
                status="pending_human",
            )
        )
        # Snippets de guía local citados en el draft (si hubo match).
        for i, f in enumerate(result.findings):
            if f.guia is None:
                continue
            write_actions.append(
                WriteAction(
                    action_id=f"guide-{i+1}",
                    target="encounter.evidence",
                    summary=f"Citar guía local: {f.guia.title}",
                    payload=f.guia.model_dump(),
                    status="pending_human",
                )
            )

    summary = (
        f"Consulta {result.patient_id}: status={result.status}, "
        f"fuente={result.transcript_source}, "
        f"acciones={sum(1 for a in write_actions if a.status == 'pending_human')} "
        f"pendientes de humano."
    )

    return HceProposal(
        patient_id=result.patient_id,
        encounter_summary=summary,
        soap_delta=soap,
        write_actions=write_actions,
        gaps=_gaps_for(hc, result),
        safety_gate=gate,
        human_required=True,
    )
