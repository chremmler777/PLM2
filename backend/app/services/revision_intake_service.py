"""Revision intake (spec 2026-09-25 §17 / §17a): every new customer index is
captured and triaged.

A new customer major that comes in through a gated path (customer package,
customer data, upload, promote) is pending: status in_review, the part's
active revision unchanged, and one intake waiting for Development. The
triage picks the route, alone (no 4-eyes):

- full_ecr: a new change (captured, same project), lead item = the part, the
  pending major as the impacted item's resulting revision. The change's
  release activates it.
- attach_ecr: the same link on an open change the user chooses (refused once
  that change is past in_implementation).
- engineering_review: the light track (EngineeringReviewService): lock the
  impact, the serving departments answer "no impact" / "impact"; all "no
  impact" activates and closes, any "impact" is escalated to a full ECR.
- administrative: activated now, reason required (title block, re-upload,
  no content change).

A newer index for a part with a waiting intake supersedes it (old intake
superseded, its revision archived), unless the waiting one is linked to a
live change: then the receive is refused with a clear message.

Refusals: IntakeError (400), IntakeForbidden (403), IntakeNotFound (404).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeImpactedItem, ChangeRequest, SCOPING_STATUSES
from app.models.entities import Plant, Project, User
from app.models.part import Part, PartRevision, RevisionFile, RevisionStatus
from app.models.revision_intake import ROUTES, RevisionIntake
from app.models.workflow import Department, UserDepartment

logger = logging.getLogger(__name__)

DEVELOPMENT = "Development"

ROUTE_LABELS = {
    "full_ecr": "Full ECR",
    "attach_ecr": "Attached to an open change",
    "engineering_review": "Engineering review",
    "administrative": "Administrative",
}
SOURCE_LABELS = {
    "package": "Customer package",
    "customer_data": "Customer data",
    "upload": "Upload",
    "promote": "Proposal adopted by the customer",
}
# attach_ecr: a change past implementation cannot take a new index any more.
ATTACH_REFUSED = ("in_validation", "released", "closed", "cancelled", "rejected")


class IntakeError(ValueError):
    """Mapped to HTTP 400."""


class IntakeForbidden(PermissionError):
    """Mapped to HTTP 403."""


class IntakeNotFound(LookupError):
    """Mapped to HTTP 404."""


def suggest_route(revision_phase: Optional[str], part_phase: Optional[str],
                  has_active: bool) -> str:
    """Spec §17a decisions 1 and 9: official data or a series part -> full
    ECR; review data (E-levels) -> engineering review; the very first data
    on an rfq part -> administrative."""
    if not has_active and part_phase == "rfq":
        return "administrative"
    if revision_phase == "official" or part_phase == "series":
        return "full_ecr"
    return "engineering_review"


def _change_is_dead(change: Optional[ChangeRequest]) -> bool:
    """A linked change that will never release the index: cancelled, or
    rejected (and maybe closed) without a release."""
    if change is None:
        return True
    return change.status == "cancelled" or (
        change.status in ("rejected", "closed") and change.released_at is None)


def _val(v):
    return v.value if hasattr(v, "value") else v


class RevisionIntakeService:

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------
    @staticmethod
    async def may_triage(session: AsyncSession, user: User) -> bool:
        """Development members (acts-as aware) and admin."""
        from app.services.change_service import ChangeService
        return await ChangeService._user_in_department(session, user, DEVELOPMENT)

    @staticmethod
    async def _development_member_ids(session: AsyncSession) -> list[int]:
        return list((await session.execute(
            select(UserDepartment.user_id).join(
                Department, Department.id == UserDepartment.department_id)
            .where(Department.name == DEVELOPMENT))).scalars().all())

    # ------------------------------------------------------------------
    # Intake creation (called from RevisionService.receive_customer_data)
    # ------------------------------------------------------------------
    @staticmethod
    async def waiting_for_part(session: AsyncSession,
                               part_id: int) -> Optional[RevisionIntake]:
        return (await session.execute(
            select(RevisionIntake).where(
                RevisionIntake.part_id == part_id,
                RevisionIntake.activated_at.is_(None),
                RevisionIntake.status != "superseded")
            .order_by(RevisionIntake.id.desc()).limit(1))).scalar_one_or_none()

    @staticmethod
    async def link_block_message(session: AsyncSession,
                                 intake: RevisionIntake) -> Optional[str]:
        """Why a newer index cannot supersede this waiting one, or None."""
        if intake.change_id is None:
            return None
        change = await session.get(ChangeRequest, intake.change_id)
        if _change_is_dead(change):
            return None
        rev = await session.get(PartRevision, intake.revision_id)
        part = await session.get(Part, intake.part_id)
        return (f"Index {rev.revision_name if rev else '?'} of "
                f"{part.part_number if part else intake.part_id} is still pending and "
                f"linked to {change.change_number}: a newer index cannot replace it. "
                f"Release or cancel {change.change_number} first, or add the new "
                f"data to that change")

    @staticmethod
    async def supersedable(session: AsyncSession,
                           part_id: int) -> Optional[RevisionIntake]:
        """The waiting intake a newer index will supersede, or None; raises
        IntakeError when the waiting one is linked to a live change."""
        waiting = await RevisionIntakeService.waiting_for_part(session, part_id)
        if waiting is None:
            return None
        msg = await RevisionIntakeService.link_block_message(session, waiting)
        if msg:
            raise IntakeError(msg)
        return waiting

    @staticmethod
    async def create(session: AsyncSession, part: Part, revision: PartRevision,
                     source: str, *, received_at: Optional[date], user_id: Optional[int],
                     batch_id: Optional[str] = None,
                     promoted_from_revision_id: Optional[int] = None,
                     supersedes: Optional[RevisionIntake] = None) -> RevisionIntake:
        from app.services.part_service import ChangelogService
        if source not in SOURCE_LABELS:
            raise IntakeError(f"Unknown intake source '{source}'")
        revision_phase = _val(revision.phase)
        intake = RevisionIntake(
            part_id=part.id, project_id=part.project_id, revision_id=revision.id,
            source=source, batch_id=batch_id, received_at=received_at,
            received_by=user_id, status="pending", revision_phase=revision_phase,
            part_phase=part.lifecycle_phase,
            suggested_route=suggest_route(revision_phase, part.lifecycle_phase,
                                          part.active_revision_id is not None),
            promoted_from_revision_id=promoted_from_revision_id,
        )
        session.add(intake)
        await session.flush()
        if supersedes is not None:
            old_rev = await session.get(PartRevision, supersedes.revision_id)
            supersedes.status = "superseded"
            supersedes.superseded_by_id = intake.id
            if old_rev is not None:
                old_rev.status = RevisionStatus.ARCHIVED.value
            await ChangelogService.log_action(
                session, part_id=part.id, revision_id=supersedes.revision_id,
                action="intake_superseded",
                action_description=(
                    f"Index {old_rev.revision_name if old_rev else '?'} superseded by "
                    f"{revision.revision_name} before it was triaged (archived)"),
                performed_by=user_id)
        members = [m for m in await RevisionIntakeService._development_member_ids(session)
                   if m != user_id]
        if members:
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, sorted(set(members)), kind="revision_intake",
                subject_key=f"intake:{intake.id}",
                title=f"Triage index {revision.revision_name} of {part.part_number}"[:255],
                body=f"{SOURCE_LABELS[source]}: decide the route for the new index",
                link=f"/parts/{part.id}")
        return intake

    # ------------------------------------------------------------------
    # Activation (shared with ChangeService.release)
    # ------------------------------------------------------------------
    @staticmethod
    async def activate(session: AsyncSession, rev: PartRevision, user_id: int, *,
                       note: Optional[str] = None,
                       change: Optional[ChangeRequest] = None) -> PartRevision:
        """The revision becomes the part's active one: pointer, approved,
        supersedes the prior active one; a pending customer major's intake
        is stamped activated and a promotion's side effects happen now."""
        from app.services.part_service import ChangelogService, RevisionService
        part = await session.get(Part, rev.part_id)
        if part is None:
            raise IntakeError("Part not found")
        prior = part.active_revision_id
        if prior is not None and prior != rev.id:
            rev.supersedes_revision_id = prior
        now = datetime.utcnow()
        rev.status = RevisionStatus.APPROVED.value
        rev.approved_at = now
        rev.approved_by = user_id
        part.active_revision_id = rev.id
        intake = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.revision_id == rev.id)
        )).scalar_one_or_none()
        if intake is not None and intake.activated_at is None:
            intake.activated_at = now
            intake.activated_by = user_id
            if intake.promoted_from_revision_id:
                proposal = await session.get(PartRevision, intake.promoted_from_revision_id)
                if proposal is not None:
                    await RevisionService.apply_promotion(
                        session, proposal, rev.revision_name, user_id)
            await ChangelogService.log_action(
                session, part_id=part.id, revision_id=rev.id, action="activated",
                action_description=(f"Index {rev.revision_name} activated"
                                    + (f": {note}" if note else "")),
                performed_by=user_id)
        await session.flush()
        return rev

    # ------------------------------------------------------------------
    # Triage
    # ------------------------------------------------------------------
    @staticmethod
    async def get(session: AsyncSession, intake_id: int,
                  user: Optional[User] = None) -> RevisionIntake:
        intake = await session.get(RevisionIntake, intake_id)
        if intake is None:
            raise IntakeNotFound("Intake not found")
        if user is not None and user.effective_role != "admin":
            org = (await session.execute(
                select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
                .where(Project.id == intake.project_id))).scalar_one_or_none()
            if org is not None and org != user.organization_id:
                raise IntakeNotFound("Intake not found")
        return intake

    @staticmethod
    async def decide(session: AsyncSession, intake: RevisionIntake, route: str,
                     user: User, *, reason: Optional[str] = None,
                     change_id: Optional[int] = None) -> RevisionIntake:
        from app.services.part_service import ChangelogService
        if not await RevisionIntakeService.may_triage(session, user):
            raise IntakeForbidden(
                "Only Development decides the route of a new index "
                "(admins: act as Development)")
        if route not in ROUTES:
            raise IntakeError(f"Unknown route '{route}' - one of {', '.join(ROUTES)}")
        if intake.status == "superseded":
            raise IntakeError("This index was superseded by a newer one: triage that one")
        if intake.activated_at is not None:
            raise IntakeError("This index is already active")
        if intake.status == "decided":
            linked = (await session.get(ChangeRequest, intake.change_id)
                      if intake.change_id else None)
            if not _change_is_dead(linked):
                raise IntakeError(
                    f"Already decided ({ROUTE_LABELS.get(intake.route, intake.route)})")
            # The linked change died without releasing it: triage again.
        reason = (reason or "").strip() or None
        if route == "administrative" and not reason:
            raise IntakeError(
                "A reason is required to activate an index administratively "
                "(e.g. title block only, re-upload, no content change)")
        if route != intake.suggested_route and not reason:
            raise IntakeError(
                f"Say why you pick {ROUTE_LABELS[route]} instead of the suggested "
                f"{ROUTE_LABELS.get(intake.suggested_route, intake.suggested_route)}")
        rev = await session.get(PartRevision, intake.revision_id)
        part = await session.get(Part, intake.part_id)
        if rev is None or part is None:
            raise IntakeError("The revision of this intake no longer exists")

        change = None
        if route == "full_ecr":
            change = await RevisionIntakeService._start_full_ecr(
                session, intake, part, rev, user, reason)
        elif route == "attach_ecr":
            change = await RevisionIntakeService._attach(
                session, intake, part, rev, user, change_id)
        elif route == "engineering_review":
            from app.services.engineering_review_service import EngineeringReviewService
            change = await EngineeringReviewService.start(
                session, intake, part, rev, user, reason)

        intake.route = route
        intake.reason = reason
        intake.status = "decided"
        intake.decided_by = user.id
        intake.decided_at = datetime.utcnow()
        intake.change_id = change.id if change is not None else None
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=part.id, revision_id=rev.id, action="intake_decided",
            action_description=(
                f"Index {rev.revision_name} triaged: {ROUTE_LABELS[route]}"
                + (f" ({change.change_number})" if change is not None else "")
                + (f". Reason: {reason}" if reason else "")),
            performed_by=user.id, new_value=route, notes=reason)
        if route == "administrative":
            await RevisionIntakeService.activate(
                session, rev, user.id, note=f"administrative: {reason}")
        return intake

    @staticmethod
    def _description(intake: RevisionIntake, part: Part, rev: PartRevision,
                     reason: Optional[str]) -> str:
        bits = [f"Customer {intake.revision_phase or ''} data".replace("  ", " ")
                + (f" received {intake.received_at.isoformat()}" if intake.received_at else "")
                + f" as index {rev.revision_name}"
                + (f" (customer index {rev.customer_index})" if rev.customer_index else "")
                + f" on {part.part_number} {part.name}"
                + f", via {SOURCE_LABELS.get(intake.source, intake.source).lower()}."]
        if rev.summary:
            bits.append(rev.summary)
        if reason:
            bits.append(f"Triage: {reason}")
        return "\n".join(bits)

    @staticmethod
    async def _link_item(session: AsyncSession, change: ChangeRequest, part: Part,
                         rev: PartRevision, user_id: int, *, lead: bool) -> None:
        from app.services.change_service import ChangeService
        await session.refresh(change, ["impacted_items"])
        item = next((i for i in change.impacted_items if i.part_id == part.id), None)
        if item is not None:
            if item.resulting_revision_id not in (None, rev.id):
                other = await session.get(PartRevision, item.resulting_revision_id)
                raise IntakeError(
                    f"{part.part_number} already carries revision "
                    f"{other.revision_name if other else item.resulting_revision_id} in "
                    f"{change.change_number}: a second new revision of the same part "
                    f"cannot ride on it")
        elif change.status in SCOPING_STATUSES:
            item = await ChangeService.add_impacted_item(
                session, change, part.id, user_id, is_lead=lead,
                eng_level_before=None)
        else:
            item = ChangeImpactedItem(change_id=change.id, part_id=part.id,
                                      created_by=user_id, is_lead=False)
            session.add(item)
            await session.flush()
            await ChangeService.append_changelog(
                session, change, "impacted_item_added",
                f"Added impacted item {part.part_number} (new customer index)", user_id,
                new_value={"part_id": part.id})
        active = (await session.get(PartRevision, part.active_revision_id)
                  if part.active_revision_id else None)
        if item.eng_level_before is None and active is not None:
            item.eng_level_before = active.revision_name
        item.resulting_revision_id = rev.id
        rev.originating_change_id = change.id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "intake_linked",
            f"New customer index {rev.revision_name} of {part.part_number} linked "
            f"as the resulting revision", user_id,
            new_value={"part_id": part.id, "revision_id": rev.id})
        if change.status == "in_implementation":
            await ChangeService._ensure_check_workflow(session, change, item, user_id)

    @staticmethod
    async def _start_full_ecr(session: AsyncSession, intake: RevisionIntake, part: Part,
                              rev: PartRevision, user: User,
                              reason: Optional[str]) -> ChangeRequest:
        from app.services.change_service import ChangeService
        change = await ChangeService.create_change(
            session, project_id=intake.project_id,
            title=f"New customer index {rev.revision_name}: {part.part_number} {part.name}"[:255],
            change_type="physical_part", raised_by=user.id,
            reason=reason or "New customer index",
            description=RevisionIntakeService._description(intake, part, rev, reason),
            customer_relevant=True)
        await RevisionIntakeService._link_item(session, change, part, rev, user.id, lead=True)
        await ChangeService.append_changelog(
            session, change, "intake_started",
            f"Started from the intake of index {rev.revision_name} ({part.part_number})",
            user.id, new_value={"intake_id": intake.id})
        return change

    @staticmethod
    async def _attach(session: AsyncSession, intake: RevisionIntake, part: Part,
                      rev: PartRevision, user: User,
                      change_id: Optional[int]) -> ChangeRequest:
        from app.services.change_service import ChangeService
        if change_id is None:
            raise IntakeError("Choose the open change to attach the index to")
        change = await ChangeService.get_change(session, change_id, viewer=user)
        if change is None:
            raise IntakeNotFound("Change not found")
        if change.project_id != intake.project_id:
            raise IntakeError("The change belongs to another project")
        if change.status in ATTACH_REFUSED:
            raise IntakeError(
                f"{change.change_number} is '{change.status}': a new index can only "
                f"join a change up to implementation. Start a full ECR instead")
        await RevisionIntakeService._link_item(session, change, part, rev, user.id, lead=False)
        await ChangeService.append_changelog(
            session, change, "intake_attached",
            f"Index {rev.revision_name} of {part.part_number} attached from the intake",
            user.id, new_value={"intake_id": intake.id})
        return change

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    def _org_scope(stmt, user: User):
        if user.effective_role == "admin":
            return stmt
        org_projects = select(Project.id).join(Plant, Project.plant_id == Plant.id).where(
            Plant.organization_id == user.organization_id)
        return stmt.where(RevisionIntake.project_id.in_(org_projects))

    @staticmethod
    async def list(session: AsyncSession, user: User, *, part_id: Optional[int] = None,
                   project_id: Optional[int] = None, status: Optional[str] = None,
                   change_id: Optional[int] = None,
                   waiting: Optional[bool] = None) -> list[RevisionIntake]:
        q = select(RevisionIntake)
        if part_id is not None:
            q = q.where(RevisionIntake.part_id == part_id)
        if project_id is not None:
            q = q.where(RevisionIntake.project_id == project_id)
        if status is not None:
            q = q.where(RevisionIntake.status == status)
        if change_id is not None:
            q = q.where(RevisionIntake.change_id == change_id)
        if waiting:
            q = q.where(RevisionIntake.activated_at.is_(None),
                        RevisionIntake.status != "superseded")
        q = RevisionIntakeService._org_scope(q, user)
        return list((await session.execute(
            q.order_by(RevisionIntake.id.desc()))).scalars().all())

    @staticmethod
    async def out(session: AsyncSession, intake: RevisionIntake,
                  can_triage: bool = False) -> dict:
        part = await session.get(Part, intake.part_id)
        rev = await session.get(PartRevision, intake.revision_id)
        change = (await session.get(ChangeRequest, intake.change_id)
                  if intake.change_id else None)
        project = await session.get(Project, intake.project_id)
        files = (await session.execute(
            select(func.count()).select_from(RevisionFile).where(
                RevisionFile.revision_id == intake.revision_id,
                RevisionFile.is_deleted.is_(False)))).scalar() or 0
        active = (await session.get(PartRevision, part.active_revision_id)
                  if part is not None and part.active_revision_id else None)
        retriage = (intake.status == "decided" and intake.activated_at is None
                    and intake.change_id is not None and _change_is_dead(change))
        return {
            "id": intake.id,
            "part_id": intake.part_id,
            "part_number": part.part_number if part else None,
            "part_name": part.name if part else None,
            "customer_part_number": part.customer_part_number if part else None,
            "project_id": intake.project_id,
            "project_name": project.name if project else None,
            "revision_id": intake.revision_id,
            "revision_name": rev.revision_name if rev else None,
            "customer_index": rev.customer_index if rev else None,
            "revision_status": _val(rev.status) if rev else None,
            "active_revision_name": active.revision_name if active else None,
            "file_count": files,
            "source": intake.source,
            "source_label": SOURCE_LABELS.get(intake.source, intake.source),
            "batch_id": intake.batch_id,
            "received_at": intake.received_at,
            "received_by_name": intake.received_by_name,
            "status": intake.status,
            "waiting": intake.is_waiting,
            "revision_phase": intake.revision_phase,
            "part_phase": intake.part_phase,
            "suggested_route": intake.suggested_route,
            "route": intake.route,
            "route_label": ROUTE_LABELS.get(intake.route) if intake.route else None,
            "reason": intake.reason,
            "decided_by_name": intake.decided_by_name,
            "decided_at": intake.decided_at,
            "change_id": intake.change_id,
            "change_number": change.change_number if change else None,
            "change_title": change.title if change else None,
            "change_status": change.status if change else None,
            "change_origin": change.origin if change else None,
            "activated_at": intake.activated_at,
            "escalated_at": intake.escalated_at,
            "superseded_by_id": intake.superseded_by_id,
            "created_at": intake.created_at,
            "needs_triage": intake.status == "pending" or retriage,
            "can_decide": can_triage and (intake.status == "pending" or retriage),
        }

    @staticmethod
    async def my(session: AsyncSession, user: User) -> dict:
        """My Tasks: "Triage index <x> of <part>" for Development, and the
        engineering-review answers owed by the caller's departments."""
        from app.services.engineering_review_service import EngineeringReviewService
        triage = []
        can = await RevisionIntakeService.may_triage(session, user)
        if can:
            for i in await RevisionIntakeService.list(session, user, status="pending"):
                triage.append(await RevisionIntakeService.out(session, i, True))
        reviews = await EngineeringReviewService.my_open_answers(session, user)
        return {"triage": triage, "review": reviews}
