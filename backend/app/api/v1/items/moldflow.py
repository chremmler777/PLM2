"""Moldflow timing endpoints: the project overview and the row writes.

  GET    /projects/{project_id}/moldflow   every tool with its produced articles and Moldflow rows
  POST   /parts/{part_id}/moldflow         a new row (version / layout) on a tool
  PATCH  /moldflow/{row_id}                change fields of a row
  DELETE /moldflow/{row_id}                soft delete

Reading: anyone in the project's organisation. Writing: the tool data rule
(Tool Engineer or admin, app/services/tool_rights.py), the same as DFM."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _part_in_org, _project_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.moldflow import ToolMoldflow
from app.models.part import Part
from app.services import moldflow_service as svc
from app.services.tool_rights import can_edit_tools, require_tool_editor

router = APIRouter(tags=["moldflow"])

InputStatus = Literal["open", "in_progress", "ready", "n/a"]
Status = Literal["not_started", "inputs_open", "ready_for_mf", "running", "received", "in_review",
                 "sent_to_customer", "customer_feedback", "rework", "final"]


class MoldflowFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Optional[str] = Field(None, max_length=10, pattern=r"^\s*[Vv]?\d{1,3}\s*$")
    cavity_layout: Optional[str] = Field(None, max_length=40)
    geometry_status: Optional[InputStatus] = None
    gate_status: Optional[InputStatus] = None
    udb_status: Optional[InputStatus] = None
    material_label: Optional[str] = Field(None, max_length=120)
    udb_source: Optional[str] = Field(None, max_length=255)
    mf_requested_on: Optional[date] = None
    received_on: Optional[date] = None
    ktx_review_on: Optional[date] = None
    sent_customer_on: Optional[date] = None
    customer_feedback_on: Optional[date] = None
    final_on: Optional[date] = None
    customer_feedback: Optional[str] = Field(None, max_length=10_000)
    status: Optional[Status] = None
    blockers: Optional[str] = Field(None, max_length=4000)
    owner: Optional[str] = Field(None, max_length=120)
    notes: Optional[str] = Field(None, max_length=10_000)
    source_ref: Optional[str] = Field(None, max_length=4000)


def _normal_version(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip().upper()
    return v if v.startswith("V") else f"V{v}"


def _http(e: svc.MoldflowError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


@router.get("/projects/{project_id}/moldflow")
async def project_moldflow(project_id: int, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)) -> dict:
    await _project_in_org(db, project_id, current_user.organization_id)
    return {"project_id": project_id, "tools": await svc.project_overview(db, project_id),
            "can_edit": await can_edit_tools(db, current_user)}


@router.post("/parts/{part_id}/moldflow", status_code=status.HTTP_201_CREATED)
async def create_moldflow(part_id: int, body: MoldflowFields, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict:
    await _part_in_org(db, part_id, current_user.organization_id)
    await require_tool_editor(db, current_user)
    tool = await db.get(Part, part_id)
    data = body.model_dump(exclude_unset=True)
    if "version" in data:
        data["version"] = _normal_version(data["version"])
    try:
        row = await svc.create(db, tool, data, current_user.id)
    except svc.MoldflowError as e:
        await db.rollback()
        raise _http(e)
    await db.commit()
    return svc.row_dict(row)


async def _row(db: AsyncSession, row_id: int, user: User) -> ToolMoldflow:
    row = await db.get(ToolMoldflow, row_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Moldflow row not found")
    await _part_in_org(db, row.tool_part_id, user.organization_id)
    return row


@router.patch("/moldflow/{row_id}")
async def update_moldflow(row_id: int, body: MoldflowFields, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> dict:
    row = await _row(db, row_id, current_user)
    await require_tool_editor(db, current_user)
    data = body.model_dump(exclude_unset=True)
    if "version" in data:
        data["version"] = _normal_version(data["version"])
    try:
        await svc.update(db, row, data, current_user.id)
    except svc.MoldflowError as e:
        await db.rollback()
        raise _http(e)
    await db.commit()
    return svc.row_dict(row)


@router.delete("/moldflow/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_moldflow(row_id: int, current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)) -> None:
    row = await _row(db, row_id, current_user)
    await require_tool_editor(db, current_user)
    await svc.soft_delete(db, row, current_user.id)
    await db.commit()
