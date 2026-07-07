# backend/tests/test_change_org_scoping.py
"""Org scoping on change queries (Task 13): a viewer should only see changes
whose project belongs to their own organization. Changes with project_id=None
are visible to everyone (explicit no-silent-data-loss decision). Internal
service callers (viewer=None) are unaffected."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeRequest
from app.models.entities import Organization, Plant, Project, User
from app.services.change_service import ChangeService, _org_scope

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
        org = Organization(name="Org B", code="org-b", is_active=True)
        s.add(org)
        await s.flush()

        plant = Plant(organization_id=org.id, name="Plant B", code="plant-b",
                      location="US", is_active=True)
        s.add(plant)
        await s.flush()

        project = Project(plant_id=plant.id, name="Project B", code="proj-b", status="active")
        s.add(project)
        await s.flush()

        user = User(
            organization_id=org.id, username="orgb", email="orgb@test.io",
            full_name="Org B User", hashed_password=get_password_hash(ORG_B_PASSWORD),
            role="engineer", is_active=True, mfa_enabled=False,
        )
        s.add(user)
        await s.commit()

        return {"org_id": org.id, "project_id": project.id, "user_id": user.id}


@pytest.fixture
async def org_b_auth(client, org_b):
    return await login(client, "orgb@test.io", ORG_B_PASSWORD)


async def test_list_changes_scoped_to_viewer_org(client, eng_auth, org_b_auth, seed, org_b):
    change_a = await _create_change(client, eng_auth, seed["project_id"])
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    res = await client.get("/api/v1/changes", headers=eng_auth)
    assert res.status_code == 200, res.text
    ids = {c["id"] for c in res.json()}
    assert change_a["id"] in ids
    assert change_b["id"] not in ids


async def test_get_change_out_of_org_scope_is_404(client, eng_auth, org_b_auth, seed, org_b):
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    res = await client.get(f"/api/v1/changes/{change_b['id']}", headers=eng_auth)
    assert res.status_code == 404, res.text

    # The org-B viewer can still see their own change.
    res = await client.get(f"/api/v1/changes/{change_b['id']}", headers=org_b_auth)
    assert res.status_code == 200, res.text


async def test_org_scope_keeps_null_project_visible_to_everyone(seed):
    """`change_requests.project_id` is NOT NULL at the DB level (see migration
    019 / ChangeRequest.project_id: Mapped[int]), so a persisted change can
    never actually have project_id=None today - there's no code path in the
    app that produces one. The brief still calls for the defensive "NULL
    stays visible to everyone" branch in `_org_scope` (future-proofing, e.g.
    if that constraint is ever relaxed, or for reuse by Task 14's reports).
    We verify the branch exists and behaves correctly by inspecting the
    compiled statement rather than round-tripping a row that the schema
    forbids."""
    viewer = User(id=1, organization_id=seed["org_id"], role="viewer")
    stmt = _org_scope(select(ChangeRequest), viewer)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "change_requests.project_id IS NULL" in compiled
    assert "change_requests.project_id IN" in compiled
    assert " OR " in compiled


async def test_list_changes_viewer_none_returns_everything(session_factory, seed, org_b, client, eng_auth, org_b_auth):
    change_a = await _create_change(client, eng_auth, seed["project_id"])
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    async with session_factory() as s:
        changes = await ChangeService.list_changes(s)
        ids = {c.id for c in changes}
        assert change_a["id"] in ids
        assert change_b["id"] in ids


async def test_get_summation_out_of_org_scope_is_404(client, eng_auth, org_b_auth, seed, org_b):
    """GET /{id}/summation must be org-scoped like the sibling endpoints —
    a cross-org viewer gets 404, not a leaked cost summary."""
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    res = await client.get(f"/api/v1/changes/{change_b['id']}/summation", headers=eng_auth)
    assert res.status_code == 404, res.text

    res = await client.get(f"/api/v1/changes/{change_b['id']}/summation", headers=org_b_auth)
    assert res.status_code == 200, res.text


async def test_get_gates_out_of_org_scope_is_404(client, eng_auth, org_b_auth, seed, org_b):
    """GET /{id}/gates must be org-scoped like the sibling endpoints — a
    cross-org viewer gets 404, not another org's gate decisions."""
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    res = await client.get(f"/api/v1/changes/{change_b['id']}/gates", headers=eng_auth)
    assert res.status_code == 404, res.text

    res = await client.get(f"/api/v1/changes/{change_b['id']}/gates", headers=org_b_auth)
    assert res.status_code == 200, res.text


async def test_admin_sees_all_organizations(client, admin_auth, org_b_auth, seed, org_b):
    """An admin viewer (role='admin') bypasses org scoping entirely - the
    controller decision documented on _org_scope, mirroring the intent
    already noted on the dead get_org_filter helper."""
    change_a = await _create_change(client, admin_auth, seed["project_id"])
    change_b = await _create_change(client, org_b_auth, org_b["project_id"])

    res = await client.get("/api/v1/changes", headers=admin_auth)
    assert res.status_code == 200, res.text
    ids = {c["id"] for c in res.json()}
    assert change_a["id"] in ids
    assert change_b["id"] in ids

    res = await client.get(f"/api/v1/changes/{change_b['id']}", headers=admin_auth)
    assert res.status_code == 200, res.text
