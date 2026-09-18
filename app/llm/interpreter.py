"""Interpret operator notes into structured directives using Gemini JSON output."""

import asyncio
import json
from typing import List

import httpx

from app.config import settings
from app.schemas.directives import DirectiveInterpretation


class LLMInterpretationError(Exception):
    """Raised when the configured model cannot produce usable directives."""


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
