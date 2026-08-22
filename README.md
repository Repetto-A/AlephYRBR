# Prognosia Health

Asistente clínico **100% local** sobre QVAC (Aleph Hackathon 2026). Captura una
consulta médica (voz o texto), extrae una nota SOAP estructurada con un LLM
local y aplica un **guardrail determinista de seguridad**: detecta el near-miss
de asma severa + betabloqueante no selectivo (p. ej. propranolol) y bloquea el
plan con evidencia trazable. Sin inference cloud.

## Setup

Requiere Python 3.12 (≥ 3.10) y Node.js ≥ 22.17 (para el worker QVAC).

```powershell
cd "C:\Users\conta\Documents\Ale\Software\Current Projects\AlephYRBR"
py -3.12 -m venv .venv-qvac
.\.venv-qvac\Scripts\Activate.ps1
pip install tetherto-qvac-sdk==0.17.1 starlette uvicorn
$env:PYTHONIOENCODING='utf-8'
```

El worker QVAC y los modelos viven en cache global
(`~\.cache\qvac\worker\0.17.1\` y `~\.qvac\models\`) — la primera corrida
descarga lo que falte (~83 MB de Whisper+VAD si no están). Si el worker
fallara, ver los workarounds en `docs/prep-entorno.md`, sección 2.

## Demo (2 comandos)

```powershell
# Caso A — near-miss: HC con asma severa + consulta que propone propranolol → BLOCKED
python -m prognosia run --hc corpus/clinic/hc-a.json --audio corpus/clinic/consulta-a.wav

# Caso B — control negativo: HTA sin asma + plan inocuo → SAFE
python -m prognosia run --hc corpus/clinic/hc-b.json --transcript corpus/clinic/consulta-b.txt
```

Cada corrida imprime el transcript, la nota SOAP en JSON y el veredicto, y
escribe `out/run-<paciente>.json` + `out/run-<paciente>.html`. También se
puede correr el caso A sin audio: `--transcript corpus/clinic/consulta-a.txt`
(transcript gold, nota más limpia).

## Shell web local (fase 2A) — sala de consulta

Misma pipeline que el CLI. UI en `prognosia/web/`: **una sola vista** de
consultorio (agenda + HC + grabar + draft + aprobar). Sin cloud, sin login.

```powershell
python -m prognosia serve                 # http://127.0.0.1:8787
python -m prognosia serve --fast          # transcript + reglas ~1 s (ensayo)
```

Flujo en la UI:

1. **Agenda** — chips A (near-miss) / B (control). HC + sesiones previas
   (fake) siempre visibles a la izquierda.
2. **Comenzar a grabar** — mic simulado + foreshadowing en vivo; **Detener y
   generar nota** dispara el pipeline (audio real si no es `--fast`). Atajo:
   «Generar desde transcript».
3. **Procesando** — progreso real (STT + extracción; 20–45 s, o ~1 s en `--fast`).
4. **Draft** — caso A: traza HC → Audio → **BLOQUEADO** + plan blocked;
   caso B: check verde. Evidencia de la regla a la derecha.
5. **Aprobar** — nota editable; disabled si hay bloqueos.

API mínima (la usa la UI, sirve también para debug):
`GET /api/cases` · `POST /api/run` con `{"case":"a"|"b","source":"audio"|"transcript"}`
· `GET /api/run/{run_id}`. La decisión de safety sigue siendo la regla
determinista del backend (`prognosia/rules.py`); el frontend solo renderiza
el `RunResult`.

Nota offline: las fuentes (Archivo / IBM Plex Mono) se piden a Google Fonts;
con WiFi off la UI cae a las fuentes del sistema sin romper nada.

### Fase 2B (pendiente) — Tauri

Cuando 2A esté ensayada: envolver `prognosia/web/` en una ventana Tauri
única (sin browser chrome) que invoque `python -m prognosia serve` del venv
local como sidecar. No cambia reglas ni schemas.

### Guión de 3 minutos (ensayado: 68 s de comandos)

1. Mostrar WiFi off / modo avión (todo es local).
2. Correr caso A con audio (~46 s): se ve el transcript de Whisper, la nota
   SOAP y el bloque **BLOCKED** con la traza HC → consulta → regla.
3. Narrar la evidencia: asma severa en la HC + propranolol en el audio.
   La decisión la toma una **regla determinista sobre el transcript crudo**,
   nunca el LLM.
4. Correr caso B (~22 s): **SAFE**, sin alerta.
5. Abrir los HTML de `out/` si queda tiempo.

## Pipeline

audio/transcript → STT local (Whisper) → extracción SOAP (Qwen3-4B local, JSON
validado con Pydantic, retry con feedback ×2, refusal sin inventar medicación)
→ reglas deterministas (`prognosia/rules.py`) → JSON + HTML mínimo.

La regla de safety evalúa el **transcript crudo** además de la nota extraída:
un near-miss se bloquea aunque el LLM falle o distorsione la extracción.

## Modelos y latencias medidas

Hardware: AMD Radeon 780M (Vulkan 1.4), Windows 11. Medido el 2026-08-22.

| Etapa | Modelo | Latencia |
| --- | --- | --- |
| STT | `WHISPER_BASE_Q8_0` (82 MB) + `VAD_SILERO_5_1_2` | 3.8 s (audio de 56 s, ~15× tiempo real, incluye carga) |
| Extracción SOAP | `QWEN3_4B_INST_Q4_K_M` (2.33 GB, ctx 8192, temp 0) | 19–39 s según largo del transcript (incluye carga a RAM) |
| Reglas de safety | determinista (regex + normalización, sin LLM) | < 1 ms |

Corrida completa: caso A con audio ~46 s, caso B con transcript ~22 s.

Spike de voz (go/no-go, 10/10 detecciones de "propranolol"): `docs/spike-voz.md`.
Corpus sintético y mapeo a la demo: `corpus/clinic/README.md`.

## Estado — DoD fase 1 funcional

- [x] Voz → transcript local (Whisper vía QVAC); "propranolol" detectable 10/10
- [x] Transcript visible en el flujo (stdout + JSON + HTML)
- [x] Un solo comando corre input → extract → reglas → output, con progreso
- [x] Near-miss: hc-a + consulta-a → `blocked` con motivo y evidencia
- [x] Control negativo: hc-b + consulta-b → `safe`
- [x] 100% local (QVAC; sin llamadas cloud de inference)
- [x] Reproducible (este README: setup, comandos, corpus, latencias)
- [x] Ensayo < 3 min (68 s de comandos + narrativa)

Caveat conocido: el audio de demo es TTS con voz en-US leyendo español (no hay
voz TTS en español en esta máquina), por eso el transcript del caso A con
`--audio` sale distorsionado y la nota SOAP hereda ruido (la droga y el
BLOCKED son estables igual). Con voz humana real o `--transcript` la nota sale
limpia. UI (mockups en `design/mockups/`) es fase 2.
