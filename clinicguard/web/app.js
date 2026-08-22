/* Shell local de ClinicGuard — port de design/mockups sobre la API del server.
   Acá no hay lógica de safety: solo se renderiza el RunResult del backend. */

"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  cases: [],
  currentCase: null,
  currentSource: null,
  runId: null,
  pollTimer: null,
  run: null, // última respuesta de GET /api/run/{id}
};

const SUBTITLES = {
  preparar: "preparar consulta",
  escuchando: "consulta en curso",
  aprobar: "aprobación humana",
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

/* ——— Navegación entre pantallas ——— */

function showScreen(name) {
  document.querySelectorAll("[data-screen]").forEach((s) => {
    s.hidden = s.dataset.screen !== name;
  });
  document.querySelectorAll(".nav-flow a").forEach((a) => {
    if (a.dataset.nav === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  if (name === "draft") {
    const blocked = state.run?.result?.status === "blocked";
    $("#topbar-sub").textContent = blocked ? "draft bloqueado" : "draft seguro";
  } else {
    $("#topbar-sub").textContent = SUBTITLES[name] || "";
  }
}

function setNavEnabled(name, enabled) {
  const a = document.querySelector(`.nav-flow a[data-nav="${name}"]`);
  if (enabled) a.removeAttribute("aria-disabled");
  else a.setAttribute("aria-disabled", "true");
}

/* ——— 01 Preparar ——— */

async function loadCases() {
  const res = await fetch("/api/cases");
  state.cases = await res.json();
  renderAgenda();
  renderHcPanel();
}

function renderAgenda() {
  const ul = $("#agenda");
  ul.innerHTML = "";
  for (const c of state.cases) {
    const li = document.createElement("li");
    const buttons = c.tiene_audio
      ? `<span style="display:flex; gap:8px; flex-wrap:wrap">
           <button class="btn btn-primary" data-case="${c.id}" data-source="audio">Iniciar</button>
           <button class="btn btn-ghost" data-case="${c.id}" data-source="transcript">Iniciar con transcript</button>
         </span>`
      : `<button class="btn btn-primary" data-case="${c.id}" data-source="transcript">Iniciar</button>`;
    li.innerHTML = `
      <div>
        <strong>${esc(c.titulo)}</strong>
        <span class="tiny">${esc(c.descripcion)}</span>
      </div>
      ${buttons}`;
    ul.appendChild(li);
  }
  ul.querySelectorAll("button[data-case]").forEach((btn) => {
    btn.addEventListener("click", () => startRun(btn.dataset.case, btn.dataset.source));
  });
}

function renderHcPanel() {
  const box = $("#hc-panel");
  box.innerHTML = "";
  for (const c of state.cases) {
    const hc = c.hc;
    const antecedentes = hc.antecedentes
      .map((a) => `${a.condicion}${a.severidad ? ` (${a.severidad})` : ""}`)
      .join(" · ");
    const medicacion = hc.medicacion_actual
      .map((m) => `${m.droga}${m.dosis ? ` ${m.dosis}` : ""}`)
      .join(" · ");
    const alergias = hc.alergias.length ? hc.alergias.join(" · ") : "Ninguna conocida";
    box.insertAdjacentHTML(
      "beforeend",
      `<p class="hc-case-title">${esc(c.titulo)}</p>
       <dl class="hc-sheet">
         <dt>Paciente</dt>
         <dd>${esc(hc.nombre)}${hc.edad ? `, ${hc.edad} años` : ""}</dd>
         <dt>Antecedentes</dt>
         <dd>${esc(antecedentes)}</dd>
         <dt>Alergias</dt>
         <dd>${esc(alergias)}</dd>
         <dt>Medicación habitual</dt>
         <dd>${esc(medicacion)}</dd>
       </dl>`
    );
  }
}

/* ——— 02 Escuchando / corrida ——— */

async function startRun(caseId, source) {
  state.currentCase = caseId;
  state.currentSource = source;
  state.run = null;
  $("#progress-steps").innerHTML = "";
  $("#run-error").hidden = true;
  $("#listen-case").textContent = `Paciente ${caseId.toUpperCase()}`;
  setNavEnabled("escuchando", true);
  setNavEnabled("draft", false);
  setNavEnabled("aprobar", false);
  showScreen("escuchando");

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ case: caseId, source }),
    });
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    state.runId = (await res.json()).run_id;
    state.pollTimer = setInterval(poll, 1200);
  } catch (err) {
    showRunError(String(err.message || err));
  }
}

async function poll() {
  try {
    const res = await fetch(`/api/run/${state.runId}`);
    const run = await res.json();
    state.run = run;
    renderSteps(run.steps);
    if (run.state === "done") {
      stopPolling();
      renderDraft(run);
      setNavEnabled("draft", true);
      setNavEnabled("aprobar", true);
      showScreen("draft");
    } else if (run.state === "error") {
      stopPolling();
      showRunError(run.error);
    }
  } catch {
    /* red local: reintenta en el próximo tick */
  }
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function renderSteps(steps) {
  $("#progress-steps").innerHTML = steps
    .map((s) => `<li>${esc(s.trim())}</li>`)
    .join("");
}

function showRunError(message) {
  const el = $("#run-error");
  el.textContent = `Error en la corrida: ${message}`;
  el.hidden = false;
}

/* ——— 03 / 04 Draft ——— */

function findingCritico(result) {
  return result.findings.find((f) => f.severidad === "critical") || null;
}

function hcCorta(evidenciaHc) {
  // "asma — severa — detalle largo…" → "Asma severa"
  const partes = evidenciaHc.split(" — ").slice(0, 2).join(" ");
  return partes.charAt(0).toUpperCase() + partes.slice(1);
}

function drogaDelMotivo(motivo) {
  const m = motivo.match(/propone\s+([a-záéíóúñ]+)/i);
  return m ? m[1] : "betabloqueante";
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
      <button class="btn btn-primary" id="btn-ir-aprobar">Corregir plan y continuar</button>
      <button class="btn btn-ghost" type="button" disabled>Aprobar nota</button>`;
    $("#draft-hint").textContent =
      "Con bloqueos abiertos, Aprobar queda deshabilitado. El camino es corregir el plan.";
  } else if (escalate) {
    actions.innerHTML = `
      <button class="btn btn-ghost" id="btn-ir-preparar">Volver a preparar</button>`;
    $("#draft-hint").textContent =
      "Sin nota validada no se puede aprobar. Reintentá la corrida o revisá el transcript.";
  } else {
    actions.innerHTML = `
      <button class="btn btn-primary" id="btn-ir-aprobar">Revisar y aprobar</button>`;
    $("#draft-hint").textContent = "";
  }
  $("#btn-ir-aprobar")?.addEventListener("click", () => {
    renderAprobar(result);
    showScreen("aprobar");
  });
  $("#btn-ir-preparar")?.addEventListener("click", () => showScreen("preparar"));

  const meta = [];
  if (result.modelo_stt)
    meta.push(`STT ${result.modelo_stt} ${result.latencia_stt_s?.toFixed(1)} s`);
  if (result.modelo_extraccion)
    meta.push(
      `Extracción ${result.modelo_extraccion} ${result.latencia_extraccion_s?.toFixed(1)} s`
    );
  meta.push("Inferencia 100% local");
  $("#draft-meta").textContent = meta.join(" · ");
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
    aside.className = "panel panel--evidence evidence";
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
    aside.className = "panel panel--dim";
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
    aside.className = "panel panel--dim";
    aside.innerHTML = `
      <h3>Panel de evidencia</h3>
      <p class="muted">La extracción no validó; el estado es <code>escalate</code>. La regla de safety igual corrió sobre el transcript crudo.</p>`;
  }
}

/* ——— 05 Aprobar ——— */

function renderAprobar(result) {
  const n = result.note;
  const texto = n
    ? `S: ${n.subjetivo}\nO: ${n.objetivo}\nA: ${n.evaluacion}\nP: ${n.plan}`
    : `Nota no disponible: ${result.note_refusal_motivo || "extracción rechazada"}`;
  $("#nota").value = texto;
  const btn = $("#btn-aprobar");
  btn.disabled = result.status !== "safe";
  $("#aprobar-status").textContent = "";
}

/* ——— Wiring global ——— */

document.querySelectorAll(".nav-flow a").forEach((a) => {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    if (a.getAttribute("aria-disabled") === "true") return;
    const name = a.dataset.nav;
    if (name === "aprobar" && state.run?.result) renderAprobar(state.run.result);
    showScreen(name);
  });
});

$("#brand-home").addEventListener("click", (e) => {
  e.preventDefault();
  showScreen("preparar");
});

$("#btn-cancelar").addEventListener("click", () => {
  stopPolling();
  showScreen("preparar");
});

$("#btn-volver-draft").addEventListener("click", () => showScreen("draft"));

$("#btn-aprobar").addEventListener("click", () => {
  $("#aprobar-status").textContent =
    "Nota aprobada (demo local). Nada salió de esta máquina.";
});

loadCases();
showScreen("preparar");
