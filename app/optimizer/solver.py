"""Solve the 24-hour grid scheduling mixed-integer linear program."""

from typing import Any, Dict, List

import pulp

from app.optimizer.model import OptimizationContext


class OptimizationError(Exception):
    """Raised when the energy model has no optimal solution."""


def solve_energy_optimization(ctx: OptimizationContext) -> List[Dict[str, Any]]:
    problem = pulp.LpProblem("GridWise_Energy_Optimization", pulp.LpMinimize)
    hours = range(24)

    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0) for h in hours]
    solar_used = [pulp.LpVariable(f"solar_used_{h}", lowBound=0) for h in hours]
    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0) for h in hours]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0) for h in hours]
    energy_after = [pulp.LpVariable(f"energy_after_{h}", lowBound=0) for h in hours]
    is_charging = [pulp.LpVariable(f"is_charging_{h}", cat=pulp.LpBinary) for h in hours]
    is_discharging = [pulp.LpVariable(f"is_discharging_{h}", cat=pulp.LpBinary) for h in hours]

    problem += pulp.lpSum(grid[h] * ctx.tariff[h] for h in hours)

    for h in hours:
        problem += solar_used[h] <= ctx.effective_solar[h], f"SolarLimit_{h}"
        problem += (
            grid[h] + solar_used[h] + discharge[h] == ctx.demand[h] + charge[h],
            f"EnergyBalance_{h}",
        )

        energy_before = ctx.initial_energy_kwh if h == 0 else energy_after[h - 1]
        problem += energy_after[h] == energy_before + charge[h] - discharge[h], f"BatteryState_{h}"
        problem += energy_after[h] >= ctx.required_minimum[h], f"MinEnergy_{h}"
        problem += energy_after[h] <= ctx.capacity_kwh, f"MaxEnergy_{h}"

        if ctx.charge_allowed[h]:
            problem += charge[h] <= ctx.max_charge_rate * is_charging[h], f"MaxCharge_{h}"
        else:
            problem += charge[h] == 0, f"NoCharge_{h}"
            problem += is_charging[h] == 0, f"NoChargeBinary_{h}"

        if ctx.discharge_allowed[h]:
            problem += discharge[h] <= ctx.max_discharge_rate * is_discharging[h], f"MaxDischarge_{h}"
        else:
            problem += discharge[h] == 0, f"NoDischarge_{h}"
            problem += is_discharging[h] == 0, f"NoDischargeBinary_{h}"

        problem += is_charging[h] + is_discharging[h] <= 1, f"MutualExclusion_{h}"

        if ctx.grid_cap[h] is not None:
            problem += grid[h] <= ctx.grid_cap[h], f"GridCap_{h}"

    problem += energy_after[23] == ctx.initial_energy_kwh, "EOD_Battery_Neutrality"

    status = problem.solve(pulp.PULP_CBC_CMD(msg=False))
    if status != pulp.LpStatusOptimal:
        raise OptimizationError(f"Optimization failed with status: {pulp.LpStatus[status]}")

    schedule = []
    for h in hours:
        charge_value = float(pulp.value(charge[h]))
        discharge_value = float(pulp.value(discharge[h]))

        if charge_value > 1e-4:
            action = "charge"
            battery_kwh = charge_value
        elif discharge_value > 1e-4:
            action = "discharge"
            battery_kwh = discharge_value
        else:
            action = "idle"
            battery_kwh = 0.0

        schedule.append(
            {
                "hour": h,
                "grid_kwh": float(pulp.value(grid[h])),
                "solar_used_kwh": float(pulp.value(solar_used[h])),
                "battery_action": action,
                "battery_kwh": battery_kwh,
                "battery_energy_after_kwh": float(pulp.value(energy_after[h])),
            }
        )

    return schedule
