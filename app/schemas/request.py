from typing import List

from pydantic import BaseModel, Field, field_validator


class HourForecast(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    demand_kwh: float = Field(..., ge=0.0)
    solar_kwh: float = Field(..., ge=0.0)
    tariff_bdt_per_kwh: float = Field(..., ge=0.0)


class BatterySpec(BaseModel):
    capacity_kwh: float = Field(..., gt=0.0)
    initial_energy_kwh: float = Field(..., ge=0.0)
    minimum_energy_kwh: float = Field(..., ge=0.0)
    max_charge_kwh_per_hour: float = Field(..., ge=0.0)
    max_discharge_kwh_per_hour: float = Field(..., ge=0.0)

    @field_validator("initial_energy_kwh")
    @classmethod
    def initial_within_capacity(cls, value: float, info):
        capacity = info.data.get("capacity_kwh")
        if capacity is not None and value > capacity:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        return value


class OptimizeEnergyRequest(BaseModel):
    scenario_id: str
    operator_notes: List[str] = Field(..., min_length=1, max_length=3)
    hours: List[HourForecast] = Field(..., min_length=24, max_length=24)
    battery: BatterySpec

    @field_validator("operator_notes")
    @classmethod
    def notes_must_be_non_empty(cls, values: List[str]):
        if any(not note.strip() for note in values):
            raise ValueError("operator_notes must contain non-empty strings")
        return values

    @field_validator("hours")
    @classmethod
    def validate_hours_sequence(cls, values: List[HourForecast]):
        seen_hours = [forecast.hour for forecast in values]
        if sorted(seen_hours) != list(range(24)):
            raise ValueError("hours must contain exactly 24 entries covering 0 through 23")
        return sorted(values, key=lambda forecast: forecast.hour)
