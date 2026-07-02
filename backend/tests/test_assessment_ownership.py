# backend/tests/test_assessment_ownership.py
from datetime import datetime

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def _routed_change(client, eng_auth, seed, session_factory, part_id):
    """Change routed into in_assessment via the standard flow."""
    from tests.conftest import approve_gates
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "own", "change_type": "tooling",
        "lead_id": seed["engineer_id"]}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    change = res.json()
    res = await client.post(f"/api/v1/changes/{change['id']}/impacted-items",
                            json={"part_id": part_id, "is_lead": True},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    await approve_gates(client, eng_auth, change["id"])
    res = await client.post(f"/api/v1/changes/{change['id']}/transition",
                            json={"to_status": "in_assessment"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    return change


async def test_assessments_get_due_date_on_activation(
        client, eng_auth, seed, session_factory, part):
    from app.models.change import ChangeAssessment
    from app.models.workflow import Department
    # Fallback routing (no ChangeRoutingStandard) maps change_type "tooling" to
    # these department names via TYPE_DISCIPLINES; seed them so rows are created.
    async with session_factory() as s:
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            s.add(Department(name=n, flow_type="action", is_active=True))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change["id"]))).scalars().all()
        assert rows
        active = [a for a in rows if a.status == "active"]
        assert active
        assert all(a.due_date is not None for a in active)
        pending = [a for a in rows if a.status == "pending"]
        assert all(a.due_date is None for a in pending)
