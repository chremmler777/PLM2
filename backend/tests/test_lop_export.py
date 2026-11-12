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
    assert r.headers["content-disposition"] == \
        f'attachment; filename="LOP lop1 {_today().isoformat()}.xlsx"'


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
