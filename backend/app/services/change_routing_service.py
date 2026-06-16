"""Change assessment routing: resolve the standard RASIC matrix, snapshot it per
change, generate staged assessments, advance stages, govern deviations, promote on
release. Standard is read from the flow designer (WfTemplate); falls back to the
legacy TYPE_DISCIPLINES dict when no ChangeRoutingStandard mapping exists.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.change import (
    ChangeRequest, ChangeAssessment, ChangeRouting, ChangeRoutingStandard,
    BLOCKING_LETTERS, TASK_LETTERS,
)
from app.models.workflow import Department, WfTemplate, WfStage, WfStep, WfStepRasic
from app.services.notification_service import NotificationService


# Legacy fallback (kept in sync with change_service.TYPE_DISCIPLINES).
FALLBACK_DISCIPLINES = {
    "physical_part": ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"],
    "tooling":       ["Tool Engineer", "Process Engineer", "Manufacturing Engineer"],
    "document_spec": ["Quality", "Project Manager"],
    "process_im":    ["Process Engineer", "Manufacturing Engineer", "Quality"],
    "packaging":     ["Packaging Engineer", "Quality", "Sales"],
}


def _first_stage_order(stages) -> int:
    orders = [s["stage_order"] for s in stages if s["departments"]]
    return min(orders) if orders else 1


class ChangeRoutingService:

    @staticmethod
    async def resolve_standard(session: AsyncSession, change_type: str):
        """Return (template_id|None, template_version|None, stages).

        stages = [{"stage_order": int, "departments": [{"department_id", "rasic_letter"}]}]
        """
        std = (await session.execute(
            select(ChangeRoutingStandard).where(ChangeRoutingStandard.change_type == change_type)
        )).scalar_one_or_none()

        if std is not None:
            template = (await session.execute(
                select(WfTemplate)
                .where(WfTemplate.id == std.template_id)
                .options(
                    selectinload(WfTemplate.stages)
                    .selectinload(WfStage.steps)
                    .selectinload(WfStep.rasic_assignments)
                )
            )).scalar_one_or_none()
            if template is not None and template.stages:
                stages = []
                for stage in sorted(template.stages, key=lambda s: s.stage_order):
                    deps = []
                    for step in sorted(stage.steps, key=lambda s: s.position_in_stage):
                        for r in step.rasic_assignments:
                            deps.append({"department_id": r.department_id, "rasic_letter": r.rasic_letter})
                    stages.append({"stage_order": stage.stage_order, "departments": deps})
                return template.id, template.version, stages

        # Fallback: single implicit stage, all blocking R, from discipline names.
        names = FALLBACK_DISCIPLINES.get(change_type, [])
        rows = (await session.execute(
            select(Department).where(Department.name.in_(names))
        )).scalars().all() if names else []
        deps = [{"department_id": d.id, "rasic_letter": "R"} for d in rows]
        return None, None, [{"stage_order": 1, "departments": deps}]

    @staticmethod
    async def build_routing(session: AsyncSession, change: ChangeRequest, user_id: int) -> ChangeRouting:
        """Idempotent: if routing already exists, do nothing. Otherwise snapshot the
        standard, create assessment rows (pending), broadcast start, activate stage 1.

        ``user_id`` is the actor initiating routing; reserved for future audit-log
        attribution and intentionally unused here.
        """
        existing = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        if existing is not None:
            return existing

        template_id, template_version, stages = await ChangeRoutingService.resolve_standard(
            session, change.change_type)

        routing = ChangeRouting(
            change_id=change.id, template_id=template_id, template_version=template_version,
            standard_snapshot={"stages": stages},
        )
        session.add(routing)

        for stage in stages:
            for dep in stage["departments"]:
                if dep["rasic_letter"] not in TASK_LETTERS:
                    continue  # I => notification only, no row
                session.add(ChangeAssessment(
                    change_id=change.id, department_id=dep["department_id"],
                    verdict="pending", stage_order=stage["stage_order"],
                    rasic_letter=dep["rasic_letter"], status="pending",
                ))
        await session.flush()

        # Broadcast "started" to everyone involved (incl. I).
        involved = ChangeRoutingService._involved_department_ids(stages)
        if involved:
            await NotificationService.notify_departments(
                session, involved,
                title=f"Change {change.change_number} entered assessment",
                body=f"'{change.title}' has started cross-functional assessment.",
                link=f"/changes/{change.id}",
            )
        # Activate the first stage that has any rows.
        await ChangeRoutingService.activate_stage(session, change, _first_stage_order(stages))
        return routing

    @staticmethod
    def _involved_department_ids(stages) -> list[int]:
        ids = []
        for stage in stages:
            for dep in stage["departments"]:
                ids.append(dep["department_id"])
        return list(dict.fromkeys(ids))

    @staticmethod
    async def activate_stage(session: AsyncSession, change: ChangeRequest, stage_order: int) -> None:
        rows = (await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.stage_order == stage_order)
            )
        )).scalars().all()
        notify = []
        for a in rows:
            if a.status == "pending":
                a.status = "active"
                notify.append(a.department_id)
        await session.flush()
        if notify:
            await NotificationService.notify_departments(
                session, list(dict.fromkeys(notify)),
                title=f"Assessment due — {change.change_number}",
                body=f"Stage {stage_order} of '{change.title}' needs your assessment.",
                link=f"/changes/{change.id}",
            )

    @staticmethod
    async def maybe_advance(session: AsyncSession, change: ChangeRequest, user_id: int) -> None:
        """If the active stage's blocking (R/A) assessments are all submitted, activate
        the next stage that has rows. C/S never block."""
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        if not rows:
            return
        all_orders = sorted({a.stage_order for a in rows})
        # The "current" stage is the highest one that has already been activated —
        # i.e. has any row no longer pending (active or submitted). Later stages are
        # still entirely pending. A stage advances only once its blocking (R/A) rows
        # are all submitted; C/S never block.
        activated_orders = [
            o for o in all_orders
            if any(a.stage_order == o and a.status != "pending" for a in rows)
        ]
        if not activated_orders:
            return
        current = activated_orders[-1]
        blocking = [a for a in rows if a.stage_order == current and a.rasic_letter in BLOCKING_LETTERS]
        if any(a.status != "submitted" for a in blocking):
            return  # still waiting on R/A
        # Activate the next stage that still has pending rows.
        for nxt in [o for o in all_orders if o > current]:
            if any(a.stage_order == nxt and a.status == "pending" for a in rows):
                await ChangeRoutingService.activate_stage(session, change, nxt)
                return

    @staticmethod
    async def blocking_complete(session: AsyncSession, change: ChangeRequest) -> bool:
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        blocking = [a for a in rows if a.rasic_letter in BLOCKING_LETTERS]
        return bool(blocking) and all(a.status == "submitted" for a in blocking)

    @staticmethod
    async def _routing(session: AsyncSession, change: ChangeRequest) -> ChangeRouting:
        r = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        if r is None:
            raise ValueError("Change has no routing yet")
        return r

    @staticmethod
    async def apply_deviation(session: AsyncSession, change: ChangeRequest, user_id: int, *,
                              op: str, department_id: int, rasic_letter: Optional[str] = None,
                              stage_order: Optional[int] = None) -> ChangeRouting:
        from app.services.change_service import ChangeService  # local import avoids cycle
        routing = await ChangeRoutingService._routing(session, change)
        existing = (await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.department_id == department_id))
        )).scalar_one_or_none()

        if op == "add":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("add requires a task letter (R/A/S/C)")
            order = stage_order or 1
            if existing is None:
                session.add(ChangeAssessment(
                    change_id=change.id, department_id=department_id, verdict="pending",
                    stage_order=order, rasic_letter=rasic_letter,
                    status="active" if order <= await ChangeRoutingService._max_active_order(session, change) else "pending",
                ))
            else:
                existing.rasic_letter = rasic_letter
                existing.stage_order = order
            desc = f"added dept {department_id} as {rasic_letter} in stage {order}"
        elif op == "remove":
            if existing is not None:
                await session.delete(existing)
            desc = f"removed dept {department_id}"
        elif op == "reletter":
            if rasic_letter not in TASK_LETTERS:
                raise ValueError("reletter requires a task letter (R/A/S/C)")
            if existing is None:
                raise ValueError("no assessment to reletter")
            existing.rasic_letter = rasic_letter
            desc = f"re-lettered dept {department_id} to {rasic_letter}"
        else:
            raise ValueError(f"unknown op '{op}'")

        routing.has_deviation = True
        routing.deviation_status = "pending_approval"
        routing.deviation_proposed_by = user_id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "routing_deviation", f"Routing deviation: {desc}", user_id)
        return routing

    @staticmethod
    async def _max_active_order(session: AsyncSession, change: ChangeRequest) -> int:
        rows = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        active = [a.stage_order for a in rows if a.status == "active"]
        return max(active) if active else 1

    @staticmethod
    async def approve_deviation(session: AsyncSession, change: ChangeRequest, user_id: int) -> ChangeRouting:
        from app.services.change_service import ChangeService
        routing = await ChangeRoutingService._routing(session, change)
        if routing.deviation_status != "pending_approval":
            raise ValueError("No deviation pending approval")
        # No self-approval. If a non-lead proposed it, only the lead may approve. If the
        # lead proposed it, anyone-but-the-proposer (i.e. the PM) may approve.
        if routing.deviation_proposed_by == user_id:
            raise ValueError("Cannot approve your own routing deviation")
        if (change.lead_id is not None
                and routing.deviation_proposed_by != change.lead_id
                and user_id != change.lead_id):
            raise ValueError("Only the change lead may approve this deviation")
        routing.deviation_status = "approved"
        routing.deviation_approved_by = user_id
        routing.deviation_approved_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "routing_deviation_approved", "Routing deviation approved", user_id)
        return routing
