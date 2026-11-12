"""Project LOP: the first date the PM sets on a default due date is the baseline."""
import pytest
from sqlalchemy import select

from app.models.lop import LopEvent
from tests.test_lop_sources import (  # noqa: F401  (fixtures and helpers)
    BASE, _forms, _from_sep, _gate, _item, _set_target, lop_sep)

pytestmark = pytest.mark.asyncio


async def _default_line(client, pm_auth, project, lop_sep, session_factory):
    await lop_sep()
    gate = await _gate(session_factory, project.id)
    await _set_target(client, pm_auth, gate)
    item = await _item(session_factory, gate)
    b = (await _from_sep(client, pm_auth, project.id, item_id=item)).json()
    assert b["due_date"] == "2026-12-04" and b["due_is_default"] is True
    return b["id"]


async def _events(session_factory, line_id):
    async with session_factory() as s:
        return list((await s.execute(select(LopEvent).where(
            LopEvent.line_id == line_id, LopEvent.field == "due_date")
            .order_by(LopEvent.id))).scalars().all())


async def test_confirming_a_default_due_date_clears_the_flag_without_reason(
        client, pm_auth, lop_project, lop_sep, session_factory):
    lid = await _default_line(client, pm_auth, lop_project, lop_sep, session_factory)
    r = await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth, json={"due_date": "2026-12-04"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["due_is_default"] is False and b["moved"] is False
    assert b["due_date"] == b["first_due_date"] == "2026-12-04"
    ev = await _events(session_factory, lid)
    assert [(e.reason, e.new_value) for e in ev] == [("first date set by the PM", "2026-12-04")]


async def test_replacing_a_default_due_date_sets_the_baseline_and_is_not_a_move(
        client, pm_auth, lop_project, lop_sep, session_factory):
    lid = await _default_line(client, pm_auth, lop_project, lop_sep, session_factory)
    r = await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth, json={"due_date": "2026-12-20"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["due_is_default"] is False and b["moved"] is False
    assert b["due_date"] == b["first_due_date"] == "2026-12-20"
    ov = (await client.get(f"{BASE}/overview", headers=pm_auth)).json()
    row = next(p for p in ov["projects"] if p["project_id"] == lop_project.id)
    assert row["dates_moved_4w"] == 0


async def test_clearing_a_default_due_date_needs_no_reason(
        client, pm_auth, lop_project, lop_sep, session_factory):
    lid = await _default_line(client, pm_auth, lop_project, lop_sep, session_factory)
    r = await client.patch(f"{BASE}/lines/{lid}", headers=pm_auth, json={"due_date": None})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["due_date"] is None and b["first_due_date"] is None and b["due_is_default"] is False


async def test_after_confirmation_a_change_needs_a_reason(
        client, pm_auth, lop_project, lop_sep, session_factory):
    lid = await _default_line(client, pm_auth, lop_project, lop_sep, session_factory)
    url = f"{BASE}/lines/{lid}"
    assert (await client.patch(url, headers=pm_auth, json={"due_date": "2026-12-04"})).status_code == 200
    assert (await client.patch(url, headers=pm_auth, json={"due_date": "2026-12-10"})).status_code == 400
    b = (await client.patch(url, headers=pm_auth,
                            json={"due_date": "2026-12-10", "reason": "supplier late"})).json()
    assert b["moved"] is True and b["first_due_date"] == "2026-12-04"
