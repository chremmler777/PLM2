"""Periodic notification sweep: due-soon/overdue tasks, at-risk/overdue change
deadlines. Deduped via NotificationService.notify_once — safe to run repeatedly
(e.g. from main.py's reminder loop) without spamming already-unread rows."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WfInstance, WfInstanceTask
from app.models.change import ChangeAssessment, ChangeRequest, TERMINAL_STATUSES
from app.services.notification_service import NotificationService

DUE_SOON_WINDOW = timedelta(days=2)


async def run_notification_sweep(session: AsyncSession) -> dict:
    """Scan active owned tasks and non-terminal changes with a deadline, and
    emit deduped notifications for due-soon/overdue tasks and at-risk/overdue
    change deadlines. Returns a dict of counts per category."""
    from app.services.change_service import ChangeService

    now = datetime.utcnow()
    counts = {"due_soon": 0, "overdue": 0, "deadline_at_risk": 0, "deadline_overdue": 0}

    tasks = (await session.execute(
        select(WfInstanceTask).where(
            WfInstanceTask.status == "active",
            WfInstanceTask.is_actionable.is_(True),
            WfInstanceTask.owner_id.is_not(None),
            WfInstanceTask.due_date.is_not(None),
        ))).scalars().all()

    for task in tasks:
        if task.due_date < now:
            n = await NotificationService.notify_once(
                session, [task.owner_id], kind="overdue",
                subject_key=f"task:{task.id}:overdue",
                title="Task overdue",
                body=f"Your task is overdue (was due {task.due_date.date().isoformat()}).",
                link="/my-tasks",
            )
            counts["overdue"] += n
        elif task.due_date <= now + DUE_SOON_WINDOW:
            n = await NotificationService.notify_once(
                session, [task.owner_id], kind="due_soon",
                subject_key=f"task:{task.id}:due_soon",
                title="Task due soon",
                body=f"Your task is due {task.due_date.date().isoformat()}.",
                link="/my-tasks",
            )
            counts["due_soon"] += n

    # Overdue tasks on CHANGE-scoped instances escalate to the change lead
    # too, claimed or not — the owned-task sweep above filters on owner_id,
    # so an unclaimed overdue task (the Phase-E primary path: assessments
    # linked to engine tasks) would otherwise notify nobody. Lead-scoped
    # dedup key keeps it independent of the owner's; lead == owner is
    # skipped to avoid a duplicate ping. Part-revision-scoped instances are
    # left as-is.
    lead_task_rows = (await session.execute(
        select(WfInstanceTask, ChangeRequest.id, ChangeRequest.lead_id)
        .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
        .join(ChangeRequest, ChangeRequest.id == WfInstance.change_id)
        .where(
            WfInstance.status == "active",
            WfInstanceTask.status == "active",
            WfInstanceTask.is_actionable.is_(True),
            WfInstanceTask.due_date.is_not(None),
            WfInstanceTask.due_date < now,
            ChangeRequest.lead_id.is_not(None),
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
        ))).all()

    for task, change_id, lead_id in lead_task_rows:
        if task.owner_id == lead_id:
            continue
        claim = " and unclaimed" if task.owner_id is None else ""
        n = await NotificationService.notify_once(
            session, [lead_id], kind="overdue",
            subject_key=f"task:{task.id}:overdue:lead",
            title="Task overdue (escalation)",
            body=f"A task on your change is overdue"
                 f" (was due {task.due_date.date().isoformat()}){claim}.",
            link=f"/changes/{change_id}",
        )
        counts["overdue"] += n

    # Overdue assessments: notify the owner (when claimed) AND the change
    # lead (when set and not the owner) via distinct dedup keys, so an
    # unclaimed assessment still escalates instead of dying silently. lead ==
    # owner is skipped to avoid a duplicate ping. Rows linked to a workflow
    # task (wf_instance_task_id set) are covered by the task sweep above —
    # the task is authoritative for those, so skip here to avoid double
    # notification.
    assessments = (await session.execute(
        select(ChangeAssessment, ChangeRequest.lead_id)
        .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
        .where(
            ChangeAssessment.status == "active",
            ChangeAssessment.wf_instance_task_id.is_(None),
            ChangeAssessment.due_date.is_not(None),
            ChangeAssessment.due_date < now,
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
        ))).all()

    for assessment, lead_id in assessments:
        if assessment.owner_id is not None:
            n = await NotificationService.notify_once(
                session, [assessment.owner_id], kind="overdue",
                subject_key=f"assessment:{assessment.id}:overdue",
                title="Assessment overdue",
                body=f"Your assessment is overdue (was due "
                     f"{assessment.due_date.date().isoformat()}).",
                link="/my-tasks",
            )
            counts["overdue"] += n
        if lead_id is not None and lead_id != assessment.owner_id:
            n = await NotificationService.notify_once(
                session, [lead_id], kind="overdue",
                subject_key=f"assessment:{assessment.id}:overdue:lead",
                title="Assessment overdue (escalation)",
                body=f"An assessment on your change is overdue (was due "
                     f"{assessment.due_date.date().isoformat()}).",
                link=f"/changes/{assessment.change_id}",
            )
            counts["overdue"] += n

    changes = (await session.execute(
        select(ChangeRequest).where(
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
            ChangeRequest.required_by_date.is_not(None),
        ))).scalars().all()

    for change in changes:
        if change.lead_id is None:
            continue
        state = await ChangeService.deadline_state(session, change)
        if state not in ("at_risk", "overdue"):
            continue
        n = await NotificationService.notify_once(
            session, [change.lead_id], kind=f"deadline_{state}",
            subject_key=f"chg:{change.id}:{state}",
            title=f"Change deadline {state.replace('_', ' ')}: {change.change_number}",
            body=f"Required by {change.required_by_date.date().isoformat()}.",
            link=f"/changes/{change.id}",
        )
        counts[f"deadline_{state}"] += n

    return counts
