"""Per-department costing pipeline (live ECR test, 2026-10-14): a department
that submitted a feasible assessment owing a cost input costs and finalizes
its own figures while the change is still in assessment."""
import json

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import DepartmentRate
from app.models.entities import Project
from app.models.workflow import Department, UserDepartment
from tests.conftest import login, ready_to_finalize

pytestmark = pytest.mark.asyncio

NOTHING_IMPACTED = {"impacts": [{"key": "cycle_time", "answer": "no",
                                 "impacted": False}]}
IMPACTED = {"impacts": [{"key": "cycle_time", "answer": "yes", "impacted": True}]}


@pytest.fixture
async def early(session_factory, seed):
    """A change in assessment: Tool Engineer submitted feasible with an
    impact, Development has not answered yet, Packaging said nothing is
    impacted."""
    async with session_factory() as s:
        tool = Department(name="Tool Engineer", flow_type="action", is_active=True)
        dev = Department(name="Development", flow_type="action", is_active=True)
        pack = Department(name="Packaging Engineer", flow_type="action", is_active=True)
        s.add_all([tool, dev, pack])
        await s.flush()
        project = await s.get(Project, seed["project_id"])
        for dept in (tool, dev, pack):
            s.add(DepartmentRate(department_id=dept.id, plant_id=project.plant_id,
                                 hourly_rate=65.0, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-EC-1", title="early costing", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"],
            status="in_assessment")
        s.add(change)
        await s.flush()
        rows = {}
        for dept, verdict, details in (
                (tool, "feasible", IMPACTED), (dev, "pending", None),
                (pack, "feasible", NOTHING_IMPACTED)):
            a = ChangeAssessment(change_id=change.id, department_id=dept.id,
                                 stage_order=1, verdict=verdict,
                                 details=json.dumps(details) if details else None)
            s.add(a)
            await s.flush()
            rows[dept.name] = a.id
        await s.commit()
        return {"change_id": change.id, "tool": tool.id, "dev": dev.id,
                "pack": pack.id, "assessments": rows,
                "plant": project.plant_id}


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


async def _add_position(client, auth, early, dept, **body):
    # ECR-solid §4 (C25): an estimate names its basis to be finalized
    payload = {"department_id": dept, "label": "Tool rework", "kind": "external", "quantity": 1, "quantity_unit": "pcs",
               "est_cost": 100.0, "basis_ref": "Hasco figure 12 Oct 2026", **body}
    return await client.post(
        f"/api/v1/changes/{early['change_id']}/costing/positions",
        json=payload, headers=auth)


def _url(early, dept, what):
    return (f"/api/v1/changes/{early['change_id']}/costing/departments/"
            f"{dept}/{what}")


async def _detail(client, auth, early):
    return (await client.get(f"/api/v1/changes/{early['change_id']}",
                             headers=auth)).json()


async def test_submitted_department_costs_and_finalizes_during_assessment(
        client, admin_auth, session_factory, seed, early):
    tool = await _member(client, session_factory, seed, early["tool"], "ec-tool@test.io")
    res = await _add_position(client, tool, early, early["tool"])
    assert res.status_code == 201, res.text

    detail = await _detail(client, admin_auth, early)
    assert detail["costing_owed_department_ids"] == [early["tool"]]
    assert detail["costing_pending_department_ids"] == [early["tool"]]

    await ready_to_finalize(session_factory, early["change_id"], early["tool"])
    res = await client.post(_url(early, early["tool"], "finalize"), headers=tool)
    assert res.status_code == 200, res.text
    assert res.json() == {"owed_department_ids": [early["tool"]],
                          "finalized_department_ids": [early["tool"]],
                          "pending_department_ids": []}
    # finalized: the department's own figures are closed to its members
    assert (await _add_position(client, tool, early, early["tool"])).status_code == 403
    lead = await client.post(f"/api/v1/changes/{early['change_id']}/cost-lead-time",
                             json={"department_id": early["tool"], "lead_time_days": 3},
                             headers=tool)
    assert lead.status_code == 400, lead.text
    # PM / admin still fix any department's lines
    assert (await _add_position(client, admin_auth, early, early["tool"])).status_code == 201
    # twice is refused
    assert (await client.post(_url(early, early["tool"], "finalize"),
                              headers=tool)).status_code == 400

    # the department reopens its own input: draft again, writable again
    res = await client.post(_url(early, early["tool"], "reopen"),
                            json={"reason": "vendor sent a new quote"}, headers=tool)
    assert res.status_code == 200, res.text
    assert res.json()["pending_department_ids"] == [early["tool"]]
    assert (await _add_position(client, tool, early, early["tool"])).status_code == 201


async def test_unanswered_and_nothing_impacted_departments_owe_no_early_costing(
        client, admin_auth, session_factory, seed, early):
    dev = await _member(client, session_factory, seed, early["dev"], "ec-dev@test.io")
    pack = await _member(client, session_factory, seed, early["pack"], "ec-pack@test.io")
    assert (await _add_position(client, dev, early, early["dev"])).status_code == 403
    assert (await _add_position(client, pack, early, early["pack"])).status_code == 403
    res = await client.post(_url(early, early["dev"], "finalize"), headers=dev)
    assert res.status_code == 400
    assert "feasible" in res.json()["detail"]
    res = await client.post(_url(early, early["pack"], "finalize"), headers=pack)
    assert res.status_code == 400
    assert "owes no costing" in res.json()["detail"]
    # another department may not finalize yours
    res = await client.post(_url(early, early["tool"], "finalize"), headers=dev)
    assert res.status_code == 403


async def test_costing_input_task_appears_right_after_the_submit(
        client, session_factory, seed, early):
    tool = await _member(client, session_factory, seed, early["tool"], "ec-tool2@test.io")
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=tool)).json()
    mine = [t for t in tasks if t["kind"] == "costing_input"
            and t["change_id"] == early["change_id"]]
    assert [t["department_id"] for t in mine] == [early["tool"]]


async def test_finalized_departments_stay_finalized_into_costing(
        client, admin_auth, session_factory, seed, early):
    tool = await _member(client, session_factory, seed, early["tool"], "ec-tool3@test.io")
    assert (await _add_position(client, tool, early, early["tool"])).status_code == 201
    await ready_to_finalize(session_factory, early["change_id"], early["tool"])
    assert (await client.post(_url(early, early["tool"], "finalize"),
                              headers=tool)).status_code == 200
    async with session_factory() as s:
        c = await s.get(ChangeRequest, early["change_id"])
        c.status = "costing"
        dev = await s.get(ChangeAssessment, early["assessments"]["Development"])
        dev.verdict = "not_feasible"
        await s.commit()
    detail = await _detail(client, admin_auth, early)
    # every department that owes has finalized: costing is complete at once
    assert detail["costing_pending_department_ids"] == []
    assert detail["costing_finalized_department_ids"] == [early["tool"]]
    # Christoph 2026-11-08: who finalized, and when, for the PM overview
    info = detail["costing_finalized_info"][str(early["tool"])]
    assert info["at"] and info["by_name"]
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.get_change(s, early["change_id"])
        missing = await ChangeService.next_step_missing(s, change)
        assert "costing_input" not in [i["key"] for i in missing["items"]]


async def test_superseded_assessments_take_the_finalization_with_them(
        client, admin_auth, session_factory, seed, early):
    """Back to scoping after a 'not feasible': the rows go, and with them the
    finalization; the department's positions stay as its draft."""
    tool = await _member(client, session_factory, seed, early["tool"], "ec-tool4@test.io")
    assert (await _add_position(client, tool, early, early["tool"])).status_code == 201
    await ready_to_finalize(session_factory, early["change_id"], early["tool"])
    assert (await client.post(_url(early, early["tool"], "finalize"),
                              headers=tool)).status_code == 200
    from app.services import early_costing
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.get_change(s, early["change_id"])
        await ChangeRoutingService.teardown_routing(s, change, seed["admin_id"])
        await s.commit()
    async with session_factory() as s:
        change = await ChangeService.get_change(s, early["change_id"])
        assert early_costing.finalized_department_ids(change) == []
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == early["change_id"]))).scalars().all()
        assert rows == []
    positions = (await client.get(
        f"/api/v1/changes/{early['change_id']}/costing/positions",
        headers=admin_auth)).json()
    # the tool line and the support hours line (0 h) finalize asked for
    assert sorted(p["kind"] for p in positions) == ["external", "support_effort"]


async def test_costing_closed_refuses_finalize_and_reopen(
        client, admin_auth, session_factory, seed, early):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, early["change_id"])
        c.status = "quoting"
        await s.commit()
    assert (await client.post(_url(early, early["tool"], "finalize"),
                              headers=admin_auth)).status_code == 400
    res = await client.post(_url(early, early["tool"], "reopen"), headers=admin_auth)
    assert res.status_code == 400
    assert "reopen costing" in res.json()["detail"]
