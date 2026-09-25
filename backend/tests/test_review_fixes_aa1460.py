"""Joint review of aa1460f9: the fixes, one test (or a few) per finding.

1 scoping -> approved is offered only to who may take it (PM, lead, admin)
2 PM writes the capture fields of a change it captures; kickoff's list
3 the re-check of a validation issue waits for validation
4 acting as a department drops the personal lead privilege everywhere
5 the impact-lock wait on a mother-plant change in scoping
6 org-scoped notifications, foreign drafts hidden, the extra-cost bound,
  the lead rule for a PM member, the reason on back_to_scoping's audit
"""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import AuditLog, Organization, User
from app.models.notification import Notification
from app.models.workflow import UserDepartment
from tests.conftest import ENGINEER_PASSWORD, KEEP_LEAD_RULE
from tests.test_mother_plant import (  # noqa: F401  (mp is a fixture)
    URL, _auth, _create, _ready_for_approval, _send, _set, _to_scoping, mp,
)

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"


async def _stage(client, cid, key):
    r = await client.get(f"{URL}/{cid}/stage-state", headers=await _auth(client, key))
    assert r.status_code == 200, r.text
    return r.json()


async def _customer_change(client, mp, key="sales", **extra):
    r = await client.post(URL, headers=await _auth(client, key), json={
        "project_id": mp["seed"]["project_id"], "title": "Rib", "reason": "r",
        "change_type": "physical_part", "customer_relevant": True, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# 1 -------------------------------------------------------------------------
async def test_approved_offered_only_to_who_may_approve(client, session_factory, mp):
    cid = await _ready_for_approval(client, session_factory, mp)
    assert (await _stage(client, cid, "pm"))["can_transition"]["approved"] is True
    for key in ("quality", "sales", "tool"):
        assert (await _stage(client, cid, key))["can_transition"]["approved"] is False


# 2 -------------------------------------------------------------------------
async def test_pm_writes_the_description_of_a_mother_plant_change(
        client, session_factory, mp):
    r = await _create(client, mp)
    cid = r.json()["id"]
    tasks = (await client.get(f"{URL}/my-tasks", headers=await _auth(client, "pm"))).json()
    row = next(t for t in tasks if t["kind"] == "kickoff" and t["change_id"] == cid)
    assert "description" in row["missing"] and "quote deadline" not in row["missing"]

    r = await client.patch(f"{URL}/{cid}", headers=await _auth(client, "pm"),
                           json={"description": "Clip tower rib moved 2 mm",
                                 "title": "WUG clip tower", "reason": "WUG ECR"})
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "Clip tower rib moved 2 mm"
    r = await client.patch(f"{URL}/{cid}", headers=await _auth(client, "quality"),
                           json={"description": "not mine"})
    assert r.status_code == 403
    tasks = (await client.get(f"{URL}/my-tasks", headers=await _auth(client, "pm"))).json()
    row = next(t for t in tasks if t["kind"] == "kickoff" and t["change_id"] == cid)
    assert "description" not in row["missing"]


async def test_pm_writes_capture_fields_only_while_nobody_leads(
        client, session_factory, mp):
    cid = (await _customer_change(client, mp))["id"]
    pm = await _auth(client, "pm")
    r = await client.patch(f"{URL}/{cid}", headers=pm, json={"description": "d1"})
    assert r.status_code == 200, r.text
    await _set(session_factory, cid, lead_id=mp["users"]["quality"])
    r = await client.patch(f"{URL}/{cid}", headers=pm, json={"description": "d2"})
    assert r.status_code == 403
    assert r.json()["detail"] == (
        "Only the change lead, Sales, Project Management or an admin may "
        "change description")


# 3 -------------------------------------------------------------------------
async def test_recheck_waits_for_validation():
    from app.services.validation_issue_service import ValidationIssueService as svc
    from app.services.validation_issue_service import Viewer

    class _Session:
        async def get(self, _model, _id):
            return SimpleNamespace(department_id=5)

    user = SimpleNamespace(id=9, effective_role="engineer")
    issue = SimpleNamespace(
        is_open=True, status="revalidation", check_id=1, department_id=5,
        route="rework", containment="c", root_cause="rc", created_by=1,
        severity=2, customer_inform=False, customer_decision=None,
        extra_cost=0, escalation_level=1, cost_bearer=None, fix_quoted_at=None)
    for status, offered in (("in_implementation", False), ("in_validation", True)):
        change = SimpleNamespace(lead_id=None, status=status)
        v = Viewer(user, change, {5}, {5: "Quality"})
        acts, _, _ = await svc.next_acts(_Session(), change, issue, v, [], [])
        assert ("recheck" in acts) is offered
        note = svc._step_note(change, issue)
        assert (note is None) is offered
    assert svc._step_note(SimpleNamespace(status="in_implementation"), issue) == (
        "Re-check after implementation, when the change is back in validation")


# 4 -------------------------------------------------------------------------
async def test_acting_drops_the_lead_privilege_in_the_pure_rules():
    from app.services.change_people import holds_lead
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.validation_issue_service import Viewer
    change = SimpleNamespace(lead_id=1, status="in_assessment")
    me = SimpleNamespace(id=1, effective_role="engineer", acts_as_department_id=None)
    acting_me = SimpleNamespace(id=1, effective_role="engineer", acts_as_department_id=3)
    assert holds_lead(change, me) and not holds_lead(change, acting_me)
    assert Viewer(me, change, set(), {}).lead is True
    assert Viewer(acting_me, change, set(), {}).lead is False
    routing = SimpleNamespace(deviation_status="pending_approval", deviation_proposed_by=2)
    assert ChangeRoutingService.user_can_decide_deviation(change, routing, 1)
    assert not ChangeRoutingService.user_can_decide_deviation(
        change, routing, 1, acting=True)


async def test_acting_lead_may_not_patch_or_run_meetings(client, session_factory, mp):
    from app.services.early_stage_service import EarlyStageService
    from app.services.meeting_service import MeetingForbidden, MeetingService
    cid = (await _customer_change(client, mp))["id"]
    admin_id = mp["seed"]["admin_id"]
    await _set(session_factory, cid, lead_id=admin_id, status="scoping")
    quality = mp["depts"]["Quality"]
    acting = {**await _auth(client, "admin"), ACTS: str(quality)}
    r = await client.patch(f"{URL}/{cid}", headers=acting, json={"priority": "high"})
    assert r.status_code == 403
    assert (await _stage(client, cid, "admin"))["can_record_meeting"] is True
    r = await client.get(f"{URL}/{cid}/stage-state", headers=acting)
    assert r.json()["can_record_meeting"] is False
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        admin = await s.get(User, admin_id)
        admin.acts_as_department_id = quality
        assert not await EarlyStageService._may_record_meeting(s, change, admin)
        with pytest.raises(MeetingForbidden):
            await MeetingService._authz(s, change, admin)


# 5 -------------------------------------------------------------------------
async def test_impact_lock_wait_on_a_mother_plant_change(client, session_factory, mp):
    cid = await _to_scoping(client, session_factory, mp)
    kinds = [w["kind"] for w in (await _stage(client, cid, "pm"))["waits"]]
    assert "impact_not_locked" in kinds
    await _set(session_factory, cid, impact_confirmed_at=datetime.utcnow())
    kinds = [w["kind"] for w in (await _stage(client, cid, "pm"))["waits"]]
    assert "impact_not_locked" not in kinds


# 6 -------------------------------------------------------------------------
async def _foreign_member(session_factory, dept_id, tag):
    async with session_factory() as s:
        org = Organization(name=f"Other {tag}", code=f"other-{tag}")
        s.add(org)
        await s.flush()
        u = User(organization_id=org.id, username=f"far-{tag}", email=f"far-{tag}@test.io",
                 full_name="Far", role="engineer", is_active=True, mfa_enabled=False,
                 hashed_password=get_password_hash(ENGINEER_PASSWORD))
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return u.id


async def _notified(session_factory, uid) -> int:
    async with session_factory() as s:
        return len((await s.execute(select(Notification).where(
            Notification.user_id == uid))).scalars().all())


async def test_send_info_notifies_the_change_org_only(client, session_factory, mp):
    far = await _foreign_member(session_factory, mp["depts"]["Tool Engineer"], "info")
    cid = await _to_scoping(client, session_factory, mp)
    assert (await _send(client, mp, cid)).status_code == 200
    assert await _notified(session_factory, mp["users"]["tool"]) == 1
    assert await _notified(session_factory, far) == 0


async def test_cost_carrier_flip_tells_the_change_org_sales_only(
        client, session_factory, mp):
    from app.services.meeting_service import MeetingService
    far = await _foreign_member(session_factory, mp["depts"]["Sales"], "flip")
    cid = (await _customer_change(client, mp))["id"]
    async with session_factory() as s:
        change = await s.get(ChangeRequest, cid)
        pm = await s.get(User, mp["users"]["pm"])
        await MeetingService._apply_cost_carrier(
            s, change, SimpleNamespace(cost_carrier="internal", id=None), pm)
        await s.commit()
    assert await _notified(session_factory, mp["users"]["sales"]) == 1
    assert await _notified(session_factory, far) == 0


async def test_assessment_draft_only_for_its_department(client, session_factory, mp):
    cid = (await _customer_change(client, mp))["id"]
    await _set(session_factory, cid, status="in_assessment")
    async with session_factory() as s:
        s.add(ChangeAssessment(
            change_id=cid, department_id=mp["depts"]["Development"],
            details=json.dumps({"draft": {"data": {"x": "secret"}, "saved_by": 1}})))
        await s.commit()

    async def details(key):
        r = await client.get(f"{URL}/{cid}", headers=await _auth(client, key))
        assert r.status_code == 200, r.text
        return r.json()["assessments"][0]["details"]

    assert (await details("dev"))["draft"]["data"] == {"x": "secret"}
    assert "draft" in await details("admin")
    assert "draft" not in await details("tool")
    assert "draft" not in await details("pm")


async def test_issue_extra_cost_beyond_numeric_12_2_is_422(client, mp):
    admin = await _auth(client, "admin")
    r = await client.post(f"{URL}/1/validation/issues/1/cost", headers=admin,
                          json={"extra_cost": 1e10})
    assert r.status_code == 422


async def test_pm_member_names_the_lead_at_capture(client, session_factory, mp):
    from app.models.workflow import Department
    async with session_factory() as s:     # PM starts customer changes too
        (await s.get(Department, mp["depts"]["Project Manager"])).can_start_change = True
        await s.commit()
    lead = mp["users"]["quality"]
    for key, kept in (("pm", True), ("sales", False)):
        r = await client.post(URL, headers={**await _auth(client, key), KEEP_LEAD_RULE: "1"},
                              json={"project_id": mp["seed"]["project_id"], "title": "L",
                                    "reason": "r", "change_type": "physical_part",
                                    "customer_relevant": True, "lead_id": lead})
        assert r.status_code == 200, r.text
        assert (r.json()["lead_id"] == lead) is kept


async def test_back_to_scoping_audit_carries_the_reason(client, session_factory, mp):
    from app.services.change_service import ChangeService
    from app.services.early_stage_service import EarlyStageService
    cid = (await _customer_change(client, mp))["id"]
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await EarlyStageService.supersede_assessments(
            s, change, mp["users"]["pm"], "Wall below 1.2 mm")
        await s.commit()
        row = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "change", AuditLog.entity_id == cid,
            AuditLog.action == "back_to_scoping"))).scalar_one()
    assert json.loads(row.new_values)["reason"] == "Wall below 1.2 mm"
