"""Mother-plant changes (spec 2026-09-25 §14).

Capture with origin mother_plant (plant dropdown, reference, SOP), who may
start it, the side track (no assessment/costing/quote, scoping -> approved
hard-gated on the impact lock and the team being informed), the inform list
with its receipts, "Read and understood", my-tasks and cockpit items, the
release deadline from the SOP and the detailed plan seeded from their MS
Project file (or the SOP milestone), the "Inform mother plant" stamp instead
of the customer publish, the team confirmation set, P&L basis "none", the
level-3 escalation audience and migration 093's backfill.
"""
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeChangelog, ChangeRequest
from app.models.change_info import ChangeInfoReceipt
from app.models.change_plan import ChangePlanTask
from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import Department, UserDepartment
from tests.conftest import ENGINEER_PASSWORD, login, validate_timing

pytestmark = pytest.mark.asyncio

SOP = date.today() + timedelta(days=90)
URL = "/api/v1/changes"

XML = (
    '<?xml version="1.0"?><Project xmlns="http://schemas.microsoft.com/project">'
    '<DurationFormat>7</DurationFormat><Tasks>'
    '<Task><UID>1</UID><Name>WUG tool rework</Name><Start>2026-11-02T08:00:00</Start>'
    '<Duration>PT40H0M0S</Duration><OutlineLevel>1</OutlineLevel></Task>'
    '<Task><UID>2</UID><Name>WUG SOP</Name><Start>2026-12-01T08:00:00</Start>'
    '<Duration>PT0H0M0S</Duration><Milestone>1</Milestone><OutlineLevel>1</OutlineLevel>'
    '</Task></Tasks></Project>').encode()


@pytest.fixture
async def mp(session_factory, seed):
    """Departments (Sales flagged can_start_change, PM not flagged), one user
    per department plus a Quality member, a Development member."""
    async with session_factory() as s:
        depts = {}
        for name, starter in [("Sales", True), ("Project Manager", False),
                              ("Quality", False), ("Development", False),
                              ("Tool Engineer", False), ("Scheduling", False),
                              ("Manufacturing Engineer", False)]:
            d = Department(name=name, flow_type="action", is_active=True,
                           can_start_change=starter)
            s.add(d)
            await s.flush()
            depts[name] = d.id
        users = {}
        for key, dept in [("sales", "Sales"), ("pm", "Project Manager"),
                          ("quality", "Quality"), ("dev", "Development"),
                          ("tool", "Tool Engineer"), ("sched", "Scheduling"),
                          ("me", "Manufacturing Engineer")]:
            email = f"mp-{key}@test.io"
            u = User(organization_id=seed["org_id"], username=f"mp-{key}",
                     email=email, full_name=key.upper(), role="engineer",
                     hashed_password=get_password_hash(ENGINEER_PASSWORD),
                     is_active=True, mfa_enabled=False)
            s.add(u)
            await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[dept]))
            users[key] = u.id
        await s.commit()
    return {"depts": depts, "users": users, "seed": seed}


async def _auth(client, key):
    if key == "admin":
        return await login(client, "admin@test.io")
    return await login(client, f"mp-{key}@test.io", ENGINEER_PASSWORD)


async def _create(client, mp, key="pm", **extra):
    body = {"project_id": mp["seed"]["project_id"], "title": "WUG bracket",
            "change_type": "physical_part", "reason": "mother plant change",
            "origin": "mother_plant", "mother_plant_ref": "WUG-ECR-4711",
            "mother_plant_sop": SOP.isoformat(), **extra}
    return await client.post(URL, json=body, headers=await _auth(client, key))


async def _set(session_factory, cid, **fields):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        for k, v in fields.items():
            setattr(c, k, v)
        await s.commit()


async def _to_scoping(client, session_factory, mp, **extra):
    r = await _create(client, mp, **extra)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    await _set(session_factory, cid, status="scoping")
    return cid


async def _send(client, mp, cid, names=("Tool Engineer", "Development"), key="pm"):
    return await client.post(
        f"{URL}/{cid}/mother-plant/info", headers=await _auth(client, key),
        json={"department_ids": [mp["depts"][n] for n in names],
              "message": "Read the WUG ECR"})


async def _ready_for_approval(client, session_factory, mp, **extra):
    cid = await _to_scoping(client, session_factory, mp, **extra)
    assert (await _send(client, mp, cid)).status_code == 200
    await _set(session_factory, cid, impact_confirmed_at=datetime.utcnow(),
               impact_confirmed_by=mp["users"]["dev"])
    return cid


async def _approve(client, cid, key="pm"):
    return await client.post(f"{URL}/{cid}/transition", headers=await _auth(client, key),
                             json={"to_status": "approved"})


# ----------------------------------------------------------------------
# Capture
# ----------------------------------------------------------------------
async def test_create_stores_origin_plant_ref_and_sop(client, mp):
    r = await _create(client, mp)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["origin"] == "mother_plant"
    assert c["mother_plant_name"] == "KTX Weissenburg (WUG)"      # the default
    assert c["mother_plant_ref"] == "WUG-ECR-4711"
    assert c["mother_plant_sop"] == SOP.isoformat()
    assert c["customer_relevant"] is False
    r = await _create(client, mp, mother_plant_name="KTX Solingen")
    assert r.json()["mother_plant_name"] == "KTX Solingen"


async def test_create_refuses_unknown_plant_missing_sop_and_customer_flag(client, mp):
    assert (await _create(client, mp, mother_plant_name="KTX Mars")).status_code == 400
    assert (await _create(client, mp, mother_plant_sop=None)).status_code == 400
    assert (await _create(client, mp, customer_relevant=True)).status_code == 400
    assert (await _create(client, mp, key="admin", origin="elsewhere")).status_code == 400


async def test_who_may_start_a_mother_plant_change(client, mp):
    # The internal PM starts it (not flagged can_start_change here); Sales,
    # though flagged can_start_change, does not; admins may.
    assert (await _create(client, mp, key="pm")).status_code == 200
    r = await _create(client, mp, key="sales")
    assert r.status_code == 403
    assert "Only Project Management (or an admin)" in r.json()["detail"]
    assert (await _create(client, mp, key="quality")).status_code == 403
    assert (await _create(client, mp, key="admin")).status_code == 200
    # ...but PM may not start an ordinary customer change without the flag
    r = await client.post(URL, headers=await _auth(client, "pm"), json={
        "project_id": mp["seed"]["project_id"], "title": "x",
        "customer_relevant": True})
    assert r.status_code == 403


async def test_permissions_carry_the_plant_list(client, mp):
    r = await client.get(f"{URL}/permissions", headers=await _auth(client, "pm"))
    body = r.json()
    assert body["mother_plants"] == ["KTX Weissenburg (WUG)", "KTX Solingen"]
    assert body["default_mother_plant"] == "KTX Weissenburg (WUG)"
    assert body["can_start_mother_plant"] is True and body["can_start_change"] is False
    q = await client.get(f"{URL}/permissions", headers=await _auth(client, "quality"))
    assert q.json()["can_start_mother_plant"] is False
    s = await client.get(f"{URL}/permissions", headers=await _auth(client, "sales"))
    assert s.json()["can_start_mother_plant"] is False
    assert s.json()["can_start_change"] is True


async def test_ordinary_changes_mirror_origin_from_the_flag(client, mp):
    r = await client.post(URL, headers=await _auth(client, "sales"), json={
        "project_id": mp["seed"]["project_id"], "title": "x", "customer_relevant": True})
    assert r.status_code == 200 and r.json()["origin"] == "customer"


async def test_patch_cannot_make_it_customer_relevant(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    r = await client.patch(f"{URL}/{cid}", headers=await _auth(client, "admin"),
                           json={"customer_relevant": True})
    assert r.status_code == 400
    assert "KTX Weissenburg (WUG)" in r.json()["detail"]
    assert "mother plant" not in r.json()["detail"].lower()


# ----------------------------------------------------------------------
# The side track
# ----------------------------------------------------------------------
async def test_never_enters_assessment(client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    r = await client.post(f"{URL}/{cid}/transition", headers=await _auth(client, "admin"),
                          json={"to_status": "in_assessment"})
    assert r.status_code == 400
    assert "no assessment, costing or quote" in r.json()["detail"]


@pytest.mark.parametrize("status,to", [("on_hold", "costing"), ("on_hold", "quoting"),
                                       ("on_hold", "quoted")])
async def test_never_enters_costing_or_quote(client, session_factory, mp, status, to):
    cid = await _ready_for_approval(client, session_factory, mp)
    await _set(session_factory, cid, status=status)
    r = await client.post(f"{URL}/{cid}/transition", headers=await _auth(client, "admin"),
                          json={"to_status": to})
    assert r.status_code == 400
    assert "no assessment, costing or quote" in r.json()["detail"]


async def test_scoping_to_approved_needs_the_impact_lock(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    assert (await _send(client, mp, cid)).status_code == 200
    r = await _approve(client, cid)
    assert r.status_code == 400 and "not locked" in r.json()["detail"]


async def test_scoping_to_approved_needs_the_team_informed(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    await _set(session_factory, cid, impact_confirmed_at=datetime.utcnow())
    r = await _approve(client, cid)
    assert r.status_code == 400 and "not informed" in r.json()["detail"]


async def test_scoping_to_approved_is_only_for_mother_plant(client, session_factory, mp):
    r = await client.post(URL, headers=await _auth(client, "sales"), json={
        "project_id": mp["seed"]["project_id"], "title": "x", "customer_relevant": True})
    cid = r.json()["id"]
    await _set(session_factory, cid, status="scoping",
               impact_confirmed_at=datetime.utcnow())
    r = await _approve(client, cid, key="admin")
    assert r.status_code == 400 and "Only a change from KTX Weissenburg / Solingen" in r.json()["detail"]


async def test_scoping_to_approved_is_the_pms_call(client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    assert (await _approve(client, cid, key="sales")).status_code == 403
    assert (await _approve(client, cid, key="tool")).status_code == 403


async def test_entering_approved_sets_release_deadline_and_sop_milestone(
        client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    r = await _approve(client, cid)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "approved"
    assert c["release_due_date"].startswith(SOP.isoformat())
    assert c["release_due_reason"] == "KTX Weissenburg (WUG) timing"
    assert c["active_deadline"] == "release"
    async with session_factory() as s:
        tasks = (await s.execute(select(ChangePlanTask).where(
            ChangePlanTask.change_id == cid,
            ChangePlanTask.plan == "detailed"))).scalars().all()
        log = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cid))).scalars().all()
    assert [(t.name, t.kind, t.start_date, t.duration_days) for t in tasks] == [
        ("SOP (KTX Weissenburg (WUG))", "milestone", SOP, 0)]
    assert "release_deadline_set" in log


async def test_entering_approved_seeds_the_plan_from_their_timing_file(
        client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    r = await client.post(f"{URL}/{cid}/attachments", headers=await _auth(client, "pm"),
                          data={"kind": "mother_plant_timing"},
                          files={"file": ("wug.xml", XML, "application/xml")})
    assert r.status_code == 201, r.text
    try:
        assert (await _approve(client, cid)).status_code == 200
        async with session_factory() as s:
            names = sorted((await s.execute(select(ChangePlanTask.name).where(
                ChangePlanTask.change_id == cid,
                ChangePlanTask.plan == "detailed"))).scalars().all())
            log = (await s.execute(select(ChangeChangelog.action).where(
                ChangeChangelog.change_id == cid))).scalars().all()
        assert names == ["WUG SOP", "WUG tool rework"]
        assert "mother_plant_timing_imported" in log
        state = (await client.get(f"{URL}/{cid}/mother-plant",
                                  headers=await _auth(client, "pm"))).json()
        assert state["timing_attachment"]["filename"] == "wug.xml"
    finally:
        async with session_factory() as s:
            from app.models.change import ChangeAttachment
            for a in (await s.execute(select(ChangeAttachment).where(
                    ChangeAttachment.change_id == cid))).scalars().all():
                Path(a.stored_path).unlink(missing_ok=True)


async def test_timing_file_must_be_ms_project_on_a_mother_plant_change(
        client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    r = await client.post(f"{URL}/{cid}/attachments", headers=await _auth(client, "pm"),
                          data={"kind": "mother_plant_timing"},
                          files={"file": ("x.xml", b"not xml", "application/xml")})
    assert r.status_code == 400
    other = await client.post(URL, headers=await _auth(client, "sales"), json={
        "project_id": mp["seed"]["project_id"], "title": "x", "customer_relevant": True})
    r = await client.post(f"{URL}/{other.json()['id']}/attachments",
                          headers=await _auth(client, "sales"),
                          data={"kind": "mother_plant_timing"},
                          files={"file": ("wug.xml", XML, "application/xml")})
    assert r.status_code == 400


# ----------------------------------------------------------------------
# Team informed
# ----------------------------------------------------------------------
async def test_send_info_creates_receipts_and_notifies_members(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    r = await _send(client, mp, cid)
    assert r.status_code == 200, r.text
    st = r.json()
    assert {x["department_name"] for x in st["receipts"]} == {"Tool Engineer", "Development"}
    assert st["open_count"] == 2
    async with session_factory() as s:
        notified = set((await s.execute(select(Notification.user_id).where(
            Notification.kind == "change_info_sent"))).scalars().all())
    assert notified == {mp["users"]["tool"], mp["users"]["dev"]}
    # the change carries it for the waits
    c = (await client.get(f"{URL}/{cid}", headers=await _auth(client, "pm"))).json()
    assert c["info_sent_at"] is not None
    assert sorted(c["info_open_department_ids"]) == sorted(
        [mp["depts"]["Tool Engineer"], mp["depts"]["Development"]])


async def test_send_info_rights_and_refusals(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    assert (await _send(client, mp, cid, key="sales")).status_code == 403
    assert (await _send(client, mp, cid, names=())).status_code == 400
    assert (await _send(client, mp, cid)).status_code == 200
    # the same departments again: nothing new to send
    assert (await _send(client, mp, cid)).status_code == 400
    # a forgotten one is added
    r = await _send(client, mp, cid, names=("Tool Engineer", "Quality"))
    assert r.status_code == 200 and len(r.json()["receipts"]) == 3


async def test_send_info_refused_on_other_changes_and_captured(client, session_factory, mp):
    r = await _create(client, mp)
    cid = r.json()["id"]                  # captured
    assert (await _send(client, mp, cid)).status_code == 400
    other = await client.post(URL, headers=await _auth(client, "sales"), json={
        "project_id": mp["seed"]["project_id"], "title": "x", "customer_relevant": True})
    oid = other.json()["id"]
    await _set(session_factory, oid, status="scoping")
    assert (await _send(client, mp, oid, key="admin")).status_code == 400


async def test_default_inform_list_is_the_physical_part_routing(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    st = (await client.get(f"{URL}/{cid}/mother-plant",
                           headers=await _auth(client, "pm"))).json()
    # fallback routing: Development, Tool Engineer, Manufacturing Engineer
    # (APQP and Packaging Engineer do not exist in this org)
    assert set(st["default_department_ids"]) == {
        mp["depts"]["Development"], mp["depts"]["Tool Engineer"],
        mp["depts"]["Manufacturing Engineer"]}
    assert st["can_send"] is True and st["mother_plants"][0] == "KTX Weissenburg (WUG)"


async def test_read_and_understood_by_a_member_with_a_note(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    st = (await _send(client, mp, cid)).json()
    tool_rid = next(x["id"] for x in st["receipts"] if x["department_name"] == "Tool Engineer")
    url = f"{URL}/{cid}/mother-plant/info/{tool_rid}/ack"
    assert (await client.post(url, headers=await _auth(client, "dev"), json={})).status_code == 403
    r = await client.post(url, headers=await _auth(client, "tool"),
                          json={"note": "Insert change is ours to build"})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["receipts"] if x["id"] == tool_rid)
    assert row["acknowledged_by_name"] == "TOOL" and row["note"] == "Insert change is ours to build"
    assert (await client.post(url, headers=await _auth(client, "tool"), json={})).status_code == 400
    assert (await client.post(f"{URL}/{cid}/mother-plant/info/99999/ack",
                              headers=await _auth(client, "tool"), json={})).status_code == 404
    async with session_factory() as s:
        back = (await s.execute(select(Notification.user_id).where(
            Notification.kind == "change_info_note"))).scalars().all()
    assert back == [mp["users"]["pm"]]


async def test_my_tasks_and_cockpit_items(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    pm = await _auth(client, "pm")
    kinds = [t["kind"] for t in (await client.get(f"{URL}/my-tasks", headers=pm)).json()
             if t["change_id"] == cid]
    assert "info_send" in kinds
    acts = (await client.get(f"{URL}/{cid}/my-actions", headers=pm)).json()["actions"]
    assert any(a["kind"] == "info_send" and a["target_tab"] == "mother" for a in acts)

    st = (await _send(client, mp, cid)).json()
    tool = await _auth(client, "tool")
    rows = [t for t in (await client.get(f"{URL}/my-tasks", headers=tool)).json()
            if t["change_id"] == cid]
    assert [(t["kind"], t["target_tab"]) for t in rows] == [("info_ack", "mother")]
    acts = (await client.get(f"{URL}/{cid}/my-actions", headers=tool)).json()["actions"]
    assert [a["label"] for a in acts if a["kind"] == "info_ack"] == [
        "Read and understood: Tool Engineer"]
    rid = next(x["id"] for x in st["receipts"] if x["department_name"] == "Tool Engineer")
    await client.post(f"{URL}/{cid}/mother-plant/info/{rid}/ack", headers=tool, json={})
    rows = [t for t in (await client.get(f"{URL}/my-tasks", headers=tool)).json()
            if t["change_id"] == cid]
    assert rows == []
    kinds = [t["kind"] for t in (await client.get(f"{URL}/my-tasks", headers=pm)).json()
             if t["change_id"] == cid]
    assert "info_send" not in kinds


# ----------------------------------------------------------------------
# Timing: team confirmation, the inform stamp, implementation
# ----------------------------------------------------------------------
async def test_timing_confirmed_by_informed_departments_and_scheduling(
        client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    assert (await _approve(client, cid)).status_code == 200
    fb = (await client.get(f"{URL}/{cid}/plan/feedback",
                           headers=await _auth(client, "pm"))).json()
    assert {r["department_name"] for r in fb["required"]} == {
        "Tool Engineer", "Development", "Scheduling"}
    tool_tasks = [t for t in (await client.get(
        f"{URL}/my-tasks", headers=await _auth(client, "tool"))).json()
        if t["change_id"] == cid and t["kind"] == "plan_feedback"]
    assert len(tool_tasks) == 1


async def test_inform_mother_plant_stamp_instead_of_customer_publish(
        client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    assert (await _approve(client, cid)).status_code == 200
    pm = await _auth(client, "pm")
    url = f"{URL}/{cid}/mother-plant/inform"
    r = await client.post(url, headers=pm)
    assert r.status_code == 400 and "Validate the timing" in r.json()["detail"]
    await validate_timing(session_factory, cid)
    assert (await client.post(url, headers=await _auth(client, "sales"))).status_code == 403
    acts = (await client.get(f"{URL}/{cid}/my-actions", headers=pm)).json()["actions"]
    assert any(a["kind"] == "inform_mother_plant" for a in acts)
    r = await client.post(url, headers=pm)
    assert r.status_code == 200, r.text
    assert r.json()["informed_at"] is not None and r.json()["informed_by_name"] == "PM"
    acts = (await client.get(f"{URL}/{cid}/my-actions", headers=pm)).json()["actions"]
    assert not any(a["kind"] == "inform_mother_plant" for a in acts)
    # the customer publish does not exist for it
    await _set(session_factory, cid, bank_build_mode="running_change")
    r = await client.post(f"{URL}/{cid}/bank-build/publish", headers=await _auth(client, "admin"))
    assert r.status_code == 400 and "inform KTX Weissenburg (WUG)" in r.json()["detail"]


async def test_walk_to_implementation_with_informed_departments_implementing(
        client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    assert (await _approve(client, cid)).status_code == 200
    await validate_timing(session_factory, cid)
    # the release gate is decided as for every change (D1)
    r = await client.put(f"{URL}/{cid}/gates/release", headers=await _auth(client, "admin"),
                         json={"decision": "yes"})
    assert r.status_code == 200, r.text
    # a check-workflow standard is only needed with impacted parts; none here
    r = await client.post(f"{URL}/{cid}/transition", headers=await _auth(client, "admin"),
                          json={"to_status": "in_implementation"})
    assert r.status_code == 200, r.text
    st = (await client.get(f"{URL}/{cid}/implementation/state",
                           headers=await _auth(client, "pm"))).json()
    assert {d["department_name"] for d in st["departments"]} == {
        "Tool Engineer", "Development"}


async def test_pnl_basis_none(client, session_factory, mp):
    from app.services.pnl_service import PnlService
    cid = await _ready_for_approval(client, session_factory, mp)
    assert (await _approve(client, cid)).status_code == 200
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        out = await PnlService.offer_vs_actual(s, change)
        batch = await PnlService._offer_vs_actual_batch(s, [change], {})
    assert out["basis"] == "none"
    assert out["planned_revenue"] is None and out["planned_cost"] == 0
    assert any("KTX Weissenburg (WUG)" in w for w in out["warnings"])
    assert not any("mother plant" in w.lower() for w in out["warnings"])
    assert not any("No price yet" in w for w in out["warnings"])
    assert batch[cid]["basis"] == "none"


async def test_level_3_escalation_informs_the_mother_plant_contact_via_pm(
        client, session_factory, mp):
    from app.models.change_validation_issue import ValidationIssue
    from app.services.validation_issue_service import ValidationIssueService
    cid = await _ready_for_approval(client, session_factory, mp)
    await _set(session_factory, cid, status="in_validation")
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        issue = ValidationIssue(change_id=cid, number=1, title="Tool cannot run",
                                category="other", severity=2, status="open", description="d",
                                department_id=mp["depts"]["Tool Engineer"],
                                created_by=mp["users"]["pm"])
        s.add(issue)
        await s.flush()
        esc = await ValidationIssueService._record_escalation(
            s, change, issue, 3, "manual", "Line down", mp["users"]["pm"])
        await s.commit()
        assert "KTX Weissenburg (WUG) contact via PM" in esc.notified
        assert issue.customer_inform is False
        bodies = set((await s.execute(select(Notification.body).where(
            Notification.subject_key == f"vi:{issue.id}:esc:{esc.id}"))).scalars().all())
    assert bodies and all(b.startswith("PM: inform the KTX Weissenburg (WUG) contact") for b in bodies)


# ----------------------------------------------------------------------
# Migration 093
# ----------------------------------------------------------------------
async def test_migration_093_backfills_origin(db_engine, session_factory, seed):
    import importlib.util
    from tests.test_change_starter_departments import _load_migration_032
    _load_migration_032()      # purges the shadowed alembic package first
    path = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "093_mother_plant.py")
    spec = importlib.util.spec_from_file_location("mig_093", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    async with session_factory() as s:
        for n, rel in enumerate((True, False)):
            s.add(ChangeRequest(change_number=f"C-093-{n}", title="t",
                                project_id=seed["project_id"], raised_by=seed["admin_id"],
                                customer_relevant=rel, origin="customer"))
        await s.commit()

    def _apply(sync_conn):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(sync_conn)):
            mod.upgrade()
    async with db_engine.begin() as conn:
        await conn.run_sync(_apply)
    async with session_factory() as s:
        got = dict((await s.execute(select(ChangeRequest.change_number,
                                           ChangeRequest.origin))).all())
        tables = await s.run_sync(lambda ss: __import__("sqlalchemy").inspect(
            ss.bind).get_table_names())
    assert got == {"C-093-0": "customer", "C-093-1": "internal"}
    assert "change_info_receipts" in tables
    assert ChangeInfoReceipt.__tablename__ == "change_info_receipts"


async def test_scoping_record_informs_and_waits_on_no_cost_carrier(
        client, session_factory, mp):
    """The scoping record of a mother-plant change says who is informed: no
    cost carrier is owed and none is waited on (final walk P2-4)."""
    cid = await _to_scoping(client, session_factory, mp)
    auth = await _auth(client, "pm")
    r = await client.post(f"{URL}/{cid}/meetings", headers=auth, json={
        "department_rasic": {str(mp["depts"]["Tool Engineer"]): "I"}})
    assert r.status_code == 200, r.text
    st = (await client.get(f"{URL}/{cid}/stage-state", headers=auth)).json()
    assert not any(w["kind"] == "cost_carrier_unconfirmed" for w in st["waits"])


async def test_pm_writes_the_description_the_kickoff_needs(client, session_factory, mp):
    """The PM who starts a mother-plant change writes its description even
    when somebody else leads it (final walk P2-5)."""
    r = await _create(client, mp)
    cid = r.json()["id"]
    await _set(session_factory, cid, lead_id=mp["users"]["sales"], description=None)
    r = await client.patch(f"{URL}/{cid}", headers=await _auth(client, "pm"),
                           json={"description": "New insert as WUG ECR 4711"})
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "New insert as WUG ECR 4711"
