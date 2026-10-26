"""The project team dialog's Save (Christoph 2026-10-26): drag and drop edits
a draft, PUT /projects/{id}/team/batch stores it in one step (all or
nothing), and every person newly named Responsible or Backup gets one
notice per save, mailed (team_assigned is in ecr_mail MAIL_KINDS); a person
taken off gets a "no longer" notice in PLM only. Plus the red marker's
count: GET /projects/team-gaps."""
import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from app.services import ecr_mail
from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _people(session_factory, seed):
    """Development: Dana, Ben, Carl; Quality: Dana, Quinn; Tooling: nobody."""
    async with session_factory() as s:
        dev = Department(name="Development", flow_type="action", is_active=True, sort_order=1)
        qual = Department(name="Quality", flow_type="action", is_active=True, sort_order=2)
        empty = Department(name="Tooling", flow_type="action", is_active=True, sort_order=3)
        s.add_all([dev, qual, empty]); await s.flush()
        ids = {}
        for name in ("Dana", "Ben", "Carl", "Quinn"):
            u = User(organization_id=seed["org_id"], username=name.lower(),
                     email=f"{name.lower()}@test.io", full_name=name,
                     hashed_password=get_password_hash("x-secret-123"),
                     role="engineer", is_active=True, mfa_enabled=False)
            s.add(u); await s.flush(); ids[name] = u.id
        for n in ("Dana", "Ben", "Carl"):
            s.add(UserDepartment(user_id=ids[n], department_id=dev.id))
        for n in ("Dana", "Quinn"):
            s.add(UserDepartment(user_id=ids[n], department_id=qual.id))
        await s.commit()
        return ids, dev.id, qual.id, empty.id


async def _notes(s, kind):
    return (await s.execute(select(Notification).where(Notification.kind == kind)
                            .order_by(Notification.user_id))).scalars().all()


async def test_save_stores_the_draft_and_tells_each_person_once(client, session_factory, seed):
    ids, dev, qual, _ = await _people(session_factory, seed)
    admin = await login(client, "admin@test.io")
    url = f"/api/v1/projects/{seed['project_id']}/team/batch"
    res = await client.put(url, headers=admin, json={"slots": [
        {"department_id": dev, "responsible_id": ids["Dana"], "backup_id": ids["Ben"]},
        {"department_id": qual, "responsible_id": ids["Dana"], "backup_id": None}]})
    assert res.status_code == 200, res.text
    dev_row = next(r for r in res.json() if r["department_id"] == dev)
    assert dev_row["responsible"]["id"] == ids["Dana"] and dev_row["backup"]["id"] == ids["Ben"]
    async with session_factory() as s:
        got = await _notes(s, "team_assigned")
        # one per person per save, both of Dana's slots in one notice
        assert sorted(n.user_id for n in got) == sorted([ids["Dana"], ids["Ben"]])
        dana = next(n for n in got if n.user_id == ids["Dana"])
        assert "Responsible for Development" in dana.title
        assert "Responsible for Quality" in dana.title
        assert "proj Project" in dana.title and dana.link == f"/projects/{seed['project_id']}"
        ben = next(n for n in got if n.user_id == ids["Ben"])
        assert ben.title.startswith("You are Backup for Development")
        # mailed through the ECR mail path (it is an immediate kind)
        assert all(ecr_mail.mailable(n) for n in got)

    # change: Carl responsible, Dana off Development (still Quality)
    res = await client.put(url, headers=admin, json={"slots": [
        {"department_id": dev, "responsible_id": ids["Carl"], "backup_id": ids["Ben"]}]})
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert [n.user_id for n in await _notes(s, "team_assigned")
                if n.user_id == ids["Carl"]] == [ids["Carl"]]
        # Ben's slot did not change: no second notice
        assert len([n for n in await _notes(s, "team_assigned") if n.user_id == ids["Ben"]]) == 1
        gone = await _notes(s, "team_removed")
        assert [n.user_id for n in gone] == [ids["Dana"]]
        assert "no longer" in gone[0].title and not ecr_mail.mailable(gone[0])


async def test_save_is_all_or_nothing_and_checks_membership(client, session_factory, seed):
    ids, dev, qual, _ = await _people(session_factory, seed)
    admin = await login(client, "admin@test.io")
    url = f"/api/v1/projects/{seed['project_id']}/team/batch"
    # Quinn is no Development member: the whole save is refused
    res = await client.put(url, headers=admin, json={"slots": [
        {"department_id": qual, "responsible_id": ids["Quinn"]},
        {"department_id": dev, "responsible_id": ids["Quinn"]}]})
    assert res.status_code == 400 and "Development" in res.json()["detail"]
    # the same person in both slots is refused
    res = await client.put(url, headers=admin, json={"slots": [
        {"department_id": dev, "responsible_id": ids["Ben"], "backup_id": ids["Ben"]}]})
    assert res.status_code == 400
    async with session_factory() as s:
        assert (await s.execute(select(ProjectResponsible))).scalars().all() == []
        assert await _notes(s, "team_assigned") == []


async def test_save_needs_pm_or_admin(client, session_factory, seed):
    ids, dev, _, _ = await _people(session_factory, seed)
    eng = await login(client, "eng@test.io")
    res = await client.put(f"/api/v1/projects/{seed['project_id']}/team/batch", headers=eng,
                           json={"slots": [{"department_id": dev, "responsible_id": ids["Ben"]}]})
    assert res.status_code == 403


async def test_team_gaps_count_open_responsible_slots_only(client, session_factory, seed):
    ids, dev, qual, _ = await _people(session_factory, seed)
    admin = await login(client, "admin@test.io")
    gaps = (await client.get("/api/v1/projects/team-gaps", headers=admin)).json()
    # Development and Quality have members and no responsible; Tooling has nobody
    assert gaps == {str(seed["project_id"]): 2}
    await client.put(f"/api/v1/projects/{seed['project_id']}/team/batch", headers=admin,
                     json={"slots": [{"department_id": dev, "responsible_id": None,
                                      "backup_id": ids["Ben"]},
                                     {"department_id": qual, "responsible_id": ids["Quinn"]}]})
    # a backup alone is still a gap; Quality is filled
    gaps = (await client.get("/api/v1/projects/team-gaps", headers=admin)).json()
    assert gaps == {str(seed["project_id"]): 1}


async def test_a_slot_pointing_to_a_former_member_is_flagged(client, session_factory, seed):
    ids, dev, _, _ = await _people(session_factory, seed)
    admin = await login(client, "admin@test.io")
    await client.put(f"/api/v1/projects/{seed['project_id']}/team/batch", headers=admin,
                     json={"slots": [{"department_id": dev, "responsible_id": ids["Carl"],
                                      "backup_id": ids["Ben"]}]})
    async with session_factory() as s:
        (await s.get(User, ids["Carl"])).is_active = False
        await s.delete(await s.get(UserDepartment, (ids["Ben"], dev)))
        await s.commit()
    rows = (await client.get(f"/api/v1/projects/{seed['project_id']}/team", headers=admin)).json()
    row = next(r for r in rows if r["department_id"] == dev)
    assert row["responsible"] is None and row["responsible_missing"]["name"] == "Carl"
    assert row["backup"] is None and row["backup_missing"]["name"] == "Ben"
