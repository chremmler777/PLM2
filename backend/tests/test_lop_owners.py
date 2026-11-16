"""Project LOP: a line has one main owner (the responsible person) and may
have additional owners. Department, lateness and escalation stay with the
main owner; additional owners see the line as theirs and can report it done."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.entities import User
from app.models.notification import Notification
from app.services.lop_digest import digest_for
from app.services.lop_service import _today

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


def _lines(pid):
    return f"{BASE}/projects/{pid}/lines"


async def _task(client, auth, p, **kw):
    body = {"title": "Warm measurement", "department_id": p.apqp_id,
            "due_date": (_today() + timedelta(days=10)).isoformat()}
    body.update(kw)
    r = await client.post(_lines(p.id), headers=auth, json=body)
    return r


async def _mine(client, auth):
    return {x["id"]: x for x in (await client.get(f"{BASE}/mine", headers=auth)).json()}


async def test_a_task_gets_a_main_owner_and_additional_owners(client, pm_auth, sales_auth, quality_auth, lop_project):
    r = await _task(client, pm_auth, lop_project, additional_owner_ids=[lop_project.sales_user_id])
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["responsible_id"] == lop_project.quality_user_id          # main owner: from the department
    assert [o["id"] for o in b["additional_owners"]] == [lop_project.sales_user_id]
    assert b["additional_owners"][0]["name"]
    assert b["department_name"] == "APQP"                              # the department stays the main owner's
    mine_sales = await _mine(client, sales_auth)
    assert mine_sales[b["id"]]["my_role"] == "additional" and mine_sales[b["id"]]["can_report"] is True
    assert (await _mine(client, quality_auth))[b["id"]]["my_role"] == "main"


async def test_no_additional_owners_is_an_empty_list(client, pm_auth, lop_project):
    assert (await _task(client, pm_auth, lop_project)).json()["additional_owners"] == []


async def test_an_additional_owner_must_be_on_the_project_team(client, pm_auth, lop_project):
    r = await _task(client, pm_auth, lop_project, additional_owner_ids=[lop_project.outsider_id])
    assert r.status_code == 400 and "project team" in r.json()["detail"]


async def test_the_main_owner_is_not_listed_twice(client, pm_auth, lop_project):
    b = (await _task(client, pm_auth, lop_project,
                     additional_owner_ids=[lop_project.quality_user_id, lop_project.sales_user_id,
                                           lop_project.sales_user_id])).json()
    assert [o["id"] for o in b["additional_owners"]] == [lop_project.sales_user_id]


async def test_pm_changes_additional_owners_history_and_badge(client, pm_auth, lop_project, line, session_factory):
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth,
                           json={"additional_owner_ids": [lop_project.sales_user_id]})
    assert r.status_code == 200, r.text
    assert [o["id"] for o in r.json()["additional_owners"]] == [lop_project.sales_user_id]
    async with session_factory() as s:
        notes = (await s.execute(select(Notification).where(
            Notification.user_id == lop_project.sales_user_id, Notification.kind == "lop_event"))).scalars().all()
    assert len(notes) == 1 and "additional owner" in notes[0].title
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"additional_owner_ids": []})
    assert r.json()["additional_owners"] == []
    hist = [h for h in (await client.get(f"{BASE}/lines/{line}/history", headers=pm_auth)).json()
            if h.get("field") == "additional_owner"]
    assert [(h["old_value"] is None, h["new_value"] is None) for h in hist] == [(False, True), (True, False)]
    # sending the same list again changes nothing
    before = len((await client.get(f"{BASE}/lines/{line}/history", headers=pm_auth)).json())
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"additional_owner_ids": []})
    assert len((await client.get(f"{BASE}/lines/{line}/history", headers=pm_auth)).json()) == before


async def test_an_additional_owner_reports_done_but_changes_nothing_else(client, pm_auth, sales_auth, lop_project, line):
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth,
                       json={"additional_owner_ids": [lop_project.sales_user_id]})
    r = await client.patch(f"{BASE}/lines/{line}", headers=sales_auth, json={"title": "mine now"})
    assert r.status_code == 403
    r = await client.patch(f"{BASE}/lines/{line}", headers=sales_auth, json={"status": "done_check"})
    assert r.status_code == 200 and r.json()["status"] == "done_check"


async def test_someone_who_is_no_owner_cannot_report_done(client, sales_auth, line):
    r = await client.patch(f"{BASE}/lines/{line}", headers=sales_auth, json={"status": "done_check"})
    assert r.status_code == 403


async def test_an_additional_owner_who_becomes_main_owner_leaves_the_additional_list(client, pm_auth, lop_project, line):
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth,
                       json={"additional_owner_ids": [lop_project.sales_user_id]})
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth,
                           json={"responsible_id": lop_project.sales_user_id})
    assert r.json()["responsible_id"] == lop_project.sales_user_id and r.json()["additional_owners"] == []


async def test_the_project_list_carries_additional_owners(client, pm_auth, lop_project, line):
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth,
                       json={"additional_owner_ids": [lop_project.sales_user_id]})
    got = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)).json()
    ln = next(x for x in got["lines"] if x["id"] == line)
    assert [o["id"] for o in ln["additional_owners"]] == [lop_project.sales_user_id]


async def test_the_morning_mail_lists_a_line_for_its_additional_owner(client, pm_auth, lop_project, session_factory):
    b = (await _task(client, pm_auth, lop_project, additional_owner_ids=[lop_project.sales_user_id],
                     due_date=(_today() + timedelta(days=1)).isoformat())).json()
    async with session_factory() as s:
        sales = await s.get(User, lop_project.sales_user_id)
        out = await digest_for(s, sales, _today(), datetime.utcnow())
    assert out is not None and f"#{b['id']}" in out[1] and "additional owner" in out[1]
