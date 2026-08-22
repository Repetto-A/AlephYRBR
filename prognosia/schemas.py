"""Schemas de datos de Prognosia (Pydantic v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Antecedente(BaseModel):
    condicion: str
    severidad: str | None = None
    detalle: str | None = None


class MedicacionActual(BaseModel):
    droga: str
    dosis: str | None = None
    frecuencia: str | None = None
    via: str | None = None


class EstudioRegistro(BaseModel):
    """Pedido o resultado de lab/estudio/derivación en la HC."""

    estudio_id: str
    tipo: Literal["lab", "estudio", "derivacion", "otro"] = "otro"
    detalle: str
    estado: Literal["pedido", "pendiente_resultado", "con_resultado", "cancelado"] = (
        "pedido"
    )
    pedido_en: str | None = None
    resultado: str | None = None
    resultado_en: str | None = None
    evidencia: str | None = None
    encounter_id: str | None = None


class PatientRecord(BaseModel):
    """Historia clínica mínima del paciente (input `--hc`)."""

    patient_id: str
    nombre: str
    edad: int | None = None
    sexo: str | None = None
    antecedentes: list[Antecedente] = Field(default_factory=list)
    medicacion_actual: list[MedicacionActual] = Field(default_factory=list)
    alergias: list[str] = Field(default_factory=list)
    estudios: list[EstudioRegistro] = Field(default_factory=list)


class ProposedMed(BaseModel):
    """Medicación propuesta en la consulta (compat: altas nuevas)."""

    nombre: str
    dosis: str | None = None
    frecuencia: str | None = None
    via: str | None = None
    evidencia: str | None = Field(
        default=None, description="Fragmento textual del transcript que la respalda."
    )


class MedChange(BaseModel):
    """Cambio de medicación detectado en el transcript."""

    accion: Literal["add", "change", "stop"]
    nombre: str
    dosis: str | None = None
    frecuencia: str | None = None
    via: str | None = None
    evidencia: str | None = None


class VitalSigns(BaseModel):
    """Signos vitales estructurados (si aparecen en el transcript)."""

    fc: int | None = None
    pa: str | None = None
    sat: int | None = None
    temperatura: float | None = None
    peso_kg: float | None = None
    evidencia: str | None = None


class AllergyMention(BaseModel):
    sustancia: str
    reaccion: str | None = None
    evidencia: str | None = None


class ClinicalOrder(BaseModel):
    tipo: Literal["lab", "estudio", "derivacion", "otro"] = "otro"
    detalle: str
    evidencia: str | None = None


class FollowUp(BaseModel):
    plazo: str | None = None
    evidencia: str | None = None


class ClinicalNote(BaseModel):
    """Nota SOAP + entidades clínicas útiles extraídas del transcript."""

    subjetivo: str = ""
    objetivo: str = ""
    evaluacion: str = ""
    plan: str = ""
    medicacion_propuesta: list[ProposedMed] = Field(default_factory=list)
    cambios_medicacion: list[MedChange] = Field(default_factory=list)
    vitales: VitalSigns | None = None
    alergias_mencionadas: list[AllergyMention] = Field(default_factory=list)
    ordenes: list[ClinicalOrder] = Field(default_factory=list)
    seguimiento: FollowUp | None = None

    @model_validator(mode="after")
    def _sync_meds_propuestas(self) -> ClinicalNote:
        """Si hay cambios add y medicacion_propuesta vacía, espejar para compat."""
        if self.medicacion_propuesta:
            return self
        adds = [c for c in self.cambios_medicacion if c.accion == "add"]
        if not adds:
            return self
        self.medicacion_propuesta = [
            ProposedMed(
                nombre=c.nombre,
                dosis=c.dosis,
                frecuencia=c.frecuencia,
                via=c.via,
                evidencia=c.evidencia,
            )
            for c in adds
        ]
        return self


class LocalGuideHit(BaseModel):
    """Snippet de guía local offline (RAG lexical o lookup por rule_id)."""

    guide_id: str
    title: str
    citation: str
    source: str
    mode: Literal["local_rag", "local_lookup"] = "local_rag"
    score: float | None = None
    section: str | None = None
    doc_id: str | None = None


class SafetyFinding(BaseModel):
    """Hallazgo de una regla determinista de seguridad."""

    rule_id: str
    severidad: Literal["critical", "warning"]
    motivo: str
    evidencia_hc: str
    evidencia_consulta: str
    guia: LocalGuideHit | None = None
    rag_snippets: list[LocalGuideHit] = Field(default_factory=list)


class TranscriptCorrection(BaseModel):
    kind: Literal["phrase", "drug", "vitals"]
    original: str
    replacement: str


class RunResult(BaseModel):
    """Resultado completo de una corrida del pipeline."""

    status: Literal["safe", "blocked", "escalate"]
    patient_id: str
    transcript: str
    transcript_source: Literal["audio", "texto"]
    transcript_raw: str | None = None
    transcript_corrections: list[TranscriptCorrection] = Field(default_factory=list)
    transcript_correccion: str | None = None
    note: ClinicalNote | None = None
    note_status: Literal["ok", "refused"] = "ok"
    note_refusal_motivo: str | None = None
    findings: list[SafetyFinding] = Field(default_factory=list)
    modelo_extraccion: str | None = None
    modelo_stt: str | None = None
    latencia_stt_s: float | None = None
    latencia_extraccion_s: float | None = None
