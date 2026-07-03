"""Synthesize change-scoped assessment instances for changes created before
Phase E (one engine). Mirrors current assessment state exactly; nothing dropped.

Changes routed before the Phase E unification carry a ChangeRouting + assessment
rows but no change-scoped WfInstance. This one-time, idempotent backfill builds
the missing instance and links each assessment payload row 1:1 to a synthesized
task, reproducing the state the live engine would have arrived at — so that
``blocking_complete`` (which now reads through ``effective_status``) returns the
SAME verdict after the backfill as it did before it, for every change.
"""
from datetime import datetime

from sqlalchemy import select

from app.models.change import (
    ChangeRequest, ChangeAssessment, ChangeRouting, TERMINAL_STATUSES,
    BLOCKING_LETTERS,
)
from app.models.workflow import WfInstance, WfInstanceTask, WfTemplate
from app.services.change_routing_service import _match_step_id

# Legacy assessment.status -> synthesized task.status for BLOCKING (R/A) rows.
# pending->pending, active->active, submitted->approved, waived->waived. This is
# the inverse of _TASK_TO_ASSESSMENT_STATUS so effective_status reads back the
# original value. S/C rows always become "noted" (execution state is payload-only).
_STATUS_MAP = {"pending": "pending", "active": "active",
               "submitted": "approved", "waived": "waived"}


async def repair_change_assessment_instances(session) -> int:
    """Backfill one change-scoped WfInstance per routed legacy change that lacks
    any instance. Idempotent (skips a change if ANY WfInstance references it,
    active or completed). Returns the number of instances synthesized."""
    created = 0
    routed = (await session.execute(select(ChangeRouting))).scalars().all()
    for routing in routed:
        existing = (await session.execute(select(WfInstance.id).where(
            WfInstance.change_id == routing.change_id))).first()
        if existing is not None:
            continue
        change = await session.get(ChangeRequest, routing.change_id)
        if change is None:
            continue
        rows = (await session.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == change.id))).scalars().all()
        if not rows:
            continue
        template_id = routing.template_id or (await session.execute(
            select(WfTemplate.id).where(WfTemplate.name == "ECM Assessment")
        )).scalar_one_or_none()
        if template_id is None:
            continue  # cannot synthesize without any template; log and move on

        # Open blocking gates decide progress. When none are open (or the change
        # is terminal) the instance is born complete — matching the engine's
        # post-Task-5 blocking-only cascade (S/C rows never gate a stage).
        open_stages = [a.stage_order for a in rows
                       if a.status in ("active", "pending")
                       and a.rasic_letter in BLOCKING_LETTERS]
        done = not open_stages or change.status in TERMINAL_STATUSES
        instance = WfInstance(
            template_id=template_id, change_id=change.id, part_revision_id=None,
            status="completed" if done else "active",
            current_stage_order=(min(open_stages) if open_stages
                                 else max((a.stage_order for a in rows), default=1)),
            started_by=change.lead_id or change.raised_by,
            started_at=change.created_at,
            completed_at=datetime.utcnow() if done else None)
        session.add(instance)
        await session.flush()

        # Tasks are synthesized only for stages that have started (<= current),
        # or all stages when done — matching the engine's lazy stage creation.
        limit = (max(a.stage_order for a in rows) if done
                 else instance.current_stage_order)
        for a in rows:
            if a.stage_order > limit:
                continue
            blocking = a.rasic_letter in BLOCKING_LETTERS
            task = WfInstanceTask(
                instance_id=instance.id, stage_order=a.stage_order,
                step_id=await _match_step_id(session, template_id, a.stage_order,
                                             a.department_id, a.rasic_letter),
                department_id=a.department_id, rasic_letter=a.rasic_letter,
                status=_STATUS_MAP.get(a.status, "pending") if blocking else "noted",
                is_actionable=blocking,
                completed_by=a.submitted_by, completed_at=a.submitted_at,
                owner_id=a.owner_id, accepted_at=a.accepted_at,
                due_date=a.due_date)
            session.add(task)
            await session.flush()
            a.wf_instance_task_id = task.id
        created += 1
    await session.flush()
    return created
