"""The negotiation loop at 'quoted'.

The offer is out; what comes back is a sequence of rounds that ends in one
final result, and Sales' go-ahead is decided on that result. These tests pin
the four rules the record exists for: only the commercial crowd sees it, only
Sales writes it, it only exists while the quote is out, and a negotiation has
exactly one result.
"""
import pytest
from datetime import datetime, timedelta

from app.models.change import ChangeRequest, ChangeNegotiation
from app.models.workflow import Department, UserDepartment
from tests.conftest import login, ENGINEER_PASSWORD

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def nego_world(session_factory, seed):
    """A customer-relevant change sitting at 'quoted', with the four people the
    permission rules distinguish: a Sales member, a PM member (reads, does not
    write), a second Sales member (writes, but is not the author of anybody
    else's round), and an outsider."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        sales = Department(name="Sales", flow_type="action", is_active=True,
                           can_start_change=True)
        pm = Department(name="Project Manager", flow_type="action", is_active=True)
        other = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add_all([sales, pm, other])
        await s.flush()
        users = {}
        for dept, email in ((sales, "nsales@test.io"), (sales, "nsales2@test.io"),
                            (pm, "npm@test.io"), (other, "ntool@test.io")):
            u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                     email=email, full_name=email, role="engineer",
                     hashed_password=get_password_hash("role-secret-1"),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=dept.id))
            users[email] = u.id
        change = ChangeRequest(
            change_number="C-N-1", title="negotiate me", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=users["nsales@test.io"], lead_id=users["nsales@test.io"],
            customer_relevant=True, status="quoted", quoted_price=12500.0,
            quoted_at=datetime.utcnow(),
            required_by_date=datetime.utcnow() + timedelta(days=20))
        s.add(change)
        await s.flush()
        await s.commit()
        return {"change_id": change.id, "users": users}


async def _sales(client):
    return await login(client, "nsales@test.io", ENGINEER_PASSWORD)


async def _sales2(client):
    return await login(client, "nsales2@test.io", ENGINEER_PASSWORD)


async def _pm(client):
    return await login(client, "npm@test.io", ENGINEER_PASSWORD)


async def _outsider(client):
    return await login(client, "ntool@test.io", ENGINEER_PASSWORD)


async def _post(client, auth, cid, **body):
    body.setdefault("channel", "call")
    body.setdefault("note", "they want 10% off")
    return await client.post(f"/api/v1/changes/{cid}/negotiations",
                             json=body, headers=auth)


async def _set_status(session_factory, cid, status):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = status
        await s.commit()


# --- writing the rounds -----------------------------------------------------

async def test_sales_records_rounds_in_order(client, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]

    res = await _post(client, sales, cid, channel="call", note="wants 10% off",
                      counter_price=11250.0)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["channel"] == "call"
    assert body["counter_price"] == 11250.0
    assert body["is_final"] is False
    assert body["created_by_name"] == "nsales@test.io"

    res = await _post(client, sales, cid, channel="meeting",
                      note="held at 12000, they will check")
    assert res.status_code == 201, res.text
    # A round that moved no number is a legitimate round.
    assert res.json()["counter_price"] is None

    res = await client.get(f"/api/v1/changes/{cid}/negotiations", headers=sales)
    assert res.status_code == 200, res.text
    rows = res.json()
    assert [r["note"] for r in rows] == ["wants 10% off",
                                         "held at 12000, they will check"]


async def test_a_minimal_post_defaults_the_optional_halves(client, nego_world):
    """The UI omits counter_price and is_final when unset rather than sending
    null/false, and gates 'delete my own entry' on created_by — so an absent
    key must read as null/false, and the author id must ride on the row."""
    sales = await _sales(client)
    cid = nego_world["change_id"]
    res = await client.post(
        f"/api/v1/changes/{cid}/negotiations",
        json={"channel": "email", "note": "they acknowledged, no number yet"},
        headers=sales)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["counter_price"] is None
    assert body["is_final"] is False
    assert body["created_by"] == nego_world["users"]["nsales@test.io"]


async def test_channel_vocabulary_is_fixed(client, nego_world):
    sales = await _sales(client)
    res = await _post(client, sales, nego_world["change_id"], channel="carrier pigeon")
    assert res.status_code == 400
    assert "Invalid channel" in res.json()["detail"]


async def test_a_round_must_carry_its_result(client, nego_world):
    sales = await _sales(client)
    res = await _post(client, sales, nego_world["change_id"], note="")
    assert res.status_code == 422  # schema-level min_length


# --- who may write ----------------------------------------------------------

async def test_outsider_cannot_record_a_round(client, nego_world):
    outsider = await _outsider(client)
    res = await _post(client, outsider, nego_world["change_id"])
    assert res.status_code == 403
    assert "Sales" in res.json()["detail"]


async def test_pm_reads_but_does_not_write(client, nego_world):
    sales = await _sales(client)
    pm = await _pm(client)
    cid = nego_world["change_id"]
    assert (await _post(client, sales, cid)).status_code == 201

    res = await client.get(f"/api/v1/changes/{cid}/negotiations", headers=pm)
    assert res.status_code == 200, res.text
    assert len(res.json()) == 1

    assert (await _post(client, pm, cid)).status_code == 403


async def test_outsider_cannot_read_the_record(client, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]
    assert (await _post(client, sales, cid)).status_code == 201

    res = await client.get(f"/api/v1/changes/{cid}/negotiations",
                           headers=await _outsider(client))
    assert res.status_code == 403


async def test_admin_may_read_and_write(client, admin_auth, nego_world):
    cid = nego_world["change_id"]
    assert (await _post(client, admin_auth, cid)).status_code == 201
    res = await client.get(f"/api/v1/changes/{cid}/negotiations", headers=admin_auth)
    assert res.status_code == 200
    assert len(res.json()) == 1


# --- the status window ------------------------------------------------------

@pytest.mark.parametrize("wrong", ["quoting", "approved"])
async def test_rounds_only_exist_while_the_quote_is_out(
        client, session_factory, nego_world, wrong):
    sales = await _sales(client)
    cid = nego_world["change_id"]
    await _set_status(session_factory, cid, wrong)

    res = await _post(client, sales, cid)
    assert res.status_code == 400
    assert "quoted" in res.json()["detail"]


# --- one final result -------------------------------------------------------

async def test_final_is_exclusive(client, session_factory, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]

    first = (await _post(client, sales, cid, note="agreed at 11800",
                         counter_price=11800.0, is_final=True)).json()
    assert first["is_final"] is True

    # They came back to the table: the new result demotes the old one rather
    # than being refused.
    second = (await _post(client, sales, cid, note="reopened, agreed at 12100",
                          counter_price=12100.0, is_final=True)).json()
    assert second["is_final"] is True

    res = await client.get(f"/api/v1/changes/{cid}/negotiations", headers=sales)
    finals = [r for r in res.json() if r["is_final"]]
    assert [r["id"] for r in finals] == [second["id"]]


# --- the number the go-ahead is based on ------------------------------------

async def test_negotiated_final_price_shows_on_the_change_detail(
        client, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]

    res = await client.get(f"/api/v1/changes/{cid}", headers=sales)
    assert res.json()["negotiated_final_price"] is None

    # A non-final counter is not the basis for anything.
    await _post(client, sales, cid, note="wants 10% off", counter_price=11250.0)
    res = await client.get(f"/api/v1/changes/{cid}", headers=sales)
    assert res.json()["negotiated_final_price"] is None

    await _post(client, sales, cid, note="agreed at 11800",
                counter_price=11800.0, is_final=True)
    res = await client.get(f"/api/v1/changes/{cid}", headers=sales)
    body = res.json()
    assert body["negotiated_final_price"] == 11800.0
    # The offer we made stays the offer we made.
    assert body["quoted_price"] == 12500.0


async def test_a_final_round_without_a_number_exposes_nothing(client, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]
    await _post(client, sales, cid, note="accepted as quoted", is_final=True)
    res = await client.get(f"/api/v1/changes/{cid}", headers=sales)
    assert res.json()["negotiated_final_price"] is None


# --- deleting ---------------------------------------------------------------

async def test_only_the_author_or_an_admin_may_remove_a_round(
        client, admin_auth, nego_world):
    sales = await _sales(client)
    sales2 = await _sales2(client)
    cid = nego_world["change_id"]

    nid = (await _post(client, sales, cid)).json()["id"]
    res = await client.delete(f"/api/v1/changes/{cid}/negotiations/{nid}",
                              headers=sales2)
    assert res.status_code == 403

    res = await client.delete(f"/api/v1/changes/{cid}/negotiations/{nid}",
                              headers=sales)
    assert res.status_code == 204, res.text

    nid2 = (await _post(client, sales, cid)).json()["id"]
    res = await client.delete(f"/api/v1/changes/{cid}/negotiations/{nid2}",
                              headers=admin_auth)
    assert res.status_code == 204, res.text

    res = await client.get(f"/api/v1/changes/{cid}/negotiations", headers=sales)
    assert res.json() == []


async def test_a_round_cannot_be_removed_once_the_change_moved_on(
        client, session_factory, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]
    nid = (await _post(client, sales, cid)).json()["id"]
    await _set_status(session_factory, cid, "approved")

    res = await client.delete(f"/api/v1/changes/{cid}/negotiations/{nid}",
                              headers=sales)
    assert res.status_code == 400
    assert "quoted" in res.json()["detail"]


async def test_removing_a_round_of_another_change_is_a_404(
        client, session_factory, seed, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]
    nid = (await _post(client, sales, cid)).json()["id"]
    async with session_factory() as s:
        other = ChangeRequest(
            change_number="C-N-2", title="other", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=nego_world["users"]["nsales@test.io"],
            lead_id=nego_world["users"]["nsales@test.io"],
            customer_relevant=True, status="quoted")
        s.add(other)
        await s.commit()
        other_id = other.id

    res = await client.delete(f"/api/v1/changes/{other_id}/negotiations/{nid}",
                              headers=sales)
    assert res.status_code == 404


# --- the audit trail --------------------------------------------------------

async def test_every_round_writes_a_changelog_entry(client, nego_world):
    sales = await _sales(client)
    cid = nego_world["change_id"]

    await _post(client, sales, cid, note="wants 10% off", counter_price=11250.0)
    nid = (await _post(client, sales, cid, note="agreed at 11800",
                       counter_price=11800.0, is_final=True)).json()["id"]

    res = await client.get(f"/api/v1/changes/{cid}/changelog", headers=sales)
    assert res.status_code == 200, res.text
    actions = [e["action"] for e in res.json()]
    # The closing round is logged distinctly from the rounds on the way there.
    assert actions.count("negotiation_round") == 1
    assert actions.count("negotiation_final") == 1

    res = await client.delete(f"/api/v1/changes/{cid}/negotiations/{nid}",
                              headers=sales)
    assert res.status_code == 204, res.text
    res = await client.get(f"/api/v1/changes/{cid}/changelog", headers=sales)
    assert "negotiation_removed" in [e["action"] for e in res.json()]


async def test_the_final_flag_survives_the_round_trip(session_factory, client,
                                                      nego_world):
    """The exclusivity rule is enforced on the rows, not just in the response."""
    from sqlalchemy import select
    sales = await _sales(client)
    cid = nego_world["change_id"]
    await _post(client, sales, cid, note="a", is_final=True)
    await _post(client, sales, cid, note="b", is_final=True)
    async with session_factory() as s:
        rows = (await s.execute(select(ChangeNegotiation).where(
            ChangeNegotiation.change_id == cid).order_by(
            ChangeNegotiation.id))).scalars().all()
    assert [r.is_final for r in rows] == [False, True]
