"""Periodic notification sweep: due-soon/overdue tasks, at-risk/overdue change
deadlines. Deduped via NotificationService.notify_once with include_read:
one notice per item and person, read or not, so the 6-hourly run never
re-sends a state it already reported (spec §0: one per item).

ECR-solid one escalation rule (spec §0, ASSESSMENT_V2): the owner is reminded
on the due date; at due + 1 working day the owner hears it is late and the
item escalates to the change lead (the lead's "Overdue" group); the deadline
alerts reach the Sales contact too (C20). The computed My Tasks rows that
owe a decision or a number (owed_items: costing input, sign-offs, the
internal approval, overrides) follow the same rule. RELEASE_V2 adds the daily overdue
digest (C27/P6, app/services/overdue_digest.py) and the daily digest for
the people involved in a change (app/services/change_digest.py). Switched off: the earlier
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


def change_task_query():
    """Active actionable engine tasks with the change they work for: a
    change-scoped instance (WfInstance.change_id) or a part revision the
    change originated (PartRevision.originating_change_id). ONE selection
    of "a change's tasks" for the sweep, the lead's group and the digest
    (R37). Rows: (task, change_id); change_id None = not a change's task."""
    from sqlalchemy import func
    from app.models.part import PartRevision
    cid = func.coalesce(WfInstance.change_id, PartRevision.originating_change_id)
    return (select(WfInstanceTask, cid.label("change_id"))
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .outerjoin(PartRevision, PartRevision.id == WfInstance.part_revision_id)
            .where(WfInstance.status == "active",
                   WfInstanceTask.status == "active",
                   WfInstanceTask.is_actionable.is_(True),
                   WfInstanceTask.due_date.is_not(None))), cid


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

    from app.services.project_team_service import _pair, _responsible
    owners: dict = {}

    async def owner_of(owner_id, project_id, department_id):
        """esc P1-1/P1-2: who is told an item is due or late: whoever took
        it, else the department's project-team responsible (claimed or
        not), else, the responsible inactive or gone, the named backup
        (_responsible). None: the department owns it as a whole."""
        if owner_id is not None:
            return owner_id
        key = (project_id, department_id)
        if key not in owners:
            r = await _responsible(session, project_id, department_id)
            owners[key] = r[0] if r is not None else None
        return owners[key]

    # the one rule (and its "the change lead sees it" wording) is for a
    # change's tasks; another workflow's tasks keep the earlier timing
    change_tasks: list = []
    if one_rule:
        q, cid = change_task_query()
        change_tasks = (await session.execute(
            q.add_columns(ChangeRequest.project_id)
            .join(ChangeRequest, ChangeRequest.id == cid)
            .where(ChangeRequest.status.not_in(TERMINAL_STATUSES)))).all()
    of_change = {t.id for t, _c, _p in change_tasks}
    for task, _cid, project_id in change_tasks:
        owner = await owner_of(task.owner_id, project_id, task.department_id)
        if owner is None:
            continue
        # reminded on the due date; "late" only at due + 1 wd
        if escalated(task.due_date, now):
            counts["overdue"] += await _once(
                session, [owner], kind="overdue",
                subject_key=f"task:{task.id}:overdue",
                title="Task late",
                body=f"Your task is late (was due {fmt_date(task.due_date)}); "
                     "your department and the change lead see it now.",
                link="/my-tasks")
        elif task.due_date.date() <= now.date():
            counts["due_soon"] += await _once(
                session, [owner], kind="due_soon",
                subject_key=f"task:{task.id}:due_soon",
                title="Task due today",
                body=f"Your task is due today ({fmt_date(task.due_date)}).",
                link="/my-tasks")

    tasks = (await session.execute(
        select(WfInstanceTask).where(
            WfInstanceTask.status == "active",
            WfInstanceTask.is_actionable.is_(True),
            WfInstanceTask.owner_id.is_not(None),
            WfInstanceTask.due_date.is_not(None),
        ))).scalars().all()
    for task in tasks:
        if task.id in of_change:
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

    # Overdue tasks of a change escalate to the change lead too, claimed or
    # not — the owned-task sweep above filters on owner_id, so an unclaimed
    # overdue task (the Phase-E primary path: assessments linked to engine
    # tasks) would otherwise notify nobody. Lead-scoped dedup key keeps it
    # independent of the owner's; lead == owner is skipped to avoid a
    # duplicate ping. A change's tasks: change-scoped instances and the
    # part revisions it originated (change_task_query, as the lead's
    # "Overdue" group counts them).
    # A6-03: a change whose lead cannot act (none, inactive, read-only)
    # escalates to Project Management, as its onward hop does
    # (ChangeService.escalation_targets); one lookup for the whole sweep.
    q, cid = change_task_query()
    lead_task_rows = (await session.execute(
        q.add_columns(ChangeRequest)
        .join(ChangeRequest, ChangeRequest.id == cid)
        .where(
            WfInstanceTask.due_date < now,
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
        ))).all()
    late_tasks = [(t, c) for t, _cid, c in lead_task_rows if escalated(t.due_date, now)]
    targets: dict = {}

    async def to(changes) -> None:
        """Fill `targets` for these changes (one lookup per batch)."""
        todo = {c.id: c for c in changes if c.id not in targets}
        if todo:
            targets.update(await ChangeService.escalation_targets(
                session, list(todo.values())))

    await to([c for _t, c in late_tasks])
    late_word = "late" if one_rule else "overdue"
    for task, c in late_tasks:
        owner = (await owner_of(task.owner_id, c.project_id, task.department_id)
                 if one_rule else task.owner_id)
        if one_rule:
            # D2b (review 2026-10-19): the engine task (an assessment's main
            # path, every check-workflow step) tells the project's named
            # backup too, once; not when the backup already owns it
            resp, backup = await _pair(session, c.project_id, task.department_id)
            if (resp is not None and backup is not None
                    and backup[0] != owner):
                counts["overdue"] += await _once(
                    session, [backup[0]], kind="overdue",
                    subject_key=f"task:{task.id}:overdue:backup",
                    title=f"Late: task on {c.change_number}",
                    body=(f"A task on {c.change_number} is late (was due "
                          f"{fmt_date(task.due_date)}); you back up {resp[1]}: "
                          "it is yours too now."),
                    link="/my-tasks")
        ids = [i for i in targets.get(c.id, []) if i is not None and i != owner]
        if not ids:
            continue
        claim = " and unclaimed" if task.owner_id is None else ""
        n = await _once(
            session, ids, kind="overdue",
            subject_key=f"task:{task.id}:overdue:lead",
            title=f"Late: task on {c.change_number}",
            body=f"A task on {c.change_number} is {late_word}"
                 f" (was due {fmt_date(task.due_date)}){claim}.",
            link=f"/changes/{c.id}",
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
    if one_rule:            # rows due today get their reminder (esc P1-1)
        wanted = ChangeAssessment.due_date < now + timedelta(days=1)
    assessments = (await session.execute(
        select(ChangeAssessment, ChangeRequest)
        .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
        .where(
            ChangeAssessment.status == "active",
            ChangeAssessment.wf_instance_task_id.is_(None),
            ChangeAssessment.due_date.is_not(None),
            wanted,
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
        ))).all()

    await to([c for a, c in assessments if escalated(a.due_date, now)])
    for assessment, change in assessments:
        due = assessment.due_date
        owner = (await owner_of(assessment.owner_id, change.project_id,
                                assessment.department_id)
                 if one_rule else assessment.owner_id)
        if not escalated(due, now):
            if (one_rule and owner is not None
                    and due.date() <= now.date()):
                counts["due_soon"] += await _once(
                    session, [owner], kind="due_soon",
                    subject_key=f"assessment:{assessment.id}:due_soon",
                    title="Assessment due today",
                    body=f"Your assessment is due today ({fmt_date(due)}).",
                    link="/my-tasks")
            continue
        if owner is not None:
            n = await _once(
                session, [owner], kind="overdue",
                subject_key=f"assessment:{assessment.id}:overdue",
                title=f"Assessment {late_word}",
                body=(f"Your assessment is late (was due {fmt_date(due)}); "
                      "your department and the change lead see it now."
                      if one_rule else
                      f"Your assessment is overdue (was due {fmt_date(due)})."),
                link="/my-tasks",
            )
            counts["overdue"] += n
        # D2b: a late department task goes to the project's named backup
        # too (once; not when the backup already owns it or is the lead)
        resp, backup = await _pair(session, change.project_id, assessment.department_id)
        if (one_rule and resp is not None and backup is not None
                and backup[0] != owner):
            counts["overdue"] += await _once(
                session, [backup[0]], kind="overdue",
                subject_key=f"assessment:{assessment.id}:overdue:backup",
                title=f"Late: assessment on {change.change_number}",
                body=(f"An assessment on {change.change_number} is late (was due "
                      f"{fmt_date(due)}); you back up {resp[1]}: it is yours too now."),
                link="/my-tasks")
        ids = [i for i in targets.get(change.id, [])
               if i is not None and i != owner]
        if ids:
            n = await _once(
                session, ids, kind="overdue",
                subject_key=f"assessment:{assessment.id}:overdue:lead",
                title=f"Late: assessment on {change.change_number}",
                body=f"An assessment on {change.change_number} is {late_word} "
                     f"(was due {fmt_date(due)}).",
                link=f"/changes/{assessment.change_id}",
            )
            counts["overdue"] += n

    # The computed rows under the same rule (owed_items: costing input,
    # sign-offs, the internal approval, overrides): who owes it is reminded
    # on the due date; at due + 1 wd the lead hears it (the lead's
    # "Overdue" group and the digest list it from the same items).
    if one_rule:
        from app.services.owed_items import owed_items
        live = (await session.execute(select(ChangeRequest).where(
            ChangeRequest.status.not_in(TERMINAL_STATUSES)))).scalars().all()
        items = await owed_items(session, live, now)
        await to([i["change"] for i in items if escalated(i["due"], now)])
        for item in items:
            c, due = item["change"], item["due"]
            if escalated(due, now):
                ids = [i for i in targets.get(c.id, [])
                       if i is not None and i not in item["owner_ids"]]
                if not ids:
                    continue
                counts["overdue"] += await _once(
                    session, ids, kind="overdue",
                    subject_key=f"{item['key']}:overdue:lead",
                    title=f"Late: {item['label']} on {c.change_number}",
                    body=(f"{item['label']} on your change is late (was due "
                          f"{fmt_date(due)}); owed by {item['owner']}."),
                    link=f"/changes/{c.id}")
            elif due.date() <= now.date() and item["owner_ids"]:
                counts["due_soon"] += await _once(
                    session, item["owner_ids"], kind="due_soon",
                    subject_key=f"{item['key']}:due_soon",
                    title=f"Due today: {item['label']} ({c.change_number})",
                    body=f"{item['label']} on {c.change_number} is due today "
                         f"({fmt_date(due)}).",
                    link=f"/changes/{c.id}")

    changes = (await session.execute(
        select(ChangeRequest).where(
            ChangeRequest.status.not_in(TERMINAL_STATUSES),
            ChangeRequest.required_by_date.is_not(None)
            | ChangeRequest.release_due_date.is_not(None),
        ))).scalars().all()

    for change in changes:
        # C20: the Sales contact who promised the date hears it too
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
    # §10 (RELEASE_V2): a concession ending within 10 wd is told once
    counts["concession_expiring"] = \
        await ValidationIssueService.remind_expiring_concessions(session)

    # C27 / P6: the daily overdue digest for the configured managers.
    from app.services.overdue_digest import send_overdue_digest
    counts["overdue_digest"] = await send_overdue_digest(session, now=now)
    # spec §0 Digest: one line per change for its lead, raiser, Sales contact
    from app.services.change_digest import send_change_digest
    counts["change_digest"] = await send_change_digest(session, now=now)

    return counts
