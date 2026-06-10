"""Dashboard aggregation endpoint - system overview in one call."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import Project
from app.models.part import Part, PartRevision, RevisionChangelog
from app.models.workflow import Department, WfInstance, WfInstanceTask, WfStage, WfTemplate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Counts, active workflows, department queues, and recent activity."""
    # --- Counts ---
    async def count(stmt):
        return (await db.execute(stmt)).scalar() or 0

    counts = {
        "projects": await count(select(func.count(Project.id))),
        "parts": await count(select(func.count(Part.id))),
        "revisions": await count(select(func.count(PartRevision.id))),
        "frozen_revisions": await count(
            select(func.count(PartRevision.id)).where(PartRevision.status == "frozen")
        ),
        "active_workflows": await count(
            select(func.count(WfInstance.id)).where(WfInstance.status == "active")
        ),
    }

    # --- Active workflows with part/revision context ---
    result = await db.execute(
        select(WfInstance, WfTemplate.name, PartRevision.revision_name, Part.id, Part.part_number, Part.name, Part.project_id)
        .join(WfTemplate, WfTemplate.id == WfInstance.template_id)
        .join(PartRevision, PartRevision.id == WfInstance.part_revision_id)
        .join(Part, Part.id == PartRevision.part_id)
        .where(WfInstance.status == "active")
        .order_by(WfInstance.started_at.desc())
        .limit(20)
    )
    rows = result.all()

    # Total stages per template (one grouped query)
    stage_counts = {
        tid: total
        for tid, total in (
            await db.execute(
                select(WfStage.template_id, func.count(func.distinct(WfStage.stage_order)))
                .group_by(WfStage.template_id)
            )
        ).all()
    }

    # Open task counts per instance (one grouped query)
    open_by_instance = {
        iid: n
        for iid, n in (
            await db.execute(
                select(WfInstanceTask.instance_id, func.count(WfInstanceTask.id))
                .where(WfInstanceTask.status == "active", WfInstanceTask.is_actionable == True)  # noqa: E712
                .group_by(WfInstanceTask.instance_id)
            )
        ).all()
    }

    active_workflows = [
        {
            "instance_id": inst.id,
            "template_name": template_name,
            "part_id": part_id,
            "part_number": part_number,
            "part_name": part_name,
            "project_id": project_id,
            "revision_name": revision_name,
            "current_stage": inst.current_stage_order,
            "total_stages": stage_counts.get(inst.template_id, inst.current_stage_order),
            "open_tasks": open_by_instance.get(inst.id, 0),
            "started_at": inst.started_at.isoformat() if inst.started_at else None,
        }
        for inst, template_name, revision_name, part_id, part_number, part_name, project_id in rows
    ]

    # --- Open tasks per department (active workflows only) ---
    result = await db.execute(
        select(Department.id, Department.name, func.count(WfInstanceTask.id))
        .join(WfInstanceTask, WfInstanceTask.department_id == Department.id)
        .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
        .where(
            WfInstance.status == "active",
            WfInstanceTask.status == "active",
            WfInstanceTask.is_actionable == True,  # noqa: E712
        )
        .group_by(Department.id, Department.name)
        .order_by(func.count(WfInstanceTask.id).desc())
    )
    department_queues = [
        {"department_id": did, "name": name, "open_tasks": n} for did, name, n in result.all()
    ]

    # --- Recent activity across all parts ---
    result = await db.execute(
        select(RevisionChangelog, Part.name, Part.project_id)
        .join(Part, Part.id == RevisionChangelog.part_id)
        .order_by(RevisionChangelog.performed_at.desc())
        .limit(15)
    )
    recent_activity = [
        {
            "id": entry.id,
            "action": entry.action,
            "description": entry.action_description,
            "part_id": entry.part_id,
            "part_name": part_name,
            "project_id": project_id,
            "performed_at": entry.performed_at.isoformat() if entry.performed_at else None,
        }
        for entry, part_name, project_id in result.all()
    ]

    return {
        "counts": counts,
        "active_workflows": active_workflows,
        "department_queues": department_queues,
        "recent_activity": recent_activity,
    }
