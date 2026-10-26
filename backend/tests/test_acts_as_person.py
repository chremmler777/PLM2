"""Act as a PERSON (Christoph 2026-10-26): a real admin sends X-Acts-As-User
and sees PLM exactly as that person (their memberships, manager role, My
Tasks; never admin); every write is audited as the admin acting as them.
A non-admin sending the header is refused like the department header."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import AuditLog, User
from app.models.workflow import Department, UserDepartment
from app.services import due_rules
from tests.conftest import login

pytestmark = pytest.mark.asyncio

H = "X-Acts-As-User"


@pytest.fixture
async def russ(session_factory, seed):
    """Russ: Manufacturing Engineer member, manager of it; Tool Engineer exists."""
    async with session_factory() as s:
        me = Department(name="Manufacturing Engineer", flow_type="action", is_active=True)
        te = Department(name="Tool Engineer", flow_type="action", is_active=True)
        sales = Department(name="Sales", flow_type="action", is_active=True, can_start_change=True)
        s.add_all([me, te, sales]); await s.flush()
        u = User(organization_id=seed["org_id"], username="russ.addison", email="russ@test.io",
                 full_name="Russ Addison", hashed_password=get_password_hash("russ-secret-1"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u); await s.flush()
        me.manager_id = u.id
        s.add_all([UserDepartment(user_id=u.id, department_id=me.id),
                   UserDepartment(user_id=u.id, department_id=sales.id)])
        await s.commit()
        return {"id": u.id, "me": me.id, "te": te.id, "sales": sales.id}


async def test_non_admin_header_is_refused(client, seed, russ):
    from tests.conftest import make_department_member
    await make_department_member(client.session_factory, seed["engineer_id"], "Quality")
    eng = await login(client, "eng@test.io")
    res = await client.get("/api/v1/auth/me", headers={**eng, H: str(russ["id"])})
    assert res.status_code == 403


async def test_unknown_or_inactive_person_and_both_headers_are_refused(client, seed, russ):
    admin = await login(client, "admin@test.io")
    assert (await client.get("/api/v1/auth/me", headers={**admin, H: str(seed["inactive_id"])})).status_code == 400
    assert (await client.get("/api/v1/auth/me", headers={**admin, H: "999"})).status_code == 400
    both = {**admin, H: str(russ["id"]), "X-Acts-As-Department": str(russ["me"])}
    assert (await client.get("/api/v1/auth/me", headers=both)).status_code == 400


async def test_rights_are_the_persons(client, seed, russ, session_factory):
    admin = await login(client, "admin@test.io")
    me = (await client.get("/api/v1/auth/me", headers={**admin, H: str(russ["id"])})).json()
    assert me["user_id"] == russ["id"] and me["role"] == "engineer"
    assert me["acting_as_user"] == {"id": russ["id"], "name": "Russ Addison"}
    assert me["real_user"]["id"] == seed["admin_id"]
    assert me["is_real_admin"] is False
    assert me["can_edit_tools"] is False           # Russ is no Tool Engineer
    # can write a Manufacturing Engineer assessment, not a Tool Engineer one
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-P-1", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"])
        s.add(c); await s.flush()
        mine = ChangeAssessment(change_id=c.id, department_id=russ["me"], status="active",
                                rasic_letter="R", due_date=datetime.utcnow() + timedelta(days=3))
        theirs = ChangeAssessment(change_id=c.id, department_id=russ["te"], status="active",
                                  rasic_letter="R", due_date=datetime.utcnow() + timedelta(days=3))
        s.add_all([mine, theirs]); await s.commit()
    acting = {**admin, H: str(russ["id"])}
    res = await client.post(f"/api/v1/changes/{c.id}/assessments/{theirs.id}/accept", headers=acting)
    assert res.status_code == 403, res.text
    res = await client.post(f"/api/v1/changes/{c.id}/assessments/{mine.id}/accept", headers=acting)
    assert res.status_code == 200, res.text
    assert res.json()["owner_id"] == russ["id"]
    # admin-only pages refuse while acting as a person
    res = await client.put(f"/api/v1/departments/{russ['me']}/manager", headers=acting,
                           json={"user_id": None})
    assert res.status_code == 403


async def test_my_tasks_and_managed_departments_are_the_persons(client, seed, russ, session_factory):
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-P-2", title="late one", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"])
        s.add(c); await s.flush()
        s.add(ChangeAssessment(change_id=c.id, department_id=russ["me"], status="active",
                               rasic_letter="R", due_date=due_rules.sub_wd(datetime.utcnow(), 5)))
        await s.commit()
    admin = await login(client, "admin@test.io")
    acting = {**admin, H: str(russ["id"])}
    esc = (await client.get("/api/v1/changes/my-department-escalations", headers=acting)).json()
    assert [d["name"] for d in esc["departments"]] == ["Manufacturing Engineer"]
    assert [r["change_number"] for r in esc["items"]] == ["C-P-2"]
    # the admin as themselves manages nothing
    mine = (await client.get("/api/v1/changes/my-department-escalations", headers=admin)).json()
    assert mine["departments"] == []
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=acting))
    assert tasks.status_code == 200, tasks.text
    assert any(t["change_id"] == c.id and t.get("department_id") == russ["me"] for t in tasks.json())


async def test_writes_are_audited_as_the_admin_acting_as_the_person(client, seed, russ, session_factory):
    admin = await login(client, "admin@test.io")
    acting = {**admin, H: str(russ["id"])}
    res = await client.post("/api/v1/changes", headers=acting, json={
        "project_id": seed["project_id"], "title": "as russ", "reason": "r",
        "change_type": "physical_part"})
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    async with session_factory() as s:
        row = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "change", AuditLog.entity_id == cid))).scalars().first()
    assert (row.user_id, row.real_user_id, row.acting_as_department_id) == \
        (russ["id"], seed["admin_id"], None)
    entries = (await client.get("/api/v1/audit", headers=admin,
                                params={"entity_type": "change", "entity_id": cid})).json()
    e = entries[0]
    assert e["real_user_name"] == "Admin" and e["acting_as_user_name"] == "Russ Addison"


async def test_options_list_people_for_the_admin(client, seed, russ):
    admin = await login(client, "admin@test.io")
    opts = (await client.get("/api/v1/auth/acts-as/options", headers=admin)).json()
    assert {"id": russ["id"], "name": "Russ Addison"} in opts["people"]
    # still answered while acting as a person (the switcher must stay)
    opts = (await client.get("/api/v1/auth/acts-as/options",
                             headers={**admin, H: str(russ["id"])})).json()
    assert opts["people"]
