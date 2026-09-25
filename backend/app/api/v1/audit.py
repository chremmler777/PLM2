"""Unified audit timeline: filterable list, chain verification, CSV export.

Org scoping (Task 22): the audit trail is cross-entity and most rows carry a
correlation_id equal to a change's change_number (change lifecycle events and
workflow-instance events - see change_service.py / workflow_service.py). Rows
with no correlation_id (e.g. user-management entity_type="user" events) or
foreign correlations do not resolve to a change the viewer could look up
anyway, so - to avoid leaking cross-org change activity through the unified
timeline - non-admin viewers only see entries whose correlation_id matches a
change_number in their own organization (reusing Task 13's `_org_scope`
change-number set). Entries with a NULL or foreign correlation_id are hidden
from non-admins by this rule. Admins bypass scoping entirely and see every
entry, matching `_org_scope`'s existing admin bypass."""
import csv
import io
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.change import ChangeRequest
from app.models.entities import AuditLog
from app.schemas.audit import AuditEntryResponse, AuditVerifyResponse
from app.services.audit_service import AuditService
from app.services.change_service import _org_scope

router = APIRouter(prefix="/audit", tags=["audit"])


async def _price_redactor(db: AsyncSession, current_user: User):
    """A function row -> bool: must this row's money be blanked for the
    caller? Rows correlated to a change follow NegotiationService.may_read
    for that change (admin, lead, PM, Sales); other rows carry no prices."""
    from app.services.price_redaction import PriceViewer
    viewer = PriceViewer(db, current_user)
    cache: dict[str, bool] = {}
    changes: dict[str, object] = {}

    async def change_of(cid):
        if cid not in changes:
            changes[cid] = (await db.execute(select(ChangeRequest).where(
                ChangeRequest.change_number == cid))).scalars().first()
        return changes[cid]

    async def must_redact(row) -> bool:
        cid = row.correlation_id
        if not cid:
            return False
        if cid not in cache:
            change = await change_of(cid)
            cache[cid] = change is not None and not await viewer.may_read(change)
        return cache[cid]
    must_redact.change_of = change_of
    return must_redact


async def _quote_hider(db: AsyncSession, current_user: User, must_redact):
    """row -> bool: does this row name a vendor quote the caller may not
    read (the costing-position rule, price_redaction.QuoteReader)?"""
    from app.services.price_redaction import QuoteReader
    reader = QuoteReader(db, current_user)

    async def hides(row) -> bool:
        if not row.correlation_id or not await must_redact(row):
            return False
        change = await must_redact.change_of(row.correlation_id)
        return await reader.hides(change, row.action, row.old_values,
                                  row.new_values)
    return hides


def _filtered(correlation_id, entity_type, entity_id, user_id, date_from, date_to):
    q = select(AuditLog)
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


def _apply_org_scope(q, current_user: User):
    """Non-admins: restrict to entries correlated to a change in their org.
    Admins: unrestricted (see module docstring for the scoping decision)."""
    if current_user.effective_role == "admin":
        return q
    allowed_numbers = _org_scope(select(ChangeRequest.change_number), current_user)
    return q.where(AuditLog.correlation_id.in_(allowed_numbers))


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
    q = _apply_org_scope(q, current_user)
    # Eager-load the actor so AuditLog.user_name resolves without a lazy load.
    q = q.options(selectinload(AuditLog.user))
    # Newest-first by id so a limit-truncated result drops the OLDEST entries,
    # not the newest (the frontend timeline re-sorts for display either way).
    rows = (await db.execute(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset))).scalars().all()
    from app.services.price_redaction import blank_quote_audit, redact_audit_row
    must_redact = await _price_redactor(db, current_user)
    hides_quote = await _quote_hider(db, current_user, must_redact)
    out = []
    for r in rows:
        if not await must_redact(r):
            out.append(r)
            continue
        row = redact_audit_row(r)
        if await hides_quote(r):
            row = blank_quote_audit(row)
        out.append(row)
    return out


@router.get("/verify", response_model=AuditVerifyResponse)
async def verify_audit(
    correlation_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Chain verification stays global regardless of the viewer's org (the
    hash chain is a single global sequence - see audit_service.py). When
    correlation_id is passed, the response is additionally annotated with
    per-correlation coverage (correlation_entries, correlation_ok) so the UI
    badge can report what it actually checked. Existing fields (valid,
    checked, first_broken_id) are unchanged for backward compatibility."""
    result = dict(await AuditService.verify_chain(db))
    if correlation_id is not None:
        result.update(await AuditService.verify_correlation(db, correlation_id, result["valid"]))
    return result


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
    q = _apply_org_scope(q, current_user)
    rows = (await db.execute(q.order_by(AuditLog.id))).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "timestamp", "correlation_id", "entity_type", "entity_id",
                     "action", "user_id", "old_values", "new_values",
                     "previous_hash", "entry_hash"])
    from app.services.price_redaction import blank_quote_json, redact_json
    must_redact = await _price_redactor(db, current_user)
    hides_quote = await _quote_hider(db, current_user, must_redact)
    for r in rows:
        old, new = r.old_values, r.new_values
        if await must_redact(r):
            old, new = redact_json(old, r.action), redact_json(new, r.action)
            if await hides_quote(r):
                old, new = blank_quote_json(old), blank_quote_json(new)
        writer.writerow([r.id, r.timestamp.isoformat(), r.correlation_id, r.entity_type,
                         r.entity_id, r.action, r.user_id, old, new,
                         r.previous_hash, r.entry_hash])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"})
