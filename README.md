# GridWise LLM

GridWise LLM exposes a 24-hour campus energy scheduler as a public HTTP API. It reads 1–3 operator notes with Google's Gemini model, checks the resulting directives, minimizes grid cost with PuLP/CBC, then independently replays every hour before returning a plan. The service requires a Gemini API key for optimization.

## Architecture and stack

`FastAPI/Pydantic request validation → Gemini note interpretation → deterministic directive guardrails → directive application → PuLP/CBC mixed integer optimization → independent schedule replay → totals and JSON response`.

Python 3.11/3.12, FastAPI, Pydantic v2, Uvicorn, httpx, Gemini's `generateContent` API, PuLP/CBC, and pytest are the main dependencies. Gemini receives the notes and battery capacity in one JSON-mode request; it never chooses the hourly schedule. The optimizer's variables represent grid import, solar use, charge, discharge, battery state, and mutually exclusive battery actions.

## Quick start

Use Python 3.11 or 3.12 and run these commands from the repository root. Local verification used Python 3.11; the Docker image uses 3.12.

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set LLM_API_KEY to your own key.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
# Edit .env and set LLM_API_KEY to your own key.
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Make sure `python` or `python3` resolves to Python 3.11 or 3.12. Leave the terminal running while sending requests. Open `http://127.0.0.1:8000/` for the browser dashboard, or `/docs` for the interactive API schema.

The dashboard lets you edit battery and hourly forecasts, write 1–3 operator notes, import the official public sample JSON, select a case, run optimization, inspect the chart and 24-hour plan, and download the request or result JSON. The Gemini key stays on the server; the browser sends only the scenario to `/optimize-energy`.

## Send a sample request

The repository includes the official public sample pack. An API request is **only** a case's `input` object. Do not send its `id`, `label`, `expected_output`, or `rationale` fields. This helper extracts the right object:

```powershell
.\.venv\Scripts\python.exe scripts/export_sample_input.py SAMPLE-01 --output sample-input.json
Invoke-RestMethod http://127.0.0.1:8000/health
$response = Invoke-RestMethod -Uri http://127.0.0.1:8000/optimize-energy -Method Post -ContentType application/json -InFile sample-input.json
$response | ConvertTo-Json -Depth 10
```

For macOS/Linux, use `.venv/bin/python scripts/export_sample_input.py SAMPLE-01 --output sample-input.json`, then:

```bash
curl -i http://127.0.0.1:8000/health
curl -sS -X POST http://127.0.0.1:8000/optimize-energy \
  -H 'Content-Type: application/json' --data-binary @sample-input.json
```

`GET /health` returns HTTP 200 with `{"status":"ok"}`. A successful `POST /optimize-energy` returns HTTP 200 with `scenario_id`, `directive_interpretation`, 24 `hourly_plan` entries, `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, and `plan_summary`. For `SAMPLE-01`, the reference optimal cost is **38,365 BDT**; a different hourly schedule can be equally optimal. Interactive request and response schemas are at `/docs`.

Requests need a nonempty `scenario_id`, 1–3 nonempty `operator_notes`, exactly one forecast for each hour 0–23, and a valid `battery` object. Each forecast needs `hour`, nonnegative `demand_kwh`, `solar_kwh`, and `tariff_bdt_per_kwh`. Battery data needs positive `capacity_kwh`; `initial_energy_kwh` and `minimum_energy_kwh` within capacity; and nonnegative hourly charge and discharge limits. JSON field names and structures must match the API schema exactly.

## Interpretation, optimization, and validation

1. Pydantic validates the request before any LLM call. Gemini converts each note to exactly one directive in its original `note_index` order. Allowed types are `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, and `no_op`. Irrelevant or ambiguous notes become `no_op`.
2. Deterministic guardrails require the matching adjustment shape, finite numeric bounds, and unique ascending hour indices from 0 to 23. They reject unsafe or malformed output before the solver runs. A solar factor is the usable fraction of forecast solar. Time windows include their start hour and exclude their end hour. Overlapping bounds apply the stricter limit.
3. PuLP/CBC solves a mixed integer linear program. Grid plus usable solar plus battery discharge equals demand plus battery charge each hour. It enforces battery capacity and rates, excludes simultaneous charge and discharge, applies note constraints, and restores the initial battery level after hour 23. Its objective is total grid cost in BDT.
4. A separate replay validator checks the returned schedule hour by hour, including all directives and end-of-day neutrality, with absolute numerical tolerance 0.01. Totals are calculated again from the accepted schedule.

Malformed JSON or structurally invalid requests return HTTP 400. Semantically invalid input or rejected directives return HTTP 422. An infeasible optimization returns HTTP 400. Upstream, unexpected, or deadline failures return a controlled HTTP 500 response. Error bodies have a `detail` field and omit stack traces and credentials. Optimization requests have a 29-second server deadline to stay within the 30-second challenge limit; external Gemini latency can still affect response time.

## Test all 10 public cases

With the Gemini key configured in `.env`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/run_public_samples.py
```

On macOS/Linux, replace the Python path with `.venv/bin/python`. The runner uses the repository's `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` by default, or accepts another path as its first argument. It requires all 10 cases, compares directive meanings and reference cost within 0.01 BDT, independently replays schedules, recomputes totals, and exits nonzero on failures.

To test only deterministic guardrails, solver, and replay without an LLM key, run `python scripts/run_public_samples.py --use-reference-directives`. This mode uses published expected directives and **does not verify note interpretation**. The public pack is a development check; private evaluation cases may differ.

Optional live checks for unseen paraphrases need the configured Gemini key. In PowerShell, run `$env:RUN_LIVE_LLM_TESTS = '1'` and then `.\.venv\Scripts\python.exe -m pytest tests/test_llm_paraphrases.py -q`. On macOS/Linux, run `RUN_LIVE_LLM_TESTS=1 .venv/bin/python -m pytest tests/test_llm_paraphrases.py -q`. These tests make external API calls and are skipped by default.

## Configuration

Copy `.env.example` to `.env` locally or set the same variables in your hosting platform. `.env` is excluded from Git and the Docker build context.

| Variable | Purpose | Default |
| --- | --- | --- |
| `LLM_PROVIDER` | LLM provider; currently `google` | `google` |
| `LLM_MODEL` | Gemini model ID | `gemini-3.1-flash-lite` |
| `LLM_API_KEY` | Gemini API key; required for optimization | empty |
| `LLM_TIMEOUT_SECONDS` | Timeout for one Gemini call | `30.0` |
| `REQUEST_TIMEOUT_SECONDS` | End-to-end optimization deadline; at most 29 seconds | `29.0` |
| `HOST`, `PORT` | Local bind address and port | `0.0.0.0`, `8000` |

The model is used to interpret natural-language notes, not to produce battery schedules. The model/API must be available from the runtime environment, and its quota and latency affect requests. No key is embedded in the image or source; keep `.env` and API keys out of commits, screenshots, and logs.

## Docker and public hosting

The Dockerfile installs CBC, runs as an unprivileged user, binds port 8000, and has a `/health` health check. On a machine with Docker installed:

```bash
docker build -t gridwise-llm .
docker run -d --rm --name gridwise-app -p 8000:8000 --env-file .env gridwise-llm
curl -i http://127.0.0.1:8000/health
python scripts/export_sample_input.py SAMPLE-01 --output sample-input.json
curl -sS -X POST http://127.0.0.1:8000/optimize-energy \
  -H 'Content-Type: application/json' --data-binary @sample-input.json
docker stop gridwise-app
```

For a public submission, deploy this service to a host with a publicly reachable HTTPS URL, verify `/health` and `POST /optimize-energy` from outside your development network, and keep it online through judging. If submitting a Docker fallback, tag and push the verified image to a registry your judges can pull, then provide its **actual image tag or digest** and the matching `docker pull` / `docker run` commands. Inject `LLM_API_KEY` at runtime. Repository visibility, final URL or image reference, and the requested three-minute demonstration video must be finalized through the competition submission process.

## Limitations and credits

The service depends on Gemini availability, quota, and latency. A local `127.0.0.1` URL cannot be reached by judges; a public deployment is a separate submission step. Docker must be installed to run the container commands above. The implementation uses FastAPI, Pydantic, httpx, PuLP/CBC, Uvicorn, pytest, and Google's Gemini API; the competition documents and sample pack define the expected behavior.
