"""Retest round 2026-10-27 (fixer C): T2 an internal change's later routing
stages (Summation & Budget, Customer activities) open no PM / Sales task;
T9 one next action; T12 the validation issue's wait text and owner while
APQP confirms limits; F9 customer numbers first; F17 Finance's costing
summation; released -> closed for an internal lead."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.notification import Notification
from app.models.workflow import (
    WfInstance, WfInstanceTask, WfStage, WfStep, WfStepRasic, WfTemplate,
)
from tests.conftest import make_department_member

pytestmark = pytest.mark.asyncio


async def _later_stage_instance(session_factory, seed, *, customer: bool):
    """A change-scoped instance whose stage 1 is answered, in costing, on a
    template carrying Summation & Budget (PM R, Sales A) and Customer
    activities (Sales R, PM A)."""
    dev = await make_department_member(session_factory, seed["engineer_id"], "Development")
    pm = await make_department_member(session_factory, seed["admin_id"], "Project Manager")
    sales = await make_department_member(session_factory, seed["admin_id"], "Sales")
    async with session_factory() as s:
        tmpl = WfTemplate(name=f"t2-{customer}", version=1, is_active=True,
                          created_by=seed["admin_id"])
        s.add(tmpl); await s.flush()
        layout = [(1, "Feasibility & Assessment", [(dev, "R")]),
                  (2, "Summation & Budget", [(pm, "R"), (sales, "A")]),
                  (3, "Customer activities", [(sales, "R"), (pm, "A")])]
        for order, name, deps in layout:
            st = WfStage(template_id=tmpl.id, stage_order=order, name=name)
            s.add(st); await s.flush()
            step = WfStep(stage_id=st.id, step_name=name, position_in_stage=1)
            s.add(step); await s.flush()
            for d, letter in deps:
                s.add(WfStepRasic(step_id=step.id, department_id=d, rasic_letter=letter))
        c = ChangeRequest(change_number=f"C-T2-{customer}", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=customer, status="costing")
        s.add(c); await s.flush()
        inst = WfInstance(template_id=tmpl.id, change_id=c.id, status="active",
                          current_stage_order=1, started_by=seed["engineer_id"])
        s.add(inst); await s.flush()
        s.add(WfInstanceTask(instance_id=inst.id, stage_order=1, department_id=dev,
                             rasic_letter="R", status="approved", is_actionable=True))
        await s.commit()
        return inst.id, c.id, pm, sales


async def test_t2_internal_change_opens_no_summation_tasks(session_factory, seed):
    from app.services.workflow_service import WorkflowService
    iid, cid, pm, sales = await _later_stage_instance(session_factory, seed, customer=False)
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        await WorkflowService._maybe_advance_stage(s, inst)
        await s.commit()
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == iid,
            WfInstanceTask.stage_order > 1))).scalars().all()
        assert tasks and all(t.status == "waived" for t in tasks)
        assert all("internal change" in (t.notes or "") for t in tasks)
        assert inst.status == "completed"
        # nobody is told of a task (or of "all stages approved")
        notes = (await s.execute(select(Notification))).scalars().all()
        assert notes == []


async def test_t2_n4_customer_change_opens_no_summation_tasks_either(session_factory, seed):
    """Retest N4: a customer change's Summation / Customer activities are
    done on the change; their PM / Sales engine tasks are born waived."""
    from app.services.workflow_service import WorkflowService
    iid, cid, pm, sales = await _later_stage_instance(session_factory, seed, customer=True)
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        await WorkflowService._maybe_advance_stage(s, inst)
        await s.commit()
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == iid,
            WfInstanceTask.stage_order > 1))).scalars().all()
        assert tasks and {t.status for t in tasks} == {"waived"}
        assert all("Done on the change" in t.notes for t in tasks)
        assert (await s.execute(select(Notification))).scalars().all() == []


async def test_t2_other_departments_keep_later_stage_tasks(session_factory, seed):
    """NEGATIVE: only PM / Sales are waived; another department's later
    stage task stays active."""
    from app.services.workflow_service import WorkflowService
    iid, cid, pm, sales = await _later_stage_instance(session_factory, seed, customer=True)
    qa = await make_department_member(session_factory, seed["engineer_id"], "Quality")
    async with session_factory() as s:
        st = (await s.execute(select(WfStage).where(
            WfStage.template_id == (await s.get(WfInstance, iid)).template_id,
            WfStage.stage_order == 2))).scalar_one()
        step = (await s.execute(select(WfStep).where(WfStep.stage_id == st.id))).scalar_one()
        s.add(WfStepRasic(step_id=step.id, department_id=qa, rasic_letter="R"))
        await s.commit()
    async with session_factory() as s:
        inst = await s.get(WfInstance, iid)
        await WorkflowService._maybe_advance_stage(s, inst)
        await s.commit()
    async with session_factory() as s:
        t = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == iid, WfInstanceTask.department_id == qa))).scalar_one()
        assert t.status == "active"
        assert (await s.get(WfInstance, iid)).current_stage_order == 2


async def _approved_change(session_factory, seed, *, planned: bool, validated: bool):
    from datetime import date, datetime
    from app.models.change_cost import ChangeGate
    from app.models.change_plan import ChangePlanTask
    async with session_factory() as s:
        c = ChangeRequest(change_number=f"C-T9-{planned}{validated}", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=False, status="approved",
                          bank_build_mode="running_change" if validated else None,
                          timing_validated_at=datetime.utcnow() if validated else None)
        s.add(c); await s.flush()
        s.add(ChangeGate(change_id=c.id, gate_key="release"))
        if planned:
            s.add(ChangePlanTask(change_id=c.id, plan="detailed", name="Tool",
                                 start_date=date.today(), created_by=seed["admin_id"]))
        await s.commit()
        return c.id


async def _lead_actions(session_factory, seed, cid):
    from app.models.entities import User
    from app.services.change_service import ChangeService
    await make_department_member(session_factory, seed["engineer_id"], "Process Engineer")
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        return await ChangeService.my_actions(s, change, await s.get(User, seed["engineer_id"]))


async def test_t9_approved_change_shows_one_next_step(session_factory, seed):
    """No plan yet: the lead's one step is the plan (with its due), the
    release gate is not offered beside it."""
    cid = await _approved_change(session_factory, seed, planned=False, validated=False)
    acts = await _lead_actions(session_factory, seed, cid)
    kinds = [a["kind"] for a in acts]
    assert "gate" not in kinds
    watch = [a for a in acts if a["kind"] == "plan_watch"]
    assert len(watch) == 1 and watch[0].get("due_date")
    assert "detailed plan" in watch[0]["hint"]


async def test_t9_release_gate_is_the_step_once_the_rest_is_done(session_factory, seed):
    cid = await _approved_change(session_factory, seed, planned=True, validated=True)
    acts = await _lead_actions(session_factory, seed, cid)
    kinds = [a["kind"] for a in acts]
    assert kinds.count("gate") == 1 and "plan_watch" not in kinds
    gate = next(a for a in acts if a["kind"] == "gate")
    assert gate.get("due_date")


from tests.test_ecr_solid_fix_concession import (  # noqa: E402,F401
    REF, _fail_weight, _issue, _iurl, _who, fix,
)
from tests.test_validation_checks import _auth, _url, val  # noqa: E402,F401


async def test_t12_issue_waits_on_apqp_while_the_limits_are_unconfirmed(
        client, fix, session_factory):
    await _fail_weight(client, fix)
    issue = await _issue(client, fix)
    tool = await _auth(client, fix, "Tool Engineer")
    res = await client.post(_url(fix, "/checks"), headers=tool, json={
        "department_id": fix["dept"]["Tool Engineer"], "check_key": "weight",
        "measurement": {"sample_size": 5, "min_value": 503.0, "max_value": 509.0,
                        "measuring_ref": REF, "what_changed_kind": "parameter",
                        "what_changed_ref": "holding pressure -5 bar, PS-114 rev C"}})
    assert res.status_code == 201 and res.json()["status"] == "passed", res.text
    issue = await _issue(client, fix)
    assert issue["status"] not in ("closed", "accepted")
    assert issue["check"]["limits_pending"] is True
    assert issue["waiting_on"].startswith("APQP confirms the limits of")
    # the close refusal names APQP, not "answered 'passed' again"
    from app.models.entities import User
    from app.services.change_service import ChangeError, ChangeService
    from app.services.validation_issue_service import ValidationIssueService
    async with session_factory() as s:
        change = await ChangeService.get_change(s, fix["change_id"])
        admin = (await s.execute(select(User).where(User.role == "admin"))).scalars().first()
        with pytest.raises(ChangeError) as e:
            await ValidationIssueService.close(s, change, issue["id"], "x", admin)
        assert "APQP confirms the limits" in str(e.value)
        assert "passed' again" not in str(e.value)
        # the release row's owner is APQP, not Quality
        change.status = "in_validation"
        nxt = await ChangeService.next_step_missing(s, change)
        row = next(i for i in nxt["items"] if i["key"] == "validation_issues")
        assert row["who"].startswith("VI-1: APQP confirms the limits")


def test_f9_customer_copy_drops_our_numbers():
    from types import SimpleNamespace
    from app.services import customer_refs
    from app.services.meeting_service import MeetingService
    title = "20-3101-001-1 - 1383 BOTTOM COVER LEFT G01 LCI"
    assert customer_refs.customer_title(title) == "BOTTOM COVER LEFT G01 LCI"
    assert customer_refs.customer_title("20-3075-305-1 +1 - 1302  ASSY IP DECOR") == "ASSY IP DECOR"
    assert customer_refs.customer_heading(title, ["51 12 7 123456", None, "51 12 7 123456"]) \
        == "51 12 7 123456 BOTTOM COVER LEFT G01 LCI"
    change = SimpleNamespace(change_number="CR-2026-0013", title=title)
    concern = SimpleNamespace(kind="needs_info", answer_from="customer", check_what="weight",
                              note="Which grain?", scope_effect=None)
    text = MeetingService.customer_copy(change, concern, "51 12 7 123456")
    assert "CR-2026-0013" not in text and "20-3101-001-1" not in text and "1383" not in text
    assert "for part 51 12 7 123456" in text and "BOTTOM COVER LEFT" in text


async def test_f17_finance_reads_the_costing_summation(client, session_factory, seed):
    from tests.conftest import ENGINEER_PASSWORD, login
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-F17", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          customer_relevant=True, status="costing")
        s.add(c); await s.commit()
        cid = c.id
    eng = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    # NEGATIVE: an engineer outside the cost roles
    assert (await client.get(f"/api/v1/changes/{cid}/summation", headers=eng)).status_code == 403
    await make_department_member(session_factory, seed["engineer_id"], "Finance")
    eng = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await client.get(f"/api/v1/changes/{cid}/summation", headers=eng)
    assert res.status_code == 200, res.text


async def test_released_lead_action_matches_my_tasks(client, session_factory, seed):
    """After release the lead's My Tasks row 'Ready: move it on' (Close
    change) is an action on the change page too (it was empty there)."""
    from app.models.entities import User
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-REL", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=True, status="released")
        s.add(c); await s.commit()
        cid = c.id
    await make_department_member(session_factory, seed["engineer_id"], "Process Engineer")
    from tests.conftest import ENGINEER_PASSWORD, login
    eng = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    tasks = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=eng)).json()
             if t["change_id"] == cid]
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions", headers=eng)).json()["actions"]
    task_adv = [t for t in tasks if t["kind"] == "advance"]
    act_adv = [a for a in acts if a["kind"] == "advance"]
    assert len(task_adv) == len(act_adv)
    if act_adv:
        assert act_adv[0]["to_status"] == "closed" and act_adv[0]["label"] == "Close change"
    assert task_adv, tasks


async def test_n1_internal_change_asks_sales_no_release_check(client, session_factory, seed):
    """Retest N1: an internal change's Release tab has no Sales row, so
    neither My Tasks nor the change page owe Sales a release check."""
    from app.services import release_checklist as rc
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-N1", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          customer_relevant=False, status="in_validation")
        s.add(c); await s.commit()
        cid = c.id
    sales_keys = [k for k in rc.CHECK_KEYS if rc.owner_for(k) == "Sales"]
    assert sales_keys and not [k for k in rc.keys_for(c) if rc.owner_for(k) == "Sales"]
    await make_department_member(session_factory, seed["engineer_id"], "Sales")
    from tests.conftest import ENGINEER_PASSWORD, login
    eng = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    tasks = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=eng)).json()
             if t["change_id"] == cid and t["kind"] == "release_check"]
    acts = [a for a in (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                         headers=eng)).json()["actions"]
            if a["kind"] == "release_check"]
    assert tasks == [] and acts == []
    # NEGATIVE: on a customer change Sales does owe its row
    async with session_factory() as s:
        (await s.get(ChangeRequest, cid)).customer_relevant = True
        await s.commit()
    acts = [a for a in (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                         headers=eng)).json()["actions"]
            if a["kind"] == "release_check"]
    assert len(acts) == 1


async def _pm_step_instance(session_factory, seed, part, *, customer: bool):
    from app.models.part import PartRevision
    from app.services.workflow_service import WorkflowService
    pm = await make_department_member(session_factory, seed["admin_id"], "Project Manager")
    sales = await make_department_member(session_factory, seed["admin_id"], "Sales")
    async with session_factory() as s:
        tmpl = WfTemplate(name=f"n8-{customer}", version=1, is_active=True,
                          created_by=seed["admin_id"])
        s.add(tmpl); await s.flush()
        st = WfStage(template_id=tmpl.id, stage_order=1, name="Industrialization")
        s.add(st); await s.flush()
        step = WfStep(stage_id=st.id, step_name="Update master data & logistics",
                      position_in_stage=1)
        s.add(step); await s.flush()
        s.add(WfStepRasic(step_id=step.id, department_id=pm, rasic_letter="A"))
        s.add(WfStepRasic(step_id=step.id, department_id=sales, rasic_letter="I"))
        c = ChangeRequest(change_number=f"C-N8-{customer}", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=customer, status="in_implementation")
        s.add(c); await s.flush()
        (await s.get(PartRevision, part["revision_id"])).originating_change_id = c.id
        await s.commit()
        tmpl_id = tmpl.id
    async with session_factory() as s:
        inst = await WorkflowService.start_workflow(s, part["revision_id"], tmpl_id,
                                                    seed["admin_id"])
        await s.commit()
        task = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == inst.id,
            WfInstanceTask.department_id == pm))).scalar_one()
        notes = (await s.execute(select(Notification))).scalars().all()
        return task, notes


async def test_n8_internal_pm_step_is_the_leads(session_factory, seed, part):
    task, notes = await _pm_step_instance(session_factory, seed, part, customer=False)
    assert task.owner_id == seed["engineer_id"]
    assert {n.user_id for n in notes if n.kind == "task_new"} == {seed["engineer_id"]}
    assert not [n for n in notes if n.kind == "fyi_stage"]      # no Sales FYI


async def test_n8_customer_pm_step_stays_with_pm(session_factory, seed, part):
    """NEGATIVE: on a customer change Project Management holds its step."""
    task, notes = await _pm_step_instance(session_factory, seed, part, customer=True)
    assert task.owner_id is None
    assert seed["engineer_id"] not in {n.user_id for n in notes if n.kind == "task_new"}


async def test_n7_ppap_and_issue_notices_reach_the_team_owner_only(session_factory, seed):
    """Retest T7 / N7: the PPAP decision notice and a failed check's issue
    audience reach the project team's Quality responsible, not its backup
    nor members the team does not name."""
    from tests.test_ecr_solid_notice_owners import _dept_with
    from app.models.workflow import ProjectResponsible
    from app.services.ppap_decision_service import PpapDecisionService
    from app.services.validation_issue_service import ValidationIssueService
    from types import SimpleNamespace
    async with session_factory() as s:
        q, (sonja, eric, udo) = await _dept_with(s, seed, "Quality", ["sonja", "eric", "udo"])
        s.add(ProjectResponsible(project_id=seed["project_id"], department_id=q,
                                 user_id=sonja, backup_user_id=eric))
        c = ChangeRequest(change_number="C-N7", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=False, status="scoping")
        s.add(c); await s.commit()
        await PpapDecisionService.notify_owed(s, c, seed["admin_id"])
        await s.commit()
        told = sorted((await s.execute(select(Notification.user_id).where(
            Notification.kind == "ppap_decision"))).scalars().all())
        assert told == [sonja]
        issue = SimpleNamespace(check_id=1, department_id=q)
        users, _ = await ValidationIssueService.audience(s, c, issue, 1)
        assert users == {sonja}


async def test_n2_approval_and_validation_tell_the_new_task_owners(session_factory, seed):
    """Retest N2: approval tells the lead (plan) and Logistics (bank build);
    validation tells each release-check owner not told by the stage notice."""
    from app.services import task_notices
    logi = await make_department_member(session_factory, seed["admin_id"], "Logistics")
    apqp = await make_department_member(session_factory, seed["admin_id"], "APQP")
    async with session_factory() as s:
        from app.models.entities import User
        u = User(organization_id=seed["org_id"], username="alexa", email="alexa@test.io",
                 full_name="Alexa", role="engineer", is_active=True, mfa_enabled=False,
                 hashed_password="!")
        s.add(u); await s.flush()
        from app.models.workflow import UserDepartment
        s.add(UserDepartment(user_id=u.id, department_id=logi))
        s.add(UserDepartment(user_id=u.id, department_id=apqp))
        c = ChangeRequest(change_number="C-N2", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=False, status="approved")
        s.add(c); await s.commit()
        alexa = u.id
        await task_notices.on_approved(s, c, seed["admin_id"])
        await s.commit()
        rows = (await s.execute(select(Notification))).scalars().all()
        assert {(n.user_id, n.subject_key) for n in rows} >= {
            (seed["engineer_id"], f"chg:{c.id}:approved:lead"),
            (alexa, f"chg:{c.id}:bank_build")}
        c.status = "in_validation"
        await s.commit()
        await task_notices.on_validation(s, c, seed["admin_id"])
        await s.commit()
        told = {n.user_id for n in (await s.execute(select(Notification).where(
            Notification.subject_key == f"chg:{c.id}:release_checks"))).scalars()}
        assert alexa in told


async def test_n11_cancel_vote_tells_the_lead_and_the_cancel_tells_the_voter(
        session_factory, seed):
    from app.models.entities import User
    from app.services.change_service import ChangeService
    from app.services.meeting_service import MeetingService
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-N11", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          customer_relevant=True, status="scoping")
        s.add(c); await s.commit()
        change = await ChangeService.get_change(s, c.id)
        await MeetingService.raise_concern(s, change, await s.get(User, seed["engineer_id"]),
                                           "reject_proposal", "Customer will drop the part")
        await s.commit()
        told = [(n.user_id, n.title) for n in (await s.execute(select(Notification))).scalars()]
        assert any(u == seed["admin_id"] and t.startswith("Cancel proposed") for u, t in told)
        await ChangeService.notify_handover_and_end(s, change, "scoping", "cancelled",
                                                    seed["admin_id"])
        await s.commit()
        ended = [n.user_id for n in (await s.execute(select(Notification).where(
            Notification.kind == "change_ended"))).scalars()]
        assert seed["engineer_id"] in ended


async def test_n9_no_geometry_drawing_row_and_no_tool_change_row_say_so(
        session_factory, seed, part):
    """Retest T18 / N9: the drawing row of a revision signed 'no geometry
    change' says so and does not refuse 'done' for missing files; the
    equipment row says the Tool Engineer found no tool change."""
    from app.models.change import ChangeAssessment, ChangeImpactedItem
    from app.models.part import PartRevision
    from app.services.change_service import ChangeService
    from app.services.release_service import ReleaseService
    from datetime import datetime
    tool = await make_department_member(session_factory, seed["engineer_id"], "Tool Engineer")
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-N9", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["admin_id"],
                          customer_relevant=True, status="in_validation")
        s.add(c); await s.flush()
        s.add(ChangeImpactedItem(change_id=c.id, part_id=part["part_id"],
                                 resulting_revision_id=part["revision_id"],
                                 created_by=seed["admin_id"]))
        a = ChangeAssessment(change_id=c.id, department_id=tool, verdict="feasible",
                             rasic_letter="R", submitted_at=datetime.utcnow(),
                             submitted_by=seed["engineer_id"])
        a.details = '{"impacted": false}'
        s.add(a)
        await s.commit()
        cid = c.id
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        assert await ReleaseService.files_missing(s, change)       # NEGATIVE: not signed
        (await s.get(PartRevision, part["revision_id"])).no_geometry_change = True
        await s.commit()
        change = await ChangeService.get_change(s, cid)
        assert await ReleaseService.files_missing(s, change) == []
        hints = await ReleaseService.revision_hints(s, change)
        assert "no geometry change signed" in hints["drawing_released"]
        assert "no tool change" in hints["equipment_updated"]


async def test_n4_hub_admin_records_its_own_departments_validation_check(session_factory, seed):
    """Retest N4 (T5's rule): Christoph (hub admin, real Development
    member) records Development's validation check without acting as; a
    local admin account's blanket membership still does not count."""
    from app.models.entities import User
    from app.services.hub_departments import HUB_MANAGED
    from app.services.validation_service import ValidationService
    async with session_factory() as s:
        hub = User(organization_id=seed["org_id"], username="christoph",
                   email="christoph@test.io", full_name="Christoph", role="admin",
                   is_active=True, mfa_enabled=False, hashed_password=HUB_MANAGED)
        s.add(hub)
        c = ChangeRequest(change_number="C-N4", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], lead_id=seed["engineer_id"],
                          customer_relevant=True, status="in_validation")
        s.add(c); await s.commit()
        hub_id, cid = hub.id, c.id
    dev = await make_department_member(session_factory, hub_id, "Development")
    await make_department_member(session_factory, seed["admin_id"], "Development")
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        assert await ValidationService.may_write(s, c, dev, await s.get(User, hub_id))
        assert not await ValidationService.may_write(s, c, dev, await s.get(User, seed["admin_id"]))


async def test_n6_lessons_step_is_in_the_leads_my_tasks(client, session_factory, seed):
    async with session_factory() as s:
        c = ChangeRequest(change_number="C-LL", title="t", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
                          customer_relevant=False, status="in_validation")
        s.add(c); await s.commit()
        cid = c.id
    await make_department_member(session_factory, seed["engineer_id"], "Process Engineer")
    from tests.conftest import ENGINEER_PASSWORD, login
    eng = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    tasks = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=eng)).json()
             if t["change_id"] == cid and t["kind"] == "lessons_step"]
    acts = [a for a in (await client.get(f"/api/v1/changes/{cid}/my-actions",
                                         headers=eng)).json()["actions"]
            if a["kind"] == "lessons_step"]
    assert len(tasks) == 1 and len(acts) == 1


async def test_esc_p3_6_team_change_leaves_history(session_factory, seed):
    from app.models.entities import AuditLog, User
    from app.services.project_team_service import ProjectTeamService
    q = await make_department_member(session_factory, seed["engineer_id"], "Quality")
    async with session_factory() as s:
        await ProjectTeamService.set_responsible(
            s, seed["project_id"], q, seed["engineer_id"], await s.get(User, seed["admin_id"]))
        await s.commit()
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "project_team"))).scalars().all()
        assert len(rows) == 1 and rows[0].action == "team_changed"
        assert '"responsible_id": %d' % seed["engineer_id"] in rows[0].new_values
