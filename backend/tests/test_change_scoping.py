"""Scoping stage: meeting model, gate seeding, and (later tasks) the state machine."""
import pytest
from sqlalchemy import select

from tests.conftest import login, ADMIN_PASSWORD


async def create_change(client, auth, project_id, **overrides):
    body = {"project_id": project_id, "title": "Scoped change",
            "change_type": "physical_part", **overrides}
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_create_seeds_only_release_gate(client, admin_auth, seed):
    change = await create_change(client, admin_auth, seed["project_id"])
    res = await client.get(f"/api/v1/changes/{change['id']}/gates", headers=admin_auth)
    assert res.status_code == 200
    assert [g["gate_key"] for g in res.json()] == ["release"]


@pytest.mark.asyncio
async def test_meeting_model_roundtrip(session_factory, client, admin_auth, seed):
    from datetime import datetime
    from app.models.change import ChangeMeeting
    change = await create_change(client, admin_auth, seed["project_id"])
    async with session_factory() as s:
        s.add(ChangeMeeting(
            change_id=change["id"], meeting_date=datetime.utcnow(),
            participants=[{"name": "PM Jane"}], notes="scope clarified",
            decision=None, selected_department_ids=[1, 2],
            created_by=seed["admin_id"]))
        await s.commit()
    async with session_factory() as s:
        row = (await s.execute(select(ChangeMeeting).where(
            ChangeMeeting.change_id == change["id"]))).scalar_one()
        assert row.participants == [{"name": "PM Jane"}]
        assert row.selected_department_ids == [1, 2]
        assert row.decision is None
