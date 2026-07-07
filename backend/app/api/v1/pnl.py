"""P&L (Profit & Loss) read endpoints: per-change rows and portfolio summary.
Thin routes over PnlService — live SQL aggregates, org-scoped via viewer."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.pnl_service import PnlService

router = APIRouter(prefix="/pnl", tags=["pnl"])


@router.get("/changes")
async def changes_pnl(
    project_id: Optional[int] = None,
    plant_id: Optional[int] = None,
    branch: Optional[Literal["customer", "internal"]] = None,
    status_group: Optional[Literal["pipeline", "realized"]] = None,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    rows = await PnlService.changes_pnl(
        db, current_user, project_id=project_id, plant_id=plant_id,
        branch=branch, status_group=status_group)
    return {"rows": rows}


@router.get("/summary")
async def pnl_summary(
    project_id: Optional[int] = None,
    plant_id: Optional[int] = None,
    branch: Optional[Literal["customer", "internal"]] = None,
    status_group: Optional[Literal["pipeline", "realized"]] = None,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await PnlService.summary(
        db, current_user, project_id=project_id, plant_id=plant_id,
        branch=branch, status_group=status_group)
