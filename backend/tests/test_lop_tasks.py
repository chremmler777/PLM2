"""Project LOP: PM tasks, assignment by department, comments, history, permissions."""
import pytest
from sqlalchemy import select

from app.models.lop import LopEvent, LopLine

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


def _lines(pid):
    return f"{BASE}/projects/{pid}/lines"


async def test_department_and_due_date_give_the_task_to_the_team_member(client, pm_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=pm_auth,
                          json={"title": "Gauge concept", "department_id": lop_project.apqp_id,
                                "due_date": "2026-11-20"})
    assert r.status_code == 201
    b = r.json()
    assert b["responsible_id"] == lop_project.quality_user_id and b["status"] == "open"
    assert b["responsible_is_default"] is False
    assert b["first_due_date"] == "2026-11-20" and b["under_control"] is True
    assert b["text"] == "Gauge concept" and b["source_label"] == "PM" and b["kind"] == "task"
    assert b["department_name"] == "APQP" and b["responsible_name"]


async def test_department_without_team_member_falls_to_the_pm(client, pm_auth, lop_project):
    b = (await client.post(_lines(lop_project.id), headers=pm_auth,
                           json={"title": "x y z", "department_id": lop_project.logistics_id,
                                 "due_date": "2026-11-20"})).json()
    assert b["responsible_id"] == lop_project.pm_id
    assert b["responsible_is_default"] is True and b["under_control"] is True


async def test_confirming_the_default_name_leaves_a_trace(client, pm_auth, lop_project, session_factory):
    from datetime import datetime
    b = (await client.post(_lines(lop_project.id), headers=pm_auth,
                           json={"title": "x y z", "department_id": lop_project.logistics_id,
                                 "due_date": "2026-11-20"})).json()
    async with session_factory() as s:
        (await s.get(LopLine, b["id"])).last_update_at = datetime(2026, 1, 1)
        await s.commit()
    m = (await client.post(f"{BASE}/projects/{lop_project.id}/meetings", headers=pm_auth)).json()
    r = await client.patch(f"{BASE}/lines/{b['id']}", headers=pm_auth,
                           json={"responsible_id": lop_project.pm_id})
    assert r.status_code == 200 and r.json()["responsible_is_default"] is False
    async with session_factory() as s:
        ev = (await s.execute(select(LopEvent).where(
            LopEvent.line_id == b["id"], LopEvent.field == "responsible_id"))).scalars().all()
        line = await s.get(LopLine, b["id"])
    assert len(ev) == 1 and ev[0].reason == "confirmed by the PM" and ev[0].user_id == lop_project.pm_id
    assert line.last_update_at > datetime(2026, 1, 1) and line.last_update_by == lop_project.pm_id
    marks = {x["line_id"]: x["mark"] for x in
             (await client.get(f"{BASE}/meetings/{m['id']}", headers=pm_auth)).json()["marks"]}
    assert marks[b["id"]] == "updated"
    again = await client.patch(f"{BASE}/lines/{b['id']}", headers=pm_auth,
                               json={"responsible_id": lop_project.pm_id})
    assert again.status_code == 200
    async with session_factory() as s:
        assert len((await s.execute(select(LopEvent).where(
            LopEvent.line_id == b["id"], LopEvent.field == "responsible_id"))).scalars().all()) == 1


async def test_no_pm_and_no_member_has_no_name(client, admin_auth, lop_project):
    r = await client.put(f"/api/v1/projects/{lop_project.id}/team", headers=admin_auth,
                         json={"department_id": lop_project.pm_dept_id, "user_id": None})
    assert r.status_code == 200, r.text
    b = (await client.post(_lines(lop_project.id), headers=admin_auth,
                           json={"title": "x y z", "department_id": lop_project.logistics_id,
                                 "due_date": "2026-11-20"})).json()
    assert b["responsible_id"] is None and b["under_control"] is False
    assert b["responsible_is_default"] is False


async def test_line_without_department_or_date_starts_new(client, pm_auth, lop_project):
    b = (await client.post(_lines(lop_project.id), headers=pm_auth,
                           json={"title": "Think about it"})).json()
    assert b["status"] == "new" and b["responsible_id"] is None and b["first_due_date"] is None
    b = (await client.post(_lines(lop_project.id), headers=pm_auth,
                           json={"title": "Dept only", "department_id": lop_project.apqp_id})).json()
    assert b["status"] == "new"


async def test_responsible_must_be_in_the_project_team(client, pm_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=pm_auth,
                          json={"title": "x y z", "department_id": lop_project.apqp_id,
                                "responsible_id": lop_project.outsider_id})
    assert r.status_code == 400


async def test_pm_can_take_a_line_himself(client, pm_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=pm_auth,
                          json={"title": "Mine", "department_id": lop_project.apqp_id,
                                "responsible_id": lop_project.pm_id, "due_date": "2026-11-20"})
    assert r.status_code == 201
    assert r.json()["responsible_id"] == lop_project.pm_id
    assert r.json()["responsible_is_default"] is False


async def test_only_pm_creates(client, quality_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=quality_auth,
                          json={"title": "x y z", "department_id": lop_project.apqp_id})
    assert r.status_code == 403


async def test_admin_creates(client, admin_auth, lop_project):
    r = await client.post(_lines(lop_project.id), headers=admin_auth, json={"title": "By admin"})
    assert r.status_code == 201


async def test_responsible_reports_done_but_cannot_close(client, quality_auth, line):
    url = f"{BASE}/lines/{line}"
    assert (await client.patch(url, headers=quality_auth, json={"status": "done_check"})).status_code == 200
    assert (await client.patch(url, headers=quality_auth, json={"status": "closed"})).status_code == 403
    assert (await client.patch(url, headers=quality_auth, json={"due_date": "2026-12-01"})).status_code == 403


async def test_others_cannot_edit(client, sales_auth, outsider_auth, line):
    url = f"{BASE}/lines/{line}"
    assert (await client.patch(url, headers=sales_auth, json={"status": "done_check"})).status_code == 403
    assert (await client.patch(url, headers=outsider_auth, json={"title": "hijack"})).status_code == 403


async def test_pm_confirms_or_reopens(client, pm_auth, line, lop_project):
    url = f"{BASE}/lines/{line}"
    b = (await client.patch(url, headers=pm_auth, json={"status": "closed"})).json()
    assert b["status"] == "closed" and b["closed_at"] and b["closed_by"] == lop_project.pm_id
    assert b["group"] == "closed"
    b = (await client.patch(url, headers=pm_auth, json={"status": "open"})).json()
    assert b["status"] == "open" and b["closed_at"] is None and b["closed_by"] is None
    assert b["first_due_date"] == "2026-11-20" and b["due_date"] == "2026-11-20"
    assert b["reopened"] is True
    kinds = [h["field"] for h in (await client.get(f"{url}/history", headers=pm_auth)).json()
             if h["type"] == "event"]
    assert kinds.count("status") == 2


async def test_moving_a_due_date_keeps_the_first_and_needs_a_reason(client, pm_auth, line):
    url = f"{BASE}/lines/{line}"
    assert (await client.patch(url, headers=pm_auth, json={"due_date": "2026-12-01"})).status_code == 400
    b = (await client.patch(url, headers=pm_auth,
                            json={"due_date": "2026-12-01", "reason": "customer drawing late"})).json()
    assert b["first_due_date"] == "2026-11-20" and b["due_date"] == "2026-12-01" and b["moved"] is True


@pytest.mark.parametrize("typed", ["first date set by the PM", "  First Date Set By The PM ",
                                   "SEP risk row changed", "sep RISK row changed  ",
                                   "Open again at the source", "GATE CLOSED"])
async def test_reserved_reasons_cannot_be_typed(client, pm_auth, line, typed, session_factory):
    url = f"{BASE}/lines/{line}"
    r = await client.patch(url, headers=pm_auth, json={"due_date": "2026-12-01", "reason": typed})
    assert r.status_code == 400 and "reserved" in r.json()["detail"]
    async with session_factory() as s:
        assert str((await s.get(LopLine, line)).due_date) == "2026-11-20"
        assert not (await s.execute(select(LopEvent).where(
            LopEvent.line_id == line, LopEvent.field == "due_date"))).scalars().all()


async def test_first_due_date_needs_no_reason(client, pm_auth, lop_project):
    b = (await client.post(_lines(lop_project.id), headers=pm_auth, json={"title": "Undated"})).json()
    r = await client.patch(f"{BASE}/lines/{b['id']}", headers=pm_auth, json={"due_date": "2026-12-01"})
    assert r.status_code == 200
    assert r.json()["first_due_date"] == "2026-12-01" and r.json()["moved"] is False


async def test_next_check_reset_needs_no_reason_but_leaves_an_event(client, pm_auth, line, session_factory):
    url = f"{BASE}/lines/{line}"
    for _ in range(2):   # the same date twice still counts
        r = await client.patch(url, headers=pm_auth, json={"next_check_date": "2026-11-25"})
        assert r.status_code == 200
    assert r.json()["next_check_date"] == "2026-11-25"
    async with session_factory() as s:
        n = len((await s.execute(select(LopEvent).where(
            LopEvent.line_id == line, LopEvent.field == "next_check_date"))).scalars().all())
    assert n == 2


async def test_changing_department_re_resolves_the_responsible(client, pm_auth, line, lop_project):
    url = f"{BASE}/lines/{line}"
    b = (await client.patch(url, headers=pm_auth, json={"department_id": lop_project.sales_dept_id})).json()
    assert b["responsible_id"] == lop_project.sales_user_id and b["department_name"] == "Sales"
    # a named responsible wins over the department's
    b = (await client.patch(url, headers=pm_auth, json={
        "department_id": lop_project.apqp_id, "responsible_id": lop_project.sales_user_id})).json()
    assert b["responsible_id"] == lop_project.sales_user_id
    b = (await client.patch(url, headers=pm_auth, json={"clear_responsible": True})).json()
    assert b["responsible_id"] is None and b["under_control"] is False
    r = await client.patch(url, headers=pm_auth, json={"responsible_id": lop_project.outsider_id})
    assert r.status_code == 400


async def test_pm_edits_title(client, pm_auth, line):
    b = (await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"title": "Gauge concept v2"})).json()
    assert b["title"] == "Gauge concept v2" and b["text"] == "Gauge concept v2"


async def test_comment_counts_as_update(client, pm_auth, quality_auth, line, lop_project):
    url = f"{BASE}/lines/{line}"
    before = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)).json()["lines"][0]
    assert before["last_comment"] is None
    r = await client.post(f"{url}/comments", headers=quality_auth, json={"text": "Supplier quoted"})
    assert r.status_code == 201
    after = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)).json()["lines"][0]
    assert after["last_update_by"] == lop_project.quality_user_id
    assert after["last_update_at"] >= before["last_update_at"]
    assert after["last_comment"]["text"] == "Supplier quoted"
    hist = (await client.get(f"{url}/history", headers=pm_auth)).json()
    assert hist[0]["type"] == "comment" and hist[0]["text"] == "Supplier quoted"


async def test_empty_comment_is_refused(client, pm_auth, line):
    assert (await client.post(f"{BASE}/lines/{line}/comments", headers=pm_auth,
                              json={"text": "   "})).status_code == 400


async def test_team_member_comments_on_someone_elses_line(client, sales_auth, line):
    r = await client.post(f"{BASE}/lines/{line}/comments", headers=sales_auth, json={"text": "FYI from sales"})
    assert r.status_code == 201


async def test_outsider_cannot_comment(client, outsider_auth, line):
    r = await client.post(f"{BASE}/lines/{line}/comments", headers=outsider_auth, json={"text": "hi there"})
    assert r.status_code == 403


async def test_everyone_logged_in_reads(client, outsider_auth, line, lop_project):
    r = await client.get(f"{BASE}/projects/{lop_project.id}", headers=outsider_auth)
    assert r.status_code == 200
    b = r.json()
    assert b["can_manage"] is False and b["last_meeting"] is None
    assert b["project"]["code"] == "lop1" and len(b["lines"]) == 1
    assert b["lines"][0]["can_manage"] is False
    assert (await client.get(f"{BASE}/lines/{line}/history", headers=outsider_auth)).status_code == 200


async def test_views_split_open_and_closed(client, pm_auth, line, lop_project):
    url = f"{BASE}/projects/{lop_project.id}"
    for v in ("meeting", "open"):
        assert [x["id"] for x in (await client.get(f"{url}?view={v}", headers=pm_auth)).json()["lines"]] == [line]
    assert (await client.get(f"{url}?view=closed", headers=pm_auth)).json()["lines"] == []
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    assert (await client.get(f"{url}?view=open", headers=pm_auth)).json()["lines"] == []
    assert [x["id"] for x in (await client.get(f"{url}?view=closed", headers=pm_auth)).json()["lines"]] == [line]


async def test_line_flags_late_and_group(client, pm_auth, lop_project):
    b = (await client.post(_lines(lop_project.id), headers=pm_auth, json={
        "title": "Way overdue", "department_id": lop_project.apqp_id, "due_date": "2020-01-01"})).json()
    assert b["late"] is True and b["days_late"] > 0 and b["group"] == "overdue"
    assert b["can_manage"] is True and b["can_report"] is False


async def test_responsible_sees_can_report(client, quality_auth, line, lop_project):
    b = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=quality_auth)).json()["lines"][0]
    assert b["can_report"] is True and b["can_manage"] is False


async def test_project_without_lop_is_404(client, pm_auth, plain_project):
    assert (await client.get(f"{BASE}/projects/{plain_project.id}", headers=pm_auth)).status_code == 404
    assert (await client.get(f"{BASE}/projects/999999", headers=pm_auth)).status_code == 404


async def test_mine_lists_my_open_lines_across_projects(client, pm_auth, quality_auth, line, lop_project):
    mine = (await client.get(f"{BASE}/mine", headers=quality_auth)).json()
    assert [x["id"] for x in mine] == [line] and mine[0]["project_code"] == "lop1"
    assert (await client.get(f"{BASE}/mine", headers=pm_auth)).json() == []
    await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={"status": "closed"})
    assert (await client.get(f"{BASE}/mine", headers=quality_auth)).json() == []


async def test_mine_asks_can_manage_once_per_project(client, pm_auth, quality_auth, lop_project, monkeypatch):
    from app.services.lop_service import LopService
    for t in ("A", "B", "C"):
        assert (await client.post(_lines(lop_project.id), headers=pm_auth,
                                  json={"title": t, "department_id": lop_project.apqp_id,
                                        "due_date": "2026-11-20"})).status_code == 201
    calls = []
    real = LopService.can_manage

    async def counted(session, user, project_id):
        calls.append(project_id)
        return await real(session, user, project_id)

    monkeypatch.setattr(LopService, "can_manage", staticmethod(counted))
    mine = (await client.get(f"{BASE}/mine", headers=quality_auth)).json()
    assert len(mine) == 3 and all(x["can_manage"] is False and x["can_report"] for x in mine)
    assert calls == [lop_project.id]


async def test_clearing_and_resetting_a_due_date_keeps_the_first_and_needs_reasons(client, pm_auth, line):
    url = f"{BASE}/lines/{line}"
    assert (await client.patch(url, headers=pm_auth, json={"due_date": None})).status_code == 400
    b = (await client.patch(url, headers=pm_auth, json={"due_date": None, "reason": "dropped"})).json()
    assert b["due_date"] is None and b["first_due_date"] == "2026-11-20"
    assert (await client.patch(url, headers=pm_auth, json={"due_date": "2027-01-10"})).status_code == 400
    b = (await client.patch(url, headers=pm_auth, json={"due_date": "2027-01-10", "reason": "back"})).json()
    assert b["due_date"] == "2027-01-10" and b["first_due_date"] == "2026-11-20"


async def test_business_date_is_local_in_the_lop_zone():
    from datetime import datetime
    from app.services.lop_service import local_date
    assert local_date(datetime(2026, 11, 12, 2, 30)) == datetime(2026, 11, 11).date()
    assert local_date(datetime(2026, 11, 12, 6, 0)) == datetime(2026, 11, 12).date()


@pytest.mark.parametrize("extra", [
    {"due_date": "2026-12-01"}, {"title": "renamed"}, "responsible"])
async def test_done_check_cannot_carry_other_changes(client, quality_auth, pm_auth, line, lop_project, extra):
    if extra == "responsible":
        extra = {"responsible_id": lop_project.sales_user_id}
    url = f"{BASE}/lines/{line}"
    assert (await client.patch(url, headers=quality_auth, json={"status": "done_check", **extra})).status_code == 403
    b = (await client.get(f"{BASE}/projects/{lop_project.id}", headers=pm_auth)).json()["lines"][0]
    assert b["status"] == "open" and b["due_date"] == "2026-11-20" and b["title"] == "Gauge concept"
    assert b["responsible_id"] == lop_project.quality_user_id


async def test_responsible_cannot_report_on_a_closed_line(client, quality_auth, pm_auth, line, lop_project):
    url = f"{BASE}/lines/{line}"
    await client.patch(url, headers=pm_auth, json={"status": "closed"})
    assert (await client.patch(url, headers=quality_auth, json={"status": "done_check"})).status_code == 403
    b = (await client.get(f"{BASE}/projects/{lop_project.id}?view=closed", headers=pm_auth)).json()["lines"]
    assert [x["status"] for x in b] == ["closed"]


async def test_clear_and_name_responsible_together_is_refused(client, pm_auth, line, lop_project):
    r = await client.patch(f"{BASE}/lines/{line}", headers=pm_auth, json={
        "clear_responsible": True, "responsible_id": lop_project.sales_user_id})
    assert r.status_code == 400
