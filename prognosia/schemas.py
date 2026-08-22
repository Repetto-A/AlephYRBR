"""Schemas de datos de Prognosia (Pydantic v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Antecedente(BaseModel):
    condicion: str
    severidad: str | None = None
    detalle: str | None = None


class MedicacionActual(BaseModel):
    droga: str
    dosis: str | None = None
    frecuencia: str | None = None
    via: str | None = None


class PatientRecord(BaseModel):
    """Historia clínica mínima del paciente (input `--hc`)."""

    patient_id: str
    nombre: str
    edad: int | None = None
    sexo: str | None = None
    antecedentes: list[Antecedente] = Field(default_factory=list)
    medicacion_actual: list[MedicacionActual] = Field(default_factory=list)
    alergias: list[str] = Field(default_factory=list)


class ProposedMed(BaseModel):
    """Medicación propuesta en la consulta, extraída del transcript."""

    nombre: str
    dosis: str | None = None
    frecuencia: str | None = None
    via: str | None = None
    evidencia: str | None = Field(
        default=None, description="Fragmento textual del transcript que la respalda."
    )


class ClinicalNote(BaseModel):
    """Nota SOAP extraída de la consulta."""

    subjetivo: str = ""
    objetivo: str = ""
    evaluacion: str = ""
    plan: str = ""
    medicacion_propuesta: list[ProposedMed] = Field(default_factory=list)


class SafetyFinding(BaseModel):
    """Hallazgo de una regla determinista de seguridad."""

    rule_id: str
    severidad: Literal["critical", "warning"]
    motivo: str
    evidencia_hc: str
    evidencia_consulta: str


class RunResult(BaseModel):
    """Resultado completo de una corrida del pipeline."""

    status: Literal["safe", "blocked", "escalate"]
    patient_id: str
    transcript: str
    transcript_source: Literal["audio", "texto"]
    note: ClinicalNote | None = None
    note_status: Literal["ok", "refused"] = "ok"
    note_refusal_motivo: str | None = None
    findings: list[SafetyFinding] = Field(default_factory=list)
    modelo_extraccion: str | None = None
    modelo_stt: str | None = None
    latencia_stt_s: float | None = None
    latencia_extraccion_s: float | None = None
