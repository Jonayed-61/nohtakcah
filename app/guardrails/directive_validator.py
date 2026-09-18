"""Validate directive structure and bounds before optimization."""

import math
from typing import List

from pydantic import ValidationError

from app.schemas.directives import (
    DirectiveInterpretation,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    SolarReductionAdjustment,
)
from app.schemas.request import OptimizeEnergyRequest


class DirectiveValidationError(Exception):
    """Raised when interpreted directives are malformed or unsafe."""


_ADJUSTMENT_TYPES = {
    "solar_reduction": SolarReductionAdjustment,
    "minimum_battery_reserve": MinimumBatteryReserveAdjustment,
    "no_charge_window": NoChargeWindowAdjustment,
    "no_discharge_window": NoDischargeWindowAdjustment,
    "max_grid_window": MaxGridWindowAdjustment,
}


def validate_directives(
    raw_directives: List[DirectiveInterpretation],
    request: OptimizeEnergyRequest,
) -> List[DirectiveInterpretation]:
    if not isinstance(raw_directives, list) or len(raw_directives) != len(request.operator_notes):
        raise DirectiveValidationError("Expected one interpretation per operator note")

    validated = []
    seen_indices = set()
    for raw in raw_directives:
        try:
            interpretation = DirectiveInterpretation.model_validate(raw)
        except (ValidationError, TypeError, ValueError) as exc:
            raise DirectiveValidationError("Malformed directive interpretation") from exc

        index = interpretation.note_index
        if index >= len(request.operator_notes) or index in seen_indices:
            raise DirectiveValidationError("Directive note indices must be unique and match operator notes")
        seen_indices.add(index)

        kind = interpretation.directive_type
        if kind == "no_op":
            if interpretation.applies or interpretation.structured_adjustment is not None:
                raise DirectiveValidationError(f"Note {index}: Invalid no_op semantics")
        else:
            if not interpretation.applies:
                raise DirectiveValidationError(f"Note {index}: Applicable directive must set applies=true")
            if interpretation.structured_adjustment is None:
                raise DirectiveValidationError(f"Note {index}: Missing structured adjustment")
            adjustment_type = _ADJUSTMENT_TYPES[kind]
            try:
                adjustment = adjustment_type.model_validate(
                    interpretation.structured_adjustment.model_dump()
                )
            except (ValidationError, TypeError, ValueError) as exc:
                raise DirectiveValidationError(f"Note {index}: Invalid {kind} adjustment") from exc

            hours = adjustment.hours
            if not hours or any(type(h) is not int or h < 0 or h > 23 for h in hours) or hours != sorted(set(hours)):
                raise DirectiveValidationError(f"Note {index}: Hours must be unique ascending integers from 0 to 23")
            if kind == "minimum_battery_reserve":
                if not math.isfinite(adjustment.minimum_energy_kwh) or adjustment.minimum_energy_kwh > request.battery.capacity_kwh:
                    raise DirectiveValidationError(f"Note {index}: Reserve exceeds battery capacity")
            elif kind == "max_grid_window" and not math.isfinite(adjustment.max_grid_kwh):
                raise DirectiveValidationError(f"Note {index}: Grid cap must be finite")

            interpretation = interpretation.model_copy(update={"structured_adjustment": adjustment})
        validated.append(interpretation)

    return sorted(validated, key=lambda item: item.note_index)
