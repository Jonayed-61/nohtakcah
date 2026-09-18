const byId = (id) => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";

const starterScenario = {
  scenario_id: "DEMO-001",
  operator_notes: ["Battery charging is unavailable from 2 PM until 4 PM."],
  hours: Array.from({ length: 24 }, (_, hour) => ({
    hour,
    demand_kwh: Math.round(88 + 28 * Math.sin(((hour - 6) * Math.PI) / 12) + (hour >= 17 && hour <= 21 ? 36 : 0)),
    solar_kwh: Math.max(0, Math.round(105 * Math.sin(((hour - 6) * Math.PI) / 12))),
    tariff_bdt_per_kwh: hour >= 17 && hour <= 21 ? 23 : hour >= 9 && hour <= 16 ? 13 : 7,
  })),
  battery: {
    capacity_kwh: 200,
    initial_energy_kwh: 100,
    minimum_energy_kwh: 20,
    max_charge_kwh_per_hour: 45,
    max_discharge_kwh_per_hour: 45,
  },
};

let sampleCases = [];
let currentResult = null;

function numberText(value, digits = 2) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Number(value));
}

function setRunStatus(message, tone = "") {
  const status = byId("runStatus");
  status.textContent = message;
  status.className = `run-status ${tone}`.trim();
}

function markDirty(message = "Inputs changed. Optimize to refresh the plan.") {
  currentResult = null;
  byId("resultsContent").hidden = true;
  byId("emptyResults").hidden = false;
  byId("downloadResultButton").disabled = true;
  setRunStatus(message);
}

function makeElement(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function renderForecastRows(hours) {
  const body = byId("forecastRows");
  body.replaceChildren();
  const forecasts = new Map(hours.map((item) => [Number(item.hour), item]));

  for (let hour = 0; hour < 24; hour += 1) {
    const values = forecasts.get(hour) || {};
    const row = document.createElement("tr");
    row.dataset.hour = String(hour);
    const hourCell = makeElement("td", "hour-cell", String(hour).padStart(2, "0"));
    hourCell.append(makeElement("span", "", `${String(hour).padStart(2, "0")}:00`));
    row.append(hourCell);

    for (const [field, label] of [
      ["demand_kwh", "Demand"],
      ["solar_kwh", "Solar"],
      ["tariff_bdt_per_kwh", "Tariff"],
    ]) {
      const cell = document.createElement("td");
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = "any";
      input.inputMode = "decimal";
      input.dataset.field = field;
      input.setAttribute("aria-label", `${label} for hour ${hour}`);
      input.value = values[field] ?? "";
      cell.append(input);
      row.append(cell);
    }
    body.append(row);
  }
}

function loadScenario(scenario, message = "Scenario loaded. Review values, then optimize.") {
  const data = scenario?.input || scenario;
  if (!data || typeof data !== "object" || !Array.isArray(data.hours) || data.hours.length !== 24 || !data.battery) {
    throw new Error("This JSON does not contain a scenario with 24 hours and a battery.");
  }
  const hours = data.hours.map((entry) => Number(entry.hour));
  if (new Set(hours).size !== 24 || hours.some((hour) => !Number.isInteger(hour) || hour < 0 || hour > 23)) {
    throw new Error("The scenario must contain each hour from 0 through 23 exactly once.");
  }

  byId("scenarioId").value = data.scenario_id ?? "";
  byId("operatorNotes").value = Array.isArray(data.operator_notes) ? data.operator_notes.join("\n") : "";
  const batteryFields = {
    capacity: "capacity_kwh",
    initialEnergy: "initial_energy_kwh",
    minimumEnergy: "minimum_energy_kwh",
    maxCharge: "max_charge_kwh_per_hour",
    maxDischarge: "max_discharge_kwh_per_hour",
  };
  for (const [inputId, key] of Object.entries(batteryFields)) {
    byId(inputId).value = data.battery[key] ?? "";
  }
  renderForecastRows(data.hours);
  markDirty(message);
}

function readNumber(input, label, min = 0) {
  const raw = input.value.trim();
  const value = Number(raw);
  if (!raw || !Number.isFinite(value) || value < min) {
    throw new Error(`${label} must be a ${min > 0 ? "positive" : "nonnegative"} number.`);
  }
  return value;
}

function collectRequest() {
  const scenarioId = byId("scenarioId").value;
  if (!scenarioId.trim()) throw new Error("Enter a scenario ID.");

  const notes = byId("operatorNotes").value.split(/\r?\n/).map((note) => note.trim()).filter(Boolean);
  if (notes.length < 1 || notes.length > 3) throw new Error("Enter 1 to 3 operator notes, one per line.");

  const battery = {
    capacity_kwh: readNumber(byId("capacity"), "Battery capacity"),
    initial_energy_kwh: readNumber(byId("initialEnergy"), "Initial battery energy"),
    minimum_energy_kwh: readNumber(byId("minimumEnergy"), "Minimum battery energy"),
    max_charge_kwh_per_hour: readNumber(byId("maxCharge"), "Maximum charge rate"),
    max_discharge_kwh_per_hour: readNumber(byId("maxDischarge"), "Maximum discharge rate"),
  };
  if (battery.capacity_kwh <= 0) throw new Error("Battery capacity must be a positive number.");
  if (battery.minimum_energy_kwh > battery.capacity_kwh || battery.initial_energy_kwh > battery.capacity_kwh || battery.initial_energy_kwh < battery.minimum_energy_kwh) {
    throw new Error("Battery energy must stay between its minimum and capacity.");
  }

  const hours = [...byId("forecastRows").querySelectorAll("tr")].map((row) => {
    const hour = Number(row.dataset.hour);
    const get = (field, label) => readNumber(row.querySelector(`[data-field="${field}"]`), `${label} at hour ${hour}`);
    return {
      hour,
      demand_kwh: get("demand_kwh", "Demand"),
      solar_kwh: get("solar_kwh", "Solar"),
      tariff_bdt_per_kwh: get("tariff_bdt_per_kwh", "Tariff"),
    };
  });
  if (hours.length !== 24) throw new Error("The forecast must include all 24 hours.");

  return { scenario_id: scenarioId, operator_notes: notes, hours, battery };
}

function downloadJSON(data, filename) {
  const blob = new Blob([`${JSON.stringify(data, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function safeFilename(id) {
  return String(id).replace(/[^a-z0-9_-]+/gi, "-").slice(0, 60) || "scenario";
}

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

function renderChart(plan, forecast) {
  const container = byId("energyChart");
  container.replaceChildren();
  const svg = svgElement("svg", { viewBox: "0 0 960 285", role: "presentation", "aria-hidden": "true" });
  const left = 48;
  const top = 20;
  const bottom = 229;
  const height = bottom - top;
  const step = 36;
  const maxValue = Math.max(1, ...forecast.map((item) => item.demand_kwh), ...plan.map((item) => item.grid_kwh + item.solar_used_kwh));
  const ceiling = Math.ceil(maxValue / 25) * 25 || 25;
  const y = (value) => bottom - (Number(value) / ceiling) * height;

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = (ceiling * tick) / 4;
    const pos = y(value);
    svg.append(svgElement("line", { x1: left, x2: 942, y1: pos, y2: pos, stroke: "#e6eee8", "stroke-width": 1 }));
    const label = svgElement("text", { x: 39, y: pos + 3, "text-anchor": "end", fill: "#8ea198", "font-size": 10 });
    label.textContent = numberText(value, 0);
    svg.append(label);
  }

  const points = [];
  for (let hour = 0; hour < 24; hour += 1) {
    const x = left + hour * step + 8;
    const grid = Number(plan[hour].grid_kwh);
    const solar = Number(plan[hour].solar_used_kwh);
    for (const [value, offset, fill, title] of [
      [grid, 0, "#218275", "Grid"],
      [solar, 13, "#cbe780", "Solar"],
    ]) {
      const bar = svgElement("rect", { x: x + offset, y: y(value), width: 11, height: Math.max(0, bottom - y(value)), rx: 2, fill });
      const label = svgElement("title");
      label.textContent = `Hour ${hour}: ${title} ${numberText(value)} kWh`;
      bar.append(label);
      svg.append(bar);
    }
    points.push(`${x + 12},${y(forecast[hour].demand_kwh)}`);
    if (hour % 4 === 0 || hour === 23) {
      const label = svgElement("text", { x: x + 11, y: 252, "text-anchor": "middle", fill: "#899d93", "font-size": 10 });
      label.textContent = String(hour).padStart(2, "0");
      svg.append(label);
    }
  }
  svg.append(svgElement("polyline", { points: points.join(" "), fill: "none", stroke: "#324e48", "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  container.append(svg);
}

function renderDirectives(directives) {
  const list = byId("directiveList");
  list.replaceChildren();
  for (const directive of directives) {
    const inactive = !directive.applies || directive.directive_type === "no_op";
    const item = makeElement("article", `directive-item${inactive ? " no-op" : ""}`);
    const head = makeElement("div", "directive-head");
    head.append(makeElement("span", "directive-type", directive.directive_type.replaceAll("_", " ")));
    head.append(makeElement("span", "directive-index", `NOTE ${directive.note_index + 1}`));
    item.append(head);
    item.append(makeElement("p", "", directive.explanation || "No explanation provided."));
    const adjustment = directive.structured_adjustment;
    if (adjustment && Array.isArray(adjustment.hours)) {
      const parts = [`Hours ${adjustment.hours.map((hour) => String(hour).padStart(2, "0")).join(", ")}`];
      if (adjustment.factor !== undefined) parts.push(`${numberText(adjustment.factor * 100)}% solar usable`);
      if (adjustment.minimum_energy_kwh !== undefined) parts.push(`Reserve ≥ ${numberText(adjustment.minimum_energy_kwh)} kWh`);
      if (adjustment.max_grid_kwh !== undefined) parts.push(`Grid ≤ ${numberText(adjustment.max_grid_kwh)} kWh`);
      item.append(makeElement("span", "directive-meta", parts.join(" · ")));
    } else {
      item.append(makeElement("span", "directive-meta", "No schedule adjustment"));
    }
    list.append(item);
  }
}

function renderPlanRows(plan) {
  const body = byId("planRows");
  body.replaceChildren();
  for (const entry of plan) {
    const row = document.createElement("tr");
    row.append(makeElement("td", "hour-cell", `${String(entry.hour).padStart(2, "0")}:00`));
    row.append(makeElement("td", "", numberText(entry.grid_kwh, 3)));
    row.append(makeElement("td", "", numberText(entry.solar_used_kwh, 3)));
    const actionCell = document.createElement("td");
    actionCell.append(makeElement("span", `action-pill ${entry.battery_action}`, entry.battery_action));
    row.append(actionCell);
    row.append(makeElement("td", "", numberText(entry.battery_kwh, 3)));
    row.append(makeElement("td", "", numberText(entry.battery_energy_after_kwh, 3)));
    body.append(row);
  }
}

function renderResult(data, request) {
  if (!Array.isArray(data.hourly_plan) || data.hourly_plan.length !== 24 || !Array.isArray(data.directive_interpretation)) {
    throw new Error("The server returned an incomplete plan.");
  }
  currentResult = data;
  byId("totalCost").textContent = numberText(data.total_cost_bdt);
  byId("totalGrid").textContent = numberText(data.total_grid_kwh);
  byId("peakGrid").textContent = numberText(data.peak_grid_kwh);
  byId("directiveCount").textContent = String(data.directive_interpretation.filter((entry) => entry.applies).length);
  byId("resultScenarioId").textContent = data.scenario_id;
  byId("planSummary").textContent = data.plan_summary;
  renderChart(data.hourly_plan, request.hours);
  renderDirectives(data.directive_interpretation);
  renderPlanRows(data.hourly_plan);
  byId("emptyResults").hidden = true;
  byId("resultsContent").hidden = false;
  byId("downloadResultButton").disabled = false;
  byId("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function optimize() {
  let request;
  try {
    request = collectRequest();
  } catch (error) {
    setRunStatus(error.message, "error");
    return;
  }
  markDirty("Interpreting notes and calculating the schedule. This can take a few seconds…");
  const button = byId("runButton");
  button.disabled = true;
  button.classList.add("busy");
  button.querySelector(".button-label").textContent = "Optimizing";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 35000);
  try {
    const response = await fetch("/optimize-energy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Request failed with HTTP ${response.status}.`);
    renderResult(data, request);
    setRunStatus(`Plan ready for ${data.scenario_id}. All 24 hours were verified.`, "success");
  } catch (error) {
    const message = error.name === "AbortError" ? "The request took too long. Please try again." : error.message;
    setRunStatus(message, "error");
  } finally {
    clearTimeout(timer);
    button.disabled = false;
    button.classList.remove("busy");
    button.querySelector(".button-label").textContent = "Optimize energy";
  }
}

async function checkHealth() {
  const chip = byId("healthStatus");
  try {
    const response = await fetch("/health", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.status !== "ok") throw new Error("Unhealthy API");
    chip.className = "health-chip";
    chip.innerHTML = '<span class="health-dot"></span>API online';
  } catch {
    chip.className = "health-chip offline";
    chip.innerHTML = '<span class="health-dot"></span>API unavailable';
  }
}

byId("resetButton").addEventListener("click", () => loadScenario(starterScenario, "Starter example loaded. Review values, then optimize."));
byId("runButton").addEventListener("click", optimize);
byId("downloadRequestButton").addEventListener("click", () => {
  try {
    const request = collectRequest();
    downloadJSON(request, `${safeFilename(request.scenario_id)}-request.json`);
    setRunStatus("Request JSON downloaded.", "success");
  } catch (error) {
    setRunStatus(error.message, "error");
  }
});
byId("downloadResultButton").addEventListener("click", () => {
  if (currentResult) downloadJSON(currentResult, `${safeFilename(currentResult.scenario_id)}-result.json`);
});
byId("chooseFileButton").addEventListener("click", () => {
  byId("sampleFile").value = "";
  byId("sampleFile").click();
});
byId("sampleFile").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    byId("fileName").textContent = file.name;
    const cases = Array.isArray(payload) ? payload : payload?.cases;
    if (Array.isArray(cases) && cases.length) {
      sampleCases = cases;
      const select = byId("caseSelect");
      select.replaceChildren();
      cases.forEach((item, index) => {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = `${item.id || item.input?.scenario_id || `Case ${index + 1}`} · ${item.label || "Public scenario"}`;
        select.append(option);
      });
      select.disabled = false;
      select.value = "0";
      loadScenario(cases[0], `${cases[0].id || "First case"} loaded. Review values, then optimize.`);
    } else {
      sampleCases = [];
      byId("caseSelect").replaceChildren(new Option("Single scenario loaded", ""));
      byId("caseSelect").disabled = true;
      loadScenario(payload, "JSON scenario loaded. Review values, then optimize.");
    }
  } catch (error) {
    setRunStatus(`Could not load JSON: ${error.message}`, "error");
  }
});
byId("caseSelect").addEventListener("change", (event) => {
  const selected = sampleCases[Number(event.target.value)];
  if (!selected) return;
  try {
    loadScenario(selected, `${selected.id || "Case"} loaded. Review values, then optimize.`);
  } catch (error) {
    setRunStatus(error.message, "error");
  }
});

for (const input of document.querySelectorAll(".setup-panel input, .setup-panel textarea")) {
  input.addEventListener("input", () => markDirty());
}
byId("forecastRows").addEventListener("input", () => markDirty());

loadScenario(starterScenario, "Starter example loaded. Review values, then optimize.");
checkHealth();
