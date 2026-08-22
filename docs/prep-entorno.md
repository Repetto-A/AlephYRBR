# Preparación de entorno — Aleph Hackathon 2026 (QVAC Track)

Estado al 22-08-2026, ~00:30 (pre-evento). Todo lo listado acá es preparación
de entorno permitida por las reglas: instalaciones, descargas y datos de
prueba. **No se escribió código del proyecto.**

## 1. Vulkan — ✅ OK

QVAC en Windows requiere Vulkan 1.4. Esta máquina cumple:

- **Loader**: `C:\Windows\System32\vulkan-1.dll` versión **1.4.341**.
- **GPU**: AMD Radeon 780M (integrada), API Vulkan **1.4.349**, driver AMD
  propietario 26.10.18. Conformance 1.4.3.3.
- Verificado con `vulkaninfo --summary`. Nada que instalar.

## 2. SDK Python — ✅ instalado y verificado

- **Paquete**: `tetherto-qvac-sdk` **0.17.1** (público en PyPI, Apache-2.0,
  sin credenciales de evento). Requiere Python ≥ 3.10 y Node.js ≥ 22.17
  (tenemos Node v24.14.0).
- **Venv**: `.venv-qvac\` en la raíz del workspace, con **Python 3.12**.
- **Worker** (runtime que corre los modelos): `@qvac/sdk@0.17.1` instalado en
  `C:\Users\conta\.cache\qvac\worker\0.17.1\`.
- **Smoke test**: `Client()` conecta al worker OK. Además se cargaron y
  descargaron los dos modelos elegidos, o sea que el stack de inferencia
  completo (Bare + llama.cpp + Vulkan) funciona en esta máquina.

### Bugs de la 0.17.1 en Windows y sus workarounds (¡leer antes del evento!)

1. **`python -m tetherto.qvac_sdk install-worker` falla** con "npm was not
   found" (el subproceso de Python no resuelve `npm.cmd`). Workaround ya
   aplicado — replicar el comando a mano:

   ```powershell
   npm install --prefix "C:\Users\conta\.cache\qvac\worker\0.17.1" @qvac/sdk@0.17.1 --omit=dev
   ```

2. **`bare.exe` queda "izado"** por npm en el `node_modules` raíz, pero el SDK
   lo busca anidado bajo `@qvac\sdk\node_modules\`. Workaround ya aplicado —
   junction:

   ```powershell
   New-Item -ItemType Junction `
     -Path "C:\Users\conta\.cache\qvac\worker\0.17.1\node_modules\@qvac\sdk\node_modules\bare-runtime-win32-x64" `
     -Target "C:\Users\conta\.cache\qvac\worker\0.17.1\node_modules\bare-runtime-win32-x64"
   ```

3. **El primer arranque del worker puede exceder el timeout default (30 s)**.
   Si `Client()` da `TimeoutError`, usar `await client.connect(timeout=120)`
   o simplemente reintentar (los arranques siguientes tardan ~4 s).

4. **`download_asset` está roto** en esta versión: el worker responde
   `RPCError: ✖ Invalid input` con cualquier modelo (incluso el del ejemplo
   oficial). **Para pre-descargar usar `load_model` + `unload_model`** (deja
   el .gguf en el cache de disco). Ya está resuelto: ver `prep\descargar_modelos.py`.

5. En PowerShell, setear `$env:PYTHONIOENCODING='utf-8'` antes de correr
   scripts: los mensajes de error del SDK traen caracteres Unicode (✖) que
   revientan la consola cp1252.

## 3. Modelos — ✅ pre-descargados y validados

Cache de modelos: `C:\Users\conta\.qvac\models\` (~4.7 GB total).

| Modelo | Constante del SDK | Tamaño | Rol |
| --- | --- | --- | --- |
| Qwen3-4B Q4_K_M | `QWEN3_4B_INST_Q4_K_M` | 2.33 GB | Extracción estructurada JSON |
| unlimited-ocr 3B Q4_0 | `OCR_3B_MULTIMODAL_Q4_0` | 1.59 GB | OCR/multimodal de facturas |
| mmproj OCR F16 | `MMPROJ_OCR_3B_MULTIMODAL_F16` | 0.77 GB | Proyección multimodal del OCR |

Los tres ya se cargaron en RAM y se descargaron sin errores (validación real
de inferencia, no solo descarga). Tiempos medidos: Qwen3 4B ~2 min de descarga;
carga multimodal completa OCR+mmproj ~90 s la primera vez.

Alternativas disponibles en el registro del SDK si hiciera falta pivotar:
`GEMMA4_4B_MULTIMODAL_Q4_K_M` (5.4 GB, visión+texto en uno),
`QWEN3VL_2B_MULTIMODAL_Q4_K`, `LLAMA_3_2_1B_INST_Q4_0` (1B, más liviano),
y OCR clásicos (`OCR_DOCTR`, `OCR_CRAFT`, `OCR_LATIN`).

### Patrones de uso (referencia para el inicio del evento)

Texto (extracción JSON):

```python
from tetherto.qvac_sdk import Client, completion, load_model, unload_model
from tetherto.qvac_sdk.models import QWEN3_4B_INST_Q4_K_M

async with Client() as client:
    t = client.transport
    model_id = await load_model(t, model_src=QWEN3_4B_INST_Q4_K_M)
    run = completion(t, model_id=model_id, history=[{"role": "user", "content": "..."}])
    async for event in run.events:
        if event.type == "contentDelta":
            ...
    await unload_model(t, model_id)
```

Multimodal (imagen de factura → texto), patrón tomado del ejemplo oficial
`llamacpp-multimodal`:

```python
from tetherto.qvac_sdk.models import OCR_3B_MULTIMODAL_Q4_0, MMPROJ_OCR_3B_MULTIMODAL_F16

model_id = await load_model(
    t,
    model_src=OCR_3B_MULTIMODAL_Q4_0,
    model_config={"ctx_size": 2048, "projectionModelSrc": MMPROJ_OCR_3B_MULTIMODAL_F16.src},
)
history = [{
    "role": "user",
    "content": "Extraé los campos de esta factura...",
    "attachments": [{"path": r"corpus\factura-01.jpg"}],
}]
```

## 4. Corpus de prueba — ⚠️ parcial (falta acción manual)

- `corpus\extracto-banco.csv`: ✅ creado. 15 movimientos sintéticos de banco
  argentino (ARS y USD), con filas diseñadas para match, discrepancia y ruido.
- `corpus\README.md`: ✅ creado, explica qué documentos reales agregar y cómo
  mapea cada uno a los escenarios de la demo.
- **Documentos reales (facturas)**: ❌ **los tenés que conseguir vos antes del
  evento** — 10-15 facturas desprolijas (PDFs, fotos de celular, WhatsApp,
  A/B/C con CUIT, una borrosa para el rechazo). Ver checklist en el README
  del corpus.

## 5. Checklist pre-evento

- [x] Vulkan 1.4 verificado (loader 1.4.341 / GPU 1.4.349).
- [x] `.venv-qvac` con `tetherto-qvac-sdk` 0.17.1.
- [x] Worker `@qvac/sdk@0.17.1` instalado + junction de `bare.exe`.
- [x] Smoke test de `Client()` OK.
- [x] Qwen3-4B Q4_K_M descargado y validado (2.33 GB).
- [x] OCR 3B Q4_0 + mmproj descargados y validados (2.36 GB).
- [x] CSV bancario sintético + README del corpus.
- [ ] **Conseguir 10-15 facturas reales y copiarlas a `corpus\`** (manual).
- [ ] Ajustar montos/fechas del CSV a las facturas conseguidas (manual).
- [ ] Opcional: probar una completion multimodal con una foto real de factura
      antes del evento (es setup/spike, no código del proyecto — criterio tuyo).

## 6. Cómo arrancar en el evento

```powershell
cd "c:\Users\conta\Documents\Ale\Software\Current Projects\Aleph 08 26"
.\.venv-qvac\Scripts\Activate.ps1
$env:PYTHONIOENCODING='utf-8'
# los modelos ya están en cache: load_model no descarga nada, solo carga a RAM
```

Si algo del worker se rompiera, reinstalar con los comandos del punto 2
(workarounds 1 y 2) — no usar `install-worker`.
