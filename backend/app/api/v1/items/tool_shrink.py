"""Tool shrinkage decision record: candidates from MaterialDB, decide with a source and a
reason, verify after the trial (reported back to MaterialDB)."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _part_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.part import Part
from app.services import tool_shrink_service as svc
from app.services.tool_shrink_service import ShrinkError

router = APIRouter(tags=["tool-shrinkage"])



async def _tool(db: AsyncSession, part_id: int, user: User) -> Part:
    await _part_in_org(db, part_id, user.organization_id)
    part = await db.get(Part, part_id)
    if part.item_category != "tool":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Shrinkage decisions belong to tools")
    return part


def _values(tool: Part) -> dict:
    return {"parallel_pct": tool.tool_shrink_parallel_pct, "normal_pct": tool.tool_shrink_normal_pct,
            "combined_pct": tool.tool_shrink_combined_pct}


@router.get("/parts/{part_id}/shrinkage")
async def get_shrinkage(part_id: int, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)) -> dict:
    tool = await _tool(db, part_id, current_user)
    return {"tool": _values(tool), "decisions": await svc.history(db, tool.id), **await svc.candidates(db, tool)}


class DecideIn(BaseModel):
    """Either combined_pct, or parallel_pct and normal_pct."""
    parallel_pct: Optional[float] = Field(None, ge=0, le=5)
    normal_pct: Optional[float] = Field(None, ge=0, le=5)
    combined_pct: Optional[float] = Field(None, ge=0, le=5)
    source_kind: Literal["datasheet", "supplier", "ktx_experience", "own"]
    source_label: Optional[str] = Field(None, max_length=500)
    rationale: str = Field(min_length=1, max_length=4000)
    materialdb_id: Optional[int] = None
    material_label: Optional[str] = Field(None, max_length=300)
    candidates: Optional[list[dict]] = Field(None, max_length=100)


class VerifyIn(BaseModel):
    measured_parallel_pct: Optional[float] = Field(None, ge=-1, le=5)
    measured_normal_pct: Optional[float] = Field(None, ge=-1, le=5)
    measured_combined_pct: Optional[float] = Field(None, ge=-1, le=5)
    measured_ref: str = Field(min_length=1, max_length=300)
    verdict: Literal["correct", "offset", "wrong"]
    next_time_note: Optional[str] = Field(None, max_length=4000)


async def _done(db: AsyncSession, tool: Part) -> dict:
    await db.commit()
    return {"tool": _values(tool), "decisions": await svc.history(db, tool.id)}


@router.post("/parts/{part_id}/shrinkage/decisions")
async def decide(part_id: int, body: DecideIn, current_user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)) -> dict:
    tool = await _tool(db, part_id, current_user)
    try:
        await svc.decide(db, tool, current_user, parallel_pct=body.parallel_pct, normal_pct=body.normal_pct,
                         combined_pct=body.combined_pct,
                         source_kind=body.source_kind, source_label=body.source_label, rationale=body.rationale,
                         materialdb_id=body.materialdb_id, material_label=body.material_label,
                         shown=body.candidates)
    except ShrinkError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return await _done(db, tool)


@router.post("/parts/{part_id}/shrinkage/decisions/{decision_id}/verify")
async def verify(part_id: int, decision_id: int, body: VerifyIn, current_user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)) -> dict:
    tool = await _tool(db, part_id, current_user)
    try:
        await svc.verify(db, tool, decision_id, current_user, **body.model_dump())
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ShrinkError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return await _done(db, tool)


@router.post("/parts/{part_id}/shrinkage/decisions/{decision_id}/report")
async def report(part_id: int, decision_id: int, current_user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)) -> dict:
    """Send a verified decision to MaterialDB again (after a failed report)."""
    tool = await _tool(db, part_id, current_user)
    try:
        await svc.resend(db, tool, decision_id, current_user)
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ShrinkError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return await _done(db, tool)
