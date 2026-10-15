"""Periodic notification sweep: due-soon/overdue tasks, at-risk/overdue change
deadlines. Deduped via NotificationService.notify_once with include_read:
one notice per item and person, read or not, so the 6-hourly run never
re-sends a state it already reported (spec §0: one per item).

ECR-solid one escalation rule (spec §0, ASSESSMENT_V2): the owner is reminded
on the due date; at due + 1 working day the owner hears it is late and the
item escalates to the change lead (the lead's "Overdue" group); the deadline
alerts reach the Sales owner too (C20). RELEASE_V2 adds the daily overdue
digest (C27/P6, app/services/overdue_digest.py). Switched off: the earlier
timing (due-soon 2 days ahead, escalation at the due date).

main.py's reminder loop calls sweep_once(), which commits."""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.display import fmt_date
from app.models.workflow import WfInstance, WfInstanceTask
from app.models.change import ChangeAssessment, ChangeRequest, TERMINAL_STATUSES
from app.services import cm_switches, due_rules
from app.services.notification_service import NotificationService

DUE_SOON_WINDOW = timedelta(days=2)


def escalated(due: Optional[datetime], now: datetime) -> bool:
    """Has an item due at `due` escalated (owner told it is late, the lead's
    "Overdue" group, the digest)? ONE test for the sweep, the lead's group,
    the digest and My Tasks' Late chip: due + 1 working day under the one
    escalation rule (ASSESSMENT_V2, due_rules.is_late), else the due date.
    Callers pre-filter in SQL with due < now (late implies past due)."""
    if due is None:
        return False
    return due_rules.is_late(due, now) if cm_switches.on("ASSESSMENT_V2") else due < now


async def _once(session, user_ids, **kw) -> int:
    """A sweep notice: one per item and person, read or not."""
    return await NotificationService.notify_once(session, user_ids, include_read=True, **kw)


async def sweep_once(session_factory=None) -> dict:
    """One run of main.py's reminder loop in its own session, committed:
    nothing the sweep creates may be rolled back with the session."""
    if session_factory is None:
        from app.models import AsyncSessionLocal as session_factory
    async with session_factory() as session:
        counts = await run_notification_sweep(session)
        await session.commit()
        return counts


async def run_notification_sweep(session: AsyncSession) -> dict:
    """Scan active owned tasks and non-terminal changes with a deadline, and
    emit deduped notifications for due-soon/overdue tasks and at-risk/overdue
    change deadlines. Returns a dict of counts per category."""
    from app.services.change_service import ChangeService

    now = datetime.utcnow()
    one_rule = cm_switches.on("ASSESSMENT_V2")
    counts = {"due_soon": 0, "overdue": 0, "deadline_at_risk": 0, "deadline_overdue": 0}

    tasks = (await session.execute(
        select(WfInstanceTask).where(
            WfInstanceTask.status == "active",
            WfInstanceTask.is_actionable.is_(True),
            WfInstanceTask.owner_id.is_not(None),
            WfInstanceTask.due_date.is_not(None),
        ))).scalars().all()

    for task in tasks:
        if one_rule:
            # reminded on the due date; "late" only at due + 1 wd
            if escalated(task.due_date, now):
                n = await _once(
                    session, [task.owner_id], kind="overdue",
                    subject_key=f"task:{task.id}:overdue",
                    title="Task late",
                    body=f"Your task is late (was due {fmt_date(task.due_date)}); "
                         "your department and the change lead see it now.",
                    link="/my-tasks")
                counts["overdue"] += n
            elif task.due_date.date() <= now.date():
                n = await _once(
                    session, [task.owner_id], kind="due_soon",
                    subject_key=f"task:{task.id}:due_soon",
                    title="Task due today",
                    body=f"Your task is due today ({fmt_date(task.due_date)}).",
                    link="/my-tasks")
                counts["due_soon"] += n
            continue
        if task.due_date < now:
            n = await _once(
                session, [task.owner_id], kind="overdue",
                subject_key=f"task:{task.id}:overdue",
                title="Task overdue",
                body=f"Your task is overdue (was due {fmt_date(task.due_date)}).",
                link="/my-tasks",
            )
            counts["overdue"] += n
        elif task.due_date <= now + DUE_SOON_WINDOW:
            n = await _once(
                session, [task.owner_id], kind="due_soon",
                subject_key=f"task:{task.id}:due_soon",
                title="Task due soon",
                body=f"Your task is due {fmt_date(task.due_date)}.",
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

    late_word = "late" if one_rule else "overdue"
    for task, change_id, lead_id in lead_task_rows:
        if task.owner_id == lead_id or not escalated(task.due_date, now):
            continue
        claim = " and unclaimed" if task.owner_id is None else ""
        n = await _once(
            session, [lead_id], kind="overdue",
            subject_key=f"task:{task.id}:overdue:lead",
            title=f"Task {late_word} (escalation)",
            body=f"A task on your change is {late_word}"
                 f" (was due {fmt_date(task.due_date)}){claim}.",
            link=f"/changes/{change_id}",
        )
        counts["overdue"] += n

    # Overdue assessments: notify the owner (when claimed) AND the change
    # lead (when set and not the owner) via distinct dedup keys, so an
    # unclaimed assessment still escalates instead of dying silently. lead ==
    # owner is skipped to avoid a duplicate ping. Rows linked to a workflow
    # task (wf_instance_task_id set) are covered by the task sweep above —
    # the task is authoritative for those, so skip here to avoid double
    # notification. Under the one rule an owned row (first editor owns) is
    # reminded on its due date like a task.
    wanted = ChangeAssessment.due_date < now
    if one_rule:            # owned rows due today get their reminder
        wanted = wanted | ChangeAssessment.owner_id.is_not(None)
    assessments = (await session.execute(
        select(ChangeAssessment, ChangeRequest.lead_id)
        .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
        .where(
            ChangeAssessment.status == "active",
            ChangeAssessment.wf_instance_task_id.is_(None),
            ChangeAssessment.due_date.is_not(None),
            wanted,
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
        ))).all()

    for assessment, lead_id in assessments:
        due = assessment.due_date
        if not escalated(due, now):
            if (one_rule and assessment.owner_id is not None
                    and due.date() <= now.date()):
                counts["due_soon"] += await _once(
                    session, [assessment.owner_id], kind="due_soon",
                    subject_key=f"assessment:{assessment.id}:due_soon",
                    title="Assessment due today",
                    body=f"Your assessment is due today ({fmt_date(due)}).",
                    link="/my-tasks")
            continue
        if assessment.owner_id is not None:
            n = await _once(
                session, [assessment.owner_id], kind="overdue",
                subject_key=f"assessment:{assessment.id}:overdue",
                title=f"Assessment {late_word}",
                body=(f"Your assessment is late (was due {fmt_date(due)}); "
                      "your department and the change lead see it now."
                      if one_rule else
                      f"Your assessment is overdue (was due {fmt_date(due)})."),
                link="/my-tasks",
            )
            counts["overdue"] += n
        if lead_id is not None and lead_id != assessment.owner_id:
            n = await _once(
                session, [lead_id], kind="overdue",
                subject_key=f"assessment:{assessment.id}:overdue:lead",
                title=f"Assessment {late_word} (escalation)",
                body=f"An assessment on your change is {late_word} (was due "
                     f"{fmt_date(due)}).",
                link=f"/changes/{assessment.change_id}",
            )
            counts["overdue"] += n

    changes = (await session.execute(
        select(ChangeRequest).where(
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
            ChangeRequest.required_by_date.is_not(None)
            | ChangeRequest.release_due_date.is_not(None),
        ))).scalars().all()

    for change in changes:
        # C20: the Sales owner who promised the date hears it too
        recipients = [u for u in (change.lead_id,
                                  change.sales_owner_id if one_rule else None)
                      if u is not None]
        if not recipients:
            continue
        state = await ChangeService.deadline_state(session, change)
        if state not in ("at_risk", "overdue"):
            continue
        # One notice per deadline and state: the active one (quote until the
        # offer went out, then release), named in the notice. A quote alert
        # keeps its earlier key (no repeat for in-flight changes); a release
        # alert names its date, so a quote alert never hides it and a moved
        # release date is told again.
        kind = change.active_deadline
        due = change.release_due_date if kind == "release" else change.required_by_date
        key = (f"chg:{change.id}:release:{due.date().isoformat()}:{state}"
               if kind == "release" else f"chg:{change.id}:{state}")
        word = "Release" if kind == "release" else "Quote"
        n = await _once(
            session, recipients, kind=f"deadline_{state}", subject_key=key,
            title=f"{word} deadline {state.replace('_', ' ')}: {change.change_number}",
            body=f"{word} due {fmt_date(due)}.",
            link=f"/changes/{change.id}",
        )
        counts[f"deadline_{state}"] += n

    # Validation issues (spec §12a): the time-based escalation triggers
    # (overdue fix action, no route after 2 working days, an unacknowledged
    # level 2, the plan moving past the baseline or the release deadline).
    from app.services.validation_issue_service import ValidationIssueService
    counts["validation_issue_escalated"] = \
        await ValidationIssueService.reevaluate_all(session)

    # C27 / P6: the daily overdue digest for the configured managers.
    from app.services.overdue_digest import send_overdue_digest
    counts["overdue_digest"] = await send_overdue_digest(session, now=now)

    return counts
