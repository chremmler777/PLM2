"""Service for the Change Management lifecycle: numbering, CRUD, state machine,
guards, hash-chained audit, assessments, impacted items, sign-off, ECN spawn,
release."""
import hashlib
import json
import logging
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeChangelog,
    CHANGE_TYPES, CHANGE_STATUSES, ASSESSMENT_VERDICTS, CUSTOMER_RESPONSES,
    SIGN_OFF_ROLES,
)
from app.models.part import Part, PartRevision
from app.models.workflow import Department

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS = {
    "captured":          {"in_assessment", "cancelled", "on_hold"},
    "in_assessment":     {"costing", "rejected", "cancelled", "on_hold"},
    "costing":           {"quoted", "on_hold", "cancelled"},
    "quoted":            {"approved", "rejected", "on_hold", "cancelled"},
    "approved":          {"in_implementation", "on_hold", "cancelled"},
    "in_implementation": {"in_validation", "on_hold", "cancelled"},
    "in_validation":     {"released", "in_implementation", "on_hold", "cancelled"},
    "released":          {"closed"},
    "on_hold":           {"in_assessment", "costing", "quoted", "approved",
                          "in_implementation", "in_validation", "cancelled"},
    "rejected":          set(),
    "closed":            set(),
    "cancelled":         set(),
}

TYPE_DISCIPLINES = {
    "physical_part": ["Tool Engineer", "APQP", "Quality", "Manufacturing Engineer", "Sales"],
    "tooling":       ["Tool Engineer", "Process Engineer", "Manufacturing Engineer"],
    "document_spec": ["Quality", "Project Manager"],
    "process_im":    ["Process Engineer", "Manufacturing Engineer", "Quality"],
    "packaging":     ["Packaging Engineer", "Quality", "Sales"],
}


class ChangeError(ValueError):
    """Raised for invalid change operations; mapped to HTTP 400 in the router."""


class ChangeService:

    @staticmethod
    async def generate_change_number(session: AsyncSession) -> str:
        year = datetime.utcnow().year
        prefix = f"CR-{year}-"
        result = await session.execute(
            select(func.count()).select_from(ChangeRequest).where(
                ChangeRequest.change_number.like(f"{prefix}%")
            )
        )
        seq = (result.scalar() or 0) + 1
        return f"{prefix}{seq:04d}"

    @staticmethod
    async def _last_entry_hash(session: AsyncSession, change_id: int) -> Optional[str]:
        result = await session.execute(
            select(ChangeChangelog.entry_hash)
            .where(ChangeChangelog.change_id == change_id)
            .order_by(ChangeChangelog.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def append_changelog(
        session: AsyncSession, change: ChangeRequest, action: str,
        description: str, performed_by: int, *, field_name: Optional[str] = None,
        old_value=None, new_value=None, notes: Optional[str] = None,
    ) -> ChangeChangelog:
        prev = await ChangeService._last_entry_hash(session, change.id)
        old_s = json.dumps(old_value) if old_value is not None else None
        new_s = json.dumps(new_value) if new_value is not None else None
        performed_at = datetime.utcnow()
        payload = "|".join([
            str(change.id), action, field_name or "", old_s or "", new_s or "",
            str(performed_by), performed_at.isoformat(), prev or "",
        ])
        entry_hash = hashlib.sha256(payload.encode()).hexdigest()
        entry = ChangeChangelog(
            change_id=change.id, action=action, action_description=description,
            field_name=field_name, old_value=old_s, new_value=new_s,
            performed_by=performed_by, performed_at=performed_at, notes=notes,
            previous_hash=prev, entry_hash=entry_hash,
        )
        session.add(entry)
        return entry

    @staticmethod
    async def create_change(
        session: AsyncSession, *, project_id: int, title: str, change_type: str,
        raised_by: int, reason: Optional[str] = None, description: Optional[str] = None,
        priority: str = "medium", lead_id: Optional[int] = None,
        data_classification: str = "confidential",
    ) -> ChangeRequest:
        if change_type not in CHANGE_TYPES:
            raise ChangeError(f"Invalid change_type '{change_type}'")
        number = await ChangeService.generate_change_number(session)
        change = ChangeRequest(
            change_number=number, project_id=project_id, title=title,
            change_type=change_type, reason=reason, description=description,
            priority=priority, lead_id=lead_id, raised_by=raised_by,
            data_classification=data_classification, status="captured",
        )
        session.add(change)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "created", f"Change {number} created", raised_by,
        )
        logger.info(f"Created change {number} in project {project_id}")
        return change

    @staticmethod
    async def get_change(session: AsyncSession, change_id: int) -> Optional[ChangeRequest]:
        result = await session.execute(
            select(ChangeRequest).where(ChangeRequest.id == change_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_changes(
        session: AsyncSession, *, project_id: Optional[int] = None,
        status: Optional[str] = None, change_type: Optional[str] = None,
        lead_id: Optional[int] = None,
    ) -> List[ChangeRequest]:
        q = select(ChangeRequest)
        if project_id is not None:
            q = q.where(ChangeRequest.project_id == project_id)
        if status is not None:
            q = q.where(ChangeRequest.status == status)
        if change_type is not None:
            q = q.where(ChangeRequest.change_type == change_type)
        if lead_id is not None:
            q = q.where(ChangeRequest.lead_id == lead_id)
        q = q.order_by(ChangeRequest.id.desc())
        result = await session.execute(q)
        return result.scalars().all()

    @staticmethod
    async def _guard(session: AsyncSession, change: ChangeRequest, to_status: str):
        """Return None if soft-OK, else a human reason string (overridable)."""
        if to_status == "in_assessment":
            count = len(change.impacted_items)
            if count == 0:
                return "No impacted items added yet"
            if change.lead_id is None:
                return "No lead (project manager) assigned"
        if to_status == "costing":
            pending = [a for a in change.assessments if a.verdict == "pending"]
            if not change.assessments or pending:
                return "Not all discipline assessments are submitted"
            if any(a.verdict == "not_feasible" for a in change.assessments):
                return "An assessment is 'not_feasible' — explicit decision required"
        if to_status == "quoted":
            if change.quoted_price is None:
                return "No quoted price recorded"
        if to_status == "in_validation":
            missing = [i for i in change.impacted_items if i.resulting_revision_id is None]
            if missing:
                return "Some impacted items have no resulting revision"
        return None

    @staticmethod
    async def transition(
        session: AsyncSession, change: ChangeRequest, to_status: str,
        user_id: int, *, justification: Optional[str] = None,
        cancellation_reason: Optional[str] = None,
    ) -> ChangeRequest:
        if to_status not in CHANGE_STATUSES:
            raise ChangeError(f"Unknown status '{to_status}'")
        allowed = ALLOWED_TRANSITIONS.get(change.status, set())
        if to_status not in allowed:
            raise ChangeError(f"Cannot move from '{change.status}' to '{to_status}'")

        # HARD gate: quoted -> approved cannot be forced
        if to_status == "approved":
            if change.customer_response != "accepted":
                raise ChangeError("Customer has not accepted the offer")
            if change.pm_signed_by is None or change.quality_signed_by is None:
                raise ChangeError("Both PM and Quality sign-off are required")

        if to_status == "cancelled":
            if not cancellation_reason:
                raise ChangeError("cancellation_reason is required to cancel")
            change.cancellation_reason = cancellation_reason
            change.cancelled_at = datetime.utcnow()

        forced = False
        reason = await ChangeService._guard(session, change, to_status)
        if reason is not None:
            if not justification:
                raise ChangeError(f"{reason}. Provide a justification to override.")
            forced = True

        # Side effects on entry
        if to_status == "in_implementation":
            await ChangeService.spawn_ecn_revisions(session, change, user_id)
        if to_status == "released":
            await ChangeService.release(session, change, user_id)
        if to_status == "closed":
            change.closed_at = datetime.utcnow()

        old = change.status
        change.status = to_status
        await session.flush()
        action = "forced_transition" if forced else "status_changed"
        desc = f"{old} -> {to_status}" + (f" (forced: {justification})" if forced else "")
        await ChangeService.append_changelog(
            session, change, action, desc, user_id,
            field_name="status", old_value=old, new_value=to_status,
            notes=justification if forced else None,
        )
        return change

    @staticmethod
    async def spawn_ecn_revisions(session: AsyncSession, change: ChangeRequest, user_id: int):
        return  # implemented in Task 11

    @staticmethod
    async def release(session: AsyncSession, change: ChangeRequest, user_id: int):
        change.released_at = datetime.utcnow()
        change.released_by = user_id
        # full activate/supersede logic added in Task 12
