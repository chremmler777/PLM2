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
   (while automatic) and the project's PM responsible as lead
   (EngineeringReviewService._as_full_ecr).

Duplicate standing effort rows (P2-1) are merged by migration 101.
Running it again changes nothing.
"""
import asyncio

from sqlalchemy import select

from app.models import AsyncSessionLocal
from app.models.change import ChangeChangelog, ChangeRequest
from app.models.entities import User
from app.models.workflow import WfInstance


async def main() -> None:
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    from app.services.engineering_review_service import EngineeringReviewService

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

        escalated = (await s.execute(select(ChangeChangelog.change_id).where(
            ChangeChangelog.action == "review_escalated"))).scalars().all()
        for cid in sorted(set(escalated)):
            change = await ChangeService.get_change(s, cid)
            before = (change.title, change.lead_id)
            await EngineeringReviewService._as_full_ecr(s, change, actor)
            if (change.title, change.lead_id) != before:
                report.append(f"{change.change_number}: title/lead {before} -> "
                              f"{(change.title, change.lead_id)}")
        await s.commit()
    print("\n".join(report) or "nothing to repair")


if __name__ == "__main__":
    asyncio.run(main())
