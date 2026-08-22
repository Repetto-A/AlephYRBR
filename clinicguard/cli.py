"""CLI de ClinicGuard.

    python -m clinicguard run --hc corpus/clinic/hc-a.json --audio corpus/clinic/consulta-a.wav
    python -m clinicguard run --hc corpus/clinic/hc-a.json --transcript corpus/clinic/consulta-a.txt

Pipeline: input → transcript → extracción SOAP (Qwen3-4B local) →
reglas deterministas → JSON + HTML en out/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from tetherto.qvac_sdk import Client

from .render import render_html
from .rules import decidir_status, evaluar_safety
from .schemas import PatientRecord, RunResult


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clinicguard")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Corre el pipeline sobre una consulta")
    run.add_argument("--hc", required=True, type=Path, help="HC del paciente (JSON)")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--audio", type=Path, help="Audio WAV de la consulta")
    source.add_argument("--transcript", type=Path, help="Transcript en texto plano")
    run.add_argument(
        "--out-dir", type=Path, default=Path("out"), help="Directorio de salida"
    )
    return parser


async def _run(args: argparse.Namespace) -> RunResult:
    hc = PatientRecord.model_validate(
        json.loads(args.hc.read_text(encoding="utf-8"))
    )
    print(f"[1/4] HC cargada: {hc.nombre} ({hc.patient_id})", flush=True)

    modelo_stt = None
    latencia_stt = None
    note = None
    note_status = "ok"
    note_refusal = None
    modelo_extraccion = None
    latencia_extraccion = None

    async with Client() as client:
        t = client.transport

        if args.audio is not None:
            from .transcribe import STT_MODEL_NAME, transcribir

            print("[2/4] Transcribiendo audio (Whisper local)...", flush=True)
            transcript, latencia_stt = await transcribir(t, args.audio)
            transcript_source = "audio"
            modelo_stt = STT_MODEL_NAME
            print(f"      listo en {latencia_stt:.1f}s", flush=True)
        else:
            transcript = args.transcript.read_text(encoding="utf-8").strip()
            transcript_source = "texto"
            print("[2/4] Transcript cargado de texto (sin STT)", flush=True)

        print("\n--- TRANSCRIPT " + "-" * 45)
        print(transcript)
        print("-" * 60 + "\n")

        from .extract import EXTRACT_MODEL_NAME, extraer_nota

        print("[3/4] Extrayendo nota SOAP (Qwen3-4B local)...", flush=True)
        t0 = time.perf_counter()
        note, note_refusal = await extraer_nota(t, transcript)
        latencia_extraccion = time.perf_counter() - t0
        modelo_extraccion = EXTRACT_MODEL_NAME
        if note is None:
            note_status = "refused"
            print(f"      extracción rechazada: {note_refusal}", flush=True)
        else:
            print(f"      listo en {latencia_extraccion:.1f}s", flush=True)

    print("[4/4] Aplicando reglas deterministas de seguridad...", flush=True)
    findings = evaluar_safety(hc, transcript, note)
    status = decidir_status(findings)
    if status == "safe" and note is None:
        # Sin nota validada no se puede afirmar que el plan es seguro.
        status = "escalate"

    return RunResult(
        status=status,
        patient_id=hc.patient_id,
        transcript=transcript,
        transcript_source=transcript_source,
        note=note,
        note_status=note_status,
        note_refusal_motivo=note_refusal,
        findings=findings,
        modelo_extraccion=modelo_extraccion,
        modelo_stt=modelo_stt,
        latencia_stt_s=latencia_stt,
        latencia_extraccion_s=latencia_extraccion,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = asyncio.run(_run(args))

    payload = result.model_dump_json(indent=2)
    print("\n--- RESULTADO (JSON) " + "-" * 39)
    print(payload)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"run-{result.patient_id.lower()}"
    json_path = args.out_dir / f"{stem}.json"
    html_path = args.out_dir / f"{stem}.html"
    json_path.write_text(payload, encoding="utf-8")
    html_path.write_text(render_html(result), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"  ESTADO: {result.status.upper()}")
    for f in result.findings:
        print(f"  - [{f.severidad}] {f.motivo}")
        print(f"    HC: {f.evidencia_hc}")
        print(f"    Consulta: «{f.evidencia_consulta}»")
    print("=" * 60)
    print(f"\nSalida: {json_path} | {html_path}")

    return 0 if result.status in ("safe", "blocked") else 1


if __name__ == "__main__":
    sys.exit(main())
