"""Periodic notification sweep: due-soon/overdue tasks, at-risk/overdue change
deadlines. Deduped via NotificationService.notify_once — safe to run repeatedly
(e.g. from main.py's reminder loop) without spamming already-unread rows."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WfInstanceTask
from app.models.change import ChangeRequest, TERMINAL_STATUSES
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
