"""Retest N2 / T16 (2026-10-27): every task newly somebody's is one notice
to its owner (spec §0 "the task is the notice"): the project team's
responsible per department, its backup while out, else the members
(NotificationService.notify_team), a named person directly. These are the
stage hops that open tasks no other notice announced: costing (each
department that owes its input, audit P3-13), approval (lead's plan,
Logistics' bank build, the at-risk sign-offs and Sales' quote), the detailed
plan (each team confirms it) and validation (each release-check owner)."""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest
from app.models.workflow import Department


async def _dept_ids(session: AsyncSession, *names: str) -> dict[str, int]:
    return dict((await session.execute(select(Department.name, Department.id).where(
        Department.name.in_(names), Department.is_active.is_(True)))).all())


def _link(change: ChangeRequest, tab: str) -> str:
    return f"/changes/{change.id}?tab={tab}"


async def on_costing(session: AsyncSession, change: ChangeRequest,
                     actor_id: Optional[int]) -> int:
    """Audit P3-13: entering costing, each department that still owes its
    costing input hears it (it was told nothing until the quote was
    ready). Once per change and department."""
    from app.services import cm_switches
    from app.services.change_service import ChangeService
    from app.services.notification_service import NotificationService
    if not cm_switches.on("ASSESSMENT_V2"):
        return 0
    num = change.change_number
    sent = 0
    for did in await ChangeService.costing_pending_department_ids(session, change):
        sent += await NotificationService.notify_team(
            session, change.project_id, [did], kind="task_new",
            subject_key=f"chg:{change.id}:costing_open:{did}",
            title=f"Your costing: {num}"[:255],
            body=(f"'{change.title}' is in costing: enter your department's hours "
                  "and costs for the change and finalize them (Costing tab)."),
            link=_link(change, "costing"))
    return sent


async def on_approved(session: AsyncSession, change: ChangeRequest,
                      actor_id: Optional[int]) -> None:
    from app.services.notification_service import NotificationService
    from app.services import mother_plants as mp
    if mp.is_mother_plant(change):
        return          # MotherPlantService.on_approved tells its people
    num = change.change_number
    if change.lead_id is not None and change.lead_id != actor_id:
        await NotificationService.notify_once(
            session, [change.lead_id], kind="task_new",
            subject_key=f"chg:{change.id}:approved:lead",
            title=f"Approved: {num}: create the detailed plan"[:255],
            body=(f"'{change.title}' is approved. Create the detailed plan (Timing "
                  "tab); then the teams confirm it."),
            link=_link(change, "timing"))
    ids = await _dept_ids(session, "Logistics", "Project Manager", "Quality")
    if change.bank_build_mode is None and "Logistics" in ids:
        await NotificationService.notify_team(
            session, change.project_id, [ids["Logistics"]], kind="task_new",
            subject_key=f"chg:{change.id}:bank_build",
            title=f"Decide the bank build: {num}"[:255],
            body=f"'{change.title}' is approved: decide how it reaches the line.",
            link=_link(change, "timing"))
    if change.customer_relevant and change.start_at_risk_approved_at is not None:
        # §7a: started at risk: both sign-offs and the quote are still owed
        owed = [ids[n] for n, by in (("Project Manager", change.pm_signed_by),
                                     ("Quality", change.quality_signed_by))
                if by is None and n in ids]
        if owed:
            await NotificationService.notify_team(
                session, change.project_id, owed, kind="task_new",
                subject_key=f"chg:{change.id}:at_risk:signoff",
                title=f"Sign off: {num} (started at risk)"[:255],
                body=f"'{change.title}' started at risk: your sign-off is owed.",
                link=_link(change, "offer"))
        if change.sales_owner_id is not None and change.quoted_at is None:
            await NotificationService.notify_once(
                session, [change.sales_owner_id], kind="task_new",
                subject_key=f"chg:{change.id}:at_risk:quote",
                title=f"Create the quote: {num} (started at risk)"[:255],
                body=f"'{change.title}' started at risk: the offer is still owed.",
                link=_link(change, "offer"))


async def on_detailed_plan(session: AsyncSession, change: ChangeRequest,
                           actor_id: Optional[int]) -> None:
    from app.services.change_plan_service import ChangePlanService
    from app.services.notification_service import NotificationService
    if change.status != "approved" or change.timing_validated_at is not None:
        return
    ids = await ChangePlanService.required_department_ids(session, change)
    if not ids:
        return
    await NotificationService.notify_team(
        session, change.project_id, ids, kind="task_new",
        subject_key=f"chg:{change.id}:plan:{int(change.plan_revision or 0)}",
        title=f"Confirm the detailed plan: {change.change_number}"[:255],
        body=f"'{change.title}': confirm your department's plan blocks (Timing tab).",
        link=_link(change, "timing"))


async def on_validation(session: AsyncSession, change: ChangeRequest,
                        actor_id: Optional[int]) -> None:
    from app.services import release_checklist as rc
    from app.services.implementation_service import ImplementationService
    from app.services.notification_service import NotificationService
    from app.services.release_service import ReleaseService
    rows = await ReleaseService.view_rows(session, change)
    owners = {r.department_id for r in rows
              if r.status not in ("done", "na") and r.department_id is not None}
    # the departments the stage notice told already ("record your checks")
    told = set(await ImplementationService.implementing_department_ids(session, change))
    if not change.customer_relevant:
        skip = await _dept_ids(session, "Project Manager", "Sales")
        told |= set(skip.values())
    ids = sorted(owners - told)
    if not ids:
        return
    await NotificationService.notify_team(
        session, change.project_id, ids, kind="task_new",
        subject_key=f"chg:{change.id}:release_checks",
        title=f"Release checklist: {change.change_number}"[:255],
        body=f"'{change.title}' is in validation: answer your release checklist rows.",
        link=_link(change, "release"))
