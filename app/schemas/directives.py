from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class HoursAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    hours: List[int] = Field(..., description="List of hour indices 0..23")


class SolarReductionAdjustment(HoursAdjustment):
    factor: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Usable fraction remaining (e.g., 0.2 for 80% reduction)",
    )


class MinimumBatteryReserveAdjustment(HoursAdjustment):
    minimum_energy_kwh: float = Field(..., ge=0.0)


class NoChargeWindowAdjustment(HoursAdjustment):
    """Hours in which the battery cannot charge."""


class NoDischargeWindowAdjustment(HoursAdjustment):
    """Hours in which the battery cannot discharge."""


class MaxGridWindowAdjustment(HoursAdjustment):
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
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    note_index: int = Field(..., ge=0, le=2)
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[StructuredAdjustment] = None
    explanation: str = Field(..., description="Concise rationale for the interpretation")
