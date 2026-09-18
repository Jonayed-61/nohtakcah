const byId = (id) => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";

// Preset Scenarios
const presets = {
  starter: {
    scenario_id: "DEMO-CAMPUS-001",
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
  },
  solarSurplus: {
    scenario_id: "SOLAR-SURPLUS-002",
    operator_notes: ["Solar generation reduced to 50% between 10 AM and 3 PM."],
    hours: Array.from({ length: 24 }, (_, hour) => ({
      hour,
      demand_kwh: Math.round(65 + 18 * Math.sin(((hour - 6) * Math.PI) / 12)),
      solar_kwh: Math.max(0, Math.round(160 * Math.sin(((hour - 6) * Math.PI) / 12))),
      tariff_bdt_per_kwh: hour >= 17 && hour <= 21 ? 25 : hour >= 9 && hour <= 16 ? 14 : 8,
    })),
    battery: {
      capacity_kwh: 250,
      initial_energy_kwh: 120,
      minimum_energy_kwh: 30,
      max_charge_kwh_per_hour: 50,
      max_discharge_kwh_per_hour: 50,
    },
  },
  eveningSpike: {
    scenario_id: "EVENING-SPIKE-003",
    operator_notes: ["Cap grid power at 80 kWh per hour from 5 PM to 9 PM."],
    hours: Array.from({ length: 24 }, (_, hour) => ({
      hour,
      demand_kwh: Math.round(75 + (hour >= 17 && hour <= 21 ? 85 : 15 * Math.sin(((hour - 6) * Math.PI) / 12))),
      solar_kwh: Math.max(0, Math.round(90 * Math.sin(((hour - 6) * Math.PI) / 12))),
      tariff_bdt_per_kwh: hour >= 17 && hour <= 21 ? 28 : hour >= 9 && hour <= 16 ? 12 : 6,
    })),
    battery: {
      capacity_kwh: 220,
      initial_energy_kwh: 110,
      minimum_energy_kwh: 25,
      max_charge_kwh_per_hour: 50,
      max_discharge_kwh_per_hour: 60,
    },
  },
  batteryMaintenance: {
    scenario_id: "BATTERY-MAINT-004",
    operator_notes: ["Keep battery reserve at least 40% from 6 PM to 10 PM."],
    hours: Array.from({ length: 24 }, (_, hour) => ({
      hour,
      demand_kwh: Math.round(80 + 25 * Math.sin(((hour - 6) * Math.PI) / 12)),
      solar_kwh: Math.max(0, Math.round(100 * Math.sin(((hour - 6) * Math.PI) / 12))),
      tariff_bdt_per_kwh: hour >= 17 && hour <= 21 ? 22 : hour >= 9 && hour <= 16 ? 12 : 7,
    })),
    battery: {
      capacity_kwh: 200,
      initial_energy_kwh: 100,
      minimum_energy_kwh: 40,
      max_charge_kwh_per_hour: 40,
      max_discharge_kwh_per_hour: 40,
    },
  },
};

let sampleCases = [];
let currentResult = null;
let currentRequest = null;
let tableFilter = "all";

// Helper utilities
function numberText(value, digits = 2) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Number(value));
}

function showToast(message, type = "info") {
  const container = byId("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  const iconMap = { success: "✅", error: "⚠️", info: "ℹ️" };
  toast.innerHTML = `<span>${iconMap[type] || "ℹ️"}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function setRunStatus(message, tone = "") {
  const status = byId("runStatus");
  status.textContent = message;
  status.className = `run-status ${tone}`.trim();
}

function markDirty(message = "Inputs modified. Click Optimize Energy Plan to calculate schedule.") {
  currentResult = null;
  byId("resultsContent").hidden = true;
  byId("emptyResults").hidden = false;
  byId("downloadResultButton").disabled = true;
  byId("exportCsvButton").disabled = true;
  setRunStatus(message);
}

function makeElement(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

// Update table cell heatmaps
function updateCellHeatmaps() {
  const rows = [...byId("forecastRows").querySelectorAll("tr")];
  const fields = ["demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"];
  const maxVals = { demand_kwh: 1, solar_kwh: 1, tariff_bdt_per_kwh: 1 };

  rows.forEach((row) => {
    fields.forEach((field) => {
      const val = Number(row.querySelector(`[data-field="${field}"]`)?.value || 0);
      if (val > maxVals[field]) maxVals[field] = val;
    });
  });

  rows.forEach((row) => {
    fields.forEach((field) => {
      const input = row.querySelector(`[data-field="${field}"]`);
      if (!input) return;
      const cell = input.parentElement;
      let bar = cell.querySelector(".cell-heatmap");
      if (!bar) {
        bar = document.createElement("div");
        bar.className = "cell-heatmap";
        cell.appendChild(bar);
      }
      const val = Number(input.value || 0);
      const ratio = Math.min(1, Math.max(0, val / maxVals[field]));
      bar.style.width = `${ratio * 100}%`;
      bar.style.opacity = String(0.15 + ratio * 0.45);
    });
  });
}

// Render hourly forecast input table
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
  updateCellHeatmaps();
}

// Load scenario into form
function loadScenario(scenario, message = "Scenario loaded. Review parameters, then optimize.") {
  const data = scenario?.input || scenario;
  if (!data || typeof data !== "object" || !Array.isArray(data.hours) || data.hours.length !== 24 || !data.battery) {
    throw new Error("Invalid scenario structure: must include 24 hours and battery parameters.");
  }

  byId("scenarioId").value = data.scenario_id ?? "";
  byId("operatorNotes").value = Array.isArray(data.operator_notes) ? data.operator_notes.join("\n") : "";
  updateNotesCount();

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

function updateNotesCount() {
  const notes = byId("operatorNotes").value.split(/\r?\n/).map((n) => n.trim()).filter(Boolean);
  const counter = byId("notesCounter");
  if (counter) counter.textContent = `${notes.length} / 3 notes`;
}

function readNumber(input, label, min = 0) {
  const raw = input.value.trim();
  const value = Number(raw);
  if (!raw || !Number.isFinite(value) || value < min) {
    throw new Error(`${label} must be a valid number ≥ ${min}.`);
  }
  return value;
}

function collectRequest() {
  const scenarioId = byId("scenarioId").value.trim();
  if (!scenarioId) throw new Error("Please enter a Scenario Identifier.");

  const notes = byId("operatorNotes").value.split(/\r?\n/).map((note) => note.trim()).filter(Boolean);
  if (notes.length < 1 || notes.length > 3) throw new Error("Enter 1 to 3 operator notes (one instruction per line).");

  const battery = {
    capacity_kwh: readNumber(byId("capacity"), "Battery capacity"),
    initial_energy_kwh: readNumber(byId("initialEnergy"), "Initial battery energy"),
    minimum_energy_kwh: readNumber(byId("minimumEnergy"), "Minimum reserve energy"),
    max_charge_kwh_per_hour: readNumber(byId("maxCharge"), "Max charge rate"),
    max_discharge_kwh_per_hour: readNumber(byId("maxDischarge"), "Max discharge rate"),
  };
  if (battery.capacity_kwh <= 0) throw new Error("Battery capacity must be greater than 0.");
  if (battery.minimum_energy_kwh > battery.capacity_kwh || battery.initial_energy_kwh > battery.capacity_kwh || battery.initial_energy_kwh < battery.minimum_energy_kwh) {
    throw new Error("Initial & minimum battery energy must remain within 0 and total capacity.");
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
  if (hours.length !== 24) throw new Error("The forecast table must include all 24 hours.");

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

function exportCSV() {
  if (!currentResult || !Array.isArray(currentResult.hourly_plan)) return;
  const headers = ["Hour", "Grid_Import_kWh", "Solar_Used_kWh", "Battery_Action", "Battery_Action_Energy_kWh", "Battery_Energy_After_kWh"];
  const rows = currentResult.hourly_plan.map((entry) => [
    `${String(entry.hour).padStart(2, "0")}:00`,
    entry.grid_kwh,
    entry.solar_used_kwh,
    entry.battery_action,
    entry.battery_kwh,
    entry.battery_energy_after_kwh,
  ]);
  const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${safeFilename(currentResult.scenario_id)}-schedule.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  showToast("Schedule exported as CSV!", "success");
}

function safeFilename(id) {
  return String(id).replace(/[^a-z0-9_-]+/gi, "-").slice(0, 60) || "scenario";
}

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

// Multi-Layer SVG Chart with Grid, Solar, Demand, and Battery State of Charge Curve
function renderChart(plan, forecast, batteryCapacity) {
  const container = byId("energyChart");
  container.replaceChildren();
  const svg = svgElement("svg", { viewBox: "0 0 980 320", role: "presentation", "aria-hidden": "true" });
  
  const left = 50;
  const top = 25;
  const bottom = 260;
  const height = bottom - top;
  const step = 37;
  
  const maxPower = Math.max(1, ...forecast.map((item) => item.demand_kwh), ...plan.map((item) => item.grid_kwh + item.solar_used_kwh));
  const ceiling = Math.ceil(maxPower / 25) * 25 || 25;
  const yPower = (value) => bottom - (Number(value) / ceiling) * height;

  const maxCap = Math.max(1, batteryCapacity || 200);
  const yBattery = (value) => bottom - (Number(value) / maxCap) * height;

  // Grid background ticks
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = (ceiling * tick) / 4;
    const pos = yPower(value);
    svg.append(svgElement("line", { x1: left, x2: 955, y1: pos, y2: pos, stroke: "var(--line)", "stroke-width": 1, "stroke-dasharray": "3 3" }));
    
    const label = svgElement("text", { x: 42, y: pos + 4, "text-anchor": "end", fill: "var(--muted)", "font-size": 10, "font-family": "JetBrains Mono" });
    label.textContent = numberText(value, 0);
    svg.append(label);
  }

  // Draw Bars & Battery SOC Area
  const demandPoints = [];
  const batteryPoints = [];

  for (let hour = 0; hour < 24; hour += 1) {
    const x = left + hour * step + 8;
    const grid = Number(plan[hour].grid_kwh);
    const solar = Number(plan[hour].solar_used_kwh);
    const battEnergy = Number(plan[hour].battery_energy_after_kwh);

    // Bars
    for (const [value, offset, fill, title] of [
      [grid, 0, "var(--emerald)", "Grid"],
      [solar, 13, "var(--lime)", "Solar"],
    ]) {
      const bar = svgElement("rect", {
        x: x + offset,
        y: yPower(value),
        width: 11,
        height: Math.max(0, bottom - yPower(value)),
        rx: 3,
        fill,
      });
      const label = svgElement("title");
      label.textContent = `Hour ${hour}:00 - ${title}: ${numberText(value)} kWh`;
      bar.append(label);
      svg.append(bar);
    }

    demandPoints.push(`${x + 12},${yPower(forecast[hour].demand_kwh)}`);
    batteryPoints.push(`${x + 12},${yBattery(battEnergy)}`);

    if (hour % 3 === 0 || hour === 23) {
      const label = svgElement("text", { x: x + 12, y: 285, "text-anchor": "middle", fill: "var(--muted)", "font-size": 10, "font-family": "JetBrains Mono" });
      label.textContent = `${String(hour).padStart(2, "0")}:00`;
      svg.append(label);
    }
  }

  // Battery Storage SOC Line (Cyan)
  svg.append(svgElement("polyline", {
    points: batteryPoints.join(" "),
    fill: "none",
    stroke: "var(--cyan)",
    "stroke-width": 2.5,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "stroke-dasharray": "4 3",
  }));

  // Demand Polyline (Ink color)
  svg.append(svgElement("polyline", {
    points: demandPoints.join(" "),
    fill: "none",
    stroke: "var(--ink)",
    "stroke-width": 3,
    "stroke-linejoin": "round",
    "stroke-linecap": "round",
  }));

  container.append(svg);
}

// Battery Action Timeline Bar
function renderBatteryTimeline(plan) {
  const container = byId("batteryTimeline");
  if (!container) return;
  container.replaceChildren();

  plan.forEach((entry) => {
    const cell = document.createElement("div");
    cell.className = `timeline-cell ${entry.battery_action}`;
    cell.textContent = String(entry.hour).padStart(2, "0");
    cell.title = `Hour ${entry.hour}:00 - Battery ${entry.battery_action.toUpperCase()} (${numberText(entry.battery_kwh)} kWh)`;
    container.appendChild(cell);
  });
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
  
  const filtered = plan.filter((entry) => {
    if (tableFilter === "charge") return entry.battery_action === "charge";
    if (tableFilter === "discharge") return entry.battery_action === "discharge";
    return true;
  });

  for (const entry of filtered) {
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
    throw new Error("The optimization server returned incomplete response data.");
  }
  currentResult = data;
  currentRequest = request;
  
  byId("totalCost").textContent = `${numberText(data.total_cost_bdt)} BDT`;
  byId("totalGrid").textContent = `${numberText(data.total_grid_kwh)} kWh`;
  byId("peakGrid").textContent = `${numberText(data.peak_grid_kwh)} kWh`;
  byId("directiveCount").textContent = String(data.directive_interpretation.filter((entry) => entry.applies).length);
  byId("resultScenarioId").textContent = data.scenario_id;
  byId("planSummary").textContent = data.plan_summary;
  
  renderChart(data.hourly_plan, request.hours, request.battery.capacity_kwh);
  renderBatteryTimeline(data.hourly_plan);
  renderDirectives(data.directive_interpretation);
  renderPlanRows(data.hourly_plan);
  
  byId("emptyResults").hidden = true;
  byId("resultsContent").hidden = false;
  byId("downloadResultButton").disabled = false;
  byId("exportCsvButton").disabled = false;
  
  byId("results").scrollIntoView({ behavior: "smooth", block: "start" });
  showToast(`Optimization complete for ${data.scenario_id}!`, "success");
}

async function optimize() {
  let request;
  try {
    request = collectRequest();
  } catch (error) {
    setRunStatus(error.message, "error");
    showToast(error.message, "error");
    return;
  }
  
  markDirty("Running LLM interpretation and PuLP optimization solver...");
  const button = byId("runButton");
  button.disabled = true;
  button.classList.add("busy");
  button.querySelector(".button-label").textContent = "Optimizing Schedule...";
  
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
    if (!response.ok) throw new Error(data.detail || `Request failed with status ${response.status}.`);
    renderResult(data, request);
    setRunStatus(`Plan ready for ${data.scenario_id}. All 24 hours verified.`, "success");
  } catch (error) {
    const message = error.name === "AbortError" ? "Optimization request timed out. Please try again." : error.message;
    setRunStatus(message, "error");
    showToast(message, "error");
  } finally {
    clearTimeout(timer);
    button.disabled = false;
    button.classList.remove("busy");
    button.querySelector(".button-label").textContent = "Optimize Energy Plan";
  }
}

async function checkHealth() {
  const chip = byId("healthStatus");
  try {
    const response = await fetch("/health", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.status !== "ok") throw new Error("Unhealthy API");
    chip.className = "health-chip";
    chip.querySelector(".health-text").textContent = "API Online";
  } catch {
    chip.className = "health-chip offline";
    chip.querySelector(".health-text").textContent = "API Offline";
  }
}

// Event Listeners Initialization
document.addEventListener("DOMContentLoaded", () => {
  // Theme toggle
  const themeToggle = byId("themeToggle");
  const savedTheme = localStorage.getItem("gridwise_theme") || "light";
  document.documentElement.setAttribute("data-theme", savedTheme);
  
  themeToggle?.addEventListener("click", () => {
    const currentTheme = document.documentElement.getAttribute("data-theme");
    const nextTheme = currentTheme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", nextTheme);
    localStorage.setItem("gridwise_theme", nextTheme);
  });

  // Quick Presets
  document.querySelectorAll(".preset-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      document.querySelectorAll(".preset-btn").forEach((b) => b.classList.remove("active"));
      e.target.classList.add("active");
      const presetKey = e.target.dataset.preset;
      if (presets[presetKey]) {
        loadScenario(presets[presetKey], `Preset "${e.target.textContent}" loaded.`);
        showToast(`Loaded preset: ${e.target.textContent}`, "info");
      }
    });
  });

  // Note template chips
  document.querySelectorAll(".template-chip").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      const template = e.target.dataset.template;
      const notesArea = byId("operatorNotes");
      const existing = notesArea.value.trim();
      const lines = existing ? existing.split(/\r?\n/) : [];
      if (lines.length >= 3) {
        showToast("Maximum 3 operator notes allowed. Clear or edit existing lines.", "error");
        return;
      }
      lines.push(template);
      notesArea.value = lines.join("\n");
      updateNotesCount();
      markDirty();
      showToast("Template note added!", "success");
    });
  });

  byId("operatorNotes")?.addEventListener("input", updateNotesCount);

  // Forecast bulk tools
  byId("toolFlatTariff")?.addEventListener("click", () => {
    const val = prompt("Enter flat tariff in BDT/kWh across all 24 hours:", "12");
    if (val !== null && !isNaN(Number(val))) {
      byId("forecastRows").querySelectorAll('[data-field="tariff_bdt_per_kwh"]').forEach((inp) => (inp.value = val));
      updateCellHeatmaps();
      markDirty();
      showToast(`Set flat tariff of ${val} BDT/kWh`, "info");
    }
  });

  byId("toolScaleDemand")?.addEventListener("click", () => {
    byId("forecastRows").querySelectorAll('[data-field="demand_kwh"]').forEach((inp) => {
      inp.value = Math.round(Number(inp.value || 0) * 1.1);
    });
    updateCellHeatmaps();
    markDirty();
    showToast("Demand scaled by +10%", "info");
  });

  // Drag and Drop Zone
  const dropZone = byId("dropZone");
  const sampleFile = byId("sampleFile");

  dropZone?.addEventListener("click", () => sampleFile?.click());
  dropZone?.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone?.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone?.addEventListener("drop", async (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = e.dataTransfer.files?.[0];
    if (file) handleJsonFile(file);
  });
  sampleFile?.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) handleJsonFile(file);
  });

  async function handleJsonFile(file) {
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
        showToast(`Loaded JSON file with ${cases.length} scenario cases!`, "success");
      } else {
        sampleCases = [];
        byId("caseSelect").replaceChildren(new Option("Single scenario loaded", ""));
        byId("caseSelect").disabled = true;
        loadScenario(payload, "JSON scenario loaded.");
        showToast("Loaded single JSON scenario!", "success");
      }
    } catch (error) {
      setRunStatus(`Could not load JSON: ${error.message}`, "error");
      showToast(`Invalid JSON file: ${error.message}`, "error");
    }
  }

  byId("caseSelect")?.addEventListener("change", (event) => {
    const selected = sampleCases[Number(event.target.value)];
    if (!selected) return;
    try {
      loadScenario(selected, `${selected.id || "Case"} loaded.`);
      showToast(`Loaded scenario ${selected.id || ""}`, "info");
    } catch (error) {
      setRunStatus(error.message, "error");
    }
  });

  // Table filters
  document.querySelectorAll(".filter-chip").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      document.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
      e.target.classList.add("active");
      tableFilter = e.target.dataset.filter;
      if (currentResult) renderPlanRows(currentResult.hourly_plan);
    });
  });

  // Actions
  byId("resetButton")?.addEventListener("click", () => {
    document.querySelectorAll(".preset-btn").forEach((b) => b.classList.remove("active"));
    document.querySelector('[data-preset="starter"]')?.classList.add("active");
    loadScenario(presets.starter, "Starter baseline scenario restored.");
    showToast("Starter scenario restored.", "info");
  });

  byId("runButton")?.addEventListener("click", optimize);
  byId("exportCsvButton")?.addEventListener("click", exportCSV);

  byId("downloadRequestButton")?.addEventListener("click", () => {
    try {
      const request = collectRequest();
      downloadJSON(request, `${safeFilename(request.scenario_id)}-request.json`);
      showToast("Request JSON downloaded!", "success");
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  byId("downloadResultButton")?.addEventListener("click", () => {
    if (currentResult) {
      downloadJSON(currentResult, `${safeFilename(currentResult.scenario_id)}-result.json`);
      showToast("Result JSON downloaded!", "success");
    }
  });

  // Inputs dirty check
  document.querySelectorAll(".setup-panel input, .setup-panel textarea").forEach((input) => {
    input.addEventListener("input", () => markDirty());
  });
  byId("forecastRows")?.addEventListener("input", () => {
    updateCellHeatmaps();
    markDirty();
  });

  // Initial load
  loadScenario(presets.starter, "Starter baseline loaded. Click Optimize Energy Plan.");
  checkHealth();
});
