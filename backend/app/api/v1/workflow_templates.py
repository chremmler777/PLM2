"""Workflow template designer API endpoints."""
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from datetime import datetime
from app.dependencies import get_db, get_current_user
from app.models import (
    User, Department, WfTemplate, WfStage, WfStep, WfStepRasic, WfTemplateHistory
)
from app.schemas.workflow import (
    DepartmentResponse, WfTemplateResponse, WfTemplateListResponse,
    WfTemplateSave
)

router = APIRouter(prefix="/workflow-templates", tags=["workflow-templates"])


@router.get("/departments", response_model=list[DepartmentResponse])
async def list_departments(db: AsyncSession = Depends(get_db)):
    """List all available departments/roles."""
    result = await db.execute(
        select(Department).order_by(Department.sort_order, Department.name)
    )
    return result.scalars().all()


@router.get("", response_model=list[WfTemplateListResponse])
async def list_templates(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List workflow templates."""
    result = await db.execute(
        select(WfTemplate).order_by(WfTemplate.created_at.desc())
    )
    return result.scalars().all()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(
    request: WfTemplateSave,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new workflow template."""
    try:
        # Create template
        template = WfTemplate(
            name=request.name,
            description=request.description,
            version=1,
            created_by=current_user.id,
            created_at=datetime.utcnow()
        )
        db.add(template)
        await db.flush()

        # Add stages and steps
        for stage_data in request.stages:
            stage = WfStage(
                template_id=template.id,
                stage_order=stage_data.stage_order,
                name=stage_data.name
            )
            db.add(stage)
            await db.flush()

            for step_data in stage_data.steps:
                step = WfStep(
                    stage_id=stage.id,
                    step_name=step_data.step_name,
                    position_in_stage=step_data.position_in_stage
                )
                db.add(step)
                await db.flush()

                for rasic_data in step_data.rasic_assignments:
                    rasic = WfStepRasic(
                        step_id=step.id,
                        department_id=rasic_data.department_id,
                        rasic_letter=rasic_data.rasic_letter
                    )
                    db.add(rasic)

        await db.flush()

        # Build snapshot from request data (don't access lazy-loaded relationships)
        snapshot_data = {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "version": template.version,
            "stages": [
                {
                    "stage_order": stage_data.stage_order,
                    "name": stage_data.name,
                    "steps": [
                        {
                            "step_name": step_data.step_name,
                            "position_in_stage": step_data.position_in_stage,
                            "rasic": [
                                {
                                    "department_id": rasic_data.department_id,
                                    "rasic_letter": rasic_data.rasic_letter,
                                }
                                for rasic_data in step_data.rasic_assignments
                            ]
                        }
                        for step_data in stage_data.steps
                    ]
                }
                for stage_data in request.stages
            ]
        }

        history = WfTemplateHistory(
            template_id=template.id,
            version=1,
            snapshot=snapshot_data,
            changed_by=current_user.id,
            change_note="Initial creation"
        )
        db.add(history)

        await db.commit()

        # Return simple response dict
        return {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "version": template.version,
            "is_active": template.is_active,
            "created_at": template.created_at,
            "created_by": template.created_by,
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{template_id}/history", response_model=list[dict])
async def get_template_history(
    template_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get all versions of a workflow template from history."""
    result = await db.execute(
        select(WfTemplateHistory)
        .where(WfTemplateHistory.template_id == template_id)
        .order_by(WfTemplateHistory.version)
    )
    histories = result.scalars().all()
    if not histories:
        raise HTTPException(status_code=404, detail="No history found")

    return [
        {
            "version": h.version,
            "snapshot": h.snapshot,
            "changed_at": h.changed_at,
            "change_note": h.change_note,
        }
        for h in histories
    ]


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get workflow template with full structure."""
    result = await db.execute(
        select(WfTemplate).where(WfTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    # Load stages with their relationships
    result = await db.execute(
        select(WfTemplate)
        .where(WfTemplate.id == template_id)
        .options(
            selectinload(WfTemplate.stages).selectinload(WfStage.steps).selectinload(WfStep.rasic_assignments)
        )
    )
    template = result.scalar_one()

    # Build response with loaded relationships
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "version": template.version,
        "is_active": template.is_active,
        "created_at": template.created_at,
        "created_by": template.created_by,
        "updated_at": template.updated_at,
        "updated_by": template.updated_by,
        "stages": [
            {
                "id": stage.id,
                "template_id": stage.template_id,
                "stage_order": stage.stage_order,
                "name": stage.name,
                "steps": [
                    {
                        "id": step.id,
                        "stage_id": step.stage_id,
                        "step_name": step.step_name,
                        "position_in_stage": step.position_in_stage,
                        "rasic_assignments": [
                            {
                                "id": rasic.id,
                                "step_id": rasic.step_id,
                                "department_id": rasic.department_id,
                                "rasic_letter": rasic.rasic_letter,
                            }
                            for rasic in step.rasic_assignments
                        ]
                    }
                    for step in stage.steps
                ]
            }
            for stage in template.stages
        ]
    }


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    request: WfTemplateSave,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update workflow template (creates new version)."""
    try:
        result = await db.execute(
            select(WfTemplate).where(WfTemplate.id == template_id)
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Delete old stages and steps (cascade)
        result = await db.execute(
            select(WfStage).where(WfStage.template_id == template_id)
        )
        old_stages = result.scalars().all()
        for stage in old_stages:
            await db.delete(stage)

        # Update template metadata
        template.name = request.name
        template.description = request.description
        template.version += 1
        template.updated_by = current_user.id
        template.updated_at = datetime.utcnow()

        await db.flush()

        # Add new stages and steps
        for stage_data in request.stages:
            stage = WfStage(
                template_id=template.id,
                stage_order=stage_data.stage_order,
                name=stage_data.name
            )
            db.add(stage)
            await db.flush()

            for step_data in stage_data.steps:
                step = WfStep(
                    stage_id=stage.id,
                    step_name=step_data.step_name,
                    position_in_stage=step_data.position_in_stage
                )
                db.add(step)
                await db.flush()

                for rasic_data in step_data.rasic_assignments:
                    rasic = WfStepRasic(
                        step_id=step.id,
                        department_id=rasic_data.department_id,
                        rasic_letter=rasic_data.rasic_letter
                    )
                    db.add(rasic)

        await db.flush()

        # Build snapshot from request data (don't access lazy-loaded relationships)
        snapshot_data = {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "version": template.version,
            "stages": [
                {
                    "stage_order": stage_data.stage_order,
                    "name": stage_data.name,
                    "steps": [
                        {
                            "step_name": step_data.step_name,
                            "position_in_stage": step_data.position_in_stage,
                            "rasic": [
                                {
                                    "department_id": rasic_data.department_id,
                                    "rasic_letter": rasic_data.rasic_letter,
                                }
                                for rasic_data in step_data.rasic_assignments
                            ]
                        }
                        for step_data in stage_data.steps
                    ]
                }
                for stage_data in request.stages
            ]
        }

        history = WfTemplateHistory(
            template_id=template.id,
            version=template.version,
            snapshot=snapshot_data,
            changed_by=current_user.id,
            change_note=request.change_note
        )
        db.add(history)

        await db.commit()

        # Return simple response dict
        return {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "version": template.version,
            "is_active": template.is_active,
            "created_at": template.created_at,
            "created_by": template.created_by,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate a template (soft delete)."""
    result = await db.execute(
        select(WfTemplate).where(WfTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.is_active = False
    template.updated_by = current_user.id
    template.updated_at = datetime.utcnow()

    await db.commit()


def _build_snapshot(template: WfTemplate) -> dict:
    """Build a JSON snapshot of the full template structure."""
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "version": template.version,
        "stages": [
            {
                "id": stage.id,
                "stage_order": stage.stage_order,
                "name": stage.name,
                "steps": [
                    {
                        "id": step.id,
                        "step_name": step.step_name,
                        "position_in_stage": step.position_in_stage,
                        "rasic": [
                            {
                                "department_id": rasic.department_id,
                                "department_name": rasic.department.name,
                                "rasic_letter": rasic.rasic_letter
                            }
                            for rasic in step.rasic_assignments
                        ]
                    }
                    for step in stage.steps
                ]
            }
            for stage in template.stages
        ]
    }
