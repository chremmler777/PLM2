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
                 user_id: Optional[int], ts: datetime, prev: Optional[str],
                 correlation_id: Optional[str], log_level: str) -> str:
        """Full row content except id is inside the hash envelope, so no field
        (including correlation_id/log_level) can be altered without breaking
        the chain."""
        return "|".join([
            entity_type, str(entity_id), action, old_s or "", new_s or "",
            str(user_id or ""), ts.isoformat(), prev or "",
            correlation_id or "", log_level,
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
                entity_type, entity_id, action, old_s, new_s, user_id, ts, prev,
                correlation_id, log_level
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
                r.user_id, r.timestamp, prev, r.correlation_id, r.log_level
            ).encode()).hexdigest()
            if r.previous_hash != prev or r.entry_hash != expected:
                return {"valid": False, "checked": len(rows), "first_broken_id": r.id}
            prev = r.entry_hash
        return {"valid": True, "checked": len(rows), "first_broken_id": None}

    @staticmethod
    async def verify_correlation(session: AsyncSession, correlation_id: str, chain_valid: bool) -> dict:
        """Per-correlation coverage report for GET /audit/verify?correlation_id=.

        The global chain check (verify_chain) already walks every row in id
        order, so it is the authoritative tamper check; this method adds a
        second, independent self-consistency pass over just this
        correlation's rows (each row's entry_hash re-derived from its own
        stored fields + its own stored previous_hash, rather than from the
        chain-walk's recomputed previous link). correlation_ok requires BOTH:
        the global chain being intact, and every one of this correlation's own
        rows re-hashing correctly in place. A correlation with zero entries is
        reported as not ok (nothing was verified)."""
        rows = (await session.execute(
            select(AuditLog).where(AuditLog.correlation_id == correlation_id).order_by(AuditLog.id)
        )).scalars().all()
        entries_ok = True
        for r in rows:
            expected = hashlib.sha256(AuditService._payload(
                r.entity_type, r.entity_id, r.action, r.old_values, r.new_values,
                r.user_id, r.timestamp, r.previous_hash, r.correlation_id, r.log_level
            ).encode()).hexdigest()
            if expected != r.entry_hash:
                entries_ok = False
                break
        return {
            "correlation_entries": len(rows),
            "correlation_ok": chain_valid and entries_ok and len(rows) > 0,
        }
