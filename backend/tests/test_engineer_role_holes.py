"""Holes the strategy-B audit found (any SSO user in one active PLM
department writes as 'engineer').

Each hole has a negative test (a plain department engineer is refused) and a
positive one (the right person still gets through):
- deleting parts and part files is admin only;
- cancelling a workflow is admin only, and never a change's own workflow
  (a change is withdrawn or rejected through the change flow);
- SEP gate and timing-form PM/Quality signatures need the department;
- PPAP approve/reject needs Quality (or admin) and a second pair of eyes;
- an inactive department grants nothing;
- a local-password row never outranks what the hub token says.
"""
import pytest
from sqlalchemy import select

from app.models.entities import User
from app.models.part import Part
from app.models.workflow import Department, UserDepartment, WfInstance, WfTemplate
from tests.conftest import _mint_cookie, make_department_member
from tests.test_engineer_role import _hub_cookie, _hub_user

pytestmark = pytest.mark.asyncio

ADMIN = _mint_cookie("admin@test.io")


async def _engineer(client, session_factory, email="e@ktx.io", dept=None):
    """A hub plm2_Viewer who is an engineer through one active department
    (or through the named one). Returns (user_id, cookie)."""
    uid = await _hub_user(client, session_factory, email,
                          dept_active=None if dept else True)
    if dept:
        await make_department_member(session_factory, uid, dept)
    return uid, _hub_cookie(email, "plm2_Viewer")


# --- 1. part and part-file deletion --------------------------------------

async def test_engineer_cannot_delete_a_part(client, seed, session_factory, part):
    _, h = await _engineer(client, session_factory)
    r = await client.delete(f"/api/v1/parts/{part['part_id']}", headers=h)
    assert r.status_code == 403, r.text
    async with session_factory() as s:
        assert await s.get(Part, part["part_id"]) is not None


async def test_admin_may_delete_a_part(client, seed, session_factory):
    r = await client.post("/api/v1/parts", headers=ADMIN, json={
        "project_id": seed["project_id"], "part_number": "DEL-1", "name": "Gone",
        "part_type": "sub_assembly", "data_classification": "confidential"})
    assert r.status_code in (200, 201), r.text
    r = await client.delete(f"/api/v1/parts/{r.json()['id']}", headers=ADMIN)
    assert r.status_code == 204, r.text


async def _part_file(session_factory, part_id, uploader):
    from app.models.part import PartFile
    async with session_factory() as s:
        f = PartFile(part_id=part_id, original_filename="a.step",
                     saved_filename="nope-a.step", file_size=1, file_type="step",
                     created_by=uploader)
        s.add(f)
        await s.commit()
        return f.id


async def test_engineer_cannot_delete_a_part_file(client, seed, session_factory, part):
    _, h = await _engineer(client, session_factory)
    fid = await _part_file(session_factory, part["part_id"], seed["admin_id"])
    r = await client.delete(f"/api/v1/parts/files/{fid}", headers=h)
    assert r.status_code == 403, r.text
    r = await client.delete(f"/api/v1/parts/files/{fid}", headers=ADMIN)
    assert r.status_code == 200, r.text


# --- 2. workflow cancel ----------------------------------------------------

async def _instance(session_factory, seed, change_id=None):
    async with session_factory() as s:
        t = WfTemplate(name=f"T{change_id}", is_active=True, created_by=seed["admin_id"])
        s.add(t)
        await s.flush()
        i = WfInstance(template_id=t.id, change_id=change_id, status="active",
                       started_by=seed["admin_id"])
        s.add(i)
        await s.commit()
        return i.id


async def test_engineer_cannot_cancel_a_workflow(client, seed, session_factory):
    _, h = await _engineer(client, session_factory)
    iid = await _instance(session_factory, seed)
    r = await client.post(f"/api/v1/workflow-instances/{iid}/cancel",
                          json={"reason": "x"}, headers=h)
    assert r.status_code == 403, r.text
    r = await client.post(f"/api/v1/workflow-instances/{iid}/cancel",
                          json={"reason": "x"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "canceled"


async def test_nobody_cancels_a_changes_workflow_directly(client, seed, session_factory):
    r = await client.post("/api/v1/changes", headers=ADMIN, json={
        "title": "T", "change_type": "physical_part", "project_id": seed["project_id"]})
    assert r.status_code in (200, 201), r.text
    iid = await _instance(session_factory, seed, change_id=r.json()["id"])
    _, h = await _engineer(client, session_factory)
    for who in (h, ADMIN):
        r = await client.post(f"/api/v1/workflow-instances/{iid}/cancel",
                              json={"reason": "x"}, headers=who)
        assert r.status_code in (403, 409), r.text
    async with session_factory() as s:
        assert (await s.get(WfInstance, iid)).status == "active"


# --- 3. signatures -------------------------------------------------------

async def _open_gate(client, auth, project_id):
    from tests.test_sep import _activate, _clear_gate_items, _get_sep
    await _activate(client, auth, project_id)
    gate = (await _get_sep(client, auth, project_id))["gates"][0]
    await _clear_gate_items(client, auth, gate)
    return gate


async def test_sep_gate_signature_needs_the_department(client, seed, session_factory):
    _, eng = await _engineer(client, session_factory)
    gate = await _open_gate(client, ADMIN, seed["project_id"])
    for role in ("pm", "quality"):
        r = await client.post(f"/api/v1/sep/gates/{gate['id']}/sign-off",
                              json={"role": role}, headers=eng)
        assert r.status_code == 403, (role, r.text)

    _, pm = await _engineer(client, session_factory, "pm@ktx.io", "Project Manager")
    _, qa = await _engineer(client, session_factory, "qa@ktx.io", "Quality")
    r = await client.post(f"/api/v1/sep/gates/{gate['id']}/sign-off",
                          json={"role": "quality"}, headers=pm)
    assert r.status_code == 403, r.text
    r = await client.post(f"/api/v1/sep/gates/{gate['id']}/sign-off",
                          json={"role": "pm"}, headers=pm)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/sep/gates/{gate['id']}/sign-off",
                          json={"role": "quality"}, headers=qa)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"


async def test_timing_form_pm_signature_needs_the_department(client, seed, session_factory, seed_forms):
    inst = await _submitted_signable(client, ADMIN, seed["project_id"])
    _, eng = await _engineer(client, session_factory)
    r = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign",
                          json={"role": "pm"}, headers=eng)
    assert r.status_code == 403, r.text
    _, pm = await _engineer(client, session_factory, "pm@ktx.io", "Project Manager")
    r = await client.post(f"/api/v1/forms/instances/{inst['id']}/sign",
                          json={"role": "pm"}, headers=pm)
    assert r.status_code == 200, r.text


async def _submitted_signable(client, auth, project_id):
    """A submitted project_legitimization form (signatures md + pm)."""
    r = await client.post(f"/api/v1/forms/projects/{project_id}/instances",
                          json={"key": "project_legitimization"}, headers=auth)
    assert r.status_code == 201, r.text
    inst = r.json()
    data = inst["data"]
    data["header"]["project_title"] = "P"
    data["budget"] = [{"item": "Tooling", "budget": 5}]
    r = await client.patch(f"/api/v1/forms/instances/{inst['id']}",
                           json={"data": data}, headers=auth)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/forms/instances/{inst['id']}/submit", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


async def _submitted_ppap(client, auth, revision_id):
    r = await client.post(f"/api/v1/quality/revisions/{revision_id}/ppap",
                          json={"level": 1}, headers=auth)
    assert r.status_code == 201, r.text
    ppap = r.json()
    for e in ppap["elements"]:
        if e["required"]:
            r = await client.patch(f"/api/v1/quality/ppap/elements/{e['id']}",
                                   json={"status": "na"}, headers=auth)
            assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/quality/ppap/{ppap['id']}/submit", headers=auth)
    assert r.status_code == 200, r.text
    return ppap["id"]


async def test_ppap_decision_needs_quality(client, seed, session_factory, part):
    _, eng = await _engineer(client, session_factory)
    pid = await _submitted_ppap(client, ADMIN, part["revision_id"])
    for verb in ("approve", "reject"):
        r = await client.post(f"/api/v1/quality/ppap/{pid}/{verb}", json={}, headers=eng)
        assert r.status_code == 403, (verb, r.text)
    _, qa = await _engineer(client, session_factory, "qa@ktx.io", "Quality")
    r = await client.post(f"/api/v1/quality/ppap/{pid}/approve", json={}, headers=qa)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


async def test_ppap_submitter_cannot_decide_own_ppap(client, seed, session_factory, part):
    _, qa = await _engineer(client, session_factory, "qa@ktx.io", "Quality")
    pid = await _submitted_ppap(client, qa, part["revision_id"])
    for verb in ("approve", "reject"):
        r = await client.post(f"/api/v1/quality/ppap/{pid}/{verb}", json={}, headers=qa)
        assert r.status_code == 403, (verb, r.text)
    r = await client.post(f"/api/v1/quality/ppap/{pid}/reject", json={}, headers=ADMIN)
    assert r.status_code == 200, r.text


# --- 4. inactive departments ---------------------------------------------

async def test_inactive_department_grants_no_department_rights(client, seed, session_factory):
    from app.services.change_service import ChangeService
    from app.services.workflow_service import WorkflowService
    uid, _ = await _engineer(client, session_factory, "s@ktx.io")
    sales_id = await make_department_member(session_factory, uid, "Sales")
    async with session_factory() as s:
        u = await s.get(User, uid)
        assert await ChangeService._user_in_department(s, u, "Sales")
        (await s.get(Department, sales_id)).is_active = False
        await s.commit()
    async with session_factory() as s:
        u = await s.get(User, uid)
        assert not await ChangeService._user_in_department(s, u, "Sales")
        assert sales_id not in await WorkflowService.get_user_department_ids(s, uid)
        assert not await WorkflowService._is_department_member(s, uid, sales_id)


# --- 5. local rows never outrank the hub ----------------------------------

async def _legacy(session_factory, seed, role="admin"):
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="legacy", email="legacy@ktx.io",
                 full_name="L", hashed_password="$2b$12$" + "x" * 53,
                 role=role, is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        d = Department(name="Anything", flow_type="action", is_active=True)
        s.add(d)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=d.id))
        await s.commit()
        return u.id


async def test_local_admin_row_drops_to_hub_role(client, seed, session_factory):
    uid = await _legacy(session_factory, seed)
    h = _hub_cookie("legacy@ktx.io", "plm2_Viewer")
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert me["effective_role"] == "engineer", me
    r = await client.post("/api/v1/workflow-templates",
                          json={"name": "Esc", "stages": []}, headers=h)
    assert r.status_code == 403, r.text
    async with session_factory() as s:   # the stored row itself is untouched
        assert (await s.get(User, uid)).role == "admin"


async def test_local_admin_row_with_hub_admin_stays_admin(client, seed, session_factory):
    await _legacy(session_factory, seed)
    h = _hub_cookie("legacy@ktx.io", "plm2_Admin")
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert me["effective_role"] == "admin", me


async def test_local_engineer_row_is_not_raised_by_hub_admin(client, seed, session_factory):
    me = (await client.get("/api/v1/auth/me", headers=ADMIN)).json()
    assert me["effective_role"] == "admin"
    me = (await client.get("/api/v1/auth/me", headers=_mint_cookie("eng@test.io"))).json()
    assert me["effective_role"] == "engineer", me


async def test_hub_cap_survives_a_rollback(client, seed, session_factory):
    from app.dependencies.auth import _cap_to_hub
    uid = await _legacy(session_factory, seed)
    async with session_factory() as s:
        u = await s.get(User, uid)
        _cap_to_hub(u, "engineer")
        assert u.role == "engineer"
        await s.rollback()            # expires the row; reload must re-cap
        await s.refresh(u)
        assert u.role == "engineer"
        await s.commit()              # and the cap is never written back
    async with session_factory() as s:
        assert (await s.get(User, uid)).role == "admin"
