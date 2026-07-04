"""Task 6: startup backfill that synthesizes change-scoped assessment instances
for changes created before Phase E's one-engine unification.

Legacy state is built BY HAND (assessments + ChangeRouting, no WfInstance) — the
whole point of the backfill is that this data predates the engine. Each scenario
captures ``blocking_complete`` before AND after the repair and asserts they are
identical: the backfill must mirror current state exactly, never block or unblock
an in-flight change.
"""
import pytest
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.change import (
    ChangeRequest, ChangeAssessment, ChangeRouting,
)
from app.models.workflow import (
    Department, WfInstance, WfInstanceTask, WfTemplate, WfStage, WfStep,
    WfStepRasic,
)
from app.services.change_routing_service import ChangeRoutingService
from app.services.assessment_instance_repair import (
    repair_change_assessment_instances,
)


# --------------------------------------------------------------------------
# Builders: construct a template + departments, and legacy (no-instance) state.
# --------------------------------------------------------------------------
async def _build_template(session, name, layout):
    """layout = [(stage_order, [(dept_name, rasic_letter), ...]), ...].
    Returns (template_id, {dept_name: dept_id}). Creates one step per stage
    carrying every listed dept's WfStepRasic so _match_step_id can resolve."""
    depts: dict[str, int] = {}
    t = WfTemplate(name=name, description="x", version=1, is_active=True,
                   created_by=1)
    session.add(t)
    await session.flush()
    for order, deps in layout:
        stage = WfStage(template_id=t.id, stage_order=order, name=f"S{order}")
        session.add(stage)
        await session.flush()
        step = WfStep(stage_id=stage.id, step_name=f"S{order}",
                      position_in_stage=1)
        session.add(step)
        await session.flush()
        for dept_name, letter in deps:
            if dept_name not in depts:
                d = Department(name=dept_name, flow_type="change",
                               is_active=True, sort_order=len(depts))
                session.add(d)
                await session.flush()
                depts[dept_name] = d.id
            session.add(WfStepRasic(step_id=step.id,
                                    department_id=depts[dept_name],
                                    rasic_letter=letter))
    await session.flush()
    return t.id, depts


async def _mk_change(session, seed, number, status="in_assessment"):
    chg = ChangeRequest(change_number=number, title="x", reason="y",
                        change_type="physical_part",
                        project_id=seed["project_id"],
                        raised_by=seed["admin_id"], status=status)
    session.add(chg)
    await session.flush()
    return chg


async def _mk_routing(session, change, template_id):
    r = ChangeRouting(change_id=change.id, template_id=template_id,
                      template_version=1, standard_snapshot={"stages": []})
    session.add(r)
    await session.flush()
    return r


async def _new_dept(session, name):
    d = Department(name=name, flow_type="change", is_active=True, sort_order=99)
    session.add(d)
    await session.flush()
    return d.id


# --------------------------------------------------------------------------
# 1. In-flight change (in_assessment): stage-1 active/submitted rows synthesize
#    mirrored tasks; a stage-2 pending blocking row is NOT yet linked (its stage
#    has not started, current_stage_order == 1).
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inflight_change_mirrors_stage1_leaves_stage2_unstarted(
        session_factory, seed):
    async with session_factory() as s:
        tid, dep = await _build_template(s, "ECM T1", [
            (1, [("T1-R1", "R"), ("T1-R2", "R"), ("T1-S", "S")]),
            (2, [("T1-A", "A")]),
        ])
        chg = await _mk_change(s, seed, "BF-001")
        await _mk_routing(s, chg, tid)
        s.add_all([
            ChangeAssessment(change_id=chg.id, department_id=dep["T1-R1"],
                             stage_order=1, rasic_letter="R", status="active"),
            ChangeAssessment(change_id=chg.id, department_id=dep["T1-R2"],
                             stage_order=1, rasic_letter="R", status="submitted",
                             submitted_by=seed["admin_id"],
                             submitted_at=datetime(2026, 6, 1, 9, 0)),
            ChangeAssessment(change_id=chg.id, department_id=dep["T1-S"],
                             stage_order=1, rasic_letter="S", status="pending"),
            ChangeAssessment(change_id=chg.id, department_id=dep["T1-A"],
                             stage_order=2, rasic_letter="A", status="pending"),
        ])
        await s.flush()
        before = await ChangeRoutingService.blocking_complete(s, chg)

        n = await repair_change_assessment_instances(s)
        assert n == 1
        await s.commit()

    async with session_factory() as s:
        chg = await s.get(ChangeRequest, chg.id)
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == chg.id))).scalar_one()
        assert inst.status == "active"
        assert inst.current_stage_order == 1
        assert inst.part_revision_id is None

        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == chg.id))).scalars().all()
        by_dep = {a.department_id: a for a in rows}

        # stage-1 R (active) -> task active, actionable, linked
        r1 = by_dep[dep["T1-R1"]]
        t_r1 = await s.get(WfInstanceTask, r1.wf_instance_task_id)
        assert t_r1.status == "active" and t_r1.is_actionable is True
        assert t_r1.stage_order == 1 and t_r1.step_id is not None

        # stage-1 R (submitted) -> task approved with completion mirrored
        r2 = by_dep[dep["T1-R2"]]
        t_r2 = await s.get(WfInstanceTask, r2.wf_instance_task_id)
        assert t_r2.status == "approved"
        assert t_r2.completed_by == seed["admin_id"]
        assert t_r2.completed_at == datetime(2026, 6, 1, 9, 0)

        # stage-1 S -> noted, non-actionable
        rs = by_dep[dep["T1-S"]]
        t_s = await s.get(WfInstanceTask, rs.wf_instance_task_id)
        assert t_s.status == "noted" and t_s.is_actionable is False

        # stage-2 A (pending) lives beyond current_stage_order -> not linked yet
        ra = by_dep[dep["T1-A"]]
        assert ra.wf_instance_task_id is None

        after = await ChangeRoutingService.blocking_complete(s, chg)
        assert after == before  # equivalence: still incomplete (R1 active)
        assert after is False


# --------------------------------------------------------------------------
# 2. Terminal change (released): all blocking rows submitted -> instance
#    'completed', every stage's tasks synthesized.
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_terminal_change_synthesizes_completed_instance(
        session_factory, seed):
    async with session_factory() as s:
        tid, dep = await _build_template(s, "ECM T2", [
            (1, [("T2-R", "R")]),
            (2, [("T2-A", "A"), ("T2-C", "C")]),
        ])
        chg = await _mk_change(s, seed, "BF-002", status="released")
        await _mk_routing(s, chg, tid)
        s.add_all([
            ChangeAssessment(change_id=chg.id, department_id=dep["T2-R"],
                             stage_order=1, rasic_letter="R", status="submitted",
                             submitted_by=seed["admin_id"],
                             submitted_at=datetime(2026, 5, 1)),
            ChangeAssessment(change_id=chg.id, department_id=dep["T2-A"],
                             stage_order=2, rasic_letter="A", status="submitted",
                             submitted_by=seed["admin_id"],
                             submitted_at=datetime(2026, 5, 2)),
            ChangeAssessment(change_id=chg.id, department_id=dep["T2-C"],
                             stage_order=2, rasic_letter="C", status="submitted",
                             submitted_at=datetime(2026, 5, 2)),
        ])
        await s.flush()
        before = await ChangeRoutingService.blocking_complete(s, chg)

        n = await repair_change_assessment_instances(s)
        assert n == 1
        await s.commit()

    async with session_factory() as s:
        chg = await s.get(ChangeRequest, chg.id)
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == chg.id))).scalar_one()
        assert inst.status == "completed"
        assert inst.completed_at is not None

        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == chg.id))).scalars().all()
        by_dep = {a.department_id: a for a in rows}
        # every row linked (all stages synthesized when done)
        for a in rows:
            assert a.wf_instance_task_id is not None
        assert (await s.get(WfInstanceTask,
                            by_dep[dep["T2-R"]].wf_instance_task_id)).status == "approved"
        assert (await s.get(WfInstanceTask,
                            by_dep[dep["T2-A"]].wf_instance_task_id)).status == "approved"
        assert (await s.get(WfInstanceTask,
                            by_dep[dep["T2-C"]].wf_instance_task_id)).status == "noted"

        after = await ChangeRoutingService.blocking_complete(s, chg)
        assert after == before and after is True


# --------------------------------------------------------------------------
# 3. Deviation-added row not in the template snapshot: task synthesized from the
#    assessment itself, step_id None. Nothing dropped.
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_deviation_row_outside_template_gets_task_with_null_step(
        session_factory, seed):
    async with session_factory() as s:
        # Template has ONE stage only; the deviation row lives in stage 2.
        tid, dep = await _build_template(s, "ECM T3", [
            (1, [("T3-R", "R")]),
        ])
        chg = await _mk_change(s, seed, "BF-003")
        await _mk_routing(s, chg, tid)
        dev_id = await _new_dept(s, "T3-DEV")
        s.add_all([
            ChangeAssessment(change_id=chg.id, department_id=dep["T3-R"],
                             stage_order=1, rasic_letter="R", status="submitted",
                             submitted_by=seed["admin_id"],
                             submitted_at=datetime(2026, 6, 10)),
            # deviation-added blocking row in a stage the template never had
            ChangeAssessment(change_id=chg.id, department_id=dev_id,
                             stage_order=2, rasic_letter="R", status="active"),
        ])
        await s.flush()
        before = await ChangeRoutingService.blocking_complete(s, chg)

        n = await repair_change_assessment_instances(s)
        assert n == 1
        await s.commit()

    async with session_factory() as s:
        chg = await s.get(ChangeRequest, chg.id)
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == chg.id))).scalar_one()
        assert inst.current_stage_order == 2  # min open blocking stage

        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == chg.id))).scalars().all()
        by_dep = {a.department_id: a for a in rows}
        # Nothing dropped: both rows linked.
        for a in rows:
            assert a.wf_instance_task_id is not None
        dev_task = await s.get(WfInstanceTask,
                               by_dep[dev_id].wf_instance_task_id)
        assert dev_task.step_id is None          # stage 2 absent from template
        assert dev_task.status == "active" and dev_task.is_actionable is True

        after = await ChangeRoutingService.blocking_complete(s, chg)
        assert after == before and after is False  # dev row still active


# --------------------------------------------------------------------------
# 4. Idempotence: a second run synthesizes nothing and duplicates nothing.
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotent_second_run_creates_nothing(session_factory, seed):
    async with session_factory() as s:
        tid, dep = await _build_template(s, "ECM T4", [
            (1, [("T4-R", "R"), ("T4-S", "S")]),
        ])
        chg = await _mk_change(s, seed, "BF-004")
        await _mk_routing(s, chg, tid)
        s.add_all([
            ChangeAssessment(change_id=chg.id, department_id=dep["T4-R"],
                             stage_order=1, rasic_letter="R", status="active"),
            ChangeAssessment(change_id=chg.id, department_id=dep["T4-S"],
                             stage_order=1, rasic_letter="S", status="pending"),
        ])
        await s.flush()

        assert await repair_change_assessment_instances(s) == 1
        await s.commit()

    async with session_factory() as s:
        # second run: nothing new
        assert await repair_change_assessment_instances(s) == 0
        await s.commit()

    async with session_factory() as s:
        instances = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == chg.id))).scalars().all()
        assert len(instances) == 1
        tasks = (await s.execute(select(WfInstanceTask).where(
            WfInstanceTask.instance_id == instances[0].id))).scalars().all()
        assert len(tasks) == 2  # one per row, no duplicates
        # links intact and unique
        links = [a.wf_instance_task_id for a in (await s.execute(
            select(ChangeAssessment).where(
                ChangeAssessment.change_id == chg.id))).scalars().all()]
        assert None not in links and len(set(links)) == 2


# --------------------------------------------------------------------------
# 5. Owner / due / accepted / completion metadata mirrored onto the task.
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_owner_due_accepted_mirrored_onto_task(session_factory, seed):
    due = datetime(2026, 8, 1, 12, 0)
    accepted = datetime(2026, 6, 15, 8, 0)
    submitted = datetime(2026, 6, 20, 10, 0)
    async with session_factory() as s:
        tid, dep = await _build_template(s, "ECM T5", [
            (1, [("T5-R", "R")]),
        ])
        chg = await _mk_change(s, seed, "BF-005")
        await _mk_routing(s, chg, tid)
        s.add(ChangeAssessment(
            change_id=chg.id, department_id=dep["T5-R"], stage_order=1,
            rasic_letter="R", status="submitted",
            owner_id=seed["admin_id"], due_date=due, accepted_at=accepted,
            submitted_by=seed["admin_id"], submitted_at=submitted))
        await s.flush()

        assert await repair_change_assessment_instances(s) == 1
        await s.commit()

    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == chg.id))).scalar_one()
        task = await s.get(WfInstanceTask, a.wf_instance_task_id)
        assert task.owner_id == seed["admin_id"]
        assert task.due_date == due
        assert task.accepted_at == accepted
        assert task.completed_by == seed["admin_id"]
        assert task.completed_at == submitted


# --------------------------------------------------------------------------
# 6. Edge case (called out in the task brief): a change still in_assessment
#    whose blocking rows are ALL submitted but which has an unsubmitted stage-3
#    S/C row. open_stages (blocking-only) is empty -> instance synthesized
#    'completed'. This matches the engine's post-Task-5 born-complete cascade
#    (blocking-only gates), and blocking_complete is TRUE both before & after.
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inflight_all_blocking_done_but_sc_open_is_completed(
        session_factory, seed):
    async with session_factory() as s:
        tid, dep = await _build_template(s, "ECM T6", [
            (1, [("T6-R", "R")]),
            (2, [("T6-A", "A")]),
            (3, [("T6-S", "S"), ("T6-C", "C")]),
        ])
        chg = await _mk_change(s, seed, "BF-006", status="in_assessment")
        await _mk_routing(s, chg, tid)
        s.add_all([
            ChangeAssessment(change_id=chg.id, department_id=dep["T6-R"],
                             stage_order=1, rasic_letter="R", status="submitted",
                             submitted_by=seed["admin_id"],
                             submitted_at=datetime(2026, 6, 1)),
            ChangeAssessment(change_id=chg.id, department_id=dep["T6-A"],
                             stage_order=2, rasic_letter="A", status="submitted",
                             submitted_by=seed["admin_id"],
                             submitted_at=datetime(2026, 6, 2)),
            # stage-3 S/C rows still unsubmitted (non-blocking)
            ChangeAssessment(change_id=chg.id, department_id=dep["T6-S"],
                             stage_order=3, rasic_letter="S", status="pending"),
            ChangeAssessment(change_id=chg.id, department_id=dep["T6-C"],
                             stage_order=3, rasic_letter="C", status="pending"),
        ])
        await s.flush()
        before = await ChangeRoutingService.blocking_complete(s, chg)
        assert before is True  # all blocking rows submitted

        n = await repair_change_assessment_instances(s)
        assert n == 1
        await s.commit()

    async with session_factory() as s:
        chg = await s.get(ChangeRequest, chg.id)
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.change_id == chg.id))).scalar_one()
        # blocking-only gates are all closed -> born-complete
        assert inst.status == "completed"
        # all stages (incl. stage 3 S/C) synthesized when done
        rows = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == chg.id))).scalars().all()
        for a in rows:
            assert a.wf_instance_task_id is not None

        after = await ChangeRoutingService.blocking_complete(s, chg)
        assert after == before and after is True
