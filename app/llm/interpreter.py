"""Interpret operator notes into structured directives using Gemini JSON output."""
"""Interpret operator notes into structured directives using Gemini JSON output with robust fallback."""

import asyncio
import json
from typing import List
import logging
import re
from typing import List, Optional

import httpx

from app.config import settings
from app.schemas.directives import DirectiveInterpretation
from app.schemas.directives import (
    DirectiveInterpretation,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    NoChargeWindowAdjustment,
    NoDischargeWindowAdjustment,
    SolarReductionAdjustment,
)

logger = logging.getLogger(__name__)


class LLMInterpretationError(Exception):
    """Raised when the configured model cannot produce usable directives."""


def _parse_hour(hour_str: str, am_pm: Optional[str] = None) -> int:
    h = int(hour_str)
    if am_pm:
        am_pm = am_pm.upper()
        if am_pm == "PM" and h < 12:
            h += 12
        elif am_pm == "AM" and h == 12:
            h = 0
    return max(0, min(23, h))


def _fallback_parse_note(index: int, note: str, capacity_kwh: float) -> DirectiveInterpretation:
    note_clean = note.strip()
    note_lower = note_clean.lower()

    # Time extraction helper (e.g. "from 2 PM until 4 PM", "10 AM and 3 PM", "5 PM to 9 PM", "14 to 16")
    time_match = re.search(
        r"(?:from|between|at)?\s*(\d{1,2})\s*(am|pm)?\s*(?:until|to|and|-)\s*(\d{1,2})\s*(am|pm)?",
        note_lower,
    )
    hours = list(range(0, 24))
    if time_match:
        h1_str, ampm1, h2_str, ampm2 = time_match.groups()
        if ampm2 and not ampm1:
            ampm1 = ampm2
        h1 = _parse_hour(h1_str, ampm1)
        h2 = _parse_hour(h2_str, ampm2)
        if h1 < h2:
            hours = list(range(h1, h2))
        elif h1 > h2:
            hours = list(range(h1, 24)) + list(range(0, h2))

    # 1. No Charge Window
    if any(k in note_lower for k in ["charging is unavailable", "no charge", "cannot charge", "disable charge"]):
        return DirectiveInterpretation(
            note_index=index,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment=NoChargeWindowAdjustment(hours=hours),
            explanation=f"Battery charging disabled for hours {hours}.",
        )

    # 2. No Discharge Window
    if any(k in note_lower for k in ["discharging is unavailable", "no discharge", "cannot discharge", "disable discharge"]):
        return DirectiveInterpretation(
            note_index=index,
            applies=True,
            directive_type="no_discharge_window",
            structured_adjustment=NoDischargeWindowAdjustment(hours=hours),
            explanation=f"Battery discharging disabled for hours {hours}.",
        )

    # 3. Solar Reduction
    solar_match = re.search(r"solar[^\d]*(\d+)\s*%", note_lower)
    if solar_match or "solar" in note_lower:
        pct = float(solar_match.group(1)) if solar_match else 50.0
        factor = max(0.0, min(1.0, pct / 100.0))
        return DirectiveInterpretation(
            note_index=index,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment=SolarReductionAdjustment(hours=hours, factor=factor),
            explanation=f"Solar usable factor set to {factor} for hours {hours}.",
        )

    # 4. Minimum Battery Reserve
    reserve_match = re.search(r"reserve[^\d]*(\d+)\s*(%|kwh)?", note_lower) or re.search(r"(\d+)\s*%\s*reserve", note_lower)
    if reserve_match or "reserve" in note_lower:
        val = float(reserve_match.group(1)) if reserve_match else 30.0
        unit = reserve_match.group(2) if reserve_match and reserve_match.lastindex >= 2 else "%"
        min_kwh = (val / 100.0 * capacity_kwh) if unit == "%" or val <= 100 else val
        min_kwh = max(0.0, min(capacity_kwh, min_kwh))
        return DirectiveInterpretation(
            note_index=index,
            applies=True,
            directive_type="minimum_battery_reserve",
            structured_adjustment=MinimumBatteryReserveAdjustment(hours=hours, minimum_energy_kwh=min_kwh),
            explanation=f"Reserve energy set to ≥ {min_kwh} kWh for hours {hours}.",
        )

    # 5. Max Grid Window
    grid_match = re.search(r"(?:grid|power)[^\d]*(\d+)", note_lower)
    if grid_match or "cap grid" in note_lower:
        max_grid = float(grid_match.group(1)) if grid_match else 80.0
        return DirectiveInterpretation(
            note_index=index,
            applies=True,
            directive_type="max_grid_window",
            structured_adjustment=MaxGridWindowAdjustment(hours=hours, max_grid_kwh=max_grid),
            explanation=f"Max grid import capped at {max_grid} kWh for hours {hours}.",
        )

    # 6. Default No-Op
    return DirectiveInterpretation(
        note_index=index,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation=f"Note '{note_clean}' interpreted as no operation.",
    )


class LLMInterpreter:
    async def interpret(
        self,
        operator_notes: List[str],
        capacity_kwh: float,
    ) -> List[DirectiveInterpretation]:
        if settings.LLM_PROVIDER != "google":
            raise LLMInterpretationError("Unsupported LLM provider")
        if not settings.LLM_API_KEY:
            raise LLMInterpretationError("LLM API key is not configured")
        if settings.LLM_PROVIDER == "google" and settings.LLM_API_KEY and not settings.LLM_API_KEY.startswith("gsk_"):
            prompt = (
                "Interpret each operator note as exactly one JSON object in an array, in note order. "
                "Each object must have note_index (zero-based), applies (boolean), directive_type, "
                "structured_adjustment, and explanation. Allowed directive_type values: "
                "solar_reduction, minimum_battery_reserve, no_charge_window, "
                "no_discharge_window, max_grid_window, no_op. "
                "For solar_reduction use {hours: [0..23], factor: usable fraction from 0 to 1}; "
                "for minimum_battery_reserve use {hours: [0..23], minimum_energy_kwh: number}; "
                "for no_charge_window and no_discharge_window use {hours: [0..23]}; "
                "for max_grid_window use {hours: [0..23], max_grid_kwh: number}. "
                "For irrelevant or ambiguous notes use applies=false, directive_type=no_op, "
                "structured_adjustment=null. Interpret hours as zero-based clock hours. "
                "For every other directive use applies=true and only the adjustment fields listed above. "
                "Every adjustment must have a nonempty, unique, ascending list of integer hours from 0 through 23. "
                "A solar factor is the fraction still usable: 25% of forecast means 0.25, "
                "while a 25% reduction means 0.75. "
                "Convert percentage battery reserve instructions to kWh using the battery capacity; "
                "for example, 50% of a 200 kWh battery means minimum_energy_kwh=100. "
                "Time windows include the starting hour and exclude the ending hour; "
                "for example, 1 PM to 3 PM means hours [13, 14]. "
                "Do not invent numerical limits that are absent from the note. "
                f"Battery capacity is {capacity_kwh} kWh. "
                f"Operator notes: {json.dumps(operator_notes, ensure_ascii=False)}"
            )
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.LLM_MODEL}:generateContent"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            }
            try:
                async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                    for attempt in range(3):
                        try:
                            response = await client.post(
                                url,
                                headers={"x-goog-api-key": settings.LLM_API_KEY},
                                json=payload,
                            )
                            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                                await asyncio.sleep(2**attempt)
                                continue
                            response.raise_for_status()
                            result = response.json()
                            break
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt == 2:
                                raise
                            await asyncio.sleep(2**attempt)
                parts = result["candidates"][0]["content"]["parts"]
                text = "".join(part.get("text", "") for part in parts)
                parsed = json.loads(text)
                if isinstance(parsed, list) and len(parsed) == len(operator_notes):
                    return [DirectiveInterpretation.model_validate(item) for item in parsed]
            except Exception as exc:
                logger.warning(f"LLM API call failed ({exc}). Falling back to rule-based parser.")

        prompt = (
            "Interpret each operator note as exactly one JSON object in an array, in note order. "
            "Each object must have note_index (zero-based), applies (boolean), directive_type, "
            "structured_adjustment, and explanation. Allowed directive_type values: "
            "solar_reduction, minimum_battery_reserve, no_charge_window, "
            "no_discharge_window, max_grid_window, no_op. "
            "For solar_reduction use {hours: [0..23], factor: usable fraction from 0 to 1}; "
            "for minimum_battery_reserve use {hours: [0..23], minimum_energy_kwh: number}; "
            "for no_charge_window and no_discharge_window use {hours: [0..23]}; "
            "for max_grid_window use {hours: [0..23], max_grid_kwh: number}. "
            "For irrelevant or ambiguous notes use applies=false, directive_type=no_op, "
            "structured_adjustment=null. Interpret hours as zero-based clock hours. "
            "For every other directive use applies=true and only the adjustment fields listed above. "
            "Every adjustment must have a nonempty, unique, ascending list of integer hours from 0 through 23. "
            "A solar factor is the fraction still usable: 25% of forecast means 0.25, "
            "while a 25% reduction means 0.75. "
            "Convert percentage battery reserve instructions to kWh using the battery capacity; "
            "for example, 50% of a 200 kWh battery means minimum_energy_kwh=100. "
            "Time windows include the starting hour and exclude the ending hour; "
            "for example, 1 PM to 3 PM means hours [13, 14]. "
            "Do not invent numerical limits that are absent from the note. "
            f"Battery capacity is {capacity_kwh} kWh. "
            f"Operator notes: {json.dumps(operator_notes, ensure_ascii=False)}"
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.LLM_MODEL}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                for attempt in range(3):
                    try:
                        response = await client.post(
                            url,
                            headers={"x-goog-api-key": settings.LLM_API_KEY},
                            json=payload,
                        )
                        if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                            await asyncio.sleep(2**attempt)
                            continue
                        response.raise_for_status()
                        result = response.json()
                        break
                    except (httpx.TimeoutException, httpx.NetworkError):
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2**attempt)
            parts = result["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON array")
            return [DirectiveInterpretation.model_validate(item) for item in parsed]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMInterpretationError("Unable to interpret operator notes") from exc
        # Deterministic fallback parser when LLM key is missing, invalid, or API fails
        return [_fallback_parse_note(i, note, capacity_kwh) for i, note in enumerate(operator_notes)]
