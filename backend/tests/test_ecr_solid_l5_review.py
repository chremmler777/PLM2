"""ECR-solid lane L5 (assessment + costing) review fixes.

Each test is a negative or a dead-end the review found: My Tasks with an
open supplier wait, money on non-price readers, check items closed without
evidence, the our-team question on an internal change, the pending
quote-vs-estimate check, and the served rights flags.
"""
import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import DepartmentRate
from app.models.entities import Project, User
from app.models.notification import Notification
from app.services import cm_switches
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio
IMPACTED = {"impacts": [{"key": "cycle_time", "answer": "yes", "impacted": True}]}


async def _user(client, session_factory, seed, key, dept=None):
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=f"l5-{key}",
                 email=f"l5-{key}@test.io", full_name=f"L5 {key}",
                 hashed_password=get_password_hash("l5-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    dept_id = (await make_department_member(session_factory, uid, dept)
               if dept else None)
    return uid, dept_id, await login(client, f"l5-{key}@test.io")


@pytest.fixture
async def cc(client, session_factory, seed):
    """A customer change in costing: Toolshop answered feasible with an
    impact and owes its costing input."""
    lead_id, _, lead = await _user(client, session_factory, seed, "lead", "Project Manager")
    dale_id, shop, dale = await _user(client, session_factory, seed, "dale", "Toolshop")
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        s.add(DepartmentRate(department_id=shop, plant_id=project.plant_id,
                             hourly_rate=65.0, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-L5-1", title="l5 costing", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=lead_id, status="costing",
            customer_relevant=True)
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=shop, stage_order=1,
                               rasic_letter="R", status="submitted",
                               verdict="feasible", details=json.dumps(IMPACTED),
                               submitted_at=datetime.utcnow()))
        await s.commit()
        cid = change.id
    return {"cid": cid, "shop": shop, "dale": dale, "dale_id": dale_id,
            "lead": lead, "lead_id": lead_id}


def _u(cid, tail=""):
    return f"/api/v1/changes/{cid}{tail}"


async def _wait(client, cid, auth, dept, **extra):
    today = date.today()
    body = {"department_id": dept, "vendor_name": "FZ",
            "asked_on": (today - timedelta(days=8)).isoformat(),
            "expected_by": (today + timedelta(days=12)).isoformat(), **extra}
    return await client.post(_u(cid, "/supplier-waits"), json=body, headers=auth)


# --- C18: My Tasks with an open supplier wait --------------------------------

async def test_my_tasks_with_a_wait_after_a_scoping_change(
        client, cc, seed, session_factory):
    """The wait hint must not depend on which other changes the list holds:
    a scoping change listed BEFORE the waiting one used to rebind the name
    the hint is built with (AttributeError, My Tasks 500)."""
    from app.services.change_service import ChangeService
    assert (await _wait(client, cc["cid"], cc["dale"], cc["shop"])).status_code == 200
    async with session_factory() as s:
        scoping = ChangeRequest(
            change_number="C-L5-S", title="in scoping", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=cc["dale_id"], lead_id=cc["dale_id"], status="scoping",
            customer_relevant=True)
        s.add(scoping)
        await s.commit()
        sid = scoping.id
    async with session_factory() as s:
        user = await s.get(User, cc["dale_id"])
        first = await s.get(ChangeRequest, sid)
        waiting = await s.get(ChangeRequest, cc["cid"])
        rows = await ChangeService.stage_tasks(s, user, [first, waiting], {cc["shop"]})
    row = next(r for r in rows if r["kind"] == "costing_input")
    assert row["waiting_on"] == "FZ" and "FZ" in row["hint"]
    res = await client.get("/api/v1/changes/my-tasks", headers=cc["dale"])
    assert res.status_code == 200, res.text
