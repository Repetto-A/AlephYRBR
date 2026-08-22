"""RAG local offline sobre guías en corpus/clinic/guidelines/.

Indexación lexical (BM25-lite / TF-IDF) — sin embeddings QVAC ni cloud.
La retrieval refuerza la explicación de findings; no decide blocked/safe.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .schemas import LocalGuideHit, SafetyFinding

_GUIDELINES_DIR = (
    Path(__file__).resolve().parent.parent / "corpus" / "clinic" / "guidelines"
)

_TOKEN_RE = re.compile(r"[a-z0-9áéíóúñü]+", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    title: str
    section: str
    text: str
    source: str


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(_normalize(text)) if len(t) > 1]


def _chunk_markdown(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    doc_id = path.stem
    lines = raw.splitlines()
    title = doc_id
    for line in lines[:8]:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    sections: list[tuple[str, list[str]]] = []
    current = "intro"
    buf: list[str] = []
    for line in lines:
        m = _HEADING_RE.match(line)
        if m and not line.startswith("# "):
            if buf:
                sections.append((current, buf))
            current = m.group(1).strip()
            buf = []
            continue
        if line.startswith("# "):
            continue
        if line.strip().startswith(">"):
            continue
        buf.append(line)
    if buf:
        sections.append((current, buf))

    chunks: list[Chunk] = []
    source = f"corpus/clinic/guidelines/{path.name}"
    for section, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if len(body) < 40:
            continue
        chunks.append(
            Chunk(
                doc_id=doc_id,
                title=title,
                section=section,
                text=body,
                source=source,
            )
        )
    return chunks


@lru_cache(maxsize=1)
def load_chunks(guidelines_dir: str | None = None) -> tuple[Chunk, ...]:
    root = Path(guidelines_dir) if guidelines_dir else _GUIDELINES_DIR
    if not root.is_dir():
        return tuple()
    chunks: list[Chunk] = []
    for path in sorted(root.glob("*.md")):
        chunks.extend(_chunk_markdown(path))
    return tuple(chunks)


@dataclass
class _Index:
    chunks: tuple[Chunk, ...]
    docs_tokens: list[list[str]]
    df: dict[str, int]
    avgdl: float
    N: int


@lru_cache(maxsize=1)
def _build_index(guidelines_dir: str | None = None) -> _Index:
    chunks = load_chunks(guidelines_dir)
    docs_tokens = [_tokenize(c.text + " " + c.section + " " + c.title) for c in chunks]
    df: dict[str, int] = {}
    for toks in docs_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    total_len = sum(len(t) for t in docs_tokens) or 1
    avgdl = total_len / max(len(docs_tokens), 1)
    return _Index(
        chunks=chunks,
        docs_tokens=docs_tokens,
        df=df,
        avgdl=avgdl,
        N=len(chunks),
    )


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], index: _Index) -> float:
    """BM25 Okapi simplificado (k1=1.5, b=0.75)."""
    if not query_tokens or not doc_tokens:
        return 0.0
    k1, b = 1.5, 0.75
    tf: dict[str, int] = {}
    for t in doc_tokens:
        tf[t] = tf.get(t, 0) + 1
    dl = len(doc_tokens)
    score = 0.0
    for q in query_tokens:
        if q not in tf:
            continue
        n_q = index.df.get(q, 0)
        idf = math.log(1 + (index.N - n_q + 0.5) / (n_q + 0.5))
        freq = tf[q]
        denom = freq + k1 * (1 - b + b * dl / index.avgdl)
        score += idf * (freq * (k1 + 1)) / denom
    return score


def retrieve(
    query: str,
    *,
    top_k: int = 2,
    min_score: float = 0.5,
    guidelines_dir: str | None = None,
) -> list[LocalGuideHit]:
    """Recupera chunks de guía local por similitud lexical (BM25)."""
    q = (query or "").strip()
    if not q:
        return []
    index = _build_index(guidelines_dir)
    if index.N == 0:
        return []
    q_tokens = _tokenize(q)
    scored: list[tuple[float, Chunk]] = []
    for chunk, toks in zip(index.chunks, index.docs_tokens):
        s = _bm25_score(q_tokens, toks, index)
        if s >= min_score:
            scored.append((s, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits: list[LocalGuideHit] = []
    for score, chunk in scored[:top_k]:
        citation = " ".join(chunk.text.split())
        if len(citation) > 420:
            citation = citation[:417].rstrip() + "…"
        hits.append(
            LocalGuideHit(
                guide_id=f"{chunk.doc_id}#{_slug(chunk.section)}",
                title=chunk.title,
                citation=citation,
                source=f"{chunk.source} · § {chunk.section}",
                mode="local_rag",
                score=round(score, 3),
                section=chunk.section,
                doc_id=chunk.doc_id,
            )
        )
    return hits


def _slug(section: str) -> str:
    s = _normalize(section)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:48] or "sec"


def query_from_finding(finding: SafetyFinding) -> str:
    """Query derivada del finding (regla + motivo + señales HC/consulta)."""
    parts = [
        finding.rule_id.replace("-", " "),
        finding.motivo,
        finding.evidencia_hc,
        finding.evidencia_consulta,
    ]
    return " ".join(p for p in parts if p)


def attach_rag_evidence(
    findings: list[SafetyFinding],
    *,
    top_k: int = 2,
    guidelines_dir: str | None = None,
) -> list[SafetyFinding]:
    """Adjunta retrieval local a findings blocked; no-op si no hay hit."""
    for f in findings:
        hits = retrieve(
            query_from_finding(f),
            top_k=top_k,
            guidelines_dir=guidelines_dir,
        )
        if not hits:
            continue
        f.rag_snippets = hits
        if f.guia is None:
            f.guia = hits[0]
    return findings


def smoke_retrieve(query: str = "propranolol asma severa") -> list[LocalGuideHit]:
    """Smoke unitario: debe devolver hit de la guía de asma."""
    return retrieve(query, top_k=2, min_score=0.1)
