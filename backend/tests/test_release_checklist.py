"""Stage 10: the release checklist and the lessons-learned step.

Pinned here: the 16 catalog items show with their owner
departments (decision 2026-09-26: APQP confirms the process stable alone, the
Tool Engineer answers the cycle time, Quality and Process Engineer own none),
retired answers stay readable and uncounted; 'na' needs a note; only the owner department, PM, the lead or
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
                     "Scheduling", "Sales", "Quality", "Process Engineer"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in (("dev", "Development"), ("tool", "Tool Engineer"),
                          ("pm", "Project Manager"), ("quality", "Quality"),
                          ("process", "Process Engineer"), ("apqp", "APQP")):
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


async def _check(client, auth, cid, key, status, note=None, **extra):
    body = {"status": status, **extra}
    if note is not None:
        body["note"] = note
    return await client.post(f"/api/v1/changes/{cid}/release/checks/{key}",
                             json=body, headers=auth)


def _answer(key):
    """The extra fields a plain 'done' needs on this item."""
    return {"outcome": "unchanged"} if key == "cycle_time_tool" else {}


async def test_sixteen_checks_seeded_with_owners(client, rel_world):
    pm = await _auth(client, "pm")
    st = await _state(client, pm, rel_world["change_id"])
    assert len(st["checks"]) == 16 and st["open_count"] == 16
    by_key = {c["key"]: c for c in st["checks"]}
    assert by_key["index_updated"]["department_name"] == "Development"
    assert by_key["index_updated"]["department_id"] == rel_world["depts"]["Development"]
    assert by_key["erp_updated"]["department_name"] == "Scheduling"
    # no Packaging Engineer department in this database: owner by name only
    assert by_key["packaging_updated"]["department_id"] is None
    assert by_key["packaging_updated"]["department_name"] == "Packaging Engineer"
    assert "41.5" in by_key["weight_measured"]["hint"]
    assert st["can_release"] is False
    assert "Release checklist incomplete: 16 open" in st["blockers"]
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
    assert res.json()["open_count"] == 14
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
    assert "Release checklist incomplete: 16 open" in res.json()["detail"]
    st = await _state(client, pm, cid)
    for c in st["checks"]:
        res = await _check(client, pm, cid, c["key"], "done", **_answer(c["key"]))
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
    assert st["open_count"] == 15


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
        assert (await _check(client, pm, cid, c["key"], "done",
                             **_answer(c["key"]))).status_code == 200
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


async def test_apqp_tool_engineer_and_process_engineer_rows(client, rel_world):
    """Decision 2026-09-26 (corrected the same day): APQP confirms the
    process stable, alone, and owns surface, technical quality,
    measurements, PPAP with the customer approval and the control plan; the
    cycle time comes from the Tool Engineer. The Process Engineer works in
    the PDB and owns no release row; neither do Quality and Manufacturing
    Engineer."""
    cid = rel_world["change_id"]
    process, apqp, tool = (await _auth(client, "process"), await _auth(client, "apqp"),
                           await _auth(client, "tool"))
    st = await _state(client, process, cid)
    by_key = {c["key"]: c for c in st["checks"]}
    owners = {}
    for c in st["checks"]:
        owners.setdefault(c["department_name"], []).append(c["key"])
    assert owners["Tool Engineer"] == [
        "equipment_updated", "weight_measured", "cycle_time_tool"]
    assert owners["APQP"] == [
        "process_stable_apqp", "surface_quality", "technical_quality",
        "parts_measured", "customer_approval", "control_plan"]
    for nobody in ("Process Engineer", "Quality", "Manufacturing Engineer"):
        assert nobody not in owners
    for gone in ("process_parameters", "process_fmea", "documents_updated",
                 "cycle_time_confirmed", "quality_samples", "quality_control_plan",
                 "cycle_time", "process_stable_pe"):
        assert gone not in by_key
    assert by_key["cycle_time_tool"]["label"] == (
        "Cycle time: changed (new value entered) or confirmed unchanged")
    assert by_key["cycle_time_tool"]["value_kind"] == "cycle_time"
    assert by_key["cycle_time_tool"]["department_id"] == rel_world["depts"]["Tool Engineer"]
    assert by_key["process_stable_apqp"]["label"] == "Process stable: SPC Cm > 1.67"
    assert by_key["process_stable_apqp"]["value_kind"] == "cm"
    assert by_key["process_stable_apqp"]["hint"] is None
    assert by_key["parts_measured"]["label"] == (
        "Measurements confirmed, measurement report on file")
    assert by_key["customer_approval"]["label"] == (
        "PPAP / initial sample documentation complete, customer approval "
        "received (ISIR / PSW)")
    assert by_key["control_plan"]["label"] == "Control plan / inspection plan updated"
    assert by_key["surface_quality"]["department_id"] == rel_world["depts"]["APQP"]
    assert not any(c["retired"] for c in st["checks"])
    # the Process Engineer answers nothing; the first version's keys are gone
    assert (await _check(client, process, cid, "process_stable_apqp", "done")).status_code == 403
    assert (await _check(client, process, cid, "cycle_time_tool", "done",
                         outcome="unchanged")).status_code == 403
    for old in ("cycle_time", "process_stable_pe"):
        res = await _check(client, process, cid, old, "done")
        assert res.status_code == 400 and "no longer" in res.json()["detail"]
    # APQP alone makes the process stable
    res = await _check(client, apqp, cid, "process_stable_apqp", "done", value=1.85)
    assert res.status_code == 200, res.text
    assert next(c for c in res.json()["checks"]
                if c["key"] == "process_stable_apqp")["note"] == "Cm 1.85"
    assert res.json()["open_count"] == 15
    # the Tool Engineer answers the cycle time
    assert (await _check(client, apqp, cid, "cycle_time_tool", "done",
                         outcome="unchanged")).status_code == 403
    res = await _check(client, tool, cid, "cycle_time_tool", "done", outcome="unchanged")
    assert res.status_code == 200, res.text
    assert res.json()["open_count"] == 14


async def test_cycle_time_answer_carries_the_value(client, rel_world):
    cid = rel_world["change_id"]
    tool = await _auth(client, "tool")
    key = "cycle_time_tool"
    for extra in ({}, {"outcome": "maybe"}, {"outcome": "changed"},
                  {"outcome": "changed", "value": 0},
                  {"outcome": "changed", "value": 0.04},   # rounds to 0.0 s
                  {"outcome": "unchanged", "value": 40}):
        res = await _check(client, tool, cid, key, "done", **extra)
        assert res.status_code == 400, (extra, res.text)
    res = await _check(client, tool, cid, key, "done", "new gripper",
                       outcome="changed", value=38.46)
    assert res.status_code == 200, res.text
    row = next(c for c in res.json()["checks"] if c["key"] == key)
    # seconds are kept to one decimal: the note says what was stored
    assert row["note"] == "Changed: new cycle time 38.5 s. new gripper"
    res = await _check(client, tool, cid, key, "done", outcome="changed",
                       value=1234567.0)
    row = next(c for c in res.json()["checks"] if c["key"] == key)
    assert row["note"] == "Changed: new cycle time 1234567 s"
    res = await _check(client, tool, cid, key, "done", outcome="unchanged")
    row = next(c for c in res.json()["checks"] if c["key"] == key)
    assert row["note"] == "Confirmed unchanged"
    # n.a. takes a reason, not a value; plain items take no value
    assert (await _check(client, tool, cid, key, "na", "x",
                         value=3)).status_code == 400
    pm = await _auth(client, "pm")
    assert (await _check(client, pm, cid, "erp_updated", "done",
                         value=3)).status_code == 400
    log = [e for e in (await client.get(f"/api/v1/changes/{cid}/changelog",
                                        headers=pm)).json()
           if e["action"] == "release_check"]
    assert any("38.5" in str(e.get("new_value")) and "38.46" not in str(e.get("new_value"))
               and "changed" in str(e.get("new_value")) for e in log)


async def test_cm_must_be_above_the_limit(client, rel_world):
    cid = rel_world["change_id"]
    apqp = await _auth(client, "apqp")
    res = await _check(client, apqp, cid, "process_stable_apqp", "done", value=1.67)
    assert res.status_code == 400 and "1.67" in res.json()["detail"]
    # checked as stored: 1.6700001 is kept as 1.67, which is not above 1.67
    res = await _check(client, apqp, cid, "process_stable_apqp", "done", value=1.6700001)
    assert res.status_code == 400 and "Cm 1.67 is not above" in res.json()["detail"]
    assert (await _check(client, apqp, cid, "process_stable_apqp", "done",
                         outcome="changed")).status_code == 400
    res = await _check(client, apqp, cid, "process_stable_apqp", "done", value=1.854)
    assert res.status_code == 200, res.text
    row = next(c for c in res.json()["checks"] if c["key"] == "process_stable_apqp")
    assert row["note"] == "Cm 1.85"
    res = await _check(client, apqp, cid, "process_stable_apqp", "done", "SPC chart on file")
    assert res.status_code == 200
    row = next(c for c in res.json()["checks"] if c["key"] == "process_stable_apqp")
    assert row["note"] == "SPC chart on file"


async def test_cycle_time_hint_reads_the_tool_engineers_validation(
        client, rel_world, session_factory):
    from app.models.change_validation import ValidationCheck
    cid = rel_world["change_id"]
    pm = await _auth(client, "pm")
    async with session_factory() as s:
        # measured under the older catalog by the Process Engineer: not shown
        s.add(ValidationCheck(change_id=cid, check_key="cycle_time", status="passed",
                              value=41.0, department_id=rel_world["depts"]["Process Engineer"]))
        await s.commit()
    row = next(c for c in (await _state(client, pm, cid))["checks"]
               if c["key"] == "cycle_time_tool")
    assert row["hint"] is None
    async with session_factory() as s:
        s.add(ValidationCheck(change_id=cid, check_key="cycle_time", status="passed",
                              value=39.5, department_id=rel_world["depts"]["Tool Engineer"]))
        await s.commit()
    row = next(c for c in (await _state(client, pm, cid))["checks"]
               if c["key"] == "cycle_time_tool")
    assert row["hint"] == "Measured in validation by the Tool Engineer: 39.5 s"


async def test_retired_answers_stay_readable(client, rel_world, session_factory):
    """Rows answered before the rework read with their old words, owner and
    answer, read-only and not counted; a reopened one has nothing to show."""
    from datetime import datetime
    from app.models.change_validation import ChangeReleaseCheck
    cid = rel_world["change_id"]
    async with session_factory() as s:
        for key, status, dept in (("process_fmea", "done", "Process Engineer"),
                                  ("quality_samples", "na", "Quality"),
                                  ("cycle_time_confirmed", "done", None),
                                  ("documents_updated", "open", "APQP"),
                                  # the first version of the 2026-09-26 rework
                                  ("cycle_time", "done", "Process Engineer"),
                                  ("process_stable_pe", "done", "Process Engineer")):
            s.add(ChangeReleaseCheck(
                change_id=cid, check_key=key, status=status,
                note="kept" if status == "na" else None,
                department_id=rel_world["depts"].get(dept),
                checked_by=rel_world["users"]["pm"] if status != "open" else None,
                checked_at=datetime(2026, 9, 20) if status != "open" else None))
        await s.commit()
    pm = await _auth(client, "pm")
    st = await _state(client, pm, cid)
    retired = [c for c in st["checks"] if c["retired"]]
    assert [c["key"] for c in retired] == [
        "cycle_time_confirmed", "cycle_time", "process_stable_pe",
        "process_fmea", "quality_samples"]
    by_key = {c["key"]: c for c in retired}
    assert by_key["process_fmea"]["label"] == "Process FMEA updated"
    assert by_key["process_fmea"]["by_name"] == "Rel pm"
    assert by_key["quality_samples"]["department_name"] == "Quality"
    assert by_key["quality_samples"]["note"] == "kept"
    assert by_key["cycle_time_confirmed"]["department_name"] == "Manufacturing Engineer"
    assert by_key["cycle_time"]["department_name"] == "Process Engineer"
    assert by_key["process_stable_pe"]["label"] == (
        "Process stable: SPC Cm > 1.67 (Process Engineer)")
    assert by_key["process_stable_pe"]["hint"] is None
    assert len(st["checks"]) == 21 and st["open_count"] == 16
    assert "Release checklist incomplete: 16 open" in st["blockers"]
    res = await _check(client, pm, cid, "process_fmea", "open")
    assert res.status_code == 400 and "no longer" in res.json()["detail"]
    # the Tool Engineer's cycle-time row is open next to the retired one
    open_row = next(c for c in st["checks"] if c["key"] == "cycle_time_tool")
    assert open_row["status"] == "open" and not open_row["retired"]


async def test_change_released_before_the_cutoff_keeps_its_checklist(
        client, rel_world, session_factory, monkeypatch):
    from datetime import datetime
    from app.services import release_checklist as catalog
    monkeypatch.delenv(catalog.RELEASE_ROWS_SINCE_ENV, raising=False)
    cid = rel_world["change_id"]
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status, c.released_at = "released", datetime(2026, 6, 1)
        await s.commit()
    st = await _state(client, await _auth(client, "pm"), cid)
    by_key = {c["key"]: c for c in st["checks"]}
    assert set(catalog.RETIRED_ORIGINAL) <= set(by_key)
    assert by_key["cycle_time_confirmed"]["label"] == "Cycle time confirmed in series production"
    assert not any(c["retired"] for c in st["checks"])
    for key in ("cycle_time", "cycle_time_tool", "process_stable_pe", "process_fmea"):
        assert key not in by_key
    # relabelled items read with the words they were asked with
    assert by_key["parts_measured"]["label"] == "Parts measured, measurement report on file"
    assert by_key["customer_approval"]["label"] == (
        "Customer approval received (PPAP / ISIR / PSW)")


async def test_open_change_reads_the_new_labels(client, rel_world):
    st = await _state(client, await _auth(client, "pm"), rel_world["change_id"])
    by_key = {c["key"]: c for c in st["checks"]}
    assert by_key["parts_measured"]["label"] == (
        "Measurements confirmed, measurement report on file")


@pytest.mark.parametrize("status,stamp,ended,shown", [
    ("released", "released_at", "2026-06-01", False),  # released before the rows existed
    ("closed", "released_at", "2026-06-01", False),
    ("released", None, None, False),                    # legacy release without a stamp
    ("cancelled", None, None, False),                   # legacy end without a stamp
    ("cancelled", "cancelled_at", "2026-06-01", False),
    ("rejected", "rejected_at", "2026-06-01", False),
    # ended without a release AFTER the cutoff: the new checklist
    ("cancelled", "cancelled_at", "2026-09-27T10:00:00", True),
    ("rejected", "rejected_at", "2026-09-27T10:00:00", True),
    ("closed", "closed_at", "2026-09-27T10:00:00", True),  # closed, never released
    # the default cutoff is 2026-09-26 04:00 UTC (midnight New York)
    ("released", "released_at", "2026-09-26T03:59:59", False),  # 23:59 EDT on the 25th
    ("released", "released_at", "2026-09-26T04:00:00", True),   # released after: they belong
    ("in_implementation", None, None, True),            # still open: they belong
])
async def test_new_rows_do_not_reach_back_into_finished_changes(
        client, rel_world, session_factory, monkeypatch, status, stamp, ended, shown):
    from datetime import datetime
    from app.services import release_checklist as catalog
    from app.services.release_service import ReleaseService
    monkeypatch.delenv(catalog.RELEASE_ROWS_SINCE_ENV, raising=False)
    cid = rel_world["change_id"]
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = status
        c.released_at = None
        if stamp:
            setattr(c, stamp, datetime.fromisoformat(ended))
        await s.commit()
    st = await _state(client, await _auth(client, "pm"), cid)
    keys = {c["key"] for c in st["checks"]}
    assert (set(catalog.ADDED_LATER) <= keys) is shown
    assert not (set(catalog.ADDED_LATER) & keys) or shown
    assert len(st["checks"]) == (16 if shown else 13)
    # the retired items of the first catalog belong to the old changes only
    assert (set(catalog.RETIRED_ORIGINAL) <= keys) is (not shown)
    async with session_factory() as s:
        n = await ReleaseService.open_count(s, await s.get(ChangeRequest, cid))
    assert n == (16 if shown else 13)


async def test_answered_new_row_stays_on_a_finished_change(client, rel_world, session_factory):
    from datetime import datetime
    cid = rel_world["change_id"]
    apqp = await _auth(client, "apqp")
    assert (await _check(client, apqp, cid, "control_plan", "done")).status_code == 200
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status, c.released_at = "released", datetime(2026, 6, 1)
        await s.commit()
    st = await _state(client, await _auth(client, "pm"), cid)
    keys = [c["key"] for c in st["checks"]]
    assert "control_plan" in keys and "surface_quality" not in keys


async def test_release_rows_since_default_and_env_override():
    from datetime import datetime
    from app.services import release_checklist as catalog
    assert catalog.release_rows_since({}) == datetime(2026, 9, 26, 4, 0)
    assert catalog.release_rows_since({"PLM_RELEASE_ROWS_SINCE": " "}) == \
        datetime(2026, 9, 26, 4, 0)
    # no offset: UTC
    assert catalog.release_rows_since(
        {"PLM_RELEASE_ROWS_SINCE": "2026-09-27T14:30:00"}) == datetime(2026, 9, 27, 14, 30)
    # Z and offsets are converted to naive UTC
    assert catalog.release_rows_since(
        {"PLM_RELEASE_ROWS_SINCE": "2026-09-27T14:30:00Z"}) == datetime(2026, 9, 27, 14, 30)
    assert catalog.release_rows_since(
        {"PLM_RELEASE_ROWS_SINCE": "2026-09-27T10:30:00-04:00"}) == \
        datetime(2026, 9, 27, 14, 30)
    # garbage: the default stands
    assert catalog.release_rows_since({"PLM_RELEASE_ROWS_SINCE": "tomorrow"}) == \
        datetime(2026, 9, 26, 4, 0)


async def test_applies_follows_the_env_cutoff(monkeypatch):
    from datetime import datetime, timezone
    from app.services import release_checklist as catalog
    monkeypatch.setenv("PLM_RELEASE_ROWS_SINCE", "2026-10-01T12:00:00Z")
    key = "control_plan"
    # released after the default but before the deploy moment: out
    assert not catalog.applies(key, "released", datetime(2026, 9, 30))
    assert catalog.applies(key, "released", datetime(2026, 10, 1, 12, 0))
    # an aware stamp is compared in UTC
    assert catalog.applies(key, "closed",
                           datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
    assert not catalog.applies(key, "closed",
                               datetime(2026, 10, 1, 11, 59, tzinfo=timezone.utc))
    # open changes, answered rows and original rows are never cut
    assert catalog.applies(key, "validation", None)
    assert catalog.applies(key, "released", datetime(2026, 1, 1), answered=True)
    assert catalog.applies("index_updated", "released", datetime(2026, 1, 1))


async def test_env_cutoff_reaches_the_release_state(
        client, rel_world, session_factory, monkeypatch):
    from datetime import datetime
    cid = rel_world["change_id"]
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status, c.released_at = "released", datetime(2026, 9, 30)
        await s.commit()
    pm = await _auth(client, "pm")
    monkeypatch.delenv("PLM_RELEASE_ROWS_SINCE", raising=False)
    assert len((await _state(client, pm, cid))["checks"]) == 16
    monkeypatch.setenv("PLM_RELEASE_ROWS_SINCE", "2026-10-01T12:00:00Z")
    assert len((await _state(client, pm, cid))["checks"]) == 13


async def test_change_finished_on_the_first_version_keeps_its_rows(
        client, rel_world, session_factory, monkeypatch):
    """A change released (and closed) while the first version of the
    2026-09-26 rework was live answered the Process Engineer's cycle time
    and process-stable rows. It keeps that checklist: those rows stay
    counted as answered, and the Tool Engineer's cycle-time row that
    replaced them is never added, so no open row appears on it."""
    from datetime import datetime
    from app.models.change_validation import ChangeReleaseCheck
    from app.services import release_checklist as catalog
    from app.services.release_service import ReleaseService
    monkeypatch.delenv(catalog.RELEASE_ROWS_SINCE_ENV, raising=False)
    cid = rel_world["change_id"]
    async with session_factory() as s:
        for key in catalog.CHECK_KEYS + ["cycle_time", "process_stable_pe"]:
            if key == "cycle_time_tool":
                continue
            dept = catalog.owner_for(key)
            s.add(ChangeReleaseCheck(
                change_id=cid, check_key=key, status="done",
                department_id=rel_world["depts"].get(dept),
                checked_by=rel_world["users"]["pm"],
                checked_at=datetime(2026, 9, 26, 10, 0)))
        c = await s.get(ChangeRequest, cid)
        c.status = "closed"
        c.released_at = datetime(2026, 9, 26, 11, 0)     # after the cutoff
        c.closed_at = datetime(2026, 9, 26, 12, 0)
        await s.commit()
    st = await _state(client, await _auth(client, "pm"), cid)
    by_key = {c["key"]: c for c in st["checks"]}
    assert "cycle_time_tool" not in by_key
    assert by_key["cycle_time"]["retired"] is False
    assert by_key["cycle_time"]["department_name"] == "Process Engineer"
    assert by_key["process_stable_pe"]["retired"] is False
    assert st["open_count"] == 0 and len(st["checks"]) == 17
    async with session_factory() as s:
        assert await ReleaseService.open_count(s, await s.get(ChangeRequest, cid)) == 0
    # the same rows on a change still running: read-only, the new row open
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status, c.released_at, c.closed_at = "in_validation", None, None
        await s.commit()
    st = await _state(client, await _auth(client, "pm"), cid)
    by_key = {c["key"]: c for c in st["checks"]}
    assert by_key["cycle_time"]["retired"] is True
    assert by_key["process_stable_pe"]["retired"] is True
    assert by_key["cycle_time_tool"]["status"] == "open"
    assert st["open_count"] == 1


async def test_closed_after_a_rejection_ends_at_its_rejection():
    """A change rejected, then closed later, ended when it was rejected: the
    close stamp is only the fallback when no earlier end is on file."""
    from datetime import datetime
    from types import SimpleNamespace
    from app.services.release_checklist import ended_at
    rejected, closed = datetime(2026, 6, 1), datetime(2026, 9, 30)
    c = SimpleNamespace(status="closed", released_at=None, rejected_at=rejected,
                        cancelled_at=None, closed_at=closed)
    assert ended_at(c) == rejected
    c.rejected_at, c.cancelled_at = None, datetime(2026, 7, 1)
    assert ended_at(c) == datetime(2026, 7, 1)
    c.cancelled_at = None
    assert ended_at(c) == closed
    c.released_at = datetime(2026, 5, 1)
    assert ended_at(c) == datetime(2026, 5, 1)


async def test_change_detail_carries_the_release_and_close_dates(
        client, rel_world, session_factory):
    """Re-check walk P3-6: the release summary reads the release date as the
    actual finish when plan tasks were never marked done."""
    from datetime import datetime
    cid = rel_world["change_id"]
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status, c.released_at = "closed", datetime(2026, 10, 16, 9, 0)
        c.closed_at = datetime(2026, 10, 20, 9, 0)
        await s.commit()
    res = await client.get(f"/api/v1/changes/{cid}", headers=await _auth(client, "pm"))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["released_at"].startswith("2026-10-16")
    assert body["closed_at"].startswith("2026-10-20")
