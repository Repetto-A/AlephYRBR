"""Reglas deterministas de seguridad. Sin LLM en la decisión.

Reglas v1:
  - asma severa + betabloqueante no selectivo → BLOCKED (critical)
  - alergia documentada en HC mencionada en el plan/transcript → BLOCKED

La regla evalúa el TRANSCRIPT CRUDO además de la nota extraída, así la
decisión de safety nunca depende de que el LLM haya extraído bien.
"""

from __future__ import annotations

import re
import unicodedata

from .schemas import ClinicalNote, PatientRecord, SafetyFinding

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

# Alias de alérgenos frecuentes (clave = forma canónica normalizada).
ALLERGEN_ALIASES: dict[str, list[str]] = {
    "acido acetilsalicilico": [
        "acido acetilsalicilico",
        "acetilsalicilico",
        "aspirina",
        "aspirin",
        "aas",
        "asa",
    ],
    "penicilina": ["penicilina", "penicillin", "amoxicilina", "ampicilina"],
    "ibuprofeno": ["ibuprofeno", "ibuprofen"],
    "metamizol": ["metamizol", "dipirona"],
}


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
    """Busca un betabloqueante no selectivo indicado (no retractado) en el texto.

    Devuelve (droga, fragmento de evidencia) o None.
    """
    normalizado = _normalize(texto)
    for droga, pattern in BETA_BLOCKER_PATTERNS.items():
        if not mencion_afirmativa(pattern, texto):
            continue
        m = pattern.search(normalizado)
        if m:
            ini = max(0, m.start() - 60)
            fin = min(len(texto), m.end() + 60)
            return droga, texto[ini:fin].strip()
    return None


def _canonical_allergen(label: str) -> tuple[str, list[str]]:
    """Mapea un string de alergia HC a (canon, alias list)."""
    norm = _normalize(label)
    for canon, aliases in ALLERGEN_ALIASES.items():
        if any(a in norm for a in aliases) or canon in norm:
            return canon, aliases
    # Fallback: tokens alfanuméricos del label (≥4 chars).
    tokens = [t for t in re.split(r"[^a-z0-9]+", norm) if len(t) >= 4]
    return norm[:40], tokens or [norm]


def _snippet_around(texto: str, needle: str) -> str:
    low = _normalize(texto)
    n = _normalize(needle)
    idx = low.find(n)
    if idx < 0:
        return needle
    ini = max(0, idx - 40)
    fin = min(len(texto), idx + len(needle) + 40)
    return texto[ini:fin].strip()


def buscar_alergia_en_consulta(
    hc: PatientRecord, transcript: str, note: ClinicalNote | None
) -> SafetyFinding | None:
    """Si el plan/transcript menciona un alérgeno documentado en HC → critical."""
    if not hc.alergias:
        return None

    corpus_parts = [transcript]
    if note is not None:
        corpus_parts.extend([note.plan, note.evaluacion, note.objetivo])
        for m in note.medicacion_propuesta:
            corpus_parts.append(m.nombre)
            if m.evidencia:
                corpus_parts.append(m.evidencia)
        for c in note.cambios_medicacion:
            corpus_parts.append(c.nombre)
            if c.evidencia:
                corpus_parts.append(c.evidencia)
        for a in note.alergias_mencionadas:
            corpus_parts.append(a.sustancia)
    corpus = "\n".join(p for p in corpus_parts if p)
    corpus_norm = _normalize(corpus)

    for alergia in hc.alergias:
        _canon, aliases = _canonical_allergen(alergia)
        hit = None
        for alias in aliases:
            if not alias:
                continue
            # Aliases cortos (aas/asa) exigen límite de palabra para evitar FPs.
            if len(alias) <= 3:
                if re.search(rf"\b{re.escape(alias)}\b", corpus_norm):
                    hit = alias
                    break
            elif alias in corpus_norm:
                hit = alias
                break
        if hit is None:
            continue
        flags = re.IGNORECASE
        pat = (
            re.compile(rf"\b{re.escape(hit)}\b", flags)
            if len(hit) <= 3
            else re.compile(re.escape(hit), flags)
        )
        if not mencion_afirmativa(pat, corpus):
            continue
        return SafetyFinding(
            rule_id="alergia-hc-vs-plan-v1",
            severidad="critical",
            motivo=(
                f"La HC documenta alergia a «{alergia}» y la consulta menciona "
                f"«{hit}» en el plan o transcript. No indicar sin revisión."
            ),
            evidencia_hc=alergia,
            evidencia_consulta=_snippet_around(transcript or corpus, hit),
        )
    return None


def evaluar_safety(
    hc: PatientRecord, transcript: str, note: ClinicalNote | None
) -> list[SafetyFinding]:
    """Aplica las reglas deterministas. Devuelve los hallazgos (vacío = safe)."""
    findings: list[SafetyFinding] = []

    evidencia_asma = hc_tiene_asma_severa(hc)
    if evidencia_asma is not None:
        hit = buscar_betabloqueante(transcript)
        if hit is None and note is not None:
            for med in note.medicacion_propuesta:
                hit = buscar_betabloqueante(med.nombre)
                if hit:
                    hit = (hit[0], med.evidencia or med.nombre)
                    break
            if hit is None:
                for cambio in note.cambios_medicacion:
                    hit = buscar_betabloqueante(cambio.nombre)
                    if hit:
                        hit = (hit[0], cambio.evidencia or cambio.nombre)
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

    alergia = buscar_alergia_en_consulta(hc, transcript, note)
    if alergia is not None:
        findings.append(alergia)

    return findings


def decidir_status(findings: list[SafetyFinding]) -> str:
    return "blocked" if any(f.severidad == "critical" for f in findings) else "safe"


MARCADOR_CORRECCION = "[Corrección del médico]"

# Ventana a la izquierda del match: "no indico X" / "en lugar de X".
_RETRACT_WINDOW = 56
_RETRACT_RE = re.compile(
    r"\b("
    r"no|nunca|retiro|retirar|suspendo|suspender|cancelo|cancelar|"
    r"equivoc|en vez de|en lugar de|descarto|descartar|"
    r"corrijo|corregir|cambio|cambiar|reemplaz|saco|sacamos"
    r")\b",
    re.IGNORECASE,
)


def mencion_afirmativa(pattern: re.Pattern[str], texto: str) -> bool:
    """True si la droga/alérgeno aparece en el texto sin marcador de retractación."""
    normalizado = _normalize(texto)
    for m in pattern.finditer(normalizado):
        ini = max(0, m.start() - _RETRACT_WINDOW)
        if _RETRACT_RE.search(normalizado[ini : m.start()]):
            continue
        return True
    return False


def _mask_pattern(texto: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub("[indicación retirada]", texto)


def texto_consulta_efectivo(original: str, correccion: str) -> str:
    """Texto sobre el que corren las reglas tras una corrección del plan.

    El original queda en el transcript completo (auditoría + extracción).
    Para safety, las indicaciones retractadas no cuentan: si no, el
    propranolol de la primera pasada dejaría el run blocked para siempre.
    Si la corrección reafirma la droga, sigue blocked.
    """
    corr = (correccion or "").strip()
    if not corr:
        return original
    if len(corr.split()) < 3:
        return f"{original.rstrip()}\n\n{MARCADOR_CORRECCION}: {corr}"

    masked = original
    for _droga, pattern in BETA_BLOCKER_PATTERNS.items():
        if pattern.search(_normalize(original)) and not mencion_afirmativa(
            pattern, corr
        ):
            masked = _mask_pattern(masked, pattern)

    orig_norm = _normalize(original)
    for _canon, aliases in ALLERGEN_ALIASES.items():
        hits = [a for a in aliases if a and (a in orig_norm or orig_norm.find(a) >= 0)]
        if not hits:
            continue
        affirmed = False
        for alias in aliases:
            if not alias:
                continue
            flags = re.IGNORECASE
            pat = (
                re.compile(rf"\b{re.escape(alias)}\b", flags)
                if len(alias) <= 3
                else re.compile(re.escape(alias), flags)
            )
            if mencion_afirmativa(pat, corr):
                affirmed = True
                break
        if affirmed:
            continue
        for alias in sorted(aliases, key=len, reverse=True):
            if not alias:
                continue
            flags = re.IGNORECASE
            pat = (
                re.compile(rf"\b{re.escape(alias)}\b", flags)
                if len(alias) <= 3
                else re.compile(re.escape(alias), flags)
            )
            masked = _mask_pattern(masked, pat)

    return f"{masked.rstrip()}\n\n{MARCADOR_CORRECCION}: {corr}"


def filtrar_nota_por_correccion(note: ClinicalNote | None, correccion: str):
    """Saca del plan extraído drogas retractadas (el LLM a veces las copia del original)."""
    if note is None or not (correccion or "").strip():
        return note

    def _afirmado(nombre: str) -> bool:
        n = _normalize(nombre)
        for _droga, pattern in BETA_BLOCKER_PATTERNS.items():
            if pattern.search(n):
                return mencion_afirmativa(pattern, correccion)
        for _canon, aliases in ALLERGEN_ALIASES.items():
            if any(a and a in n for a in aliases) or _canon in n:
                for alias in aliases:
                    if not alias or len(alias) <= 3:
                        continue
                    pat = re.compile(re.escape(alias), re.IGNORECASE)
                    if mencion_afirmativa(pat, correccion):
                        return True
                return False
        return True

    note.medicacion_propuesta = [
        m for m in note.medicacion_propuesta if _afirmado(m.nombre)
    ]
    note.cambios_medicacion = [
        c
        for c in note.cambios_medicacion
        if c.accion == "stop" or _afirmado(c.nombre)
    ]
    return note
