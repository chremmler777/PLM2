"""Idempotent dev-data repair after the final walk (2026-09-25).

    docker exec plm2-ecr-backend python -m scripts.repair_final_walk

1. P1-1: every assessment row of a started stage gets its engine task
   (ChangeRoutingService.repair_stage_tasks) on every change with an active
   change-scoped instance. Room-added departments (CR-2026-0001 Quality,
   CR-2026-0021 Quality/PM/Sales/APQP/Packaging, ...) had rows but no task.
   The routing read (GET /changes/{id}/routing) and the admin endpoint
   POST /changes/{id}/routing/repair run the same repair.
2. P2-4: a released or closed change keeps no workflow open
   (ChangeService.close_engine_work): the revisions' check flows are
   canceled and the change's own flow completed, open tasks waived.
3. P2-8: an escalated engineering review reads like an ECR: composed title
   (while automatic; EarlyStageService.recompose_title) and the project's PM
   responsible as lead, as EngineeringReviewService._as_full_ecr does on
   escalation. The lead is only set while nobody has chosen one since the
   escalation: no lead_changed entry after the latest review_escalated, or
   the lead is still the reviewer who raised the review. A lead picked by
   hand after the escalation is left alone.

Duplicate standing effort rows (P2-1) are merged by migration 101.
Running it again changes nothing: step 1 and 2 only act on what is missing
or still open, the title is recomposed only when it differs, and the lead
set here writes a lead_changed entry after the escalation, so the next run
leaves it (it is the PM, not the reviewer, unless the PM is the reviewer,
in which case it is already equal).
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncSessionLocal
from app.models.change import ChangeChangelog, ChangeRequest
from app.models.entities import User
from app.models.workflow import WfInstance


async def _lead_open(s: AsyncSession, change: ChangeRequest) -> bool:
    """True while the lead may still follow the PM responsible: nobody
    changed it after the (latest) escalation, or it is still the reviewer."""
    if change.lead_id is not None and change.lead_id == change.raised_by:
        return True
    escalated_at = (await s.execute(select(ChangeChangelog.id).where(
        ChangeChangelog.change_id == change.id,
        ChangeChangelog.action == "review_escalated")
        .order_by(ChangeChangelog.id.desc()).limit(1))).scalar_one_or_none()
    if escalated_at is None:
        return False
    later = (await s.execute(select(ChangeChangelog.id).where(
        ChangeChangelog.change_id == change.id,
        ChangeChangelog.action == "lead_changed",
        ChangeChangelog.id > escalated_at).limit(1))).scalar_one_or_none()
    return later is None


async def repair_escalated_reviews(s: AsyncSession, actor: int) -> list[str]:
    """Step 3: title and lead of escalated reviews. Returns report lines."""
    from app.services.change_service import ChangeService
    from app.services.early_stage_service import EarlyStageService
    from app.services.project_team_service import ProjectTeamService
    report = []
    escalated = (await s.execute(select(ChangeChangelog.change_id).where(
        ChangeChangelog.action == "review_escalated"))).scalars().all()
    for cid in sorted(set(escalated)):
        change = await ChangeService.get_change(s, cid)
        before = (change.title, change.lead_id)
        await EarlyStageService.recompose_title(s, change, actor)
        if await _lead_open(s, change):
            pm = await ProjectTeamService.responsible_user_id(
                s, change.project_id, "Project Manager")
            if pm is not None and pm != change.lead_id:
                old = change.lead_id
                change.lead_id = pm
                await s.flush()
                await ChangeService.append_changelog(
                    s, change, "lead_changed",
                    "Lead set to the project's Project Manager responsible "
                    "(escalated review, final-walk repair)", actor,
                    field_name="lead_id", old_value=old, new_value=pm)
        if (change.title, change.lead_id) != before:
            report.append(f"{change.change_number}: title/lead {before} -> "
                          f"{(change.title, change.lead_id)}")
    return report


async def main() -> None:
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService

    async with AsyncSessionLocal() as s:
        actor = (await s.execute(select(User.id).where(User.role == "admin")
                                 .order_by(User.id).limit(1))).scalar_one()
        report = []
        change_ids = sorted(set((await s.execute(
            select(WfInstance.change_id).where(
                WfInstance.change_id.isnot(None),
                WfInstance.status == "active"))).scalars().all()))
        for cid in change_ids:
            change = await ChangeService.get_change(s, cid)
            repaired = await ChangeRoutingService.repair_stage_tasks(s, change, actor)
            if repaired:
                report.append(f"{change.change_number}: tasks for assessments {repaired}")

        finished = (await s.execute(select(ChangeRequest.id).where(
            ChangeRequest.status.in_(("released", "closed"))))).scalars().all()
        for cid in finished:
            change = await ChangeService.get_change(s, cid)
            closed = await ChangeService.close_engine_work(
                s, change, actor,
                why=f"{change.change_number} {change.status}: closed by the "
                    "final-walk repair")
            if closed:
                report.append(f"{change.change_number}: closed instances {closed}")

        report += await repair_escalated_reviews(s, actor)
        await s.commit()
    print("\n".join(report) or "nothing to repair")


if __name__ == "__main__":
    asyncio.run(main())
