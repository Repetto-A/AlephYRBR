"""Léxico clínico post-STT: corrige distorsiones típicas de Whisper.

Determinista, 100% local. Se aplica al transcript (audio o texto) antes
de la extracción LLM y de las reglas de safety, para que el modelo y las
regex «entiendan» mejor el plan y los vitales.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

_LEXICON_PATH = Path(__file__).resolve().parent.parent / "corpus" / "clinic" / "lexicon.json"

# Números en palabras (español) usados en vitales del corpus demo.
_UNITS: dict[str, int] = {
    "cero": 0,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintiun": 21,
    "veintiún": 21,
    "veintidos": 22,
    "veintidós": 22,
    "veintitres": 23,
    "veintitrés": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintiséis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}

_HUNDREDS: dict[str, int] = {
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "trescientos": 300,
}


@dataclass
class LexiconCorrection:
    kind: str  # phrase | drug | vitals
    original: str
    replacement: str


@dataclass
class LexiconResult:
    text: str
    corrections: list[LexiconCorrection] = field(default_factory=list)
    raw: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.corrections)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(_LEXICON_PATH.read_text(encoding="utf-8"))


def whisper_prompt() -> str:
    return str(_load().get("whisper_prompt") or "").strip()


def drug_canonicals() -> list[str]:
    return [d["canonical"] for d in _load().get("drugs") or []]


def resolve_drug_name(nombre: str) -> str | None:
    """Si el nombre (posiblemente distorsionado) matchea el léxico, canónico."""
    n = _normalize(nombre.strip())
    if not n:
        return None
    best: tuple[float, str] | None = None
    for d in _load().get("drugs") or []:
        canon = d["canonical"]
        candidates = [_normalize(canon), *(_normalize(a) for a in d.get("aliases") or [])]
        for c in candidates:
            if not c:
                continue
            if n == c or (len(n) >= 5 and (n in c or c in n)):
                return canon
            ratio = SequenceMatcher(None, n, c).ratio()
            if ratio >= 0.78 and (best is None or ratio > best[0]):
                best = (ratio, canon)
    return best[1] if best else None


def drug_mentioned(nombre: str, transcript: str) -> bool:
    """True si la droga (o alias/fuzzy) aparece en el transcript."""
    if resolve_drug_name(nombre) is None and len(_normalize(nombre)) < 4:
        return False
    normalizado = _normalize(transcript)
    n = _normalize(nombre)
    if n and (n in normalizado or n[: max(6, len(n) - 3)] in normalizado):
        return True
    canon = resolve_drug_name(nombre)
    if canon and _normalize(canon) in normalizado:
        return True
    if canon:
        for d in _load().get("drugs") or []:
            if d["canonical"] != canon:
                continue
            for a in d.get("aliases") or []:
                an = _normalize(a)
                if an and an in normalizado:
                    return True
    # Fuzzy token-level
    tokens = re.findall(r"[a-z0-9]{5,}", normalizado)
    target = _normalize(canon or nombre)
    for tok in tokens:
        if SequenceMatcher(None, tok, target).ratio() >= 0.82:
            return True
    return False


def _parse_spanish_number(phrase: str) -> int | None:
    """Parsea frases tipo 'noventa y seis' / 'ciento treinta' → int."""
    raw = _normalize(phrase)
    raw = raw.replace("-", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)

    total = 0
    parts = raw.split()
    i = 0
    while i < len(parts):
        p = parts[i]
        if p in ("y", "con"):
            i += 1
            continue
        if p in _HUNDREDS:
            total += _HUNDREDS[p]
            i += 1
            continue
        if p in _UNITS:
            total += _UNITS[p]
            i += 1
            continue
        # "treinta y seis" ya cubierto; token desconocido → abortar
        return None
    return total if total > 0 else None


_NUM_WORDS = (
    r"(?:ciento|cien|doscientos|trescientos|veinti[uú]n|veintiún|veintidos|veintidós|"
    r"veintitres|veintitrés|veinticuatro|veinticinco|veintiseis|veintiséis|"
    r"veintisiete|veintiocho|veintinueve|treinta|cuarenta|cincuenta|sesenta|"
    r"setenta|ochenta|noventa|diez|once|doce|trece|catorce|quince|dieci\w+|"
    r"veinte|uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|"
    r"\d+)"
)
_NUM_PHRASE = rf"(?:{_NUM_WORDS}(?:\s+(?:y\s+)?{_NUM_WORDS}){{0,4}})"


def _normalize_vitals_phrases(text: str) -> tuple[str, list[LexiconCorrection]]:
    """Inserta formas numéricas junto a FC / PA dichas en palabras."""
    corrections: list[LexiconCorrection] = []
    out = text

    # FC: "frecuencia cardíaca noventa y seis por minuto"
    fc_re = re.compile(
        rf"(frecuencia\s+card[ií]aca\s+)({_NUM_PHRASE})(\s*(?:por\s+minuto|lpm|/min)?)",
        re.IGNORECASE,
    )

    def fc_sub(m: re.Match[str]) -> str:
        n = _parse_spanish_number(m.group(2))
        if n is None or str(n) in m.group(0):
            return m.group(0)
        repl = f"{m.group(1)}{n}{m.group(3) or ''}"
        corrections.append(
            LexiconCorrection("vitals", m.group(0).strip(), repl.strip())
        )
        return repl

    out = fc_re.sub(fc_sub, out)

    # PA: "tensión arterial ciento treinta sobre ochenta y cinco"
    pa_re = re.compile(
        rf"((?:tensi[oó]n|presi[oó]n)\s+arterial\s+)({_NUM_PHRASE})\s+sobre\s+({_NUM_PHRASE})",
        re.IGNORECASE,
    )

    def pa_sub(m: re.Match[str]) -> str:
        sys_ = _parse_spanish_number(m.group(2))
        dia = _parse_spanish_number(m.group(3))
        if sys_ is None or dia is None:
            return m.group(0)
        repl = f"{m.group(1)}{sys_}/{dia}"
        corrections.append(
            LexiconCorrection("vitals", m.group(0).strip(), repl.strip())
        )
        return repl

    out = pa_re.sub(pa_sub, out)
    return out, corrections


def corregir_transcript(raw: str) -> LexiconResult:
    """Aplica phrase fixes, canónicos de drogas y normalización de vitales."""
    if not raw or not raw.strip():
        return LexiconResult(text=raw, raw=raw)

    text = raw
    corrections: list[LexiconCorrection] = []
    data = _load()

    # 1) Frases clínicas frecuentes (límites de palabra; más largas primero).
    phrases = sorted(
        [
            item
            for item in (data.get("phrase_fixes") or [])
            if (item.get("from") or "")
            and (item.get("to") or "")
            and _normalize(item["from"]) != _normalize(item["to"])
        ],
        key=lambda it: len(it["from"]),
        reverse=True,
    )
    for item in phrases:
        src = item["from"]
        dst = item["to"]
        pattern = re.compile(
            rf"(?<![A-Za-zÁÉÍÓÚáéíóú]){re.escape(src)}(?![A-Za-zÁÉÍÓÚáéíóú])",
            re.IGNORECASE,
        )

        def _repl(m: re.Match[str], dst: str = dst) -> str:
            corrections.append(LexiconCorrection("phrase", m.group(0), dst))
            if m.group(0)[:1].isupper():
                return dst[:1].upper() + dst[1:]
            return dst

        text = pattern.sub(_repl, text)

    # 2) Drogas: aliases → canónico (word-ish, tolerante).
    for d in data.get("drugs") or []:
        canon = d["canonical"]
        aliases = sorted(
            {a for a in (d.get("aliases") or []) if _normalize(a) != _normalize(canon)},
            key=len,
            reverse=True,
        )
        for alias in aliases:
            # Preferir match de token con tolerancia a 1-2 chars vía regex simple.
            pat = re.compile(rf"(?<![a-zA-ZÁÉÍÓÚáéíóú]){re.escape(alias)}(?![a-zA-ZÁÉÍÓÚáéíóú])", re.IGNORECASE)

            def drug_repl(m: re.Match[str], canon: str = canon) -> str:
                if _normalize(m.group(0)) == _normalize(canon):
                    return m.group(0)
                corrections.append(LexiconCorrection("drug", m.group(0), canon))
                return canon

            text = pat.sub(drug_repl, text)

        # Fuzzy: tokens parecidos al canónico (p.ej. propranodol).
        canon_n = _normalize(canon)
        tokens = set(re.findall(r"[A-Za-zÁÉÍÓÚáéíóú]{6,}", text))
        for tok in tokens:
            tn = _normalize(tok)
            if tn == canon_n:
                continue
            if SequenceMatcher(None, tn, canon_n).ratio() >= 0.84:
                text2 = re.sub(
                    rf"(?<![a-zA-ZÁÉÍÓÚáéíóú]){re.escape(tok)}(?![a-zA-ZÁÉÍÓÚáéíóú])",
                    canon,
                    text,
                    count=1,
                )
                if text2 != text:
                    corrections.append(LexiconCorrection("drug", tok, canon))
                    text = text2

    # 3) Vitales en palabras → dígitos.
    text, vitals_corr = _normalize_vitals_phrases(text)
    corrections.extend(vitals_corr)

    # Dedup corrections (misma original→replacement).
    seen: set[tuple[str, str, str]] = set()
    unique: list[LexiconCorrection] = []
    for c in corrections:
        key = (c.kind, _normalize(c.original), _normalize(c.replacement))
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    return LexiconResult(text=text, corrections=unique, raw=raw)
