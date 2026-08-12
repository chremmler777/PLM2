"""The quote stage: costing -> quoting -> quoted.

Writing the offer and waiting on the customer were one status, which made
"Sales still has to build this" indistinguishable from "the ball is in the
customer's court". They are now two, with the costing-side guards on the way in
and the price required on the way out — and both hops belong to Sales.
"""
import pytest
from datetime import datetime, timedelta

from app.models.change import ChangeRequest
from app.models.workflow import Department, UserDepartment
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def sales_world(session_factory, seed):
    """A customer-relevant change sitting in costing, plus a Sales member and
    an outsider — the two sides of the permission rule."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        sales = Department(name="Sales", flow_type="action", is_active=True,
                           can_start_change=True)
        other = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add_all([sales, other])
        await s.flush()
        users = {}
        for dept, email in ((sales, "qsales@test.io"), (other, "qtool@test.io")):
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=email, role="engineer",
                     hashed_password=get_password_hash("role-secret-1"),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=dept.id))
            users[dept.name] = u.id
        change = ChangeRequest(
            change_number="C-Q-1", title="quote me", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=users["Sales"], lead_id=users["Sales"],
            customer_relevant=True, status="costing",
            required_by_date=datetime.utcnow() + timedelta(days=20))
        s.add(change)
        await s.flush()
        # A change reaches costing with its blocking assessments in: the
        # costing-side guards read them on the way out again.
        from app.models.change import ChangeAssessment
        s.add(ChangeAssessment(
            change_id=change.id, department_id=other.id, stage_order=1,
            rasic_letter="R", status="submitted", verdict="feasible",
            submitted_at=datetime.utcnow()))
        await s.commit()
        return {"change_id": change.id, "sales_dept": sales.id,
                "other_dept": other.id, "users": users}


async def _sales(client):
    return await login(client, "qsales@test.io", ENGINEER_PASSWORD)


async def _outsider(client):
    return await login(client, "qtool@test.io", ENGINEER_PASSWORD)


async def _transition(client, auth, cid, to_status):
    return await client.post(f"/api/v1/changes/{cid}/transition",
                             json={"to_status": to_status}, headers=auth)


async def _set(session_factory, cid, **values):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in values.items():
            setattr(c, k, v)
        await s.commit()


# --- the chain --------------------------------------------------------------

async def test_costing_goes_through_quoting_on_its_way_to_quoted(
        client, session_factory, sales_world):
    sales = await _sales(client)
    cid = sales_world["change_id"]

    # The old one-hop route is gone: 'quoted' means the offer is out, and it
    # cannot be out before anybody wrote it.
    res = await _transition(client, sales, cid, "quoted")
    assert res.status_code == 400
    assert "Cannot move from 'costing' to 'quoted'" in res.json()["detail"]

    res = await _transition(client, sales, cid, "quoting")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "quoting"


async def test_quoting_cannot_be_sent_without_a_price(
        client, session_factory, sales_world):
    sales = await _sales(client)
    cid = sales_world["change_id"]
    assert (await _transition(client, sales, cid, "quoting")).status_code == 200

    res = await _transition(client, sales, cid, "quoted")
    assert res.status_code == 400
    assert "No quoted price recorded" in res.json()["detail"]

    await _set(session_factory, cid, quoted_price=12500.0)
    res = await _transition(client, sales, cid, "quoted")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "quoted"
    # Sending the offer is what freezes the quote milestone, not starting it.
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).quoted_at is not None


async def test_the_costing_guards_bite_on_the_way_into_quoting(
        client, session_factory, sales_world):
    """An open assessment blocks the offer: quoting work nobody has agreed to
    do is exactly what the costing guards exist to stop."""
    from app.models.change import ChangeAssessment
    sales = await _sales(client)
    cid = sales_world["change_id"]
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=cid,
                               department_id=sales_world["sales_dept"],
                               stage_order=1, rasic_letter="R",
                               status="active", verdict="pending"))
        await s.commit()

    res = await _transition(client, sales, cid, "quoting")
    assert res.status_code == 400
    assert "submitted" in res.json()["detail"]


async def test_quoting_can_step_back_to_costing(client, session_factory, sales_world):
    sales = await _sales(client)
    cid = sales_world["change_id"]
    assert (await _transition(client, sales, cid, "quoting")).status_code == 200
    res = await _transition(client, sales, cid, "costing")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "costing"


async def test_an_internal_change_never_enters_quoting(
        client, session_factory, sales_world):
    sales = await _sales(client)
    cid = sales_world["change_id"]
    await _set(session_factory, cid, customer_relevant=False)
    res = await _transition(client, sales, cid, "quoting")
    assert res.status_code == 400
    assert "Internal changes skip the quote" in res.json()["detail"]


# --- permission -------------------------------------------------------------

async def test_only_sales_may_open_and_send_the_quote(
        client, session_factory, sales_world):
    outsider = await _outsider(client)
    sales = await _sales(client)
    cid = sales_world["change_id"]

    res = await _transition(client, outsider, cid, "quoting")
    assert res.status_code == 403
    assert "Sales" in res.json()["detail"]

    assert (await _transition(client, sales, cid, "quoting")).status_code == 200
    await _set(session_factory, cid, quoted_price=999.0)

    res = await _transition(client, outsider, cid, "quoted")
    assert res.status_code == 403
    assert (await _transition(client, sales, cid, "quoted")).status_code == 200


async def test_an_admin_may_still_drive_the_quote_stage(
        client, admin_auth, sales_world):
    res = await _transition(client, admin_auth, sales_world["change_id"], "quoting")
    assert res.status_code == 200, res.text


# --- my-tasks ---------------------------------------------------------------

async def test_quoting_is_sales_open_task(client, session_factory, sales_world):
    sales = await _sales(client)
    cid = sales_world["change_id"]

    async def rows():
        res = await client.get("/api/v1/changes/my-tasks", headers=sales)
        assert res.status_code == 200, res.text
        return [t for t in res.json()
                if t["kind"] == "create_quote" and t["change_id"] == cid]

    assert await rows() == []           # nothing to build while still costing
    assert (await _transition(client, sales, cid, "quoting")).status_code == 200

    got = await rows()
    assert len(got) == 1
    assert got[0]["has_price"] is False
    # The quote deadline is still the active one while the offer is being
    # written — it has not gone out yet.
    assert got[0]["due_date"] is not None

    await _set(session_factory, cid, quoted_price=500.0)
    assert (await rows())[0]["has_price"] is True

    assert (await _transition(client, sales, cid, "quoted")).status_code == 200
    assert await rows() == []           # sent: the ball is with the customer


async def test_the_task_is_not_addressed_to_other_departments(
        client, session_factory, sales_world):
    sales = await _sales(client)
    outsider = await _outsider(client)
    assert (await _transition(client, sales, sales_world["change_id"],
                              "quoting")).status_code == 200
    res = await client.get("/api/v1/changes/my-tasks", headers=outsider)
    assert [t for t in res.json() if t["kind"] == "create_quote"] == []
