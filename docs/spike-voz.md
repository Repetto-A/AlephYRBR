# Spike voz/transcript QVAC — resultado: GO

Fecha: 2026-08-22. SDK `tetherto-qvac-sdk` 0.17.1, worker `@qvac/sdk` 0.17.1,
Windows + Vulkan (AMD Radeon 780M).

## Veredicto

**GO** — la transcripción local QVAC detecta la droga clave de forma estable:

| Config | Detección "propranolol" | Latencia media (audio de 56 s) |
| --- | --- | --- |
| Sin prompt | **5/5** | 2.8 s |
| Con prompt de sesgo médico | **5/5** | 2.8 s |

Criterio del kickoff: ≥4/5 → cumplido con margen. El CLI acepta `--audio`;
`--transcript` queda como fallback siempre disponible.

## Qué API se usa (hallazgos sobre 0.17.1)

- **Modelo**: `WHISPER_BASE_Q8_0` (multilingüe, 82 MB, engine
  `whispercpp-transcription`) + **VAD obligatorio** `VAD_SILERO_5_1_2`
  (885 KB). Ambos quedan en el cache global `~\.qvac\models\` tras la primera
  descarga (~83 MB en total, única descarga nueva de este spike).
- **Carga**: `load_model(t, model_src=WHISPER_BASE_Q8_0, model_config={"vadModelSrc": VAD_SILERO_5_1_2.src})`.
  Sin `vadModelSrc` el worker rechaza con
  `RPCError: VAD model name is required for Whisper transcription`.
- **Path que funciona**: `transcribe_stream_session` (duplex): se escriben
  chunks de **PCM s16le 16 kHz mono** (WAV sin header) y se itera el texto.
- **Path roto en 0.17.1**: `transcribe` no-streaming (filePath o base64)
  falla en el transporte con `RuntimeError: expected a response stream`.
  No usarlo.
- Carga del modelo: ~3 s (ya cacheado). Transcripción determinista
  (mismo audio → mismo texto).

Script reproducible: `scripts/spike_voz.py`
(`python scripts/spike_voz.py [audio] [n]` con el venv activo y
`$env:PYTHONIOENCODING='utf-8'`).

## Caveats del audio de prueba

- No hay **ninguna voz TTS en español** instalada en esta máquina (solo
  Microsoft David/Zira/Mark en-US). `consulta-a.wav` se generó con voz en-US
  leyendo texto en español → pronunciación mala a propósito ("el audio más
  difícil"). Aun así "propranolol" salió 10/10.
- Por esa voz, el transcript general tiene mucha distorsión ortográfica
  ("Tencin arterial", "oscultation"). Con voz humana real en español la
  calidad debería mejorar; para la demo en vivo conviene grabar la consulta
  con voz real o usar `--transcript` (gold en `corpus/clinic/consulta-a.txt`).
- El transcript omitió el tramo inicial del audio (arranca en "tensión
  arterial"): posible efecto del VAD sobre el arranque sintético. La droga
  está en el tramo final (plan), que se transcribe siempre.

## Decisión para el pipeline

1. `--audio` usa `transcribe_stream_session` + Whisper base + VAD Silero
   **con prompt médico** (`corpus/clinic/lexicon.json` → `whisper_prompt`).
2. Tras STT (y también sobre `--transcript`), corre
   `clinicguard/lexicon.py`: frases clínicas, canónicos de drogas y
   vitales en palabras → dígitos (`130/85`, `FC 96`). El resultado
   corregido es el que ve el LLM y las reglas; el crudo queda en
   `transcript_raw` si hubo cambios.
3. `--transcript` (texto plano) sigue siendo fallback de primera clase.
4. El matching de safety es tolerante a variantes
   (`propr?an[oa]lol`) + léxico fuzzy.
