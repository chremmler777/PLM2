"""Workflow instance execution API endpoints (Phase 3c)."""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, get_current_user
from app.models import User, WfInstance, WfInstanceTask, WfTemplate
from app.models.workflow import WfStep
from app.schemas.workflow import (
    StartWorkflowRequest,
    CompleteTaskRequest,
    CancelWorkflowRequest,
)
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflow-instances", tags=["workflow-instances"])


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def _load_instance_full(db: AsyncSession, instance_id: int) -> WfInstance:
    """Load a WfInstance with all nested data needed for serialization."""
    result = await db.execute(
        select(WfInstance)
        .where(WfInstance.id == instance_id)
        .options(
            selectinload(WfInstance.tasks).selectinload(WfInstanceTask.step),
            selectinload(WfInstance.tasks).selectinload(WfInstanceTask.department),
            selectinload(WfInstance.template),
        )
    )
    return result.scalar_one()


def _serialize_instance(instance: WfInstance) -> dict:
    """Build a JSON-serializable dict from a fully loaded WfInstance."""
    return {
        "id": instance.id,
        "template_id": instance.template_id,
        "template_name": instance.template.name if instance.template else "",
        "revision_id": instance.revision_id,
        "status": instance.status,
        "current_stage_order": instance.current_stage_order,
        "started_by": instance.started_by,
        "started_at": instance.started_at,
        "completed_at": instance.completed_at,
        "canceled_at": instance.canceled_at,
        "cancel_reason": instance.cancel_reason,
        "tasks": [
            {
                "id": t.id,
                "instance_id": t.instance_id,
                "stage_order": t.stage_order,
                "step_id": t.step_id,
                "step_name": t.step.step_name if t.step else "",
                "department_id": t.department_id,
                "department_name": t.department.name if t.department else "",
                "rasic_letter": t.rasic_letter,
                "status": t.status,
                "is_actionable": t.is_actionable,
                "completed_by": t.completed_by,
                "completed_at": t.completed_at,
                "decision": t.decision,
                "notes": t.notes,
            }
            for t in instance.tasks
        ],
    }


# ---------------------------------------------------------------------------
# Routes — NOTE: my-tasks MUST be registered before /{instance_id}
# ---------------------------------------------------------------------------

@router.get("/my-tasks")
async def get_my_tasks(
    department_id: int = Query(..., description="Department ID to fetch tasks for"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List active actionable tasks for a department."""
    tasks = await WorkflowService.get_my_tasks(db, department_id)
    return tasks


@router.post(
    "/revisions/{revision_id}/start",
    status_code=status.HTTP_201_CREATED,
)
async def start_workflow(
    revision_id: int,
    request: StartWorkflowRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a workflow instance for a revision."""
    try:
        instance = await WorkflowService.start_workflow(
            db,
            revision_id=revision_id,
            template_id=request.template_id,
            started_by_id=current_user.id,
        )
        await db.commit()
        full = await _load_instance_full(db, instance.id)
        return _serialize_instance(full)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/revisions/{revision_id}/current")
async def get_current_workflow(
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest workflow instance for a revision (or null)."""
    instance = await WorkflowService.get_revision_workflow(db, revision_id)
    if instance is None:
        return {"instance": None}
    return {"instance": _serialize_instance(instance)}


@router.get("/{instance_id}")
async def get_workflow_instance(
    instance_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a workflow instance by ID."""
    full = await _load_instance_full(db, instance_id)
    if not full:
        raise HTTPException(status_code=404, detail="Workflow instance not found")
    return _serialize_instance(full)


@router.post("/{instance_id}/tasks/{task_id}/complete")
async def complete_task(
    instance_id: int,
    task_id: int,
    request: CompleteTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete an actionable task with approve/reject decision."""
    try:
        instance = await WorkflowService.complete_task(
            db,
            task_id=task_id,
            decision=request.decision,
            notes=request.notes,
            completed_by_id=current_user.id,
        )
        await db.commit()
        full = await _load_instance_full(db, instance.id)
        return _serialize_instance(full)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{instance_id}/cancel")
async def cancel_workflow(
    instance_id: int,
    request: CancelWorkflowRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel an active workflow instance."""
    try:
        instance = await WorkflowService.cancel_workflow(
            db,
            instance_id=instance_id,
            canceled_by_id=current_user.id,
            reason=request.reason,
        )
        await db.commit()
        full = await _load_instance_full(db, instance.id)
        return _serialize_instance(full)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
