"""Department heads (migration 151, Christoph 2026-10-26: "give heads like
Russ or Holmes a banner or a headline"):

- an admin names / clears a department's head, an active member of it
  (400 otherwise, 404 for an unknown department); non-admins 403;
- head and manager are independent (same person or not);
- the overview carries head_id / head_name / head_email and warns (red)
  when the head is inactive or no longer a member, never when unset.
"""
import pytest
from sqlalchemy import delete, select

from app.models.entities import AuditLog, User
from app.models.workflow import Department, UserDepartment
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio


async def _row(client, headers, dept_id):
    rows = (await client.get("/api/v1/departments/overview", headers=headers)).json()
    return next(r for r in rows if r["id"] == dept_id)


async def test_admin_sets_and_clears_the_head(client, session_factory, seed):
    dept_id = await make_department_member(session_factory, seed["engineer_id"], "Manufacturing Engineer")
    admin = await login(client, "admin@test.io")
    res = await client.put(f"/api/v1/departments/{dept_id}/head", headers=admin,
                           json={"user_id": seed["engineer_id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["head_id"], body["head_name"], body["head_email"]) == (
        seed["engineer_id"], "Engineer", "eng@test.io")
    assert body["manager_id"] is None     # head is not the manager
    assert not {w["code"] for w in body["warnings"]} & {"head_inactive", "head_not_member"}
    # everyone reads it on the overview
    eng = await login(client, "eng@test.io")
    assert (await _row(client, eng, dept_id))["head_name"] == "Engineer"
    async with session_factory() as s:
        logged = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "department", AuditLog.action == "head_set"))).scalars().all()
        assert len(logged) == 1
    res = await client.put(f"/api/v1/departments/{dept_id}/head", headers=admin,
                           json={"user_id": None})
    assert res.status_code == 200
    assert (res.json()["head_id"], res.json()["head_name"]) == (None, None)


async def test_head_and_manager_are_independent(client, session_factory, seed):
    dept_id = await make_department_member(session_factory, seed["engineer_id"], "Process Engineer")
    admin = await login(client, "admin@test.io")
    for path in ("head", "manager"):
        res = await client.put(f"/api/v1/departments/{dept_id}/{path}", headers=admin,
                               json={"user_id": seed["engineer_id"]})
        assert res.status_code == 200, res.text
    res = await client.put(f"/api/v1/departments/{dept_id}/manager", headers=admin,
                           json={"user_id": None})
    assert res.json()["head_id"] == seed["engineer_id"] and res.json()["manager_id"] is None


async def test_head_must_be_an_active_member(client, session_factory, seed):
    async with session_factory() as s:
        d = Department(name="Logistics", flow_type="action", is_active=True)
        s.add(d)
        await s.flush()
        s.add(UserDepartment(user_id=seed["inactive_id"], department_id=d.id))
        await s.commit()
    admin = await login(client, "admin@test.io")
    res = await client.put(f"/api/v1/departments/{d.id}/head", headers=admin,
                           json={"user_id": seed["engineer_id"]})          # no member
    assert res.status_code == 400 and res.json()["detail"] == \
        "The head must be an active member of Logistics"
    res = await client.put(f"/api/v1/departments/{d.id}/head", headers=admin,
                           json={"user_id": seed["inactive_id"]})          # member, inactive
    assert res.status_code == 400
    res = await client.put("/api/v1/departments/9999/head", headers=admin,
                           json={"user_id": seed["admin_id"]})
    assert res.status_code == 404


async def test_only_admins_set_the_head(client, session_factory, seed):
    dept_id = await make_department_member(session_factory, seed["engineer_id"], "Development")
    eng = await login(client, "eng@test.io")
    res = await client.put(f"/api/v1/departments/{dept_id}/head", headers=eng,
                           json={"user_id": seed["engineer_id"]})
    assert res.status_code == 403, res.text
    async with session_factory() as s:
        assert (await s.get(Department, dept_id)).head_id is None


async def test_overview_warns_when_the_head_left_or_turned_inactive(client, session_factory, seed):
    dept_id = await make_department_member(session_factory, seed["engineer_id"], "Tool Engineer")
    admin = await login(client, "admin@test.io")
    codes = lambda r: {w["code"] for w in r["warnings"]}  # noqa: E731
    # unset head: no warning
    assert not codes(await _row(client, admin, dept_id)) & {"head_inactive", "head_not_member"}
    assert (await client.put(f"/api/v1/departments/{dept_id}/head", headers=admin,
                             json={"user_id": seed["engineer_id"]})).status_code == 200
    # the head leaves the department (AdminPanel role removed)
    async with session_factory() as s:
        await s.execute(delete(UserDepartment).where(UserDepartment.department_id == dept_id))
        await s.commit()
    row = await _row(client, admin, dept_id)
    assert "head_not_member" in codes(row) and row["head_name"] == "Engineer"
    assert next(w for w in row["warnings"] if w["code"] == "head_not_member")["level"] == "red"
    # back in, but inactive
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept_id))
        (await s.get(User, seed["engineer_id"])).is_active = False
        await s.commit()
    row = await _row(client, admin, dept_id)
    assert "head_inactive" in codes(row) and "head_not_member" not in codes(row)
