"""CLI de ClinicGuard.

    python -m clinicguard run --hc corpus/clinic/hc-a.json --audio corpus/clinic/consulta-a.wav
    python -m clinicguard run --hc corpus/clinic/hc-a.json --transcript corpus/clinic/consulta-a.txt
    python -m clinicguard serve            # shell web local en http://127.0.0.1:8787

Pipeline: input → transcript → extracción SOAP (Qwen3-4B local) →
reglas deterministas → JSON + HTML en out/.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from .render import render_html


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

    serve = sub.add_parser("serve", help="Levanta el shell web local (misma pipeline)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    return parser


def _print_progress(event: dict[str, Any]) -> None:
    print(event["message"], flush=True)
    if "transcript" in event:
        print("\n--- TRANSCRIPT " + "-" * 45)
        print(event["transcript"])
        print("-" * 60 + "\n")


def _cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import run_pipeline

    result = asyncio.run(
        run_pipeline(
            hc_path=args.hc,
            audio_path=args.audio,
            transcript_path=args.transcript,
            progress=_print_progress,
        )
    )

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


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import app

    print(f"ClinicGuard shell local → http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        return _cmd_serve(args)
    return _cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
