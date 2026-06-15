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
