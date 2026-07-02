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


async def _first_active_assessment(session_factory, change_id):
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        return (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change_id,
            ChangeAssessment.status == "active"))).scalars().first()


async def test_accept_and_assign_assessment(client, eng_auth, admin_auth, seed,
                                            session_factory, part):
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            s.add(Department(name=n, flow_type="action", is_active=True))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    a = await _first_active_assessment(session_factory, change["id"])
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=a.department_id))
        await s.commit()

    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/accept",
        headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["owner_id"] == seed["engineer_id"]
    assert body["accepted_at"] is not None

    # admin assigns back to engineer -> accepted_at cleared
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/assign",
        json={"user_id": seed["engineer_id"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["accepted_at"] is None

    # non-member assignee refused
    res = await client.post(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/assign",
        json={"user_id": seed["admin_id"]}, headers=admin_auth)
    assert res.status_code == 400


async def test_assessment_due_date_lead_only(client, eng_auth, admin_auth, seed,
                                             session_factory, part):
    from datetime import datetime, timedelta
    from app.models.workflow import Department
    async with session_factory() as s:
        for n in ("Tool Engineer", "Process Engineer", "Manufacturing Engineer"):
            s.add(Department(name=n, flow_type="action", is_active=True))
        await s.commit()
    change = await _routed_change(client, eng_auth, seed, session_factory,
                                  part["part_id"])
    a = await _first_active_assessment(session_factory, change["id"])
    new_due = (datetime.utcnow() + timedelta(days=3)).isoformat()

    # engineer IS the lead (fixture sets lead_id) -> allowed
    res = await client.put(
        f"/api/v1/changes/{change['id']}/assessments/{a.id}/due-date",
        json={"due_date": new_due}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["due_date"] is not None

    # ownership events are in the changelog/audit
    from app.models.entities import AuditLog
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.correlation_id == change["change_number"],
            AuditLog.action == "assessment_due_date_set"))).scalars().all()
    assert len(rows) == 1
