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

from app.models.change_cost import ChangeGate
from app.models.change_cost import GATE_KEYS, GATE_DECISIONS, GATE_TARGET_STATUS
from app.models.change import (
    ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeChangelog,
    ChangeAttachment,
    CHANGE_TYPES, CHANGE_STATUSES, ASSESSMENT_VERDICTS, CUSTOMER_RESPONSES,
    SIGN_OFF_ROLES,
)
from app.models.part import Part, PartRevision, PartRelation
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
    async def decide_gate(
        session: AsyncSession, change: ChangeRequest, gate_key: str,
        decision: str, user_id: int, *, remark: Optional[str] = None,
    ) -> ChangeGate:
        if gate_key not in GATE_KEYS:
            raise ChangeError(f"Unknown gate '{gate_key}'")
        if decision not in GATE_DECISIONS:
            raise ChangeError(f"Invalid gate decision '{decision}'")
        row = (await session.execute(
            select(ChangeGate).where(
                (ChangeGate.change_id == change.id) & (ChangeGate.gate_key == gate_key))
        )).scalar_one_or_none()
        if row is None:
            row = ChangeGate(change_id=change.id, gate_key=gate_key)
            session.add(row)
        row.decision = decision
        row.decided_by = user_id
        row.decided_at = datetime.utcnow()
        row.remark = remark
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "gate_decided", f"Gate {gate_key}: {decision}", user_id,
            field_name=f"gate_{gate_key}", new_value=decision, notes=remark,
        )
        return row

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
            from app.services.change_routing_service import ChangeRoutingService
            if not await ChangeRoutingService.blocking_complete(session, change):
                return "Not all responsible/accountable assessments are submitted"
            submitted = [a for a in change.assessments if a.verdict != "pending"]
            if any(a.verdict == "not_feasible" for a in submitted):
                return "An assessment is 'not_feasible' — explicit decision required"
            routing = change.routing
            if routing is not None and routing.deviation_status == "pending_approval":
                return "Routing deviation is pending approval"
        if to_status == "quoted":
            if change.quoted_price is None:
                return "No quoted price recorded"
        if to_status == "in_validation":
            missing = [i for i in change.impacted_items if i.resulting_revision_id is None]
            if missing:
                return "Some impacted items have no resulting revision"
        # Gate wiring (additive): a gate constrains its target transition only when a
        # row exists. Changes with no gate rows behave exactly as before.
        for gate in change.gates:
            if GATE_TARGET_STATUS.get(gate.gate_key) == to_status and gate.decision != "yes":
                return f"Gate '{gate.gate_key}' is not approved ('{gate.decision}')"
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
        if to_status == "in_assessment":
            await ChangeService.ensure_assessments(session, change, user_id)
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
        for item in change.impacted_items:
            if item.resulting_revision_id is not None:
                continue
            # count existing ECN revisions on this part for a simple unique name
            result = await session.execute(
                select(func.count()).select_from(PartRevision).where(
                    (PartRevision.part_id == item.part_id) & (PartRevision.phase == "ecn")
                )
            )
            n = (result.scalar() or 0) + 1
            rev = PartRevision(
                part_id=item.part_id,
                revision_name=f"ECR{n}.1",
                phase="ecn",
                status="draft",
                change_reason=f"{change.change_number}: {change.title}",
                created_by=user_id,
            )
            session.add(rev)
            await session.flush()
            item.resulting_revision_id = rev.id
            await ChangeService.append_changelog(
                session, change, "revision_spawned",
                f"Spawned ECN revision {rev.revision_name} on part {item.part_id}",
                user_id, new_value={"revision_id": rev.id, "part_id": item.part_id},
            )

    @staticmethod
    async def release(session: AsyncSession, change: ChangeRequest, user_id: int):
        change.released_at = datetime.utcnow()
        change.released_by = user_id
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
                continue
            rev = await session.get(PartRevision, item.resulting_revision_id)
            part = await session.get(Part, item.part_id)
            if rev is None or part is None:
                continue
            prior = part.active_revision_id
            if prior is not None and prior != rev.id:
                rev.supersedes_revision_id = prior
            rev.status = "approved"
            rev.approved_at = datetime.utcnow()
            rev.approved_by = user_id
            part.active_revision_id = rev.id
            # stamp engineering level
            item.eng_level_after = rev.revision_name
            await session.flush()
            await ChangeService.append_changelog(
                session, change, "released",
                f"Released revision {rev.revision_name} as active on part {part.id}",
                user_id, new_value={"part_id": part.id, "revision_id": rev.id},
            )
        from app.services.change_routing_service import ChangeRoutingService
        await ChangeRoutingService.promote_to_standard(session, change, user_id)

    @staticmethod
    async def add_impacted_item(
        session: AsyncSession, change: ChangeRequest, part_id: int,
        user_id: int, *, impact_note: Optional[str] = None,
        eng_level_before: Optional[str] = None,
    ) -> ChangeImpactedItem:
        part = await session.get(Part, part_id)
        if not part or part.project_id != change.project_id:
            raise ChangeError("Part not found in this project")
        if any(i.part_id == part_id for i in change.impacted_items):
            raise ChangeError("Item already impacted")
        item = ChangeImpactedItem(
            change_id=change.id, part_id=part_id, impact_note=impact_note,
            eng_level_before=eng_level_before, created_by=user_id,
        )
        session.add(item)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "impacted_item_added",
            f"Added impacted item {part.part_number}", user_id,
            new_value={"part_id": part_id},
        )
        return item

    @staticmethod
    async def remove_impacted_item(
        session: AsyncSession, change: ChangeRequest, item_id: int, user_id: int,
    ) -> None:
        item = await session.get(ChangeImpactedItem, item_id)
        if not item or item.change_id != change.id:
            raise ChangeError("Impacted item not found")
        await session.delete(item)
        await ChangeService.append_changelog(
            session, change, "impacted_item_removed",
            f"Removed impacted item {item.part_id}", user_id,
            old_value={"part_id": item.part_id},
        )

    @staticmethod
    async def seed_impacted_from_relations(
        session: AsyncSession, change: ChangeRequest, user_id: int,
    ) -> int:
        """For every currently-impacted part, pull in related parts (produces/checks/
        assembles) that are not yet impacted. Returns count added."""
        existing = {i.part_id for i in change.impacted_items}
        added = 0
        for part_id in list(existing):
            result = await session.execute(
                select(PartRelation).where(
                    (PartRelation.from_part_id == part_id) | (PartRelation.to_part_id == part_id)
                )
            )
            for rel in result.scalars().all():
                other = rel.to_part_id if rel.from_part_id == part_id else rel.from_part_id
                if other not in existing:
                    existing.add(other)
                    await ChangeService.add_impacted_item(
                        session, change, other, user_id,
                        impact_note=f"Linked via '{rel.relation_type}'",
                    )
                    added += 1
        return added

    @staticmethod
    async def ensure_assessments(
        session: AsyncSession, change: ChangeRequest, user_id: int,
    ) -> None:
        from app.services.change_routing_service import ChangeRoutingService
        await ChangeRoutingService.build_routing(session, change, user_id)

    @staticmethod
    async def submit_assessment(
        session: AsyncSession, change: ChangeRequest, department_id: int,
        verdict: str, user_id: int, *, cost_impact=None, lead_time_impact_days=None,
        conditions=None, notes=None, responsible_id=None,
    ) -> ChangeAssessment:
        if verdict not in ASSESSMENT_VERDICTS:
            raise ChangeError(f"Invalid verdict '{verdict}'")
        result = await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.department_id == department_id)
            )
        )
        a = result.scalar_one_or_none()
        if a is None:
            a = ChangeAssessment(change_id=change.id, department_id=department_id)
            session.add(a)
        a.verdict = verdict
        a.cost_impact = cost_impact
        a.lead_time_impact_days = lead_time_impact_days
        a.conditions = conditions
        a.notes = notes
        a.responsible_id = responsible_id
        a.submitted_at = datetime.utcnow()
        a.submitted_by = user_id
        a.status = "submitted"
        await session.flush()
        from app.services.change_routing_service import ChangeRoutingService
        await ChangeRoutingService.maybe_advance(session, change, user_id)
        await ChangeService.append_changelog(
            session, change, "assessment_submitted",
            f"Assessment for dept {department_id}: {verdict}", user_id,
            field_name="verdict", new_value=verdict,
        )
        return a

    @staticmethod
    async def update_change(
        session: AsyncSession, change: ChangeRequest, user_id: int, **fields,
    ) -> ChangeRequest:
        allowed = {
            "title", "reason", "description", "priority", "change_type", "lead_id",
            "estimated_cost", "quoted_price", "pnl_note", "timing_milestone_id",
        }
        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(change, k, v)
        change.updated_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "metadata_updated", "Change metadata updated", user_id,
        )
        return change

    @staticmethod
    async def record_customer_response(
        session: AsyncSession, change: ChangeRequest, response: str, user_id: int,
    ) -> ChangeRequest:
        if response not in CUSTOMER_RESPONSES:
            raise ChangeError(f"Invalid customer response '{response}'")
        change.customer_response = response
        change.customer_response_at = datetime.utcnow()
        change.customer_response_by = user_id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "customer_response_recorded",
            f"Customer response: {response}", user_id,
            field_name="customer_response", new_value=response,
        )
        return change

    @staticmethod
    async def sign_off(
        session: AsyncSession, change: ChangeRequest, role: str, user_id: int,
    ) -> ChangeRequest:
        if role not in SIGN_OFF_ROLES:
            raise ChangeError(f"Invalid sign-off role '{role}'")
        other = change.quality_signed_by if role == "pm" else change.pm_signed_by
        if other is not None and other == user_id:
            raise ChangeError("PM and Quality sign-off must be different users")
        now = datetime.utcnow()
        if role == "pm":
            change.pm_signed_by, change.pm_signed_at = user_id, now
        else:
            change.quality_signed_by, change.quality_signed_at = user_id, now
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "signed_off", f"{role} sign-off", user_id,
            field_name=f"{role}_signed_by", new_value=user_id,
        )
        return change

    @staticmethod
    async def add_attachment(
        session: AsyncSession, change: ChangeRequest, *, filename: str,
        stored_path: str, content_type: str, size_bytes: int, sha256: str, user_id: int,
    ) -> ChangeAttachment:
        att = ChangeAttachment(
            change_id=change.id, filename=filename, stored_path=stored_path,
            content_type=content_type, size_bytes=size_bytes, sha256=sha256,
            uploaded_by=user_id,
        )
        session.add(att)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "attachment_added", f"Attached {filename}", user_id,
            new_value={"filename": filename},
        )
        return att
