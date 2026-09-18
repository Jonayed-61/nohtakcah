"""Interpret operator notes into structured directives using Groq JSON output."""

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
        if settings.LLM_PROVIDER != "groq":
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
            "Do not invent numerical limits that are absent from the note. "
            f"Battery capacity is {capacity_kwh} kWh. "
            f"Operator notes: {json.dumps(operator_notes, ensure_ascii=False)}"
        )
        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON. Follow the user's output contract exactly.",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
            text = result["choices"][0]["message"]["content"]
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON array")
            return [DirectiveInterpretation.model_validate(item) for item in parsed]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMInterpretationError("Unable to interpret operator notes") from exc
