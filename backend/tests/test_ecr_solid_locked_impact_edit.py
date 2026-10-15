"""ECR-solid C16 (spec §4 "Impact edits after the lock", switch
ASSESSMENT_V2): after proceed and before the offer, the run team changes the
impacted set only with a reason; the departments whose objects moved get
their finalized costing back (in quoting the change steps back to costing)
and are told once. Others may not edit at all (P1-5, kept)."""
import json
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeImpactedItem, ChangeRequest
from app.models.notification import Notification
from app.models.part import Part
from app.services import cm_switches
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def locked(client, session_factory, seed):
    """In costing, Development routed and finalized on part A."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="li-dev", email="li-dev@test.io",
                 full_name="LI dev", hashed_password=get_password_hash("li-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        dev_user = u.id
    dev = await make_department_member(session_factory, dev_user, "Development")
    async with session_factory() as s:
        a = Part(project_id=seed["project_id"], part_number="ART-LI-A", name="A",
                 part_type="internal_mfg", created_by=seed["admin_id"])
        b = Part(project_id=seed["project_id"], part_number="ART-LI-B", name="B",
                 part_type="internal_mfg", created_by=seed["admin_id"])
        s.add_all([a, b])
        await s.flush()
        change = ChangeRequest(
            change_number="C-LI-1", title="locked edit", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing",
            customer_relevant=True, impact_confirmed_at=datetime.utcnow(),
            impact_confirmed_by=seed["admin_id"])
        s.add(change)
        await s.flush()
        s.add(ChangeImpactedItem(change_id=change.id, part_id=a.id, is_lead=True,
                                 created_by=seed["admin_id"]))
        s.add(ChangeAssessment(
            change_id=change.id, department_id=dev, stage_order=1, rasic_letter="R",
            status="submitted", verdict="feasible", submitted_at=datetime(2026, 9, 1),
            owner_id=dev_user,
            details=json.dumps({"impacts": [{"key": "x", "answer": "yes", "impacted": True}],
                                "costing_finalized_at": "2026-10-01T00:00:00"})))
        await s.commit()
        return {"cid": change.id, "a": a.id, "b": b.id, "dev": dev,
                "dev_user": dev_user, "dev_auth": await login(client, "li-dev@test.io")}


def _u(x, tail=""):
    return f"/api/v1/changes/{x['cid']}{tail}"


async def test_an_edit_after_the_lock_needs_a_reason_and_reopens_costing(
        client, admin_auth, locked, session_factory):
    res = await client.post(_u(locked, "/impacted-items"),
                            json={"part_id": locked["b"]}, headers=admin_auth)
    assert res.status_code == 400 and "say why it changes" in res.json()["detail"]
    res = await client.post(_u(locked, "/impacted-items"),
                            json={"part_id": locked["b"], "reason": "ok"},
                            headers=admin_auth)
    assert res.status_code == 400
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    detail = (await client.get(_u(locked), headers=admin_auth)).json()
    assert detail["costing_finalized_department_ids"] == []
    assert locked["dev"] in detail["costing_pending_department_ids"]
    async with session_factory() as s:
        told = (await s.execute(select(Notification).where(
            Notification.kind == "impact_edited"))).scalars().all()
        assert [n.user_id for n in told] == [locked["dev_user"]]
        assert "ART-LI-B" in told[0].body and "costing is open again" in told[0].body


async def test_a_department_member_may_not_edit_after_the_lock(client, locked):
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=locked["dev_auth"])
    assert res.status_code == 403


async def test_in_quoting_the_change_steps_back_to_costing(
        client, admin_auth, locked, session_factory):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, locked["cid"])
        c.status = "quoting"
        await s.commit()
    res = await client.post(_u(locked, "/impacted-items"), json={
        "part_id": locked["b"], "reason": "Customer added the mirror part B"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, locked["cid"])).status == "costing"


async def test_switch_off_keeps_the_silent_edit(client, admin_auth, locked, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    res = await client.post(_u(locked, "/impacted-items"),
                            json={"part_id": locked["b"]}, headers=admin_auth)
    assert res.status_code == 200, res.text
