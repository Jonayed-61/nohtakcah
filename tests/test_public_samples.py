import json

import pytest

from app.schemas.directives import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import HourlyPlanEntry, OptimizeEnergyResponse
from scripts import run_public_samples


def make_case(reference_cost=240):
    request = {
        "scenario_id": "sample-1",
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
    return {"input": request, "expected_output": {
        "total_cost_bdt": reference_cost,
        "directive_interpretation": [{
            "note_index": 0, "applies": False, "directive_type": "no_op",
            "structured_adjustment": None, "explanation": "No change",
        }],
    }}


def make_response(request):
    return OptimizeEnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=[DirectiveInterpretation(
            note_index=0, applies=False, directive_type="no_op",
            structured_adjustment=None, explanation="No change",
        )],
        hourly_plan=[HourlyPlanEntry(
            hour=h, grid_kwh=2, solar_used_kwh=0, battery_action="idle",
            battery_kwh=0, battery_energy_after_kwh=5,
        ) for h in range(24)],
        total_grid_kwh=48,
        total_cost_bdt=240,
        peak_grid_kwh=2,
        plan_summary="No changes",
    )


def test_runner_replays_plan_and_checks_reference_cost():
    request = OptimizeEnergyRequest.model_validate(make_case()["input"])
    response = make_response(request)
    reference = make_case()["expected_output"]["directive_interpretation"]
    assert run_public_samples.verify_result(request, response, 240, reference) == "PASS"
    assert run_public_samples.verify_result(request, response, None) == "FEASIBLE (no reference cost)"
    with pytest.raises(AssertionError, match="Cost mismatch"):
        run_public_samples.verify_result(request, response, 200, reference)
    wrong_reference = [dict(reference[0], directive_type="no_charge_window")]
    with pytest.raises(AssertionError, match="interpretation mismatch"):
        run_public_samples.verify_result(request, response, 240, wrong_reference)
    response.hourly_plan[0].grid_kwh = 3
    with pytest.raises(Exception, match="Energy balance"):
        run_public_samples.verify_result(request, response, 240, reference)


@pytest.mark.asyncio
async def test_runner_reports_failed_case_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    class FakeService:
        async def run_pipeline(self, request):
            return make_response(request)

    monkeypatch.setattr(run_public_samples, "OptimizationService", FakeService)
    path = tmp_path / "samples.json"
    path.write_text(json.dumps([make_case(240), make_case(200)]), encoding="utf-8")
    assert await run_public_samples.run_samples(path, expected_count=2) == 1
    output = capsys.readouterr().out
    assert "1 reference matches" in output
    assert "1 failed" in output
    assert await run_public_samples.run_samples(tmp_path / "missing.json", expected_count=2) == 2


@pytest.mark.asyncio
async def test_runner_requires_complete_cost_references(tmp_path, monkeypatch):
    class FakeService:
        async def run_pipeline(self, request):
            return make_response(request)

    monkeypatch.setattr(run_public_samples, "OptimizationService", FakeService)
    path = tmp_path / "samples.json"
    path.write_text(json.dumps([make_case(240)]), encoding="utf-8")
    assert await run_public_samples.run_samples(path) == 2

    path.write_text(json.dumps([{"input": make_case()["input"]}]), encoding="utf-8")
    assert await run_public_samples.run_samples(path, expected_count=1) == 1
