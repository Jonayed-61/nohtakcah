import pytest
import pulp

from app.optimizer.model import build_optimization_context
from app.optimizer.solver import OptimizationError, solve_energy_optimization
from app.schemas.directives import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest


def make_request(*, demand=2.0, solar=0.0, tariff=5.0):
    return OptimizeEnergyRequest.model_validate(
        {
            "scenario_id": "part-3-check",
            "operator_notes": ["Optimize the schedule"],
            "hours": [
                {
                    "hour": h,
                    "demand_kwh": demand,
                    "solar_kwh": solar,
                    "tariff_bdt_per_kwh": tariff,
                }
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
    )


def directive(kind, adjustment, *, applies=True):
    return DirectiveInterpretation.model_validate(
        {
            "note_index": 0,
            "applies": applies,
            "directive_type": kind,
            "structured_adjustment": adjustment,
            "explanation": "Test directive",
        }
    )


def test_context_applies_hourly_bounds_and_tightest_caps():
    request = make_request(solar=4)
    directives = [
        directive("solar_reduction", {"hours": [3], "factor": 0.25}),
        directive("minimum_battery_reserve", {"hours": [3, 4], "minimum_energy_kwh": 4}),
        directive("minimum_battery_reserve", {"hours": [4], "minimum_energy_kwh": 1}),
        directive("no_charge_window", {"hours": [3]}),
        directive("no_discharge_window", {"hours": [4]}),
        directive("max_grid_window", {"hours": [3], "max_grid_kwh": 2}),
        directive("max_grid_window", {"hours": [3], "max_grid_kwh": 1}),
        directive("solar_reduction", {"hours": [5], "factor": 0}, applies=False),
    ]

    context = build_optimization_context(request, directives)

    assert context.effective_solar[3] == 1
    assert context.effective_solar[5] == 4
    assert context.required_minimum[3:5] == [4, 4]
    assert context.charge_allowed[3] is False
    assert context.discharge_allowed[4] is False
    assert context.grid_cap[3] == 1
    assert context.grid_cap[4] is None


def test_solver_respects_physics_and_end_of_day_neutrality(monkeypatch):
    request = make_request()
    request.hours[0].tariff_bdt_per_kwh = 1
    request.hours[1].tariff_bdt_per_kwh = 10
    directives = [
        directive("no_charge_window", {"hours": [1]}),
        directive("no_discharge_window", {"hours": [0]}),
        directive("max_grid_window", {"hours": [1], "max_grid_kwh": 0}),
    ]
    context = build_optimization_context(request, directives)
    original_solve = pulp.LpProblem.solve

    def check_raw_solution(problem, *args, **kwargs):
        status = original_solve(problem, *args, **kwargs)
        if status == pulp.LpStatusOptimal:
            variables = {variable.name: variable for variable in problem.variables()}
            for h in range(24):
                charge = pulp.value(variables[f"charge_{h}"])
                discharge = pulp.value(variables[f"discharge_{h}"])
                assert not (charge > 1e-6 and discharge > 1e-6)
        return status

    monkeypatch.setattr(pulp.LpProblem, "solve", check_raw_solution)
    schedule = solve_energy_optimization(context)

    assert len(schedule) == 24
    assert schedule[0]["battery_action"] == "charge"
    assert schedule[1]["battery_action"] == "discharge"
    assert schedule[1]["grid_kwh"] == pytest.approx(0, abs=1e-6)
    assert schedule[-1]["battery_energy_after_kwh"] == pytest.approx(5, abs=1e-6)

    previous_energy = context.initial_energy_kwh
    for h, entry in enumerate(schedule):
        charge = entry["battery_kwh"] if entry["battery_action"] == "charge" else 0
        discharge = entry["battery_kwh"] if entry["battery_action"] == "discharge" else 0
        assert entry["grid_kwh"] >= -1e-6
        assert entry["solar_used_kwh"] <= context.effective_solar[h] + 1e-6
        assert entry["grid_kwh"] + entry["solar_used_kwh"] + discharge == pytest.approx(
            context.demand[h] + charge, abs=1e-6
        )
        assert entry["battery_energy_after_kwh"] == pytest.approx(
            previous_energy + charge - discharge, abs=1e-6
        )
        assert context.required_minimum[h] - 1e-6 <= entry["battery_energy_after_kwh"] <= context.capacity_kwh + 1e-6
        assert charge <= context.max_charge_rate + 1e-6
        assert discharge <= context.max_discharge_rate + 1e-6
        previous_energy = entry["battery_energy_after_kwh"]


def test_surplus_solar_is_curtailed_without_negative_grid():
    context = build_optimization_context(make_request(demand=1, solar=10), [])
    schedule = solve_energy_optimization(context)

    assert all(entry["grid_kwh"] == pytest.approx(0, abs=1e-6) for entry in schedule)
    assert sum(entry["solar_used_kwh"] for entry in schedule) == pytest.approx(24, abs=1e-6)
    assert schedule[-1]["battery_energy_after_kwh"] == pytest.approx(5, abs=1e-6)


def test_infeasible_grid_cap_raises_optimization_error():
    request = make_request(demand=2)
    directives = [
        directive("max_grid_window", {"hours": list(range(24)), "max_grid_kwh": 0}),
    ]
    context = build_optimization_context(request, directives)

    with pytest.raises(OptimizationError, match="Infeasible"):
        solve_energy_optimization(context)
