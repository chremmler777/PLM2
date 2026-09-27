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
    # no position on the row: its owner is unknown, so the vendor and the
    # position are hidden too (the costing-name rule, round 3)
    assert vc["action_description"] == "Vendor chosen"
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


# ===========================================================================
# Round 2 (security review of 49cf1fdf)
# ===========================================================================
ACTS = "X-Acts-As-Department"


async def _admin(client, acts=None):
    h = await login(client, "admin@test.io")
    return {**h, ACTS: str(acts)} if acts is not None else h


async def _quality_dept(session_factory):
    from sqlalchemy import select
    async with session_factory() as s:
        return (await s.execute(select(Department.id).where(
            Department.name == "Quality"))).scalar_one()


async def _set_lead(session_factory, cid, uid):
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).lead_id = uid
        await s.commit()


# --- HIGH: nobody makes themselves lead; header fields follow the UI rights -

async def test_patch_lead_id_takeover_is_refused(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    aid = await _vendor_quote(session_factory, offer_world)
    qid = await _user(session_factory, seed, "q", "Quality")
    q = await _auth(client, "q")
    url = f"/api/v1/changes/{cid}"
    res = await client.patch(url, headers=q, json={"lead_id": qid})
    assert res.status_code == 403, res.text
    res = await client.patch(url, headers=q, json={"estimated_cost": 1.0})
    assert res.status_code == 403, res.text
    # the takeover would have opened the quote: still closed
    assert (await client.get(_dl(cid, aid), headers=q)).status_code == 403
    # an admin acting as Quality is Quality here
    res = await client.patch(url, headers=await _admin(
        client, await _quality_dept(session_factory)), json={"lead_id": qid})
    assert res.status_code == 403, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).lead_id is None


async def test_lead_hand_over_by_lead_pm_admin_is_logged(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    tool = offer_world["users"]["tool"]
    sales = offer_world["users"]["sales"]
    qid = await _user(session_factory, seed, "q", "Quality")
    url = f"/api/v1/changes/{cid}"
    await _set_lead(session_factory, cid, tool)
    # the current lead hands over
    res = await client.patch(url, headers=await _off(client, "tool"),
                             json={"lead_id": sales})
    assert res.status_code == 200, res.text
    # PM re-assigns
    res = await client.patch(url, headers=await _off(client, "pm"),
                             json={"lead_id": qid})
    assert res.status_code == 200, res.text
    # the admin too
    res = await client.patch(url, headers=await _admin(client),
                             json={"lead_id": tool})
    assert res.status_code == 200, res.text
    # the former lead is no longer entitled
    res = await client.patch(url, headers=await _off(client, "sales"),
                             json={"lead_id": sales})
    assert res.status_code == 403, res.text
    log = (await client.get(f"{url}/changelog", headers=await _admin(client))).json()
    moves = [(r["old_value"], r["new_value"]) for r in log
             if r["action"] == "lead_changed"]
    assert moves == [(str(tool), str(sales)), (str(sales), str(qid)),
                     (str(qid), str(tool))]


async def test_patch_fields_follow_ui_rights(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    await _user(session_factory, seed, "q", "Quality")
    q = await _auth(client, "q")
    url = f"/api/v1/changes/{cid}"
    for body in ({"priority": "high"}, {"title": "mine now"},
                 {"description": "rewritten"}, {"estimated_cost": 5.0},
                 {"required_by_date": "2031-01-01T00:00:00",
                  "required_by_reason": "because"}):
        res = await client.patch(url, headers=q, json=body)
        assert res.status_code == 403, (body, res.text)
    # an unchanged value moves nothing and needs no right
    cur = (await client.get(url, headers=q)).json()
    res = await client.patch(url, headers=q, json={"priority": cur["priority"]})
    assert res.status_code == 200, res.text
    # Quality is a governance role: the D1 master data is theirs
    res = await client.patch(url, headers=q, json={"issuer": "OEM"})
    assert res.status_code == 200, res.text
    # Sales writes the description, PM moves the quote deadline
    res = await client.patch(url, headers=await _off(client, "sales"),
                             json={"description": "Rib +0.7 mm"})
    assert res.status_code == 200, res.text
    res = await client.patch(url, headers=await _off(client, "pm"),
                             json={"required_by_date": "2031-01-01T00:00:00",
                                   "required_by_reason": "customer moved SOP"})
    assert res.status_code == 200, res.text
    # priority is the lead's (or admin's)
    res = await client.patch(url, headers=await _off(client, "sales"),
                             json={"priority": "high"})
    assert res.status_code == 403, res.text
    res = await client.patch(url, headers=await _admin(client), json={"priority": "high"})
    assert res.status_code == 200, res.text


# --- MEDIUM: who may delete evidence and plain documents --------------------

async def _docs(session_factory, world, verdict_submitted=True):
    tool_dept = world["depts"]["Tool Engineer"]
    async with session_factory() as s:
        from datetime import datetime
        a = ChangeAssessment(change_id=world["change_id"], department_id=tool_dept,
                             rasic_letter="S", verdict="not_feasible",
                             status="submitted" if verdict_submitted else "active",
                             submitted_at=datetime.utcnow() if verdict_submitted else None)
        s.add(a)
        await s.flush()
        ids = {}
        for kind, extra in (("change_ppt", {"assessment_id": a.id}),
                            ("rfq", {"assessment_id": a.id}),
                            ("customer_email", {}), ("general", {})):
            fd, path = tempfile.mkstemp(suffix=".pdf")
            os.write(fd, b"doc")
            os.close(fd)
            att = ChangeAttachment(
                change_id=world["change_id"], filename=f"{kind}.pdf",
                stored_path=path, content_type="application/pdf", size_bytes=3,
                sha256="y" * 64, phase="post_scoping", kind=kind,
                uploaded_by=world["users"]["tool"], **extra)
            s.add(att)
            await s.flush()
            ids[kind] = att.id
        await s.commit()
        return ids


async def test_evidence_delete_mirrors_attach_rule_and_freezes(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    ids = await _docs(session_factory, offer_world)
    await _user(session_factory, seed, "q", "Quality")
    q = await _auth(client, "q")
    tool = await _off(client, "tool")
    url = lambda k: f"/api/v1/changes/{cid}/attachments/{ids[k]}"  # noqa: E731
    for kind in ("change_ppt", "rfq"):
        assert (await client.delete(url(kind), headers=q)).status_code == 403
        # the department may file it, but the verdict it backs is submitted
        assert (await client.delete(url(kind), headers=tool)).status_code == 409
    assert (await client.delete(url("change_ppt"), headers=await _admin(
        client, offer_world["depts"]["Tool Engineer"]))).status_code == 409
    assert (await client.delete(url("change_ppt"),
                                headers=await _admin(client))).status_code == 204


async def test_evidence_of_open_assessment_is_removable_by_the_department(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    ids = await _docs(session_factory, offer_world, verdict_submitted=False)
    res = await client.delete(f"/api/v1/changes/{cid}/attachments/{ids['rfq']}",
                              headers=await _off(client, "tool"))
    assert res.status_code == 204, res.text


async def test_plain_documents_uploader_lead_pm_admin_only(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    ids = await _docs(session_factory, offer_world)
    await _user(session_factory, seed, "q", "Quality")
    q = await _auth(client, "q")
    url = lambda k: f"/api/v1/changes/{cid}/attachments/{ids[k]}"  # noqa: E731
    for kind in ("customer_email", "general"):
        assert (await client.delete(url(kind), headers=q)).status_code == 403
        assert (await client.delete(url(kind), headers=await _off(
            client, "sales"))).status_code == 403
    # the uploader (Tool) and PM
    assert (await client.delete(url("general"), headers=await _off(
        client, "tool"))).status_code == 204
    assert (await client.delete(url("customer_email"), headers=await _off(
        client, "pm"))).status_code == 204


# --- LOW: a vendor quote's name in the changelog / audit --------------------

async def test_vendor_quote_name_hidden_in_changelog_and_audit(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    await _user(session_factory, seed, "q", "Quality")
    async with session_factory() as s:
        off = CostingOffer(position_id=offer_world["position_id"],
                           vendor_name="Hasco", cost=987.65,
                           created_by=offer_world["users"]["tool"])
        s.add(off)
        await s.flush()
        c = await s.get(ChangeRequest, cid)
        await ChangeService.append_changelog(
            s, c, "attachment_added",
            "Attached Hasco-987.pdf (post_scoping, vendor_quote)",
            offer_world["users"]["tool"],
            new_value={"filename": "Hasco-987.pdf", "phase": "post_scoping",
                       "kind": "vendor_quote", "costing_offer_id": off.id})
        await s.commit()
    q = await _auth(client, "q")
    tool = await _off(client, "tool")
    url = f"/api/v1/changes/{cid}/changelog"

    def added(rows):
        return next(r for r in rows if r["action"] == "attachment_added")
    row = added((await client.get(url, headers=q)).json())
    assert "Hasco" not in row["action_description"]
    assert "Hasco" not in (row["new_value"] or "")
    assert "Hasco-987.pdf" in added((await client.get(url, headers=tool)).json())[
        "new_value"]
    audit = "/api/v1/audit?correlation_id=C-O-1"

    def audit_added(rows):
        return next(r for r in rows if r["action"] == "attachment_added")
    assert "Hasco" not in (audit_added((await client.get(
        audit, headers=q)).json())["new_values"] or "")
    assert "Hasco-987.pdf" in audit_added((await client.get(
        audit, headers=tool)).json())["new_values"]
    csv = (await client.get("/api/v1/audit/export?correlation_id=C-O-1",
                            headers=q)).text
    assert "Hasco-987" not in csv


# --- INFO: an acting admin loses cross-org visibility -----------------------

async def test_acting_admin_is_org_scoped(client, offer_world, session_factory, seed):
    from app.models.entities import Plant
    async with session_factory() as s:
        org = Organization(name="B", code="b", is_active=True)
        s.add(org)
        await s.flush()
        pl = Plant(organization_id=org.id, name="PB", code="pb", location="X",
                   is_active=True)
        s.add(pl)
        await s.flush()
        pr = Project(plant_id=pl.id, name="PrB", code="prb", status="active")
        s.add(pr)
        await s.flush()
        c = ChangeRequest(change_number="C-B-1", title="org B", reason="r",
                          change_type="physical_part", project_id=pr.id,
                          raised_by=seed["admin_id"])
        s.add(c)
        await s.commit()
        cb = c.id
    url = f"/api/v1/changes/{cb}"
    acting = await _admin(client, offer_world["depts"]["Tool Engineer"])
    assert (await client.get(url, headers=acting)).status_code == 404
    assert (await client.get(url, headers=await _admin(client))).status_code == 200


# ===========================================================================
# Round 3 (re-review of 3a1be470)
# ===========================================================================

async def _loose(session_factory, cid, kind, by, **kw):
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.write(fd, b"doc")
    os.close(fd)
    async with session_factory() as s:
        att = ChangeAttachment(change_id=cid, filename=f"{kind}.pdf", stored_path=path,
                               content_type="application/pdf", size_bytes=3,
                               sha256="z" * 64, phase="post_scoping", kind=kind,
                               uploaded_by=by, **kw)
        s.add(att)
        await s.commit()
        return att.id


async def _org2(session_factory):
    from app.models.entities import Plant
    async with session_factory() as s:
        org = Organization(name="Org2", code="org2", is_active=True)
        s.add(org)
        await s.flush()
        pl = Plant(organization_id=org.id, name="P2", code="p2", location="US",
                   is_active=True)
        s.add(pl)
        await s.flush()
        pr = Project(plant_id=pl.id, name="Proj2", code="pj2", status="active")
        s.add(pr)
        await s.commit()
        return org.id, pl.id, pr.id


# --- HIGH: every attachment kind defaults to uploader / lead / PM / admin ---

async def test_every_attachment_kind_defaults_to_uploader_lead_pm_admin(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    tool_id = offer_world["users"]["tool"]
    await _user(session_factory, seed, "q", "Quality")
    q = await _auth(client, "q")
    tool = await _off(client, "tool")
    for kind in ("rejection_letter", "rfq", "change_ppt", "info_request",
                 "info_response", "general", "customer_email"):
        aid = await _loose(session_factory, cid, kind, tool_id)
        url = f"/api/v1/changes/{cid}/attachments/{aid}"
        res = await client.delete(url, headers=q)
        assert res.status_code == 403, (kind, res.text)
        res = await client.delete(url, headers=tool)
        assert res.status_code == 204, (kind, res.text)


async def test_concern_documents_default_rule_and_freeze_when_settled(
        client, offer_world, session_factory, seed):
    from datetime import datetime
    from app.models.change import ChangeConcern
    cid = offer_world["change_id"]
    tool_id = offer_world["users"]["tool"]
    await _user(session_factory, seed, "q", "Quality")
    async with session_factory() as s:
        open_c = ChangeConcern(change_id=cid, kind="needs_info", note="q?",
                               raised_by=tool_id)
        closed_c = ChangeConcern(change_id=cid, kind="needs_info", note="q2?",
                                 raised_by=tool_id, withdrawn_at=datetime.utcnow())
        s.add_all([open_c, closed_c])
        await s.commit()
        open_id, closed_id = open_c.id, closed_c.id
    aid = await _loose(session_factory, cid, "info_response", tool_id,
                       concern_id=open_id)
    url = f"/api/v1/changes/{cid}/attachments/{aid}"
    assert (await client.delete(url, headers=await _auth(client, "q"))).status_code == 403
    assert (await client.delete(url, headers=await _off(client, "tool"))).status_code == 204
    aid = await _loose(session_factory, cid, "info_response", tool_id,
                       concern_id=closed_id)
    url = f"/api/v1/changes/{cid}/attachments/{aid}"
    assert (await client.delete(url, headers=await _off(client, "tool"))).status_code == 409
    assert (await client.delete(url, headers=await _admin(
        client, offer_world["depts"]["Tool Engineer"]))).status_code == 409
    assert (await client.delete(url, headers=await _admin(client))).status_code == 204


async def test_sent_rejection_letter_is_frozen(
        client, offer_world, session_factory, seed):
    from datetime import datetime
    cid = offer_world["change_id"]
    sales_id = offer_world["users"]["sales"]
    aid = await _loose(session_factory, cid, "rejection_letter", sales_id)
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).rejection_sent_at = datetime.utcnow()
        await s.commit()
    url = f"/api/v1/changes/{cid}/attachments/{aid}"
    assert (await client.delete(url, headers=await _off(client, "sales"))).status_code == 409
    assert (await client.delete(url, headers=await _off(client, "pm"))).status_code == 409
    assert (await client.delete(url, headers=await _admin(client))).status_code == 204


async def test_evidence_with_missing_assessment_falls_back_to_default(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    tool_id = offer_world["users"]["tool"]
    await _user(session_factory, seed, "q", "Quality")
    aid = await _loose(session_factory, cid, "change_ppt", tool_id,
                       assessment_id=99999)
    url = f"/api/v1/changes/{cid}/attachments/{aid}"
    assert (await client.delete(url, headers=await _auth(client, "q"))).status_code == 403
    assert (await client.delete(url, headers=await _off(client, "tool"))).status_code == 204


# --- vendor / position names in the offer rows of changelog and audit ------

async def test_vendor_names_hidden_in_offer_rows(
        client, offer_world, session_factory, seed):
    cid = offer_world["change_id"]
    pid = offer_world["position_id"]
    await _user(session_factory, seed, "q", "Quality")
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        uid = offer_world["users"]["tool"]
        await ChangeService.append_changelog(
            s, c, "costing_offer_added", "Offer from Meusburger on 'Insert rework': 1234.5",
            uid, new_value={"position_id": pid, "offer_id": 1,
                            "vendor_name": "Meusburger", "total_cost": 1234.5})
        await ChangeService.append_changelog(
            s, c, "costing_offer_deleted", "Offer from Meusburger on 'Insert rework' removed",
            uid, old_value={"position_id": pid, "vendor_name": "Meusburger"})
        await ChangeService.append_changelog(
            s, c, "vendor_chosen", "Vendor chosen: Meusburger on 'Insert rework'",
            offer_world["users"]["sales"],
            new_value={"position_id": pid, "offer_id": 1,
                       "vendor_name": "Meusburger", "recommended_vendor": "Hasco"})
        await s.commit()
    names = ("Meusburger", "Hasco", "Insert rework")
    q = await _auth(client, "q")
    tool = await _off(client, "tool")
    url = f"/api/v1/changes/{cid}/changelog"
    rows = [r for r in (await client.get(url, headers=q)).json()
            if r["action"] in ("costing_offer_added", "costing_offer_deleted",
                               "vendor_chosen")]
    assert len(rows) == 3
    for r in rows:
        text = f"{r['action_description']} {r['old_value']} {r['new_value']}"
        assert not any(n in text for n in names), text
    own = [r for r in (await client.get(url, headers=tool)).json()
           if r["action"] == "costing_offer_added"]
    assert "Meusburger" in own[0]["action_description"]
    audit = (await client.get("/api/v1/audit?correlation_id=C-O-1", headers=q)).json()
    for r in audit:
        if r["action"] in ("costing_offer_added", "costing_offer_deleted",
                           "vendor_chosen"):
            assert not any(n in f"{r['old_values']} {r['new_values']}"
                           for n in names), r
    csv = (await client.get("/api/v1/audit/export?correlation_id=C-O-1",
                            headers=q)).text
    assert "Meusburger" not in csv
    audit_tool = (await client.get("/api/v1/audit?correlation_id=C-O-1",
                                   headers=tool)).json()
    assert any("Meusburger" in (r["new_values"] or "") for r in audit_tool
               if r["action"] == "costing_offer_added")


# --- organization boundaries on create / lead / plants ----------------------

async def test_create_change_is_org_bound(client, offer_world, session_factory, seed):
    _, _, pr2 = await _org2(session_factory)
    sales = await _off(client, "sales")
    res = await client.post("/api/v1/changes", headers=sales, json={
        "project_id": pr2, "title": "x-org", "reason": "r",
        "change_type": "physical_part"})
    assert res.status_code == 404, res.text
    org2 = (await _org2_id(session_factory))
    stranger = await _user(session_factory, seed, "stranger", org_id=org2)
    # Sales does not name the lead (spec §16): lead_id is ignored, so no
    # foreign user can slip in that way either.
    from tests.conftest import KEEP_LEAD_RULE, login
    res = await client.post("/api/v1/changes", headers={**sales, KEEP_LEAD_RULE: "1"}, json={
        "project_id": seed["project_id"], "title": "x-lead", "reason": "r",
        "change_type": "physical_part", "lead_id": stranger})
    assert res.status_code == 200 and res.json()["lead_id"] is None, res.text
    # Whoever may name it (an admin) is held to the organization.
    admin = await login(client, "admin@test.io")
    res = await client.post("/api/v1/changes", headers=admin, json={
        "project_id": seed["project_id"], "title": "x-lead", "reason": "r",
        "change_type": "physical_part", "lead_id": stranger})
    assert res.status_code == 400, res.text
    res = await client.post("/api/v1/changes", headers=sales, json={
        "project_id": seed["project_id"], "title": "ok", "reason": "r",
        "change_type": "physical_part", "lead_id": offer_world["users"]["sales"]})
    assert res.status_code == 200, res.text


async def _org2_id(session_factory):
    from sqlalchemy import select
    async with session_factory() as s:
        return (await s.execute(select(Organization.id).where(
            Organization.code == "org2"))).scalar_one()


async def test_patch_lead_and_plants_stay_in_the_org(
        client, offer_world, session_factory, seed):
    org2, pl2, _ = await _org2(session_factory)
    stranger = await _user(session_factory, seed, "stranger", org_id=org2)
    cid = offer_world["change_id"]
    url = f"/api/v1/changes/{cid}"
    pm = await _off(client, "pm")
    res = await client.patch(url, headers=pm, json={"lead_id": stranger})
    assert res.status_code == 400, res.text
    res = await client.patch(url, headers=pm, json={"affected_plant_ids": [pl2]})
    assert res.status_code == 400, res.text
    async with session_factory() as s:
        own_plant = (await s.get(Project, seed["project_id"])).plant_id
    res = await client.patch(url, headers=pm, json={"affected_plant_ids": [own_plant]})
    assert res.status_code == 200, res.text


async def test_noop_patch_writes_no_history(client, offer_world, session_factory, seed):
    from sqlalchemy import func, select
    from app.models.change import ChangeChangelog
    from app.models.entities import AuditLog
    cid = offer_world["change_id"]
    url = f"/api/v1/changes/{cid}"
    admin = await _admin(client)
    cur = (await client.get(url, headers=admin)).json()

    async def counts():
        async with session_factory() as s:
            return ((await s.execute(select(func.count()).select_from(
                ChangeChangelog).where(ChangeChangelog.change_id == cid))).scalar(),
                (await s.execute(select(func.count()).select_from(AuditLog))).scalar())
    before = await counts()
    res = await client.patch(url, headers=admin, json={
        "title": cur["title"], "priority": cur["priority"],
        "customer_relevant": cur["customer_relevant"],
        "affected_plant_ids": cur.get("affected_plant_ids") or [],
        "required_by_date": cur["required_by_date"]})
    assert res.status_code == 200, res.text
    assert await counts() == before
    res = await client.patch(url, headers=admin, json={"title": "moved"})
    assert res.status_code == 200
    after = await counts()
    assert after[0] == before[0] + 1
