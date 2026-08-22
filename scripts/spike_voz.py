"""Spike go/no-go de transcripción QVAC (kickoff Paso 0).

Corre N veces la transcripción del audio más difícil del corpus con
WHISPER_BASE_Q8_0 (+ VAD Silero, requerido por el worker) y mide si la
droga clave ("propranolol") es detectable.

Hallazgos de API (SDK 0.17.1):
- `transcribe` (no-streaming, filePath/base64) falla en el transporte con
  "expected a response stream" — no usable en esta versión.
- `transcribe_stream_session` (duplex) funciona alimentando PCM s16le 16 kHz
  mono, pero el modelo Whisper debe cargarse con `vadModelSrc`, si no el
  worker responde "VAD model name is required for Whisper transcription".

Uso:
    python scripts/spike_voz.py [ruta_audio] [n_corridas]
"""

import asyncio
import re
import sys
import time
import wave
from pathlib import Path

from tetherto.qvac_sdk import Client, load_model, transcribe_stream_session, unload_model
from tetherto.qvac_sdk.models import VAD_SILERO_5_1_2, WHISPER_BASE_Q8_0

# Acepta variantes de mis-transcripción cercanas (propanolol, propranalol, etc.)
DRUG_PATTERN = re.compile(r"propr?an[oa]lol", re.IGNORECASE)

REPO = Path(__file__).resolve().parent.parent
DEFAULT_AUDIO = REPO / "corpus" / "clinic" / "consulta-a.wav"

PROMPT = "Consulta médica en español. Medicamentos: propranolol, enalapril, salbutamol."


def read_pcm(audio: Path) -> bytes:
    with wave.open(str(audio), "rb") as w:
        assert w.getframerate() == 16000, "se espera WAV de 16 kHz"
        assert w.getnchannels() == 1, "se espera WAV mono"
        assert w.getsampwidth() == 2, "se espera PCM de 16 bits"
        return w.readframes(w.getnframes())


async def run_once(transport, model_id: str, pcm: bytes, prompt: str | None):
    parts: list[str] = []
    t0 = time.perf_counter()
    async with transcribe_stream_session(
        transport, model_id=model_id, prompt=prompt
    ) as session:
        chunk_size = 16000 * 2  # 1 segundo de PCM s16le
        for i in range(0, len(pcm), chunk_size):
            session.write(pcm[i : i + chunk_size])
        session.end()
        async for text in session:
            parts.append(text)
    return "".join(parts).strip(), time.perf_counter() - t0


async def main() -> None:
    audio = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_AUDIO
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    pcm = read_pcm(audio)
    audio_secs = len(pcm) / (16000 * 2)
    print(f"[spike] audio: {audio.name} ({audio_secs:.0f}s)")

    async with Client() as client:
        t = client.transport
        t0 = time.perf_counter()
        model_id = await load_model(
            t,
            model_src=WHISPER_BASE_Q8_0,
            model_config={"vadModelSrc": VAD_SILERO_5_1_2.src},
        )
        print(f"[spike] modelo cargado en {time.perf_counter() - t0:.1f}s: {model_id}")

        for label, prompt in (("sin prompt", None), ("con prompt de sesgo", PROMPT)):
            hits = 0
            latencies = []
            print(f"\n=== Config: {label} ===")
            for i in range(1, n + 1):
                text, latency = await run_once(t, model_id, pcm, prompt)
                latencies.append(latency)
                found = bool(DRUG_PATTERN.search(text))
                hits += found
                print(f"[{i}/{n}] {latency:.1f}s  droga={'SI' if found else 'NO'}")
                print(f"      {text[:300]}")
            avg = sum(latencies) / len(latencies)
            print(f"--> {label}: {hits}/{n} detecciones, latencia media {avg:.1f}s")

        await unload_model(t, model_id)


if __name__ == "__main__":
    asyncio.run(main())
