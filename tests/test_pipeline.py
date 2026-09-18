import asyncio
import copy
import json

import httpx
import pytest

from app.api import routes
from app.config import settings
from app.guardrails.directive_validator import (
    DirectiveValidationError,
    validate_directives,
)
from app.llm.interpreter import LLMInterpreter
from app.main import app
from app.optimizer.model import build_optimization_context
from app.schemas.directives import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest
from app.validators.schedule_validator import ScheduleValidationError, validate_schedule


def request_data():
    return {
        "scenario_id": "pipeline-check",
        "operator_notes": ["No changes"],
        "hours": [
            {"hour": h, "demand_kwh": 2, "solar_kwh": 0, "tariff_bdt_per_kwh": 5}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 10,
            "initial_energy_kwh": 5,
            "minimum_energy_kwh": 2,
            "max_charge_kwh_per_hour": 3,
            "max_discharge_kwh_per_hour": 3,
        },
    }


def interpretation(kind="no_op", adjustment=None, applies=False):
    return DirectiveInterpretation.model_validate(
        {
            "note_index": 0,
            "applies": applies,
            "directive_type": kind,
            "structured_adjustment": adjustment,
            "explanation": "Test interpretation",
        }
    )


def idle_plan():
    return [
        {
            "hour": h,
            "grid_kwh": 2,
            "solar_used_kwh": 0,
            "battery_action": "idle",
            "battery_kwh": 0,
            "battery_energy_after_kwh": 5,
        }
        for h in range(24)
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p[0].update(grid_kwh=-1), "Negative energy"),
        (lambda p: p[0].update(solar_used_kwh=1), "Solar used"),
        (lambda p: p[0].update(battery_action="unknown"), "Unknown battery action"),
        (lambda p: p[0].update(grid_kwh=3), "Energy balance"),
        (lambda p: p[0].update(battery_energy_after_kwh=6), "state transition"),
        (lambda p: p[23].update(battery_action="charge", battery_kwh=1, grid_kwh=3, battery_energy_after_kwh=6), "neutrality"),
        (lambda p: p[0].update(grid_kwh=float("nan")), "finite number"),
    ],
)
def test_schedule_replay_rejects_invalid_physics(change, message):
    request = OptimizeEnergyRequest.model_validate(request_data())
    plan = copy.deepcopy(idle_plan())
    change(plan)
    with pytest.raises(ScheduleValidationError, match=message):
        validate_schedule(request, [], plan)


def test_schedule_replay_enforces_directives_independently():
    request = OptimizeEnergyRequest.model_validate(request_data())
    plan = idle_plan()
    directive = interpretation(
        "max_grid_window", {"hours": [0], "max_grid_kwh": 1}, applies=True
    )
    with pytest.raises(ScheduleValidationError, match="Grid import exceeded"):
        validate_schedule(request, [directive], plan)


def test_directives_are_returned_in_note_order_and_bad_hours_are_rejected():
    data = request_data()
    data["operator_notes"] = ["First note", "Second note"]
    request = OptimizeEnergyRequest.model_validate(data)
    second = interpretation().model_copy(update={"note_index": 1})
    result = validate_directives([second, interpretation()], request)
    assert [item.note_index for item in result] == [0, 1]

    duplicate_hours = interpretation(
        "no_charge_window", {"hours": [2, 2]}, applies=True
    )
    with pytest.raises(DirectiveValidationError, match="Hours must be unique"):
        validate_directives([duplicate_hours, second], request)

    unsorted_hours = interpretation(
        "no_charge_window", {"hours": [3, 2]}, applies=True
    )
    with pytest.raises(DirectiveValidationError, match="ascending"):
        validate_directives([unsorted_hours, second], request)


@pytest.mark.parametrize("directive", [
    interpretation().model_copy(update={"applies": True}),
    interpretation("no_charge_window", {"hours": [2]}, applies=False),
])
def test_guardrail_rejects_invalid_applies_semantics(directive):
    request = OptimizeEnergyRequest.model_validate(request_data())
    with pytest.raises(DirectiveValidationError):
        validate_directives([directive], request)


def test_overlapping_solar_reductions_use_strictest_limit_in_solver_and_replay():
    data = request_data()
    data["operator_notes"] = ["First reduction", "Second reduction"]
    data["hours"][0]["demand_kwh"] = 5
    data["hours"][0]["solar_kwh"] = 10
    request = OptimizeEnergyRequest.model_validate(data)
    directives = [
        interpretation("solar_reduction", {"hours": [0], "factor": 0.5}, True),
        interpretation("solar_reduction", {"hours": [0], "factor": 0.25}, True).model_copy(
            update={"note_index": 1}
        ),
    ]
    validated = validate_directives(directives, request)
    assert build_optimization_context(request, validated).effective_solar[0] == 2.5

    plan = idle_plan()
    plan[0].update(grid_kwh=2, solar_used_kwh=3)
    with pytest.raises(ScheduleValidationError, match="Solar used exceeds"):
        validate_schedule(request, validated, plan)


@pytest.mark.parametrize("adjustment", [
    {"hours": [0], "factor": 0.5, "extra": 1},
    {"hours": [0], "factor": float("nan")},
    {"hours": [0], "factor": 1.1},
])
def test_interpreter_rejects_invalid_adjustment_shape_and_factors(adjustment):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        interpretation("solar_reduction", adjustment, True)


@pytest.mark.parametrize(
    ("kind", "adjustment", "change", "message"),
    [
        ("minimum_battery_reserve", {"hours": [0], "minimum_energy_kwh": 6}, lambda p: None, "required reserve"),
        ("no_charge_window", {"hours": [0]}, lambda p: p[0].update(battery_action="charge", battery_kwh=1, grid_kwh=3, battery_energy_after_kwh=6), "no_charge_window"),
        ("no_discharge_window", {"hours": [0]}, lambda p: p[0].update(battery_action="discharge", battery_kwh=1, grid_kwh=1, battery_energy_after_kwh=4), "no_discharge_window"),
    ],
)
def test_schedule_replay_enforces_battery_directives(kind, adjustment, change, message):
    request = OptimizeEnergyRequest.model_validate(request_data())
    plan = idle_plan()
    change(plan)
    with pytest.raises(ScheduleValidationError, match=message):
        validate_schedule(request, [interpretation(kind, adjustment, True)], plan)


@pytest.mark.asyncio
async def test_interpreter_parses_gemini_json_response(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    original_client = httpx.AsyncClient
    calls = 0

    def respond(request):
        nonlocal calls
        calls += 1
        assert request.headers["x-goog-api-key"] == "test-key"
        assert request.url.path.endswith(f"/{settings.LLM_MODEL}:generateContent")
        assert b"exclude the ending hour" in request.read()
        payload = json.loads(request.read())
        assert payload["generationConfig"]["temperature"] == 0
        assert "percentage battery reserve" in payload["contents"][0]["parts"][0]["text"]
        if calls == 1:
            return httpx.Response(503, json={"error": {"message": "Temporary overload"}})
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps([interpretation().model_dump()])}]}}]},
        )

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport))
    result = await LLMInterpreter().interpret(["No changes"], 10)
    assert calls == 2
    assert len(result) == 1
    assert result[0].directive_type == "no_op"


class FakeInterpreter:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error

    async def interpret(self, operator_notes, capacity_kwh):
        assert operator_notes == ["No changes"]
        assert capacity_kwh == 10
        if self.error:
            raise self.error
        return self.output


@pytest.mark.asyncio
async def test_endpoint_runs_full_pipeline(monkeypatch):
    monkeypatch.setattr(routes.optimization_service, "interpreter", FakeInterpreter([interpretation()]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/optimize-energy", json=request_data())

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == "pipeline-check"
    assert len(body["hourly_plan"]) == 24
    assert body["total_grid_kwh"] == 48
    assert body["total_cost_bdt"] == 240
    assert body["peak_grid_kwh"] == max(entry["grid_kwh"] for entry in body["hourly_plan"])
    assert "0 operator directive(s)" in body["plan_summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fake", "status_code"),
    [
        (FakeInterpreter([interpretation("minimum_battery_reserve", {"hours": [0], "minimum_energy_kwh": 11}, True)]), 422),
        (FakeInterpreter([interpretation("max_grid_window", {"hours": list(range(24)), "max_grid_kwh": 0}, True)]), 400),
        (FakeInterpreter(error=RuntimeError("private upstream detail")), 500),
    ],
)
async def test_endpoint_maps_pipeline_failures(monkeypatch, fake, status_code):
    monkeypatch.setattr(routes.optimization_service, "interpreter", fake)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/optimize-energy", json=request_data())

    assert response.status_code == status_code
    assert set(response.json()) == {"detail"}
    assert "Traceback" not in response.text
    assert "private upstream detail" not in response.text


@pytest.mark.asyncio
async def test_endpoint_times_out_with_controlled_response(monkeypatch):
    from app.config import settings

    async def slow_pipeline(request):
        await asyncio.sleep(0.1)

    monkeypatch.setattr(routes.optimization_service, "run_pipeline", slow_pipeline)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 0.01)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/optimize-energy", json=request_data())
    assert response.status_code == 500
    assert response.json() == {"detail": "Optimization request timed out."}
