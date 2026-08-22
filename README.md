# ClinicGuard

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
pip install tetherto-qvac-sdk==0.17.1
$env:PYTHONIOENCODING='utf-8'
```

El worker QVAC y los modelos ya viven en cache global
(`~\.cache\qvac\worker\0.17.1\` y `~\.qvac\models\`) — no hay que
re-descargar nada. Si el worker fallara, ver los workarounds en
`docs/prep-entorno.md`, sección 2.

## Estado

**Fase 1 funcional en construcción.** Pipeline objetivo: audio/transcript →
extracción SOAP (Qwen3-4B local) → reglas deterministas → JSON + HTML mínimo.
La UI (mockups en `design/mockups/`) es fase 2.
