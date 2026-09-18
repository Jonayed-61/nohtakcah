"""Turn validated request data and directives into hourly solver inputs."""

from dataclasses import dataclass
from typing import List, Optional

from app.schemas.directives import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest


@dataclass
class OptimizationContext:
    scenario_id: str
    capacity_kwh: float
    initial_energy_kwh: float
    base_minimum_kwh: float
    max_charge_rate: float
    max_discharge_rate: float

    demand: List[float]
    tariff: List[float]
    effective_solar: List[float]
    required_minimum: List[float]
    charge_allowed: List[bool]
    discharge_allowed: List[bool]
    grid_cap: List[Optional[float]]


def build_optimization_context(
    request: OptimizeEnergyRequest,
    directives: List[DirectiveInterpretation],
) -> OptimizationContext:
    demand = [hour.demand_kwh for hour in request.hours]
    tariff = [hour.tariff_bdt_per_kwh for hour in request.hours]
    effective_solar = [hour.solar_kwh for hour in request.hours]

    battery = request.battery
    base_minimum = battery.minimum_energy_kwh
    required_minimum = [base_minimum] * 24
    charge_allowed = [True] * 24
    discharge_allowed = [True] * 24
    grid_cap: List[Optional[float]] = [None] * 24

    for interpretation in directives:
        if (
            not interpretation.applies
            or interpretation.directive_type == "no_op"
            or interpretation.structured_adjustment is None
        ):
            continue

        adjustment = interpretation.structured_adjustment
        hours = getattr(adjustment, "hours", [])

        if interpretation.directive_type == "solar_reduction":
            factor = getattr(adjustment, "factor", 1.0)
            for hour in hours:
                effective_solar[hour] = request.hours[hour].solar_kwh * factor

        elif interpretation.directive_type == "minimum_battery_reserve":
            minimum = getattr(adjustment, "minimum_energy_kwh", base_minimum)
            for hour in hours:
                required_minimum[hour] = max(required_minimum[hour], minimum)

        elif interpretation.directive_type == "no_charge_window":
            for hour in hours:
                charge_allowed[hour] = False

        elif interpretation.directive_type == "no_discharge_window":
            for hour in hours:
                discharge_allowed[hour] = False

        elif interpretation.directive_type == "max_grid_window":
            cap = getattr(adjustment, "max_grid_kwh", None)
            if cap is not None:
                for hour in hours:
                    grid_cap[hour] = cap if grid_cap[hour] is None else min(grid_cap[hour], cap)

    return OptimizationContext(
        scenario_id=request.scenario_id,
        capacity_kwh=battery.capacity_kwh,
        initial_energy_kwh=battery.initial_energy_kwh,
        base_minimum_kwh=base_minimum,
        max_charge_rate=battery.max_charge_kwh_per_hour,
        max_discharge_rate=battery.max_discharge_kwh_per_hour,
        demand=demand,
        tariff=tariff,
        effective_solar=effective_solar,
        required_minimum=required_minimum,
        charge_allowed=charge_allowed,
        discharge_allowed=discharge_allowed,
        grid_cap=grid_cap,
    )
