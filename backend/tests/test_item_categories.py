"""Controlled item categories (tools, assembly equipment, gauges) tests."""


async def _create_item(client, eng_auth, seed, **overrides):
    payload = {
        "project_id": seed["project_id"],
        "part_number": overrides.pop("part_number", "G-001"),
        "name": overrides.pop("name", "Caliper"),
        "part_type": "purchased",
        "data_classification": "confidential",
        **overrides,
    }
    return await client.post("/api/v1/parts", json=payload, headers=eng_auth)


async def test_create_gauge_with_calibration_interval(client, eng_auth, seed):
    res = await _create_item(
        client, eng_auth, seed,
        item_category="gauge",
        calibration_interval_months=12,
        last_calibrated_at="2026-01-01T00:00:00",
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["item_category"] == "gauge"
    assert body["calibration_interval_months"] == 12
    # next due computed: 2026-01-01 + ~12 months
    assert body["next_calibration_due"].startswith("2026-12") or body["next_calibration_due"].startswith("2027-01")


async def test_default_category_is_article(client, eng_auth, seed):
    res = await _create_item(client, eng_auth, seed, part_number="A-001", name="Bracket")
    assert res.status_code == 200
    assert res.json()["item_category"] == "article"


async def test_invalid_category_rejected(client, eng_auth, seed):
    res = await _create_item(client, eng_auth, seed, item_category="spaceship")
    assert res.status_code == 400


async def test_mark_calibrated_updates_due_date(client, eng_auth, seed):
    res = await _create_item(
        client, eng_auth, seed,
        item_category="gauge",
        calibration_interval_months=6,
    )
    part_id = res.json()["id"]
    assert res.json()["next_calibration_due"] is None  # never calibrated

    res = await client.put(
        f"/api/v1/parts/{part_id}",
        json={"last_calibrated_at": "2026-06-01T00:00:00"},
        headers=eng_auth,
    )
    assert res.status_code == 200
    assert res.json()["next_calibration_due"] is not None


async def test_tool_inherits_revision_machinery(client, eng_auth, seed):
    """Tools are controlled items: they get revisions like articles."""
    res = await _create_item(client, eng_auth, seed, part_number="T-001", name="Die", item_category="tool")
    tool_id = res.json()["id"]

    res = await client.post(
        f"/api/v1/parts/{tool_id}/revisions/rfq", json={"summary": "tool rev"}, headers=eng_auth
    )
    assert res.status_code == 200
    assert res.json()["revision_name"] == "RFQ1"
