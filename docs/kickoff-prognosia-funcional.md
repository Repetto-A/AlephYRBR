# Kickoff prompt — Prognosia Health (fase funcional primero)

Pegá este documento entero como primer mensaje a un agente / sesión de hackathon.
**Prioridad:** 100% funcional y demoable. UI = fase 2 (ya existen mockups en `design/mockups/`; no los reimplementes ahora).

---

## Contexto del producto

**Prognosia Health** — asistente clínico 100% local (QVAC / Aleph Hackathon 2026).

Loop:
1. Captura de consulta (voz → transcript)
2. Extracción estructurada (nota SOAP + medicación propuesta)
3. Reglas deterministas de safety (near-miss: asma severa + propranolol → BLOQUEADO)
4. Output verificable (JSON + HTML mínimo o CLI) con evidencia trazable

Diferencial vs scribe genérico / Nodica: **guardrail de seguridad** (rehúso / campo bloqueado), no solo “escribir la nota”.

Pitch demo (3 min): WiFi off → grabar / cargar audio → transcript visible → traza `HC → Audio → BLOQUEADO` → plan no se inventa.

---

## Stack y prep ya listos (no reinventar)

- SDK: `tetherto-qvac-sdk` en `.venv-qvac` (ver `docs/prep-entorno.md`)
- Modelos pre-descargados en `~/.qvac/models/` (Qwen3-4B + OCR si hace falta)
- Research tracks: `aleph-hackathon-2026-research/`
- Spec viejo de conciliador (facturas): `docs/superpowers/specs/` — **NO es el producto actual**; el producto es Prognosia Health clínico
- UI mockups (fase 2): `design/mockups/` + `design/handoff.md`

Regla hackathon: código del producto **durante el evento**. Este kickoff asume que ya podés codear.

---

## Objetivo de esta fase (Definition of Done funcional)

Al terminar la fase 1, debe existir un vertical slice que un juez pueda ver sin explicación larga:

| # | Criterio | Cómo se verifica |
|---|---|---|
| 1 | **Voz → transcript confiable** | Audio de demo produce texto legible; “propranolol” (o sinónimo) aparece en el transcript |
| 2 | **Transcript visible en el flujo** | El usuario ve el transcript antes o junto con la nota (CLI print y/o archivo `.txt`/`.json`) |
| 3 | **Procesamiento demoable** | Un solo comando corre: input → extract → reglas → output; tarda un tiempo predecible; se ve progreso |
| 4 | **Near-miss funciona** | Con HC “asma severa” + audio/texto que propone betabloqueante → estado `blocked` + motivo |
| 5 | **Control negativo** | Caso sin riesgo → `safe`, sin alerta roja |
| 6 | **100% local** | Sin llamadas cloud de inference; documentar modelo QVAC usado |
| 7 | **Reproducible** | README: setup, comando exacto, corpus de demo, hardware/latencia |

**Fuera de alcance fase 1:** pixel-perfect UI, Figma, animaciones, sello estético, RAG de papers (opcional al final si sobra tiempo), auth, HCE real, multi-paciente, WDK/pagos.

---

## Orden de trabajo (no saltear)

### Paso 0 — Spike voz/transcript (45–60 min, go/no-go)

1. Confirmar QVAC corre en Windows (Vulkan ya OK según prep).
2. Probar **transcripción** con el path que ofrezca QVAC (transcription / multimodal / lo que documente el SDK).
3. Correr **5 veces** el audio más difícil del corpus.
4. Criterio go: ≥4/5 transcripts con la droga o frase clave detectable.
5. Si falla: **fallback inmediato** — input = texto pegado / `.txt` de la consulta (mismo pipeline después del transcript). No bloquear el resto del producto por voz.

Entregar: notas en README o `docs/spike-voz.md` (qué API, latencia, tasa de acierto, fallback).

### Paso 1 — Corpus mínimo de demo

Crear `corpus/clinic/` (sintético, sin datos reales de pacientes):

- `hc-a.json` — asma severa + contexto near-miss  
- `hc-b.json` — control HTA, sin asma  
- `consulta-a.wav` (o `.mp3` / `.m4a`) — médico propone propranolol  
- `consulta-a.txt` — transcript gold / fallback  
- `consulta-b.txt` — plan inocuo  
- `README.md` — cómo mapear cada archivo a la demo  

### Paso 2 — Schema + reglas (sin UI)

- Pydantic (o dataclasses): `ClinicalNote`, `ProposedMed`, `SafetyFinding`, `RunResult`
- Regla dura v1: si HC tiene asma (severa) Y texto/transcript menciona betabloqueante no selectivo (propranolol, etc.) → `blocked`
- Sin LLM en la decisión de safety

### Paso 3 — Pipeline CLI

```bash
# forma objetivo (ajustar a la impl real)
python -m prognosia run --hc corpus/clinic/hc-a.json --audio corpus/clinic/consulta-a.wav
python -m prognosia run --hc corpus/clinic/hc-a.json --transcript corpus/clinic/consulta-a.txt
```

Salida mínima:

1. Transcript (si hubo audio)  
2. JSON de nota + findings  
3. HTML **mínimo** (puede ser feo): bastan secciones S/O/A/P + bloque “BLOQUEADO” + transcript  

Reusar estructura de `design/mockups/03` solo si no frena; si frena, HTML crudo.

### Paso 4 — Integración QVAC extraction

- Tras transcript: LLM local → JSON SOAP validado  
- Retry con feedback del validador (máx 2)  
- Si no valida: escalate / campos vacíos + motivo — **no inventar medicación**  

### Paso 5 — Demo rehearsal

Ensayar el guión de 3 minutos **antes** de tocar UI:

1. Mostrar sello / WiFi off  
2. Correr caso A (blocked)  
3. Mostrar transcript + traza mental HC→audio→regla  
4. Correr caso B (safe) en 30 s  
5. Congelar código → README → video  

### Paso 6 — UI (solo después del DoD funcional)

Implementar / portar `design/mockups/` encima del mismo pipeline. No cambiar reglas ni schemas por estética.

---

## Prompt corto para el agente (copiar debajo)

```text
Sos el agente de implementación de Prognosia Health para el Aleph Hackathon 2026 (QVAC).

Leé este archivo completo: docs/kickoff-prognosia-funcional.md
Y el prep: docs/prep-entorno.md

FASE ACTUAL: funcionalidad 100% demoable. NO prioritizar UI.
Orden obligatorio:
1) Spike de voz/transcript QVAC (go/no-go + fallback a texto)
2) Corpus sintético en corpus/clinic/
3) Schema + reglas deterministas asma+betabloqueante
4) CLI `run` end-to-end (audio y/o transcript → JSON + HTML mínimo)
5) Extracción SOAP vía QVAC con validación/retry/refusal
6) Ensayo de demo 3 min

Criterio de éxito: en un comando se ve transcript + near-miss BLOQUEADO + caso safe.
Mockups en design/mockups/ son referencia para FASE 2, no bloquean la fase 1.
Todo local: tetherto-qvac-sdk, sin inference cloud.
Trabajá en commits pequeños y documentá latencia/modelo en README.
```

---

## Anti-patrones (rechazar en code review de fase 1)

- Empezar por CSS / rehacer mockups  
- Chat UI tipo ChatGPT sin pipeline  
- Dejar que el LLM “decida” la contraindicación  
- Depender de API cloud para STT o LLM  
- Scope creep: RAG de papers, pagos WDK, login, multi-tenant  
- Demo que solo funciona con WiFi y un happy path cherry-picked  

---

## Checklist rápido antes de pasar a UI

- [ ] Spike voz documentado (o fallback texto activado por defecto en demo)  
- [ ] `consulta-a` reproduce BLOQUEADO de forma estable  
- [ ] `consulta-b` / hc-b reproduce SAFE  
- [ ] Transcript se imprime o se guarda y se muestra en el output  
- [ ] Un comando documentado en README  
- [ ] Modelo QVAC + RAM + latencia medida  
- [ ] Ensayo cronometrado &lt; 3 minutos de narrativa  

Cuando todos los checks estén en verde → abrir `design/handoff.md` y portar UI.
