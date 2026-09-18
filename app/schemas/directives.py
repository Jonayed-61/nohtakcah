from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class SolarReductionAdjustment(BaseModel):
    hours: List[int] = Field(..., description="List of hour indices 0..23")
    factor: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Usable fraction remaining (e.g., 0.2 for 80% reduction)",
    )


class MinimumBatteryReserveAdjustment(BaseModel):
    hours: List[int]
    minimum_energy_kwh: float = Field(..., ge=0.0)


class NoChargeWindowAdjustment(BaseModel):
    hours: List[int]


class NoDischargeWindowAdjustment(BaseModel):
    hours: List[int]


class MaxGridWindowAdjustment(BaseModel):
    hours: List[int]
    max_grid_kwh: float = Field(..., ge=0.0)


StructuredAdjustment = Union[
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    MaxGridWindowAdjustment,
    None,
]


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(..., ge=0, le=2)
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[StructuredAdjustment] = None
    explanation: str = Field(..., description="Concise rationale for the interpretation")
