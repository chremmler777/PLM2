"""Department managers for the escalation overview (migration 149,
Christoph 2026-10-26) and the Departments admin page:

- an admin names / clears a department's manager (an active user, no
  membership needed) and places people in a department; non-admins 403;
- the overdue digest goes to each manager for the departments they manage,
  the rest (no department, no active manager) to the configured recipients,
  once per person and day;
- My Tasks' "Late in my departments" lists every escalated item of the
  managed departments; nobody else gets the group;
- managing grants no write rights.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from app.services import due_rules
from app.services.overdue_digest import send_overdue_digest
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio


async def _dept(s, name, manager_id=None, active=True):
    d = Department(name=name, flow_type="action", is_active=active, manager_id=manager_id)
    s.add(d)
    await s.flush()
    return d


async def _change(s, seed, number, **kw):
    c = ChangeRequest(change_number=number, title=f"title {number}", reason="r",
                      change_type="physical_part", project_id=seed["project_id"],
                      raised_by=seed["admin_id"], **kw)
    s.add(c)
    await s.flush()
    return c


def _late(change_id, dept_id, days=5, **kw):
    return ChangeAssessment(change_id=change_id, department_id=dept_id, status="active",
                            rasic_letter="R",
                            due_date=due_rules.sub_wd(datetime.utcnow(), days), **kw)


async def _digests(s):
    return {n.user_id: n.body for n in (await s.execute(select(Notification).where(
        Notification.kind == "overdue_digest"))).scalars().all()}


# --- manager set / clear -------------------------------------------------

async def test_admin_sets_and_clears_a_manager_who_need_not_be_a_member(
        client, session_factory, seed):
    async with session_factory() as s:
        d = await _dept(s, "Tool Engineer")
        await s.commit()
    admin = await login(client, "admin@test.io")
    res = await client.put(f"/api/v1/departments/{d.id}/manager", headers=admin,
                           json={"user_id": seed["engineer_id"]})
    assert res.status_code == 200, res.text
    assert res.json()["manager_id"] == seed["engineer_id"]
    assert res.json()["manager_name"] == "Engineer"
    # the departments list everyone reads carries it
    lst = await client.get("/api/v1/workflow-templates/departments", headers=admin)
    row = next(r for r in lst.json() if r["id"] == d.id)
    assert (row["manager_id"], row["manager_name"]) == (seed["engineer_id"], "Engineer")
    # not made a member by it
    async with session_factory() as s:
        assert await s.get(UserDepartment, (seed["engineer_id"], d.id)) is None
    res = await client.put(f"/api/v1/departments/{d.id}/manager", headers=admin,
                           json={"user_id": None})
    assert res.status_code == 200 and res.json()["manager_id"] is None


async def test_one_person_manages_several_departments(client, session_factory, seed):
    async with session_factory() as s:
        ids = [(await _dept(s, n)).id for n in ("Process Engineer", "Tool Engineer")]
        await s.commit()
    admin = await login(client, "admin@test.io")
    for i in ids:
        res = await client.put(f"/api/v1/departments/{i}/manager", headers=admin,
                               json={"user_id": seed["admin_id"]})
        assert res.status_code == 200, res.text
    lst = (await client.get("/api/v1/departments/admin", headers=admin)).json()
    assert {r["id"] for r in lst if r["manager_id"] == seed["admin_id"]} == set(ids)


async def test_manager_set_refused_for_non_admin_inactive_user_unknown_department(
        client, session_factory, seed):
    await make_department_member(session_factory, seed["engineer_id"], "Development")
    async with session_factory() as s:
        d = await _dept(s, "Tool Engineer")
        await s.commit()
    eng = await login(client, "eng@test.io")
    admin = await login(client, "admin@test.io")
    res = await client.put(f"/api/v1/departments/{d.id}/manager", headers=eng,
                           json={"user_id": seed["engineer_id"]})
    assert res.status_code == 403, res.text
    res = await client.put(f"/api/v1/departments/{d.id}/manager", headers=admin,
                           json={"user_id": seed["inactive_id"]})
    assert res.status_code == 400, res.text
    res = await client.put("/api/v1/departments/9999/manager", headers=admin,
                           json={"user_id": seed["admin_id"]})
    assert res.status_code == 404
    assert (await client.get("/api/v1/departments/admin", headers=eng)).status_code == 403
    async with session_factory() as s:
        assert (await s.get(Department, d.id)).manager_id is None


# --- members / activation (the Departments page) -------------------------

async def test_admin_places_people_in_a_department(client, session_factory, seed):
    async with session_factory() as s:
        d = await _dept(s, "Process Engineer")
        await s.commit()
    admin = await login(client, "admin@test.io")
    res = await client.put(f"/api/v1/departments/{d.id}/members", headers=admin,
                           json={"user_ids": [seed["engineer_id"], seed["admin_id"]]})
    assert res.status_code == 200, res.text
    assert {m["id"] for m in res.json()["members"]} == {seed["engineer_id"], seed["admin_id"]}
    # the per-user endpoint sees the same membership
    per_user = await client.get(f"/api/v1/users/{seed['engineer_id']}/departments",
                                headers=admin)
    assert [x["id"] for x in per_user.json()] == [d.id]
    res = await client.put(f"/api/v1/departments/{d.id}/members", headers=admin,
                           json={"user_ids": [seed["admin_id"]]})
    assert [m["id"] for m in res.json()["members"]] == [seed["admin_id"]]
    # NEGATIVE: an inactive person is not added; a non-admin may not
    res = await client.put(f"/api/v1/departments/{d.id}/members", headers=admin,
                           json={"user_ids": [seed["admin_id"], seed["inactive_id"]]})
    assert res.status_code == 400, res.text
    eng = await login(client, "eng@test.io")
    res = await client.put(f"/api/v1/departments/{d.id}/members", headers=eng,
                           json={"user_ids": [seed["engineer_id"]]})
    assert res.status_code == 403


async def test_admin_activates_a_retired_department(client, session_factory, seed):
    async with session_factory() as s:
        d = await _dept(s, "Old Role", active=False)
        await s.commit()
    eng = await login(client, "eng@test.io")
    assert (await client.post(f"/api/v1/departments/{d.id}/activate",
                              headers=eng)).status_code == 403
    admin = await login(client, "admin@test.io")
    res = await client.post(f"/api/v1/departments/{d.id}/activate", headers=admin)
    assert res.status_code == 200 and res.json()["is_active"] is True


# --- overdue digest: split by manager, fallback kept ---------------------

async def test_digest_goes_to_the_manager_for_their_departments_rest_to_fallback(
        session_factory, seed, monkeypatch):
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin")
    async with session_factory() as s:
        managed = await _dept(s, "Tool Engineer", manager_id=seed["engineer_id"])
        unmanaged = await _dept(s, "Quality")
        c1 = await _change(s, seed, "C-M-1")
        c2 = await _change(s, seed, "C-M-2")
        s.add_all([_late(c1.id, managed.id), _late(c2.id, unmanaged.id),
                   # not late yet: in nobody's digest
                   ChangeAssessment(change_id=c1.id, department_id=managed.id,
                                    status="active", rasic_letter="R",
                                    due_date=datetime.utcnow() + timedelta(days=3))])
        await s.commit()
        assert await send_overdue_digest(s) == 2
        await s.commit()
        got = await _digests(s)
        assert set(got) == {seed["engineer_id"], seed["admin_id"]}
        assert "C-M-1" in got[seed["engineer_id"]] and "C-M-2" not in got[seed["engineer_id"]]
        assert "Tool Engineer assessment" in got[seed["engineer_id"]]
        # the fallback keeps what no manager reads, not the managed item
        assert "C-M-2" in got[seed["admin_id"]] and "C-M-1" not in got[seed["admin_id"]]
        # once per recipient and day
        assert await send_overdue_digest(s) == 0


async def test_manager_who_is_also_a_fallback_recipient_gets_one_digest_with_both(
        session_factory, seed, monkeypatch):
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin")
    async with session_factory() as s:
        mine = await _dept(s, "Process Engineer", manager_id=seed["admin_id"])
        other = await _dept(s, "Tool Engineer", manager_id=seed["engineer_id"])
        loose = await _dept(s, "Quality")
        c = await _change(s, seed, "C-M-3")
        s.add_all([_late(c.id, mine.id), _late(c.id, other.id), _late(c.id, loose.id)])
        await s.commit()
        await send_overdue_digest(s)
        await s.commit()
        got = await _digests(s)
        body = got[seed["admin_id"]]
        assert "Process Engineer assessment" in body and "Quality assessment" in body
        assert "Tool Engineer assessment" not in body
        assert "Tool Engineer assessment" in got[seed["engineer_id"]]
        assert len((await s.execute(select(Notification).where(
            Notification.kind == "overdue_digest",
            Notification.user_id == seed["admin_id"]))).scalars().all()) == 1


async def test_inactive_manager_falls_back_to_the_configured_recipients(
        session_factory, seed, monkeypatch):
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin")
    async with session_factory() as s:
        d = await _dept(s, "Tool Engineer", manager_id=seed["inactive_id"])
        c = await _change(s, seed, "C-M-4")
        s.add(_late(c.id, d.id))
        await s.commit()
        await send_overdue_digest(s)
        await s.commit()
        got = await _digests(s)
        assert set(got) == {seed["admin_id"]} and "C-M-4" in got[seed["admin_id"]]


async def test_manager_digest_is_org_scoped(session_factory, seed, monkeypatch):
    from app.models.entities import Organization, Plant, Project
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "")
    async with session_factory() as s:
        org = Organization(name="Other", code="other", is_active=True)
        s.add(org); await s.flush()
        plant = Plant(organization_id=org.id, name="P2", code="p2", location="US",
                      is_active=True)
        s.add(plant); await s.flush()
        proj = Project(plant_id=plant.id, name="Other project", code="op", status="active")
        s.add(proj); await s.flush()
        d = await _dept(s, "Tool Engineer", manager_id=seed["engineer_id"])
        here = await _change(s, seed, "C-M-5")
        there = ChangeRequest(change_number="C-M-6", title="t", reason="r",
                              change_type="physical_part", project_id=proj.id,
                              raised_by=seed["admin_id"])
        s.add(there); await s.flush()
        s.add_all([_late(here.id, d.id), _late(there.id, d.id)])
        await s.commit()
        await send_overdue_digest(s)
        await s.commit()
        body = (await _digests(s))[seed["engineer_id"]]
        assert "C-M-5" in body and "C-M-6" not in body


# --- My Tasks: "Late in my departments" ----------------------------------

async def test_late_in_my_departments_lists_every_late_item_of_managed_departments(
        client, session_factory, seed):
    async with session_factory() as s:
        managed = await _dept(s, "Tool Engineer", manager_id=seed["engineer_id"])
        other = await _dept(s, "Quality")
        c1 = await _change(s, seed, "C-M-7", lead_id=seed["admin_id"])
        c2 = await _change(s, seed, "C-M-8")
        s.add_all([_late(c1.id, managed.id, days=6, owner_id=seed["admin_id"]),
                   _late(c2.id, managed.id, days=3),
                   _late(c1.id, other.id),
                   ChangeAssessment(change_id=c2.id, department_id=managed.id,
                                    status="active", rasic_letter="R",
                                    due_date=datetime.utcnow() + timedelta(days=2))])
        await s.commit()
    eng = await login(client, "eng@test.io")
    res = await client.get("/api/v1/changes/my-department-escalations", headers=eng)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["departments"] == [{"id": managed.id, "name": "Tool Engineer"}]
    rows = body["items"]
    assert [r["change_number"] for r in rows] == ["C-M-7", "C-M-8"]   # most late first
    first = rows[0]
    assert first["department_name"] == "Tool Engineer"
    assert first["change_title"] == "title C-M-7"
    assert first["owner_name"] == "Admin"
    assert first["days_overdue"] >= 6 and first["due_date"]
    assert first["change_id"] == c1.id


async def test_late_in_my_departments_hidden_for_a_non_manager(client, session_factory, seed):
    async with session_factory() as s:
        d = await _dept(s, "Tool Engineer", manager_id=seed["engineer_id"])
        c = await _change(s, seed, "C-M-9")
        s.add(_late(c.id, d.id))
        await s.commit()
    admin = await login(client, "admin@test.io")     # admin, but manages nothing
    res = await client.get("/api/v1/changes/my-department-escalations", headers=admin)
    assert res.json() == {"departments": [], "items": []}


async def test_acting_admin_sees_the_real_users_managed_departments(
        client, session_factory, seed):
    async with session_factory() as s:
        d = await _dept(s, "Tool Engineer", manager_id=seed["admin_id"])
        acting = await _dept(s, "Quality")
        c = await _change(s, seed, "C-M-10")
        s.add(_late(c.id, d.id))
        await s.commit()
    admin = await login(client, "admin@test.io")
    res = await client.get("/api/v1/changes/my-department-escalations",
                           headers={**admin, "X-Acts-As-Department": str(acting.id)})
    assert res.status_code == 200, res.text
    assert [r["change_number"] for r in res.json()["items"]] == ["C-M-10"]


# --- managing grants no write rights -------------------------------------

async def test_manager_gets_no_write_rights_in_the_managed_department(
        client, session_factory, seed):
    from app.services.workflow_service import WorkflowService
    # a member elsewhere (so a writer at all), manager of Tool Engineer
    await make_department_member(session_factory, seed["engineer_id"], "Development")
    async with session_factory() as s:
        d = await _dept(s, "Tool Engineer", manager_id=seed["engineer_id"])
        c = await _change(s, seed, "C-M-11")
        a = _late(c.id, d.id)
        s.add(a)
        await s.commit()
        eng_user = await s.get(User, seed["engineer_id"])
        assert d.id not in await WorkflowService.effective_department_ids(s, eng_user)
    eng = await login(client, "eng@test.io")
    res = await client.post(f"/api/v1/changes/{c.id}/assessments/{a.id}/accept",
                            headers=eng)
    assert res.status_code == 403, res.text


# --- project team dialog: members carry their email -----------------------

async def test_project_team_members_carry_their_email(client, session_factory, seed):
    dept_id = await make_department_member(session_factory, seed["engineer_id"], "Development")
    admin = await login(client, "admin@test.io")
    res = await client.get(f"/api/v1/projects/{seed['project_id']}/team", headers=admin)
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r["department_id"] == dept_id)
    assert [(m["id"], m["email"]) for m in row["members"]] == [(seed["engineer_id"], "eng@test.io")]
