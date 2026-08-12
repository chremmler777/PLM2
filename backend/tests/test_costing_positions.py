"""Costing positions: either a direct quote or an estimate.

The rules under test are the ones the cost grid could not express — who owns a
position, where its number comes from when several suppliers answered, and what
"this department owes a costing number" means once a department has already
said the change does not touch it.
"""
import json

import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import DepartmentRate
from app.models.entities import Plant, Project
from app.models.workflow import Department, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def costing(session_factory, seed):
    """A change in costing with two feasible departments and rates — the same
    setup test_costing_contract.py uses, so both files describe one world."""
    async with session_factory() as s:
        tool = Department(name="Tool Engineer", flow_type="action", is_active=True)
        dev = Department(name="Development", flow_type="action", is_active=True)
        s.add_all([tool, dev])
        await s.flush()
        project = await s.get(Project, seed["project_id"])
        usa = Plant(organization_id=seed["org_id"], name="USA", code="usa",
                    location="US", is_active=True)
        s.add(usa)
        await s.flush()
        for dept in (tool, dev):
            for plant_id, rate in ((project.plant_id, 65.0), (usa.id, 100.0)):
                s.add(DepartmentRate(department_id=dept.id, plant_id=plant_id,
                                     hourly_rate=rate, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-POS-1", title="positions", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing")
        s.add(change)
        await s.flush()
        rows = {}
        for dept in (tool, dev):
            a = ChangeAssessment(change_id=change.id, department_id=dept.id,
                                 stage_order=1, verdict="feasible")
            s.add(a)
            await s.flush()
            rows[dept.name] = a.id
        await s.commit()
        return {"change_id": change.id, "tool": tool.id, "dev": dev.id,
                "assessments": rows, "home_plant": project.plant_id,
                "usa_plant": usa.id}


async def _member(client, session_factory, seed, dept_id, email):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                 email=email, full_name=email, role="engineer",
                 hashed_password=get_password_hash("member-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return await login(client, email)


def _positions_url(costing) -> str:
    return f"/api/v1/changes/{costing['change_id']}/costing/positions"


async def _add_position(client, auth, costing, **body):
    payload = {"department_id": costing["tool"], "label": "Tool rework",
               "kind": "external", **body}
    return await client.post(_positions_url(costing), json=payload, headers=auth)


async def _add_offer(client, auth, costing, pid, **body):
    payload = {"vendor_name": "Vendor A", "cost": 1000.0, **body}
    return await client.post(f"{_positions_url(costing)}/{pid}/offers",
                             json=payload, headers=auth)


async def _set_status(session_factory, change_id, status):
    async with session_factory() as s:
        change = await s.get(ChangeRequest, change_id)
        change.status = status
        await s.commit()


# --- CRUD -------------------------------------------------------------------

async def test_position_round_trips_with_its_estimate(client, admin_auth, costing):
    res = await _add_position(
        client, admin_auth, costing, kind="internal_effort",
        label="Assessment time", tag="documentation", est_cost=320.0, hours=4.0)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["effective_cost"] == 320.0
    # Effort is never quoted, whatever the caller sent.
    assert body["pricing"] == "estimate"
    assert body["offers"] == []

    listed = await client.get(_positions_url(costing), headers=admin_auth)
    assert listed.status_code == 200, listed.text
    assert [p["id"] for p in listed.json()] == [body["id"]]
    assert listed.json()[0]["hours"] == 4.0


async def test_position_update_and_delete(client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               est_cost=100.0)).json()["id"]
    res = await client.put(f"{_positions_url(costing)}/{pid}",
                           json={"est_cost": 250.0, "tag": "tool_change"},
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["est_cost"] == 250.0
    assert res.json()["tag"] == "tool_change"
    # A field left out of a partial update is left alone.
    assert res.json()["label"] == "Tool rework"

    res = await client.delete(f"{_positions_url(costing)}/{pid}", headers=admin_auth)
    assert res.status_code == 204, res.text
    assert (await client.get(_positions_url(costing), headers=admin_auth)).json() == []


async def test_a_position_needs_a_routed_department(client, admin_auth, costing):
    """Only a department carrying an assessment has costs on this change."""
    res = await _add_position(client, admin_auth, costing, department_id=999_999,
                              est_cost=1.0)
    assert res.status_code == 400
    assert "no assessment on this change" in res.json()["detail"]


async def test_a_label_is_required(client, admin_auth, costing):
    res = await _add_position(client, admin_auth, costing, label="   ")
    assert res.status_code == 400
    assert "label" in res.json()["detail"]


# --- permissions ------------------------------------------------------------

async def test_department_writes_its_own_positions_only(
        client, session_factory, seed, costing):
    tool_member = await _member(client, session_factory, seed, costing["tool"],
                                "posstool@test.io")
    mine = await _add_position(client, tool_member, costing, est_cost=10.0)
    assert mine.status_code == 201, mine.text

    theirs = await _add_position(client, tool_member, costing,
                                 department_id=costing["dev"], est_cost=10.0)
    assert theirs.status_code == 403
    assert "Project Management" in theirs.json()["detail"]


async def test_positions_are_writable_only_while_the_change_is_in_costing(
        client, admin_auth, session_factory, seed, costing):
    tool_member = await _member(client, session_factory, seed, costing["tool"],
                                "posstool2@test.io")
    await _set_status(session_factory, costing["change_id"], "in_assessment")

    denied = await _add_position(client, tool_member, costing, est_cost=10.0)
    assert denied.status_code == 403
    # PM/admin run costing and are not held to the window.
    assert (await _add_position(client, admin_auth, costing,
                                est_cost=10.0)).status_code == 201


async def test_a_department_reads_only_its_own_positions(
        client, admin_auth, session_factory, seed, costing):
    await _add_position(client, admin_auth, costing, label="Tool work",
                        est_cost=10.0)
    await _add_position(client, admin_auth, costing, department_id=costing["dev"],
                        label="Design work", est_cost=20.0)
    tool_member = await _member(client, session_factory, seed, costing["tool"],
                                "posstool3@test.io")

    seen = (await client.get(_positions_url(costing), headers=tool_member)).json()
    assert [p["label"] for p in seen] == ["Tool work"]
    # The lead (here the admin who raised it) prices the change as a whole.
    everything = (await client.get(_positions_url(costing), headers=admin_auth)).json()
    assert len(everything) == 2


# --- offers -----------------------------------------------------------------

async def test_offers_belong_to_external_positions_only(client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               kind="support_effort", est_cost=50.0)).json()["id"]
    res = await _add_offer(client, admin_auth, costing, pid)
    assert res.status_code == 400
    assert "external" in res.json()["detail"]


async def test_favorite_is_exclusive_per_position(client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    first = (await _add_offer(client, admin_auth, costing, pid,
                              vendor_name="A", cost=1000.0,
                              favorite=True)).json()
    second = (await _add_offer(client, admin_auth, costing, pid,
                               vendor_name="B", cost=900.0,
                               favorite=True)).json()
    assert second["favorite"] is True

    position = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    favorites = [o["id"] for o in position["offers"] if o["favorite"]]
    assert favorites == [second["id"]]
    assert position["favorite_offer_id"] == second["id"]
    assert position["effective_cost"] == 900.0

    # Voting back is the same move in reverse.
    res = await client.put(
        f"/api/v1/changes/{costing['change_id']}/costing/offers/{first['id']}",
        json={"favorite": True}, headers=admin_auth)
    assert res.status_code == 200, res.text
    position = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    assert position["favorite_offer_id"] == first["id"]


async def test_effective_cost_adds_shipping_unless_it_is_included(
        client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    stated = (await _add_offer(client, admin_auth, costing, pid, vendor_name="A",
                               cost=1000.0, shipping_cost=150.0,
                               favorite=True)).json()
    assert stated["total_cost"] == 1150.0
    position = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    assert position["effective_cost"] == 1150.0

    res = await client.put(
        f"/api/v1/changes/{costing['change_id']}/costing/offers/{stated['id']}",
        json={"shipping_included": True}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["total_cost"] == 1000.0
    position = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    assert position["effective_cost"] == 1000.0


async def test_a_single_offer_prices_the_position_without_a_vote(
        client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote", est_cost=99.0)).json()["id"]
    listed = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    # A quoted position with no offer yet is worth nothing stated — the stale
    # estimate must not stand in for a supplier's answer.
    assert listed["effective_cost"] is None

    await _add_offer(client, admin_auth, costing, pid, vendor_name="Only",
                     cost=750.0)
    listed = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    assert listed["effective_cost"] == 750.0


async def test_deleting_an_offer_leaves_the_position(client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    oid = (await _add_offer(client, admin_auth, costing, pid, cost=500.0)).json()["id"]
    res = await client.delete(
        f"/api/v1/changes/{costing['change_id']}/costing/offers/{oid}",
        headers=admin_auth)
    assert res.status_code == 204, res.text
    listed = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    assert listed["offers"] == []
    assert listed["effective_cost"] is None


async def test_hours_are_accepted_on_an_external_position_too(
        client, admin_auth, costing):
    """The department's own time around a supplier's work is effort, and it
    coexists with the supplier's price rather than replacing it."""
    pid = (await _add_position(client, admin_auth, costing, pricing="quote",
                               hours=6.5)).json()["id"]
    await _add_offer(client, admin_auth, costing, pid, cost=800.0, favorite=True)
    listed = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    assert listed["hours"] == 6.5
    assert listed["effective_cost"] == 800.0


# --- lead time units --------------------------------------------------------

async def test_a_lead_time_unit_must_be_one_we_know(client, admin_auth, costing):
    res = await _add_position(client, admin_auth, costing, est_cost=1.0,
                              lead_time_days=5, lead_time_unit="fortnights")
    assert res.status_code == 400
    assert "lead time unit" in res.json()["detail"]

    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    res = await _add_offer(client, admin_auth, costing, pid, cost=1.0,
                           lead_time_days=5, lead_time_unit="moons")
    assert res.status_code == 400
    assert "lead time unit" in res.json()["detail"]


async def test_lead_time_defaults_to_calendar_days(client, admin_auth, costing):
    res = await _add_position(client, admin_auth, costing, est_cost=1.0,
                              lead_time_days=10)
    assert res.status_code == 201, res.text
    assert res.json()["lead_time_unit"] == "calendar_days"
    assert res.json()["effective_lead_time_calendar_days"] == 10


async def test_business_days_convert_for_the_roll_up(client, admin_auth, costing):
    """Five working days are seven calendar days — and beat a six-day quote."""
    res = await _add_position(client, admin_auth, costing, est_cost=1.0,
                              lead_time_days=5, lead_time_unit="business_days")
    body = res.json()
    assert body["lead_time_days"] == 5                       # as entered
    assert body["effective_lead_time_unit"] == "business_days"
    assert body["effective_lead_time_calendar_days"] == 7    # as compared

    await _add_position(client, admin_auth, costing, label="Other",
                        est_cost=1.0, lead_time_days=6,
                        lead_time_unit="calendar_days")
    summ = (await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                             headers=admin_auth)).json()
    assert summ["max_lead_time_days"] == 7


async def test_the_favorite_offers_lead_time_wins_the_roll_up(
        client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing, pricing="quote",
                               lead_time_days=3)).json()["id"]
    await _add_offer(client, admin_auth, costing, pid, vendor_name="Slow",
                     cost=900.0, lead_time_days=40)
    fast = (await _add_offer(client, admin_auth, costing, pid, vendor_name="Fast",
                             cost=1200.0, lead_time_days=10,
                             favorite=True)).json()
    assert fast["lead_time_calendar_days"] == 10

    listed = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    # The chosen supplier's date, not the other bidder's and not the stale
    # estimate typed on the position.
    assert listed["effective_lead_time_days"] == 10
    assert listed["effective_cost"] == 1200.0

    summ = (await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                             headers=admin_auth)).json()
    assert summ["max_lead_time_days"] == 10
    assert summ["total_position_cost"] == 1200.0


async def test_a_favorite_quoted_in_business_days_is_compared_on_the_calendar(
        client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    await _add_offer(client, admin_auth, costing, pid, vendor_name="Works days",
                     cost=500.0, lead_time_days=20,
                     lead_time_unit="business_days", favorite=True)
    listed = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    assert listed["effective_lead_time_days"] == 20
    assert listed["effective_lead_time_unit"] == "business_days"
    assert listed["effective_lead_time_calendar_days"] == 28

    summ = (await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                             headers=admin_auth)).json()
    assert summ["max_lead_time_days"] == 28
    assert summ["lead_time_by_department"][0]["lead_time_days"] == 28


# --- the quote document -----------------------------------------------------

async def _upload(client, auth, change_id, **form):
    return await client.post(
        f"/api/v1/changes/{change_id}/attachments",
        files={"file": ("quote.pdf", b"%PDF-1.4 q", "application/pdf")},
        data={k: str(v) for k, v in form.items()}, headers=auth)


async def test_a_vendor_quote_files_against_its_offer(client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    oid = (await _add_offer(client, admin_auth, costing, pid, cost=500.0)).json()["id"]

    res = await _upload(client, admin_auth, costing["change_id"],
                        kind="vendor_quote", costing_offer_id=oid)
    assert res.status_code in (200, 201), res.text
    assert res.json()["costing_offer_id"] == oid

    listed = (await client.get(_positions_url(costing), headers=admin_auth)).json()[0]
    docs = listed["offers"][0]["attachments"]
    assert [d["filename"] for d in docs] == ["quote.pdf"]


async def test_a_vendor_quote_must_name_an_offer(client, admin_auth, costing):
    res = await _upload(client, admin_auth, costing["change_id"],
                        kind="vendor_quote")
    assert res.status_code == 400
    assert "costing offer" in res.json()["detail"]


async def test_only_a_vendor_quote_may_name_an_offer(client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    oid = (await _add_offer(client, admin_auth, costing, pid, cost=500.0)).json()["id"]
    res = await _upload(client, admin_auth, costing["change_id"],
                        kind="general", costing_offer_id=oid)
    assert res.status_code == 400
    assert "vendor_quote" in res.json()["detail"]


async def test_a_quote_belongs_to_one_container_only(client, admin_auth, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    oid = (await _add_offer(client, admin_auth, costing, pid, cost=500.0)).json()["id"]
    res = await _upload(client, admin_auth, costing["change_id"],
                        kind="vendor_quote", costing_offer_id=oid,
                        assessment_id=costing["assessments"]["Tool Engineer"])
    assert res.status_code == 400
    assert "not to more than one" in res.json()["detail"]


async def test_a_stranger_cannot_document_another_departments_offer(
        client, admin_auth, session_factory, seed, costing):
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    oid = (await _add_offer(client, admin_auth, costing, pid, cost=500.0)).json()["id"]
    outsider = await _member(client, session_factory, seed, costing["dev"],
                             "posdev@test.io")
    res = await _upload(client, outsider, costing["change_id"],
                        kind="vendor_quote", costing_offer_id=oid)
    assert res.status_code == 400
    assert "costing department" in res.json()["detail"]


# --- tags -------------------------------------------------------------------

async def test_costing_tags_offer_common_plus_department_extras(
        client, admin_auth, costing):
    res = await client.get("/api/v1/changes/reference/costing-tags",
                           headers=admin_auth)
    assert res.status_code == 200, res.text
    common = [i["key"] for i in res.json()["items"]]
    assert "tool_change" in common and "other" in common
    assert all(i["extra"] is False for i in res.json()["items"])

    res = await client.get(
        f"/api/v1/changes/reference/costing-tags?department_id={costing['tool']}",
        headers=admin_auth)
    keys = [i["key"] for i in res.json()["items"]]
    assert "tool_change" in keys              # common set is still there
    assert "hot_runner" in keys               # and the department's own


async def test_a_free_text_tag_is_accepted(client, admin_auth, costing):
    res = await _add_position(client, admin_auth, costing, tag="whatever_we_call_it",
                              est_cost=1.0)
    assert res.status_code == 201, res.text
    assert res.json()["tag"] == "whatever_we_call_it"


# --- the costing queue ------------------------------------------------------

async def _mark_nothing_impacted(session_factory, assessment_id):
    async with session_factory() as s:
        a = await s.get(ChangeAssessment, assessment_id)
        a.details = json.dumps({"impacts": [
            {"key": "cycle_time_change", "impacted": False},
            {"key": "scrap_increase", "impacted": False},
        ]})
        await s.commit()


async def test_costing_queue_skips_the_department_that_marked_nothing_impacted(
        client, admin_auth, session_factory, costing):
    detail = (await client.get(f"/api/v1/changes/{costing['change_id']}",
                               headers=admin_auth)).json()
    assert sorted(detail["costing_pending_department_ids"]) == sorted(
        [costing["tool"], costing["dev"]])

    await _mark_nothing_impacted(session_factory, costing["assessments"]["Development"])

    detail = (await client.get(f"/api/v1/changes/{costing['change_id']}",
                               headers=admin_auth)).json()
    assert detail["costing_pending_department_ids"] == [costing["tool"]]


async def test_nothing_impacted_but_a_cost_declared_still_owes_a_number(
        client, admin_auth, session_factory, costing):
    await _mark_nothing_impacted(session_factory, costing["assessments"]["Development"])
    async with session_factory() as s:
        a = await s.get(ChangeAssessment, costing["assessments"]["Development"])
        a.cost_impact = 500.0
        await s.commit()

    detail = (await client.get(f"/api/v1/changes/{costing['change_id']}",
                               headers=admin_auth)).json()
    assert sorted(detail["costing_pending_department_ids"]) == sorted(
        [costing["tool"], costing["dev"]])


async def test_the_costing_input_task_disappears_for_a_nothing_impacted_department(
        client, session_factory, seed, costing):
    dev_member = await _member(client, session_factory, seed, costing["dev"],
                               "posdev2@test.io")

    async def rows():
        res = await client.get("/api/v1/changes/my-tasks", headers=dev_member)
        assert res.status_code == 200, res.text
        return [t for t in res.json()
                if t["kind"] == "costing_input"
                and t["change_id"] == costing["change_id"]]

    assert len(await rows()) == 1
    await _mark_nothing_impacted(session_factory, costing["assessments"]["Development"])
    assert await rows() == []


async def test_a_position_answers_the_costing_queue(
        client, admin_auth, costing):
    await _add_position(client, admin_auth, costing, est_cost=42.0)
    detail = (await client.get(f"/api/v1/changes/{costing['change_id']}",
                               headers=admin_auth)).json()
    assert detail["costing_pending_department_ids"] == [costing["dev"]]


# --- summation --------------------------------------------------------------

async def test_positions_add_to_the_department_totals(client, admin_auth, costing):
    base = (await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                             headers=admin_auth)).json()
    assert base["totals"]["grand_total"] == 0.0

    await _add_position(client, admin_auth, costing, kind="internal_effort",
                        label="Assessment time", est_cost=300.0, hours=4.0)
    pid = (await _add_position(client, admin_auth, costing, kind="external",
                               pricing="quote", label="New nozzle",
                               lead_time_days=None)).json()["id"]
    await _add_offer(client, admin_auth, costing, pid, vendor_name="A",
                     cost=1000.0, shipping_cost=150.0, lead_time_days=30,
                     favorite=True)

    summ = (await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                             headers=admin_auth)).json()
    # 300 estimate + 4 h × 65 €/h at the home plant.
    assert summ["totals"]["one_time_internal"] == 560.0
    assert summ["totals"]["one_time_external"] == 1150.0
    assert summ["totals"]["grand_total"] == 1710.0

    dept = [d for d in summ["by_department"]
            if d["department_id"] == costing["tool"]][0]
    assert dept["one_time_internal"] == 560.0
    assert dept["one_time_external"] == 1150.0

    broken_out = summ["positions_by_department"][0]
    assert broken_out["department_id"] == costing["tool"]
    assert broken_out["position_cost"] == 1450.0
    assert broken_out["hours"] == 4.0
    assert broken_out["hours_cost"] == 260.0
    assert broken_out["unrated_hours"] is False
    assert broken_out["position_count"] == 2
    assert summ["total_position_cost"] == 1450.0
    assert summ["total_position_hours_cost"] == 260.0

    # The supplier's delivery date is a lead time like any other.
    assert summ["max_lead_time_days"] == 30
    # Positions carry no plant, so the per-plant matrix is untouched by them.
    assert summ["by_plant"] == []


async def _summation(client, auth, costing):
    res = await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                           headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def test_declared_hours_become_money_at_the_department_rate(
        client, admin_auth, costing):
    """The assessment time IS a cost. Reporting 6 h and no euros was the bug:
    Sales quotes euros."""
    await _add_position(client, admin_auth, costing, kind="internal_effort",
                        label="Time spent on the assessment", hours=6.0)
    summ = await _summation(client, admin_auth, costing)

    assert summ["totals"]["one_time_internal"] == 390.0     # 6 h × 65 €/h
    assert summ["totals"]["grand_total"] == 390.0
    dept = [d for d in summ["by_department"]
            if d["department_id"] == costing["tool"]][0]
    assert dept["one_time_internal"] == 390.0

    row = summ["positions_by_department"][0]
    assert row["hours"] == 6.0                 # the raw hours are still there
    assert row["hours_cost"] == 390.0
    assert row["position_cost"] == 0.0         # no estimate was given
    assert row["unrated_hours"] is False


async def test_an_external_positions_own_time_is_valued_too(
        client, admin_auth, costing):
    """Specifying and chasing a supplier is our time, and it is priced at our
    rate on top of the supplier's number."""
    pid = (await _add_position(client, admin_auth, costing, kind="external",
                               pricing="quote", label="New nozzle",
                               hours=2.0)).json()["id"]
    await _add_offer(client, admin_auth, costing, pid, cost=1000.0, favorite=True)

    summ = await _summation(client, admin_auth, costing)
    assert summ["totals"]["one_time_external"] == 1000.0    # the supplier
    assert summ["totals"]["one_time_internal"] == 130.0     # 2 h × 65 €/h
    assert summ["totals"]["grand_total"] == 1130.0
    row = summ["positions_by_department"][0]
    assert row["hours_cost"] == 130.0
    assert row["position_cost"] == 1000.0


async def test_hours_with_no_configured_rate_are_flagged_not_invented(
        client, admin_auth, session_factory, seed, costing):
    """A department with no rate at the costing plant is counted at zero and
    said so — an invented rate is a number somebody would quote."""
    async with session_factory() as s:
        unrated = Department(name="Quality", flow_type="action", is_active=True)
        s.add(unrated)
        await s.flush()
        s.add(ChangeAssessment(change_id=costing["change_id"],
                               department_id=unrated.id, stage_order=1,
                               verdict="feasible"))
        await s.commit()
        unrated_id = unrated.id

    res = await _add_position(client, admin_auth, costing,
                              department_id=unrated_id, kind="internal_effort",
                              label="Layout inspection time", hours=8.0)
    assert res.status_code == 201, res.text

    summ = await _summation(client, admin_auth, costing)
    assert summ["totals"]["one_time_internal"] == 0.0
    assert summ["totals"]["grand_total"] == 0.0
    row = [r for r in summ["positions_by_department"]
           if r["department_id"] == unrated_id][0]
    assert row["hours"] == 8.0          # the work is still on the record
    assert row["hours_cost"] == 0.0
    assert row["unrated_hours"] is True
    assert summ["total_position_hours_cost"] == 0.0


# --- the vendor decision (stage 5) ------------------------------------------
# The department's favorite is a RECOMMENDATION. Sales decides, Sales is
# accountable, and going against the recommendation has to say why.

async def _two_offers(client, admin_auth, costing):
    """A quoted external position with vendor A (the department's favorite)
    and the pricier vendor B behind it."""
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    a = (await _add_offer(client, admin_auth, costing, pid,
                          vendor_name="Vendor A", cost=1000.0,
                          favorite=True)).json()["id"]
    b = (await _add_offer(client, admin_auth, costing, pid,
                          vendor_name="Vendor B", cost=1500.0)).json()["id"]
    return pid, a, b


def _choose_url(costing, oid) -> str:
    return (f"/api/v1/changes/{costing['change_id']}/costing/offers/"
            f"{oid}/choose")


async def _choose(client, auth, costing, oid, **body):
    return await client.put(_choose_url(costing, oid), json=body, headers=auth)


async def _sales_member(client, session_factory, seed, email="sales@pos.test"):
    async with session_factory() as s:
        dept = Department(name="Sales", flow_type="action", is_active=True,
                          can_start_change=True)
        s.add(dept)
        await s.flush()
        dept_id = dept.id
        await s.commit()
    return await _member(client, session_factory, seed, dept_id, email)


async def _actions(client, auth, change_id):
    res = await client.get(f"/api/v1/changes/{change_id}/changelog", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def test_choosing_against_the_recommendation_needs_a_reason(
        client, admin_auth, costing):
    pid, a, b = await _two_offers(client, admin_auth, costing)

    res = await _choose(client, admin_auth, costing, b)
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "Vendor B" in detail and "Vendor A" in detail
    assert "Sales' to account for" in detail

    res = await _choose(client, admin_auth, costing, b,
                        reason="A cannot hold the date, B can")
    assert res.status_code == 201 or res.status_code == 200, res.text
    body = res.json()
    assert body["chosen"] is True
    assert body["chosen_reason"] == "A cannot hold the date, B can"
    assert body["chosen_by"] is not None and body["chosen_at"] is not None

    entries = await _actions(client, admin_auth, costing["change_id"])
    chosen = [e for e in entries if e["action"] == "vendor_chosen"]
    assert len(chosen) == 1
    assert ("Vendor chosen against the department recommendation"
            in chosen[0]["action_description"])
    assert "A cannot hold the date, B can" in chosen[0]["action_description"]


async def test_choosing_the_recommendation_needs_no_reason(
        client, admin_auth, costing):
    pid, a, b = await _two_offers(client, admin_auth, costing)
    res = await _choose(client, admin_auth, costing, a)
    assert res.status_code in (200, 201), res.text
    assert res.json()["chosen"] is True
    assert res.json()["chosen_reason"] is None

    entries = await _actions(client, admin_auth, costing["change_id"])
    chosen = [e for e in entries if e["action"] == "vendor_chosen"]
    assert "against the department recommendation" not in \
        chosen[0]["action_description"]


async def test_one_decision_per_position_and_re_deciding_is_audited(
        client, admin_auth, costing):
    pid, a, b = await _two_offers(client, admin_auth, costing)
    await _choose(client, admin_auth, costing, a)
    await _choose(client, admin_auth, costing, b, reason="A went bankrupt")

    listed = await client.get(_positions_url(costing), headers=admin_auth)
    position = listed.json()[0]
    flags = {o["vendor_name"]: o["chosen"] for o in position["offers"]}
    assert flags == {"Vendor A": False, "Vendor B": True}
    # The reversed decision keeps no name on it.
    old = next(o for o in position["offers"] if o["vendor_name"] == "Vendor A")
    assert old["chosen_by"] is None and old["chosen_reason"] is None

    entries = await _actions(client, admin_auth, costing["change_id"])
    assert len([e for e in entries if e["action"] == "vendor_chosen"]) == 2


async def test_the_department_recommends_and_sales_decides(
        client, admin_auth, costing, session_factory, seed):
    """The tool shop may vote for its favorite; it may not sign the order."""
    pid, a, b = await _two_offers(client, admin_auth, costing)
    tool = await _member(client, session_factory, seed, costing["tool"],
                         "tool@pos.test")
    sales = await _sales_member(client, session_factory, seed)

    await _set_status(session_factory, costing["change_id"], "quoting")
    res = await _choose(client, tool, costing, b, reason="we like B")
    assert res.status_code == 403, res.text
    assert "Sales decides" in res.json()["detail"]

    res = await _choose(client, sales, costing, b, reason="B holds the date")
    assert res.status_code in (200, 201), res.text
    assert res.json()["chosen"] is True
    assert res.json()["chosen_by_name"] == "sales@pos.test"


async def test_the_decision_belongs_to_the_quoting_window(
        client, costing, session_factory, seed):
    sales = await _sales_member(client, session_factory, seed)
    admin = await login(client, "admin@test.io")
    pid, a, b = await _two_offers(client, admin, costing)

    # The change is still in costing: the offer is not being written yet.
    res = await _choose(client, sales, costing, a)
    assert res.status_code == 403, res.text

    await _set_status(session_factory, costing["change_id"], "quoting")
    assert (await _choose(client, sales, costing, a)).status_code in (200, 201)


async def test_summation_quotes_the_chosen_vendor_while_the_vote_stays_visible(
        client, admin_auth, costing):
    pid, a, b = await _two_offers(client, admin_auth, costing)
    url = f"/api/v1/changes/{costing['change_id']}/summation"

    summ = (await client.get(url, headers=admin_auth)).json()
    # Nobody has decided yet: the department's recommendation prices it.
    assert summ["total_position_cost"] == 1000.0

    await _choose(client, admin_auth, costing, b, reason="B holds the date")
    summ = (await client.get(url, headers=admin_auth)).json()
    # The money follows Sales' decision — that is what is being quoted.
    assert summ["total_position_cost"] == 1500.0
    assert summ["totals"]["one_time_external"] == 1500.0

    detail = summ["positions_by_department"][0]["positions"][0]
    # ...while the department's vote is still on the page next to it.
    assert detail["recommended_vendor"] == "Vendor A"
    assert detail["recommended_cost"] == 1000.0
    assert detail["chosen_vendor"] == "Vendor B"
    assert detail["chosen_cost"] == 1500.0
    assert detail["chosen_reason"] == "B holds the date"
    assert detail["choice_diverges"] is True

    # The position payload says the same thing without a summation.
    position = (await client.get(_positions_url(costing),
                                 headers=admin_auth)).json()[0]
    assert position["recommended_vendor"] == "Vendor A"
    assert position["chosen_vendor"] == "Vendor B"
    assert position["choice_diverges"] is True
    # effective_cost stays the DEPARTMENT's number; quoted_cost is the offer.
    assert position["effective_cost"] == 1000.0
    assert position["quoted_cost"] == 1500.0


async def test_with_no_vote_cast_any_offer_may_be_chosen_without_a_reason(
        client, admin_auth, costing):
    """A position nobody voted on carries no recommendation, so there is
    nothing to diverge from — demanding a justification for disagreeing with
    an opinion the department never expressed would be theatre."""
    pid = (await _add_position(client, admin_auth, costing,
                               pricing="quote")).json()["id"]
    a = (await _add_offer(client, admin_auth, costing, pid,
                          vendor_name="Vendor A", cost=1000.0)).json()["id"]
    b = (await _add_offer(client, admin_auth, costing, pid,
                          vendor_name="Vendor B", cost=1500.0)).json()["id"]

    res = await _choose(client, admin_auth, costing, b)
    assert res.status_code in (200, 201), res.text
    assert res.json()["chosen"] is True
    assert res.json()["chosen_reason"] is None

    position = (await client.get(_positions_url(costing),
                                 headers=admin_auth)).json()[0]
    assert position["recommended_vendor"] is None
    assert position["choice_diverges"] is False
    assert position["chosen_vendor"] == "Vendor B"
    # And the money still follows the decision.
    assert position["quoted_cost"] == 1500.0

    entries = await _actions(client, admin_auth, costing["change_id"])
    chosen = [e for e in entries if e["action"] == "vendor_chosen"]
    assert "against the department recommendation" not in \
        chosen[0]["action_description"]
