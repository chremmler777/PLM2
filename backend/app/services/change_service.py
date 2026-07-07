"""Service for the Change Management lifecycle: numbering, CRUD, state machine,
guards, hash-chained audit, assessments, impacted items, sign-off, ECN spawn,
release."""
import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change_cost import ChangeGate, GATE_KEYS, GATE_DECISIONS, GATE_TARGET_STATUS
from app.models.change import (
    ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeChangelog,
    ChangeAttachment, ChangeTransitionDeviation, ChangeMeeting,
    CHANGE_TYPES, CHANGE_STATUSES, ASSESSMENT_VERDICTS, CUSTOMER_RESPONSES,
    SIGN_OFF_ROLES, IMPLEMENTATION_MODES, TERMINAL_STATUSES, BLOCKING_LETTERS,
)
from app.models.entities import User, Project, Plant
from app.models.part import Part, PartRevision, PartRelation, PartBOMItem
from app.models.workflow import Department

logger = logging.getLogger(__name__)


def _org_scope(stmt, viewer: Optional[User]):
    """Restrict a ChangeRequest select to the viewer's organization.

    Scoping path: ChangeRequest.project_id -> Project.plant_id ->
    Plant.organization_id. Changes with project_id NULL stay visible to
    everyone (explicit decision - no silent data loss). viewer=None means
    "internal/service caller" and returns the statement unchanged. Admins
    (viewer.role == "admin") also see every organization - mirrors the
    intent already documented on the dead get_org_filter helper in
    app/dependencies/auth.py ("Admins see all organizations").
    """
    if viewer is None or viewer.role == "admin":
        return stmt
    org_projects = select(Project.id).join(Plant, Project.plant_id == Plant.id).where(
        Plant.organization_id == viewer.organization_id)
    return stmt.where(
        ChangeRequest.project_id.is_(None) | ChangeRequest.project_id.in_(org_projects))

ALLOWED_TRANSITIONS = {
    "captured":          {"scoping", "cancelled", "on_hold"},
    "scoping":           {"in_assessment", "rejected", "cancelled", "on_hold"},
    "in_assessment":     {"costing", "rejected", "cancelled", "on_hold"},
    "costing":           {"quoted", "approved", "on_hold", "cancelled"},
    "quoted":            {"approved", "rejected", "on_hold", "cancelled"},
    "approved":          {"in_implementation", "on_hold", "cancelled"},
    "in_implementation": {"in_validation", "on_hold", "cancelled"},
    "in_validation":     {"released", "in_implementation", "on_hold", "cancelled"},
    "released":          {"closed"},
    "on_hold":           {"scoping", "in_assessment", "costing", "quoted", "approved",
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


IMPACT_LOCKED_STATUSES = ("in_implementation", "in_validation", "released",
                          "closed", "rejected", "cancelled")


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
        from app.services.audit_service import AuditService  # local import avoids cycle
        await AuditService.record(
            session, entity_type="change", entity_id=change.id, action=action,
            user_id=performed_by, old_values=old_value, new_values=new_value,
            correlation_id=change.change_number,
        )
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
    async def propose_transition_deviation(
        session: AsyncSession, change: ChangeRequest, to_status: str,
        reason: str, user_id: int,
    ) -> ChangeTransitionDeviation:
        if to_status not in CHANGE_STATUSES:
            raise ChangeError(f"Unknown status '{to_status}'")
        if not reason or not reason.strip():
            raise ChangeError("A reason is required to propose a deviation")
        if any(d.to_status == to_status and d.status == "pending"
               for d in change.transition_deviations):
            raise ChangeError("A deviation for this transition is already pending")
        dev = ChangeTransitionDeviation(
            change_id=change.id, to_status=to_status, reason=reason.strip(),
            proposed_by=user_id,
        )
        session.add(dev)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "deviation_proposed",
            f"Transition deviation to '{to_status}' proposed", user_id,
            field_name="deviation",
            new_value={"deviation_id": dev.id, "to_status": to_status},
            notes=reason.strip(),
        )
        if change.lead_id is not None and change.lead_id != user_id:
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [change.lead_id], kind="deviation_pending",
                subject_key=f"dev:{dev.id}",
                title=f"Deviation pending: {change.change_number}",
                body=f"A transition deviation to '{to_status}' needs your review.",
                link=f"/changes/{change.id}",
            )
        return dev

    @staticmethod
    async def decide_transition_deviation(
        session: AsyncSession, change: ChangeRequest, deviation_id: int,
        decision: str, actor: User, *, note: Optional[str] = None,
    ) -> ChangeTransitionDeviation:
        if decision not in ("approved", "rejected"):
            raise ChangeError(f"Invalid deviation decision '{decision}'")
        dev = next((d for d in change.transition_deviations if d.id == deviation_id), None)
        if dev is None:
            raise ChangeError("Deviation not found")
        if dev.status != "pending":
            raise ChangeError(f"Deviation is '{dev.status}', not pending")
        if dev.proposed_by == actor.id:
            raise ChangeError("Cannot decide your own deviation (4-eyes rule)")
        if actor.role not in ("admin", "engineer"):
            raise ChangeError("Deviation decisions require an engineer or admin role")
        if (actor.role != "admin" and actor.id != change.lead_id
                and dev.proposed_by != change.lead_id):
            raise ChangeError("Only the change lead or an admin may decide this deviation")
        dev.status = decision
        dev.decided_by = actor.id
        dev.decided_at = datetime.utcnow()
        dev.decision_note = note
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "deviation_decided",
            f"Deviation #{dev.id} ({dev.to_status}): {decision}", actor.id,
            field_name="deviation",
            new_value={"deviation_id": dev.id, "decision": decision},
            notes=note,
        )
        return dev

    @staticmethod
    async def create_change(
        session: AsyncSession, *, project_id: int, title: str, change_type: str,
        raised_by: int, reason: Optional[str] = None, description: Optional[str] = None,
        priority: str = "medium", lead_id: Optional[int] = None,
        data_classification: str = "confidential",
        customer_relevant: Optional[bool] = None,
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
        if customer_relevant is not None:
            change.customer_relevant = customer_relevant
        session.add(change)
        await session.flush()
        # Only the release gate is seeded up front. Feasibility is answered by
        # the scoping meeting decision; budget by the costing path split
        # (customer quote acceptance / internal cost approval).
        session.add(ChangeGate(change_id=change.id, gate_key="release"))
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "created", f"Change {number} created", raised_by,
        )
        logger.info(f"Created change {number} in project {project_id}")
        return change

    @staticmethod
    async def get_change(
        session: AsyncSession, change_id: int, viewer: Optional[User] = None,
    ) -> Optional[ChangeRequest]:
        q = _org_scope(select(ChangeRequest).where(ChangeRequest.id == change_id), viewer)
        result = await session.execute(q)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_changes(
        session: AsyncSession, *, viewer: Optional[User] = None,
        project_id: Optional[int] = None,
        status: Optional[str] = None, change_type: Optional[str] = None,
        lead_id: Optional[int] = None,
    ) -> List[ChangeRequest]:
        q = select(ChangeRequest)
        q = _org_scope(q, viewer)
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
    async def deadline_state(session: AsyncSession, change: ChangeRequest) -> str | None:
        """Computed on_track/at_risk/overdue state for a Sales-set required-by
        date. None when no deadline is set or the change is already terminal
        (done changes don't need a deadline banner)."""
        if change.required_by_date is None or change.status in TERMINAL_STATUSES:
            return None
        from sqlalchemy.orm import selectinload
        from app.models.workflow import WfInstance, WfTemplate
        from app.services.workflow_service import DEFAULT_TASK_DUE_DAYS

        now = datetime.utcnow()
        if change.required_by_date < now:
            return "overdue"
        insts = (await session.execute(
            select(WfInstance).where(WfInstance.status == "active").where(
                (WfInstance.change_id == change.id)
                | WfInstance.part_revision_id.in_(
                    select(PartRevision.id).where(
                        PartRevision.originating_change_id == change.id))
            ).options(selectinload(WfInstance.template).selectinload(WfTemplate.stages))
        )).scalars().all()
        needed = 0
        for inst in insts:
            max_stage = max((s.stage_order for s in inst.template.stages), default=inst.current_stage_order)
            needed = max(needed, (max_stage - inst.current_stage_order + 1) * DEFAULT_TASK_DUE_DAYS)
        days_left = (change.required_by_date - now).days
        return "at_risk" if needed > days_left else "on_track"

    @staticmethod
    async def lead_escalations(session: AsyncSession, user_id: int) -> list[dict]:
        from app.models.workflow import Department, WfInstance, WfInstanceTask, WfStep

        now = datetime.utcnow()
        changes = (await session.execute(
            select(ChangeRequest).where(
                ChangeRequest.lead_id == user_id,
                ChangeRequest.status.not_in(TERMINAL_STATUSES)))).scalars().all()
        if not changes:
            return []
        by_id = {c.id: c for c in changes}
        out: list[dict] = []

        assessment_rows = (await session.execute(
            select(ChangeAssessment, Department.name)
            .join(Department, Department.id == ChangeAssessment.department_id)
            .where(ChangeAssessment.change_id.in_(by_id.keys()),
                   ChangeAssessment.status == "active",
                   ChangeAssessment.wf_instance_task_id.is_(None),
                   ChangeAssessment.due_date.is_not(None),
                   ChangeAssessment.due_date < now))).all()
        for a, dept_name in assessment_rows:
            c = by_id[a.change_id]
            out.append({
                "kind": "assessment", "change_id": c.id,
                "change_number": c.change_number, "change_title": c.title,
                "label": dept_name, "owner_id": a.owner_id,
                "owner_name": a.owner_name,
                "due_date": a.due_date.isoformat(),
                "days_overdue": (now - a.due_date).days,
            })

        task_rows = (await session.execute(
            select(WfInstanceTask, WfStep.step_name, PartRevision.originating_change_id)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .join(PartRevision, PartRevision.id == WfInstance.part_revision_id)
            .join(WfStep, WfStep.id == WfInstanceTask.step_id)
            .where(PartRevision.originating_change_id.in_(by_id.keys()),
                   WfInstance.status == "active",
                   WfInstanceTask.status == "active",
                   WfInstanceTask.is_actionable == True,  # noqa: E712
                   WfInstanceTask.due_date.is_not(None),
                   WfInstanceTask.due_date < now))).all()
        seen_task_ids: set[int] = set()
        for t, step_name, change_id in task_rows:
            seen_task_ids.add(t.id)
            c = by_id[change_id]
            out.append({
                "kind": "wf_task", "change_id": c.id,
                "change_number": c.change_number, "change_title": c.title,
                "label": step_name, "owner_id": t.owner_id,
                "owner_name": t.owner_name,
                "due_date": t.due_date.isoformat(),
                "days_overdue": (now - t.due_date).days,
            })

        # Change-scoped instances attach to a change directly (no part
        # revision, step_id may be null): roll their overdue tasks up too.
        change_task_rows = (await session.execute(
            select(WfInstanceTask, Department.name, WfInstance.change_id)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .join(Department, Department.id == WfInstanceTask.department_id)
            .where(WfInstance.change_id.in_(by_id.keys()),
                   WfInstance.status == "active",
                   WfInstanceTask.status == "active",
                   WfInstanceTask.is_actionable == True,  # noqa: E712
                   WfInstanceTask.due_date.is_not(None),
                   WfInstanceTask.due_date < now))).all()
        for t, dept_name, change_id in change_task_rows:
            if t.id in seen_task_ids:
                continue
            seen_task_ids.add(t.id)
            c = by_id[change_id]
            out.append({
                "kind": "wf_task", "change_id": c.id,
                "change_number": c.change_number, "change_title": c.title,
                "label": dept_name, "owner_id": t.owner_id,
                "owner_name": t.owner_name,
                "due_date": t.due_date.isoformat(),
                "days_overdue": (now - t.due_date).days,
            })

        # Sales-set deadlines at risk or already overdue.
        for c in changes:
            if c.required_by_date is None:
                continue
            state = await ChangeService.deadline_state(session, c)
            if state not in ("at_risk", "overdue"):
                continue
            days_overdue = (now - c.required_by_date).days if state == "overdue" \
                else -(c.required_by_date - now).days
            out.append({
                "kind": "deadline", "change_id": c.id,
                "change_number": c.change_number, "change_title": c.title,
                # label mirrors the other escalation kinds so existing
                # renderers (EscalationsCard) show something meaningful.
                "label": f"Required by {c.required_by_date.date().isoformat()}",
                "required_by_date": c.required_by_date.isoformat(),
                "state": state,
                # negative for at_risk (days until deadline) so the shared
                # days_overdue sort ranks true overdues above at-risk rows.
                "days_overdue": days_overdue,
            })

        out.sort(key=lambda r: r["days_overdue"], reverse=True)
        return out

    @staticmethod
    async def implementation_progress(session: AsyncSession,
                                      change: ChangeRequest) -> dict:
        from app.models.part import RevisionFile
        from app.models.workflow import WfInstance, WfStage

        items = []
        for item in change.impacted_items:
            part = await session.get(Part, item.part_id)
            entry = {
                "item_id": item.id,
                "part_id": item.part_id,
                "part_number": part.part_number if part else None,
                "part_name": part.name if part else None,
                "item_category": part.item_category if part else None,
                "is_lead": item.is_lead,
                "revision_id": item.resulting_revision_id,
                "revision_name": None,
                "instance_id": None,
                "instance_status": None,
                "current_stage_order": None,
                "total_stages": None,
                "has_cad_file": False,
                "no_geometry_change": False,
                "ready": False,
            }
            if item.resulting_revision_id is not None:
                rev = await session.get(PartRevision, item.resulting_revision_id)
                if rev is not None:
                    entry["revision_name"] = rev.revision_name
                    entry["no_geometry_change"] = bool(rev.no_geometry_change)
                n_files = (await session.execute(
                    select(func.count()).select_from(RevisionFile).where(
                        RevisionFile.revision_id == item.resulting_revision_id,
                        RevisionFile.file_type == "cad",
                        RevisionFile.is_deleted == False,  # noqa: E712
                    ))).scalar()
                entry["has_cad_file"] = bool(n_files)
                inst = (await session.execute(
                    select(WfInstance)
                    .where(WfInstance.part_revision_id == item.resulting_revision_id)
                    .order_by(WfInstance.id.desc()).limit(1)
                )).scalar_one_or_none()
                if inst is not None:
                    entry["instance_id"] = inst.id
                    entry["instance_status"] = inst.status
                    entry["current_stage_order"] = inst.current_stage_order
                    entry["total_stages"] = (await session.execute(
                        select(func.count()).select_from(WfStage).where(
                            WfStage.template_id == inst.template_id))).scalar()
                    entry["ready"] = inst.status == "completed"
            items.append(entry)
        return {
            "ready_to_go": bool(items) and all(e["ready"] for e in items),
            "items": items,
        }

    @staticmethod
    async def _guard(session: AsyncSession, change: ChangeRequest, to_status: str):
        """Return None if soft-OK, else a human reason string (overridable)."""
        if to_status == "in_assessment":
            count = len(change.impacted_items)
            if count == 0:
                return "No impacted items added yet"
            if change.lead_id is None:
                return "No lead (project manager) assigned"
            # A change that already has routing has fanned out once — the proceed
            # meeting was consumed then. Resuming from on_hold back into
            # in_assessment must not re-demand a fresh meeting (build_routing is
            # idempotent and won't re-scope). Only require the meeting on the
            # first entry, when no routing exists yet.
            from app.models.change import ChangeRouting
            existing_routing = (await session.execute(
                select(ChangeRouting.id).where(
                    ChangeRouting.change_id == change.id).limit(1)
            )).scalar_one_or_none()
            if existing_routing is None:
                proceed = (await session.execute(
                    select(ChangeMeeting.id).where(
                        ChangeMeeting.change_id == change.id,
                        ChangeMeeting.decision == "proceed").limit(1)
                )).scalar_one_or_none()
                if proceed is None:
                    return "No scoping meeting with decision 'proceed' recorded"
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
        if to_status == "in_implementation":
            if change.impact_confirmed_at is None:
                return "impact_not_confirmed"
            from app.models.workflow import CheckWorkflowStandard
            part_ids = [i.part_id for i in change.impacted_items]
            if part_ids:
                cats = {c for (c,) in await session.execute(
                    select(Part.item_category).where(Part.id.in_(part_ids)))}
                mapped = {c for (c,) in await session.execute(
                    select(CheckWorkflowStandard.item_category).where(
                        CheckWorkflowStandard.item_category.in_(cats)))}
                missing = sorted(cats - mapped)
                if missing:
                    return ("no check-workflow template mapped for item "
                            f"category: {', '.join(missing)}")
        if to_status == "released":
            progress = await ChangeService.implementation_progress(session, change)
            if not progress["ready_to_go"]:
                pending = sum(1 for e in progress["items"] if not e["ready"])
                return (f"not ready to go: {pending} of {len(progress['items'])} "
                        "impacted revisions have not completed their check workflow")
        # Gate wiring (additive): a gate constrains its target transition only when a
        # row exists. Changes with no gate rows behave exactly as before.
        for gate in change.gates:
            if GATE_TARGET_STATUS.get(gate.gate_key) == to_status and gate.decision != "yes":
                return f"Gate '{gate.gate_key}' is not approved ('{gate.decision}')"
        return None

    @staticmethod
    async def transition(
        session: AsyncSession, change: ChangeRequest, to_status: str,
        user_id: int, *, cancellation_reason: Optional[str] = None,
    ) -> ChangeRequest:
        if to_status not in CHANGE_STATUSES:
            raise ChangeError(f"Unknown status '{to_status}'")
        allowed = ALLOWED_TRANSITIONS.get(change.status, set())
        if to_status not in allowed:
            raise ChangeError(f"Cannot move from '{change.status}' to '{to_status}'")

        # HARD gates: the approval decision cannot be forced.
        if to_status == "approved":
            if change.customer_relevant:
                if change.customer_response != "accepted":
                    raise ChangeError("Customer has not accepted the offer")
                if change.pm_signed_by is None or change.quality_signed_by is None:
                    raise ChangeError("Both PM and Quality sign-off are required")
                if change.status == "costing":
                    raise ChangeError(
                        "Customer-relevant changes must go through the quote")
            else:
                if change.internal_approved_at is None:
                    raise ChangeError(
                        "Internal cost approval is required before approval")
        if to_status == "quoted" and not change.customer_relevant:
            raise ChangeError(
                "Internal changes skip the quote — record internal cost approval instead")

        if to_status == "cancelled":
            if not cancellation_reason:
                raise ChangeError("cancellation_reason is required to cancel")
            change.cancellation_reason = cancellation_reason
            change.cancelled_at = datetime.utcnow()

        deviation = None
        reason = await ChangeService._guard(session, change, to_status)
        if reason is not None:
            deviation = next(
                (d for d in change.transition_deviations
                 if d.to_status == to_status and d.status == "approved"), None)
            if deviation is None:
                raise ChangeError(
                    f"{reason}. An approved deviation is required to proceed.")
            deviation.status = "consumed"

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
        action = "deviated_transition" if deviation else "status_changed"
        desc = f"{old} -> {to_status}" + (
            f" (deviation #{deviation.id}: {deviation.reason})" if deviation else "")
        await ChangeService.append_changelog(
            session, change, action, desc, user_id,
            field_name="status", old_value=old, new_value=to_status,
            notes=deviation.reason if deviation else None,
        )
        return change

    @staticmethod
    async def spawn_ecn_revisions(session: AsyncSession, change: ChangeRequest, user_id: int):
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
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
                    originating_change_id=change.id,
                )
                session.add(rev)
                await session.flush()
                item.resulting_revision_id = rev.id
                await ChangeService.append_changelog(
                    session, change, "revision_spawned",
                    f"Spawned ECN revision {rev.revision_name} on part {item.part_id}",
                    user_id, new_value={"revision_id": rev.id, "part_id": item.part_id},
                )
            await ChangeService._ensure_check_workflow(session, change, item, user_id)

    @staticmethod
    async def _ensure_check_workflow(session: AsyncSession, change: ChangeRequest,
                                     item: "ChangeImpactedItem", user_id: int) -> None:
        """Start the mapped check-WF instance for an impacted item's ECN
        revision. No-op if one already runs/ran, or (deviation-bypassed
        kickoff) no mapping exists — the change then stays not-ready-to-go."""
        from app.models.workflow import CheckWorkflowStandard, WfInstance
        from app.services.workflow_service import WorkflowService

        existing = (await session.execute(
            select(WfInstance).where(
                WfInstance.part_revision_id == item.resulting_revision_id,
                WfInstance.status.in_(("active", "completed")))
        )).scalars().first()
        if existing is not None:
            return
        part = await session.get(Part, item.part_id)
        standard = (await session.execute(
            select(CheckWorkflowStandard).where(
                CheckWorkflowStandard.item_category == part.item_category)
        )).scalar_one_or_none()
        if standard is None:
            return
        instance = await WorkflowService.start_workflow(
            session, item.resulting_revision_id, standard.template_id, user_id)
        await ChangeService.append_changelog(
            session, change, "check_wf_started",
            f"Check workflow started for revision {item.resulting_revision_id} "
            f"(part {item.part_id})",
            user_id, new_value={"instance_id": instance.id,
                                "revision_id": item.resulting_revision_id},
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
    async def get_impact_tree(session: AsyncSession, change: ChangeRequest) -> dict:
        parts = (await session.execute(
            select(Part).where(Part.project_id == change.project_id)
        )).scalars().all()
        impacted = {i.part_id: i for i in change.impacted_items}
        ids = {p.id for p in parts}
        children_map: dict = defaultdict(list)
        roots = []
        for p in parts:
            if p.parent_part_id in ids and p.parent_part_id != p.id:
                children_map[p.parent_part_id].append(p)
            else:
                roots.append(p)

        def node(p: Part, seen: frozenset) -> dict:
            item = impacted.get(p.id)
            # Cycle guard: never descend into a part already on the current path.
            seen = seen | {p.id}
            kids = [c for c in sorted(children_map.get(p.id, []), key=lambda x: x.id)
                    if c.id not in seen]
            return {
                "part_id": p.id,
                "part_number": p.part_number,
                "name": p.name,
                "part_type": p.part_type,
                "item_category": p.item_category,
                "is_impacted": item is not None,
                "is_lead": bool(item and item.is_lead),
                "resulting_revision_id": item.resulting_revision_id if item else None,
                "children": [node(c, seen) for c in kids],
            }

        return {
            "tree": [node(p, frozenset()) for p in sorted(roots, key=lambda x: x.id)],
            "impacted_part_ids": sorted(impacted),
            "lead_part_id": next(
                (pid for pid, it in impacted.items() if it.is_lead), None),
        }

    @staticmethod
    async def suggest_rollups(session: AsyncSession, project_id: int,
                              part_ids: set[int]) -> set[int]:
        """Transitive BOM roll-up: parents whose display revision's BOM
        references a selected (or already-suggested) part structurally must
        revise too. Display revision = active revision, else latest."""
        rows = (await session.execute(
            select(Part.id, Part.active_revision_id)
            .where(Part.project_id == project_id))).all()
        display_rev_to_part: dict[int, int] = {}
        missing = []
        for pid, active in rows:
            if active is not None:
                display_rev_to_part[active] = pid
            else:
                missing.append(pid)
        if missing:
            latest = (await session.execute(
                select(PartRevision.part_id, func.max(PartRevision.id))
                .where(PartRevision.part_id.in_(missing))
                .group_by(PartRevision.part_id))).all()
            for pid, rid in latest:
                display_rev_to_part[rid] = pid
        if not display_rev_to_part:
            return set()
        edges = (await session.execute(
            select(PartBOMItem.child_part_id, PartBOMItem.revision_id).where(
                PartBOMItem.revision_id.in_(display_rev_to_part.keys()),
                PartBOMItem.child_part_id.is_not(None)))).all()
        parents_of: dict[int, set[int]] = defaultdict(set)
        for child_id, rev_id in edges:
            parents_of[child_id].add(display_rev_to_part[rev_id])

        suggested: set[int] = set()
        frontier = set(part_ids)
        while frontier:
            nxt: set[int] = set()
            for pid in frontier:
                for parent in parents_of.get(pid, ()):
                    if parent not in part_ids and parent not in suggested:
                        suggested.add(parent)
                        nxt.add(parent)
            frontier = nxt
        return suggested

    @staticmethod
    async def apply_impact_selection(session: AsyncSession, change: ChangeRequest,
                                     part_ids: list[int], user_id: int) -> None:
        if change.status in IMPACT_LOCKED_STATUSES:
            raise ChangeError(
                "Impact selection is locked once implementation has started")
        wanted = set(part_ids)
        valid = {pid for (pid,) in (await session.execute(
            select(Part.id).where(Part.project_id == change.project_id,
                                  Part.id.in_(wanted))))}
        unknown = sorted(wanted - valid)
        if unknown:
            raise ChangeError(f"Parts not in this project: {unknown}")
        current = {i.part_id: i for i in change.impacted_items}
        changed = False
        for pid, item in list(current.items()):
            if pid in wanted:
                continue
            if item.is_lead:
                raise ChangeError("The lead item cannot be removed")
            if item.resulting_revision_id is not None:
                raise ChangeError(
                    f"Part {pid} already has a spawned revision and cannot be removed")
            await session.delete(item)
            await ChangeService.append_changelog(
                session, change, "impacted_removed",
                f"Impacted part {pid} removed via impact tree", user_id,
                old_value={"part_id": pid})
            changed = True
        for pid in sorted(wanted - set(current)):
            session.add(ChangeImpactedItem(change_id=change.id, part_id=pid,
                                           created_by=user_id))
            await ChangeService.append_changelog(
                session, change, "impacted_added",
                f"Impacted part {pid} added via impact tree", user_id,
                new_value={"part_id": pid})
            changed = True
        await session.flush()
        if changed:
            await ChangeService._reset_impact_confirmation(session, change, user_id)

    @staticmethod
    async def _reset_impact_confirmation(
        session: AsyncSession, change: ChangeRequest, user_id: int,
    ) -> None:
        """Task 18: the impacted-item set changed after Engineering (R&D)
        confirmed it - invalidate the confirmation so it must be redone."""
        if change.impact_confirmed_at is None:
            return
        change.impact_confirmed_by = None
        change.impact_confirmed_at = None
        await ChangeService.append_changelog(
            session, change, "impact_confirmation_reset",
            "Impact confirmation cleared - impacted-item set changed", user_id,
        )

    @staticmethod
    async def add_impacted_item(
        session: AsyncSession, change: ChangeRequest, part_id: int,
        user_id: int, *, impact_note: Optional[str] = None,
        eng_level_before: Optional[str] = None,
        is_lead: bool = False,
    ) -> ChangeImpactedItem:
        part = await session.get(Part, part_id)
        if not part or part.project_id != change.project_id:
            raise ChangeError("Part not found in this project")
        if any(i.part_id == part_id for i in change.impacted_items):
            raise ChangeError("Item already impacted")
        item = ChangeImpactedItem(
            change_id=change.id, part_id=part_id, impact_note=impact_note,
            eng_level_before=eng_level_before, created_by=user_id, is_lead=is_lead,
        )
        session.add(item)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "impacted_item_added",
            f"Added impacted item {part.part_number}", user_id,
            new_value={"part_id": part_id},
        )
        await ChangeService._reset_impact_confirmation(session, change, user_id)
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
        await ChangeService._reset_impact_confirmation(session, change, user_id)

    @staticmethod
    async def confirm_impact(
        session: AsyncSession, change: ChangeRequest, user_id: int,
    ) -> ChangeRequest:
        """Task 18: Engineering (R&D) confirms the lead-proposed impacted-item
        set. Idempotent by design - re-confirming (e.g. by a different R&D
        member) simply refreshes who/when; it does not error, since the set
        may legitimately be re-reviewed without having changed."""
        if not change.impacted_items:
            raise ChangeError("No impacted items to confirm")
        change.impact_confirmed_by = user_id
        change.impact_confirmed_at = datetime.utcnow()
        await ChangeService.append_changelog(
            session, change, "impact_confirmed",
            "Impacted-item set confirmed by Engineering (R&D)", user_id,
        )
        return change

    @staticmethod
    async def user_can_confirm_impact(session: AsyncSession, user: User) -> bool:
        """Task 18's confirm-impact rule (only an R&D department member or an
        admin), extracted so both POST /impact/confirm (changes.py) and the
        Task 19 my-actions assembly below use the identical check instead of
        duplicating it."""
        if user.role == "admin":
            return True
        from app.services.workflow_service import WorkflowService
        rd_dept = (await session.execute(
            select(Department).where(Department.name == "R&D"))).scalar_one_or_none()
        if rd_dept is None:
            return False
        dept_ids = await WorkflowService.get_user_department_ids(session, user.id)
        return rd_dept.id in dept_ids

    @staticmethod
    async def my_actions(
        session: AsyncSession, change: ChangeRequest, user: User,
    ) -> list[dict]:
        """Task 19: the current user's open, actionable items on this one
        change - the cockpit's 'Your actions' panel. Every authz check below
        mirrors the endpoint that actually performs the action; see the
        docstring on each for the mirrored source."""
        from app.models.workflow import WfInstance, WfInstanceTask, WfStep
        from app.services.workflow_service import WorkflowService

        actions: list[dict] = []
        dept_ids = set(await WorkflowService.get_user_department_ids(session, user.id))

        # kind "assessment": active change-scoped assessment tasks in the
        # user's departments, or owned by them. Mirrors GET /changes/my-tasks
        # (changes.py my_change_tasks) narrowed to this one change.
        assess_dept_ids = {a.department_id for a in change.assessments}
        dept_names: dict[int, str] = {}
        if assess_dept_ids:
            rows = (await session.execute(
                select(Department.id, Department.name)
                .where(Department.id.in_(assess_dept_ids)))).all()
            dept_names = {i: n for i, n in rows}
        for a in change.assessments:
            if a.effective_status != "active":
                continue
            if a.department_id not in dept_ids and a.effective_owner_id != user.id:
                continue
            actions.append({
                "kind": "assessment",
                "label": f"Submit assessment for {dept_names.get(a.department_id, a.department_id)}",
                "target_tab": "assessments",
                "assessment_id": a.id,
            })

        # kind "wf_task": active ECN (part-revision-scoped) tasks spawned by
        # this change, in the user's departments or owned by them. Mirrors
        # WorkflowService.get_my_tasks, narrowed to this change via
        # PartRevision.originating_change_id.
        task_rows = (await session.execute(
            select(WfInstanceTask, WfStep.step_name)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .join(PartRevision, PartRevision.id == WfInstance.part_revision_id)
            .outerjoin(WfStep, WfStep.id == WfInstanceTask.step_id)
            .where(
                PartRevision.originating_change_id == change.id,
                WfInstance.status == "active",
                WfInstanceTask.status == "active",
                WfInstanceTask.is_actionable == True,  # noqa: E712
            ))).all()
        for t, step_name in task_rows:
            if t.department_id not in dept_ids and t.owner_id != user.id:
                continue
            actions.append({
                "kind": "wf_task",
                "label": f"Complete {step_name or 'workflow'} task",
                "target_tab": "implementation",
                "task_id": t.id,
            })

        # kind "deviation_decision": pending transition deviations this user
        # may decide. Mirrors ChangeService.decide_transition_deviation's
        # authz exactly (4-eyes rule + engineer/admin + lead-or-admin).
        for dev in change.transition_deviations:
            if dev.status != "pending":
                continue
            if dev.proposed_by == user.id:
                continue
            if user.role not in ("admin", "engineer"):
                continue
            if (user.role != "admin" and user.id != change.lead_id
                    and dev.proposed_by != change.lead_id):
                continue
            actions.append({
                "kind": "deviation_decision",
                "label": f"Decide deviation #{dev.id}",
                "target_tab": "overview",
                "deviation_id": dev.id,
            })

        # kind "impact_confirm": approved & not yet confirmed, and this user
        # may confirm it. Mirrors ChangeService.user_can_confirm_impact /
        # POST /changes/{id}/impact/confirm's authz (changes.py confirm_impact).
        if (change.status == "approved" and change.impact_confirmed_at is None
                and await ChangeService.user_can_confirm_impact(session, user)):
            actions.append({
                "kind": "impact_confirm",
                "label": "Confirm impacted items",
                "target_tab": "impacted",
            })

        # kind "gate": a gate that guards the currently-reachable transition,
        # not yet decided 'yes', decidable by this user. Mirrors put_gate's
        # authz exactly (changes.py put_gate: admin or the change lead).
        if user.role == "admin" or user.id == change.lead_id:
            reachable = ALLOWED_TRANSITIONS.get(change.status, set())
            for gate in change.gates:
                target = GATE_TARGET_STATUS.get(gate.gate_key)
                if target in reachable and gate.decision != "yes":
                    actions.append({
                        "kind": "gate",
                        "label": f"Decide gate '{gate.gate_key}'",
                        "target_tab": "d1",
                        "gate_key": gate.gate_key,
                    })

        return actions

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
        conditions=None, notes=None, responsible_id=None, effort_hours=None,
    ) -> ChangeAssessment:
        if verdict not in ASSESSMENT_VERDICTS:
            raise ChangeError(f"Invalid verdict '{verdict}'")
        result = await session.execute(
            select(ChangeAssessment).where(
                (ChangeAssessment.change_id == change.id)
                & (ChangeAssessment.department_id == department_id)
            )
        )
        rows = result.scalars().all()
        # A department may hold assessment rows across several stages (e.g. R in
        # stage 1, A in stage 2). Target the currently-actionable one deterministically
        # via effective_status (which reads execution state through the linked engine
        # task): prefer the lowest-stage effectively-'active' row, else the lowest-stage
        # effectively-'pending' row. Rows whose task is already completed read
        # 'submitted'/'waived' and are done, so they are never re-targeted — even
        # though their own raw status column stays 'pending'.
        open_rows = [r for r in rows if r.effective_status not in ("submitted", "waived")]
        if open_rows:
            a = min(open_rows, key=lambda r: (r.effective_status != "active", r.stage_order))
        elif not rows:
            # No routing row at all: tolerate a bare submit (pre-routing behaviour).
            a = ChangeAssessment(change_id=change.id, department_id=department_id)
            session.add(a)
        else:
            raise ChangeError("no open assessment for this department")
        a.verdict = verdict
        a.cost_impact = cost_impact
        a.lead_time_impact_days = lead_time_impact_days
        a.conditions = conditions
        a.notes = notes
        a.responsible_id = responsible_id
        a.effort_hours = effort_hours
        a.submitted_at = datetime.utcnow()
        a.submitted_by = user_id
        await session.flush()
        # Blocking (R/A) rows linked to an engine task complete that task, which
        # drives stage advancement through the workflow engine. S/C rows and any
        # unlinked row (a future stage whose task does not exist yet, or a legacy
        # bare-submit row) are payload-only: mark the row submitted directly.
        if a.rasic_letter in BLOCKING_LETTERS and a.wf_instance_task_id is not None:
            from app.services.workflow_service import WorkflowService
            await WorkflowService.complete_task(
                session, a.wf_instance_task_id, "approved",
                notes or f"Assessment: {verdict}", user_id)
        else:
            a.status = "submitted"   # S/C payload-only; unlinked legacy rows too
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_submitted",
            f"Assessment for dept {department_id}: {verdict}", user_id,
            field_name="verdict", new_value=verdict,
        )
        return a

    @staticmethod
    async def _get_assessment(session: AsyncSession, change: ChangeRequest,
                              assessment_id: int) -> ChangeAssessment:
        a = await session.get(ChangeAssessment, assessment_id)
        if a is None or a.change_id != change.id:
            raise ChangeError("Assessment not found on this change")
        # Execution state lives on the linked engine task for R/A rows (Phase E);
        # the row itself may sit at "pending" while its task is active.
        if a.effective_status != "active":
            raise ChangeError("Assessment is not active")
        return a

    @staticmethod
    async def accept_assessment(session: AsyncSession, change: ChangeRequest,
                                assessment_id: int, user) -> ChangeAssessment:
        from app.services.workflow_service import WorkflowService
        a = await ChangeService._get_assessment(session, change, assessment_id)
        if a.wf_instance_task_id is not None and a.rasic_letter in BLOCKING_LETTERS:
            # Linked R/A row: the engine task is the source of truth for
            # execution state — delegate ownership to it.
            try:
                await WorkflowService.accept_task(session, a.wf_instance_task_id, user)
            except ValueError as e:
                raise ChangeError(str(e))
        else:
            # Legacy/unlinked fallback (e.g. routing-deviation rows).
            if user.role != "admin" and not await WorkflowService._is_department_member(
                    session, user.id, a.department_id):
                raise ChangeError("Only members of the assessed department may accept")
            if a.owner_id is not None and a.owner_id != user.id:
                raise ChangeError("Assessment is already owned by another user")
            a.owner_id = user.id
            a.accepted_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_accepted",
            f"Assessment {a.id} accepted", user.id,
            new_value={"assessment_id": a.id, "owner_id": user.id})
        return a

    @staticmethod
    async def assign_assessment(session: AsyncSession, change: ChangeRequest,
                                assessment_id: int, assignee_id: int,
                                actor) -> ChangeAssessment:
        from app.services.workflow_service import WorkflowService
        a = await ChangeService._get_assessment(session, change, assessment_id)
        if a.wf_instance_task_id is not None and a.rasic_letter in BLOCKING_LETTERS:
            # Linked R/A row: delegate to the engine task. WorkflowService
            # .assign_task authorizes admin-or-department-member, with the
            # same change-lead carve-out as set_task_due_date, mirroring the
            # legacy "change lead may assign" allowance below.
            try:
                await WorkflowService.assign_task(
                    session, a.wf_instance_task_id, assignee_id, actor)
            except ValueError as e:
                raise ChangeError(str(e))
        else:
            allowed = (actor.role == "admin" or change.lead_id == actor.id
                       or await WorkflowService._is_department_member(
                           session, actor.id, a.department_id))
            if not allowed:
                raise ChangeError(
                    "Only an admin, the change lead, or a department member may assign")
            assignee = await session.get(User, assignee_id)
            if assignee is None or not assignee.is_active:
                raise ChangeError("Assignee not found or inactive")
            if not await WorkflowService._is_department_member(
                    session, assignee_id, a.department_id):
                raise ChangeError("Assignee must be a member of the assessed department")
            a.owner_id = assignee_id
            a.accepted_at = None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_assigned",
            f"Assessment {a.id} assigned to user {assignee_id}", actor.id,
            new_value={"assessment_id": a.id, "owner_id": assignee_id})
        if assignee_id != actor.id:
            from app.services.notification_service import NotificationService
            await NotificationService.notify_users(
                session, [assignee_id],
                title=f"Assessment assigned: {change.change_number}",
                link=f"/changes/{change.id}")
        return a

    @staticmethod
    async def set_assessment_due_date(session: AsyncSession, change: ChangeRequest,
                                      assessment_id: int, due_date: datetime,
                                      actor) -> ChangeAssessment:
        from app.services.workflow_service import WorkflowService
        a = await ChangeService._get_assessment(session, change, assessment_id)
        old = a.effective_due_date.isoformat() if a.effective_due_date else None
        if a.wf_instance_task_id is not None and a.rasic_letter in BLOCKING_LETTERS:
            # Linked R/A row: delegate to the engine task, which already
            # authorizes against the change lead for change-scoped instances.
            try:
                await WorkflowService.set_task_due_date(
                    session, a.wf_instance_task_id, due_date, actor)
            except ValueError as e:
                raise ChangeError(str(e))
        else:
            if actor.role != "admin" and change.lead_id != actor.id:
                raise ChangeError("Only the change lead or an admin may set due dates")
            a.due_date = due_date
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assessment_due_date_set",
            f"Assessment {a.id} due date set", actor.id,
            old_value={"due_date": old},
            new_value={"assessment_id": a.id, "due_date": due_date.isoformat()})
        return a

    @staticmethod
    async def update_change(
        session: AsyncSession, change: ChangeRequest, user_id: int, **fields,
    ) -> ChangeRequest:
        allowed = {
            "title", "reason", "description", "priority", "change_type", "lead_id",
            "estimated_cost", "quoted_price", "pnl_note", "timing_milestone_id",
            "issuer", "is_series", "cm_internal", "cm_external",
            "implementation_mode", "customer_relevant", "car_line",
        }

        # Validate implementation_mode before applying any changes
        impl_mode = fields.get("implementation_mode")
        if impl_mode is not None and impl_mode not in IMPLEMENTATION_MODES:
            raise ChangeError(
                f"Invalid implementation_mode '{impl_mode}'. "
                f"Allowed: {', '.join(IMPLEMENTATION_MODES)}"
            )

        # customer_relevant may only be changed during capture/scoping, once
        # the change has moved on (costing, quoted, etc.) it has already
        # driven downstream gates/pricing decisions. Idempotent PATCHes
        # (same value) are allowed at any status.
        cust_rel = fields.get("customer_relevant")
        if (
            cust_rel is not None
            and cust_rel != change.customer_relevant
            and change.status not in ("captured", "scoping")
        ):
            raise ChangeError(
                "Customer-relevant can only be changed during capture or scoping"
            )

        # Sales-settable deadline: handled before the generic loop (not part
        # of the plain-attribute `allowed` whitelist) so an explicit null
        # (clear the deadline) is honored rather than skipped by the `v is
        # not None` guard below.
        if "required_by_date" in fields:
            new_date = fields.pop("required_by_date")
            old = change.required_by_date
            change.required_by_date = new_date
            # Reason only changes when the request explicitly carries it —
            # a date-only PATCH must not wipe the stored justification.
            if "required_by_reason" in fields:
                change.required_by_reason = fields.pop("required_by_reason")
            reason = change.required_by_reason
            change.required_by_set_by = user_id
            change.required_by_set_at = datetime.utcnow()
            await ChangeService.append_changelog(
                session, change, "deadline_set",
                f"Required-by {old} -> {new_date}", user_id,
                field_name="required_by_date",
                old_value=str(old) if old else None,
                new_value=str(new_date) if new_date else None, notes=reason)

        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(change, k, v)

        # Handle affected_plant_ids (replace-set semantics; [] clears all)
        if "affected_plant_ids" in fields and fields["affected_plant_ids"] is not None:
            from app.models.entities import Plant
            plant_ids = fields["affected_plant_ids"]
            plants = []
            for pid in plant_ids:
                plant = await session.get(Plant, pid)
                if plant is None:
                    raise ChangeError(f"Plant {pid} not found")
                plants.append(plant)
            old_ids = sorted(p.id for p in change.affected_plants)
            change.affected_plants = plants
            await session.flush()  # persist M2M rows before changelog query
            new_ids = sorted(plant_ids)
            await ChangeService.append_changelog(
                session, change, "affected_plants_updated",
                "Affected plants updated", user_id,
                field_name="affected_plant_ids",
                old_value=old_ids, new_value=new_ids,
            )

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
    async def approve_internal_costs(
        session: AsyncSession, change: ChangeRequest, actor: User,
        *, note: Optional[str] = None,
    ) -> ChangeRequest:
        """Internal costing branch: PM approves the summation total instead of
        a customer quote. Amount is snapshotted for the later P&L view."""
        from app.services.meeting_service import MeetingService
        if change.customer_relevant:
            raise ChangeError(
                "Customer-relevant changes are approved via the customer quote")
        # 'costing' is the normal branch; 'quoted' is tolerated for legacy internal
        # changes that were driven through the quote status before the costing-path
        # split existed — they still need an internal cost approval to reach approved.
        if change.status not in ("costing", "quoted"):
            raise ChangeError("Internal cost approval happens in 'costing' or 'quoted'")
        if change.internal_approved_at is not None:
            raise ChangeError("Internal costs are already approved")
        if actor.id != change.lead_id and not await MeetingService.user_is_pm(
                session, actor):
            raise ChangeError(
                "Only Project Management, the change lead, or an admin "
                "may approve internal costs")
        from app.services.cost_service import CostService
        summ = await CostService.summation(session, change)
        change.internal_approved_by = actor.id
        change.internal_approved_at = datetime.utcnow()
        change.internal_approved_amount = summ["totals"]["grand_total"]
        change.internal_approval_note = note
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "internal_costs_approved",
            f"Internal costs approved ({summ['totals']['grand_total']:.2f})",
            actor.id, field_name="internal_approved_amount",
            new_value=summ["totals"]["grand_total"], notes=note)
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
