# backend/tests/test_audit_scoping.py
"""Org scoping on the unified audit API (Task 22): a non-admin viewer should
only see audit entries whose correlation_id resolves to a change in their own
organization (reusing Task 13's `_org_scope` change-number set). Entries with
no correlation_id, or a correlation_id belonging to another org's change, are
hidden from non-admins. Admins bypass scoping entirely - mirrors the existing
`_org_scope` admin bypass used for /changes and /reports.

Also covers GET /audit/verify?correlation_id=: the hash-chain check itself
stays global, but the response gains {correlation_entries, correlation_ok}
reporting coverage for just that correlation."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_password_hash
from app.models.entities import Organization, Plant, Project, User

from tests.conftest import login

pytestmark = pytest.mark.asyncio

ORG_B_PASSWORD = "org-b-secret-1"


async def _create_change(client, auth, project_id, **over):
    body = {"project_id": project_id, "title": "Wall thickness +0.2mm",
            "change_type": "physical_part", "reason": "Sink marks on Class-A surface"}
    body.update(over)
    res = await client.post("/api/v1/changes", json=body, headers=auth)
    assert res.status_code in (200, 201), res.text
    return res.json()


@pytest.fixture
async def org_b(session_factory):
    """A second org + plant + project + user, independent of `seed`'s org."""
    async with session_factory() as s:
        org = Organization(name="Org B", code="audit-org-b", is_active=True)
        s.add(org)
        await s.flush()

        plant = Plant(organization_id=org.id, name="Plant B", code="audit-plant-b",
                      location="US", is_active=True)
        s.add(plant)
        await s.flush()

        project = Project(plant_id=plant.id, name="Project B", code="audit-proj-b", status="active")
        s.add(project)
        await s.flush()

        user = User(
            organization_id=org.id, username="auditorgb", email="auditorgb@test.io",
            full_name="Audit Org B User", hashed_password=get_password_hash(ORG_B_PASSWORD),
            role="engineer", is_active=True, mfa_enabled=False,
        )
        s.add(user)
        await s.commit()

        return {"org_id": org.id, "project_id": project.id, "user_id": user.id}


@pytest.fixture
async def org_b_auth(client, org_b):
    return await login(client, "auditorgb@test.io", ORG_B_PASSWORD)


async def test_org_b_user_cannot_list_org_a_entries(client, eng_auth, org_b_auth, seed, org_b):
    change_a = await _create_change(client, eng_auth, seed["project_id"])
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    res = await client.get(f"/api/v1/audit?correlation_id={change_a['change_number']}", headers=org_b_auth)
    assert res.status_code == 200, res.text
    assert res.json() == []

    # org-B's own change is visible to them.
    res = await client.get(f"/api/v1/audit?correlation_id={change_b['change_number']}", headers=org_b_auth)
    assert res.status_code == 200, res.text
    assert len(res.json()) >= 1


async def test_org_b_user_cannot_list_unscoped_org_a_entries(client, eng_auth, org_b_auth, seed, org_b):
    """Without a correlation_id filter, listing all entries must still hide
    org-A's change-correlated rows from an org-B viewer."""
    change_a = await _create_change(client, eng_auth, seed["project_id"])

    res = await client.get("/api/v1/audit?limit=1000", headers=org_b_auth)
    assert res.status_code == 200, res.text
    numbers = {e["correlation_id"] for e in res.json()}
    assert change_a["change_number"] not in numbers


async def test_org_b_user_cannot_export_org_a_entries(client, eng_auth, org_b_auth, seed, org_b):
    change_a = await _create_change(client, eng_auth, seed["project_id"])

    res = await client.get(
        f"/api/v1/audit/export?correlation_id={change_a['change_number']}", headers=org_b_auth)
    assert res.status_code == 200
    assert change_a["change_number"] not in res.text

    res = await client.get(
        f"/api/v1/audit/export?correlation_id={change_a['change_number']}", headers=eng_auth)
    assert res.status_code == 200
    assert change_a["change_number"] in res.text


async def test_admin_can_list_and_export_any_org_entries(client, admin_auth, eng_auth, org_b_auth, seed, org_b):
    change_a = await _create_change(client, eng_auth, seed["project_id"])
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    res = await client.get("/api/v1/audit?limit=1000", headers=admin_auth)
    assert res.status_code == 200, res.text
    numbers = {e["correlation_id"] for e in res.json()}
    assert change_a["change_number"] in numbers
    assert change_b["change_number"] in numbers

    res = await client.get(
        f"/api/v1/audit/export?correlation_id={change_b['change_number']}", headers=admin_auth)
    assert res.status_code == 200
    assert change_b["change_number"] in res.text


async def test_verify_correlation_reports_scoped_coverage(client, eng_auth, seed):
    change = await _create_change(client, eng_auth, seed["project_id"])
    number = change["change_number"]

    res = await client.get(f"/api/v1/audit/verify?correlation_id={number}", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    # Backward-compatible global fields untouched.
    assert body["valid"] is True
    assert "checked" in body and "first_broken_id" in body
    # New scoped-coverage fields.
    assert body["correlation_entries"] >= 1
    assert body["correlation_ok"] is True


async def test_verify_without_correlation_id_omits_scoped_fields(client, eng_auth, seed):
    res = await client.get("/api/v1/audit/verify", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["correlation_entries"] is None
    assert body["correlation_ok"] is None


async def test_verify_correlation_unknown_number_is_not_ok(client, eng_auth, seed):
    res = await client.get("/api/v1/audit/verify?correlation_id=CR-2026-9999", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["correlation_entries"] == 0
    assert body["correlation_ok"] is False
