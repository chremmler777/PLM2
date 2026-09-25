"""P&L (Profit & Loss) read endpoints: per-change rows and portfolio summary.
Thin routes over PnlService — live SQL aggregates, org-scoped via viewer."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.pnl_service import PnlService

router = APIRouter(prefix="/pnl", tags=["pnl"])


def _validate_date(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {field}: {value!r}")
    return value


@router.get("/changes")
async def changes_pnl(
    project_id: Optional[int] = None,
    plant_id: Optional[int] = None,
    branch: Optional[Literal["customer", "internal"]] = None,
    status_group: Optional[Literal["pipeline", "realized"]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    rows = await PnlService.changes_pnl(
        db, current_user, project_id=project_id, plant_id=plant_id,
        branch=branch, status_group=status_group,
        date_from=date_from, date_to=date_to)
    return {"rows": rows}


@router.get("/summary")
async def pnl_summary(
    project_id: Optional[int] = None,
    plant_id: Optional[int] = None,
    branch: Optional[Literal["customer", "internal"]] = None,
    status_group: Optional[Literal["pipeline", "realized"]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    date_from = _validate_date(date_from, "date_from")
    date_to = _validate_date(date_to, "date_to")
    return await PnlService.summary(
        db, current_user, project_id=project_id, plant_id=plant_id,
        branch=branch, status_group=status_group,
        date_from=date_from, date_to=date_to)


@router.get("/changes/{change_id}/actuals")
async def change_actuals(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Plan versus actual for one change (stage 9).

    The same block the change's summation carries under 'actuals' — booked
    implementation hours valued at the departments' current rates, against
    what the costing planned, plus the costs that are not hours. Served here
    too for portfolio callers that have no reason to pull a whole costing
    grid. Additive: every pre-existing /pnl route is untouched.
    """
    from app.services.change_service import ChangeService
    from app.services.cost_service import CostService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    from app.services.negotiation_service import NegotiationService
    if not await NegotiationService.may_read(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Project Management, Sales, the change lead or an "
                   "admin may read a change's actuals")
    summation = await CostService.summation(db, change)
    return {"change_id": change.id, "actuals": summation["actuals"]}


@router.get("/changes/{change_id}/offer-vs-actual")
async def change_offer_vs_actual(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Offer versus doing for one change (spec §13): the plan frozen at
    customer acceptance against booked hours, supplier invoices, scrap and
    validation issue costs, with margins, slip and warnings. Cost roles."""
    from app.services.change_service import ChangeService
    from app.services.negotiation_service import NegotiationService
    change = await ChangeService.get_change(db, change_id, viewer=current_user)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    if not await NegotiationService.may_read(db, change, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only Project Management, Sales, the change lead or an "
                   "admin may read a change's P&L")
    return await PnlService.offer_vs_actual(db, change)
