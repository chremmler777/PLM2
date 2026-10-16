"""ECR-solid C15 (lane L7, no switch): book hours.

One "Book hours" dialog on any open change, until 7 days after close or
cancel: department (yours), hours (> 0, one day at most), the day worked
(today back 21 days), optionally for a colleague; the lead's Coordination
row. Each booking stores its source (a confirmed estimate or typed) and
the change's status. The state prefills the confirm with the department's
estimate ("your estimate: 6 h"). The P&L effort column reads the
internal_effort positions. The effort report names the departments with
work and no booking ("not booked", never 0).
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models.change import ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.change_impl import ImplementationBooking
from app.utils.clock import business_today
from tests.conftest import login
from tests.test_ecr_solid_gates import _change, admin, depts, people  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _with_estimate(client, admin, seed, session_factory, depts, status="in_assessment",
                         **values):
    cid = await _change(client, admin, seed, session_factory, status, **values)
    async with session_factory() as s:
        s.add(CostingPosition(change_id=cid, department_id=depts["Development"],
                              label="Assessment", kind="internal_effort", pricing="estimate",
                              hours=6.0, created_by=seed["admin_id"]))
        s.add(CostingPosition(change_id=cid, department_id=depts["Tool Engineer"],
                              label="Rework", kind="own_time", pricing="estimate",
                              hours=10.0, created_by=seed["admin_id"]))
        await s.commit()
    return cid


async def _book(client, auth, cid, **body):
    return await client.post(f"/api/v1/changes/{cid}/hours", json=body, headers=auth)


async def test_book_hours_in_assessment_with_the_estimate_prefilled(
        client, admin, seed, depts, people, session_factory):
    cid = await _with_estimate(client, admin, seed, session_factory, depts)
    dev = people["Development"][1]
    st = (await client.get(f"/api/v1/changes/{cid}/hours", headers=dev)).json()
    mine = {m["department_id"]: m for m in st["mine"]}[depts["Development"]]
    assert mine["prefill_hours"] == 6.0 and mine["source_label"] == "your estimate: 6 h"
    res = await _book(client, dev, cid, department_id=depts["Development"], hours=6,
                      source="estimate")
    assert res.status_code == 201, res.text
    st = res.json()
    row = {r["department_id"]: r for r in st["departments"]}[depts["Development"]]
    assert row["booked_hours"] == 6.0 and row["estimate_hours"] == 6.0
    b = st["bookings"][0]
    assert b["source"] == "estimate" and b["status_at_booking"] == "in_assessment"
    assert b["work_date"] == business_today().isoformat()
    mine = {m["department_id"]: m for m in st["mine"]}[depts["Development"]]
    assert mine["prefill_hours"] is None and "6 h booked" in mine["source_label"]


async def test_negative_bookings_that_are_refused(
        client, admin, seed, depts, people, session_factory):
    cid = await _with_estimate(client, admin, seed, session_factory, depts)
    dev = people["Development"][1]
    d = depts["Development"]
    # not my department
    res = await _book(client, dev, cid, department_id=depts["Tool Engineer"], hours=2)
    assert res.status_code == 403
    # zero hours: not booked, never a 0
    res = await _book(client, dev, cid, department_id=d, hours=0)
    assert res.status_code == 400 and "not booked" in res.json()["detail"]
    res = await _book(client, dev, cid, department_id=d, hours=25)
    assert res.status_code == 400
    # the future, more than 21 days back
    res = await _book(client, dev, cid, department_id=d, hours=2,
                      work_date=(business_today() + timedelta(days=1)).isoformat())
    assert res.status_code == 400
    res = await _book(client, dev, cid, department_id=d, hours=2,
                      work_date=(business_today() - timedelta(days=22)).isoformat())
    assert res.status_code == 400
    # Coordination is the lead's row
    res = await _book(client, dev, cid, department_id=d, hours=1, coordination=True)
    assert res.status_code == 403
    # 21 days back is fine, for a colleague
    res = await _book(client, dev, cid, department_id=d, hours=3,
                      work_date=(business_today() - timedelta(days=21)).isoformat(),
                      booked_for="toolmaker Hans")
    assert res.status_code == 201, res.text
    assert res.json()["bookings"][0]["booked_for"] == "toolmaker Hans"


async def test_the_lead_books_coordination(client, admin, seed, depts, session_factory):
    cid = await _with_estimate(client, admin, seed, session_factory, depts)
    lead = await login(client, "eng@test.io", admin=False)   # seeded lead, Development
    res = await _book(client, lead, cid, department_id=depts["Development"], hours=1.5,
                      coordination=True)
    assert res.status_code == 201, res.text
    assert res.json()["bookings"][0]["activity"] == "coordination"
    assert res.json()["can_coordinate"] is True


async def test_window_ends_seven_days_after_close(
        client, admin, seed, depts, people, session_factory):
    cid = await _with_estimate(client, admin, seed, session_factory, depts, status="closed",
                               closed_at=datetime.utcnow() - timedelta(days=3))
    dev = people["Development"][1]
    assert (await _book(client, dev, cid, department_id=depts["Development"],
                        hours=2)).status_code == 201
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid).values(
            closed_at=datetime.utcnow() - timedelta(days=8)))
        await s.commit()
    res = await _book(client, dev, cid, department_id=depts["Development"], hours=2)
    assert res.status_code == 400 and "7 days" in res.json()["detail"]   # NEGATIVE


async def test_effort_report_names_not_booked(
        client, admin, seed, depts, people, session_factory):
    cid = await _with_estimate(client, admin, seed, session_factory, depts)
    await _book(client, people["Development"][1], cid, department_id=depts["Development"],
                hours=5)
    # NEGATIVE: a plain department member does not read the report
    res = await client.get("/api/v1/reports/ecr-effort", headers=people["Development"][1])
    assert res.status_code == 403
    res = await client.get("/api/v1/reports/ecr-effort", headers=people["Project Manager"][1])
    assert res.status_code == 200, res.text
    row = next(r for r in res.json()["changes"] if r["change_id"] == cid)
    assert row["booked_hours"] == 5.0 and row["estimate_hours"] == 16.0
    assert row["not_booked"] == ["Tool Engineer"]


async def test_pnl_effort_reads_the_internal_effort_positions(
        client, admin, seed, depts, session_factory):
    """C15 (1): the P&L effort column is the internal_effort positions (6 h),
    not 0 from the assessments' empty effort_hours."""
    from app.models.entities import User
    from app.services.pnl_service import PnlService
    cid = await _with_estimate(client, admin, seed, session_factory, depts, status="quoted")
    async with session_factory() as s:
        rows = await PnlService.changes_pnl(s, await s.get(User, seed["admin_id"]))
    row = next(r for r in rows if r["change_id"] == cid)
    assert row["effort_hours"] == 6.0


# --- review loop 1 ------------------------------------------------------------

async def test_estimate_source_only_for_the_prefill_itself(
        client, admin, seed, depts, people, session_factory):
    cid = await _with_estimate(client, admin, seed, session_factory, depts)
    dev = people["Development"][1]
    res = await _book(client, dev, cid, department_id=depts["Development"], hours=4,
                      source="estimate")
    assert res.status_code == 201, res.text
    assert res.json()["bookings"][0]["source"] == "typed"     # 4 h is not the 6 h estimate


async def test_negative_an_inactive_department_takes_no_hours(
        client, admin, seed, depts, session_factory):
    from app.models.workflow import Department
    cid = await _with_estimate(client, admin, seed, session_factory, depts)
    async with session_factory() as s:
        (await s.get(Department, depts["Tool Engineer"])).is_active = False
        await s.commit()
    res = await _book(client, admin, cid, department_id=depts["Tool Engineer"], hours=2)
    assert res.status_code == 400 and "active" in res.json()["detail"]


async def test_stage8_booking_is_dated_and_in_the_dated_report(
        client, admin, seed, depts, people, session_factory):
    """No side door: the stage-8 booking is dated, so the date-filtered
    effort report counts it; PM books nobody else's hours there."""
    cid = await _with_estimate(client, admin, seed, session_factory, depts,
                               status="in_implementation")
    url = f"/api/v1/changes/{cid}/implementation/bookings"
    pm = people["Project Manager"][1]
    res = await client.post(url, headers=pm, json={
        "department_id": depts["Development"], "hours": 2})
    assert res.status_code == 403, res.text
    dev = people["Development"][1]
    res = await client.post(url, headers=dev, json={
        "department_id": depts["Development"], "hours": 2})
    assert res.status_code == 201, res.text
    assert res.json()["work_date"] == business_today().isoformat()
    today = business_today().isoformat()
    rep = (await client.get(f"/api/v1/reports/ecr-effort?since={today}&until={today}",
                            headers=pm)).json()
    row = next(r for r in rep["changes"] if r["change_id"] == cid)
    dev_row = next(d for d in row["departments"] if d["department_id"] == depts["Development"])
    assert dev_row["booked_hours"] == 2.0
