"""Stage 10: the release checklist and the lessons-learned step.

Pinned here: the 13 catalog items show with their owner
departments; 'na' needs a note; only the owner department, PM, the lead or
an admin answer an item; lessons are added by anyone on the change and the
step is completed by PM/lead/admin with at least one lesson or a reason; and
in_validation -> released refuses, in this order, on the checklist and then
on the lessons step (after the existing validation blocker).
"""
import pytest

from app.models.change import ChangeRequest
from app.models.lesson import LessonLearned
from app.models.workflow import Department, UserDepartment
from app.services.change_service import ChangeService
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def rel_world(session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        depts = {}
        for name in ("Development", "Tool Engineer", "APQP", "Project Manager",
                     "Scheduling", "Sales"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in (("dev", "Development"), ("tool", "Tool Engineer"),
                          ("pm", "Project Manager")):
            u = User(organization_id=seed["org_id"], username=f"rel-{key}",
                     email=f"rel-{key}@test.io", full_name=f"Rel {key}",
                     role="engineer",
                     hashed_password=get_password_hash("role-secret-1"),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[dept]))
            users[key] = u.id
        change = ChangeRequest(
            change_number="C-R-1", title="release me", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=users["pm"], customer_relevant=True,
            status="in_validation", validated_part_weight_g=41.5)
        s.add(change)
        await s.commit()
        return {"change_id": change.id, "users": users, "depts": depts}


async def _auth(client, key):
    return await login(client, f"rel-{key}@test.io", ENGINEER_PASSWORD)


async def _state(client, auth, cid):
    res = await client.get(f"/api/v1/changes/{cid}/release", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _check(client, auth, cid, key, status, note=None):
    body = {"status": status}
    if note is not None:
        body["note"] = note
    return await client.post(f"/api/v1/changes/{cid}/release/checks/{key}",
                             json=body, headers=auth)


async def test_thirteen_checks_seeded_with_owners(client, rel_world):
    pm = await _auth(client, "pm")
    st = await _state(client, pm, rel_world["change_id"])
    assert len(st["checks"]) == 13 and st["open_count"] == 13
    by_key = {c["key"]: c for c in st["checks"]}
    assert by_key["index_updated"]["department_name"] == "Development"
    assert by_key["index_updated"]["department_id"] == rel_world["depts"]["Development"]
    assert by_key["erp_updated"]["department_name"] == "Scheduling"
    # no Packaging Engineer department in this database: owner by name only
    assert by_key["packaging_updated"]["department_id"] is None
    assert by_key["packaging_updated"]["department_name"] == "Packaging Engineer"
    assert "41.5" in by_key["weight_measured"]["hint"]
    assert st["can_release"] is False
    assert "Release checklist incomplete: 13 open" in st["blockers"]
    assert "Lessons learned step not done" in st["blockers"]


async def test_na_needs_a_note_and_owner_rights(client, rel_world, session_factory):
    cid = rel_world["change_id"]
    dev, tool, pm = (await _auth(client, "dev"), await _auth(client, "tool"),
                     await _auth(client, "pm"))
    res = await _check(client, dev, cid, "spare_parts", "na")
    assert res.status_code == 400
    res = await _check(client, dev, cid, "spare_parts", "na", "no service parts")
    assert res.status_code == 200, res.text
    c = next(c for c in res.json()["checks"] if c["key"] == "spare_parts")
    assert (c["status"], c["note"], c["by_name"]) == ("na", "no service parts", "Rel dev")
    # not the owner
    res = await _check(client, tool, cid, "index_updated", "done")
    assert res.status_code == 403
    # PM answers anything, also items nobody owns here
    res = await _check(client, pm, cid, "packaging_updated", "done")
    assert res.status_code == 200
    assert res.json()["open_count"] == 11
    # reopening clears the signature
    res = await _check(client, pm, cid, "packaging_updated", "open")
    assert next(c for c in res.json()["checks"]
                if c["key"] == "packaging_updated")["by_name"] is None
    res = await _check(client, pm, cid, "nonsense", "done")
    assert res.status_code == 404
    # outside implementation/validation the checklist is closed
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).status = "approved"
        await s.commit()
    res = await _check(client, pm, cid, "erp_updated", "done")
    assert res.status_code == 400


async def test_lessons_add_and_complete(client, rel_world, session_factory, seed):
    cid = rel_world["change_id"]
    tool, pm = await _auth(client, "tool"), await _auth(client, "pm")
    # complete refused for non-PM, and without lessons or a reason
    res = await client.post(f"/api/v1/changes/{cid}/lessons/complete", json={},
                            headers=tool)
    assert res.status_code == 403
    res = await client.post(f"/api/v1/changes/{cid}/lessons/complete", json={},
                            headers=pm)
    assert res.status_code == 400
    res = await client.post(f"/api/v1/changes/{cid}/lessons", json={
        "title": "Order inserts earlier", "description": "Lead time ate the buffer",
        "category": "supplier", "lesson_type": "improvement", "severity": "medium",
        "recommendation": "RFQ at assessment"}, headers=tool)
    assert res.status_code == 201, res.text
    lesson = res.json()
    assert lesson["change_id"] == cid and lesson["status"] == "in_review"
    assert lesson["created_by_name"] == "Rel tool"
    async with session_factory() as s:
        row = await s.get(LessonLearned, lesson["id"])
        assert row.project_id == seed["project_id"]
    res = await client.post(f"/api/v1/changes/{cid}/lessons", json={
        "title": "x", "description": "y", "category": "bogus"}, headers=tool)
    assert res.status_code == 400
    res = await client.post(f"/api/v1/changes/{cid}/lessons/complete", json={},
                            headers=pm)
    assert res.status_code == 200, res.text
    lessons = res.json()["lessons"]
    assert lessons["done_at"] is not None and lessons["done_by_name"] == "Rel pm"
    assert [l["title"] for l in lessons["items"]] == ["Order inserts earlier"]
    log = [e["action"] for e in (await client.get(
        f"/api/v1/changes/{cid}/changelog", headers=pm)).json()]
    assert "lesson_added" in log and "lessons_completed" in log


async def test_release_guard_messages(client, rel_world, monkeypatch):
    """The checklist and lessons halves of in_validation -> released. The
    ready-to-go half (impacted revisions through their check workflows) is
    covered in test_ready_to_go.py and stubbed out here."""
    async def ready(session, change):
        return {"ready_to_go": True, "items": []}
    monkeypatch.setattr(ChangeService, "implementation_progress", staticmethod(ready))

    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")

    async def release():
        return await client.post(f"/api/v1/changes/{cid}/transition",
                                 json={"to_status": "released"}, headers=pm)

    res = await release()
    assert res.status_code == 400
    assert "Release checklist incomplete: 13 open" in res.json()["detail"]
    st = await _state(client, pm, cid)
    for c in st["checks"]:
        res = await _check(client, pm, cid, c["key"], "done")
        assert res.status_code == 200, res.text
    res = await release()
    assert res.status_code == 400
    assert "Lessons learned step not done" in res.json()["detail"]
    kinds = {a["kind"] for a in (await client.get(
        f"/api/v1/changes/{cid}/my-actions", headers=pm)).json()["actions"]}
    assert "lessons_step" in kinds
    res = await client.post(f"/api/v1/changes/{cid}/lessons/complete",
                            json={"none_reason": "routine index change"}, headers=pm)
    assert res.status_code == 200
    assert res.json()["can_release"] is True and res.json()["blockers"] == []
    res = await release()
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "released"


async def test_release_check_task_for_owner(client, rel_world):
    dev = await _auth(client, "dev")
    cid = rel_world["change_id"]
    actions = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                headers=dev)).json()["actions"]
    row = next(a for a in actions if a["kind"] == "release_check")
    assert row["target_tab"] == "release" and row["count"] == 3
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=dev)).json()
    t = next(t for t in tasks if t["kind"] == "release_check")
    assert t["open_count"] == 3 and t["department_id"] == rel_world["depts"]["Development"]


async def test_get_release_writes_nothing(client, rel_world, session_factory):
    from sqlalchemy import func, select
    from app.models.change_validation import ChangeReleaseCheck
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    await _state(client, pm, cid)
    await _state(client, pm, cid)
    async with session_factory() as s:
        n = (await s.execute(select(func.count()).select_from(ChangeReleaseCheck)
                             .where(ChangeReleaseCheck.change_id == cid))).scalar()
    assert n == 0
    # a refused answer writes nothing either; an accepted one writes its row only
    tool = await _auth(client, "tool")
    assert (await _check(client, tool, cid, "index_updated", "done")).status_code == 403
    assert (await _check(client, pm, cid, "index_updated", "done")).status_code == 200
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeReleaseCheck)
                                .where(ChangeReleaseCheck.change_id == cid))).scalars().all()
    assert [(r.check_key, r.status) for r in rows] == [("index_updated", "done")]
    assert rows[0].department_id == rel_world["depts"]["Development"]
    st = await _state(client, pm, cid)
    assert st["open_count"] == 12


async def test_timing_guard_cannot_be_bypassed_through_on_hold(session_factory, rel_world):
    """approved -> on_hold -> in_implementation used to skip 'timing
    validated'. A hold taken during implementation still resumes freely."""
    from datetime import datetime
    async with session_factory() as s:
        c = await s.get(ChangeRequest, rel_world["change_id"])
        c.status = "on_hold"
        c.impact_confirmed_at = datetime.utcnow()
        c.customer_response = "accepted"
        c.timing_validated_at = None
        await s.flush()
        await s.refresh(c, ["impacted_items", "gates"])
        assert "Timing not validated" in (
            await ChangeService._guard(s, c, "in_implementation") or "")
        # the change had been in implementation before the hold: exempt
        await ChangeService.append_changelog(
            s, c, "status_changed", "approved -> in_implementation", 1,
            field_name="status", old_value="approved", new_value="in_implementation")
        await s.flush()
        assert "Timing not validated" not in (
            await ChangeService._guard(s, c, "in_implementation") or "")
        # loop-back from validation stays exempt
        c.status = "in_validation"
        assert "Timing not validated" not in (
            await ChangeService._guard(s, c, "in_implementation") or "")


async def test_open_plan_deviations_block_the_release(client, rel_world, monkeypatch,
                                                      session_factory):
    """An open plan deviation is a decision nobody took: lock or escalate it
    before the change is released. Locked / escalated ones do not block."""
    from datetime import date
    from app.models.change_plan import ChangePlanDeviation, ChangePlanTask

    async def ready(session, change):
        return {"ready_to_go": True, "items": []}
    monkeypatch.setattr(ChangeService, "implementation_progress", staticmethod(ready))
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    async with session_factory() as s:
        t = ChangePlanTask(change_id=cid, plan="detailed", name="Tool rework",
                           start_date=date(2026, 10, 1), duration_days=5,
                           created_by=rel_world["users"]["pm"])
        s.add(t)
        await s.flush()
        for st in ("open", "open", "locked"):
            s.add(ChangePlanDeviation(
                change_id=cid, task_id=t.id, old_start=date(2026, 10, 1),
                old_end=date(2026, 10, 6), new_start=date(2026, 10, 3),
                new_end=date(2026, 10, 8), slip_days=2, reason="late steel",
                status=st, created_by=rel_world["users"]["pm"]))
        await s.commit()
    st = await _state(client, pm, cid)
    for c in st["checks"]:
        assert (await _check(client, pm, cid, c["key"], "done")).status_code == 200
    res = await client.post(f"/api/v1/changes/{cid}/lessons/complete",
                            json={"none_reason": "routine"}, headers=pm)
    msg = "2 moves with plan deviations still open: lock or escalate them first"
    assert res.json()["blockers"] == [msg] and res.json()["can_release"] is False
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "released"}, headers=pm)
    assert res.status_code == 400 and msg in res.json()["detail"]
    async with session_factory() as s:
        from sqlalchemy import update
        await s.execute(update(ChangePlanDeviation).where(
            ChangePlanDeviation.change_id == cid).values(status="escalated"))
        await s.commit()
    assert (await _state(client, pm, cid))["blockers"] == []


async def test_not_ready_to_go_is_a_blocker_on_the_release_tab(client, rel_world,
                                                               monkeypatch):
    async def pending(session, change):
        return {"ready_to_go": False,
                "items": [{"ready": False}, {"ready": True}, {"ready": False}]}
    monkeypatch.setattr(ChangeService, "implementation_progress",
                        staticmethod(pending))
    pm = await _auth(client, "pm")
    st = await _state(client, pm, rel_world["change_id"])
    assert ("Not ready to go: 2 impacted revisions have not completed their "
            "check workflow") in st["blockers"]
    assert not any("—" in b for b in st["blockers"])


async def test_release_and_close_are_pm_lead_or_admin(client, rel_world, session_factory,
                                                       admin_auth):
    cid = rel_world["change_id"]
    dev, pm = await _auth(client, "dev"), await _auth(client, "pm")

    async def move(auth, to):
        return await client.post(f"/api/v1/changes/{cid}/transition",
                                 json={"to_status": to}, headers=auth)

    res = await move(dev, "released")
    assert res.status_code == 403 and "Project Management" in res.json()["detail"]
    # PM passes the role check (and is refused on the guard instead)
    assert (await move(pm, "released")).status_code == 400
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = "released"
        await s.commit()
    assert (await move(dev, "closed")).status_code == 403
    assert (await move(admin_auth, "closed")).status_code == 200
