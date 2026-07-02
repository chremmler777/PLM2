"""Unified tamper-evident audit trail: globally hash-chained audit_logs rows
with a correlation id (the change number) for cross-entity timelines.

Chain design: each entry's payload hash covers its content plus the previous
entry's hash (global order by id). SQLite serializes writers, so the read-last/
write-next pattern is race-free here; revisit if moving to Postgres with
concurrent writers (advisory lock or per-correlation chains)."""
import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog


class AuditService:

    @staticmethod
    def _payload(entity_type: str, entity_id: int, action: str,
                 old_s: Optional[str], new_s: Optional[str],
                 user_id: Optional[int], ts: datetime, prev: Optional[str]) -> str:
        return "|".join([
            entity_type, str(entity_id), action, old_s or "", new_s or "",
            str(user_id or ""), ts.isoformat(), prev or "",
        ])

    @staticmethod
    async def record(
        session: AsyncSession, *, entity_type: str, entity_id: int, action: str,
        user_id: Optional[int] = None, old_values=None, new_values=None,
        correlation_id: Optional[str] = None, log_level: str = "info",
    ) -> AuditLog:
        prev = (await session.execute(
            select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
        )).scalar_one_or_none()
        old_s = json.dumps(old_values) if old_values is not None else None
        new_s = json.dumps(new_values) if new_values is not None else None
        ts = datetime.utcnow()
        entry = AuditLog(
            entity_type=entity_type, entity_id=entity_id, action=action,
            user_id=user_id, timestamp=ts, old_values=old_s, new_values=new_s,
            correlation_id=correlation_id, log_level=log_level,
            previous_hash=prev,
            entry_hash=hashlib.sha256(AuditService._payload(
                entity_type, entity_id, action, old_s, new_s, user_id, ts, prev
            ).encode()).hexdigest(),
        )
        session.add(entry)
        await session.flush()
        return entry

    @staticmethod
    async def verify_chain(session: AsyncSession) -> dict:
        rows = (await session.execute(
            select(AuditLog).order_by(AuditLog.id))).scalars().all()
        prev = None
        for r in rows:
            expected = hashlib.sha256(AuditService._payload(
                r.entity_type, r.entity_id, r.action, r.old_values, r.new_values,
                r.user_id, r.timestamp, prev).encode()).hexdigest()
            if r.previous_hash != prev or r.entry_hash != expected:
                return {"valid": False, "checked": len(rows), "first_broken_id": r.id}
            prev = r.entry_hash
        return {"valid": True, "checked": len(rows), "first_broken_id": None}
