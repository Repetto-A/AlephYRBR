/* Shell local — sala de consulta sobre la API del server.
   Sin lógica de safety: solo renderiza el RunResult del backend. */

"use strict";

const $ = (sel) => document.querySelector(sel);

const PAST_SESSIONS = {
  a: [
    { fecha: "12 mar 2026", titulo: "Control asma", tag: "safe" },
    { fecha: "28 ene 2026", titulo: "Exacerbación leve", tag: "revisión" },
  ],
  b: [
    { fecha: "15 feb 2026", titulo: "Control HTA", tag: "safe" },
    { fecha: "10 nov 2025", titulo: "Ajuste enalapril", tag: "safe" },
  ],
};

const LIVE_LINES = {
  a: [
    "Paciente refiere palpitaciones y temblor de dos semanas…",
    "Examen: FC 96 · PA 130/85 · auscultación normal.",
    "Impresión: síndrome ansioso con hiperactividad adrenérgica.",
    'Plan: “voy a indicar <em>propranolol</em> 40 mg cada 12 horas…”',
  ],
  b: [
    "Control programado de hipertensión. Buena adherencia.",
    "Examen: PA 128/82 · FC 72 · peso estable.",
    "Impresión: HTA esencial en buen control.",
    "Plan: continuar enalapril 10 mg/día · control en 3 meses.",
  ],
};

const PHASE_COPY = {
  idle: { kicker: "Listo para consultar", pill: "idle", sub: "sala de consulta" },
  recording: { kicker: "Consulta en curso", pill: "grabando", sub: "escuchando" },
  processing: { kicker: "Procesando en local", pill: "generando", sub: "pipeline local" },
  draft: { kicker: "Borrador listo", pill: "draft", sub: "revisión" },
  approve: { kicker: "Aprobación humana", pill: "firmar", sub: "aprobación humana" },
};

const state = {
  cases: [],
  config: { fast: false },
  selectedId: null,
  phase: "idle",
  pendingSource: "transcript",
  runId: null,
  pollTimer: null,
  liveTimer: null,
  liveIdx: 0,
  run: null,
};

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function truncate(text, max) {
  if (!text) return "";
  return text.length <= max ? text : text.slice(0, max - 1).trimEnd() + "…";
}

function selectedCase() {
  return state.cases.find((c) => c.id === state.selectedId) || null;
}

function findingCritico(result) {
  return (result.findings || []).find((f) => f.severidad === "critical") || null;
}

function hcCorta(evidenciaHc) {
  const partes = String(evidenciaHc || "").split(" — ").slice(0, 2).join(" ");
  return partes ? partes.charAt(0).toUpperCase() + partes.slice(1) : "";
}

function drogaDelMotivo(motivo) {
  const m = String(motivo || "").match(/propone\s+([a-záéíóúñ]+)/i);
  return m ? m[1] : "betabloqueante";
}

function setPhase(phase) {
  state.phase = phase;
  document.querySelectorAll("[data-phase-panel]").forEach((el) => {
    el.hidden = el.dataset.phasePanel !== phase;
  });

  const copy = PHASE_COPY[phase] || PHASE_COPY.idle;
  $("#phase-kicker").textContent = copy.kicker;
  $("#topbar-sub").textContent = copy.sub;

  const pill = $("#phase-pill");
  pill.textContent = copy.pill;
  pill.dataset.phase = phase;
  delete pill.dataset.blocked;

  if (phase === "draft" && state.run?.result?.status === "blocked") {
    pill.dataset.blocked = "true";
    pill.textContent = "blocked";
    $("#topbar-sub").textContent = "draft bloqueado";
    $("#phase-kicker").textContent = "Near-miss detectado";
  } else if (phase === "draft" && state.run?.result?.status === "safe") {
    $("#topbar-sub").textContent = "draft seguro";
  }
}

function stopLive() {
  clearInterval(state.liveTimer);
  state.liveTimer = null;
  state.liveIdx = 0;
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function renderAgenda() {
  const box = $("#agenda-chips");
  box.innerHTML = "";
  for (const c of state.cases) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.setAttribute("aria-pressed", c.id === state.selectedId ? "true" : "false");
    btn.innerHTML = `${esc(c.titulo)}<span class="chip__meta">${esc(c.descripcion)}</span>`;
    btn.addEventListener("click", () => selectPatient(c.id));
    box.appendChild(btn);
  }
}

function renderHc(c) {
  const box = $("#hc-live");
  if (!c) {
    box.innerHTML = `<p class="muted">Elegí un paciente de la agenda.</p>`;
    return;
  }
  const hc = c.hc;
  const antecedentes = (hc.antecedentes || [])
    .map((a) => `${a.condicion}${a.severidad ? ` (${a.severidad})` : ""}`)
    .join(" · ");
  const medicacion = (hc.medicacion_actual || [])
    .map((m) => `${m.droga}${m.dosis ? ` ${m.dosis}` : ""}`)
    .join(" · ");
  const alergias = (hc.alergias || []).length ? hc.alergias.join(" · ") : "Ninguna conocida";

  box.innerHTML = `
    <p class="hc-live-title">${esc(hc.nombre)}${hc.edad ? `, ${hc.edad} años` : ""}</p>
    <dl class="hc-sheet">
      <dt>Antecedentes</dt>
      <dd>${esc(antecedentes || "—")}</dd>
      <dt>Alergias</dt>
      <dd>${esc(alergias)}</dd>
      <dt>Medicación habitual</dt>
      <dd>${esc(medicacion || "—")}</dd>
      <dt>ID</dt>
      <dd><span class="vital">${esc(hc.patient_id || c.id)}</span></dd>
    </dl>`;
}

function renderSessions(caseId) {
  const ul = $("#session-list");
  const rows = PAST_SESSIONS[caseId] || [];
  if (!rows.length) {
    ul.innerHTML = `<li class="muted">Sin sesiones previas en la demo.</li>`;
    return;
  }
  ul.innerHTML = rows
    .map(
      (s) => `<li>
        <strong>${esc(s.titulo)}</strong>
        <span class="tiny">${esc(s.fecha)} · ${esc(s.tag)}</span>
      </li>`
    )
    .join("");
}

function resetEvidence() {
  $("#evidence-panel").innerHTML = `
    <h3>Contexto</h3>
    <p class="muted">Acá aparece la evidencia de la regla cuando hay un near-miss.</p>`;
}

function selectPatient(caseId) {
  stopLive();
  stopPolling();
  state.selectedId = caseId;
  state.run = null;
  state.runId = null;
  renderAgenda();
  const c = selectedCase();
  renderHc(c);
  renderSessions(caseId);
  resetEvidence();
  $("#patient-heading").textContent = c?.hc?.nombre || c?.titulo || "Paciente";
  $("#patient-sub").textContent = c?.descripcion || "";
  $("#btn-start-rec").disabled = false;
  $("#btn-from-transcript").disabled = false;
  if (state.config.fast) {
    $("#btn-start-rec").textContent = "Simular consulta y generar";
  } else {
    $("#btn-start-rec").textContent = c?.tiene_audio
      ? "Comenzar a grabar"
      : "Simular consulta";
  }
  setPhase("idle");
}

function startRecording() {
  const c = selectedCase();
  if (!c) return;
  state.pendingSource =
    !state.config.fast && c.tiene_audio ? "audio" : "transcript";
  setPhase("recording");
  const lines = LIVE_LINES[c.id] || LIVE_LINES.a;
  const el = $("#live-transcript");
  el.innerHTML = "";
  state.liveIdx = 0;
  stopLive();
  el.innerHTML = lines[0];
  state.liveIdx = 1;
  state.liveTimer = setInterval(() => {
    if (state.liveIdx >= lines.length) {
      stopLive();
      return;
    }
    el.innerHTML = lines.slice(0, state.liveIdx + 1).join("<br />");
    state.liveIdx += 1;
  }, 1600);
}

function cancelRecording() {
  stopLive();
  setPhase("idle");
  $("#live-transcript").textContent = "";
}

async function startRun(source) {
  const c = selectedCase();
  if (!c) return;
  stopLive();
  state.pendingSource = source;
  state.run = null;
  $("#progress-steps").innerHTML = "";
  $("#run-error").hidden = true;
  setPhase("processing");

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case: c.id, source }),
    });
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    state.runId = (await res.json()).run_id;
    state.pollTimer = setInterval(poll, 900);
  } catch (err) {
    showRunError(String(err.message || err));
  }
}

async function poll() {
  try {
    const res = await fetch(`/api/run/${state.runId}`);
    const run = await res.json();
    state.run = run;
    renderSteps(run.steps || []);
    if (run.state === "done") {
      stopPolling();
      renderDraft(run);
      setPhase("draft");
    } else if (run.state === "error") {
      stopPolling();
      showRunError(run.error);
    }
  } catch {
    /* reintento */
  }
}

function renderSteps(steps) {
  $("#progress-steps").innerHTML = steps
    .map((s) => `<li>${esc(String(s).trim())}</li>`)
    .join("");
}

function showRunError(message) {
  const el = $("#run-error");
  el.textContent = `Error en la corrida: ${message}`;
  el.hidden = false;
}

function renderDraft(run) {
  const result = run.result;
  const blocked = result.status === "blocked";
  const escalate = result.status === "escalate";
  const finding = findingCritico(result);
  const fuente = result.transcript_source === "audio" ? "Audio" : "Consulta";

  renderBanner(result, finding, fuente);
  renderSoap(result, finding);
  renderEvidence(result, finding);
  renderProposal(run.proposal);

  $("#draft-estado").innerHTML = blocked
    ? "Estado: <code>draft.blocked</code> · el modelo no completa la indicación"
    : escalate
      ? "Estado: <code>escalate</code> · extracción no validada, requiere revisión humana"
      : "Estado: <code>draft.safe</code>";

  $("#transcript-summary").textContent =
    `Transcript (fuente: ${result.transcript_source})`;
  $("#transcript-text").textContent = result.transcript;

  const actions = $("#draft-actions");
  if (blocked) {
    actions.innerHTML = `
      <button class="btn btn-primary" type="button" id="btn-ir-aprobar">Corregir plan y continuar</button>
      <button class="btn btn-ghost" type="button" disabled>Aprobar nota</button>
      <button class="btn btn-ghost" type="button" id="btn-nueva">Nueva consulta</button>`;
    $("#draft-hint").textContent =
      "Con bloqueos abiertos, Aprobar queda deshabilitado. El camino es corregir el plan.";
  } else if (escalate) {
    actions.innerHTML = `
      <button class="btn btn-ghost" type="button" id="btn-nueva">Volver a la sala</button>`;
    $("#draft-hint").textContent =
      "Sin nota validada no se puede aprobar. Reintentá o revisá el transcript.";
  } else {
    actions.innerHTML = `
      <button class="btn btn-primary" type="button" id="btn-ir-aprobar">Revisar y aprobar</button>
      <button class="btn btn-ghost" type="button" id="btn-nueva">Nueva consulta</button>`;
    $("#draft-hint").textContent = "";
  }

  $("#btn-ir-aprobar")?.addEventListener("click", () => {
    renderAprobar(result, run.proposal);
    setPhase("approve");
  });
  $("#btn-nueva")?.addEventListener("click", () => {
    if (state.selectedId) selectPatient(state.selectedId);
  });

  const meta = [];
  if (result.modelo_stt)
    meta.push(`STT ${result.modelo_stt} ${result.latencia_stt_s?.toFixed(1)} s`);
  if (result.modelo_extraccion)
    meta.push(
      `Extracción ${result.modelo_extraccion} ${result.latencia_extraccion_s?.toFixed(1)} s`
    );
  meta.push("QVAC local · agente HCE pending_human");
  $("#draft-meta").textContent = meta.join(" · ");
}

function renderProposal(proposal) {
  const panel = $("#proposal-panel");
  if (!proposal) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const gate = $("#proposal-gate");
  gate.textContent =
    proposal.safety_gate === "closed" ? "safety gate closed" : "safety gate open";
  gate.dataset.gate = proposal.safety_gate;
  $("#proposal-summary").textContent = proposal.encounter_summary || "";
  $("#proposal-note").textContent = proposal.note || "";

  const soap = proposal.soap_delta || {};
  $("#proposal-soap").innerHTML = ["S", "O", "A", "P"]
    .filter((k) => soap[k])
    .map(
      (k) =>
        `<dt>${k}</dt><dd>${esc(truncate(soap[k], 140))}</dd>`
    )
    .join("") || "<dd class='muted'>Sin delta SOAP</dd>";

  $("#proposal-actions").innerHTML = (proposal.write_actions || [])
    .map(
      (a) =>
        `<li><span class="tag" data-status="${esc(a.status)}">${esc(a.status)}</span>${esc(a.summary)} <span class="tiny">→ ${esc(a.target)}</span></li>`
    )
    .join("") || "<li class='muted'>Sin acciones</li>";

  $("#proposal-gaps").innerHTML = (proposal.gaps || [])
    .map(
      (g) =>
        `<li><span class="tag">${esc(g.severity)}</span><strong>${esc(g.title)}</strong><br /><span class="tiny">${esc(g.detail)}</span></li>`
    )
    .join("") || "<li class='muted'>Sin gaps</li>";
}

function renderBanner(result, finding, fuente) {
  const box = $("#draft-banner");
  if (result.status === "blocked" && finding) {
    const droga = drogaDelMotivo(finding.motivo);
    box.innerHTML = `
      <div class="trace" role="alert" aria-label="Traza de incidente de seguridad">
        <div class="trace__node">
          <span class="trace__label">HC</span>
          <span class="trace__value">${esc(hcCorta(finding.evidencia_hc))}</span>
        </div>
        <div class="trace__connector" aria-hidden="true"></div>
        <div class="trace__node">
          <span class="trace__label">${esc(fuente)}</span>
          <span class="trace__value">“${esc(truncate(finding.evidencia_consulta, 64))}”</span>
        </div>
        <div class="trace__connector" aria-hidden="true"></div>
        <div class="trace__node trace__node--blocked">
          <span class="trace__label">Regla</span>
          <span class="trace__value">BLOQUEADO</span>
        </div>
      </div>
      <p class="trace__detail">
        <strong>Plan propuesto choca con la historia clínica.</strong>
        Betabloqueante no selectivo (${esc(droga)}) + asma severa documentada. No iniciar sin revisión.
      </p>`;
  } else if (result.status === "safe") {
    box.innerHTML = `
      <div class="safe-banner" role="status">
        <span class="safe-banner__mark" aria-hidden="true">OK</span>
        <div>
          <strong>Sin choques con la HC</strong>
          <p>El plan no choca con contraindicaciones conocidas de la HC sintética.</p>
        </div>
      </div>`;
  } else {
    box.innerHTML = `
      <p class="trace__detail" role="alert">
        <strong>Extracción no validada.</strong>
        ${esc(result.note_refusal_motivo || "El modelo no produjo una nota validable.")}
        Requiere revisión humana.
      </p>`;
  }
}

function renderSoap(result, finding) {
  const soap = $("#soap");
  if (!result.note) {
    soap.innerHTML = `<section>
      <div class="label">Nota no disponible</div>
      <p class="muted">${esc(result.note_refusal_motivo || "La extracción fue rechazada; no se inventa medicación.")}</p>
    </section>`;
    return;
  }
  const n = result.note;
  const blocked = result.status === "blocked";
  const fuente = result.transcript_source === "audio" ? "audio" : "transcript";
  soap.innerHTML = `
    <section>
      <div class="label">S — Subjetivo</div>
      <p>${esc(n.subjetivo)}</p>
    </section>
    <section>
      <div class="label">O — Objetivo</div>
      <p>${esc(n.objetivo)}</p>
    </section>
    <section>
      <div class="label">A — Evaluación</div>
      <p>${esc(n.evaluacion)}</p>
    </section>
    <section>
      <div class="label">P — Plan</div>
      <p>${esc(n.plan)}</p>
      ${
        blocked && finding
          ? `<div class="blocked">
               Campo bloqueado — evidencia de riesgo; el modelo no completa la indicación.<br />
               <span class="tiny" style="color: inherit">Propuesta detectada en ${esc(fuente)}: “${esc(truncate(finding.evidencia_consulta, 90))}” → rechazada por regla + HC.</span>
             </div>`
          : ""
      }
    </section>`;
}

function renderEvidence(result, finding) {
  const aside = $("#evidence-panel");
  if (result.status === "blocked" && finding) {
    aside.innerHTML = `
      <h3>Evidencia de la regla</h3>
      <p class="muted">Decisión determinista, offline — no cloud.</p>
      <blockquote>${esc(finding.motivo)}</blockquote>
      <dl class="hc-box" style="margin-top: 14px">
        <dt>Señal desde HC</dt>
        <dd>${esc(hcCorta(finding.evidencia_hc))}</dd>
        <dt>Señal desde consulta</dt>
        <dd>“${esc(truncate(finding.evidencia_consulta, 110))}”</dd>
        <dt>Motor</dt>
        <dd>Regla determinista <span class="vital">${esc(finding.rule_id)}</span></dd>
      </dl>`;
  } else if (result.status === "safe") {
    aside.innerHTML = `
      <h3>Panel de evidencia</h3>
      <p class="muted">Sin disparadores de regla. No se fuerza una alerta si no hay riesgo.</p>
      <dl class="hc-box" style="margin-top: 14px">
        <dt>Alertas</dt>
        <dd><span class="vital">0</span></dd>
        <dt>Campos bloqueados</dt>
        <dd><span class="vital">0</span></dd>
      </dl>`;
  } else {
    aside.innerHTML = `
      <h3>Panel de evidencia</h3>
      <p class="muted">La extracción no validó; el estado es <code>escalate</code>. La regla de safety igual corrió sobre el transcript crudo.</p>`;
  }
}

function renderAprobar(result, proposal) {
  const n = result.note;
  const texto = n
    ? `S: ${n.subjetivo}\nO: ${n.objetivo}\nA: ${n.evaluacion}\nP: ${n.plan}`
    : `Nota no disponible: ${result.note_refusal_motivo || "extracción rechazada"}`;
  $("#nota").value = texto;
  $("#btn-aprobar").disabled = result.status !== "safe";
  $("#aprobar-status").textContent = "";

  const strip = $("#approve-proposal-strip");
  if (proposal) {
    strip.hidden = false;
    const pending = (proposal.write_actions || []).filter(
      (a) => a.status === "pending_human"
    ).length;
    const blockedActs = (proposal.write_actions || []).filter(
      (a) => a.status === "blocked_by_safety"
    ).length;
    const gaps = (proposal.gaps || []).length;
    strip.innerHTML = `
      <strong>Agente HCE local (QVAC)</strong> —
      gate <code>${esc(proposal.safety_gate)}</code> ·
      ${pending} write(s) pending_human ·
      ${blockedActs} blocked_by_safety ·
      ${gaps} gap(s). Nada se escribe sin firmar.`;
  } else {
    strip.hidden = true;
  }
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    state.config = await res.json();
  } catch {
    state.config = { fast: false };
  }
  const banner = $("#fast-banner");
  const stack = state.config.stack;
  const stackLine = stack
    ? ` Stack QVAC: STT ${stack.stt} · LLM ${stack.llm} · safety ${stack.safety} · HCE ${stack.hce_agent}.`
    : "";
  if (state.config.fast) {
    banner.hidden = false;
    banner.innerHTML =
      `Modo <code>--fast</code>: transcript gold + reglas (~1 s). Sin Whisper ni LLM.${stackLine}`;
  } else if (stack) {
    banner.hidden = false;
    banner.innerHTML = `Track QVAC · inferencia 100% local · cloud_inference=<code>false</code>.${stackLine}`;
  } else {
    banner.hidden = true;
  }
}

async function boot() {
  await loadConfig();
  const res = await fetch("/api/cases");
  state.cases = await res.json();
  renderAgenda();
  if (state.cases[0]) selectPatient(state.cases[0].id);
}

$("#brand-home").addEventListener("click", (e) => {
  e.preventDefault();
  if (state.selectedId) selectPatient(state.selectedId);
});

$("#btn-start-rec").addEventListener("click", startRecording);
$("#btn-from-transcript").addEventListener("click", () => startRun("transcript"));
$("#btn-stop-rec").addEventListener("click", () => {
  stopLive();
  startRun(state.pendingSource);
});
$("#btn-cancel-rec").addEventListener("click", cancelRecording);
$("#btn-cancel-run").addEventListener("click", () => {
  stopPolling();
  setPhase("idle");
});
$("#btn-volver-draft").addEventListener("click", () => setPhase("draft"));
$("#btn-aprobar").addEventListener("click", () => {
  $("#aprobar-status").textContent =
    "Nota aprobada (demo local). Writes HCE quedan en pending_human — nada salió de esta máquina.";
});

boot();
