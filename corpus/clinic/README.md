# Corpus de demo — Prognosia Health

Datos 100% sintéticos, generados para la demo. Ninguna persona real.

| Archivo | Rol en la demo |
| --- | --- |
| `hc-a.json` | HC de Ana López: **asma severa persistente** + espirometría con resultado + peak flow pendiente. Near-miss. |
| `hc-b.json` | HC de Jorge Díaz: HTA + perfil lipídico con resultado + creatinina/K pendiente. Control negativo. |
| `consulta-a.txt` | Transcript gold de la consulta A: el médico propone **propranolol** 40 mg c/12 h. Con `hc-a.json` → **BLOCKED**. |
| `consulta-a.wav` | Audio de la consulta A (TTS Windows, voz en-US leyendo español a 16 kHz mono — "audio difícil" del spike). Con `--audio` → transcribe local vía QVAC. |
| `consulta-b.txt` | Transcript de la consulta B: plan inocuo (continuar enalapril). Con `hc-b.json` → **SAFE**. |
| `evidence.json` | Fallback estático por `rule_id` (si el RAG no hittea). |
| `guidelines/*.md` | Corpus de **guías locales** (asma+BB, alergias). Indexadas con BM25 en `prognosia/rag.py`. |
| `lexicon.json` | Léxico clínico post-STT: frases, drogas canónicas y prompt Whisper. |
| `priors.json` | Visitas previas sintéticas por `patient_id` (fallback si no hay encuentros en `out/encounters/`). |

## Mapeo a la demo (3 min)

1. **Caso A (blocked)**: `python -m prognosia run --hc corpus/clinic/hc-a.json --audio corpus/clinic/consulta-a.wav`
   (o `--transcript corpus/clinic/consulta-a.txt` como fallback sin STT).
2. **Caso B (safe)**: `python -m prognosia run --hc corpus/clinic/hc-b.json --transcript corpus/clinic/consulta-b.txt`
3. **Smoke RAG**: `python -m prognosia rag-smoke` → hit de guía asma para «propranolol asma severa».

Nota: el audio sintético produce un transcript con distorsión (ver
`docs/spike-voz.md`), pero "propranolol" se detecta 10/10. Para la demo en
vivo, grabar voz humana real mejora la calidad del transcript.

El panel «Evidencia (RAG local)» cita **guías markdown indexadas offline**
(no PubMed ni papers académicos). La decisión blocked/safe la toma `rules.py`.
