"""Run supplied public cases through the real service and replay every schedule."""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.schemas.directives import DirectiveInterpretation  # noqa: E402
from app.schemas.request import OptimizeEnergyRequest  # noqa: E402
from app.services.optimization_service import OptimizationService  # noqa: E402
from app.utils.calculations import calculate_totals  # noqa: E402
from app.validators.schedule_validator import validate_schedule  # noqa: E402

SAMPLE_NAME = "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
DEFAULT_SAMPLES = ROOT / SAMPLE_NAME


def load_cases(path: Path):
    with path.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("Sample file must contain a nonempty array or a 'cases' array")
    return cases


def split_case(case):
    if not isinstance(case, dict):
        raise ValueError("Each case must be a JSON object")
    request_data = case.get("input", case.get("request", case))
    expected = case.get("expected_output", case.get("expected", {}))
    if not isinstance(request_data, dict) or not isinstance(expected, dict):
        raise ValueError("Case input and expected output must be JSON objects")
    reference_cost = expected.get("total_cost_bdt", case.get("expected_total_cost_bdt"))
    return request_data, reference_cost, expected.get("directive_interpretation")


def verify_directives(request, response, reference_directives):
    if reference_directives is None:
        return False
    if not isinstance(reference_directives, list) or len(reference_directives) != len(request.operator_notes):
        raise AssertionError("Reference directives do not match the operator notes")
    for index, (actual, reference) in enumerate(zip(response.directive_interpretation, reference_directives)):
        if actual.note_index != index or reference.get("note_index") != index:
            raise AssertionError(f"Directive {index}: wrong note order")
        if actual.applies != reference.get("applies") or actual.directive_type != reference.get("directive_type"):
            raise AssertionError(f"Directive {index}: interpretation mismatch")
        actual_adjustment = actual.structured_adjustment.model_dump() if actual.structured_adjustment else None
        expected_adjustment = reference.get("structured_adjustment")
        if (actual_adjustment is None) != (expected_adjustment is None):
            raise AssertionError(f"Directive {index}: adjustment mismatch")
        if actual_adjustment is None:
            continue
        if set(actual_adjustment) != set(expected_adjustment):
            raise AssertionError(f"Directive {index}: adjustment fields mismatch")
        for field, value in expected_adjustment.items():
            actual_value = actual_adjustment[field]
            if field == "hours":
                if actual_value != value:
                    raise AssertionError(f"Directive {index}: hours mismatch")
            elif not math.isclose(actual_value, value, rel_tol=0, abs_tol=0.01):
                raise AssertionError(f"Directive {index}: {field} mismatch")
    return True


def verify_result(request, response, reference_cost, reference_directives=None):
    if response.scenario_id != request.scenario_id:
        raise AssertionError("Scenario ID mismatch")
    if len(response.directive_interpretation) != len(request.operator_notes):
        raise AssertionError("Missing operator note interpretations")
    directives_verified = verify_directives(request, response, reference_directives)
    plan = [entry.model_dump() for entry in response.hourly_plan]
    validate_schedule(request, response.directive_interpretation, plan)
    grid, cost, peak = calculate_totals(plan, request.hours)
    for label, actual, calculated in (
        ("total grid", response.total_grid_kwh, grid),
        ("total cost", response.total_cost_bdt, cost),
        ("peak grid", response.peak_grid_kwh, peak),
    ):
        if not math.isclose(actual, calculated, rel_tol=1e-7, abs_tol=0.01):
            raise AssertionError(f"{label} does not match the hourly plan")
    if reference_cost is None:
        return "FEASIBLE (no reference cost)"
    if isinstance(reference_cost, bool) or not isinstance(reference_cost, (int, float)) or not math.isfinite(reference_cost) or reference_cost < 0:
        raise ValueError("Reference cost must be a finite nonnegative number")
    tolerance = 0.01
    if abs(cost - reference_cost) > tolerance:
        raise AssertionError(f"Cost mismatch: got {cost:.2f}, expected {reference_cost:.2f}, tolerance {tolerance:.2f}")
    return "PASS" if directives_verified else "FEASIBLE (no directive reference)"


class ReferenceInterpreter:
    """Replay published directives to check deterministic stages without an LLM key."""

    def __init__(self, reference_directives):
        self.reference_directives = reference_directives

    async def interpret(self, operator_notes, capacity_kwh):
        return [DirectiveInterpretation.model_validate(item) for item in self.reference_directives]


async def run_samples(path: Path, expected_count: int = 10, use_reference_directives: bool = False) -> int:
    try:
        cases = load_cases(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Unable to load public samples from {path}: {exc}", file=sys.stderr)
        return 2
    if len(cases) != expected_count:
        print(f"Expected {expected_count} public sample cases, found {len(cases)}", file=sys.stderr)
        return 2

    service = OptimizationService()
    passed = feasible_only = failed = 0
    mode = "reference-directive solver check" if use_reference_directives else "full pipeline"
    print(f"Running {len(cases)} public sample cases from {path} ({mode})")
    for index, case in enumerate(cases, start=1):
        scenario_id = case.get("scenario_id", f"Case-{index}") if isinstance(case, dict) else f"Case-{index}"
        try:
            request_data, reference_cost, reference_directives = split_case(case)
            scenario_id = request_data.get("scenario_id", scenario_id)
            request = OptimizeEnergyRequest.model_validate(request_data)
            active_service = (
                OptimizationService(ReferenceInterpreter(reference_directives))
                if use_reference_directives else service
            )
            response = await active_service.run_pipeline(request)
            verdict = verify_result(request, response, reference_cost, reference_directives)
            if verdict == "PASS":
                passed += 1
            else:
                feasible_only += 1
            print(f"[{index}/{len(cases)}] {scenario_id}: {verdict} ({response.total_cost_bdt:.2f} BDT)")
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(cases)}] {scenario_id}: FAIL ({exc})")
    print(f"Summary: {passed} reference matches, {feasible_only} feasible without reference, {failed} failed")
    return 1 if failed or feasible_only else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", nargs="?", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument(
        "--use-reference-directives", action="store_true",
        help="Check guardrails, solver, replay, and cost using published directives; does not test the LLM",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_samples(args.samples, use_reference_directives=args.use_reference_directives)))


if __name__ == "__main__":
    main()
