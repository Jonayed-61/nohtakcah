import { readFileSync, writeFileSync } from "node:fs";

const targets = await (await fetch("http://127.0.0.1:9223/json")).json();
const target = targets.find((item) => item.url === "http://127.0.0.1:8001/");
if (!target) throw new Error("GridWise browser tab not found");

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextId = 1;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});

function send(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const response = await send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}

const sleep = (duration) => new Promise((resolve) => setTimeout(resolve, duration));
await send("Page.enable");
await send("Runtime.enable");
await send("Page.reload", { ignoreCache: true });
await sleep(600);

const rows = await evaluate("document.querySelectorAll('#forecastRows tr').length");
const health = await evaluate("document.getElementById('healthStatus').textContent");
if (rows !== 24) throw new Error(`Expected 24 forecast rows, got ${rows}`);
console.log(`Initial UI: ${rows} rows, ${health}`);

await send("Emulation.setDeviceMetricsOverride", {
  width: 390,
  height: 844,
  deviceScaleFactor: 1,
  mobile: true,
});
await sleep(400);
const mobile = await evaluate("({width: innerWidth, scrollWidth: document.documentElement.scrollWidth})");
console.log("Mobile layout:", mobile);
console.log("Mobile overflow:", await evaluate("({visualWidth: visualViewport.width, clientWidth: document.documentElement.clientWidth, offenders: [...document.querySelectorAll('body *')].filter(e => { const r=e.getBoundingClientRect(); return r.right > 390 && getComputedStyle(e).position !== 'absolute' && !e.closest('.table-scroll'); }).slice(0, 12).map(e => ({tag:e.tagName, className:e.className?.baseVal || e.className, width:Math.round(e.getBoundingClientRect().width), right:Math.round(e.getBoundingClientRect().right)}))})"));
const mobileImage = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
writeFileSync("C:/Users/USER/AppData/Local/Temp/gridwise-mobile-cdp.png", Buffer.from(mobileImage.data, "base64"));

await send("Emulation.setDeviceMetricsOverride", {
  width: 1440,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
});
await evaluate("document.getElementById('runButton').click()");
let result;
for (let attempt = 0; attempt < 38; attempt += 1) {
  await sleep(1000);
  result = await evaluate("({status: document.getElementById('runStatus').textContent, ready: !document.getElementById('resultsContent').hidden, cost: document.getElementById('totalCost').textContent})");
  if (result.ready || result.status.includes("Unable") || result.status.includes("failed") || result.status.includes("too long")) break;
}
console.log("Optimize interaction:", result);
if (!result.ready) throw new Error("The UI did not show an optimization result");
const resultImage = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
writeFileSync("C:/Users/USER/AppData/Local/Temp/gridwise-results-cdp.png", Buffer.from(resultImage.data, "base64"));

const publicSamples = readFileSync("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", "utf8");
await evaluate(`(() => { const file = new File([${JSON.stringify(publicSamples)}], 'public-samples.json', {type:'application/json'}); const transfer = new DataTransfer(); transfer.items.add(file); const input = document.getElementById('sampleFile'); input.files = transfer.files; input.dispatchEvent(new Event('change', {bubbles:true})); return true; })()`);
await sleep(500);
const imported = await evaluate("({caseCount: document.getElementById('caseSelect').options.length, scenario: document.getElementById('scenarioId').value, notes: document.getElementById('operatorNotes').value.split('\\n').length})");
console.log("Imported public samples:", imported);
if (imported.caseCount !== 10 || imported.scenario !== "SAMPLE-01" || imported.notes !== 2) {
  throw new Error("Public sample import did not populate the form correctly");
}
socket.close();
