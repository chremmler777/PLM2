"""Project LOP: weekly meeting, marks, escalation list, minutes."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.lop import LopLine, LopMeeting, LopMeetingMark
from app.models.notification import Notification
from app.services.lop_service import _today

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


def _d(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


async def _line(client, auth, project, title="Task x", **kw):
    body = {"title": title, "department_id": project.apqp_id, "due_date": _d(10)}
    body.update(kw)
    r = await client.post(f"{BASE}/projects/{project.id}/lines", headers=auth, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _start(client, auth, project):
    r = await client.post(f"{BASE}/projects/{project.id}/meetings", headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _close(client, auth, mid):
    r = await client.post(f"{BASE}/meetings/{mid}/close", headers=auth)
    assert r.status_code == 200, r.text


def _marks(m):
    return {x["line_id"]: x for x in m["marks"]}


async def _meeting(client, auth, mid):
    return (await client.get(f"{BASE}/meetings/{mid}", headers=auth)).json()


async def _escalated_ids(client, auth, project):
    r = await client.get(f"{BASE}/escalations?project_id={project.id}", headers=auth)
    assert r.status_code == 200, r.text
    return {e["line"]["id"] for e in r.json() if e["kind"] == "line"}


async def test_start_meeting_snapshots_late_and_stale(client, pm_auth, lop_project, session_factory):
    late = await _line(client, pm_auth, lop_project, "Late", due_date=_d(-3))
    ok = await _line(client, pm_auth, lop_project, "Fine")
    async with session_factory() as s:
        (await s.get(LopLine, ok)).last_update_at = datetime.utcnow() - timedelta(days=30)
        await s.commit()
    m = await _start(client, pm_auth, lop_project)
    marks = _marks(m)
    assert marks[late]["was_late"] is True and marks[late]["mark"] == "none"
    assert marks[ok]["was_late"] is False and marks[ok]["was_stale"] is True
    again = await client.post(f"{BASE}/projects/{lop_project.id}/meetings", headers=pm_auth)
    assert again.status_code == 200 and again.json()["id"] == m["id"]
    assert len(again.json()["marks"]) == len(m["marks"]) == 2
    async with session_factory() as s:
        assert len((await s.execute(select(LopMeeting))).scalars().all()) == 1
        assert len((await s.execute(select(LopMeetingMark))).scalars().all()) == 2


async def test_pinned_topic_gets_a_row_and_closed_source_does_not(
        client, pm_auth, lop_project, session_factory, seed_forms):
    from app.models.sep import SepWorkItem
    r = await client.post(f"/api/v1/sep/projects/{lop_project.id}/activate", headers=pm_auth)
    assert r.status_code == 201, r.text
    async with session_factory() as s:
        item = (await s.execute(select(SepWorkItem).where(SepWorkItem.status == "open")
                                .order_by(SepWorkItem.id))).scalars().first().id
    r = await client.post(f"{BASE}/projects/{lop_project.id}/lines/from-sep", headers=pm_auth,
                          json={"item_id": item, "due_date": _d(5)})
    assert r.status_code in (200, 201), r.text
    sep_line = r.json()["id"]
    async with session_factory() as s:
        pin = LopLine(project_id=lop_project.id, kind="pdb_topic", ref_key="77", title="Topic",
                      status="open", due_date=datetime.utcnow().date() + timedelta(days=5),
                      last_update_at=datetime.utcnow(), created_at=datetime.utcnow())
        s.add(pin)
        (await s.get(SepWorkItem, item)).status = "not_applicable"       # the source closed
        await s.commit()
        pin_id = pin.id
    m = await _start(client, pm_auth, lop_project)
    assert pin_id in _marks(m) and sep_line not in _marks(m)


async def test_editing_during_the_meeting_marks_the_line_updated(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    r = await client.patch(f"{BASE}/lines/{a}", headers=pm_auth, json={"title": "Renamed"})
    assert r.status_code == 200
    assert _marks(await _meeting(client, pm_auth, m["id"]))[a]["mark"] == "updated"
    g = await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)
    assert g.json()["meeting"] == {"id": m["id"], "held_on": m["held_on"], "open": True}


async def test_comment_marks_updated_and_new_line_gets_a_row(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    assert (await client.post(f"{BASE}/lines/{a}/comments", headers=pm_auth,
                              json={"text": "talked"})).status_code == 201
    b = await _line(client, pm_auth, lop_project, "Made in the meeting")
    marks = _marks(await _meeting(client, pm_auth, m["id"]))
    assert marks[a]["mark"] == "updated"
    assert marks[b]["mark"] == "updated" and marks[b]["was_late"] is False


async def test_moving_a_date_marks_moved(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    r = await client.patch(f"{BASE}/lines/{a}", headers=pm_auth,
                           json={"due_date": _d(20), "reason": "supplier slip"})
    assert r.status_code == 200, r.text
    await client.post(f"{BASE}/lines/{a}/comments", headers=pm_auth, json={"text": "later"})
    assert _marks(await _meeting(client, pm_auth, m["id"]))[a]["mark"] == "moved"


async def test_hand_mark_wins_and_is_pm_only(client, pm_auth, quality_auth, lop_project):
    a = await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    url = f"{BASE}/meetings/{m['id']}/marks/{a}"
    assert (await client.put(url, headers=pm_auth, json={"mark": "escalated"})).status_code == 200
    await client.patch(f"{BASE}/lines/{a}", headers=pm_auth, json={"title": "Again"})
    assert _marks(await _meeting(client, pm_auth, m["id"]))[a]["mark"] == "escalated"
    assert (await client.put(url, headers=pm_auth, json={"mark": "bogus"})).status_code == 422
    assert (await client.put(url, headers=quality_auth, json={"mark": "none"})).status_code == 403


async def test_untouched_lines_are_counted(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project, "A")
    await _line(client, pm_auth, lop_project, "B")
    await _line(client, pm_auth, lop_project, "C")
    m = await _start(client, pm_auth, lop_project)
    await client.patch(f"{BASE}/lines/{a}", headers=pm_auth, json={"title": "A2"})
    await _close(client, pm_auth, m["id"])
    g = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)).json()
    assert g["untouched"] == 2
    assert g["last_meeting"] == m["held_on"] and g["meeting"]["open"] is False


async def _reasons(client, auth, project):
    r = await client.get(f"{BASE}/escalations?project_id={project.id}", headers=auth)
    assert r.status_code == 200, r.text
    return {e["line"]["id"]: e["reason"] for e in r.json() if e["kind"] == "line"}


async def test_late_at_two_meetings_in_a_row_escalates(client, pm_auth, lop_project):
    late = await _line(client, pm_auth, lop_project, "Late", due_date=_d(-3))
    for _ in range(2):
        m = await _start(client, pm_auth, lop_project)
        await _close(client, pm_auth, m["id"])
    assert late in await _escalated_ids(client, pm_auth, lop_project)
    assert (await _reasons(client, pm_auth, lop_project))[late] == "late"


async def test_late_then_stale_escalates_as_late_or_stale(client, pm_auth, lop_project, session_factory):
    a = await _line(client, pm_auth, lop_project, "Mixed", due_date=_d(-3))
    m = await _start(client, pm_auth, lop_project)
    assert _marks(m)[a]["was_late"] is True and _marks(m)[a]["was_stale"] is False
    await _close(client, pm_auth, m["id"])
    await client.patch(f"{BASE}/lines/{a}", headers=pm_auth,
                       json={"due_date": _d(7), "reason": "new plan"})
    async with session_factory() as s:
        (await s.get(LopLine, a)).last_update_at = datetime.utcnow() - timedelta(days=30)
        await s.commit()
    m = await _start(client, pm_auth, lop_project)
    assert _marks(m)[a]["was_late"] is False and _marks(m)[a]["was_stale"] is True
    await _close(client, pm_auth, m["id"])
    assert (await _reasons(client, pm_auth, lop_project))[a] == "late_or_stale"


async def test_hand_mark_wins_over_late_twice(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project, "Late", due_date=_d(-3))
    m = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m["id"])
    m = await _start(client, pm_auth, lop_project)
    await client.put(f"{BASE}/meetings/{m['id']}/marks/{a}", headers=pm_auth, json={"mark": "escalated"})
    await _close(client, pm_auth, m["id"])
    assert (await _reasons(client, pm_auth, lop_project))[a] == "hand"


async def test_late_once_then_fixed_does_not_escalate(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project, "Late", due_date=_d(-3))
    m = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m["id"])
    await client.patch(f"{BASE}/lines/{a}", headers=pm_auth,
                       json={"due_date": _d(7), "reason": "new plan"})
    m = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m["id"])
    assert a not in await _escalated_ids(client, pm_auth, lop_project)


async def test_stale_alone_at_one_meeting_does_not_escalate(client, pm_auth, lop_project, session_factory):
    a = await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m["id"])
    async with session_factory() as s:
        (await s.get(LopLine, a)).last_update_at = datetime.utcnow() - timedelta(days=30)
        await s.commit()
    m = await _start(client, pm_auth, lop_project)
    assert _marks(m)[a]["was_stale"] is True
    await _close(client, pm_auth, m["id"])
    assert a not in await _escalated_ids(client, pm_auth, lop_project)       # fresh at meeting 1
    # the same line, still stale at a third meeting: stale at two in a row escalates
    m = await _start(client, pm_auth, lop_project)
    assert _marks(m)[a]["was_stale"] is True
    await _close(client, pm_auth, m["id"])
    assert a in await _escalated_ids(client, pm_auth, lop_project)
    assert (await _reasons(client, pm_auth, lop_project))[a] == "stale"


async def test_hand_escalated_line_is_listed_and_closed_line_is_not(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project, "A")
    b = await _line(client, pm_auth, lop_project, "B")
    m = await _start(client, pm_auth, lop_project)
    for x in (a, b):
        await client.put(f"{BASE}/meetings/{m['id']}/marks/{x}", headers=pm_auth, json={"mark": "escalated"})
    await _close(client, pm_auth, m["id"])
    assert {a, b} <= await _escalated_ids(client, pm_auth, lop_project)
    assert (await _reasons(client, pm_auth, lop_project))[a] == "hand"
    await client.patch(f"{BASE}/lines/{b}", headers=pm_auth, json={"status": "closed"})
    ids = await _escalated_ids(client, pm_auth, lop_project)
    assert a in ids and b not in ids


async def _old_meeting(session_factory, project, days_ago):
    async with session_factory() as s:
        s.add(LopMeeting(project_id=project.id, held_on=_today() - timedelta(days=days_ago),
                         closed_at=datetime.utcnow()))
        await s.commit()


async def _no_meeting_entries(client, auth, project):
    r = await client.get(f"{BASE}/escalations?project_id={project.id}", headers=auth)
    return [e for e in r.json() if e["kind"] == "no_meeting"]


async def test_no_meeting_for_ten_days_escalates_the_pm(client, pm_auth, lop_project, session_factory):
    await _line(client, pm_auth, lop_project)
    await _old_meeting(session_factory, lop_project, 11)
    out = await _no_meeting_entries(client, pm_auth, lop_project)
    assert len(out) == 1 and out[0]["project_code"] == "lop1" and out[0]["pm_name"]
    assert out[0]["project_id"] == lop_project.id and out[0]["since"] == _d(-11)


async def test_nine_days_does_not(client, pm_auth, lop_project, session_factory):
    await _line(client, pm_auth, lop_project)
    await _old_meeting(session_factory, lop_project, 9)
    assert await _no_meeting_entries(client, pm_auth, lop_project) == []


async def test_no_meeting_ever_counts_from_the_oldest_open_line(client, pm_auth, lop_project, session_factory):
    a = await _line(client, pm_auth, lop_project)
    assert await _no_meeting_entries(client, pm_auth, lop_project) == []
    async with session_factory() as s:
        (await s.get(LopLine, a)).created_at = datetime.utcnow() - timedelta(days=12)
        await s.commit()
    assert len(await _no_meeting_entries(client, pm_auth, lop_project)) == 1


async def _notes(session_factory):
    async with session_factory() as s:
        return list((await s.execute(select(Notification).where(
            Notification.kind == "lop_minutes"))).scalars().all())


async def test_minutes_go_once_to_the_team_only(client, pm_auth, lop_project, session_factory):
    await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    mid = m["id"]
    assert (await client.post(f"{BASE}/meetings/{mid}/minutes", headers=pm_auth)).status_code == 400
    await _close(client, pm_auth, mid)
    assert (await client.post(f"{BASE}/meetings/{mid}/minutes", headers=pm_auth)).status_code == 200
    notes = await _notes(session_factory)
    assert {n.user_id for n in notes} == {lop_project.pm_id, lop_project.quality_user_id,
                                          lop_project.sales_user_id}
    assert lop_project.outsider_id not in {n.user_id for n in notes}
    assert all(n.title == f"LOP minutes lop1 {m['held_on']}" for n in notes)
    assert len(notes) == 3
    assert notes[0].link == f"/projects/{lop_project.id}/lop"
    assert (await client.post(f"{BASE}/meetings/{mid}/minutes", headers=pm_auth)).status_code == 409


async def test_minutes_list_closed_new_moved_overdue_stale(client, pm_auth, lop_project, session_factory):
    from app.services.lop_meetings import minutes_text
    stale = await _line(client, pm_auth, lop_project, "Stale one")
    moved = await _line(client, pm_auth, lop_project, "Moved one")
    old = await _line(client, pm_auth, lop_project, "Old and done")
    m1 = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m1["id"])
    async with session_factory() as s:
        (await s.get(LopLine, stale)).last_update_at = datetime.utcnow() - timedelta(days=30)
        await s.commit()
    new = await _line(client, pm_auth, lop_project, "Brand new")
    late = await _line(client, pm_auth, lop_project, "Overdue one", due_date=_d(-2))
    await client.patch(f"{BASE}/lines/{moved}", headers=pm_auth,
                       json={"due_date": _d(30), "reason": "slip"})
    await client.patch(f"{BASE}/lines/{old}", headers=pm_auth, json={"status": "closed"})
    m2 = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m2["id"])
    async with session_factory() as s:
        title, body = await minutes_text(s, m2["id"])
    sections = {}
    cur = None
    for ln in body.splitlines():
        if ln.split(" (")[0] in ("Closed", "New", "Moved", "Overdue", "Stale") and "(" in ln:
            cur = ln.split(" (")[0]
            sections[cur] = []
        elif cur and ln.startswith("#"):
            sections[cur].append(int(ln.split()[0][1:]))
    assert old in sections["Closed"] and new in sections["New"] and late in sections["New"]
    assert moved in sections["Moved"] and late in sections["Overdue"] and stale in sections["Stale"]
    assert old not in sections["Overdue"] and new not in sections["Closed"]
    assert body.rstrip().endswith(f"/projects/{lop_project.id}/lop")
    assert "| APQP |" in body


async def test_only_pm_runs_the_meeting(client, pm_auth, quality_auth, outsider_auth, lop_project):
    r = await client.post(f"{BASE}/projects/{lop_project.id}/meetings", headers=quality_auth)
    assert r.status_code == 403
    m = await _start(client, pm_auth, lop_project)
    assert (await client.post(f"{BASE}/meetings/{m['id']}/close", headers=quality_auth)).status_code == 403
    assert (await client.post(f"{BASE}/meetings/{m['id']}/minutes", headers=quality_auth)).status_code == 403
    assert (await client.get(f"{BASE}/meetings/{m['id']}", headers=outsider_auth)).status_code == 200


async def test_double_send_is_409_with_one_notification_per_member(client, pm_auth, lop_project, session_factory):
    await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m["id"])
    url = f"{BASE}/meetings/{m['id']}/minutes"
    assert (await client.post(url, headers=pm_auth)).status_code == 200
    assert (await client.post(url, headers=pm_auth)).status_code == 409
    notes = await _notes(session_factory)
    assert sorted(n.user_id for n in notes) == sorted(
        {lop_project.pm_id, lop_project.quality_user_id, lop_project.sales_user_id})
    async with session_factory() as s:
        assert (await s.get(LopMeeting, m["id"])).minutes_sent_at is not None


async def test_empty_team_is_400_and_does_not_stamp(client, admin_auth, pm_auth, lop_project, session_factory):
    await _line(client, pm_auth, lop_project)
    m = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m["id"])
    for dept in (lop_project.pm_dept_id, lop_project.apqp_id, lop_project.sales_dept_id):
        r = await client.put(f"/api/v1/projects/{lop_project.id}/team", headers=admin_auth,
                             json={"department_id": dept, "user_id": None})
        assert r.status_code == 200, r.text
    r = await client.post(f"{BASE}/meetings/{m['id']}/minutes", headers=admin_auth)
    assert r.status_code == 400 and "No project team" in r.json()["detail"]
    async with session_factory() as s:
        assert (await s.get(LopMeeting, m["id"])).minutes_sent_at is None
    assert await _notes(session_factory) == []


async def test_repeating_the_same_due_date_is_not_a_move(client, pm_auth, lop_project):
    a = await _line(client, pm_auth, lop_project, due_date=_d(10))
    m = await _start(client, pm_auth, lop_project)
    await client.patch(f"{BASE}/lines/{a}", headers=pm_auth, json={"due_date": _d(10), "title": "T2"})
    assert _marks(await _meeting(client, pm_auth, m["id"]))[a]["mark"] == "updated"


async def test_minutes_sections_are_capped(client, pm_auth, lop_project, session_factory):
    from app.services.lop_meetings import minutes_text
    for i in range(52):
        await _line(client, pm_auth, lop_project, f"Line {i}")
    m = await _start(client, pm_auth, lop_project)
    await _close(client, pm_auth, m["id"])
    async with session_factory() as s:
        _, body = await minutes_text(s, m["id"])
    assert sum(1 for ln in body.splitlines() if ln.startswith("#")) == 50
    assert "... and 2 more" in body
