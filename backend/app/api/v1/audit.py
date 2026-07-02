"""Unified audit timeline: filterable list, chain verification, CSV export."""
import csv
import io
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import AuditLog
from app.schemas.audit import AuditEntryResponse, AuditVerifyResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


def _filtered(correlation_id, entity_type, entity_id, user_id, date_from, date_to):
    q = select(AuditLog).order_by(AuditLog.id)
    if correlation_id is not None:
        q = q.where(AuditLog.correlation_id == correlation_id)
    if entity_type is not None:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(AuditLog.entity_id == entity_id)
    if user_id is not None:
        q = q.where(AuditLog.user_id == user_id)
    if date_from is not None:
        q = q.where(AuditLog.timestamp >= date_from)
    if date_to is not None:
        q = q.where(AuditLog.timestamp <= date_to)
    return q


@router.get("", response_model=List[AuditEntryResponse])
async def list_audit(
    correlation_id: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = _filtered(correlation_id, entity_type, entity_id, user_id, date_from, date_to)
    rows = (await db.execute(q.limit(limit).offset(offset))).scalars().all()
    return rows


@router.get("/verify", response_model=AuditVerifyResponse)
async def verify_audit(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await AuditService.verify_chain(db)


@router.get("/export")
async def export_audit(
    correlation_id: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = _filtered(correlation_id, entity_type, entity_id, user_id, date_from, date_to)
    rows = (await db.execute(q)).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "timestamp", "correlation_id", "entity_type", "entity_id",
                     "action", "user_id", "old_values", "new_values",
                     "previous_hash", "entry_hash"])
    for r in rows:
        writer.writerow([r.id, r.timestamp.isoformat(), r.correlation_id, r.entity_type,
                         r.entity_id, r.action, r.user_id, r.old_values, r.new_values,
                         r.previous_hash, r.entry_hash])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"})
