"""Calculate response totals from a validated hourly plan."""

from typing import Any, Dict, List, Tuple

from app.schemas.request import HourForecast


def calculate_totals(
    hourly_plan: List[Dict[str, Any]],
    hours_forecast: List[HourForecast],
) -> Tuple[float, float, float]:
    total_grid_kwh = sum(entry["grid_kwh"] for entry in hourly_plan)
    total_cost_bdt = sum(
        entry["grid_kwh"] * forecast.tariff_bdt_per_kwh
        for entry, forecast in zip(hourly_plan, hours_forecast)
    )
    peak_grid_kwh = max(entry["grid_kwh"] for entry in hourly_plan)
    return round(total_grid_kwh, 4), round(total_cost_bdt, 4), round(peak_grid_kwh, 4)


def generate_plan_summary(
    total_grid_kwh: float,
    total_cost_bdt: float,
    directives_applied: int,
) -> str:
    return (
        f"Optimized 24-hour schedule satisfies {directives_applied} operator directive(s) "
        f"and maintains end-of-day battery neutrality. "
        f"Total grid procurement: {total_grid_kwh:.2f} kWh costing {total_cost_bdt:.2f} BDT."
    )
