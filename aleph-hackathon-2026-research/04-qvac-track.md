# QVAC Track — research brief

## One-line thesis

Use QVAC as the **local inference layer** to automate private operations work or to prove that a small local model can use tools reliably.

## Prize structure

- Total: up to **$2,000 USD₮**
- 1st: **$1,000 USD₮** — local agents replacing operations work.
- 2nd: **$500 USD₮** — hard tool use and small-model reliability.
- Extra: **$500 USD₮** Vault Guardian pool, split among everyone who beats the separate challenge.

## QVAC mental model

- Local, cross-platform inference with JS/TS (`@qvac/sdk`) or Python (`tetherto-qvac-sdk`).
- No cloud model API for the judged inference path.
- Capabilities include LLMs, embeddings, RAG, OCR, multimodal input, transcription, and more.
- An OpenAI-compatible local HTTP server can let existing tools talk to QVAC at `localhost`.
- Local inference creates privacy/offline/cost advantages, but model size and reliability become product constraints.

## Direction A — local operations agents

Strong use cases:

- Invoice reconciliation across PDFs, photos, scans, purchase orders, and statements.
- Post-trigger credit-risk operations: gather documents, summarize exposure, draft notes, route next actions.
- Transaction anomaly triage, categorization, duplicate detection, and change explanation.
- Contract/email/receipt text converted into structured financial workflows.
- Multimodal extraction from messy receipts or handwritten delivery notes.

Winning characteristics:

- Handles messy inputs, not one curated document.
- Shows traceable evidence and uncertainty.
- Produces an output a human can verify in seconds.
- Refuses or escalates instead of confidently inventing values.

## Direction B — tool use and reliability

Strong use cases:

- Multi-step tool chains across search, calculation, local data, and files.
- Grounded answers that depend on retrieved results.
- Structured-output validation, retries, self-checks, and explicit failure handling.
- A reproducible benchmark exposing where the small model succeeds and breaks.

Winning characteristics:

- Evidence over a polished one-off demo.
- Repeated runs with success-rate metrics.
- Visible failure taxonomy and mitigation effectiveness.
- Correct refusal when tools fail or return insufficient evidence.

## Critical feasibility tension

The track frames **1–4B models** as the practical laptop target. However, QVAC's own current connection guide warns that reliable general-purpose local tool use often needs roughly **14B+** with agent/coder post-training; 4B/8B instruct models may narrate a tool call without emitting one or may ignore results.

This does not make the track impossible. It changes the winning strategy:

- Narrow the tool vocabulary and workflow.
- Use deterministic orchestration around the model.
- Validate every structured output.
- Separate planning from tool execution.
- Measure reliability on a bounded task rather than claiming general agency.
- Consider Direction A if hardware cannot support larger models.

## Hard requirements and gotchas

- All judged inference must run through QVAC locally.
- Cloud model calls do not count.
- The QVAC integration must be new and central.
- Track brief estimate: 4B Q4 ≈ 4 GB RAM; 8B ≈ 8 GB; first model download can be multi-GB.
- Current official JS/TS SDK documentation requires Node.js **22.17+**, while the CLI-level doctor page has broader minimum checks; follow the SDK-specific requirement for a JS/TS project.
- Windows currently requires Vulkan 1.4 even for CPU-only inference.
- Mobile inference requires a physical device, not an emulator.
- VisionPsy is not supported through the SDK yet; use supported OCR/multimodal capabilities.
- Image/video generation is explicitly a weak judged direction.

## Submission evidence

- Public repo and README naming QVAC capabilities/models.
- Direct permalinks to inference integration files/lines.
- Local end-to-end demo.
- Model, quantization, hardware, RAM, and latency details.
- Clean-clone setup.
- For reliability work: test corpus, run count, success metric, and known failure cases.

## Feasibility profile

- **Fastest route:** deterministic OCR/extraction pipeline with human-auditable output.
- **Highest research value:** bounded tool-use benchmark with reliability engineering.
- **Biggest hidden risk:** model/hardware mismatch and tool-calling claims that fail outside a cherry-picked demo.

## Primary resources

- [Track brief](https://hacki.crecimiento.build/h/aleph-hackathon-2026/tracks/qvac-track)
- [QVAC documentation](https://docs.qvac.tether.io/)
- [System requirements](https://docs.qvac.tether.io/system-requirements/)
- [JS/TS SDK](https://docs.qvac.tether.io/js-ts-sdk/)
- [OpenAI-compatible local server](https://docs.qvac.tether.io/cli/)
- [Tool-integration caveats](https://docs.qvac.tether.io/cli/http-server/connection/)
- [OCR](https://docs.qvac.tether.io/ai-capabilities/ocr/)
- [QVAC GitHub](https://github.com/tetherto/qvac)
