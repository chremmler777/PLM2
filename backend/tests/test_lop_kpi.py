"""Project LOP: control KPIs per project and department, the overview, and the
lines behind each number."""
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import Organization, Plant, Project
from app.models.lop import LopEvent, LopLine
from app.models.sep import SepGate, SepWorkItem
from app.services import pdb_client
from app.services.lop_service import _today

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"
COUNT_FIELDS = ("open", "stale", "late", "untouched_last_meeting", "dates_moved_4w",
                "opened_week", "closed_week", "no_control")


def _d(days: int) -> str:
    return (_today() + timedelta(days=days)).isoformat()


async def _task(client, auth, project, title="Task x", **kw):
    body = {"title": title, "department_id": project.apqp_id, "due_date": _d(10)}
    body.update(kw)
    r = await client.post(f"{BASE}/projects/{project.id}/lines", headers=auth, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _overview(client, auth):
    r = await client.get(f"{BASE}/overview", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def _row(ov, project):
    return next(p for p in ov["projects"] if p["project_id"] == project.id)


async def _set(session_factory, line_id, **fields):
    async with session_factory() as s:
        ln = await s.get(LopLine, line_id)
        for k, v in fields.items():
            setattr(ln, k, v)
        await s.commit()


async def _db_line(session_factory, project_id, **kw):
    base = dict(project_id=project_id, kind="task", title="db line", status="open",
                created_at=datetime.utcnow(), last_update_at=datetime.utcnow())
    base.update(kw)
    async with session_factory() as s:
        ln = LopLine(**base)
        s.add(ln)
        await s.commit()
        return ln.id


async def _more_project(session_factory, code, *, lop=True, org_id=None):
    async with session_factory() as s:
        if org_id is None:
            plant_id = (await s.execute(select(Plant.id))).scalars().first()
        else:
            org = Organization(name="Other Org", code=f"o-{code}", is_active=True)
            s.add(org)
            await s.flush()
            plant = Plant(organization_id=org.id, name="P2", code=f"p-{code}", location="DE",
                          is_active=True)
            s.add(plant)
            await s.flush()
            plant_id = plant.id
        p = Project(plant_id=plant_id, name=f"Project {code}", code=code, status="active",
                    lop_enabled=lop)
        s.add(p)
        await s.commit()
        return p.id


# ------------------------------------------------------------ control share
async def test_control_share_counts_name_and_date(client, pm_auth, lop_project):
    for i in range(3):
        await _task(client, pm_auth, lop_project, f"Controlled {i}")
    await _task(client, pm_auth, lop_project, "No department", department_id=None, due_date=None)
    row = _row(await _overview(client, pm_auth), lop_project)
    assert row["open"] == 4 and row["with_name_and_date_pct"] == 75 and row["no_control"] == 1


async def test_no_open_lines_has_no_percentage(client, pm_auth, lop_project):
    row = _row(await _overview(client, pm_auth), lop_project)
    assert row["open"] == 0 and row["with_name_and_date_pct"] is None
    assert row["on_time_pct_4w"] is None and row["avg_days_late"] == 0


async def test_late_stale_and_average_days_late(client, pm_auth, lop_project, session_factory):
    a = await _task(client, pm_auth, lop_project, "A")
    b = await _task(client, pm_auth, lop_project, "B")
    await _task(client, pm_auth, lop_project, "C")
    await _set(session_factory, a, due_date=_today() - timedelta(days=4))
    await _set(session_factory, b, due_date=_today() - timedelta(days=1),
               last_update_at=datetime.utcnow() - timedelta(days=30))
    row = _row(await _overview(client, pm_auth), lop_project)
    assert row["late"] == 2 and row["stale"] == 1 and row["avg_days_late"] == 2.5


# --------------------------------------------------------------------- PDB
class Pdb:
    def __init__(self):
        self.topics = []
        self.fail = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(self.fail)
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"tool_count": 5, "funnel": {}, "tools": [
                {"tool_number": "1", "ps": "C"}, {"tool_number": "2", "ps": "c"},
                {"tool_number": "3", "ps": "B"}, {"tool_number": "4", "ps": "A"},
                {"tool_number": "5", "ps": None}]})
        return httpx.Response(200, json=self.topics)


def _topic(i, **kw):
    t = {"id": i, "tool_number": "3001", "issue": f"Issue {i}", "todo": "", "department": "Process ENG",
         "date_recorded": "2026-10-01", "age_days": 10, "last_log_at": None,
         "escalation_level": 0, "escalated": False, "committed_until": None,
         "handover_impact": False}
    t.update(kw)
    return t


@pytest.fixture
def pdb(monkeypatch):
    fake = Pdb()
    monkeypatch.setattr(get_settings(), "pdb_service_token", "tok")
    monkeypatch.setattr(pdb_client, "default_transport", httpx.MockTransport(fake.handler))
    pdb_client.clear_cache()
    yield fake
    pdb_client.clear_cache()


@pytest.fixture
async def pdb_project(lop_project, session_factory):
    async with session_factory() as s:
        (await s.get(Project, lop_project.id)).code = "1748"
        await s.commit()
    return lop_project


async def test_unpinned_pdb_topics_have_their_own_kpi_and_leave_the_control_share_alone(
        client, pm_auth, pdb_project, pdb):
    pdb.topics = [_topic(1, escalated=True), _topic(2), _topic(3)]
    await _task(client, pm_auth, pdb_project)
    before = _row(await _overview(client, pm_auth), pdb_project)
    r = await client.post(f"{BASE}/projects/{pdb_project.id}/pdb/1/pin", headers=pm_auth,
                          json={"responsible_id": pdb_project.pm_id, "due_date": _d(5)})
    assert r.status_code == 201, r.text
    pdb_client.clear_cache()
    ov = await _overview(client, pm_auth)
    row = _row(ov, pdb_project)
    assert before["open"] == 1 and row["open"] == 2          # the pin is a line, topics 2 and 3 are not
    assert row["with_name_and_date_pct"] == 100 and row["late"] == 0 and row["stale"] == 0
    assert row["pdb"] == {"available": True, "tools_c": 2, "tools_b": 1, "tools_a": 1,
                          "open_topics": 3, "escalated": 1, "pinned": 1,
                          "pdb_without_name_and_date": 2}
    assert ov["totals"]["pdb_without_name_and_date"] == 2 and ov["totals"]["open"] == 2


async def test_pdb_down_gives_available_false_and_numbers_still_come(
        client, pm_auth, pdb_project, pdb):
    pdb.topics = [_topic(1)]
    await _task(client, pm_auth, pdb_project)
    await client.post(f"{BASE}/projects/{pdb_project.id}/pdb/1/pin", headers=pm_auth,
                      json={"responsible_id": pdb_project.pm_id, "due_date": _d(5)})
    pdb_client.clear_cache()
    pdb.fail = 503
    row = _row(await _overview(client, pm_auth), pdb_project)
    assert row["open"] == 2
    assert row["pdb"] == {"available": False, "tools_c": None, "tools_b": None, "tools_a": None,
                          "open_topics": None, "escalated": None, "pinned": 1,
                          "pdb_without_name_and_date": None}


async def test_unexpected_pdb_error_is_not_a_500(client, pm_auth, pdb_project, pdb, monkeypatch):
    async def boom(code, **kw):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(pdb_client, "project_topics", boom)
    row = _row(await _overview(client, pm_auth), pdb_project)
    assert row["pdb"]["available"] is False


async def test_project_without_pdb_id_makes_no_request(client, pm_auth, lop_project, pdb):
    row = _row(await _overview(client, pm_auth), lop_project)          # code "lop1"
    assert row["pdb"]["available"] is False and row["pdb"]["pinned"] == 0


# ----------------------------------------------------------------- on time
async def test_on_time_uses_first_due_date_over_4_weeks(client, pm_auth, lop_project, session_factory):
    pid = lop_project.id
    now = datetime.utcnow()
    # closed today after the first date had passed, though the date was moved on: late
    await _db_line(session_factory, pid, status="closed", closed_at=now,
                   first_due_date=_today() - timedelta(days=10), due_date=_today() + timedelta(days=5))
    assert _row(await _overview(client, pm_auth), lop_project)["on_time_pct_4w"] == 0
    # closed before its first date: on time
    await _db_line(session_factory, pid, status="closed", closed_at=now,
                   first_due_date=_today() + timedelta(days=3), due_date=_today() + timedelta(days=3))
    # closed 5 weeks ago: outside the window; closed without any date: not measured
    await _db_line(session_factory, pid, status="closed", closed_at=now - timedelta(days=35),
                   first_due_date=_today() + timedelta(days=3))
    await _db_line(session_factory, pid, status="closed", closed_at=now)
    assert _row(await _overview(client, pm_auth), lop_project)["on_time_pct_4w"] == 50


async def test_reopened_line_is_never_on_time(client, pm_auth, lop_project):
    a = await _task(client, pm_auth, lop_project)
    for st in ("closed", "open", "closed"):
        assert (await client.patch(f"{BASE}/lines/{a}", headers=pm_auth,
                                   json={"status": st})).status_code == 200
    row = _row(await _overview(client, pm_auth), lop_project)
    assert row["on_time_pct_4w"] == 0 and row["closed_week"] == 1


# ------------------------------------------------------------- dates moved
async def test_dates_moved_counts_events_in_4_weeks(client, pm_auth, lop_project, session_factory):
    a = await _task(client, pm_auth, lop_project)
    assert _row(await _overview(client, pm_auth), lop_project)["dates_moved_4w"] == 0
    r = await client.patch(f"{BASE}/lines/{a}", headers=pm_auth,
                           json={"due_date": _d(20), "reason": "supplier late"})
    assert r.status_code == 200, r.text
    assert _row(await _overview(client, pm_auth), lop_project)["dates_moved_4w"] == 1
    # the first next-check date is not a move; re-setting it is
    for day in (7, 7, 9):
        r = await client.patch(f"{BASE}/lines/{a}", headers=pm_auth, json={"next_check_date": _d(day)})
        assert r.status_code == 200, r.text
    assert _row(await _overview(client, pm_auth), lop_project)["dates_moved_4w"] == 3
    # an old move does not count
    async with session_factory() as s:
        s.add(LopEvent(line_id=a, field="due_date", old_value="2026-01-01", new_value="2026-02-01",
                       created_at=datetime.utcnow() - timedelta(days=40)))
        await s.commit()
    assert _row(await _overview(client, pm_auth), lop_project)["dates_moved_4w"] == 3


# ------------------------------------------------------- weeks, departments
async def test_opened_and_closed_in_the_last_week(client, pm_auth, lop_project, session_factory):
    a = await _task(client, pm_auth, lop_project, "A")
    b = await _task(client, pm_auth, lop_project, "B")
    old = await _task(client, pm_auth, lop_project, "Old")
    await _set(session_factory, old, created_at=datetime.utcnow() - timedelta(days=20))
    await client.patch(f"{BASE}/lines/{b}", headers=pm_auth, json={"status": "closed"})
    row = _row(await _overview(client, pm_auth), lop_project)
    assert row["opened_week"] == 2 and row["closed_week"] == 1 and row["open"] == 2


async def test_department_rows_sum_to_totals(client, pm_auth, lop_project, session_factory):
    other = await _more_project(session_factory, "7")
    await _task(client, pm_auth, lop_project, "Q1")
    q2 = await _task(client, pm_auth, lop_project, "Q2")
    s1 = await _task(client, pm_auth, lop_project, "S1", department_id=lop_project.sales_dept_id)
    await _task(client, pm_auth, lop_project, "None", department_id=None, due_date=None)
    done = await _task(client, pm_auth, lop_project, "Done")
    await client.patch(f"{BASE}/lines/{done}", headers=pm_auth, json={"status": "closed"})
    await _set(session_factory, q2, due_date=_today() - timedelta(days=3),
               last_update_at=datetime.utcnow() - timedelta(days=40))
    await _set(session_factory, s1, due_date=_today() - timedelta(days=1))
    await client.patch(f"{BASE}/lines/{q2}", headers=pm_auth, json={"next_check_date": _d(3)})
    await client.patch(f"{BASE}/lines/{q2}", headers=pm_auth, json={"next_check_date": _d(4)})
    await _db_line(session_factory, other, department_id=lop_project.apqp_id,
                   due_date=_today() - timedelta(days=2))
    m = (await client.post(f"{BASE}/projects/{lop_project.id}/meetings", headers=pm_auth)).json()
    await client.post(f"{BASE}/meetings/{m['id']}/close", headers=pm_auth)
    ov = await _overview(client, pm_auth)
    assert ov["totals"]["untouched_last_meeting"] > 0
    names = [d["name"] for d in ov["departments"]]
    assert names == sorted(n for n in names if n != "No department") + ["No department"]
    assert next(d for d in ov["departments"] if d["name"] == "No department")["department_id"] is None
    for f in COUNT_FIELDS:
        assert sum(d[f] for d in ov["departments"]) == ov["totals"][f], f
        assert sum(p[f] for p in ov["projects"]) == ov["totals"][f], f


async def test_everyone_logged_in_sees_the_whole_overview(client, outsider_auth, pm_auth, lop_project):
    await _task(client, pm_auth, lop_project)
    ov = await _overview(client, outsider_auth)
    assert _row(ov, lop_project)["open"] == 1 and ov["departments"]
    assert set(ov) == {"totals", "projects", "departments", "escalations"}


# --------------------------------------------------------------------- SEP
async def test_gate_ready_share(client, pm_auth, lop_project, session_factory):
    pid = lop_project.id
    async with session_factory() as s:
        g1 = SepGate(project_id=pid, code="K0/RG1", seq=1, phase_de="p", phase_en="p", status="closed")
        g2 = SepGate(project_id=pid, code="K1/RG2", seq=2, phase_de="p", phase_en="p",
                     status="in_progress", target_date=datetime(2027, 1, 15))
        s.add_all([g1, g2])
        await s.flush()
        s.add(SepWorkItem(gate_id=g1.id, project_id=pid, item_no=1, title_de="t", title_en="t",
                          department="PM", status="open"))
        for n in range(42):
            st = "done" if n < 5 else ("not_applicable" if n == 5 else "open")
            s.add(SepWorkItem(gate_id=g2.id, project_id=pid, item_no=n + 1, title_de="t",
                              title_en="t", department="PM", status=st))
        await s.commit()
    row = _row(await _overview(client, pm_auth), lop_project)
    assert row["gate"] == {"code": "K1/RG2", "done_pct": 14, "target_date": "2027-01-15"}


async def test_no_gates_means_no_gate(client, pm_auth, lop_project):
    assert _row(await _overview(client, pm_auth), lop_project)["gate"] is None


# ----------------------------------------------------------- project list
async def test_only_lop_projects_are_listed_by_number(client, pm_auth, lop_project, plain_project,
                                                      session_factory):
    for code in ("20", "3", "abc"):
        await _more_project(session_factory, code)
    await _more_project(session_factory, "5", lop=False)
    await _more_project(session_factory, "9", org_id=True)           # another organization
    ov = await _overview(client, pm_auth)
    assert [p["code"] for p in ov["projects"]] == ["3", "20", "abc", "lop1"]


# ------------------------------------------------------------ lines behind
async def _lines(client, auth, **q):
    r = await client.get(f"{BASE}/lines", headers=auth, params=q)
    assert r.status_code == 200, r.text
    return r.json()


async def test_lines_filter_matches_the_count(client, pm_auth, lop_project, session_factory):
    other = await _more_project(session_factory, "7")
    a = await _task(client, pm_auth, lop_project, "A")
    b = await _task(client, pm_auth, lop_project, "B", department_id=lop_project.sales_dept_id)
    await _task(client, pm_auth, lop_project, "Loose", department_id=None, due_date=None)
    await _set(session_factory, a, last_update_at=datetime.utcnow() - timedelta(days=30),
               due_date=_today() - timedelta(days=2))
    await _db_line(session_factory, other, department_id=lop_project.apqp_id,
                   last_update_at=datetime.utcnow() - timedelta(days=30))
    await _db_line(session_factory, other)                           # no department, no name
    m = (await client.post(f"{BASE}/projects/{lop_project.id}/meetings", headers=pm_auth)).json()
    await client.post(f"{BASE}/meetings/{m['id']}/close", headers=pm_auth)
    await client.patch(f"{BASE}/lines/{b}", headers=pm_auth, json={"status": "closed"})
    ov = await _overview(client, pm_auth)
    count = {"open": "open", "stale": "stale", "late": "late", "no_control": "no_control",
             "untouched": "untouched_last_meeting"}
    for flag, field in count.items():
        assert ov["totals"][field] == len(await _lines(client, pm_auth, flag=flag)), flag
        for p in ov["projects"]:
            assert p[field] == len(await _lines(client, pm_auth, flag=flag, project_id=p["project_id"])), flag
        for d in ov["departments"]:
            got = await _lines(client, pm_auth, flag=flag, department_id=d["department_id"] or 0)
            assert d[field] == len(got), (flag, d["name"])
    assert ov["totals"]["stale"] >= 2 and ov["totals"]["no_control"] >= 2
    rows = await _lines(client, pm_auth, flag="stale")
    assert all("project_code" in r and r["stale"] for r in rows)
    assert {r["project_code"] for r in rows} == {"lop1", "7"}


async def test_lines_without_flag_include_closed_and_unknown_project_is_404(
        client, pm_auth, lop_project, plain_project):
    a = await _task(client, pm_auth, lop_project)
    await client.patch(f"{BASE}/lines/{a}", headers=pm_auth, json={"status": "closed"})
    assert len(await _lines(client, pm_auth, project_id=lop_project.id)) == 1
    assert await _lines(client, pm_auth, project_id=lop_project.id, flag="open") == []
    r = await client.get(f"{BASE}/lines", headers=pm_auth, params={"project_id": plain_project.id})
    assert r.status_code == 404
    r = await client.get(f"{BASE}/lines", headers=pm_auth, params={"flag": "bogus"})
    assert r.status_code == 422
