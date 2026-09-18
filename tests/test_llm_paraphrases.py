"""Optional live Gemini checks for note paraphrases outside the public samples."""

import os

import pytest

from app.llm.interpreter import LLMInterpreter

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_LLM_TESTS") != "1",
        reason="Set RUN_LIVE_LLM_TESTS=1 and configure LLM_API_KEY to run live Gemini checks",
    ),
]


@pytest.mark.parametrize(
    ("notes", "expected_type", "expected_hours", "expected_value"),
    [
        (
            [
                "Please suspend all battery charging for the 2 PM and 3 PM slots.",
                "The storage unit must not absorb electricity from 14:00 up to 16:00.",
                "From two in the afternoon until four, charging is unavailable.",
            ],
            "no_charge_window",
            [14, 15],
            None,
        ),
        (
            [
                "From 11:00 to 13:00, usable PV is a fifth of normal.",
                "Expect an eighty-percent cut in rooftop generation between 11 AM and 1 PM.",
                "For the 11 AM and noon slots, just 20% of forecast solar energy can be used.",
            ],
            "solar_reduction",
            [11, 12],
            0.2,
        ),
    ],
)
async def test_paraphrased_notes_have_same_semantics(
    notes, expected_type, expected_hours, expected_value
):
    directives = await LLMInterpreter().interpret(notes, capacity_kwh=200)

    assert len(directives) == len(notes)
    for index, directive in enumerate(directives):
        assert directive.note_index == index
        assert directive.applies is True
        assert directive.directive_type == expected_type
        assert directive.structured_adjustment.hours == expected_hours
        if expected_value is not None:
            assert directive.structured_adjustment.factor == pytest.approx(
                expected_value, abs=0.01
            )
