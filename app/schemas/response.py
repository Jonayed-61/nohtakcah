from typing import List, Literal

from pydantic import BaseModel, Field

from app.schemas.directives import DirectiveInterpretation

BatteryAction = Literal["charge", "discharge", "idle"]


class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0.0)
    solar_used_kwh: float = Field(..., ge=0.0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0.0)
    battery_energy_after_kwh: float = Field(..., ge=0.0)


class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float = Field(..., ge=0.0)
    total_cost_bdt: float = Field(..., ge=0.0)
    peak_grid_kwh: float = Field(..., ge=0.0)
    plan_summary: str


class HealthResponse(BaseModel):
    status: str = "ok"
