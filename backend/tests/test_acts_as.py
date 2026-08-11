"""Acts-as department switch: a real admin walks the flow as one department,
with the admin bypass dropped, and both identities land in the audit trail.

Spec: docs/superpowers/specs/2026-07-22-acts-as-role-switch-design.md (D1-D5).
"""
import pytest
from sqlalchemy import select

from app.models.entities import AuditLog
from app.models.workflow import Department
from tests.conftest import login, satisfy_capture_gate

pytestmark = pytest.mark.asyncio

HEADER = "X-Acts-As-Department"


@pytest.fixture
async def depts(session_factory):
    """Sales (may start changes) and Development (confirms impact)."""
    async with session_factory() as s:
        sales = Department(name="Sales", flow_type="action", is_active=True,
                           can_start_change=True)
        dev = Department(name="Development", flow_type="action", is_active=True)
        off = Department(name="Retired", flow_type="action", is_active=False)
        s.add_all([sales, dev, off])
        await s.commit()
        return {"sales": sales.id, "dev": dev.id, "inactive": off.id}


def _acting(auth, dept_id):
    return {**auth, HEADER: str(dept_id)}


async def _create(client, auth, seed, title="acts-as"):
    return await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": title, "reason": "r",
        "change_type": "physical_part"}, headers=auth)


async def test_non_admin_sending_the_header_is_refused(client, seed, depts):
    viewer = await login(client, "eng@test.io", admin=False)
    res = await client.get("/api/v1/auth/me", headers=_acting(viewer, depts["sales"]))
    assert res.status_code == 403
    assert "admin" in res.json()["detail"].lower()


async def test_unknown_or_inactive_department_is_refused(client, admin_auth, depts):
    res = await client.get("/api/v1/auth/me",
                           headers=_acting(admin_auth, 999_999))
    assert res.status_code == 400
    res = await client.get("/api/v1/auth/me",
                           headers=_acting(admin_auth, depts["inactive"]))
    assert res.status_code == 400


async def test_me_reports_the_assumed_identity(client, admin_auth, depts):
    plain = (await client.get("/api/v1/auth/me", headers=admin_auth)).json()
    assert plain["acting_as"] is None
    assert plain["is_real_admin"] is True
    assert plain["effective_role"] == "admin"

    acting = (await client.get(
        "/api/v1/auth/me", headers=_acting(admin_auth, depts["sales"]))).json()
    assert acting["acting_as"] == {"id": depts["sales"], "name": "Sales"}
    assert acting["is_real_admin"] is True          # the real row is never rewritten
    assert acting["effective_role"] == "engineer"   # ...but the bypass is gone


async def test_acts_as_options_is_admin_only_and_lists_active(
        client, admin_auth, depts):
    res = await client.get("/api/v1/auth/acts-as/options", headers=admin_auth)
    assert res.status_code == 200, res.text
    names = {d["name"] for d in res.json()["departments"]}
    assert {"Sales", "Development"} <= names
    assert "Retired" not in names

    viewer = await login(client, "eng@test.io", admin=False)
    assert (await client.get("/api/v1/auth/acts-as/options",
                             headers=viewer)).status_code == 403


async def test_acting_as_sales_may_capture_but_not_confirm_impact(
        client, admin_auth, seed, part, depts):
    sales = _acting(admin_auth, depts["sales"])
    res = await _create(client, sales, seed, "sales capture")
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True}, headers=sales)
    await satisfy_capture_gate(client, sales, cid)
    assert (await client.post(f"/api/v1/changes/{cid}/transition",
                              json={"to_status": "scoping"},
                              headers=sales)).status_code == 200

    # Sales is not Development -> the impact lock is out of reach, admin or not
    res = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=sales)
    assert res.status_code == 403
    assert "Development" in res.json()["detail"]


async def test_acting_as_development_may_confirm_but_not_capture(
        client, admin_auth, seed, part, depts):
    # build the change as the plain admin first
    res = await _create(client, admin_auth, seed, "dev confirms")
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True},
                      headers=admin_auth)
    await satisfy_capture_gate(client, admin_auth, cid)
    await client.post(f"/api/v1/changes/{cid}/transition",
                      json={"to_status": "scoping"}, headers=admin_auth)

    dev = _acting(admin_auth, depts["dev"])
    assert (await _create(client, dev, seed, "nope")).status_code == 403
    res = await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=dev)
    assert res.status_code == 200, res.text


async def test_mutation_audits_both_identities(
        client, admin_auth, seed, depts, session_factory):
    sales = _acting(admin_auth, depts["sales"])
    res = await _create(client, sales, seed, "audited capture")
    assert res.status_code == 200, res.text
    cid = res.json()["id"]

    async with session_factory() as s:
        rows = (await s.execute(
            select(AuditLog).where(AuditLog.entity_type == "change",
                                   AuditLog.entity_id == cid))).scalars().all()
    assert rows, "change creation must be audited"
    row = rows[0]
    assert row.user_id == seed["admin_id"]              # effective identity
    assert row.real_user_id == seed["admin_id"]         # ...and the human
    assert row.acting_as_department_id == depts["sales"]


async def test_ordinary_requests_are_untouched(
        client, admin_auth, seed, depts, session_factory):
    """No header -> nothing about the request changes, audit columns stay null."""
    res = await _create(client, admin_auth, seed, "plain")
    cid = res.json()["id"]
    async with session_factory() as s:
        row = (await s.execute(
            select(AuditLog).where(AuditLog.entity_type == "change",
                                   AuditLog.entity_id == cid))).scalars().first()
    assert row.real_user_id is None
    assert row.acting_as_department_id is None
