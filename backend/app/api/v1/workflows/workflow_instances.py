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
    AssignTaskRequest,
    DueDateRequest,
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


def _serialize_task(t: WfInstanceTask) -> dict:
    """Build a JSON-serializable dict from a loaded WfInstanceTask.

    Requires ``step`` and ``department`` loaded; ``owner`` is lazy=selectin
    so ``owner_name``/``overdue`` are safe to read.
    """
    return {
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
        "owner_id": t.owner_id,
        "owner_name": t.owner_name,
        "accepted_at": t.accepted_at,
        "due_date": t.due_date,
        "overdue": t.overdue,
    }


def _serialize_instance(instance: WfInstance) -> dict:
    """Build a JSON-serializable dict from a fully loaded WfInstance."""
    return {
        "id": instance.id,
        "template_id": instance.template_id,
        "template_name": instance.template.name if instance.template else "",
        "part_revision_id": instance.part_revision_id,
        "status": instance.status,
        "current_stage_order": instance.current_stage_order,
        "started_by": instance.started_by,
        "started_at": instance.started_at,
        "completed_at": instance.completed_at,
        "canceled_at": instance.canceled_at,
        "cancel_reason": instance.cancel_reason,
        "tasks": [_serialize_task(t) for t in instance.tasks],
    }


async def _task_response(db: AsyncSession, task: WfInstanceTask) -> dict:
    """Reload a task with step/department loaded and serialize it."""
    result = await db.execute(
        select(WfInstanceTask)
        .where(WfInstanceTask.id == task.id)
        .options(
            selectinload(WfInstanceTask.step),
            selectinload(WfInstanceTask.department),
            selectinload(WfInstanceTask.owner),
        )
        # The task may already be in the identity map with a stale ``owner``
        # relationship (loaded as None before accept/assign set owner_id).
        # populate_existing forces the loaders to refresh it.
        .execution_options(populate_existing=True)
    )
    return _serialize_task(result.scalar_one())


# ---------------------------------------------------------------------------
# Routes — NOTE: my-tasks MUST be registered before /{instance_id}
# ---------------------------------------------------------------------------

@router.get("/open-task-count")
async def get_open_task_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Actionable open tasks for the nav badge — scoped to the user's
    departments when they have memberships, global otherwise."""
    from sqlalchemy import func

    stmt = (
        select(func.count(WfInstanceTask.id))
        .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
        .where(
            WfInstance.status == "active",
            WfInstanceTask.status == "active",
            WfInstanceTask.is_actionable == True,  # noqa: E712
        )
    )
    dept_ids = await WorkflowService.get_user_department_ids(db, current_user.id)
    if dept_ids:
        stmt = stmt.where(WfInstanceTask.department_id.in_(dept_ids))
    result = await db.execute(stmt)
    return {"count": result.scalar() or 0}


@router.get("/my-tasks")
async def get_my_tasks(
    department_id: int | None = Query(None, description="Department ID; omit to use your department memberships"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List active actionable tasks for a department, or for all of the
    current user's departments when department_id is omitted."""
    if department_id is not None:
        dept_ids = [department_id]
    else:
        dept_ids = await WorkflowService.get_user_department_ids(db, current_user.id)
    return await WorkflowService.get_my_tasks(db, dept_ids, current_user.id)


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


@router.post("/{instance_id}/tasks/{task_id}/accept")
async def accept_task(
    instance_id: int,
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept ownership of an actionable task (dept member or admin)."""
    try:
        task = await WorkflowService.accept_task(db, task_id, current_user)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _task_response(db, task)


@router.post("/{instance_id}/tasks/{task_id}/assign")
async def assign_task(
    instance_id: int,
    task_id: int,
    body: AssignTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign an actionable task to an active department member."""
    try:
        task = await WorkflowService.assign_task(
            db, task_id, body.user_id, current_user)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _task_response(db, task)


@router.put("/{instance_id}/tasks/{task_id}/due-date")
async def set_task_due_date(
    instance_id: int,
    task_id: int,
    body: DueDateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a task's due date (admin, workflow starter, or change lead)."""
    try:
        task = await WorkflowService.set_task_due_date(
            db, task_id, body.due_date, current_user)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return await _task_response(db, task)


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
