"""Reports/analytics: pipeline funnel + throughput + cycle time, department/
owner workload, and cost roll-ups - all live SQL aggregates, org-scoped."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/pipeline")
async def pipeline_report(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await ReportService.pipeline(db, current_user)


@router.get("/workload")
async def workload_report(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await ReportService.workload(db, current_user)


@router.get("/cost")
async def cost_report(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await ReportService.cost(db, current_user)
