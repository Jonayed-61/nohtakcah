"""Replay a proposed schedule without trusting the optimizer's internal state."""

import math
from typing import Any, Dict, List

from app.schemas.directives import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest


class ScheduleValidationError(Exception):
    """Raised when a candidate schedule violates a physical or directive bound."""


def _number(entry: Dict[str, Any], field: str, hour: int) -> float:
    value = entry.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScheduleValidationError(f"Hour {hour}: {field} must be a finite number")
    return float(value)


def validate_schedule(
    request: OptimizeEnergyRequest,
    directives: List[DirectiveInterpretation],
    hourly_plan: List[Dict[str, Any]],
    tolerance: float = 1e-2,
) -> None:
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and nonnegative")
    if len(hourly_plan) != 24:
        raise ScheduleValidationError(f"Expected 24 entries in hourly plan, got {len(hourly_plan)}")

    battery = request.battery
    effective_solar = [forecast.solar_kwh for forecast in request.hours]
    required_minimum = [battery.minimum_energy_kwh] * 24
    charge_allowed = [True] * 24
    discharge_allowed = [True] * 24
    grid_caps = [float("inf")] * 24

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
            for h in hours:
                effective_solar[h] = min(
                    effective_solar[h], request.hours[h].solar_kwh * factor
                )
        elif interpretation.directive_type == "minimum_battery_reserve":
            minimum = getattr(adjustment, "minimum_energy_kwh", battery.minimum_energy_kwh)
            for h in hours:
                required_minimum[h] = max(required_minimum[h], minimum)
        elif interpretation.directive_type == "no_charge_window":
            for h in hours:
                charge_allowed[h] = False
        elif interpretation.directive_type == "no_discharge_window":
            for h in hours:
                discharge_allowed[h] = False
        elif interpretation.directive_type == "max_grid_window":
            cap = getattr(adjustment, "max_grid_kwh", float("inf"))
            for h in hours:
                grid_caps[h] = min(grid_caps[h], cap)

    current_energy = battery.initial_energy_kwh
    for h, entry in enumerate(hourly_plan):
        if not isinstance(entry, dict):
            raise ScheduleValidationError(f"Hour {h}: Expected an object")
        if type(entry.get("hour")) is not int or entry["hour"] != h:
            raise ScheduleValidationError(f"Hour mismatch at index {h}: expected {h}, got {entry.get('hour')}")

        grid = _number(entry, "grid_kwh", h)
        solar_used = _number(entry, "solar_used_kwh", h)
        battery_kwh = _number(entry, "battery_kwh", h)
        energy_after = _number(entry, "battery_energy_after_kwh", h)
        action = entry.get("battery_action")

        if grid < -tolerance or solar_used < -tolerance or battery_kwh < -tolerance:
            raise ScheduleValidationError(f"Hour {h}: Negative energy values detected")
        if solar_used > effective_solar[h] + tolerance:
            raise ScheduleValidationError(f"Hour {h}: Solar used exceeds effective solar limit")

        charge = discharge = 0.0
        if action == "charge":
            if not charge_allowed[h]:
                raise ScheduleValidationError(f"Hour {h}: Battery charged during no_charge_window")
            if battery_kwh > battery.max_charge_kwh_per_hour + tolerance:
                raise ScheduleValidationError(f"Hour {h}: Charge rate exceeds maximum")
            charge = battery_kwh
        elif action == "discharge":
            if not discharge_allowed[h]:
                raise ScheduleValidationError(f"Hour {h}: Battery discharged during no_discharge_window")
            if battery_kwh > battery.max_discharge_kwh_per_hour + tolerance:
                raise ScheduleValidationError(f"Hour {h}: Discharge rate exceeds maximum")
            discharge = battery_kwh
        elif action == "idle":
            if abs(battery_kwh) > tolerance:
                raise ScheduleValidationError(f"Hour {h}: Idle action has nonzero battery_kwh")
        else:
            raise ScheduleValidationError(f"Hour {h}: Unknown battery action")

        supply = grid + solar_used + discharge
        load = request.hours[h].demand_kwh + charge
        if abs(supply - load) > tolerance:
            raise ScheduleValidationError(f"Hour {h}: Energy balance violation")

        expected_after = current_energy + charge - discharge
        if abs(energy_after - expected_after) > tolerance:
            raise ScheduleValidationError(f"Hour {h}: Battery state transition mismatch")
        if energy_after < required_minimum[h] - tolerance:
            raise ScheduleValidationError(f"Hour {h}: Battery energy fell below required reserve")
        if energy_after > battery.capacity_kwh + tolerance:
            raise ScheduleValidationError(f"Hour {h}: Battery energy exceeded capacity")
        if grid > grid_caps[h] + tolerance:
            raise ScheduleValidationError(f"Hour {h}: Grid import exceeded max_grid_window limit")
        current_energy = energy_after

    if abs(current_energy - battery.initial_energy_kwh) > tolerance:
        raise ScheduleValidationError("End of day battery neutrality check failed")
