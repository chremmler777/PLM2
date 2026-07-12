"""Task 11: notification emission, dedup, and periodic sweep."""
import pytest
from datetime import datetime, timedelta
from sqlalchemy import select

from app.models.entities import User
from app.models.notification import Notification
from app.models.workflow import (
    WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep, WfStepRasic,
    Department, UserDepartment,
)
from app.models.change import ChangeRequest, ChangeAssessment
from app.services.notification_service import NotificationService
from app.services.workflow_service import WorkflowService
from app.services.change_service import ChangeService
from app.services.notification_sweep import run_notification_sweep


async def _mk_change(session, seed, number: str, **kw) -> ChangeRequest:
    chg = ChangeRequest(change_number=number, title="x", reason="y",
                        change_type="physical_part",
                        project_id=seed["project_id"],
                        raised_by=seed["admin_id"], **kw)
    session.add(chg)
    await session.flush()
    return chg


@pytest.mark.asyncio
async def test_notify_once_dedups_second_call(session_factory, seed):
    async with session_factory() as session:
        n1 = await NotificationService.notify_once(
            session, [seed["engineer_id"]], kind="task_assigned",
            subject_key="task:1", title="hello")
        await session.commit()
        assert n1 == 1

        n2 = await NotificationService.notify_once(
            session, [seed["engineer_id"]], kind="task_assigned",
            subject_key="task:1", title="hello again")
        await session.commit()
        assert n2 == 0

        rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"]))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_notify_once_read_row_does_not_block_new(session_factory, seed):
    async with session_factory() as session:
        await NotificationService.notify_once(
            session, [seed["engineer_id"]], kind="task_assigned",
            subject_key="task:2", title="first")
        await session.commit()

        row = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.subject_key == "task:2"))).scalar_one()
        row.is_read = True
        await session.commit()

        n2 = await NotificationService.notify_once(
            session, [seed["engineer_id"]], kind="task_assigned",
            subject_key="task:2", title="second")
        await session.commit()
        assert n2 == 1

        rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.subject_key == "task:2"))).scalars().all()
        assert len(rows) == 2


async def _admin(session, seed) -> User:
    return await session.get(User, seed["admin_id"])


@pytest.mark.asyncio
async def test_assign_task_notifies_assignee_change_scoped_link(session_factory, seed):
    async with session_factory() as session:
        tmpl = WfTemplate(name="T", created_by=1)
        dept = Department(name="Dept-Assign", flow_type="action")
        session.add_all([tmpl, dept])
        await session.flush()
        chg = await _mk_change(session, seed, "C-N-001")
        inst = WfInstance(template_id=tmpl.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        task = WfInstanceTask(instance_id=inst.id, stage_order=1, step_id=None,
                              department_id=dept.id, rasic_letter="R",
                              status="active", is_actionable=True)
        session.add(task)
        session.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        await session.flush()
        await session.commit()

        admin = await _admin(session, seed)
        await WorkflowService.assign_task(session, task.id, seed["engineer_id"], admin)
        await session.commit()

        rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "task_assigned"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].link == f"/changes/{chg.id}?tab=assessments"
        # Link uses the numeric change id, not the change_number string.
        assert rows[0].link.split("/changes/")[1].split("?")[0].isdigit()


@pytest.mark.asyncio
async def test_assign_task_notifies_assignee_revision_scoped_link(
        session_factory, seed):
    from app.models.part import Part, PartRevision

    async with session_factory() as session:
        tmpl = WfTemplate(name="T2", created_by=1)
        dept = Department(name="Dept-Assign2", flow_type="action")
        session.add_all([tmpl, dept])
        await session.flush()
        part = Part(project_id=seed["project_id"], part_number="P-1", name="P-1",
                    part_type="internal_mfg", item_category="article",
                    created_by=seed["admin_id"])
        session.add(part)
        await session.flush()
        rev = PartRevision(part_id=part.id, revision_name="A", phase="prototype",
                          status="draft", created_by=seed["admin_id"])
        session.add(rev)
        await session.flush()
        inst = WfInstance(template_id=tmpl.id, part_revision_id=rev.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        task = WfInstanceTask(instance_id=inst.id, stage_order=1, step_id=None,
                              department_id=dept.id, rasic_letter="R",
                              status="active", is_actionable=True)
        session.add(task)
        session.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept.id))
        await session.flush()
        await session.commit()

        admin = await _admin(session, seed)
        await WorkflowService.assign_task(session, task.id, seed["engineer_id"], admin)
        await session.commit()

        rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "task_assigned"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].link == "/my-tasks"


@pytest.mark.asyncio
async def test_assign_task_skips_self_notification(session_factory, seed):
    async with session_factory() as session:
        tmpl = WfTemplate(name="T3", created_by=1)
        dept = Department(name="Dept-Self", flow_type="action")
        session.add_all([tmpl, dept])
        await session.flush()
        chg = await _mk_change(session, seed, "C-N-002")
        inst = WfInstance(template_id=tmpl.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        task = WfInstanceTask(instance_id=inst.id, stage_order=1, step_id=None,
                              department_id=dept.id, rasic_letter="R",
                              status="active", is_actionable=True)
        session.add(task)
        session.add(UserDepartment(user_id=seed["admin_id"], department_id=dept.id))
        await session.flush()
        await session.commit()

        admin = await _admin(session, seed)
        await WorkflowService.assign_task(session, task.id, seed["admin_id"], admin)
        await session.commit()

        rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["admin_id"],
            Notification.kind == "task_assigned"))).scalars().all()
        assert len(rows) == 0


@pytest.mark.asyncio
async def test_stage_activation_notifies_i_letter_departments(session_factory, seed):
    async with session_factory() as session:
        dept_r = Department(name="R-Dept", flow_type="action")
        dept_i = Department(name="I-Dept", flow_type="info")
        session.add_all([dept_r, dept_i])
        await session.flush()
        tmpl = WfTemplate(name="FyiTmpl", created_by=1)
        session.add(tmpl)
        await session.flush()
        stage = WfStage(template_id=tmpl.id, stage_order=1, name="Stage 1")
        session.add(stage)
        await session.flush()
        step = WfStep(stage_id=stage.id, step_name="Step1", position_in_stage=1)
        session.add(step)
        await session.flush()
        session.add_all([
            WfStepRasic(step_id=step.id, department_id=dept_r.id, rasic_letter="R"),
            WfStepRasic(step_id=step.id, department_id=dept_i.id, rasic_letter="I"),
        ])
        session.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept_i.id))
        await session.flush()
        await session.commit()

        chg = await _mk_change(session, seed, "C-N-003")
        inst = WfInstance(template_id=tmpl.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()
        # _create_stage_tasks expects stage.steps / step.rasic_assignments eager
        # loaded (as the real engine call sites do via selectinload) — reload
        # with the same shape rather than relying on a first-access lazy load,
        # which AsyncSession does not support outside an explicit query.
        from sqlalchemy.orm import selectinload
        stage = (await session.execute(
            select(WfStage).where(WfStage.id == stage.id)
            .options(selectinload(WfStage.steps).selectinload(WfStep.rasic_assignments))
        )).scalar_one()
        await WorkflowService._create_stage_tasks(session, inst, stage)
        await session.commit()

        rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "fyi_stage"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].subject_key == f"inst:{inst.id}:stage:1"

        # Re-running the same stage activation (idempotent path) must not
        # duplicate the FYI while it's still unread.
        await WorkflowService._create_stage_tasks(session, inst, stage)
        await session.commit()
        rows2 = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "fyi_stage"))).scalars().all()
        assert len(rows2) == 1


@pytest.mark.asyncio
async def test_propose_deviation_notifies_lead(session_factory, seed):
    async with session_factory() as session:
        chg = await _mk_change(session, seed, "C-N-004", lead_id=seed["engineer_id"])
        await session.commit()
        # Reload through the same path production routes use (get_change) so
        # the lazy="selectin" transition_deviations relation is populated —
        # a freshly-inserted-but-never-queried instance can't lazy-load it
        # under AsyncSession outside an explicit query.
        chg = await ChangeService.get_change(session, chg.id)

        dev = await ChangeService.propose_transition_deviation(
            session, chg, "released", "urgent business need", seed["admin_id"])
        await session.commit()

        rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "deviation_pending"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].subject_key == f"dev:{dev.id}"
        assert rows[0].link == f"/changes/{chg.id}"


@pytest.mark.asyncio
async def test_sweep_due_soon_overdue_and_at_risk_dedup(session_factory, seed):
    async with session_factory() as session:
        dept = Department(name="Sweep-Dept", flow_type="action")
        session.add(dept)
        await session.flush()
        tmpl = WfTemplate(name="SweepTmpl", created_by=1)
        session.add(tmpl)
        await session.flush()
        stage1 = WfStage(template_id=tmpl.id, stage_order=1, name="S1")
        stage2 = WfStage(template_id=tmpl.id, stage_order=2, name="S2")
        session.add_all([stage1, stage2])
        await session.flush()

        chg_due = await _mk_change(session, seed, "C-N-005")
        inst = WfInstance(template_id=tmpl.id, change_id=chg_due.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()

        due_soon_task = WfInstanceTask(
            instance_id=inst.id, stage_order=1, step_id=None,
            department_id=dept.id, rasic_letter="R", status="active",
            is_actionable=True, owner_id=seed["engineer_id"],
            due_date=datetime.utcnow() + timedelta(days=1))
        overdue_task = WfInstanceTask(
            instance_id=inst.id, stage_order=1, step_id=None,
            department_id=dept.id, rasic_letter="A", status="active",
            is_actionable=True, owner_id=seed["admin_id"],
            due_date=datetime.utcnow() - timedelta(days=1))
        session.add_all([due_soon_task, overdue_task])
        await session.flush()

        # At-risk change: 2 stages remain from stage 1 (14 days needed) but
        # required_by_date is only 3 days out -> at_risk.
        chg_risk = await _mk_change(
            session, seed, "C-N-006", lead_id=seed["engineer_id"],
            required_by_date=datetime.utcnow() + timedelta(days=3))
        inst_risk = WfInstance(template_id=tmpl.id, change_id=chg_risk.id,
                               status="active", current_stage_order=1,
                               started_by=seed["admin_id"])
        session.add(inst_risk)
        await session.flush()
        assert await ChangeService.deadline_state(session, chg_risk) == "at_risk"
        await session.commit()

        counts1 = await run_notification_sweep(session)
        await session.commit()
        assert counts1["due_soon"] == 1
        assert counts1["overdue"] == 1
        assert counts1["deadline_at_risk"] == 1

        due_soon_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "due_soon"))).scalars().all()
        assert len(due_soon_rows) == 1
        assert due_soon_rows[0].subject_key == f"task:{due_soon_task.id}:due_soon"

        overdue_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["admin_id"],
            Notification.kind == "overdue"))).scalars().all()
        assert len(overdue_rows) == 1
        assert overdue_rows[0].subject_key == f"task:{overdue_task.id}:overdue"

        risk_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "deadline_at_risk"))).scalars().all()
        assert len(risk_rows) == 1
        assert risk_rows[0].subject_key == f"chg:{chg_risk.id}:at_risk"

        # Second sweep run: unread rows already exist -> nothing new.
        counts2 = await run_notification_sweep(session)
        await session.commit()
        assert counts2 == {"due_soon": 0, "overdue": 0,
                           "deadline_at_risk": 0, "deadline_overdue": 0}


@pytest.mark.asyncio
async def test_unclaimed_overdue_assessment_notifies_lead(session_factory, seed):
    """An overdue assessment with no owner must still escalate: the sweep
    should notify the change lead (dedup key distinct from the owner's key,
    so a later claim + owner-notify can fire independently)."""
    async with session_factory() as session:
        dept = Department(name="Sweep-Assess-Dept-1", flow_type="action")
        session.add(dept)
        await session.flush()

        chg = await _mk_change(session, seed, "C-N-007", lead_id=seed["engineer_id"])
        assessment = ChangeAssessment(
            change_id=chg.id, department_id=dept.id, status="active",
            rasic_letter="R", owner_id=None,
            due_date=datetime.utcnow() - timedelta(days=1))
        session.add(assessment)
        await session.flush()
        assessment_id = assessment.id
        await session.commit()

        counts = await run_notification_sweep(session)
        await session.commit()
        assert counts["overdue"] >= 1

        lead_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "overdue",
            Notification.subject_key == f"assessment:{assessment_id}:overdue:lead",
        ))).scalars().all()
        assert len(lead_rows) == 1

        # No owner exists, so no owner-scoped notification should be emitted.
        owner_rows = (await session.execute(select(Notification).where(
            Notification.subject_key == f"assessment:{assessment_id}:overdue",
        ))).scalars().all()
        assert len(owner_rows) == 0


@pytest.mark.asyncio
async def test_claimed_overdue_assessment_notifies_lead_and_owner(session_factory, seed):
    """A claimed overdue assessment notifies both the owner AND the change
    lead, via distinct dedup keys so re-running the sweep doesn't double up
    on either recipient."""
    async with session_factory() as session:
        dept = Department(name="Sweep-Assess-Dept-2", flow_type="action")
        session.add(dept)
        await session.flush()

        chg = await _mk_change(session, seed, "C-N-008", lead_id=seed["engineer_id"])
        assessment = ChangeAssessment(
            change_id=chg.id, department_id=dept.id, status="active",
            rasic_letter="R", owner_id=seed["admin_id"],
            due_date=datetime.utcnow() - timedelta(days=1))
        session.add(assessment)
        await session.flush()
        assessment_id = assessment.id
        await session.commit()

        counts = await run_notification_sweep(session)
        await session.commit()
        assert counts["overdue"] >= 2

        lead_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "overdue",
            Notification.subject_key == f"assessment:{assessment_id}:overdue:lead",
        ))).scalars().all()
        assert len(lead_rows) == 1

        owner_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["admin_id"],
            Notification.kind == "overdue",
            Notification.subject_key == f"assessment:{assessment_id}:overdue",
        ))).scalars().all()
        assert len(owner_rows) == 1

        # Re-running is a no-op (both dedup keys already have unread rows).
        counts2 = await run_notification_sweep(session)
        await session.commit()
        assert counts2["overdue"] == 0


@pytest.mark.asyncio
async def test_unclaimed_overdue_change_task_notifies_lead(session_factory, seed):
    """Phase-E primary path: an active, actionable, OVERDUE workflow task with
    no owner on a change-scoped instance must escalate to the change lead
    (dedup key task:{id}:overdue:lead, link /changes/{change_id}); a second
    sweep run is a no-op."""
    async with session_factory() as session:
        dept = Department(name="Sweep-Task-Dept-1", flow_type="action")
        session.add(dept)
        await session.flush()
        tmpl = WfTemplate(name="SweepTmpl-Lead-1", created_by=1)
        session.add(tmpl)
        await session.flush()

        chg = await _mk_change(session, seed, "C-N-009", lead_id=seed["engineer_id"])
        inst = WfInstance(template_id=tmpl.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()

        task = WfInstanceTask(
            instance_id=inst.id, stage_order=1, step_id=None,
            department_id=dept.id, rasic_letter="R", status="active",
            is_actionable=True, owner_id=None,
            due_date=datetime.utcnow() - timedelta(days=2))
        session.add(task)
        await session.flush()
        task_id, chg_id = task.id, chg.id
        await session.commit()

        counts = await run_notification_sweep(session)
        await session.commit()
        assert counts["overdue"] >= 1

        lead_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "overdue",
            Notification.subject_key == f"task:{task_id}:overdue:lead",
        ))).scalars().all()
        assert len(lead_rows) == 1
        assert lead_rows[0].link == f"/changes/{chg_id}"

        # No owner exists -> no owner-scoped notification.
        owner_rows = (await session.execute(select(Notification).where(
            Notification.subject_key == f"task:{task_id}:overdue",
        ))).scalars().all()
        assert len(owner_rows) == 0

        counts2 = await run_notification_sweep(session)
        await session.commit()
        assert counts2["overdue"] == 0


@pytest.mark.asyncio
async def test_owned_overdue_change_task_notifies_owner_and_lead(session_factory, seed):
    """An owned overdue change-scoped task keeps the existing owner
    notification AND escalates to the change lead — except when the lead IS
    the owner, in which case the lead escalation is skipped (no duplicate)."""
    async with session_factory() as session:
        dept = Department(name="Sweep-Task-Dept-2", flow_type="action")
        session.add(dept)
        await session.flush()
        tmpl = WfTemplate(name="SweepTmpl-Lead-2", created_by=1)
        session.add(tmpl)
        await session.flush()

        chg = await _mk_change(session, seed, "C-N-010", lead_id=seed["engineer_id"])
        inst = WfInstance(template_id=tmpl.id, change_id=chg.id, status="active",
                          current_stage_order=1, started_by=seed["admin_id"])
        session.add(inst)
        await session.flush()

        # Task A: owned by admin (owner != lead) -> owner + lead notified.
        task_a = WfInstanceTask(
            instance_id=inst.id, stage_order=1, step_id=None,
            department_id=dept.id, rasic_letter="R", status="active",
            is_actionable=True, owner_id=seed["admin_id"],
            due_date=datetime.utcnow() - timedelta(days=1))
        # Task B: owned by the lead themselves -> owner notification only.
        task_b = WfInstanceTask(
            instance_id=inst.id, stage_order=1, step_id=None,
            department_id=dept.id, rasic_letter="A", status="active",
            is_actionable=True, owner_id=seed["engineer_id"],
            due_date=datetime.utcnow() - timedelta(days=1))
        session.add_all([task_a, task_b])
        await session.flush()
        task_a_id, task_b_id, chg_id = task_a.id, task_b.id, chg.id
        await session.commit()

        counts = await run_notification_sweep(session)
        await session.commit()
        # owner A + lead A + owner B (no lead B: lead == owner)
        assert counts["overdue"] >= 3

        owner_a = (await session.execute(select(Notification).where(
            Notification.user_id == seed["admin_id"],
            Notification.subject_key == f"task:{task_a_id}:overdue",
        ))).scalars().all()
        assert len(owner_a) == 1

        lead_a = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.subject_key == f"task:{task_a_id}:overdue:lead",
        ))).scalars().all()
        assert len(lead_a) == 1
        assert lead_a[0].link == f"/changes/{chg_id}"

        owner_b = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.subject_key == f"task:{task_b_id}:overdue",
        ))).scalars().all()
        assert len(owner_b) == 1

        # lead == owner -> no separate lead escalation for task B.
        lead_b = (await session.execute(select(Notification).where(
            Notification.subject_key == f"task:{task_b_id}:overdue:lead",
        ))).scalars().all()
        assert len(lead_b) == 0

        counts2 = await run_notification_sweep(session)
        await session.commit()
        assert counts2["overdue"] == 0


@pytest.mark.asyncio
async def test_owned_overdue_assessment_lead_equals_owner_notifies_once(
    session_factory, seed
):
    """An overdue assessment claimed by the change lead themselves must only
    produce the owner-keyed notification — the lead escalation is skipped to
    avoid a duplicate ping (mirrors the change-task lead==owner behavior)."""
    async with session_factory() as session:
        dept = Department(name="Sweep-Assess-Dept-3", flow_type="action")
        session.add(dept)
        await session.flush()

        chg = await _mk_change(session, seed, "C-N-011", lead_id=seed["engineer_id"])
        assessment = ChangeAssessment(
            change_id=chg.id, department_id=dept.id, status="active",
            rasic_letter="R", owner_id=seed["engineer_id"],
            due_date=datetime.utcnow() - timedelta(days=1))
        session.add(assessment)
        await session.flush()
        assessment_id = assessment.id
        await session.commit()

        counts = await run_notification_sweep(session)
        await session.commit()
        assert counts["overdue"] == 1

        owner_rows = (await session.execute(select(Notification).where(
            Notification.user_id == seed["engineer_id"],
            Notification.kind == "overdue",
            Notification.subject_key == f"assessment:{assessment_id}:overdue",
        ))).scalars().all()
        assert len(owner_rows) == 1

        lead_rows = (await session.execute(select(Notification).where(
            Notification.subject_key == f"assessment:{assessment_id}:overdue:lead",
        ))).scalars().all()
        assert len(lead_rows) == 0
