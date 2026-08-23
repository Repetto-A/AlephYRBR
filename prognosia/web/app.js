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
  [/hc cargada|leyendo la historia/i, "Leyendo la historia clínica"],
  [/transcri|escuchando|audio|stt|whisper/i, "Repasando lo que se dijo en la consulta"],
  [/correcci[oó]n del m[eé]dico|revalida/i, "Tomando tu corrección del plan"],
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
  correcting: false,
  previousRun: null,
  previousRunId: null,
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

const VIEWS = ["home", "cal", "patients", "consult", "prefs", "profile"];

function setView(view) {
  state.view = view;
  VIEWS.forEach((v) => {
    const el = $("#view-" + (v === "consult" ? "consult" : v));
    if (el) el.hidden = v !== view;
  });
  document.querySelectorAll(".sidenav").forEach((b) => {
    b.setAttribute("aria-current", b.dataset.nav === view ? "true" : "false");
  });
  if (view === "home") renderHome();
  if (view === "cal") renderCalDay();
  if (view === "patients") renderPatients();
  if (view === "prefs") fillPrefsForm();
  if (view === "profile") fillProfileForm();
}

function homeStatus(msg) {
  const el = $("#home-status");
  el.textContent = msg || "";
  el.hidden = !msg;
}

/* ===== Identidad del médico y memoria clínica (localStorage) ===== */

const DOCTOR_KEY = "prognosia-doctor";
const PREFS_KEY = "prognosia-prefs";

const DOCTOR_DEFAULT = {
  nombre: "Dra. Valeria Sosa",
  especialidad: "Clínica médica",
  matricula: "MN 112.334",
  clinica: "Clínica del Parque",
  sede: "CABA · Consultorio 12",
};

function loadJson(key, fallback) {
  try {
    return { ...fallback, ...(JSON.parse(localStorage.getItem(key)) || {}) };
  } catch {
    return { ...fallback };
  }
}

function getDoctor() { return loadJson(DOCTOR_KEY, DOCTOR_DEFAULT); }
function getPrefs() {
  return loadJson(PREFS_KEY, { medicamentos: "", farmaceuticas: "", indicaciones: "", estilo: "concisa" });
}

function hasPrefs() {
  const pr = getPrefs();
  return Boolean(pr.medicamentos || pr.farmaceuticas || pr.indicaciones);
}

function renderDoctor() {
  const d = getDoctor();
  const iniciales = d.nombre.replace(/^Dra?\.?\s*/i, "").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "PR";
  $("#doctor-avatar").textContent = iniciales;
  $("#doctor-chip-name").textContent = d.nombre;
  $("#doctor-chip-spec").textContent = d.especialidad;
  $("#clinic-card-name").textContent = d.clinica;
  $("#clinic-card-sede").textContent = d.sede;
}

/* ===== Agenda del día (horarios de demo sobre pacientes reales) ===== */

const SLOT_MINS = [540, 580, 620, 700, 840, 880, 920, 960, 1000, 1040];
const CITA_DUR = 35;

function fmtHora(min) {
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}

function buildSchedule() {
  state.schedule = state.cases.map((c, i) => ({
    id: "cita-" + c.id,
    caseId: c.id,
    hora: SLOT_MINS[i % SLOT_MINS.length],
    dur: CITA_DUR,
    nombre: nombreDe(c),
    motivo: c.descripcion || "Consulta",
    cancelada: false,
  }));
  state.schedule.push({
    id: "cita-maria",
    caseId: null,
    hora: 660,
    dur: CITA_DUR,
    nombre: "María Torres",
    motivo: "Renovación de recetas",
    cancelada: true,
  });
}

function citaEstado(r) {
  if (r.cancelada) return "cancelada";
  if (r.caseId && state.signedToday[r.caseId]) return "atendida";
  return "confirmada";
}

function scheduleToday() {
  if (!state.schedule) buildSchedule();
  return [...state.schedule].sort((a, b) => a.hora - b.hora).map((r) => ({
    ...r,
    horaTxt: fmtHora(r.hora),
    estado: citaEstado(r),
  }));
}

function renderHome() {
  const d = getDoctor();
  const ahora = new Date();
  const h = ahora.getHours();
  const saludo = h < 13 ? "Buen día" : h < 20 ? "Buenas tardes" : "Buenas noches";
  $("#dash-greeting").textContent = `${saludo}, ${d.nombre.split(" ")[0] === d.nombre ? d.nombre : d.nombre.replace(/^(Dra?\.?)\s+(\S+).*$/i, "$1 $2")}`;
  $("#dash-date").textContent = ahora.toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" }) + ` · ${d.clinica}`;

  const agenda = scheduleToday();
  const atendidas = agenda.filter((r) => r.estado === "atendida").length;
  const canceladas = agenda.filter((r) => r.estado === "cancelada").length;
  const pendientes = agenda.length - atendidas - canceladas;
  const minutos = atendidas * 12;
  $("#dash-stats").innerHTML = `
    <div class="stat-tile"><b>${agenda.length - canceladas}</b><span>Citas hoy</span></div>
    <div class="stat-tile"><b>${atendidas}</b><span>Atendidas</span></div>
    <div class="stat-tile"><b>${pendientes}</b><span>Por atender</span></div>
    <div class="stat-tile"><b>${canceladas}</b><span>Canceladas</span></div>
    <div class="stat-tile"><b>${minutos}′</b><span>Tiempo ahorrado</span></div>`;

  $("#dash-agenda").innerHTML = agenda
    .map((r) => `
      <li><button type="button" class="agenda-row" data-case="${esc(r.caseId || "")}" data-cancelada="${r.estado === "cancelada"}">
        <span class="agenda-row__time">${esc(r.horaTxt)}</span>
        <span class="agenda-row__name">${esc(r.nombre)}</span>
        <span class="agenda-row__motivo">${esc(r.motivo)}</span>
        <span class="agenda-badge" data-k="${esc(r.estado)}">${esc(r.estado)}</span>
      </button></li>`)
    .join("");
  $("#dash-agenda").querySelectorAll(".agenda-row").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.cancelada === "true" || !btn.dataset.case) return;
      homeStatus("");
      openConsult(btn.dataset.case);
    });
  });

  renderCalendar();
}

function renderCalendar() {
  const hoy = new Date();
  const y = hoy.getFullYear();
  const m = hoy.getMonth();
  $("#cal-title").textContent = hoy.toLocaleDateString("es-AR", { month: "long", year: "numeric" }).replace(/^./, (c) => c.toUpperCase());
  const first = new Date(y, m, 1);
  const offset = (first.getDay() + 6) % 7;
  const days = new Date(y, m + 1, 0).getDate();
  const conCitas = new Set([hoy.getDate(), Math.min(days, hoy.getDate() + 2), Math.min(days, hoy.getDate() + 5), Math.max(1, hoy.getDate() - 3)]);
  let html = ["L", "M", "M", "J", "V", "S", "D"].map((d) => `<span class="dow">${d}</span>`).join("");
  for (let i = 0; i < offset; i++) html += `<span class="cal-day cal-day--off"></span>`;
  for (let d = 1; d <= days; d++) {
    const cls = ["cal-day"];
    if (d === hoy.getDate()) cls.push("cal-day--today");
    if (conCitas.has(d)) cls.push("cal-day--dot");
    const dow = new Date(y, m, d).getDay();
    if (dow === 0 || dow === 6) cls.push("cal-day--off");
    html += `<span class="${cls.join(" ")}">${d}</span>`;
  }
  $("#dash-cal").innerHTML = html;
}

/* ===== Agenda de día (calendario con drag & drop) ===== */

const CAL_START = 480;
const CAL_END = 1080;
const PX_MIN = 840 / (CAL_END - CAL_START);

let toastTimer = null;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

function renderCalDay() {
  if (!state.schedule) buildSchedule();
  const hoy = new Date();
  $("#cal-day-date").textContent = hoy.toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" });
  const box = $("#cal-day");
  let html = "";
  for (let m = CAL_START; m <= CAL_END; m += 30) {
    const top = (m - CAL_START) * PX_MIN;
    const half = m % 60 !== 0;
    html += `<div class="cal-hour${half ? " cal-hour--half" : ""}" style="top:${top}px">${half ? "" : fmtHora(m)}</div>`;
  }
  const ahora = hoy.getHours() * 60 + hoy.getMinutes();
  if (ahora >= CAL_START && ahora <= CAL_END) {
    html += `<div class="cal-now" data-hora="${fmtHora(ahora)}" style="top:${(ahora - CAL_START) * PX_MIN}px"></div>`;
  }
  box.innerHTML = html;
  for (const r of scheduleToday()) {
    const el = document.createElement("div");
    el.className = "cal-evt";
    el.dataset.cita = r.id;
    el.dataset.estado = r.estado;
    el.style.top = (r.hora - CAL_START) * PX_MIN + "px";
    el.style.height = Math.max(34, r.dur * PX_MIN) + "px";
    el.innerHTML = `
      <span class="cal-evt__time">${esc(r.horaTxt)}</span>
      <span class="cal-evt__body"><b>${esc(r.nombre)}</b><span>${esc(r.motivo)}</span></span>
      <button type="button" class="cal-evt__x" title="${r.estado === "cancelada" ? "Eliminar cita" : "Cancelar cita"}" aria-label="Cancelar cita">✕</button>`;
    attachEvtHandlers(el);
    box.appendChild(el);
  }
}

function citaById(id) {
  return (state.schedule || []).find((r) => r.id === id) || null;
}

function attachEvtHandlers(el) {
  const id = el.dataset.cita;

  el.querySelector(".cal-evt__x").addEventListener("click", (e) => {
    e.stopPropagation();
    const r = citaById(id);
    if (!r) return;
    if (r.cancelada) {
      state.schedule = state.schedule.filter((x) => x.id !== id);
      toast(`Cita de ${r.nombre} eliminada.`);
    } else {
      r.cancelada = true;
      toast(`Cita de ${r.nombre} cancelada.`);
    }
    renderCalDay();
  });

  let drag = null;
  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".cal-evt__x")) return;
    const r = citaById(id);
    if (!r) return;
    drag = { startY: e.clientY, horaInicial: r.hora, moved: false };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dy = e.clientY - drag.startY;
    if (Math.abs(dy) > 6) drag.moved = true;
    if (!drag.moved) return;
    el.classList.add("dragging");
    const r = citaById(id);
    let nueva = drag.horaInicial + Math.round(dy / PX_MIN / 10) * 10;
    nueva = Math.max(CAL_START, Math.min(CAL_END - r.dur, nueva));
    r.hora = nueva;
    el.style.top = (nueva - CAL_START) * PX_MIN + "px";
    el.querySelector(".cal-evt__time").textContent = fmtHora(nueva);
  });
  el.addEventListener("pointerup", () => {
    if (!drag) return;
    const fueDrag = drag.moved;
    drag = null;
    el.classList.remove("dragging");
    const r = citaById(id);
    if (fueDrag) {
      toast(`Cita de ${r.nombre} movida a ${fmtHora(r.hora)}.`);
      renderCalDay();
    } else {
      openCitaPop(id);
    }
  });
}

function openCitaPop(id) {
  const r = citaById(id);
  if (!r) return;
  const c = state.cases.find((x) => x.id === r.caseId) || null;
  const hc = c?.hc || null;
  const ant = hc ? (hc.antecedentes || []).map((a) => `${a.condicion}${a.severidad ? ` (${a.severidad})` : ""}`).join(" · ") : "";
  const med = hc ? (hc.medicacion_actual || []).map((m) => `${m.droga}${m.dosis ? ` ${m.dosis}` : ""}`).join(" · ") : "";
  const ale = hc ? ((hc.alergias || []).join(" · ") || "Ninguna conocida") : "";
  const est = hc ? (hc.estudios || []).length : 0;
  const enc = c?.encounters_count || 0;
  const estado = citaEstado(r);
  $("#cita-pop-card").innerHTML = `
    <h3>${esc(r.nombre)}${hc?.edad ? `, ${esc(String(hc.edad))} años` : ""}</h3>
    <p class="cita-pop__sub">${esc(fmtHora(r.hora))} hs · ${esc(r.motivo)} · <span class="agenda-badge" data-k="${esc(estado)}">${esc(estado)}</span></p>
    ${hc ? `
    <dl>
      <dt>Antecedentes</dt><dd>${esc(ant || "Sin antecedentes registrados")}</dd>
      <dt>Alergias</dt><dd>${esc(ale)}</dd>
      <dt>Medicación habitual</dt><dd>${esc(med || "Sin medicación registrada")}</dd>
      <dt>Historial</dt><dd>${enc} consulta${enc === 1 ? "" : "s"} registrada${enc === 1 ? "" : "s"} · ${est} estudio${est === 1 ? "" : "s"}</dd>
    </dl>` : `<p class="muted" style="font-size:.9rem">Sin ficha en la clínica (cita externa).</p>`}
    <div class="actions">
      ${c && estado !== "cancelada" ? `<button class="btn btn-primary" type="button" id="pop-iniciar">Iniciar consulta</button>` : ""}
      ${estado !== "cancelada" ? `<button class="btn btn-ghost" type="button" id="pop-cancelar">Cancelar cita</button>` : `<button class="btn btn-ghost" type="button" id="pop-eliminar">Eliminar</button>`}
      <button class="btn btn-ghost" type="button" id="pop-cerrar">Cerrar</button>
    </div>`;
  $("#cita-pop").hidden = false;
  $("#pop-cerrar").addEventListener("click", closeCitaPop);
  $("#pop-iniciar")?.addEventListener("click", () => { closeCitaPop(); openConsult(r.caseId); });
  $("#pop-cancelar")?.addEventListener("click", () => {
    r.cancelada = true;
    closeCitaPop();
    renderCalDay();
    toast(`Cita de ${r.nombre} cancelada.`);
  });
  $("#pop-eliminar")?.addEventListener("click", () => {
    state.schedule = state.schedule.filter((x) => x.id !== r.id);
    closeCitaPop();
    renderCalDay();
    toast(`Cita de ${r.nombre} eliminada.`);
  });
}

function closeCitaPop() {
  $("#cita-pop").hidden = true;
}

function openNuevaCita(hora) {
  const opts = state.cases.map((c) => `<option value="${esc(c.id)}">${esc(nombreDe(c))}</option>`).join("");
  $("#cita-pop-card").innerHTML = `
    <h3>Nueva cita</h3>
    <p class="cita-pop__sub">${esc(fmtHora(hora))} hs · elegí el paciente</p>
    <select id="nueva-cita-paciente" class="note-doc" style="margin:0 0 16px;width:100%">${opts}</select>
    <div class="actions">
      <button class="btn btn-primary" type="button" id="pop-crear">Agendar</button>
      <button class="btn btn-ghost" type="button" id="pop-cerrar">Cerrar</button>
    </div>`;
  $("#cita-pop").hidden = false;
  $("#pop-cerrar").addEventListener("click", closeCitaPop);
  $("#pop-crear").addEventListener("click", () => {
    const caseId = $("#nueva-cita-paciente").value;
    const c = state.cases.find((x) => x.id === caseId);
    if (!c) return;
    state.schedule.push({
      id: "cita-" + caseId + "-" + Date.now(),
      caseId,
      hora,
      dur: CITA_DUR,
      nombre: nombreDe(c),
      motivo: c.descripcion || "Consulta",
      cancelada: false,
    });
    closeCitaPop();
    renderCalDay();
    toast(`Cita de ${nombreDe(c)} agendada a las ${fmtHora(hora)}.`);
  });
}

/* ===== Lista de pacientes con búsqueda ===== */

function patientMatches(c, q) {
  if (!q) return true;
  const hc = c.hc || {};
  const blob = [nombreDe(c), c.descripcion, (hc.antecedentes || []).map((a) => a.condicion).join(" "), (hc.alergias || []).join(" ")].join(" ").toLowerCase();
  return q.toLowerCase().split(/\s+/).every((w) => blob.includes(w));
}

function renderPatients() {
  const q = $("#patient-search").value.trim();
  const list = $("#patient-list");
  const visibles = state.cases.filter((c) => patientMatches(c, q));
  $("#patients-count").textContent = q
    ? `${visibles.length} de ${state.cases.length} pacientes`
    : `${state.cases.length} pacientes en la clínica`;
  if (!visibles.length) {
    list.innerHTML = `<li class="patient-row" style="cursor:default"><span class="muted">Sin resultados para “${esc(q)}”.</span></li>`;
    return;
  }
  list.innerHTML = visibles
    .map((c) => {
      const firmada = Boolean(state.signedToday[c.id]);
      const ini = nombreDe(c).split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
      const enc = c.encounters_count ? ` · ${c.encounters_count} consulta${c.encounters_count === 1 ? "" : "s"}` : "";
      return `
      <li><button type="button" class="patient-row" data-case="${esc(c.id)}">
        <span class="patient-row__avatar">${esc(ini)}</span>
        <span class="patient-row__meta">
          <b>${esc(nombreDe(c))}${c.hc?.edad ? `, ${esc(String(c.hc.edad))} años` : ""}</b>
          <span>${esc(c.descripcion || "Consulta")}${enc}</span>
        </span>
        <span class="patient-card__estado" data-done="${firmada}">${firmada ? "Nota firmada" : "Pendiente"}</span>
      </button></li>`;
    })
    .join("");
  list.querySelectorAll(".patient-row[data-case]").forEach((btn) => {
    btn.addEventListener("click", () => openConsult(btn.dataset.case));
  });
}

/* ===== Formularios de memoria y perfil ===== */

function fillPrefsForm() {
  const pr = getPrefs();
  $("#pref-medicamentos").value = pr.medicamentos;
  $("#pref-farmaceuticas").value = pr.farmaceuticas;
  $("#pref-indicaciones").value = pr.indicaciones;
  $("#pref-estilo").value = pr.estilo;
}

function fillProfileForm() {
  const d = getDoctor();
  $("#prof-nombre").value = d.nombre;
  $("#prof-especialidad").value = d.especialidad;
  $("#prof-matricula").value = d.matricula;
  $("#prof-clinica").value = d.clinica;
  $("#prof-sede").value = d.sede;
}

/* ===== Pacientes de demo para poblar la agenda ===== */

const SEED_PATIENTS = [
  { nombre: "Marta Quiroga", edad: 61, motivo: "Control de diabetes", antecedentes: "diabetes tipo 2, hipertensión arterial", medicacion: "metformina, losartán" },
  { nombre: "Lucía Ferreyra", edad: 29, motivo: "Migraña recurrente", antecedentes: "asma severa", medicacion: "salbutamol" },
  { nombre: "Raúl Mendoza", edad: 72, motivo: "Control post-operatorio", antecedentes: "cardiopatía isquémica", medicacion: "aspirina, atorvastatina" },
  { nombre: "Carla Domínguez", edad: 38, motivo: "Chequeo anual", antecedentes: "", medicacion: "" },
  { nombre: "Bruno Castillo", edad: 45, motivo: "Dolor lumbar", antecedentes: "", alergias: "ibuprofeno", medicacion: "" },
  { nombre: "Tomás Aguirre", edad: 8, motivo: "Fiebre y tos", antecedentes: "", alergias: "penicilina", medicacion: "" },
];

async function seedDemoPatients() {
  if (state.cases.length > 4) return;
  for (const p of SEED_PATIENTS) {
    try {
      const res = await fetch("/api/patients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      if (res.ok) state.cases.push(await res.json());
    } catch {
      /* demo */
    }
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
    if (state.schedule) {
      const ultima = Math.max(CAL_START, ...state.schedule.map((r) => r.hora + r.dur));
      state.schedule.push({
        id: "cita-" + nuevo.id,
        caseId: nuevo.id,
        hora: Math.min(CAL_END - CITA_DUR, ultima + 5),
        dur: CITA_DUR,
        nombre: nuevo.titulo,
        motivo: nuevo.descripcion || "Consulta",
        cancelada: false,
      });
    }
    $("#patient-form").reset();
    toggleForm(false);
    renderPatients();
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
  const estudios = hc.estudios || [];
  const pendientes = estudios.filter((e) =>
    ["pedido", "pendiente_resultado"].includes(e.estado)
  );
  const conResultado = estudios.filter((e) => e.estado === "con_resultado");
  const estudiosHtml = estudios.length
    ? `<ul class="hc-estudios">${estudios
        .map((e) => {
          const tag =
            e.estado === "con_resultado"
              ? "resultado"
              : e.estado === "pendiente_resultado"
                ? "pendiente"
                : e.estado === "pedido"
                  ? "pedido"
                  : e.estado;
          const extra =
            e.estado === "con_resultado" && e.resultado
              ? `<span class="tiny">${esc(truncate(e.resultado, 90))}</span>`
              : e.pedido_en
                ? `<span class="tiny">pedido ${esc(e.pedido_en)}</span>`
                : "";
          return `<li><span class="tag" data-status="${esc(tag)}">${esc(tag)}</span> <strong>${esc(e.tipo)}</strong> — ${esc(e.detalle)}${extra ? `<br />${extra}` : ""}</li>`;
        })
        .join("")}</ul>`
    : `<dd class="muted">Sin estudios cargados</dd>`;

  box.innerHTML = `
    <p class="hc-live-title">${esc(hc.nombre)}${hc.edad ? `, ${hc.edad} años` : ""}</p>
    <dl class="hc-sheet">
      <dt>Antecedentes</dt>
      <dd>${esc(antecedentes || "—")}</dd>
      <dt>Alergias</dt>
      <dd>${esc(alergias)}</dd>
      <dt>Medicación habitual</dt>
      <dd>${esc(medicacion || "—")}</dd>
      <dt>Estudios <span class="tiny">(${pendientes.length} abiertos · ${conResultado.length} con resultado)</span></dt>
      <dd>${estudiosHtml}</dd>
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
    <h3>Evidencia (RAG local)</h3>
    <p class="muted">Si hay near-miss, acá aparece la guía local indexada (offline) — no PubMed.</p>`;
}

function selectPatient(caseId) {
  stopLive();
  stopPolling();
  state.selectedId = caseId;
  state.run = null;
  state.runId = null;
  state.correcting = false;
  state.previousRun = null;
  state.previousRunId = null;
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

function setRecordingChrome(correcting) {
  $("#rec-kicker").textContent = correcting ? "Corrección del plan" : "Escuchando…";
  $("#btn-stop-rec").textContent = correcting
    ? "Terminar y revalidar"
    : "Terminar y armar la nota";
  $("#rec-hint").textContent = correcting
    ? "Decí el plan nuevo (por ejemplo: no indico propranolol, paso a diltiazem). Al terminar se vuelve a revisar la seguridad."
    : "Atendé como siempre: mirá al paciente, no al teclado. La nota se arma al terminar.";
}

function setWriteChrome(correcting) {
  $("#write-heading").textContent = correcting
    ? "¿Cuál es el plan corregido?"
    : "¿Qué se habló en la consulta?";
  $("#write-lead").textContent = correcting
    ? "La indicación anterior chocó con la historia clínica. Escribí el plan nuevo. Prognosia vuelve a validar y, si está bien, vas a poder firmar."
    : "Escribí o pegá lo conversado con el paciente. Prognosia arma el borrador de la nota y revisa que el plan sea seguro.";
  $("#consulta-texto").placeholder = correcting
    ? "Ej.: No indico propranolol. Paso a diltiazem 60 mg cada 12 horas y control en dos semanas."
    : "Ej.: Paciente refiere dolor de cabeza de tres días… Examen: PA 120/80… Plan: voy a indicar…";
  $("#btn-run-text").textContent = correcting ? "Revalidar el plan" : "Armar la nota";
}

function startRecording() {
  const c = selectedCase();
  if (!c) return;
  state.correcting = false;
  setRecordingChrome(false);
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
  stopMicCapture();
  $("#live-transcript").textContent = "";
  if (state.correcting) {
    setRecordingChrome(false);
    setPhase("draft");
    return;
  }
  setPhase("idle");
}

/* ——— Mic local → WAV PCM 16 kHz (corrección del plan) ——— */

const micState = {
  stream: null,
  ctx: null,
  processor: null,
  sourceNode: null,
  mute: null,
  chunks: [],
  sampleRate: 48000,
  startedAt: 0,
  tickTimer: null,
};

function mergeFloatChunks(chunks) {
  let n = 0;
  for (const c of chunks) n += c.length;
  const out = new Float32Array(n);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}

function downsampleTo16k(input, fromRate) {
  if (fromRate === 16000) return input;
  const ratio = fromRate / 16000;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    out[i] = input[Math.floor(i * ratio)] || 0;
  }
  return out;
}

function encodeWavPcm16(samples, sampleRate) {
  const n = samples.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const view = new DataView(buf);
  const writeStr = (off, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + n * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, n * 2, true);
  let off = 44;
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    off += 2;
  }
  return buf;
}

function bufToB64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

async function startMicCapture() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Este navegador no permite usar el micrófono.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true },
  });
  const ctx = new AudioContext();
  const sourceNode = ctx.createMediaStreamSource(stream);
  const mute = ctx.createGain();
  mute.gain.value = 0;
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  processor.onaudioprocess = (ev) => {
    chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
  };
  sourceNode.connect(processor);
  processor.connect(mute);
  mute.connect(ctx.destination);
  micState.stream = stream;
  micState.ctx = ctx;
  micState.processor = processor;
  micState.sourceNode = sourceNode;
  micState.mute = mute;
  micState.chunks = chunks;
  micState.sampleRate = ctx.sampleRate;
  micState.startedAt = Date.now();
  clearInterval(micState.tickTimer);
  micState.tickTimer = setInterval(() => {
    const sec = ((Date.now() - micState.startedAt) / 1000).toFixed(0);
    $("#live-transcript").textContent = `Grabando corrección… ${sec} s`;
  }, 400);
}

function stopMicCapture() {
  clearInterval(micState.tickTimer);
  micState.tickTimer = null;
  try {
    micState.processor?.disconnect();
    micState.sourceNode?.disconnect();
    micState.mute?.disconnect();
  } catch {
    /* ya desconectado */
  }
  micState.stream?.getTracks().forEach((t) => t.stop());
  if (micState.ctx && micState.ctx.state !== "closed") {
    micState.ctx.close();
  }
  const chunks = micState.chunks.slice();
  const rate = micState.sampleRate || 48000;
  micState.stream = null;
  micState.ctx = null;
  micState.processor = null;
  micState.sourceNode = null;
  micState.mute = null;
  micState.chunks = [];
  if (!chunks.length) return null;
  const merged = mergeFloatChunks(chunks);
  const pcm16k = downsampleTo16k(merged, rate);
  return encodeWavPcm16(pcm16k, 16000);
}

async function startCorrectionRecording() {
  if (state.config.fast) {
    openCorrectionWrite();
    return;
  }
  state.correcting = true;
  setRecordingChrome(true);
  setPhase("recording");
  $("#live-transcript").textContent = "Pidiendo permiso de micrófono…";
  try {
    await startMicCapture();
  } catch (err) {
    $("#live-transcript").textContent = "";
    setRecordingChrome(false);
    setPhase("draft");
    alert(`No se pudo abrir el mic: ${err.message || err}`);
  }
}

function openCorrectionWrite() {
  state.correcting = true;
  setWriteChrome(true);
  $("#write-error").hidden = true;
  $("#consulta-texto").value = "";
  setPhase("write");
  $("#consulta-texto").focus();
}

async function startRun(source, texto) {
  const c = selectedCase();
  if (!c) return;
  stopLive();
  state.pendingSource = source;
  state.correcting = false;
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

async function startCorrection({ texto, audioWavB64 }) {
  if (!state.runId) {
    showRunError("No hay una nota retenida para corregir.");
    return;
  }
  stopLive();
  state.previousRun = state.run;
  state.previousRunId = state.runId;
  $("#progress-steps").innerHTML = "";
  $("#run-error").hidden = true;
  setPhase("processing");

  const body = {};
  if (texto) body.texto = texto;
  if (audioWavB64) body.audio_wav_b64 = audioWavB64;

  try {
    const res = await fetch(`/api/run/${state.runId}/correct`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error((await res.json()).error || res.statusText);
    state.runId = (await res.json()).run_id;
    state.pollTimer = setInterval(poll, 900);
  } catch (err) {
    showRunError(String(err.message || err));
    if (state.previousRunId) {
      state.runId = state.previousRunId;
      state.run = state.previousRun;
    }
  }
}

function runFromText() {
  const texto = $("#consulta-texto").value.trim();
  const errorEl = $("#write-error");
  errorEl.hidden = true;
  const min = state.correcting ? 8 : 15;
  if (texto.length < min) {
    errorEl.textContent = state.correcting
      ? "Escribí el plan nuevo para poder revalidarlo."
      : "Contanos un poco más de la consulta para poder armar la nota.";
    errorEl.hidden = false;
    return;
  }
  if (state.correcting) {
    startCorrection({ texto });
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
      state.correcting = false;
      state.previousRun = null;
      state.previousRunId = null;
      setWriteChrome(false);
      setRecordingChrome(false);
      renderDraft(run);
      setPhase("draft");
    } else if (run.state === "error") {
      stopPolling();
      showRunError(run.error);
      if (state.previousRun) {
        state.runId = state.previousRunId;
        state.run = state.previousRun;
        state.correcting = false;
      }
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
  renderProposal(run.proposal);

  $("#draft-estado").textContent = blocked
    ? "La nota quedó retenida: hay una indicación que puede ser peligrosa para este paciente."
    : escalate
      ? "No se pudo armar la nota completa. Revisala manualmente antes de seguir."
      : "El borrador está listo para tu revisión.";

  $("#transcript-text").textContent = result.transcript_correccion
    ? `${result.transcript}\n\n— Corrección del plan —\n${result.transcript_correccion}`
    : result.transcript;

  const actions = $("#draft-actions");
  if (blocked) {
    actions.innerHTML = `
      <button class="btn btn-primary" type="button" id="btn-correct-audio">Corregir el plan hablando</button>
      <button class="btn btn-ghost" type="button" id="btn-correct-write">Corregir por escrito</button>
      <button class="btn btn-ghost" type="button" id="btn-nueva">Nueva consulta</button>`;
    $("#draft-hint").textContent =
      "La firma queda deshabilitada mientras la alerta siga activa. Corregí el plan (audio o texto) para volver a validar y poder firmar.";
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
    renderAprobar(result, run.proposal);
    setPhase("approve");
  });
  $("#btn-correct-audio")?.addEventListener("click", () => {
    startCorrectionRecording();
  });
  $("#btn-correct-write")?.addEventListener("click", () => {
    openCorrectionWrite();
  });
  $("#btn-nueva")?.addEventListener("click", () => {
    if (state.selectedId) selectPatient(state.selectedId);
  });

  $("#draft-meta").textContent =
    "Generado en esta computadora · la información del paciente no salió de tu equipo." +
    (hasPrefs() ? " · Ajustado a tu memoria clínica." : "");
}

const ACTION_STATUS = {
  pending_human: "Esperando tu firma",
  blocked_by_safety: "Retenida por seguridad",
  skipped: "Omitida",
};

const GAP_SEVERITY = { info: "Dato", warning: "Atención" };

function renderProposal(proposal) {
  const panel = $("#proposal-panel");
  if (!proposal) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;

  const gate = $("#proposal-gate");
  const cerrado = proposal.safety_gate === "closed";
  gate.textContent = cerrado ? "Registro retenido" : "Listo para registrar";
  gate.dataset.gate = proposal.safety_gate;

  const acciones = (proposal.write_actions || []).length;
  $("#proposal-summary").textContent = acciones
    ? `Prognosia preparó ${acciones === 1 ? "1 registro" : acciones + " registros"} para esta consulta. Nada se guarda sin tu confirmación.`
    : "No hay registros pendientes para esta consulta.";
  $("#proposal-note").textContent =
    "Nada se escribe en la historia clínica sin tu confirmación.";

  const soap = proposal.soap_delta || {};
  $("#proposal-soap").innerHTML =
    ["S", "O", "A", "P"]
      .filter((k) => soap[k])
      .map((k) => `<dt>${k}</dt><dd>${esc(truncate(soap[k], 140))}</dd>`)
      .join("") || "<dd class='muted'>Sin cambios para registrar</dd>";

  $("#proposal-actions").innerHTML =
    (proposal.write_actions || [])
      .map(
        (a) =>
          `<li><span class="tag" data-status="${esc(a.status)}">${esc(ACTION_STATUS[a.status] || a.status)}</span>${esc(a.summary)}</li>`
      )
      .join("") || "<li class='muted'>Sin acciones pendientes</li>";

  $("#proposal-gaps").innerHTML =
    (proposal.gaps || [])
      .map(
        (g) =>
          `<li><span class="tag">${esc(GAP_SEVERITY[g.severity] || g.severity)}</span><strong>${esc(g.title)}</strong><br /><span class="tiny">${esc(g.detail)}</span></li>`
      )
      .join("") || "<li class='muted'>Nada pendiente de visitas anteriores</li>";
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
        ${esc(droga.charAt(0).toUpperCase() + droga.slice(1))} está contraindicado con los antecedentes de este paciente. No iniciar sin revisión. Corregí el plan hablando o por escrito para revalidar.
      </p>`;
  } else if (result.status === "safe") {
    const revalidado = result.transcript_correccion
      ? " El plan se revalidó después de tu corrección."
      : "";
    box.innerHTML = `
      <div class="safe-banner" role="status">
        <span class="safe-banner__mark" aria-hidden="true">OK</span>
        <div>
          <strong>Sin alertas de seguridad</strong>
          <p>El plan es compatible con la historia clínica del paciente.${revalidado}</p>
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
    const g = finding.guia;
    const snippets =
      Array.isArray(finding.rag_snippets) && finding.rag_snippets.length
        ? finding.rag_snippets
        : g
          ? [g]
          : [];
    const primary = snippets[0] || g;
    const modeLabel =
      primary?.mode === "local_rag"
        ? "RAG local (BM25 · guías markdown)"
        : primary?.mode === "local_lookup"
          ? "Lookup estático (evidence.json)"
          : "Sin hit de guía";
    const guideBlock = primary
      ? `<div style="margin: 10px 0 14px">
          <p class="tiny" style="margin:0 0 4px"><strong>Guía local</strong> · ${esc(modeLabel)}</p>
          <p class="tiny" style="margin:0 0 8px"><strong>${esc(primary.title)}</strong>${
            primary.section ? ` · § ${esc(primary.section)}` : ""
          }</p>
          <blockquote>“${esc(primary.citation || finding.motivo)}”</blockquote>
          <p class="tiny">${esc(primary.source || "")}${
            primary.score != null ? ` · score ${esc(String(primary.score))}` : ""
          }</p>
        </div>`
      : `<blockquote>${esc(finding.motivo)}</blockquote>`;
    aside.innerHTML = `
      <h3>Evidencia (RAG local)</h3>
      <p class="muted">Guía indexada offline — no PubMed / no cloud. Solo refuerza la explicación; la decisión es la regla.</p>
      ${guideBlock}
      <dl class="hc-box" style="margin-top: 14px">
        <dt>En la historia clínica</dt>
        <dd>${esc(hcCorta(finding.evidencia_hc))}</dd>
        <dt>En la consulta</dt>
        <dd>“${esc(truncate(finding.evidencia_consulta, 110))}”</dd>
        <dt>Motor</dt>
        <dd>Regla <span class="vital">${esc(finding.rule_id)}</span>${
          primary ? ` + <code>${esc(primary.guide_id || primary.doc_id || "")}</code>` : ""
        }</dd>
      </dl>`;
  } else if (result.status === "safe") {
    aside.innerHTML = `
      <h3>Seguridad</h3>
      <p class="muted">Sin findings. El RAG local no se fuerza en consultas safe.</p>
      <dl class="hc-box" style="margin-top: 14px">
        <dt>Alertas</dt>
        <dd><span class="vital">0</span></dd>
        <dt>Corpus local</dt>
        <dd class="tiny">guidelines/ indexadas; retrieval solo si hay blocked</dd>
      </dl>`;
  } else {
    aside.innerHTML = `
      <h3>Seguridad</h3>
      <p class="muted">La nota quedó incompleta, pero la verificación de seguridad corrió igual sobre lo que se dijo en la consulta.</p>`;
  }
}

function renderAprobar(result, proposal) {
  const n = result.note;
  const texto = n
    ? `S: ${n.subjetivo}\nO: ${n.objetivo}\nA: ${n.evaluacion}\nP: ${n.plan}`
    : `Nota no disponible: ${result.note_refusal_motivo || "no se pudo armar la nota"}`;
  $("#nota").value = texto;
  const gateClosed = proposal && proposal.safety_gate === "closed";
  const blocked = result.status !== "safe" || !!gateClosed;
  $("#btn-aprobar").disabled = blocked;
  $("#approve-hint").textContent = blocked
    ? gateClosed
      ? "Safety gate cerrado: la firma queda deshabilitada hasta corregir el plan."
      : "Mientras la alerta de seguridad siga activa, la firma queda deshabilitada. Corregí el plan y generá la nota de nuevo."
    : "";
  $("#aprobar-status").textContent = "";

  const strip = $("#approve-proposal-strip");
  if (proposal) {
    strip.hidden = false;
    const pendientes = (proposal.write_actions || []).filter(
      (a) => a.status === "pending_human"
    ).length;
    const retenidas = (proposal.write_actions || []).filter(
      (a) => a.status === "blocked_by_safety"
    ).length;
    const partes = [];
    if (pendientes) partes.push(`${pendientes} ${pendientes === 1 ? "acción espera" : "acciones esperan"} tu firma`);
    if (retenidas) partes.push(`${retenidas} ${retenidas === 1 ? "quedó retenida" : "quedaron retenidas"} por seguridad`);
    if (gateClosed) partes.push("gate cerrado");
    strip.innerHTML = `<strong>Al firmar se registra en la historia clínica.</strong> ${esc(partes.join(" · ") || "Sin acciones pendientes.")}`;
  } else {
    strip.hidden = true;
  }
}

async function firmarNota() {
  const c = selectedCase();
  if (!c) return;
  const status = $("#aprobar-status");
  const btn = $("#btn-aprobar");
  if (!state.runId) {
    status.textContent = "No hay corrida activa para firmar.";
    return;
  }
  btn.disabled = true;
  status.textContent = "Firmando y guardando en la historia clínica local…";
  try {
    const res = await fetch("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: state.runId,
        edited_soap: $("#nota")?.value || null,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.error || `No se pudo firmar (${res.status})`;
      btn.disabled = false;
      return;
    }
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
    const casesRes = await fetch("/api/cases");
    state.cases = await casesRes.json();
    renderAgenda();
    renderSessions(c.id);
    const n = (data.applied_action_ids || []).length;
    status.textContent =
      `Nota de ${nombreDe(c)} firmada · encuentro ${data.encounter_id} · ${n} acción(es) en HC local.`;
    setTimeout(() => {
      setView("home");
      homeStatus(`Nota de ${nombreDe(c)} firmada. ¿Quién sigue?`);
    }, 1200);
  } catch (err) {
    status.textContent = `Fallo al firmar: ${err}`;
    btn.disabled = false;
  }
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
  await seedDemoPatients();
  renderDoctor();
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
document.querySelectorAll("[data-nav]").forEach((b) => {
  b.addEventListener("click", () => setView(b.dataset.nav));
});
$("#btn-dash-nuevo").addEventListener("click", () => {
  setView("patients");
  toggleForm(true);
});
$("#patient-search").addEventListener("input", renderPatients);
$("#cal-day").addEventListener("click", (e) => {
  if (e.target.closest(".cal-evt")) return;
  const rect = $("#cal-day").getBoundingClientRect();
  let hora = CAL_START + Math.round((e.clientY - rect.top) / PX_MIN / 10) * 10;
  hora = Math.max(CAL_START, Math.min(CAL_END - CITA_DUR, hora));
  openNuevaCita(hora);
});
$("#cita-pop").addEventListener("click", (e) => {
  if (e.target === $("#cita-pop")) closeCitaPop();
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#cita-pop").hidden) closeCitaPop();
});
$("#prefs-form").addEventListener("submit", (e) => {
  e.preventDefault();
  localStorage.setItem(PREFS_KEY, JSON.stringify({
    medicamentos: $("#pref-medicamentos").value.trim(),
    farmaceuticas: $("#pref-farmaceuticas").value.trim(),
    indicaciones: $("#pref-indicaciones").value.trim(),
    estilo: $("#pref-estilo").value,
  }));
  $("#prefs-status").textContent = "Preferencias guardadas. Prognosia las tiene en cuenta al armar tus notas.";
});
$("#profile-form").addEventListener("submit", (e) => {
  e.preventDefault();
  localStorage.setItem(DOCTOR_KEY, JSON.stringify({
    nombre: $("#prof-nombre").value.trim() || DOCTOR_DEFAULT.nombre,
    especialidad: $("#prof-especialidad").value.trim(),
    matricula: $("#prof-matricula").value.trim(),
    clinica: $("#prof-clinica").value.trim(),
    sede: $("#prof-sede").value.trim(),
  }));
  renderDoctor();
  $("#profile-status").textContent = "Perfil actualizado.";
});
$("#btn-nuevo-paciente").addEventListener("click", () => toggleForm($("#new-patient-panel").hidden));
$("#btn-form-cancel").addEventListener("click", () => toggleForm(false));
$("#patient-form").addEventListener("submit", submitPatient);

$("#btn-start-rec").addEventListener("click", startRecording);
$("#btn-write").addEventListener("click", () => {
  state.correcting = false;
  setWriteChrome(false);
  $("#write-error").hidden = true;
  setPhase("write");
  $("#consulta-texto").focus();
});
$("#btn-run-text").addEventListener("click", runFromText);
$("#btn-cancel-write").addEventListener("click", () => {
  setWriteChrome(false);
  if (state.correcting) {
    state.correcting = false;
    setPhase("draft");
    return;
  }
  setPhase("idle");
});
$("#btn-stop-rec").addEventListener("click", async () => {
  stopLive();
  if (state.correcting) {
    const wav = stopMicCapture();
    if (!wav) {
      showRunError("No se capturó audio. Reintentá la corrección.");
      setPhase("draft");
      return;
    }
    await startCorrection({ audioWavB64: bufToB64(wav) });
    return;
  }
  startRun(state.pendingSource);
});
$("#btn-cancel-rec").addEventListener("click", cancelRecording);
$("#btn-cancel-run").addEventListener("click", () => {
  stopPolling();
  if (state.correcting || state.previousRun) {
    if (state.previousRunId) {
      state.runId = state.previousRunId;
      state.run = state.previousRun;
    }
    state.correcting = false;
    setPhase("draft");
    return;
  }
  setPhase("idle");
});
$("#btn-volver-draft").addEventListener("click", () => setPhase("draft"));
$("#btn-aprobar").addEventListener("click", firmarNota);

boot();
