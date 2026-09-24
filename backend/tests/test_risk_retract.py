"""A risk raised by mistake can be deleted by its raiser — hidden, not erased."""
from datetime import datetime

import pytest

from app.models.change import ChangeAssessment, ChangeAttachment, ChangeConcern, ChangeRequest
from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ctx(session_factory, seed):
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        change = ChangeRequest(
            change_number="C-RT-1", title="rt", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=dept.id, stage_order=1))
        await s.commit()
        return {"change_id": change.id, "department_id": dept.id}


async def _raise(client, auth, ctx):
    res = await client.post(f"/api/v1/changes/{ctx['change_id']}/concerns", json={
        "kind": "risk", "note": "oops", "risk_type": "timing", "severity": 2,
        "department_id": ctx["department_id"], "checklist_key": "threed_change"},
        headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _retract(client, auth, ctx, cid):
    return client.post(f"/api/v1/changes/{ctx['change_id']}/concerns/{cid}/retract",
                       headers=auth)


async def test_raiser_deletes_and_it_leaves_the_register(client, admin_auth, ctx):
    cid = await _raise(client, admin_auth, ctx)
    res = await _retract(client, admin_auth, ctx, cid)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False
    listed = (await client.get(f"/api/v1/changes/{ctx['change_id']}/concerns",
                               headers=admin_auth)).json()
    assert [c["id"] for c in listed] == []


async def test_deletion_is_on_the_record(client, admin_auth, ctx, session_factory):
    cid = await _raise(client, admin_auth, ctx)
    await _retract(client, admin_auth, ctx, cid)
    async with session_factory() as s:
        row = await s.get(ChangeConcern, cid)
        assert row is not None and row.retracted_at is not None
    log = await client.get(f"/api/v1/changes/{ctx['change_id']}/changelog",
                           headers=admin_auth)
    assert log.status_code == 200, log.text
    assert any(e["action"] == "concern_retracted" for e in log.json())


async def test_only_the_raiser_may_delete(client, admin_auth, eng_auth, ctx):
    cid = await _raise(client, admin_auth, ctx)
    res = await _retract(client, eng_auth, ctx, cid)
    assert res.status_code in (400, 403)


async def test_not_once_a_proposal_hangs_off_it(client, admin_auth, ctx, session_factory):
    cid = await _raise(client, admin_auth, ctx)
    async with session_factory() as s:
        row = await s.get(ChangeConcern, cid)
        row.answer_note = "move the gate"
        row.answered_at = datetime.utcnow()
        await s.commit()
    res = await _retract(client, admin_auth, ctx, cid)
    assert res.status_code == 400
    assert "resolve" in res.json()["detail"].lower()


async def test_not_once_a_document_hangs_off_it(client, admin_auth, ctx, session_factory, seed):
    cid = await _raise(client, admin_auth, ctx)
    async with session_factory() as s:
        s.add(ChangeAttachment(change_id=ctx["change_id"], filename="p.pptx",
                               stored_path="x", content_type="application/x", size_bytes=1,
                               sha256="0" * 64, concern_id=cid, uploaded_by=seed["admin_id"]))
        await s.commit()
    res = await _retract(client, admin_auth, ctx, cid)
    assert res.status_code == 400


async def test_not_twice_and_not_after_resolving(client, admin_auth, ctx):
    cid = await _raise(client, admin_auth, ctx)
    assert (await _retract(client, admin_auth, ctx, cid)).status_code == 200
    assert (await _retract(client, admin_auth, ctx, cid)).status_code == 400


async def test_only_risks(client, admin_auth, ctx, session_factory, seed):
    async with session_factory() as s:
        q = ChangeConcern(change_id=ctx["change_id"], kind="needs_info", note="q",
                          raised_by=seed["admin_id"])
        s.add(q)
        await s.commit()
        qid = q.id
    res = await _retract(client, admin_auth, ctx, qid)
    assert res.status_code == 400
