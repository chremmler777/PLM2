"""A rejected customer-relevant change is only DONE once the customer has been
told: letter on file, send confirmed, then closed. Internal rejections carry
no such debt."""
import pytest

from tests.conftest import login, satisfy_capture_gate, make_internal

pytestmark = pytest.mark.asyncio


async def _sales_auth(client, session_factory, seed, user_id=None):
    """A Sales member (the seed admin by default, so they can also reject)."""
    from sqlalchemy import select
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        dept = (await s.execute(select(Department).where(
            Department.name == "Sales"))).scalar_one_or_none()
        if dept is None:
            dept = Department(name="Sales", flow_type="action", is_active=True,
                              can_start_change=True)
            s.add(dept)
            await s.flush()
        uid = user_id or seed["admin_id"]
        if await s.get(UserDepartment, (uid, dept.id)) is None:
            s.add(UserDepartment(user_id=uid, department_id=dept.id))
        await s.commit()
        return dept.id


async def _rejected_change(client, auth, seed, title, *, customer_relevant=True):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": title, "reason": "r",
        "change_type": "physical_part", "customer_relevant": True,
    }, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    if not customer_relevant:
        # Creation is external-only for now; the internal flow is reached by
        # flipping during capture.
        await make_internal(client, auth, cid)
    # A real capture, so reopening lands back in scoping without tripping the
    # kickoff gate on the way.
    await satisfy_capture_gate(client, auth, cid)
    res = await client.post(f"/api/v1/changes/{cid}/transition", headers=auth,
                            json={"to_status": "rejected",
                                  "rejection_reason": "Not economical"})
    assert res.status_code == 200, res.text
    return cid


async def _letter(client, auth, cid, name="rejection.pdf"):
    return await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": (name, b"we are sorry", "application/pdf")},
        data={"kind": "rejection_letter"}, headers=auth)


async def _close(client, auth, cid):
    return await client.post(f"/api/v1/changes/{cid}/transition",
                             json={"to_status": "closed"}, headers=auth)


async def test_close_blocked_without_letter_then_without_confirmation(
        client, admin_auth, seed, session_factory):
    await _sales_auth(client, session_factory, seed)
    cid = await _rejected_change(client, admin_auth, seed, "needs a letter")

    res = await _close(client, admin_auth, cid)
    assert res.status_code == 400
    assert "rejection letter" in res.json()["detail"].lower()

    up = await _letter(client, admin_auth, cid)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] == "rejection_letter"

    res = await _close(client, admin_auth, cid)
    assert res.status_code == 400
    assert "confirmed as sent" in res.json()["detail"].lower()


async def test_internal_rejection_closes_freely(client, admin_auth, seed):
    cid = await _rejected_change(client, admin_auth, seed, "internal",
                                 customer_relevant=False)
    res = await _close(client, admin_auth, cid)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "closed"


async def test_rejection_sent_stamps_audits_and_closes(
        client, admin_auth, seed, session_factory):
    await _sales_auth(client, session_factory, seed)
    cid = await _rejected_change(client, admin_auth, seed, "full loop")

    # no letter yet -> refused
    res = await client.post(f"/api/v1/changes/{cid}/rejection-sent", headers=admin_auth)
    assert res.status_code == 400
    assert "rejection letter" in res.json()["detail"].lower()

    await _letter(client, admin_auth, cid)
    res = await client.post(f"/api/v1/changes/{cid}/rejection-sent", headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "closed"
    assert body["rejection_sent_at"] is not None
    assert body["rejection_sent_by"] == seed["admin_id"]

    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin_auth)).json()
    assert any(e["action"] == "rejection_sent" for e in log)

    # idempotent guard: the change is closed and the send already recorded
    res = await client.post(f"/api/v1/changes/{cid}/rejection-sent", headers=admin_auth)
    assert res.status_code == 400


async def test_only_sales_may_confirm_the_send(client, admin_auth, eng_auth, seed,
                                               session_factory):
    dept_id = await _sales_auth(client, session_factory, seed)
    cid = await _rejected_change(client, admin_auth, seed, "authz")
    await _letter(client, admin_auth, cid)

    res = await client.post(f"/api/v1/changes/{cid}/rejection-sent", headers=eng_auth)
    assert res.status_code == 403
    assert "act as Sales" in res.json()["detail"]


async def test_reopen_still_works_until_the_change_is_closed(
        client, admin_auth, seed, session_factory):
    await _sales_auth(client, session_factory, seed)
    cid = await _rejected_change(client, admin_auth, seed, "reopen me")
    res = await client.post(f"/api/v1/changes/{cid}/transition", headers=admin_auth,
                            json={"to_status": "scoping",
                                  "reopen_reason": "Customer came back"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "scoping"

    # once closed, nothing moves
    cid2 = await _rejected_change(client, admin_auth, seed, "closed for good")
    await _letter(client, admin_auth, cid2)
    await client.post(f"/api/v1/changes/{cid2}/rejection-sent", headers=admin_auth)
    res = await client.post(f"/api/v1/changes/{cid2}/transition", headers=admin_auth,
                            json={"to_status": "scoping",
                                  "reopen_reason": "too late"})
    assert res.status_code == 400
    assert "cannot move from 'closed'" in res.json()["detail"].lower()


async def test_my_tasks_send_rejection_row_reports_the_missing_half(
        client, admin_auth, seed, session_factory):
    await _sales_auth(client, session_factory, seed)
    cid = await _rejected_change(client, admin_auth, seed, "task row")

    async def row():
        res = await client.get("/api/v1/changes/my-tasks", headers=admin_auth)
        assert res.status_code == 200, res.text
        got = [t for t in res.json()
               if t["kind"] == "send_rejection" and t["change_id"] == cid]
        return got[0] if got else None

    r = await row()
    assert r is not None and r["has_letter"] is False
    assert r["project_number"] == "proj"

    await _letter(client, admin_auth, cid)
    r = await row()
    assert r is not None and r["has_letter"] is True

    await client.post(f"/api/v1/changes/{cid}/rejection-sent", headers=admin_auth)
    assert await row() is None
