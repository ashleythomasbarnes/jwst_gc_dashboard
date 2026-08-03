"use strict";

const DATA_URL = "./data/visits.json";
const FOOTPRINTS_URL = "./data/footprints.json";
const THEME_KEY = "jwst-gc-dashboard-theme";
const GROUP_LABELS = {
  neutral: "Flight Ready / Other",
  scheduled: "Scheduled",
  completed: "Completed",
  failed: "Failed",
};

const state = {
  data: null,
  footprints: null,
  status: "all",
  search: "",
};

const elements = {
  grid: document.querySelector("#visit-grid"),
  loading: document.querySelector("#loading-panel"),
  error: document.querySelector("#error-panel"),
  empty: document.querySelector("#empty-panel"),
  results: document.querySelector("#results-count"),
  search: document.querySelector("#search-input"),
  select: document.querySelector("#status-select"),
  updated: document.querySelector("#last-updated"),
  sourceTime: document.querySelector("#source-time"),
  title: document.querySelector("#program-title"),
  sourceLink: document.querySelector("#source-link"),
  helpLink: document.querySelector("#help-link"),
  coverageOrientation: document.querySelector("#coverage-orientation"),
  coverageAttitudeNote: document.querySelector("#coverage-attitude-note"),
  themeToggle: document.querySelector("#theme-toggle"),
  themeColor: document.querySelector("#theme-color"),
  summaryButtons: [...document.querySelectorAll("[data-status-filter]")],
  footprintMaps: [
    {
      instrument: "nircam",
      label: "NIRCam",
      canvas: document.querySelector("#nircam-map"),
      count: document.querySelector("#nircam-map-count"),
      loading: document.querySelector("#nircam-map-loading"),
    },
    {
      instrument: "miri",
      label: "MIRI",
      canvas: document.querySelector("#miri-map"),
      count: document.querySelector("#miri-map-count"),
      loading: document.querySelector("#miri-map-loading"),
    },
  ],
};

const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
let footprintRenderFrame = null;

function currentTheme() {
  return document.documentElement.dataset.theme || (themeMedia.matches ? "dark" : "light");
}

function updateThemeControl() {
  const theme = currentTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";
  const label = `Switch to ${nextTheme} theme`;
  elements.themeToggle.setAttribute("aria-label", label);
  elements.themeToggle.title = label;
  elements.themeColor.content = theme === "dark" ? "#0b1418" : "#f3f6f7";
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch (error) {
    // The theme still applies for this page view when storage is unavailable.
  }
  updateThemeControl();
  scheduleFootprintRender();
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function localTimestamp(value) {
  if (!value) return "Update time unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

function formatHours(value) {
  if (value === null || value === undefined) return "Not listed";
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
  return `${formatted} hr`;
}

function timingDetails(visit) {
  if (visit.plan_windows.length) {
    return { label: visit.plan_windows.length > 1 ? "Plan windows" : "Plan window", values: visit.plan_windows };
  }

  const times = [visit.start_time, visit.end_time].filter(Boolean);
  if (times.length) {
    return {
      label: visit.status_group === "scheduled" ? "Scheduled time (UT)" : "Observed time (UT)",
      values: [times.join(" – ")],
    };
  }

  return { label: "Timing", values: ["No timing information listed"] };
}

function detailRow(label, values) {
  const row = element("div", "detail-row");
  row.append(element("dt", "detail-row__label", label));
  const description = element("dd", "detail-row__value");
  values.forEach((value) => description.append(element("span", null, value)));
  row.append(description);
  return row;
}

function visitCard(visit) {
  const card = element("article", `visit-card status-${visit.status_group}`);
  const targetNames = visit.targets.join(", ");
  card.setAttribute("aria-label", `${targetNames}, ${visit.status}`);

  const header = element("header", "visit-card__header");
  const headingGroup = element("div");
  headingGroup.append(element("p", "visit-card__id", `Observation ${visit.observation} · Visit ${visit.visit}`));
  headingGroup.append(element("h3", "visit-card__target", targetNames));

  const badge = element("span", "status-badge");
  badge.append(element("span", "status-dot"));
  badge.firstElementChild.setAttribute("aria-hidden", "true");
  badge.append(document.createTextNode(visit.status));
  header.append(headingGroup, badge);

  const details = element("dl", "visit-card__details");
  details.append(detailRow("Observing modes", visit.configurations.length ? visit.configurations : ["Not listed"]));
  details.append(detailRow("Charged time", [formatHours(visit.hours)]));
  const timing = timingDetails(visit);
  details.append(detailRow(timing.label, timing.values));

  const footer = element("footer", "visit-card__footer");
  footer.append(element("span", `group-label group-label--${visit.status_group}`, GROUP_LABELS[visit.status_group] || "Other"));
  footer.append(element("span", "visit-card__programme", visit.id));

  card.append(header, details, footer);
  return card;
}

function searchableText(visit) {
  return [
    ...visit.targets,
    visit.status,
    visit.observation,
    visit.visit,
    ...visit.configurations,
    ...visit.plan_windows,
  ].join(" ").toLocaleLowerCase();
}

function filteredVisits() {
  const query = state.search.trim().toLocaleLowerCase();
  return state.data.visits.filter((visit) => {
    const statusMatches = state.status === "all" || visit.status_group === state.status;
    const searchMatches = !query || searchableText(visit).includes(query);
    return statusMatches && searchMatches;
  });
}

function statusColor(group) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--${group}`).trim();
}

function drawPolygon(context, polygon, color, width, height) {
  context.beginPath();
  polygon.forEach(([x, y], index) => {
    const method = index === 0 ? "moveTo" : "lineTo";
    context[method](x * width, y * height);
  });
  context.closePath();

  context.globalAlpha = 0.11;
  context.fillStyle = color;
  context.fill();

  context.globalAlpha = 0.48;
  context.strokeStyle = "#031015";
  context.lineWidth = 2.2;
  context.stroke();

  context.globalAlpha = 0.92;
  context.strokeStyle = color;
  context.lineWidth = 0.85;
  context.stroke();
}

function renderFootprints() {
  footprintRenderFrame = null;
  if (!state.data || !state.footprints) return;

  const visibleObservations = new Set(filteredVisits().map((visit) => visit.observation));
  const visitsByObservation = new Map(state.data.visits.map((visit) => [visit.observation, visit]));
  const statusOrder = { neutral: 0, scheduled: 1, completed: 2, failed: 3 };
  const fields = state.footprints.fields
    .filter((field) => visibleObservations.has(field.observation))
    .sort((a, b) => {
      const aGroup = visitsByObservation.get(a.observation)?.status_group || "neutral";
      const bGroup = visitsByObservation.get(b.observation)?.status_group || "neutral";
      return statusOrder[aGroup] - statusOrder[bGroup];
    });

  elements.footprintMaps.forEach((map) => {
    const width = map.canvas.clientWidth;
    const height = map.canvas.clientHeight;
    if (!width || !height) return;

    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    map.canvas.width = Math.round(width * pixelRatio);
    map.canvas.height = Math.round(height * pixelRatio);
    const context = map.canvas.getContext("2d");
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    fields.forEach((field) => {
      const visit = visitsByObservation.get(field.observation);
      const color = statusColor(visit?.status_group || "neutral");
      field[map.instrument].forEach((polygon) => drawPolygon(context, polygon, color, width, height));
    });
    context.globalAlpha = 1;

    const noun = fields.length === 1 ? "field" : "fields";
    map.count.textContent = `${fields.length} ${noun}`;
    map.canvas.setAttribute(
      "aria-label",
      `${map.label} nominal survey coverage showing ${fields.length} of ${state.data.visits.length} fields over a Spitzer 8 micron image`,
    );
    map.loading.hidden = true;
  });
}

function scheduleFootprintRender() {
  if (footprintRenderFrame !== null) cancelAnimationFrame(footprintRenderFrame);
  footprintRenderFrame = requestAnimationFrame(renderFootprints);
}

function showFootprintError(message) {
  elements.footprintMaps.forEach((map) => {
    map.count.textContent = "Map unavailable";
    map.loading.textContent = message;
    map.loading.hidden = false;
  });
}

function updateSelectedStatus() {
  elements.select.value = state.status;
  elements.summaryButtons.forEach((button) => {
    const selected = button.dataset.statusFilter === state.status;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function renderVisits() {
  const visits = filteredVisits();
  const fragment = document.createDocumentFragment();
  visits.forEach((visit) => fragment.append(visitCard(visit)));
  elements.grid.replaceChildren(fragment);

  const total = state.data.visits.length;
  const noun = visits.length === 1 ? "field" : "fields";
  elements.results.textContent = `Showing ${visits.length} of ${total} ${noun}`;
  elements.empty.hidden = visits.length !== 0;
  updateSelectedStatus();
  scheduleFootprintRender();
}

function setCount(id, value) {
  document.querySelector(`#count-${id}`).textContent = new Intl.NumberFormat().format(value);
}

function renderMetadata(data) {
  elements.title.textContent = data.program.title;
  elements.sourceLink.href = data.program.source_url;
  elements.helpLink.href = data.program.help_url;
  elements.updated.textContent = `Updated ${localTimestamp(data.fetched_at)}`;
  elements.sourceTime.textContent = data.report_time ? `STScI report: ${data.report_time}` : "";

  setCount("total", data.visits.length);
  Object.keys(GROUP_LABELS).forEach((group) => {
    const count = data.visits.filter((visit) => visit.status_group === group).length;
    setCount(group, count);
  });
}

function validateData(data) {
  if (!data || data.program?.id !== "10678" || !Array.isArray(data.visits) || data.visits.length === 0) {
    throw new Error("The dashboard data does not contain a valid Program 10678 visit report");
  }
}

function validateFootprints(data) {
  if (!data || data.program_id !== "10678" || !Array.isArray(data.fields) || data.fields.length === 0) {
    throw new Error("The footprint data does not contain valid Program 10678 geometry");
  }
}

async function loadDashboard() {
  try {
    const response = await fetch(DATA_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`Data request failed with HTTP ${response.status}`);
    const data = await response.json();
    validateData(data);

    state.data = data;
    renderMetadata(data);
    renderVisits();
    elements.loading.hidden = true;
  } catch (error) {
    console.error(error);
    elements.loading.hidden = true;
    elements.error.hidden = false;
    elements.results.textContent = "Visit data unavailable";
    showFootprintError("Visit status unavailable");
  }
}

async function loadFootprints() {
  try {
    const response = await fetch(FOOTPRINTS_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`Footprint request failed with HTTP ${response.status}`);
    const data = await response.json();
    validateFootprints(data);
    state.footprints = data;
    elements.coverageOrientation.textContent = `Nominal planning geometry at V3PA ${data.nominal_v3pa_degrees}°`;
    if (Array.isArray(data.approved_v3pa_range_degrees)) {
      const [minimum, maximum] = data.approved_v3pa_range_degrees;
      elements.coverageAttitudeNote.textContent = `The final on-sky orientation may differ within the approved ${minimum}–${maximum}° V3PA range.`;
    }
    scheduleFootprintRender();
  } catch (error) {
    console.error(error);
    showFootprintError("Footprint geometry unavailable");
  }
}

elements.search.addEventListener("input", (event) => {
  state.search = event.target.value;
  if (state.data) renderVisits();
});

elements.select.addEventListener("change", (event) => {
  state.status = event.target.value;
  if (state.data) renderVisits();
});

elements.summaryButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.status = button.dataset.statusFilter;
    if (state.data) renderVisits();
    document.querySelector("#visits-title").scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

elements.themeToggle.addEventListener("click", () => {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
});

themeMedia.addEventListener("change", () => {
  if (!document.documentElement.dataset.theme) {
    updateThemeControl();
    scheduleFootprintRender();
  }
});

if ("ResizeObserver" in window) {
  const footprintResizeObserver = new ResizeObserver(scheduleFootprintRender);
  elements.footprintMaps.forEach((map) => footprintResizeObserver.observe(map.canvas.parentElement));
} else {
  window.addEventListener("resize", scheduleFootprintRender);
}

updateThemeControl();
loadDashboard();
loadFootprints();
