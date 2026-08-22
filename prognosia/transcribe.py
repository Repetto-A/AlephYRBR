"""Transcripción local de audio vía QVAC (Whisper base + VAD Silero).

Hallazgos de la 0.17.1 (ver docs/spike-voz.md): hay que usar la sesión
duplex `transcribe_stream_session` con PCM s16le 16 kHz mono, y cargar el
modelo con `vadModelSrc` (el worker lo exige para Whisper).
"""

from __future__ import annotations

import audioop
import time
import wave
from pathlib import Path

from tetherto.qvac_sdk import load_model, transcribe_stream_session, unload_model
from tetherto.qvac_sdk.models import VAD_SILERO_5_1_2, WHISPER_BASE_Q8_0

STT_MODEL_NAME = "WHISPER_BASE_Q8_0 (multilingüe) + VAD_SILERO_5_1_2"

_TARGET_RATE = 16000


def _wav_a_pcm16k(audio: Path) -> bytes:
    """Lee un WAV y lo lleva a PCM s16le 16 kHz mono."""
    with wave.open(str(audio), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if channels == 2:
        pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
    if rate != _TARGET_RATE:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, _TARGET_RATE, None)
    return pcm


async def transcribir(transport, audio: Path) -> tuple[str, float]:
    """Transcribe un WAV. Devuelve (texto, latencia_segundos)."""
    pcm = _wav_a_pcm16k(audio)
    t0 = time.perf_counter()
    model_id = await load_model(
        transport,
        model_src=WHISPER_BASE_Q8_0,
        model_config={"vadModelSrc": VAD_SILERO_5_1_2.src},
    )
    try:
        parts: list[str] = []
        async with transcribe_stream_session(transport, model_id=model_id) as session:
            chunk_size = _TARGET_RATE * 2  # 1 segundo de audio
            for i in range(0, len(pcm), chunk_size):
                session.write(pcm[i : i + chunk_size])
            session.end()
            async for text in session:
                parts.append(text)
    finally:
        await unload_model(transport, model_id)
    return "".join(parts).strip(), time.perf_counter() - t0
