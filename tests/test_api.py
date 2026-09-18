"""HTTP contract checks for the public optimization API."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def sample_request():
    return {
        "scenario_id": "TEST-101",
        "operator_notes": ["No charging between 14:00 and 16:00."],
        "hours": [
            {"hour": h, "demand_kwh": 100.0, "solar_kwh": 20.0, "tariff_bdt_per_kwh": 5.0}
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 200.0,
            "initial_energy_kwh": 100.0,
            "minimum_energy_kwh": 20.0,
            "max_charge_kwh_per_hour": 50.0,
            "max_discharge_kwh_per_hour": 50.0,
        },
    }


@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    "missing_hour", "duplicate_hour", "negative_demand", "empty_note",
    "minimum_above_capacity", "initial_below_minimum",
])
async def test_invalid_request_is_rejected(sample_request, invalid):
    if invalid == "missing_hour":
        sample_request["hours"].pop()
    elif invalid == "duplicate_hour":
        sample_request["hours"][23]["hour"] = 22
    elif invalid == "negative_demand":
        sample_request["hours"][0]["demand_kwh"] = -1
    elif invalid == "minimum_above_capacity":
        sample_request["battery"]["minimum_energy_kwh"] = 201
    elif invalid == "initial_below_minimum":
        sample_request["battery"]["minimum_energy_kwh"] = 101
    else:
        sample_request["operator_notes"] = [" "]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/optimize-energy", json=sample_request)
    assert response.status_code == 422
