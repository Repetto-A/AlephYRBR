# Handoff UI — Prognosia Health

Producto de demo: **scribe clínico local + safety** (near-miss betabloqueante + asma). Loop estilo Nodica; diferencial = alerta + RAG + refusal.

**Dirección visual:** “Luz de quirófano, tipografía de archivo” — luz clínica fría, verde quirúrgico, rojo de incidente único, familia Archivo (Omnibus-Type, Buenos Aires).

**Tagline:** La nota se escribe sola. El riesgo no pasa.

## Tokens (ver `mockups/styles.css`)

| Token | Valor | Uso |
|---|---|---|
| `--surface` / `--surface-dim` | `#FCFDFC` / `#F1F5F2` | Blanco quirúrgico |
| `--text-primary` → `--text-muted` | `#10221E` … `#6B7672` | 4 niveles de texto |
| `--brand` / `--brand-ink` | `#0A5C46` / `#063D2F` | Verde quirúrgico |
| `--incident` / `--incident-wash` | `#C2281D` / `#FBEDEB` | Único rojo (near-miss) |
| `--ok` | `#1E7A4F` | Draft safe |
| `--evidence` | `#12507B` | Panel RAG |
| `--seal` | `#6B7672` | Sello LOCAL·QVAC·SIN RED |
| Tipografía | Archivo + Archivo Expanded 700 | UI + wordmark |
| Vitales | IBM Plex Mono + `tabular-nums` | FC / PA / Sat |
| Depth | borders-first | Hairlines; 2 sombras máx. |

## Pantallas

| ID | Archivo | Propósito |
|---|---|---|
| 00 | `index.html` | Portada de pitch + protocolo numerado |
| 01 | `01-preparar.html` | Agenda + HC con regla de margen |
| 02 | `02-escuchando.html` | Sala en escucha + foreshadowing “propranolol” |
| 03 | `03-draft-alerta.html` | **Hero:** traza de incidente + SOAP + evidencia |
| 04 | `04-draft-limpio.html` | Control negativo: mismo esqueleto, check verde |
| 05 | `05-aprobar.html` | Revisar / editar / aprobar (+ estados disabled) |

## Estados críticos a implementar

1. `recording` — mic activo, sin nota aún  
2. `draft.safe` — sin alerta; Aprobar habilitado  
3. `draft.blocked` — traza roja + campo `blocked` + Aprobar disabled  
4. `evidence.open` — snippet de guía citado al lado  
5. `awaiting_approval` — CTA primaria deshabilitada si hay bloqueos  

## Signature element

**Traza de incidente** (solo en 03): HC → Audio → REGLA: BLOQUEADO. Es el único rojo de la app. Distingue Prognosia Health de un scribe genérico / Nodica.

## Copy fijo (no inventar en impl)

- Detalle alerta: **“Plan propuesto choca con la historia clínica”** + **“Betabloqueante no selectivo (propranolol) + asma severa documentada. No iniciar sin revisión.”**
- Refusal: **“Campo bloqueado — evidencia de riesgo; el modelo no completa la indicación.”**
- Sello (header, todas las pantallas): **“Local · QVAC · sin red”**

## Motion

- 02: barras de audio respirando (1.6s).  
- 03: stagger de nodos de traza + `scaleX` en conectores.  
- 03: highlight-sweep una vez en el blockquote de evidencia.  
- Respetar `prefers-reduced-motion`. Nunca animar texto SOAP ni el botón Aprobar.

## Qué NO va en v1 UI

- Chat libre estilo ChatGPT  
- Dashboard de analytics  
- Login / multi-tenant  
- Integración real a HCE  
- Emojis, púrpura, cream+terracotta, dark default  

## Prompt de implementación sugerido

```text
Usá design/handoff.md + design/mockups/*.html como especificación visual.
Replicá layout, tokens y copy. La lógica (QVAC, reglas, RAG) se enchufa después;
la UI debe soportar los estados draft.safe y draft.blocked.
La traza de incidente es el elemento signature — no la reemplaces por un banner genérico.
```
