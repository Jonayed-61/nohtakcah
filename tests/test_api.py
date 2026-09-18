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
async def test_dashboard_and_static_assets_are_served():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/")
        stylesheet = await client.get("/static/styles.css")
        script = await client.get("/static/app.js")

    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert 'id="runButton"' in page.text
    assert stylesheet.status_code == 200
    assert "text/css" in stylesheet.headers["content-type"]
    assert script.status_code == 200
    assert "/optimize-energy" in script.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("invalid", "expected_status"), [
    ("missing_hour", 400), ("duplicate_hour", 422),
    ("negative_demand", 422), ("empty_note", 422),
    ("minimum_above_capacity", 422), ("initial_below_minimum", 422),
    ("unknown_field", 400),
])
async def test_invalid_request_is_rejected(sample_request, invalid, expected_status):
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
    elif invalid == "unknown_field":
        sample_request["unexpected"] = "value"
    else:
        sample_request["operator_notes"] = [" "]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/optimize-energy", json=sample_request)
    assert response.status_code == expected_status
    assert set(response.json()) == {"detail"}


@pytest.mark.asyncio
async def test_malformed_json_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/optimize-energy", content="{bad json", headers={"content-type": "application/json"}
        )
    assert response.status_code == 400
    assert response.json() == {"detail": "Malformed or structurally invalid request."}
