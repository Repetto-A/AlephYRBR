/* Shell local — sala de consulta sobre la API del server.
   Sin lógica de safety: solo renderiza el RunResult del backend.
   Todo el copy es para médicos: nada de jerga técnica. */

"use strict";

const $ = (sel) => document.querySelector(sel);

const PAST_SESSIONS = {
  a: [
    { fecha: "12 mar 2026", titulo: "Control asma", tag: "firmada" },
    { fecha: "28 ene 2026", titulo: "Exacerbación leve", tag: "revisada" },
  ],
  b: [
    { fecha: "15 feb 2026", titulo: "Control de presión", tag: "firmada" },
    { fecha: "10 nov 2025", titulo: "Ajuste enalapril", tag: "firmada" },
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
    "Control programado de presión. Buena adherencia.",
    "Examen: PA 128/82 · FC 72 · peso estable.",
    "Impresión: hipertensión en buen control.",
    "Plan: continuar enalapril 10 mg/día · control en 3 meses.",
  ],
};

const PHASE_COPY = {
  idle: { kicker: "Listo para atender", pill: "En espera", sub: "consulta" },
  recording: { kicker: "Consulta en curso", pill: "Escuchando", sub: "consulta en curso" },
  write: { kicker: "Consulta escrita", pill: "Escribiendo", sub: "consulta escrita" },
  processing: { kicker: "Un momento", pill: "Preparando", sub: "preparando la nota" },
  draft: { kicker: "Borrador listo", pill: "Borrador", sub: "revisión" },
  approve: { kicker: "Revisión final", pill: "Para firmar", sub: "firma" },
};

/* Los pasos internos llegan con vocabulario técnico: acá se traducen
   a lenguaje de consultorio antes de mostrarse. */
const STEP_TRANSLATIONS = [
  [/hc cargada/i, "Leyendo la historia clínica"],
  [/transcri|escuchando|audio|stt|whisper/i, "Repasando lo que se dijo en la consulta"],
  [/extra|nota soap|qwen|llm/i, "Armando el borrador de la nota"],
  [/safety|regla|verific/i, "Revisando que el plan sea seguro"],
  [/listo|done|ok/i, "Casi listo"],
];

const state = {
  view: "home",
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
  signedToday: {},
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
  return m ? m[1] : "esta medicación";
}

function nombreDe(c) {
  return c?.hc?.nombre || c?.titulo || "Paciente";
}

/* ===== Vistas ===== */

function setView(view) {
  state.view = view;
  $("#view-home").hidden = view !== "home";
  $("#view-consult").hidden = view !== "consult";
  if (view === "home") renderHome();
}

function homeStatus(msg) {
  const el = $("#home-status");
  el.textContent = msg || "";
  el.hidden = !msg;
}

function renderHome() {
  const box = $("#patient-cards");
  box.innerHTML = "";
  if (!state.cases.length) {
    box.innerHTML = `<p class="muted">Todavía no hay pacientes cargados. Agregá el primero.</p>`;
    return;
  }
  for (const c of state.cases) {
    const firmada = Boolean(state.signedToday[c.id]);
    const card = document.createElement("button");
    card.type = "button";
    card.className = "patient-card";
    card.innerHTML = `
      <span class="patient-card__name">${esc(nombreDe(c))}${c.hc?.edad ? `<span class="patient-card__age">, ${esc(String(c.hc.edad))} años</span>` : ""}</span>
      <span class="patient-card__motivo">${esc(c.descripcion || "Consulta")}</span>
      <span class="patient-card__estado" data-done="${firmada}">${firmada ? "Nota firmada" : "Pendiente"}</span>`;
    card.addEventListener("click", () => {
      homeStatus("");
      openConsult(c.id);
    });
    box.appendChild(card);
  }
}

function openConsult(caseId) {
  setView("consult");
  selectPatient(caseId);
}

/* ===== Alta de paciente ===== */

function toggleForm(show) {
  $("#new-patient-panel").hidden = !show;
  $("#form-error").hidden = true;
  if (show) $("#f-nombre").focus();
}

async function submitPatient(event) {
  event.preventDefault();
  const errorEl = $("#form-error");
  errorEl.hidden = true;
  const nombre = $("#f-nombre").value.trim();
  if (!nombre) {
    errorEl.textContent = "Ingresá el nombre del paciente.";
    errorEl.hidden = false;
    return;
  }
  try {
    const res = await fetch("/api/patients", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nombre,
        edad: $("#f-edad").value,
        motivo: $("#f-motivo").value,
        antecedentes: $("#f-antecedentes").value,
        alergias: $("#f-alergias").value,
        medicacion: $("#f-medicacion").value,
      }),
    });
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    const nuevo = await res.json();
    state.cases.push(nuevo);
    $("#patient-form").reset();
    toggleForm(false);
    renderHome();
    homeStatus(`${nuevo.titulo} quedó registrado. Abrí su ficha cuando llegue.`);
  } catch (err) {
    errorEl.textContent = `No se pudo guardar: ${err.message || err}`;
    errorEl.hidden = false;
  }
}

/* ===== Consulta ===== */

function setPhase(phase) {
  state.phase = phase;
  document.querySelectorAll("[data-phase-panel]").forEach((el) => {
    el.hidden = el.dataset.phasePanel !== phase;
  });

  const copy = PHASE_COPY[phase] || PHASE_COPY.idle;
  $("#phase-kicker").textContent = copy.kicker;

  const pill = $("#phase-pill");
  pill.textContent = copy.pill;
  pill.dataset.phase = phase;
  delete pill.dataset.blocked;

  if (phase === "draft" && state.run?.result?.status === "blocked") {
    pill.dataset.blocked = "true";
    pill.textContent = "Retenida";
    $("#phase-kicker").textContent = "Atención: riesgo detectado";
  } else if (phase === "draft" && state.run?.result?.status === "safe") {
    pill.textContent = "Lista";
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
    btn.innerHTML = `${esc(nombreDe(c))}<span class="chip__meta">${esc(c.descripcion || "")}</span>`;
    btn.addEventListener("click", () => selectPatient(c.id));
    box.appendChild(btn);
  }
}

function renderHc(c) {
  const box = $("#hc-live");
  if (!c) {
    box.innerHTML = `<p class="muted">Elegí un paciente.</p>`;
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
    </dl>`;
}

function renderSessions(caseId) {
  const ul = $("#session-list");
  const rows = PAST_SESSIONS[caseId] || [];
  if (!rows.length) {
    ul.innerHTML = `<li class="muted">Todavía no hay consultas registradas.</li>`;
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
    <h3>Seguridad</h3>
    <p class="muted">Si el plan choca con la historia clínica, acá vas a ver por qué.</p>`;
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
  $("#patient-heading").textContent = nombreDe(c);
  $("#patient-sub").textContent = c?.descripcion || "";

  const scripted = Boolean(LIVE_LINES[caseId] || c?.tiene_audio || hasSampleTranscript(c));
  $("#btn-start-rec").hidden = !scripted;
  $("#idle-copy").textContent = scripted
    ? "Revisá la historia clínica a la izquierda y, cuando estés con el paciente, empezá la consulta."
    : "Revisá la historia clínica a la izquierda. Cuando atiendas, escribí o pegá lo conversado y Prognosia arma la nota.";
  setPhase("idle");
}

function hasSampleTranscript(c) {
  return c && (c.id === "a" || c.id === "b");
}

function startRecording() {
  const c = selectedCase();
  if (!c) return;
  state.pendingSource =
    !state.config.fast && c.tiene_audio ? "audio" : "transcript";
  setPhase("recording");
  const lines = LIVE_LINES[c.id] || [
    "Escuchando la consulta…",
    "Atendé como siempre; la nota se arma al terminar.",
  ];
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

async function startRun(source, texto) {
  const c = selectedCase();
  if (!c) return;
  stopLive();
  state.pendingSource = source;
  state.run = null;
  $("#progress-steps").innerHTML = "";
  $("#run-error").hidden = true;
  setPhase("processing");

  try {
    const body = { case: c.id, source };
    if (texto) body.texto = texto;
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    state.runId = (await res.json()).run_id;
    state.pollTimer = setInterval(poll, 900);
  } catch (err) {
    showRunError(String(err.message || err));
  }
}

function runFromText() {
  const texto = $("#consulta-texto").value.trim();
  const errorEl = $("#write-error");
  errorEl.hidden = true;
  if (texto.length < 15) {
    errorEl.textContent = "Contanos un poco más de la consulta para poder armar la nota.";
    errorEl.hidden = false;
    return;
  }
  startRun("texto", texto);
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

function translateStep(raw) {
  const s = String(raw).trim();
  for (const [pattern, friendly] of STEP_TRANSLATIONS) {
    if (pattern.test(s)) return friendly;
  }
  return null;
}

function renderSteps(steps) {
  const seen = new Set();
  const items = [];
  for (const s of steps) {
    const t = translateStep(s);
    if (t && !seen.has(t)) {
      seen.add(t);
      items.push(`<li>${esc(t)}</li>`);
    }
  }
  $("#progress-steps").innerHTML = items.join("");
}

function showRunError(message) {
  const el = $("#run-error");
  el.textContent = `Algo no salió bien: ${message}`;
  el.hidden = false;
}

function renderDraft(run) {
  const result = run.result;
  const blocked = result.status === "blocked";
  const escalate = result.status === "escalate";
  const finding = findingCritico(result);

  renderBanner(result, finding);
  renderSoap(result, finding);
  renderEvidence(result, finding);

  $("#draft-estado").textContent = blocked
    ? "La nota quedó retenida: hay una indicación que puede ser peligrosa para este paciente."
    : escalate
      ? "No se pudo armar la nota completa. Revisala manualmente antes de seguir."
      : "El borrador está listo para tu revisión.";

  $("#transcript-text").textContent = result.transcript;

  const actions = $("#draft-actions");
  if (blocked) {
    actions.innerHTML = `
      <button class="btn btn-primary" type="button" id="btn-ir-aprobar">Corregir el plan</button>
      <button class="btn btn-ghost" type="button" disabled>Firmar nota</button>
      <button class="btn btn-ghost" type="button" id="btn-nueva">Nueva consulta</button>`;
    $("#draft-hint").textContent =
      "Mientras la alerta siga activa, la firma queda deshabilitada. El camino es corregir el plan.";
  } else if (escalate) {
    actions.innerHTML = `
      <button class="btn btn-ghost" type="button" id="btn-nueva">Volver a la consulta</button>`;
    $("#draft-hint").textContent =
      "Sin una nota completa no se puede firmar. Probá de nuevo o escribí la consulta.";
  } else {
    actions.innerHTML = `
      <button class="btn btn-primary" type="button" id="btn-ir-aprobar">Revisar y firmar</button>
      <button class="btn btn-ghost" type="button" id="btn-nueva">Nueva consulta</button>`;
    $("#draft-hint").textContent = "";
  }

  $("#btn-ir-aprobar")?.addEventListener("click", () => {
    renderAprobar(result);
    setPhase("approve");
  });
  $("#btn-nueva")?.addEventListener("click", () => {
    if (state.selectedId) selectPatient(state.selectedId);
  });

  $("#draft-meta").textContent =
    "Generado en esta computadora · la información del paciente no salió de tu equipo.";
}

function renderBanner(result, finding) {
  const box = $("#draft-banner");
  if (result.status === "blocked" && finding) {
    const droga = drogaDelMotivo(finding.motivo);
    box.innerHTML = `
      <div class="trace" role="alert" aria-label="Alerta de seguridad">
        <div class="trace__node">
          <span class="trace__label">Historia clínica</span>
          <span class="trace__value">${esc(hcCorta(finding.evidencia_hc))}</span>
        </div>
        <div class="trace__connector" aria-hidden="true"></div>
        <div class="trace__node">
          <span class="trace__label">Consulta</span>
          <span class="trace__value">“${esc(truncate(finding.evidencia_consulta, 64))}”</span>
        </div>
        <div class="trace__connector" aria-hidden="true"></div>
        <div class="trace__node trace__node--blocked">
          <span class="trace__label">Seguridad</span>
          <span class="trace__value">RETENIDO</span>
        </div>
      </div>
      <p class="trace__detail">
        <strong>El plan propuesto contradice la historia clínica.</strong>
        ${esc(droga.charAt(0).toUpperCase() + droga.slice(1))} está contraindicado con los antecedentes de este paciente. No iniciar sin revisión.
      </p>`;
  } else if (result.status === "safe") {
    box.innerHTML = `
      <div class="safe-banner" role="status">
        <span class="safe-banner__mark" aria-hidden="true">OK</span>
        <div>
          <strong>Sin alertas de seguridad</strong>
          <p>El plan es compatible con la historia clínica del paciente.</p>
        </div>
      </div>`;
  } else {
    box.innerHTML = `
      <p class="trace__detail" role="alert">
        <strong>La nota quedó incompleta.</strong>
        ${esc(result.note_refusal_motivo || "No se pudo armar una nota confiable con lo que se escuchó.")}
        Revisala vos antes de seguir.
      </p>`;
  }
}

function renderSoap(result, finding) {
  const soap = $("#soap");
  if (!result.note) {
    soap.innerHTML = `<section>
      <div class="label">Nota no disponible</div>
      <p class="muted">${esc(result.note_refusal_motivo || "No se pudo armar la nota; nunca se inventa medicación.")}</p>
    </section>`;
    return;
  }
  const n = result.note;
  const blocked = result.status === "blocked";
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
               Indicación retenida por seguridad: puede ser riesgosa para este paciente.<br />
               <span class="tiny" style="color: inherit">Se detectó: “${esc(truncate(finding.evidencia_consulta, 90))}”.</span>
             </div>`
          : ""
      }
    </section>`;
}

function renderEvidence(result, finding) {
  const aside = $("#evidence-panel");
  if (result.status === "blocked" && finding) {
    aside.innerHTML = `
      <h3>¿Por qué se retuvo?</h3>
      <blockquote>${esc(finding.motivo)}</blockquote>
      <dl class="hc-box" style="margin-top: 14px">
        <dt>En la historia clínica</dt>
        <dd>${esc(hcCorta(finding.evidencia_hc))}</dd>
        <dt>En la consulta</dt>
        <dd>“${esc(truncate(finding.evidencia_consulta, 110))}”</dd>
      </dl>
      <p class="tiny" style="margin-top: 12px">La verificación se hace en tu computadora, comparando el plan con la historia clínica.</p>`;
  } else if (result.status === "safe") {
    aside.innerHTML = `
      <h3>Seguridad</h3>
      <p class="muted">No se encontraron choques entre el plan y la historia clínica.</p>
      <dl class="hc-box" style="margin-top: 14px">
        <dt>Alertas</dt>
        <dd><span class="vital">0</span></dd>
      </dl>`;
  } else {
    aside.innerHTML = `
      <h3>Seguridad</h3>
      <p class="muted">La nota quedó incompleta, pero la verificación de seguridad corrió igual sobre lo que se dijo en la consulta.</p>`;
  }
}

function renderAprobar(result) {
  const n = result.note;
  const texto = n
    ? `S: ${n.subjetivo}\nO: ${n.objetivo}\nA: ${n.evaluacion}\nP: ${n.plan}`
    : `Nota no disponible: ${result.note_refusal_motivo || "no se pudo armar la nota"}`;
  $("#nota").value = texto;
  const blocked = result.status !== "safe";
  $("#btn-aprobar").disabled = blocked;
  $("#approve-hint").textContent = blocked
    ? "Mientras la alerta de seguridad siga activa, la firma queda deshabilitada. Corregí el plan y generá la nota de nuevo."
    : "";
  $("#aprobar-status").textContent = "";
}

function firmarNota() {
  const c = selectedCase();
  if (!c) return;
  const hoy = new Date().toLocaleDateString("es-AR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  if (!PAST_SESSIONS[c.id]) PAST_SESSIONS[c.id] = [];
  PAST_SESSIONS[c.id].unshift({
    fecha: hoy,
    titulo: c.descripcion || "Consulta",
    tag: "firmada",
  });
  state.signedToday[c.id] = true;
  renderSessions(c.id);
  $("#aprobar-status").textContent =
    `Nota de ${nombreDe(c)} firmada y guardada en su historia clínica.`;
  $("#btn-aprobar").disabled = true;
  setTimeout(() => {
    setView("home");
    homeStatus(`Nota de ${nombreDe(c)} firmada. ¿Quién sigue?`);
  }, 1200);
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    state.config = await res.json();
  } catch {
    state.config = { fast: false };
  }
}

async function boot() {
  await loadConfig();
  const res = await fetch("/api/cases");
  state.cases = await res.json();
  setView("home");
}

/* ===== Tema claro / oscuro ===== */

const THEME_KEY = "prognosia-theme";

const ICON_SUN = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
  <circle cx="12" cy="12" r="4.2"/>
  <path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.2 5.2l1.7 1.7M17.1 17.1l1.7 1.7M18.8 5.2l-1.7 1.7M6.9 17.1l-1.7 1.7"/>
</svg>`;

const ICON_MOON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M20.4 14.2A8.6 8.6 0 0 1 9.8 3.6a8.6 8.6 0 1 0 10.6 10.6Z"/>
</svg>`;

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("#brand-logo").src =
    theme === "light" ? "assets/prognosiatext-dark.svg" : "assets/prognosiatext.svg";
  const btn = $("#btn-theme");
  btn.innerHTML = theme === "light" ? ICON_MOON : ICON_SUN;
  btn.setAttribute(
    "aria-label",
    theme === "light" ? "Cambiar a modo oscuro" : "Cambiar a modo claro"
  );
  btn.title = theme === "light" ? "Modo oscuro" : "Modo claro";
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* sin persistencia */
  }
}

/* ===== Eventos ===== */

applyTheme((() => {
  try {
    return localStorage.getItem(THEME_KEY) || "dark";
  } catch {
    return "dark";
  }
})());

$("#btn-theme").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});

$("#brand-home").addEventListener("click", (e) => {
  e.preventDefault();
  setView("home");
});
$("#btn-back-home").addEventListener("click", () => setView("home"));
$("#btn-nuevo-paciente").addEventListener("click", () => toggleForm($("#new-patient-panel").hidden));
$("#btn-form-cancel").addEventListener("click", () => toggleForm(false));
$("#patient-form").addEventListener("submit", submitPatient);

$("#btn-start-rec").addEventListener("click", startRecording);
$("#btn-write").addEventListener("click", () => {
  $("#write-error").hidden = true;
  setPhase("write");
  $("#consulta-texto").focus();
});
$("#btn-run-text").addEventListener("click", runFromText);
$("#btn-cancel-write").addEventListener("click", () => setPhase("idle"));
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
$("#btn-aprobar").addEventListener("click", firmarNota);

boot();
