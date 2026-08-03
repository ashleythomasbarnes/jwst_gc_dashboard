"use strict";

const DATA_URL = "./data/visits.json";
const GROUP_LABELS = {
  neutral: "Flight Ready / Other",
  scheduled: "Scheduled",
  completed: "Completed",
  failed: "Failed",
};

const state = {
  data: null,
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
  summaryButtons: [...document.querySelectorAll("[data-status-filter]")],
};

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

loadDashboard();
