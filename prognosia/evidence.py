"""Evidencia local para draft.blocked.

1. RAG lexical (BM25) sobre corpus/clinic/guidelines/*.md
2. Fallback: lookup por rule_id en corpus/clinic/evidence.json

Sin cloud. La decisión blocked/safe sigue en rules.py.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .schemas import LocalGuideHit, SafetyFinding

_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "clinic" / "evidence.json"


@lru_cache(maxsize=1)
def _load_guides() -> list[dict]:
    if not _CORPUS.is_file():
        return []
    data = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return list(data.get("guides") or [])


def lookup_guide(rule_id: str) -> LocalGuideHit | None:
    """Devuelve el snippet estático asociado a la regla, o None."""
    for g in _load_guides():
        if rule_id in (g.get("rule_ids") or []):
            return LocalGuideHit(
                guide_id=g["guide_id"],
                title=g["title"],
                citation=g["citation"],
                source=g["source"],
                mode="local_lookup",
                doc_id=g["guide_id"],
            )
    return None


def attach_local_evidence(findings: list[SafetyFinding]) -> list[SafetyFinding]:
    """Adjunta guía local: RAG primero; evidence.json como fallback."""
    if not findings:
        return findings

    from .rag import attach_rag_evidence

    attach_rag_evidence(findings)
    for f in findings:
        if f.guia is None:
            f.guia = lookup_guide(f.rule_id)
        elif not f.rag_snippets and f.guia.mode == "local_lookup":
            f.rag_snippets = [f.guia]
    return findings
