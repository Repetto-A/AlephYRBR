"""Propuesta de registro en HCE — capa de 'agente ops' determinista.

No usa LLM. A partir de HC + RunResult arma:
  - delta SOAP a persistir
  - acciones de escritura propuestas (siempre pending_human)
  - gaps vs visitas previas sintéticas (lo que el médico podría no haber mirado)

La safety ya decidió en rules.py; acá solo se traduce a un plan de
write-back auditable. Nada se escribe solo.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .schemas import ClinicalNote, PatientRecord, RunResult


class WriteAction(BaseModel):
    action_id: str
    target: str  # p.ej. "encounter.note.soap", "meds.active"
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending_human", "blocked_by_safety", "skipped"] = "pending_human"


class ClinicalGap(BaseModel):
    gap_id: str
    severity: Literal["info", "warning"]
    title: str
    detail: str
    source: str  # "prior_visit" | "hc" | "guideline_local"


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


# Alias estable por si algún caller usa la capitalización HCE.
HCEProposal = HceProposal


# Visitas previas sintéticas (atmósfera de producto; no son FHIR real).
_PRIOR: dict[str, list[dict[str, str]]] = {
    "HC-A-001": [
        {
            "fecha": "2026-03-12",
            "titulo": "Control asma",
            "hallazgo": "Peak flow no registrado en la última visita.",
        },
        {
            "fecha": "2026-01-28",
            "titulo": "Exacerbación leve",
            "hallazgo": "Corticoide oral 5 días; sin spirometría de control documentada.",
        },
    ],
    "HC-B-001": [
        {
            "fecha": "2026-02-15",
            "titulo": "Control HTA",
            "hallazgo": "PA en consultorio 128/82; falta registro de PA domiciliaria.",
        },
        {
            "fecha": "2025-11-10",
            "titulo": "Ajuste enalapril",
            "hallazgo": "Creatinina y K+ de control pendientes de cargar.",
        },
    ],
}


def _soap_delta(note: ClinicalNote | None) -> dict[str, str]:
    if note is None:
        return {}
    return {
        "S": note.subjetivo or "",
        "O": note.objetivo or "",
        "A": note.evaluacion or "",
        "P": note.plan or "",
    }


def _med_actions(
    hc: PatientRecord, result: RunResult
) -> list[WriteAction]:
    actions: list[WriteAction] = []
    note = result.note
    if note is None:
        return actions

    actuales = {m.droga.lower() for m in hc.medicacion_actual}
    for i, med in enumerate(note.medicacion_propuesta):
        nombre = med.nombre.strip()
        if not nombre:
            continue
        already = nombre.lower() in actuales
        blocked = result.status == "blocked"
        actions.append(
            WriteAction(
                action_id=f"med-{i+1}",
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
                payload={
                    "nombre": nombre,
                    "dosis": med.dosis,
                    "frecuencia": med.frecuencia,
                    "via": med.via,
                    "evidencia": med.evidencia,
                },
                status="blocked_by_safety" if blocked else "pending_human",
            )
        )
    return actions


def _gaps_for(hc: PatientRecord, result: RunResult) -> list[ClinicalGap]:
    gaps: list[ClinicalGap] = []
    pid = hc.patient_id
    for i, prior in enumerate(_PRIOR.get(pid, [])):
        gaps.append(
            ClinicalGap(
                gap_id=f"prior-{i+1}",
                severity="warning",
                title=f"Visita {prior['fecha']}: {prior['titulo']}",
                detail=prior["hallazgo"],
                source="prior_visit",
            )
        )

    # Gaps derivados de HC + estado de safety (sin LLM).
    if any(a.condicion.lower().startswith("asma") for a in hc.antecedentes):
        gaps.append(
            ClinicalGap(
                gap_id="asma-peakflow",
                severity="warning",
                title="Peak flow / control funcional",
                detail=(
                    "HC documenta asma severa; no hay peak flow ni espirometría "
                    "citada en esta consulta."
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
