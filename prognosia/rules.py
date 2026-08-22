"""Reglas deterministas de seguridad. Sin LLM en la decisión.

Regla v1 (near-miss del kickoff): si la HC registra asma (severa) y la
consulta (transcript crudo y/o medicación extraída) menciona un
betabloqueante no selectivo → BLOCKED.

La regla evalúa el TRANSCRIPT CRUDO además de la nota extraída, así la
decisión de safety nunca depende de que el LLM haya extraído bien.
"""

from __future__ import annotations

import re
import unicodedata

from .schemas import ClinicalNote, PatientRecord, SafetyFinding

# Patrones tolerantes a variantes de transcripción (ver docs/spike-voz.md).
# Betabloqueantes no selectivos (y mixtos alfa-beta) contraindicados en asma.
BETA_BLOCKER_PATTERNS: dict[str, re.Pattern[str]] = {
    "propranolol": re.compile(r"propr?an[oa]lol", re.IGNORECASE),
    "nadolol": re.compile(r"nadolol", re.IGNORECASE),
    "timolol": re.compile(r"timolol", re.IGNORECASE),
    "sotalol": re.compile(r"sotalol", re.IGNORECASE),
    "pindolol": re.compile(r"pindolol", re.IGNORECASE),
    "carvedilol": re.compile(r"carvedilol", re.IGNORECASE),
    "labetalol": re.compile(r"labetalol", re.IGNORECASE),
}

ASMA_PATTERN = re.compile(r"\basma\b", re.IGNORECASE)
SEVERA_PATTERN = re.compile(r"sever[ao]|grave", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Minúsculas y sin tildes, para matching robusto."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def hc_tiene_asma_severa(hc: PatientRecord) -> str | None:
    """Devuelve la evidencia textual de la HC si hay asma severa, o None."""
    for ant in hc.antecedentes:
        campo = _normalize(f"{ant.condicion} {ant.severidad or ''} {ant.detalle or ''}")
        if ASMA_PATTERN.search(campo) and SEVERA_PATTERN.search(campo):
            partes = [ant.condicion]
            if ant.severidad:
                partes.append(ant.severidad)
            if ant.detalle:
                partes.append(ant.detalle)
            return " — ".join(partes)
    return None


def buscar_betabloqueante(texto: str) -> tuple[str, str] | None:
    """Busca un betabloqueante no selectivo en el texto.

    Devuelve (droga, fragmento de evidencia) o None.
    """
    normalizado = _normalize(texto)
    for droga, pattern in BETA_BLOCKER_PATTERNS.items():
        m = pattern.search(normalizado)
        if m:
            ini = max(0, m.start() - 60)
            fin = min(len(texto), m.end() + 60)
            return droga, texto[ini:fin].strip()
    return None


def evaluar_safety(
    hc: PatientRecord, transcript: str, note: ClinicalNote | None
) -> list[SafetyFinding]:
    """Aplica las reglas deterministas. Devuelve los hallazgos (vacío = safe)."""
    findings: list[SafetyFinding] = []

    evidencia_asma = hc_tiene_asma_severa(hc)
    if evidencia_asma is None:
        return findings

    # Fuente 1: el transcript crudo (no depende del LLM).
    hit = buscar_betabloqueante(transcript)
    # Fuente 2: la medicación extraída por el LLM (defensa en profundidad).
    if hit is None and note is not None:
        for med in note.medicacion_propuesta:
            hit = buscar_betabloqueante(med.nombre)
            if hit:
                hit = (hit[0], med.evidencia or med.nombre)
                break

    if hit:
        droga, evidencia_consulta = hit
        findings.append(
            SafetyFinding(
                rule_id="asma-severa-betabloqueante-v1",
                severidad="critical",
                motivo=(
                    f"La HC registra asma severa y la consulta propone {droga}, "
                    "un betabloqueante contraindicado por riesgo de broncoespasmo "
                    "potencialmente fatal."
                ),
                evidencia_hc=evidencia_asma,
                evidencia_consulta=evidencia_consulta,
            )
        )
    return findings


def decidir_status(findings: list[SafetyFinding]) -> str:
    return "blocked" if any(f.severidad == "critical" for f in findings) else "safe"
