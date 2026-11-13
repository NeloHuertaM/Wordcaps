"use strict";

const TOKEN = document.querySelector('meta[name="wordcaps-token"]').content;
const SETTINGS_KEY = "wordcaps.settings";
const ANIMATION_LABELS = { none: "Ninguna", pop: "Pop", bounce: "Rebote", grow: "Crecer", punch: "Golpe" };
const MODE_ACCUMULATE = "accumulate";
const MESSAGE_ERROR = "error";
const MESSAGE_OK = "ok";
const CHECKBOX_TYPE = "checkbox";
const JOB_STATE = { DONE: "done", FAILED: "failed" };
const ACTION_BUTTONS = ["transcribe", "place", "run-all", "install-script", "create-template"];

const state = { words: [], timeline: null, templates: [], layout: null, busy: false, defaults: null, animations: [] };
const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const options = { headers: { "X-WordCaps-Token": TOKEN } };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || `Error ${response.status}`);
  return payload.result;
}

function showMessage(text, kind = "") {
  const box = $("message");
  box.textContent = text;
  box.className = `message ${kind}`;
}

function lockActions() {
  state.busy = true;
  for (const id of ACTION_BUTTONS) $(id).disabled = true;
}

function unlockActions() {
  state.busy = false;
  for (const id of ACTION_BUTTONS) $(id).disabled = false;
}

function loadSettings() {
  const defaults = { ...state.defaults, keywords: state.defaults.keywords.join(", ") };
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
  } catch {
    stored = {};
  }
  const settings = { ...defaults, ...stored };
  for (const name of ["animation", "emphasis_animation"]) {
    if (!state.animations.includes(settings[name])) settings[name] = defaults[name];
  }
  return settings;
}

function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    return;
  }
}

function fillSettingsForm(settings) {
  const form = $("settings");
  for (const element of form.elements) {
    if (!(element.name in settings)) continue;
    if (element.type === CHECKBOX_TYPE) element.checked = Boolean(settings[element.name]);
    else element.value = settings[element.name];
  }
}

function readSettings() {
  const settings = {};
  for (const element of $("settings").elements) {
    if (!element.name) continue;
    if (element.type === CHECKBOX_TYPE) settings[element.name] = element.checked;
    else if (element.type === "number") settings[element.name] = Number(element.value);
    else settings[element.name] = element.value;
  }
  return settings;
}

const GLYPHS = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]_abcdefghijklmnopqrstuvwxyz"
  + "ÁÉÍÓÚÜÑÀÈÌÒÙÇÂÊÎÔÛÄËÏÖáéíóúüñàèìòùçâêîôûäëïöß¿¡…’«»";
const FONT_WEIGHTS = { thin: 100, extralight: 200, light: 300, regular: 400, medium: 500,
  semibold: 600, bold: 700, extrabold: 800, black: 900, heavy: 900 };
const glyphCache = new Map();

function cssFont(settings, px) {
  const weight = FONT_WEIGHTS[settings.font_style.toLowerCase().replace(/[\s-]/g, "")] || 400;
  const italic = /italic|oblique/i.test(settings.font_style) ? "italic " : "";
  return `${italic}${weight} ${px}px "${settings.font}", sans-serif`;
}

function measureGlyphs(settings) {
  const key = `${settings.font}|${settings.font_style}`;
  if (glyphCache.has(key)) return glyphCache.get(key);
  const context = document.createElement("canvas").getContext("2d");
  const em = 100;
  context.font = cssFont(settings, em);
  const widths = {};
  for (const ch of GLYPHS) widths[ch] = Math.round((context.measureText(ch).width / em) * 1000) / 1000;
  glyphCache.set(key, widths);
  return widths;
}

function settingsForApi() {
  const settings = readSettings();
  return {
    ...settings,
    keywords: settings.keywords.split(",").map((k) => k.trim()).filter(Boolean),
    glyph_widths: measureGlyphs(settings),
  };
}

function selectedTemplate() {
  const id = $("template-select").value;
  return state.templates.find((t) => t.id === id) || null;
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    const pill = $("resolve-pill");
    if (status.resolve.online) {
      pill.textContent = `Resolve conectado (${status.resolve.info.product} ${status.resolve.info.version})`;
      pill.className = "pill pill-on";
    } else {
      pill.textContent = "Resolve sin conectar";
      pill.className = "pill pill-off";
    }
    const details = [];
    details.push(status.scriptInstalled ? "Script instalado." : "Script sin instalar.");
    if (!status.prefsFound) details.push("No encuentro Fusion.prefs: abre Resolve al menos una vez.");
    if (!status.resolve.online) details.push(status.resolve.error);
    $("connection-detail").textContent = details.join(" ");
    fillModels(status.whisper);
    if (status.resolve.online) {
      await Promise.allSettled([refreshTemplates(), refreshTimeline()]);
    }
  } catch (error) {
    showMessage(error.message, MESSAGE_ERROR);
  }
}

function fillModels(whisper) {
  const select = $("model");
  const current = select.value || whisper.defaultModel;
  select.innerHTML = "";
  for (const model of whisper.models) {
    const option = new Option(`${model.label} (${model.sizeMb} MB)${model.installed ? " ✓" : ""}`, model.id);
    select.add(option);
  }
  select.value = current;
}

function fillAnimations() {
  for (const select of document.querySelectorAll(".animation-select")) {
    for (const name of state.animations) select.add(new Option(ANIMATION_LABELS[name] || name, name));
  }
}

async function refreshTemplates() {
  const result = await api("/api/templates", {});
  state.templates = result.templates;
  const select = $("template-select");
  const previous = select.value;
  select.innerHTML = "";
  if (!state.templates.length) select.add(new Option("Sin plantillas en el Media Pool", ""));
  for (const template of state.templates) select.add(new Option(template.name, template.id));
  const preferred = state.templates.find((t) => t.id === previous) || state.templates.find((t) => t.name.startsWith("WordCaps"));
  if (preferred) select.value = preferred.id;
}

async function refreshTimeline() {
  state.timeline = await api("/api/timeline", {});
  const canvas = $("preview");
  const scale = 640 / Math.max(state.timeline.width, state.timeline.height);
  canvas.width = Math.round(state.timeline.width * scale);
  canvas.height = Math.round(state.timeline.height * scale);
  schedulePreview();
}

function setWords(words) {
  state.words = words;
  renderWords();
  schedulePreview();
}

function renderWords() {
  const box = $("words");
  box.innerHTML = "";
  $("word-count").textContent = state.words.length ? `${state.words.length} palabras. Puedes corregirlas aquí.` : "";
  state.words.forEach((word, index) => {
    const input = document.createElement("input");
    input.value = word.text;
    input.size = Math.max(2, word.text.length);
    input.title = `${word.start.toFixed(2)} s – ${word.end.toFixed(2)} s`;
    input.addEventListener("change", () => {
      state.words[index] = { ...state.words[index], text: input.value.trim() || state.words[index].text };
      schedulePreview();
    });
    box.appendChild(input);
  });
}

let previewTimer = null;
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(updateLayout, 250);
}

async function updateLayout() {
  saveSettings(readSettings());
  if (!state.words.length) {
    state.layout = null;
    drawPreview();
    return;
  }
  try {
    state.layout = await api("/api/layout", { words: state.words, settings: settingsForApi(), timeline: state.timeline });
    const last = state.layout.groups.at(-1);
    $("scrub").max = last ? last.end.toFixed(2) : 0;
    $("preview-info").textContent = `${state.layout.groups.length} grupos, ${state.layout.clips.length} clips Text+ en ${state.layout.lanes} pistas.`;
    drawPreview();
  } catch (error) {
    $("preview-info").textContent = error.message;
  }
}

function drawPreview() {
  const canvas = $("preview");
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  if (!state.layout) return;
  const settings = readSettings();
  const time = Number($("scrub").value);
  const group = state.layout.groups.find((g) => time >= g.start && time < g.end) || state.layout.groups.find((g) => g.start >= time);
  if (!group) return;
  const at = Math.max(time, group.start);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineJoin = "round";
  for (const word of group.words) {
    if (word.start > at) continue;
    const px = word.size * canvas.width;
    const active = at >= word.start && at < word.end;
    context.font = cssFont(settings, px);
    const x = word.x * canvas.width;
    const y = (1 - word.y) * canvas.height;
    if (settings.outline) {
      context.lineWidth = Math.max(1, settings.outline_thickness * px * 2);
      context.strokeStyle = settings.outline_color;
      context.strokeText(word.text, x, y);
    }
    const highlighted = word.emphasis || (settings.highlight_active && settings.mode === MODE_ACCUMULATE && active);
    context.fillStyle = highlighted ? settings.highlight_color : settings.color;
    context.fillText(word.text, x, y);
  }
}

async function followJob(jobId) {
  $("job").classList.remove("hidden");
  for (;;) {
    const job = await api(`/api/jobs/${jobId}`);
    $("job-stage").textContent = job.stage + (job.progress != null ? ` (${Math.round(job.progress * 100)} %)` : "");
    $("job-bar").style.width = job.progress != null ? `${Math.round(job.progress * 100)}%` : "100%";
    if (job.state === JOB_STATE.DONE) return job.result;
    if (job.state === JOB_STATE.FAILED) throw new Error(job.error);
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}

async function runJob(start, onDone) {
  if (state.busy) return;
  lockActions();
  showMessage("");
  try {
    const { job } = await start();
    const result = await followJob(job);
    onDone(result);
  } catch (error) {
    showMessage(error.message, MESSAGE_ERROR);
  } finally {
    unlockActions();
    $("job").classList.add("hidden");
  }
}

function placedMessage(result) {
  const failed = result.failed ? `\n${result.failed} fallaron: ${result.firstError}` : "";
  return `Listo: ${result.placed} clips Text+ en las pistas V${result.tracks.join(", V")}.${failed}`;
}

function requireTemplate() {
  const template = selectedTemplate();
  if (!template) showMessage("Elige una plantilla Text+ del Media Pool (paso 2).", MESSAGE_ERROR);
  return template;
}

function bindEvents() {
  $("refresh-status").addEventListener("click", refreshStatus);
  $("refresh-templates").addEventListener("click", () => refreshTemplates().catch((e) => showMessage(e.message, MESSAGE_ERROR)));

  $("install-script").addEventListener("click", async () => {
    try {
      const result = await api("/api/install-script", {});
      showMessage(`Script instalado en ${result.path}. Ábrelo desde Workspace › Scripts › WordCaps.`, MESSAGE_OK);
      refreshStatus();
    } catch (error) {
      showMessage(error.message, MESSAGE_ERROR);
    }
  });

  $("create-template").addEventListener("click", async () => {
    try {
      await api("/api/create-template", {});
      showMessage("Text+ insertado en el cabezal. Arrástralo al Media Pool y renómbralo a WordCaps Word.", MESSAGE_OK);
    } catch (error) {
      showMessage(error.message, MESSAGE_ERROR);
    }
  });

  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("hidden", b.id !== tab.dataset.tab));
    });
  }

  $("srt-file").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const result = await api("/api/import-srt", { content: await file.text() });
      setWords(result.words);
      showMessage(`SRT importado: ${result.words.length} palabras.`, MESSAGE_OK);
    } catch (error) {
      showMessage(error.message, MESSAGE_ERROR);
    }
  });

  $("transcribe").addEventListener("click", () =>
    runJob(
      () => api("/api/transcribe", { model: $("model").value, language: $("language").value }),
      (result) => {
        state.timeline = result.timeline;
        setWords(result.words);
        showMessage(`Transcripción lista: ${result.words.length} palabras.`, MESSAGE_OK);
        refreshStatus();
      },
    ),
  );

  $("place").addEventListener("click", () => {
    const template = requireTemplate();
    if (!template) return;
    if (!state.words.length) {
      showMessage("No hay palabras: transcribe o importa un SRT primero.", MESSAGE_ERROR);
      return;
    }
    runJob(
      () => api("/api/place", { words: state.words, settings: settingsForApi(), template }),
      (result) => showMessage(placedMessage(result), result.failed ? MESSAGE_ERROR : MESSAGE_OK),
    );
  });

  $("run-all").addEventListener("click", () => {
    const template = requireTemplate();
    if (!template) return;
    runJob(
      () => api("/api/run-all", { model: $("model").value, language: $("language").value, settings: settingsForApi(), template }),
      (result) => {
        setWords(result.words);
        showMessage(placedMessage(result), result.failed ? MESSAGE_ERROR : MESSAGE_OK);
      },
    );
  });

  $("settings").addEventListener("input", schedulePreview);
  $("scrub").addEventListener("input", drawPreview);
}

async function init() {
  try {
    const defaults = await api("/api/defaults");
    state.defaults = defaults.settings;
    state.animations = defaults.animations;
  } catch (error) {
    showMessage(`No pude cargar la configuración: ${error.message}`, MESSAGE_ERROR);
    return;
  }
  fillAnimations();
  fillSettingsForm(loadSettings());
  bindEvents();
  refreshStatus();
}

init();
