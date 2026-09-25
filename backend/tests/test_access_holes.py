"""Regression tests for access holes found against the real app.

Each test names the hole it closes: vendor quotes readable by any logged-in
user, cost lines writable by any department, non-blocking assessments
submittable by a non-member, cost notes leaking to non-cost roles, and change
routes that were not scoped to the viewer's organization.
"""
import os
import tempfile

import pytest

from app.auth.security import get_password_hash
from app.models.change import ChangeAssessment, ChangeAttachment, ChangeRequest
from app.models.change_cost import CostingOffer, DepartmentRate
from app.models.entities import Organization, Project, User
from app.models.workflow import Department, UserDepartment
from app.services.change_service import ChangeService
from tests.conftest import login
from tests.test_offers import offer_world  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def _user(session_factory, seed, key, dept_name=None, org_id=None):
    """An engineer, optionally in a (new) department, optionally in another org."""
    async with session_factory() as s:
        u = User(organization_id=org_id or seed["org_id"], username=f"hole-{key}",
                 email=f"hole-{key}@test.io", full_name=f"Hole {key}",
                 role="engineer", hashed_password=get_password_hash("role-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        if dept_name:
            d = Department(name=dept_name, flow_type="action", is_active=True)
            s.add(d)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=d.id))
        await s.commit()
        return u.id


async def _other_org_user(session_factory, seed):
    async with session_factory() as s:
        org = Organization(name="Other Org", code="other-org", is_active=True)
        s.add(org)
        await s.commit()
        org_id = org.id
    return await _user(session_factory, seed, "stranger", org_id=org_id)


async def _auth(client, key):
    return await login(client, f"hole-{key}@test.io")


async def _off(client, key):
    return await login(client, f"off-{key}@test.io")


async def _vendor_quote(session_factory, world):
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.write(fd, b"%PDF vendor Hasco price 987.65 EUR")
    os.close(fd)
    async with session_factory() as s:
        off = CostingOffer(position_id=world["position_id"], vendor_name="Hasco",
                           cost=987.65, created_by=world["users"]["tool"])
        s.add(off)
        await s.flush()
        att = ChangeAttachment(
            change_id=world["change_id"], filename="hasco-quote.pdf",
            stored_path=path, content_type="application/pdf", size_bytes=10,
            sha256="x" * 64, phase="post_scoping", kind="vendor_quote",
            costing_offer_id=off.id, uploaded_by=world["users"]["tool"])
        s.add(att)
        await s.commit()
        return att.id


def _dl(cid, aid):
    return f"/api/v1/changes/{cid}/attachments/{aid}/download"


# --- 1/2: vendor quotes follow the costing-position read rule ---------------

async def test_vendor_quote_download_is_department_scoped(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    aid = await _vendor_quote(session_factory, offer_world)
    await _user(session_factory, seed, "q", "Quality")
    res = await client.get(_dl(cid, aid), headers=await _auth(client, "q"))
    assert res.status_code == 403, res.text
    # the position's own department and the cost roles read it
    for key in ("tool", "sales", "pm"):
        res = await client.get(_dl(cid, aid), headers=await _off(client, key))
        assert res.status_code == 200, (key, res.text)
        assert b"987.65" in res.content


async def test_vendor_quote_download_needs_the_change_and_the_org(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    aid = await _vendor_quote(session_factory, offer_world)
    await _other_org_user(session_factory, seed)
    res = await client.get(_dl(cid, aid), headers=await _auth(client, "stranger"))
    assert res.status_code == 404
    # an attachment id under another change id does not resolve
    async with session_factory() as s:
        other = ChangeRequest(change_number="C-O-2", title="other", reason="r",
                              change_type="physical_part",
                              project_id=seed["project_id"],
                              raised_by=offer_world["users"]["sales"])
        s.add(other)
        await s.commit()
        other_id = other.id
    res = await client.get(_dl(other_id, aid), headers=await _off(client, "sales"))
    assert res.status_code == 404


async def test_detail_hides_vendor_quotes_from_other_departments(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    aid = await _vendor_quote(session_factory, offer_world)
    await _user(session_factory, seed, "q", "Quality")
    q = (await client.get(f"/api/v1/changes/{cid}",
                          headers=await _auth(client, "q"))).json()
    assert aid not in [a["id"] for a in q["attachments"]]
    for key in ("tool", "sales"):
        d = (await client.get(f"/api/v1/changes/{cid}",
                              headers=await _off(client, key))).json()
        assert aid in [a["id"] for a in d["attachments"]], key


async def test_vendor_quote_delete_needs_position_write(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    aid = await _vendor_quote(session_factory, offer_world)
    await _user(session_factory, seed, "q", "Quality")
    url = f"/api/v1/changes/{cid}/attachments/{aid}"
    res = await client.delete(url, headers=await _auth(client, "q"))
    assert res.status_code == 403
    res = await client.delete(url, headers=await _off(client, "pm"))
    assert res.status_code == 204, res.text


# --- 3: cost lines follow the costing-position write rule -------------------

async def test_cost_lines_put_follows_costing_write_rule(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    tool_dept = offer_world["depts"]["Tool Engineer"]
    await _user(session_factory, seed, "q", "Quality")
    async with session_factory() as s:
        plant = (await s.get(Project, seed["project_id"])).plant_id
        a = ChangeAssessment(change_id=cid, department_id=tool_dept,
                             verdict="feasible", cost_impact=4321.0)
        s.add(a)
        s.add(DepartmentRate(department_id=tool_dept, plant_id=plant,
                             hourly_rate=80.0))
        await s.commit()
        aid = a.id
    url = f"/api/v1/changes/{cid}/assessments/{aid}/cost-lines"
    body = {"lines": [{"plant_id": plant, "activity_label": "rework",
                       "demand_hours": 0, "external_cost": 1.0}]}
    # another department: never
    res = await client.put(url, headers=await _auth(client, "q"), json=body)
    assert res.status_code == 403, res.text
    # the department itself, outside costing (the change is quoting): no
    res = await client.put(url, headers=await _off(client, "tool"), json=body)
    assert res.status_code == 403, res.text
    # PM at any time
    res = await client.put(url, headers=await _off(client, "pm"), json=body)
    assert res.status_code == 200, res.text
    # the department itself while in costing
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).status = "costing"
        await s.commit()
    res = await client.put(url, headers=await _off(client, "tool"), json=body)
    assert res.status_code == 200, res.text
    # another org: not found
    await _other_org_user(session_factory, seed)
    res = await client.put(url, headers=await _auth(client, "stranger"), json=body)
    assert res.status_code == 404


# --- 4: non-blocking assessment submits need department membership ---------

async def test_non_blocking_assessment_submit_needs_membership(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    tool_dept = offer_world["depts"]["Tool Engineer"]
    await _user(session_factory, seed, "q", "Quality")
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=cid, department_id=tool_dept,
                               rasic_letter="S", status="active"))
        await s.commit()
    url = f"/api/v1/changes/{cid}/assessments"
    body = {"department_id": tool_dept, "verdict": "feasible"}
    res = await client.post(url, headers=await _auth(client, "q"), json=body)
    assert res.status_code == 400
    assert "member" in res.json()["detail"]
    res = await client.post(url, headers=await _off(client, "tool"), json=body)
    assert res.status_code == 200, res.text


async def test_bare_assessment_submit_needs_membership(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    await _user(session_factory, seed, "q", "Quality")
    sales_dept = offer_world["depts"]["Sales"]
    url = f"/api/v1/changes/{cid}/assessments"
    body = {"department_id": sales_dept, "verdict": "feasible"}
    res = await client.post(url, headers=await _auth(client, "q"), json=body)
    assert res.status_code == 400
    async with session_factory() as s:
        from sqlalchemy import select
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == sales_dept))).scalars().all()
        assert rows == []
    res = await client.post(url, headers=await _off(client, "sales"), json=body)
    assert res.status_code == 200, res.text


# --- 6: free-text cost notes are redacted for non-cost roles ----------------

async def test_cost_notes_redacted_on_change_response(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    await _user(session_factory, seed, "q", "Quality")
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.internal_approval_note = "approved at 12k"
        c.weight_delta_ack_note = "absorbed 3 EUR/pc"
        await s.commit()
    q = (await client.get(f"/api/v1/changes/{cid}",
                          headers=await _auth(client, "q"))).json()
    assert q["internal_approval_note"] is None
    assert q["weight_delta_ack_note"] is None
    sales = (await client.get(f"/api/v1/changes/{cid}",
                              headers=await _off(client, "sales"))).json()
    assert sales["internal_approval_note"] == "approved at 12k"
    assert sales["weight_delta_ack_note"] == "absorbed 3 EUR/pc"


async def test_changelog_notes_redacted_for_non_cost_roles(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    await _user(session_factory, seed, "q", "Quality")
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        uid = offer_world["users"]["sales"]
        await ChangeService.append_changelog(
            s, c, "vendor_chosen",
            "Vendor chosen against the department recommendation: Meusburger "
            "instead of Hasco on 'Insert rework' — Hasco 400 EUR dearer",
            uid, notes="Hasco 400 EUR dearer")
        await ChangeService.append_changelog(
            s, c, "costing_reopened", "Costing reopened: tool rate was 95 not 80",
            uid, notes="tool rate was 95 not 80")
        await ChangeService.append_changelog(
            s, c, "internal_costs_approved", "Internal costs approved (1.00)",
            uid, notes="approved at 12k")
        await ChangeService.append_changelog(
            s, c, "weight_delta_acknowledged",
            "Weight delta of +3 g acknowledged for the quote", uid,
            notes="absorbed 3 EUR/pc")
        await s.commit()
    url = f"/api/v1/changes/{cid}/changelog"
    rows = {r["action"]: r for r in (await client.get(
        url, headers=await _auth(client, "q"))).json()}
    vc = rows["vendor_chosen"]
    assert vc["notes"] is None and "400" not in vc["action_description"]
    assert vc["action_description"].endswith("on 'Insert rework'")
    assert rows["costing_reopened"]["action_description"] == "Costing reopened"
    assert rows["costing_reopened"]["notes"] is None
    assert rows["internal_costs_approved"]["notes"] is None
    assert rows["weight_delta_acknowledged"]["notes"] is None
    full = {r["action"]: r for r in (await client.get(
        url, headers=await _off(client, "sales"))).json()}
    assert full["vendor_chosen"]["notes"] == "Hasco 400 EUR dearer"
    assert full["costing_reopened"]["notes"] == "tool rate was 95 not 80"


# --- sweep: every change route is scoped to the viewer's organization -------

async def test_change_routes_are_org_scoped(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    await _other_org_user(session_factory, seed)
    h = await _auth(client, "stranger")
    base = f"/api/v1/changes/{cid}"
    calls = [
        ("get", f"{base}/implementation", None),
        ("get", f"{base}/recommended-departments", None),
        ("get", f"{base}/routing", None),
        ("post", f"{base}/routing/deviation/approve", None),
        ("post", f"{base}/transition", {"to_status": "costing"}),
        ("get", f"{base}/impact-tree", None),
        ("post", f"{base}/impacted-items/seed", None),
        ("post", f"{base}/assessments", {"department_id": 1, "verdict": "feasible"}),
        ("patch", base, {"title": "hijacked"}),
        ("post", f"{base}/sign-off", {"role": "pm"}),
        ("get", f"{base}/deviations", None),
        ("delete", f"{base}/attachments/1", None),
    ]
    for method, url, body in calls:
        kw = {"headers": h}
        if body is not None:
            kw["json"] = body
        res = await getattr(client, method)(url, **kw)
        assert res.status_code in (404, 422), (method, url, res.status_code, res.text)
        if res.status_code == 422:
            # a body the route rejects before it loads the change says nothing
            # about scoping; every call above is shaped to reach the loader.
            pytest.fail(f"{method} {url} rejected the body: {res.text}")
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).title == "offer me"
