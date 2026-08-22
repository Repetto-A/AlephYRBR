"""Render HTML mínimo del resultado (fase 1: funcional, sin estética)."""

from __future__ import annotations

import html

from .schemas import RunResult


def _esc(text: str | None) -> str:
    return html.escape(text or "")


def render_html(result: RunResult) -> str:
    if result.status == "blocked":
        banner = "<div style='background:#c0392b;color:#fff;padding:16px;font-size:1.3em'><strong>BLOQUEADO</strong> — near-miss detectado por regla determinista</div>"
    elif result.status == "escalate":
        banner = "<div style='background:#e67e22;color:#fff;padding:16px;font-size:1.3em'><strong>ESCALADO</strong> — la nota no pudo validarse; revisar manualmente</div>"
    else:
        banner = "<div style='background:#27ae60;color:#fff;padding:16px;font-size:1.3em'><strong>SAFE</strong> — sin hallazgos de seguridad</div>"

    findings_html = ""
    for f in result.findings:
        findings_html += (
            f"<div style='border:2px solid #c0392b;padding:12px;margin:8px 0'>"
            f"<p><strong>Regla:</strong> {_esc(f.rule_id)} ({_esc(f.severidad)})</p>"
            f"<p><strong>Motivo:</strong> {_esc(f.motivo)}</p>"
            f"<p><strong>Evidencia HC:</strong> {_esc(f.evidencia_hc)}</p>"
            f"<p><strong>Evidencia consulta:</strong> «{_esc(f.evidencia_consulta)}»</p>"
            f"</div>"
        )

    note = result.note
    if note is not None:
        meds_rows = "".join(
            f"<li>{_esc(m.nombre)} {_esc(m.dosis)} {_esc(m.frecuencia)} {_esc(m.via)}"
            + (f" — <em>«{_esc(m.evidencia)}»</em>" if m.evidencia else "")
            + "</li>"
            for m in note.medicacion_propuesta
        )
        note_html = f"""
  <h2>Nota SOAP</h2>
  <h3>S — Subjetivo</h3><p>{_esc(note.subjetivo)}</p>
  <h3>O — Objetivo</h3><p>{_esc(note.objetivo)}</p>
  <h3>A — Evaluación</h3><p>{_esc(note.evaluacion)}</p>
  <h3>P — Plan</h3><p>{_esc(note.plan)}</p>
  <h3>Medicación propuesta</h3><ul>{meds_rows or "<li>(ninguna)</li>"}</ul>"""
    elif result.note_status == "refused":
        note_html = (
            "<h2>Nota SOAP</h2><p><em>Extracción rechazada: "
            f"{_esc(result.note_refusal_motivo)}. No se inventa medicación.</em></p>"
        )
    else:
        note_html = "<h2>Nota SOAP</h2><p><em>(sin extracción)</em></p>"

    stt = (
        f"<p>STT: {_esc(result.modelo_stt)} ({result.latencia_stt_s:.1f}s)</p>"
        if result.modelo_stt and result.latencia_stt_s is not None
        else ""
    )
    extract = (
        f"<p>Extracción: {_esc(result.modelo_extraccion)} ({result.latencia_extraccion_s:.1f}s)</p>"
        if result.modelo_extraccion and result.latencia_extraccion_s is not None
        else ""
    )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>ClinicGuard — {_esc(result.patient_id)}</title></head>
<body style="font-family:sans-serif;max-width:800px;margin:24px auto;padding:0 16px">
  <h1>ClinicGuard — {_esc(result.patient_id)}</h1>
  {banner}
  {findings_html}
  {note_html}
  <h2>Transcript ({_esc(result.transcript_source)})</h2>
  <pre style="white-space:pre-wrap;background:#f4f4f4;padding:12px">{_esc(result.transcript)}</pre>
  <hr>
  <footer style="color:#666;font-size:0.85em">
    <p>100% local (QVAC). Sin inference cloud.</p>
    {stt}{extract}
  </footer>
</body></html>
"""
