# backend/app/api/v1/changes/early_stage.py
"""Early stages polish (spec 2026-09-25 §16): capture, scoping, assessment.

    GET  /changes/{id}/stage-state                          cockpit data
    GET  /changes/{id}/assessments/{aid}/draft              checklist draft
    PUT  /changes/{id}/assessments/{aid}/draft              save it
    POST /changes/{id}/impacted-items/{item_id}/make-lead   lead item

(GET /changes/reference/labels lives in changes.py, declared before
/{change_id}.) Rules live in EarlyStageService: ChangeError -> 400,
PermissionError -> 403.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.change_service import ChangeError, ChangeService
from app.services.early_stage_service import EarlyStageService

router = APIRouter(prefix="/changes", tags=["changes"])


class DraftIn(BaseModel):
    draft: dict


async def _change(db: AsyncSession, change_id: int, user: User):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


@router.get("/{change_id}/stage-state")
async def stage_state(change_id: int,
                      current_user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    """Everything the cockpit needs to say what the change waits on and
    which buttons the caller gets (spec §16)."""
    change = await _change(db, change_id, current_user)
    return await EarlyStageService.stage_state(db, change, current_user)


@router.get("/{change_id}/assessments/{assessment_id}/draft")
async def get_draft(change_id: int, assessment_id: int,
                    current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    try:
        return await EarlyStageService.load_draft(db, change, assessment_id, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{change_id}/assessments/{assessment_id}/draft")
async def put_draft(change_id: int, assessment_id: int, body: DraftIn,
                    current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    try:
        out = await EarlyStageService.save_draft(
            db, change, assessment_id, current_user, body.draft)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return out


@router.post("/{change_id}/impacted-items/{item_id}/make-lead")
async def make_lead(change_id: int, item_id: int,
                    current_user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)):
    change = await _change(db, change_id, current_user)
    refusal = await EarlyStageService.impact_edit_refusal(db, change, current_user)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)
    try:
        item = await EarlyStageService.make_lead(db, change, item_id, current_user.id)
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return {"item_id": item.id, "part_id": item.part_id, "is_lead": True,
            "title": change.title, "title_auto": bool(change.title_auto)}


@router.get("/{change_id}/lead-candidates")
async def lead_candidates(change_id: int,
                          current_user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    """[{id, name, department, is_default, is_current}] for the lead picker:
    Project Manager members of the change's organization plus the current
    lead (spec §16)."""
    change = await _change(db, change_id, current_user)
    return await EarlyStageService.lead_candidates(db, change)


@router.get("/{change_id}/impact-objects")
async def impact_objects(change_id: int, part_ids: str = "",
                         current_user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Served-by objects for the given parts (comma-separated ids; default:
    the change's impacted items), during scoping and before routing."""
    change = await _change(db, change_id, current_user)
    try:
        ids = [int(x) for x in part_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="part_ids: comma-separated ids")
    if not ids:
        ids = [i.part_id for i in change.impacted_items]
    return await EarlyStageService.impact_objects(db, change, ids)
