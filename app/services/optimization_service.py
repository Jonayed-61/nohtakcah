"""Run interpretation, guardrails, optimization, and independent verification."""

import asyncio
from typing import Optional

from app.guardrails.directive_validator import validate_directives
from app.llm.interpreter import LLMInterpreter
from app.optimizer.model import build_optimization_context
from app.optimizer.solver import solve_energy_optimization
from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import HourlyPlanEntry, OptimizeEnergyResponse
from app.utils.calculations import calculate_totals, generate_plan_summary
from app.validators.schedule_validator import validate_schedule


class OptimizationService:
    def __init__(self, interpreter: Optional[LLMInterpreter] = None):
        self.interpreter = interpreter if interpreter is not None else LLMInterpreter()

    async def run_pipeline(self, request: OptimizeEnergyRequest) -> OptimizeEnergyResponse:
        raw_directives = await self.interpreter.interpret(
            operator_notes=request.operator_notes,
            capacity_kwh=request.battery.capacity_kwh,
        )
        validated_directives = validate_directives(raw_directives, request)
        context = build_optimization_context(request, validated_directives)
        candidate_schedule = await asyncio.to_thread(solve_energy_optimization, context)
        validate_schedule(request, validated_directives, candidate_schedule)

        total_grid, total_cost, peak_grid = calculate_totals(candidate_schedule, request.hours)
        active_count = sum(
            directive.applies and directive.directive_type != "no_op"
            for directive in validated_directives
        )
        return OptimizeEnergyResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=validated_directives,
            hourly_plan=[HourlyPlanEntry(**entry) for entry in candidate_schedule],
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak_grid,
            plan_summary=generate_plan_summary(total_grid, total_cost, active_count),
        )
