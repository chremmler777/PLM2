"""Project LOP: Excel export of the project's list."""
from datetime import timedelta
from io import BytesIO

import httpx
import pytest
from openpyxl import load_workbook

from app.core.config import get_settings
from app.models.entities import Project
from app.services import pdb_client
from app.services.lop_service import _today

from tests.test_lop_pdb import Pdb, pdb_project, topic  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEAD = ["No.", "Task", "Source", "Tool", "Department", "Responsible", "First due", "Due",
        "Next check", "Days late", "Status", "Stale", "Last update", "Last comment"]


async def _add(client, auth, pid, title, due=None, dept=None):
    body = {"title": title}
    if due:
        body["due_date"] = due.isoformat()
    if dept:
        body["department_id"] = dept
    r = await client.post(f"{BASE}/projects/{pid}/lines", headers=auth, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _export(client, auth, pid, q=""):
    r = await client.get(f"{BASE}/projects/{pid}/export.xlsx{q}", headers=auth)
    assert r.status_code == 200, r.text
    return r, load_workbook(BytesIO(r.content))["LOP"]


def _rows(ws):
    return [[c.value for c in row] for row in ws.iter_rows()]


@pytest.fixture
def pdb(monkeypatch):
    fake = Pdb()
    monkeypatch.setattr(get_settings(), "pdb_service_token", "tok")
    monkeypatch.setattr(pdb_client, "default_transport", httpx.MockTransport(fake.handler))
    pdb_client.clear_cache()
    yield fake
    pdb_client.clear_cache()


async def test_export_has_one_row_per_open_line(client, pm_auth, lop_project):
    for t in ("One thing", "Two things", "Three things"):
        await _add(client, pm_auth, lop_project.id, t)
    r, ws = await _export(client, pm_auth, lop_project.id)
    assert r.headers["content-type"].startswith(XLSX)
    rows = _rows(ws)
    # PDB is not configured: note row, then header, then the lines
    assert "not configured" in rows[0][0] and rows[1] == HEAD
    assert len(rows) == 2 + 3
    assert {r_[1] for r_ in rows[2:]} == {"One thing", "Two things", "Three things"}
    assert ws.freeze_panes == "A3" and ws.auto_filter.ref


async def test_late_line_shows_days_late(client, pm_auth, lop_project):
    await _add(client, pm_auth, lop_project.id, "Late one",
               due=_today() - timedelta(days=8), dept=lop_project.apqp_id)
    _, ws = await _export(client, pm_auth, lop_project.id)
    rows = _rows(ws)
    assert rows[2][HEAD.index("Days late")] == 8
    assert rows[2][HEAD.index("Status")] == "Open"


async def test_dates_are_real_dates(client, pm_auth, lop_project):
    await _add(client, pm_auth, lop_project.id, "Dated",
               due=_today() + timedelta(days=5), dept=lop_project.apqp_id)
    _, ws = await _export(client, pm_auth, lop_project.id)
    for col in ("First due", "Due", "Last update"):
        cell = ws.cell(row=3, column=HEAD.index(col) + 1)
        assert cell.is_date, col
        assert cell.number_format == "yyyy-mm-dd"


async def test_pdb_down_is_stated_in_the_sheet(client, pm_auth, pdb_project, pdb):
    pdb.fail = 500
    await _add(client, pm_auth, pdb_project.id, "A line")
    _, ws = await _export(client, pm_auth, pdb_project.id)
    rows = _rows(ws)
    assert rows[0][0] == "PDB could not be reached; PDB topics are missing from this list."
    assert rows[1] == HEAD and len(rows) == 3


async def test_text_with_control_characters_does_not_break(client, pm_auth, lop_project):
    line = await _add(client, pm_auth, lop_project.id, "Has comment")
    r = await client.post(f"{BASE}/lines/{line['id']}/comments", headers=pm_auth,
                          json={"text": "bad\x0bchar"})
    assert r.status_code == 201
    _, ws = await _export(client, pm_auth, lop_project.id)
    assert _rows(ws)[2][HEAD.index("Last comment")] == "badchar"


async def test_filename_carries_project_code_and_date(client, pm_auth, lop_project):
    r, _ = await _export(client, pm_auth, lop_project.id)
    name = f"LOP lop1 {_today().isoformat()}.xlsx"
    assert r.headers["content-disposition"] == \
        f'attachment; filename="{name}"; filename*=UTF-8\'\'{name.replace(" ", "%20")}'


async def test_unpinned_pdb_topics_follow_the_lines_with_blank_number(
        client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(11, age=5), topic(12, age=30), topic(13, age=1, escalated=True)]
    await _add(client, pm_auth, pdb_project.id, "A line")
    _, ws = await _export(client, pm_auth, pdb_project.id)
    rows = _rows(ws)
    assert rows[0] == HEAD and len(rows) == 1 + 1 + 3
    assert rows[1][0] is not None and rows[1][1] == "A line"
    assert [r_[0] for r_ in rows[2:]] == [None, None, None]
    assert [r_[1].split("\n")[0] for r_ in rows[2:]] == ["Issue 13", "Issue 12", "Issue 11"]
    assert {r_[HEAD.index("Status")] for r_ in rows[2:]} == {"Open in PDB"}
    assert rows[2][HEAD.index("Tool")] == "3001"
    # closed view never lists PDB topics
    _, ws = await _export(client, pm_auth, pdb_project.id, "?view=closed")
    assert _rows(ws)[0] == HEAD and len(_rows(ws)) == 1


async def test_missing_or_disabled_project_is_404(client, pm_auth, plain_project):
    r = await client.get(f"{BASE}/projects/{plain_project.id}/export.xlsx", headers=pm_auth)
    assert r.status_code == 404
    r = await client.get(f"{BASE}/projects/999999/export.xlsx", headers=pm_auth)
    assert r.status_code == 404


async def test_hostile_project_code_gives_a_safe_header(client, pm_auth, lop_project, session_factory):
    async with session_factory() as s:
        p = await s.get(Project, lop_project.id)
        p.code = 'A"b/c\\d\r\nX-Evil: 1é中'
        await s.commit()
    r, ws = await _export(client, pm_auth, lop_project.id)
    h = r.headers["content-disposition"]
    h.encode("latin-1")
    assert "\r" not in h and "\n" not in h
    fallback = h.split('filename="')[1].split('"; filename*=')[0]
    assert '"' not in fallback and "/" not in fallback and "\\" not in fallback
    assert fallback.isascii() and fallback.endswith(".xlsx")
    assert "filename*=UTF-8''LOP%20A%22b%2Fc" in h and "%C3%A9" in h


async def test_pin_line_keeps_its_topic_off_the_unpinned_rows(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(21), topic(22)]
    r = await client.post(f"{BASE}/projects/{pdb_project.id}/pdb/21/pin", headers=pm_auth,
                          json={"due_date": (_today() + timedelta(days=3)).isoformat()})
    assert r.status_code == 201, r.text
    for view in ("open", "meeting"):
        _, ws = await _export(client, pm_auth, pdb_project.id, f"?view={view}")
        rows = _rows(ws)
        assert len(rows) == 1 + 2
        assert [r_[0] is None for r_ in rows[1:]] == [False, True]
        assert sum("Issue 21" in r_[1] for r_ in rows[1:]) == 1


async def test_follow_pdb_failure_does_not_fail_the_download(
        client, pm_auth, pdb_project, pdb, monkeypatch):
    from app.services.lop_service import LopService

    async def boom(*a, **k):
        raise RuntimeError("db hiccup")
    monkeypatch.setattr(LopService, "follow_pdb", boom)
    pdb.topics = [topic(31)]
    await _add(client, pm_auth, pdb_project.id, "Still here")
    _, ws = await _export(client, pm_auth, pdb_project.id)
    rows = _rows(ws)
    assert rows[0] == HEAD and len(rows) == 3 and rows[1][1] == "Still here"


async def test_formula_like_text_stays_a_string(client, pm_auth, lop_project):
    texts = ["=1+1", "@x", "+1", "-1"]
    for t in texts:
        line = await _add(client, pm_auth, lop_project.id, t)
        r = await client.post(f"{BASE}/lines/{line['id']}/comments", headers=pm_auth,
                              json={"text": t})
        assert r.status_code == 201
    _, ws = await _export(client, pm_auth, lop_project.id)
    rows = _rows(ws)[2:]
    assert sorted(r_[1] for r_ in rows) == sorted(texts)
    for row in ws.iter_rows(min_row=3):
        for c in (row[1], row[13]):
            assert c.data_type == "s" and isinstance(c.value, str)


async def test_meeting_view_exports_the_open_lines_and_topics(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(41)]
    await _add(client, pm_auth, pdb_project.id, "For the meeting")
    _, ws = await _export(client, pm_auth, pdb_project.id, "?view=meeting")
    rows = _rows(ws)
    assert rows[0] == HEAD and len(rows) == 3
    assert rows[1][1] == "For the meeting" and rows[2][0] is None


async def test_rows_are_ordered_by_group_then_due_date(client, pm_auth, lop_project):
    t = _today()
    far = t + timedelta(days=60)
    await _add(client, pm_auth, lop_project.id, "far", due=far, dept=lop_project.apqp_id)
    await _add(client, pm_auth, lop_project.id, "late recent",
               due=t - timedelta(days=2), dept=lop_project.apqp_id)
    await _add(client, pm_auth, lop_project.id, "late old",
               due=t - timedelta(days=9), dept=lop_project.apqp_id)
    await _add(client, pm_auth, lop_project.id, "undated")
    _, ws = await _export(client, pm_auth, lop_project.id)
    titles = [r_[1] for r_ in _rows(ws)[2:]]
    assert titles == ["late old", "late recent", "undated", "far"]   # overdue, new, other


async def test_empty_pdb_list_closes_the_pins(client, pm_auth, pdb_project, pdb):
    pdb.topics = [topic(51)]
    r = await client.post(f"{BASE}/projects/{pdb_project.id}/pdb/51/pin", headers=pm_auth,
                          json={"due_date": (_today() + timedelta(days=3)).isoformat()})
    assert r.status_code == 201, r.text
    line_id = r.json()["id"]
    pdb.topics = []
    pdb_client.clear_cache()
    _, ws = await _export(client, pm_auth, pdb_project.id)
    assert _rows(ws) == [HEAD]
    _, ws = await _export(client, pm_auth, pdb_project.id, "?view=closed")
    assert [r_[0] for r_ in _rows(ws)[1:]] == [line_id]
