"""Reports/analytics: pipeline funnel + throughput + cycle time, department/
owner workload, and cost roll-ups - all live SQL aggregates, org-scoped."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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


@router.get("/ecr-kpis")
async def ecr_kpis_report(
    months: int = Query(12, ge=0, le=120),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """RFQ on-time and implementation-on-time KPIs over the last `months`
    calendar months (0 = all time)."""
    return await ReportService.ecr_kpis(db, current_user, months or None)


class EcrKpiTargets(BaseModel):
    """On-time targets in percent; omitted = unchanged."""
    rfq: Optional[float] = Field(None, ge=0, le=100)
    implementation: Optional[float] = Field(None, ge=0, le=100)


@router.get("/ecr-kpis/targets")
async def get_ecr_kpi_targets(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await ReportService.ecr_kpi_targets(db, current_user.organization_id)


@router.put("/ecr-kpis/targets")
async def put_ecr_kpi_targets(
    body: EcrKpiTargets,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Admins set the organization's targets."""
    if current_user.effective_role != "admin":
        raise HTTPException(403, "Only an admin may set KPI targets")
    return await ReportService.set_ecr_kpi_targets(db, current_user, body.model_dump())
