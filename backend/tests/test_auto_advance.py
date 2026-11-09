"""Assessment & costing runs on its own (Christoph 2026-11-09): once every
department with an assessment row submitted it and every department that owes
a costing input finalized it (or said no cost), the change moves to Quote
creation without a PM button; a guard still holds it."""
import json

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeChangelog, ChangeRequest
from app.models.change_cost import DepartmentRate
from app.models.entities import Project
from app.models.workflow import Department, UserDepartment
from app.services import auto_advance
from tests.conftest import login

pytestmark = [pytest.mark.asyncio, pytest.mark.auto_advance]

NOTHING_IMPACTED = {"impacts": [{"key": "cycle_time", "answer": "no",
                                 "impacted": False}]}
IMPACTED = {"impacts": [{"key": "cycle_time", "answer": "yes", "impacted": True}]}


async def _make(session_factory, seed, *, status="costing", extra_rows=(),
                tool_verdict="feasible"):
    """A customer change: Tool Engineer submitted feasible with an impact
    (owes costing), Packaging submitted 'nothing impacted' (owes nothing).
    extra_rows: (department name, stage, letter, submitted)."""
    from datetime import datetime, timedelta
    async with session_factory() as s:
        depts = {}
        for name in ("Tool Engineer", "Packaging Engineer", "Development", "Project Manager"):
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        project = await s.get(Project, seed["project_id"])
        for d in depts.values():
            s.add(DepartmentRate(department_id=d, plant_id=project.plant_id,
                                 hourly_rate=65.0, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-AUTO-1", title="auto", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"],
            customer_relevant=True, status=status,
            required_by_date=datetime(2026, 12, 31))
        s.add(change)
        await s.flush()
        # a minute back: this WSL clock steps back ~7.5 s now and then (seen
        # 2026-11-09 night), and a submit stamped 'now' could then land after the
        # finalize / booking the test makes next (flaky 1-3 of 10 runs)
        now = datetime.utcnow() - timedelta(minutes=1)
        rows = [("Tool Engineer", 1, "R", tool_verdict, IMPACTED, True),
                ("Packaging Engineer", 1, "R", "feasible", NOTHING_IMPACTED, True)]
        rows += [(n, st, l, "feasible" if sub else "pending", NOTHING_IMPACTED if sub else None, sub)
                 for n, st, l, sub in extra_rows]
        for name, stage, letter, verdict, details, sub in rows:
            s.add(ChangeAssessment(
                change_id=change.id, department_id=depts[name], stage_order=stage,
                rasic_letter=letter, verdict=verdict,
                status="submitted" if sub else "pending",
                submitted_at=now if sub else None,
                details=json.dumps(details) if details else None))
        await s.commit()
        return {"change_id": change.id, **depts}


async def _member(client, session_factory, seed, dept_id, email):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                 email=email, full_name=email, role="engineer",
                 hashed_password=get_password_hash("member-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return await login(client, email)


async def _finalize_tool(client, session_factory, seed, ids, email, dept="Tool Engineer"):
    tool = await _member(client, session_factory, seed, ids[dept], email)
    res = await client.post(
        f"/api/v1/changes/{ids['change_id']}/costing/positions",
        json={"department_id": ids[dept], "label": "Tool rework",
              "kind": "external", "quantity": 1, "quantity_unit": "pcs",
              "est_cost": 100.0, "basis_ref": "Hasco figure 12 Oct 2026"},
        headers=tool)
    assert res.status_code == 201, res.text
    res = await client.post(
        f"/api/v1/changes/{ids['change_id']}/costing/positions",
        json={"department_id": ids[dept], "kind": "support_effort",
              "label": "Implementation support (h)", "hours": 0}, headers=tool)
    assert res.status_code == 201, res.text
    res = await client.post(
        f"/api/v1/changes/{ids['change_id']}/costing/departments/"
        f"{ids[dept]}/finalize", headers=tool)
    assert res.status_code == 200, res.text


async def _status(session_factory, change_id):
    async with session_factory() as s:
        return (await s.get(ChangeRequest, change_id)).status


async def test_last_finalize_moves_the_change_to_quote_creation(
        client, session_factory, seed):
    ids = await _make(session_factory, seed)
    await _finalize_tool(client, session_factory, seed, ids, "auto-tool1@test.io")
    assert await _status(session_factory, ids["change_id"]) == "quoting"
    async with session_factory() as s:
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == ids["change_id"],
            ChangeChangelog.action == "auto_advanced"))).scalars().all()
        assert [e.action_description for e in log] == [auto_advance.TEXT_QUOTING]
        status_rows = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == ids["change_id"],
            ChangeChangelog.action == "status_changed"))).scalars().all()
        assert [e.action_description for e in status_rows] == ["costing -> quoting"]


async def test_one_open_row_of_a_later_stage_holds_the_move(
        client, admin_auth, session_factory, seed):
    # Development consulted in stage 2 has not answered yet
    ids = await _make(session_factory, seed,
                      extra_rows=[("Development", 2, "C", False)])
    await _finalize_tool(client, session_factory, seed, ids, "auto-tool2@test.io")
    assert await _status(session_factory, ids["change_id"]) == "costing"
    st = (await client.get(f"/api/v1/changes/{ids['change_id']}/stage-state",
                           headers=admin_auth)).json()["auto_advance"]
    assert (st["done"], st["total"], st["ready"]) == (2, 3, False), st
    assert [(o["department_name"], o["open"]) for o in st["open"]] == [
        ("Development", "assessment")]


async def test_costing_still_open_is_named(client, admin_auth, session_factory, seed):
    ids = await _make(session_factory, seed)
    st = (await client.get(f"/api/v1/changes/{ids['change_id']}/stage-state",
                           headers=admin_auth)).json()["auto_advance"]
    assert (st["done"], st["total"], st["to"]) == (1, 2, "quoting")
    assert [(o["department_name"], o["open"]) for o in st["open"]] == [
        ("Tool Engineer", "costing")]


async def test_a_guard_holds_the_move_and_says_why(client, admin_auth, session_factory, seed):
    # every answer is in, but one is "not feasible": the hop to costing is
    # held by its guard, nothing moves, the cockpit names the rule
    ids = await _make(session_factory, seed, status="in_assessment",
                      tool_verdict="not_feasible")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, ids["change_id"])
        assert await auto_advance.maybe_advance(s, change, seed["admin_id"]) is None
    moved = []
    async with session_factory() as s:
        moved = await auto_advance.run_after(s, ids["change_id"], seed["admin_id"])
    assert moved == []
    assert await _status(session_factory, ids["change_id"]) == "in_assessment"
    st = (await client.get(f"/api/v1/changes/{ids['change_id']}/stage-state",
                           headers=admin_auth)).json()["auto_advance"]
    assert st["to"] == "costing"
    assert "not feasible" in st["held_by"]


async def test_full_assessment_runs_through_costing_into_quote_creation(
        session_factory, seed):
    # in assessment, every answer in and nothing owed: both hops at once
    ids = await _make(session_factory, seed, status="in_assessment")
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == ids["change_id"],
            ChangeAssessment.department_id == ids["Tool Engineer"]))).scalar_one()
        a.details = json.dumps(NOTHING_IMPACTED)
        await s.commit()
    async with session_factory() as s:
        moved = await auto_advance.run_after(s, ids["change_id"], seed["admin_id"])
    assert moved == ["costing", "quoting"]
    assert await _status(session_factory, ids["change_id"]) == "quoting"


async def test_switched_off_nothing_moves(monkeypatch, client, session_factory, seed):
    monkeypatch.setattr(auto_advance, "ON", False)
    ids = await _make(session_factory, seed)
    await _finalize_tool(client, session_factory, seed, ids, "auto-tool3@test.io")
    assert await _status(session_factory, ids["change_id"]) == "costing"


async def test_project_manager_owes_costing_and_holds_the_move(
        client, admin_auth, session_factory, seed):
    """Christoph 2026-11-09: the PM books its hours and estimates its time
    still to come, and finalizes: the move waits for it, also
    while its row sits on stage 2 and has no feasible answer."""
    ids = await _make(session_factory, seed,
                      extra_rows=[("Project Manager", 2, "R", False)])
    detail = (await client.get(f"/api/v1/changes/{ids['change_id']}",
                               headers=admin_auth)).json()
    assert ids["Project Manager"] in detail["costing_owed_department_ids"]
    assert ids["Project Manager"] in detail["costing_pending_department_ids"]
    # the PM answered its row: still its costing open
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == ids["change_id"],
            ChangeAssessment.department_id == ids["Project Manager"]))).scalar_one()
        a.status, a.verdict = "submitted", "feasible"
        from datetime import datetime, timedelta
        a.submitted_at = datetime.utcnow() - timedelta(minutes=1)  # clock steps, see _make
        await s.commit()
    await _finalize_tool(client, session_factory, seed, ids, "auto-tool4@test.io")
    assert await _status(session_factory, ids["change_id"]) == "costing"
    st = (await client.get(f"/api/v1/changes/{ids['change_id']}/stage-state",
                           headers=admin_auth)).json()["auto_advance"]
    assert [(o["department_name"], o["open"]) for o in st["open"]] == [
        ("Project Manager", "costing")]
    pm = await _member(client, session_factory, seed, ids["Project Manager"], "auto-pm@test.io")
    res = await client.post(
        f"/api/v1/changes/{ids['change_id']}/costing/departments/"
        f"{ids['Project Manager']}/finalize", headers=pm)
    assert res.status_code == 400
    assert "PM time still to come" in res.json()["detail"]
    res = await client.post(
        f"/api/v1/changes/{ids['change_id']}/costing/positions",
        json={"department_id": ids["Project Manager"], "kind": "support_effort",
              "label": "PM time still to come, estimated (h): offer, implementation, release", "hours": 6},
        headers=pm)
    assert res.status_code == 201, res.text
    res = await client.post(
        f"/api/v1/changes/{ids['change_id']}/costing/departments/"
        f"{ids['Project Manager']}/finalize", headers=pm)
    assert res.status_code == 200, res.text
    assert await _status(session_factory, ids["change_id"]) == "quoting"


async def test_internal_change_pm_owes_nothing(client, admin_auth, session_factory, seed):
    ids = await _make(session_factory, seed,
                      extra_rows=[("Project Manager", 2, "R", False)])
    async with session_factory() as s:
        c = await s.get(ChangeRequest, ids["change_id"])
        c.customer_relevant = False
        await s.commit()
    detail = (await client.get(f"/api/v1/changes/{ids['change_id']}",
                               headers=admin_auth)).json()
    assert ids["Project Manager"] not in detail["costing_owed_department_ids"]


async def test_pm_rows_scoping_and_costing_effort_from_the_bookings(session_factory, seed):
    """Christoph 2026-11-09: the PM's 'Scoping effort' is its time booked
    during capture and scoping; 'Costing effort' what it booked in
    assessment and costing."""
    from app.models.change_cost import CostingPosition
    from app.models.change_impl import ImplementationBooking
    from app.services.hours_service import HoursService
    ids = await _make(session_factory, seed,
                      extra_rows=[("Project Manager", 2, "R", False)])
    pm = ids["Project Manager"]
    async with session_factory() as s:
        for status, h in (("captured", 1.0), ("scoping", 2.5), ("in_assessment", 1.5),
                          ("costing", 0.5)):
            s.add(ImplementationBooking(change_id=ids["change_id"], department_id=pm,
                                        hours=h, booked_by=seed["admin_id"],
                                        status_at_booking=status))
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, ids["change_id"])
        await HoursService.sync_assessment_effort(s, change, pm, seed["admin_id"])
        await s.commit()
        rows = {p.label: p.hours for p in (await s.execute(select(CostingPosition).where(
            CostingPosition.change_id == ids["change_id"],
            CostingPosition.department_id == pm))).scalars()}
    assert rows == {HoursService.PM_SCOPING_LABEL: 3.5,
                    HoursService.COSTING_EFFORT_LABEL: 2.0}


async def test_pm_books_scoping_effort_from_its_row_while_in_costing(
        client, session_factory, seed):
    """Christoph 2026-11-09 night: the PM's 'Scoping effort' Book hours
    (scoping=true) lands on Scoping effort even when the change is in
    costing; a plain booking then lands on Costing effort. Only the PM's
    row, only before the offer."""
    from app.models.change_cost import CostingPosition
    from app.services.hours_service import HoursService
    ids = await _make(session_factory, seed,
                      extra_rows=[("Project Manager", 2, "R", False)])
    pm = await _member(client, session_factory, seed, ids["Project Manager"],
                       "auto-pm-scoping@test.io")
    url = f"/api/v1/changes/{ids['change_id']}/hours"
    res = await client.post(url, json={"department_id": ids["Project Manager"],
                                       "hours": 2, "scoping": True}, headers=pm)
    assert res.status_code == 201, res.text
    res = await client.post(url, json={"department_id": ids["Project Manager"],
                                       "hours": 1}, headers=pm)
    assert res.status_code == 201, res.text
    phases = sorted((b["hours"], b["phase"]) for b in res.json()["bookings"])
    assert phases == [(1, "costing"), (2, "scoping")]
    async with session_factory() as s:
        rows = {p.label: p.hours for p in (await s.execute(select(CostingPosition).where(
            CostingPosition.change_id == ids["change_id"],
            CostingPosition.department_id == ids["Project Manager"]))).scalars()}
    assert rows == {HoursService.PM_SCOPING_LABEL: 2.0,
                    HoursService.COSTING_EFFORT_LABEL: 1.0}
    # another department cannot book 'scoping'
    tool = await _member(client, session_factory, seed, ids["Tool Engineer"],
                         "auto-tool-scoping@test.io")
    res = await client.post(url, json={"department_id": ids["Tool Engineer"],
                                       "hours": 1, "scoping": True}, headers=tool)
    assert res.status_code == 400
    assert "Project Manager" in res.json()["detail"]


async def test_pm_costing_counts_in_x_of_y_without_a_counted_row(
        monkeypatch, client, admin_auth, session_factory, seed):
    """2026-11-09 night (CR-33): the PM's only rows are the excluded cost
    review and the quote stage; its owed costing still holds the hop and must
    be one of the X of Y and named as open (it showed 'all finished')."""
    ids = await _make(session_factory, seed,
                      extra_rows=[("Project Manager", 2, "R", False)])
    real = auto_advance.counted_rows

    async def without_pm(session, change):
        return [a for a in await real(session, change)
                if a.department_id != ids["Project Manager"]]
    monkeypatch.setattr(auto_advance, "counted_rows", without_pm)
    await _finalize_tool(client, session_factory, seed, ids, "auto-tool9@test.io")
    assert await _status(session_factory, ids["change_id"]) == "costing"
    st = (await client.get(f"/api/v1/changes/{ids['change_id']}/stage-state",
                           headers=admin_auth)).json()["auto_advance"]
    assert [(o["department_name"], o["open"]) for o in st["open"]] == [
        ("Project Manager", "costing")]
    assert st["ready"] is False and st["done"] == st["total"] - 1


async def test_an_engine_noted_consulted_row_does_not_hold_the_move(
        client, session_factory, seed):
    """DECIDED BY CLAUDE (night 2026-11-09, CR-33): a C row whose engine task
    is 'noted' and not actionable has no submit path and no task; it counts
    as done. A C row without such a task still holds (all rows count)."""
    from app.models.workflow import WfInstance, WfInstanceTask, WfTemplate
    ids = await _make(session_factory, seed,
                      extra_rows=[("Development", 2, "C", False)])
    async with session_factory() as s:
        tmpl = WfTemplate(name="auto-noted", version=1, is_active=True,
                          created_by=seed["admin_id"])
        s.add(tmpl); await s.flush()
        inst = WfInstance(template_id=tmpl.id, change_id=ids["change_id"], status="active",
                          current_stage_order=2, started_by=seed["admin_id"])
        s.add(inst); await s.flush()
        task = WfInstanceTask(instance_id=inst.id, stage_order=2,
                              department_id=ids["Development"], rasic_letter="C",
                              status="noted", is_actionable=False)
        s.add(task); await s.flush()
        row = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == ids["change_id"],
            ChangeAssessment.department_id == ids["Development"]))).scalar_one()
        row.wf_instance_task_id = task.id
        await s.commit()
    await _finalize_tool(client, session_factory, seed, ids, "auto-tool11@test.io")
    assert await _status(session_factory, ids["change_id"]) == "quoting"
