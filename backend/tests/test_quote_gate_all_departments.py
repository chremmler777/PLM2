"""Quote creation waits for every Responsible department (Christoph
2026-11-14, live CR-2026-0001): a department that answered No on every
checklist row still closes its costing (implementation support hours, 0
allowed, then Finalize; or "no cost") before the change moves to quoting.
Before, such a department owed nothing and quoting opened the second the
last assessment was submitted."""
import pytest

from app.services import cm_switches
from tests.conftest import login  # noqa: F401
from tests.test_auto_advance import _finalize_tool, _make, _member, _status

pytestmark = [pytest.mark.asyncio, pytest.mark.auto_advance]


async def _state(client, auth, change_id):
    return (await client.get(f"/api/v1/changes/{change_id}/stage-state",
                             headers=auth)).json()["auto_advance"]


async def test_all_no_department_holds_quote_creation(
        client, admin_auth, session_factory, seed):
    ids = await _make(session_factory, seed, packaging_closed=False)
    await _finalize_tool(client, session_factory, seed, ids, "gate-tool1@test.io")
    assert await _status(session_factory, ids["change_id"]) == "costing"
    st = await _state(client, admin_auth, ids["change_id"])
    assert [(o["department_name"], o["open"]) for o in st["open"]] == [
        ("Packaging Engineer", "costing")]


async def test_support_hours_and_finalize_is_enough_for_an_all_no_department(
        client, admin_auth, session_factory, seed):
    ids = await _make(session_factory, seed, packaging_closed=False)
    await _finalize_tool(client, session_factory, seed, ids, "gate-tool2@test.io")
    pack = await _member(client, session_factory, seed, ids["Packaging Engineer"],
                         "gate-pack2@test.io")
    base = f"/api/v1/changes/{ids['change_id']}/costing"
    # without the support hours the finalize is refused and says what is missing
    res = await client.post(
        f"{base}/departments/{ids['Packaging Engineer']}/finalize", headers=pack)
    assert res.status_code == 400 and "support hours" in res.text, res.text
    res = await client.post(
        f"{base}/positions",
        json={"department_id": ids["Packaging Engineer"], "kind": "support_effort",
              "label": "Implementation support (h)", "hours": 0}, headers=pack)
    assert res.status_code == 201, res.text
    # no costing booking is asked of a department that had nothing to cost
    res = await client.post(
        f"{base}/departments/{ids['Packaging Engineer']}/finalize", headers=pack)
    assert res.status_code == 200, res.text
    assert await _status(session_factory, ids["change_id"]) == "quoting"


async def test_no_cost_closes_an_all_no_department(
        client, admin_auth, session_factory, seed):
    ids = await _make(session_factory, seed, packaging_closed=False)
    await _finalize_tool(client, session_factory, seed, ids, "gate-tool3@test.io")
    pack = await _member(client, session_factory, seed, ids["Packaging Engineer"],
                         "gate-pack3@test.io")
    res = await client.post(
        f"/api/v1/changes/{ids['change_id']}/costing/departments/"
        f"{ids['Packaging Engineer']}/no-cost", json={"reason": "no_work"}, headers=pack)
    assert res.status_code == 200, res.text
    assert await _status(session_factory, ids["change_id"]) == "quoting"


async def test_a_consulted_all_no_row_owes_nothing(
        client, admin_auth, session_factory, seed):
    ids = await _make(session_factory, seed, packaging_closed=False,
                      extra_rows=[("Development", 1, "C", True)])
    await _finalize_tool(client, session_factory, seed, ids, "gate-tool4@test.io")
    st = await _state(client, admin_auth, ids["change_id"])
    assert [o["department_name"] for o in st["open"]] == ["Packaging Engineer"]


async def test_switched_off_the_old_rule_holds(
        monkeypatch, client, session_factory, seed):
    monkeypatch.setattr(cm_switches, "ALL_RESPONSIBLE_CLOSE_COSTING", False)
    ids = await _make(session_factory, seed, packaging_closed=False)
    await _finalize_tool(client, session_factory, seed, ids, "gate-tool5@test.io")
    assert await _status(session_factory, ids["change_id"]) == "quoting"
