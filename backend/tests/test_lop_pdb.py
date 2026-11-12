"""Project LOP: live PDB status and open topics, pinning with name and date."""
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import Project
from app.models.lop import LopEvent, LopLine
from app.services import pdb_client
from app.services.lop_service import _today

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


class Pdb:
    """Mutable fake PDB behind httpx.MockTransport."""
    def __init__(self):
        self.topics = []
        self.fail = None          # status code to answer with
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.path, request.headers.get("authorization")))
        if self.fail:
            return httpx.Response(self.fail)
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"tool_count": 2, "funnel": {}, "tools": [
                {"tool_number": "3001", "tool_name": "Cover", "ps": "Green", "ts": "Green",
                 "open_topics": 2}]})
        return httpx.Response(200, json=self.topics)


def topic(i, age=10, **kw):
    t = {"id": i, "tool_number": "3001", "issue": f"Issue {i}", "todo": f"Fix {i}",
         "department": "Process ENG", "date_recorded": "2026-10-01", "age_days": age,
         "last_log_at": None, "escalation_level": 0, "escalated": False,
         "committed_until": None, "handover_impact": False}
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
    """The LOP project with a numeric project number, so it has a PDB id."""
    async with session_factory() as s:
        p = await s.get(Project, lop_project.id)
        p.code = "1748"
        await s.commit()
    return lop_project


async def _get(client, auth, pid, q=""):
    r = await client.get(f"{BASE}/projects/{pid}/pdb{q}", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


async def _pin(client, auth, pid, tid, **body):
    return await client.post(f"{BASE}/projects/{pid}/pdb/{tid}/pin", headers=auth, json=body)


async def test_pdb_not_configured_says_so(client, pm_auth, lop_project):
    b = await _get(client, pm_auth, lop_project.id)
    assert b["available"] is False and b["topics"] == [] and "not configured" in b["reason"]


async def test_project_code_that_is_not_a_number_has_no_pdb(client, pm_auth, lop_project, pdb):
    b = await _get(client, pm_auth, lop_project.id)          # code "lop1"
    assert b["available"] is False and "no PDB project" in b["reason"]
    assert pdb.calls == []


async def test_pdb_down_does_not_break_the_lop(client, pm_auth, pdb_project, pdb):
    pdb.fail = 503
    r = await client.get(f"{BASE}/projects/{pdb_project.id}?view=meeting", headers=pm_auth)
    assert r.status_code == 200
    b = await _get(client, pm_auth, pdb_project.id)
    assert b["available"] is False and b["reason"] and b["topics"] == []


async def test_status_and_topics_come_from_pdb_with_the_token(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7, age=41)]
    b = await _get(client, pm_auth, pdb_project.id)
    assert b["available"] is True and b["reason"] is None and b["hidden"] == 0
    assert b["status"]["tool_count"] == 2
    assert {c[0] for c in pdb.calls} == {"/service/plm/projects/1748/status",
                                         "/service/plm/projects/1748/topics"}
    assert all(c[1] == "Bearer tok" for c in pdb.calls)


async def test_unpinned_topic_is_never_late_but_has_no_name(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7, age=41)]
    t = (await _get(client, pm_auth, pdb_project.id))["topics"][0]
    assert t["late"] is False and t["stale"] is False and t["under_control"] is False
    assert t["group"] == "pdb" and t["age_days"] == 41
    assert t["kind"] == "pdb_topic" and t["ref_key"] == "7" and t["id"] is None
    assert "Issue 7" in t["text"] and "Fix 7" in t["text"] and t["tool_number"] == "3001"
    assert t["pinned"] is False


async def test_escalated_topics_first_then_oldest(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(1, age=5), topic(2, age=30), topic(3, age=1, escalated=True,
                                                          escalation_level=2),
                  topic(4, age=None)]
    ts = (await _get(client, pm_auth, pdb_project.id))["topics"]
    assert [t["ref_key"] for t in ts] == ["3", "2", "1", "4"]
    assert ts[-1]["age_days"] == 0


async def test_default_view_limits_to_ten_oldest_and_all_shows_everything(
        client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(i, age=i) for i in range(1, 16)]
    pdb.topics[0]["escalated"] = True                      # id 1, youngest, escalated
    b = await _get(client, pm_auth, pdb_project.id)
    keys = [t["ref_key"] for t in b["topics"]]
    assert len(keys) == 11 and keys[0] == "1" and b["hidden"] == 4
    assert "15" in keys and "5" not in keys
    b = await _get(client, pm_auth, pdb_project.id, "?all=true")
    assert len(b["topics"]) == 15 and b["hidden"] == 0


async def test_pin_needs_a_date(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    assert (await _pin(client, pm_auth, pdb_project.id, 7)).status_code == 400


async def test_unmapped_department_without_responsible_falls_to_the_pm(
        client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7, department="Something Else")]       # not in the department map
    r = await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01")
    assert r.status_code == 201, r.text
    assert r.json()["responsible_id"] == pdb_project.pm_id
    assert r.json()["responsible_is_default"] is True and r.json()["department_id"] is None


async def test_pin_without_any_responsible_and_no_pm_is_refused(
        client, admin_auth, pdb_project, pdb, session_factory):
    from app.models.workflow import ProjectResponsible
    async with session_factory() as s:
        row = (await s.execute(select(ProjectResponsible).where(
            ProjectResponsible.project_id == pdb_project.id,
            ProjectResponsible.department_id == pdb_project.pm_dept_id))).scalar_one()
        await s.delete(row)
        await s.commit()
    pdb.topics = [topic(7, department="Something Else")]
    r = await _pin(client, admin_auth, pdb_project.id, 7, due_date="2026-12-01")
    assert r.status_code == 400 and "responsible" in r.json()["detail"]


async def test_status_failing_alone_keeps_the_topics(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    inner = pdb.handler
    pdb.handler = lambda req: (httpx.Response(503) if req.url.path.endswith("/status")
                               else inner(req))
    import app.services.pdb_client as pc
    pc.default_transport = httpx.MockTransport(pdb.handler)
    b = await _get(client, pm_auth, pdb_project.id)
    assert b["available"] is True and b["status"] is None and b["status_reason"]
    assert [t["ref_key"] for t in b["topics"]] == ["7"]


async def test_non_numeric_topic_id_does_not_break_the_sort(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic("abc", age=3), topic("def", age=3)]
    b = await _get(client, pm_auth, pdb_project.id)
    assert {t["ref_key"] for t in b["topics"]} == {"abc", "def"}


async def test_cache_holds_for_60_seconds_per_project(monkeypatch):
    monkeypatch.setattr(get_settings(), "pdb_service_token", "tok")
    pdb_client.clear_cache()
    now = [1000.0]
    monkeypatch.setattr(pdb_client.time, "monotonic", lambda: now[0])
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json=[])
    tr = httpx.MockTransport(handler)
    await pdb_client.project_topics("1748", transport=tr)
    now[0] += 30
    await pdb_client.project_topics("1748", transport=tr)
    assert len(calls) == 1
    await pdb_client.project_topics("1749", transport=tr)          # other project: own entry
    assert len(calls) == 2
    now[0] += 31
    await pdb_client.project_topics("1748", transport=tr)
    assert len(calls) == 3
    pdb_client.clear_cache()


async def test_mapped_department_without_team_member_falls_to_the_pm(
        client, pm_auth, pdb_project, pdb, session_factory):
    from tests.conftest import make_department_member
    await make_department_member(session_factory, pdb_project.outsider_id, "Tool Engineer")
    pdb.topics = [topic(7, department="Tool Engineering")]
    r = await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01")
    assert r.status_code == 201, r.text
    assert r.json()["responsible_id"] == pdb_project.pm_id
    assert r.json()["responsible_is_default"] is True


async def test_pin_resolves_the_team_member_from_the_pdb_department(
        client, pm_auth, session_factory, pdb_project, pdb, admin_auth):
    from tests.conftest import make_department_member
    proc_user = pdb_project.quality_user_id
    dept = await make_department_member(session_factory, proc_user, "Process Engineer")
    r = await client.put(f"/api/v1/projects/{pdb_project.id}/team", headers=admin_auth,
                         json={"department_id": dept, "user_id": proc_user})
    assert r.status_code == 200, r.text
    pdb.topics = [topic(7)]
    r = await _pin(client, pm_auth, pdb_project.id, 7, next_check_date="2026-12-01")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["responsible_id"] == proc_user and b["department_id"] == dept
    assert b["kind"] == "pdb_topic" and b["ref_key"] == "7" and b["status"] == "open"
    assert b["title"] == "Issue 7"


async def test_pinned_topic_follows_the_rules(client, pm_auth, quality_auth, pdb_project, pdb):
    pdb.topics = [topic(7, issue="Tool leaks")]
    yesterday = (_today() - timedelta(days=1)).isoformat()
    r = await _pin(client, pm_auth, pdb_project.id, 7, responsible_id=pdb_project.quality_user_id,
                   due_date=yesterday)
    assert r.status_code == 201, r.text
    t = (await _get(client, pm_auth, pdb_project.id))["topics"][0]
    assert t["pinned"] is True and t["id"] == r.json()["id"]
    assert t["late"] is True and t["group"] == "overdue" and t["under_control"] is True
    assert t["text"].startswith("Tool leaks") and t["age_days"] == 10
    # My tasks needs no PDB: snapshot text
    pdb.fail = 503
    mine = (await client.get(f"{BASE}/mine", headers=quality_auth)).json()
    assert [m["ref_key"] for m in mine] == ["7"]
    assert mine[0]["title"] == "Tool leaks" and mine[0]["late"] is True
    # the project view lists the pin from its snapshot
    v = (await client.get(f"{BASE}/projects/{pdb_project.id}?view=open", headers=pm_auth)).json()
    assert [ln["ref_key"] for ln in v["lines"]] == ["7"]


async def test_pdb_text_is_live_when_pdb_changed(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7, issue="Old")]
    await _pin(client, pm_auth, pdb_project.id, 7, responsible_id=pdb_project.quality_user_id,
               due_date="2099-01-01")
    pdb.topics = [topic(7, issue="New", todo="Do it")]
    pdb_client.clear_cache()
    t = (await _get(client, pm_auth, pdb_project.id))["topics"][0]
    assert "New" in t["text"] and t["title"] == "Old"


async def test_only_pm_pins(client, quality_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    r = await _pin(client, quality_auth, pdb_project.id, 7, due_date="2026-12-01")
    assert r.status_code == 403


async def test_pin_unknown_topic_is_404_and_pdb_down_is_503(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    assert (await _pin(client, pm_auth, pdb_project.id, 99,
                       responsible_id=pdb_project.quality_user_id,
                       due_date="2026-12-01")).status_code == 404
    pdb.fail = 503
    pdb_client.clear_cache()
    assert (await _pin(client, pm_auth, pdb_project.id, 7,
                       responsible_id=pdb_project.quality_user_id,
                       due_date="2026-12-01")).status_code == 503


async def test_pinned_topic_cannot_be_closed_in_plm(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    lid = (await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01",
                      responsible_id=pdb_project.quality_user_id)).json()["id"]
    r = await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth, json={"status": "closed"})
    assert r.status_code == 400 and "closed in PDB" in r.json()["detail"]


async def test_responsible_comments_and_reports_done_on_a_pinned_topic(
        client, pm_auth, quality_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    lid = (await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01",
                      responsible_id=pdb_project.quality_user_id)).json()["id"]
    assert (await client.post(f"{BASE}/lines/{lid}/comments", headers=quality_auth,
                              json={"text": "on it"})).status_code == 201
    assert (await client.patch(f"{BASE}/lines/{lid}", headers=quality_auth,
                               json={"status": "done_check"})).status_code == 200
    assert (await client.patch(f"{BASE}/lines/{lid}", headers=quality_auth,
                               json={"due_date": "2026-12-05"})).status_code == 403


async def test_topic_closed_in_pdb_closes_the_pin(client, pm_auth, pdb_project, pdb,
                                                  session_factory):
    pdb.topics = [topic(7), topic(8)]
    lid = (await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01",
                      responsible_id=pdb_project.quality_user_id)).json()["id"]
    # PDB down: nothing is closed
    pdb.fail = 503
    pdb_client.clear_cache()
    await _get(client, pm_auth, pdb_project.id)
    async with session_factory() as s:
        assert (await s.get(LopLine, lid)).status == "open"
    # PDB answers without topic 7
    pdb.fail = None
    pdb.topics = [topic(8)]
    pdb_client.clear_cache()
    b = await _get(client, pm_auth, pdb_project.id)
    assert [t["ref_key"] for t in b["topics"]] == ["8"]
    async with session_factory() as s:
        ln = await s.get(LopLine, lid)
        assert ln.status == "closed" and ln.closed_at is not None and ln.closed_by is None
        ev = (await s.execute(select(LopEvent).where(
            LopEvent.line_id == lid, LopEvent.new_value == "closed in PDB"))).scalars().all()
        assert len(ev) == 1
    # topic comes back: the pin reopens
    pdb.topics = [topic(7), topic(8)]
    pdb_client.clear_cache()
    t = {x["ref_key"]: x for x in (await _get(client, pm_auth, pdb_project.id))["topics"]}
    assert t["7"]["pinned"] is True and t["7"]["status"] == "open"


async def test_pinning_twice_returns_the_same_line(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    a = await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01",
                   responsible_id=pdb_project.quality_user_id)
    b = await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01",
                   responsible_id=pdb_project.quality_user_id)
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]


async def test_project_get_includes_pinned_topics_without_calling_pdb(
        client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7, issue="Tool leaks")]
    yesterday = (_today() - timedelta(days=1)).isoformat()
    lid = (await _pin(client, pm_auth, pdb_project.id, 7,
                      responsible_id=pdb_project.quality_user_id, due_date=yesterday)).json()["id"]
    pdb.calls.clear()
    pdb.fail = 503                       # would fail the test if PDB were asked
    for view in ("open", "meeting"):
        v = (await client.get(f"{BASE}/projects/{pdb_project.id}?view={view}", headers=pm_auth)).json()
        assert [ln["id"] for ln in v["lines"]] == [lid]
        ln = v["lines"][0]
        assert ln["kind"] == "pdb_topic" and ln["pinned"] is True and ln["ref_key"] == "7"
        assert ln["text"] == "Tool leaks" and ln["late"] is True and ln["group"] == "overdue"
        assert ln["pdb_live"] is False
    assert pdb.calls == []


async def test_closed_pin_is_in_the_closed_view(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(7)]
    lid = (await _pin(client, pm_auth, pdb_project.id, 7, due_date="2026-12-01",
                      responsible_id=pdb_project.quality_user_id)).json()["id"]
    pdb.topics = []                      # gone from PDB: the pin closes
    pdb_client.clear_cache()
    await _get(client, pm_auth, pdb_project.id)
    closed = (await client.get(f"{BASE}/projects/{pdb_project.id}?view=closed", headers=pm_auth)).json()
    assert [ln["id"] for ln in closed["lines"]] == [lid]
    opened = (await client.get(f"{BASE}/projects/{pdb_project.id}?view=open", headers=pm_auth)).json()
    assert opened["lines"] == []
