# GridWise LLM

An API for scheduling 24 hours of campus electricity demand, solar generation, and battery use at minimum grid cost. The service interprets operator notes with Google's Gemini API, validates the resulting directives, solves a mixed integer linear program with PuLP/CBC, and independently replays the schedule before returning it.

## Processing flow

1. Pydantic validates the 24 hourly forecasts, battery limits, and operator notes.
2. Gemini interprets each note into one structured directive.
3. Guardrails validate directive types, hours, and numerical bounds.
4. The optimization model applies those bounds to the hourly forecast; CBC minimizes grid cost.
5. A separate replay validator checks energy balance, battery limits, directives, and end-of-day battery neutrality. Totals are recalculated from the accepted plan.

## Setup

Python 3.12 is used in the container. Install the dependencies and set a Gemini API key:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `LLM_API_KEY`. The API cannot optimize requests without a configured key. On Windows, activate the virtual environment with `.venv\Scripts\Activate.ps1`; on macOS/Linux, use `source .venv/bin/activate`.

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`GET /health` returns `{"status":"ok"}`. `POST /optimize-energy` accepts a scenario with one to three operator notes, a forecast for every hour from 0 through 23, and battery limits. The response includes the interpreted directives, 24 hourly schedule entries, total grid energy, cost, and peak grid import. The interactive API schema is at `/docs`.

Invalid request bodies and rejected directives return HTTP 422. An infeasible optimization returns HTTP 400. Unexpected service failures return HTTP 500.

## Validation and samples

```bash
python -m pytest -q
python scripts/run_public_samples.py
```

The sample runner expects `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` at the project root by default. Pass another path as its first argument. The file must contain a JSON array of cases or an object with a `cases` array. Each case can be a request object directly or have an `input` or `request` object. Reference directives belong in `expected_output.directive_interpretation`; a reference cost can be provided as `expected_total_cost_bdt` on the case or as `total_cost_bdt` in `expected_output` or `expected`.

The runner requires exactly ten cases, checks directive semantics and schedule feasibility, recomputes totals from the hourly plan, and compares each reference cost within 0.01 BDT as stated in the supplied public sample pack. Missing references are labeled `FEASIBLE` and cause a nonzero exit because equivalence is unverified. Missing or malformed sample files and failed cases also cause a nonzero exit.

Without an LLM key, run `python scripts/run_public_samples.py --use-reference-directives` to check guardrails, solver, replay, and costs against the published directives. This mode does not test note interpretation.

## Docker

```bash
docker build -t gridwise-llm .
docker run --env-file .env -p 8000:8000 gridwise-llm
```

The container includes the CBC solver. Its API listens on port 8000. Provide the Gemini key through `.env` or another environment variable source; `.env` is excluded from the image.
