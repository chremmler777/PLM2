"""P3 fixes from the 2026-10-26 test round (backend):
esc P3-1 digest day = business day; P3-5 one-field team PUT tells the
person; P3-6 history names departments and the changed field; P3-8 refusal
grammar; P3-7 a bare hub username reads as a mail address."""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeChangelog, ChangeRequest
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_p3_1_digest_key_is_the_business_day(session_factory, seed, monkeypatch):
    """02:30 UTC on 27 Oct is still 26 Oct in Toccoa: one digest that day."""
    from app.services import overdue_digest
    from app.core.config import get_settings
    monkeypatch.setenv("PLM_BUSINESS_TZ", "America/New_York")
    monkeypatch.setattr(get_settings(), "overdue_digest_recipients", "admin")
    seen = {}

    async def lines(session, now, viewer=None, keep=None):
        return ["C-1 late"]
    monkeypatch.setattr(overdue_digest, "overdue_lines", lines)
    async with session_factory() as s:
        await overdue_digest.send_overdue_digest(s, now=datetime(2026, 10, 27, 2, 30))
        await s.commit()
        keys = (await s.execute(select(Notification.subject_key).where(
            Notification.kind == overdue_digest.DIGEST_KIND))).scalars().all()
    assert keys and all(k == "digest:2026-10-26" for k in keys)


async def test_p3_5_one_field_team_put_tells_the_person(client, seed, session_factory):
    async with session_factory() as s:
        d = Department(name="Sales", flow_type="action", is_active=True)
        s.add(d); await s.flush()
        u = User(organization_id=seed["org_id"], username="karl", email="karl@test.io",
                 full_name="Karl L", hashed_password=get_password_hash("x-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u); await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=d.id))
        await s.commit()
        did, uid = d.id, u.id
    admin = await login(client, "admin@test.io")
    res = await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                           json={"department_id": did, "user_id": uid}, headers=admin)
    assert res.status_code == 200, res.text
    res = await client.put(f"/api/v1/projects/{seed['project_id']}/team",
                           json={"department_id": did, "user_id": None}, headers=admin)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        kinds = sorted((await s.execute(select(Notification.kind).where(
            Notification.user_id == uid))).scalars().all())
    assert kinds == ["team_assigned", "team_removed"]


async def test_p3_6_history_names_departments(session_factory, seed):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        d = Department(name="Process Engineer", flow_type="action", is_active=True)
        s.add(d); await s.flush()
        c = ChangeRequest(change_number="C-P3-1", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"])
        s.add(c); await s.flush()
        e = await ChangeService.append_changelog(
            s, c, "implementation_part_done", f"Dept {d.id}: our part done",
            seed["admin_id"])
        e2 = await ChangeService.append_changelog(
            s, c, "x", "Dept 99999: unknown stays", seed["admin_id"])
    assert e.action_description == "Process Engineer: our part done"
    assert e2.action_description == "Dept 99999: unknown stays"


async def test_p3_6_metadata_line_names_the_field(client, seed, session_factory):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-P3-2", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], status="captured")
        s.add(c); await s.commit()
        cid = c.id
    admin = await login(client, "admin@test.io")
    res = await client.patch(f"/api/v1/changes/{cid}", json={"title": "New title"},
                             headers=admin)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        lines = (await s.execute(select(ChangeChangelog.action_description).where(
            ChangeChangelog.change_id == cid,
            ChangeChangelog.action == "metadata_updated"))).scalars().all()
    assert lines == ["Change metadata updated: title"]


async def test_p3_8_who_starts_reads_project_management_starts(session_factory, seed):
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        s.add(Department(name="Project Manager", flow_type="action", is_active=True,
                         can_start_change=True))
        await s.commit()
        text = await ChangeService.who_starts_changes(s)
    assert "Project Management starts customer changes" in text


def test_p3_7_bare_username_reads_as_mail_address(monkeypatch):
    from app.core.config import get_settings
    from app.services.ecr_mail import display_address
    monkeypatch.setattr(get_settings(), "mail_default_domain", "us.ktx.group")
    assert display_address("jubei.hughes") == "jubei.hughes@us.ktx.group"
    assert display_address("a@b.io") == "a@b.io"
    monkeypatch.setattr(get_settings(), "mail_default_domain", "")
    assert display_address("jubei.hughes") == "jubei.hughes"


async def test_p3_2_another_departments_submit_and_due_date_are_403(
        client, seed, session_factory):
    from datetime import timedelta
    from app.models.change import ChangeAssessment
    from tests.conftest import make_department_member
    await make_department_member(session_factory, seed["engineer_id"], "Sales")
    async with session_factory() as s:
        d = Department(name="Quality", flow_type="action", is_active=True)
        s.add(d); await s.flush()
        c = ChangeRequest(change_number="C-P3-3", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          status="in_assessment")
        s.add(c); await s.flush()
        a = ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                             rasic_letter="C")
        s.add(a); await s.commit()
        cid, did, aid = c.id, d.id, a.id
    eng = await login(client, "eng@test.io")
    res = await client.post(f"/api/v1/changes/{cid}/assessments", headers=eng,
                            json={"department_id": did, "verdict": "feasible"})
    assert res.status_code == 403, res.text
    res = await client.put(f"/api/v1/changes/{cid}/assessments/{aid}/due-date", headers=eng,
                           json={"due_date": (datetime.utcnow() + timedelta(days=3)).isoformat()})
    assert res.status_code == 403, res.text


async def test_f13_absorbed_hours_count_in_the_estimate(session_factory, seed):
    import json
    from app.models.change import ChangeAssessment
    from app.services.hours_service import estimate_by_department
    async with session_factory() as s:
        d = Department(name="APQP", flow_type="action", is_active=True)
        s.add(d); await s.flush()
        c = ChangeRequest(change_number="C-F13", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"])
        s.add(c); await s.flush()
        s.add(ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                               rasic_letter="R", details=json.dumps(
                                   {"costing_no_cost": {"reason": "absorbed", "hours": 2}})))
        s.add(ChangeAssessment(change_id=c.id, department_id=d.id, status="active",
                               rasic_letter="C", details=json.dumps(
                                   {"costing_no_cost": {"reason": "no_work"}})))
        await s.commit()
        est = await estimate_by_department(s, [c.id])
    assert est == {(c.id, d.id): 2.0}
