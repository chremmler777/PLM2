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
from app.models.revision_intake import (
    CLOSED_STATUSES, LIVE_CHANGE_REASONS, NO_VISIBLE_CHANGE, ROUTES, WHAT_CHANGED_AREAS,
    RevisionIntake,
)
from app.models.workflow import Department

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


def _v2() -> bool:
    from app.services import cm_switches
    return cm_switches.on("SCOPING_V2")


#: A live change: not dead and not past release.
NOT_LIVE = ("released", "closed", "cancelled", "rejected")
LIVE_CHANGE_REASON_LABELS = {
    "separate_topic": "A separate topic from the live change",
    "customer_separate_ec": "The customer runs it as a separate EC",
    "live_change_too_far": "The live change is too far along",
    "other": "Other",
}


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
    async def _development_id(session: AsyncSession) -> Optional[int]:
        return (await session.execute(
            select(Department.id).where(Department.name == DEVELOPMENT))).scalar_one_or_none()

    @staticmethod
    async def _development_member_ids(session: AsyncSession,
                                      project_id: Optional[int]) -> list[int]:
        """Active Development members of the project's organization only
        (never a namesake department of another customer's plant)."""
        from app.services.change_people import department_members_of_change_org
        from types import SimpleNamespace
        dev_id = await RevisionIntakeService._development_id(session)
        if dev_id is None:
            return []
        return await department_members_of_change_org(
            session, SimpleNamespace(project_id=project_id), [dev_id])

    @staticmethod
    async def _notify_development(session: AsyncSession, intake: RevisionIntake,
                                  actor_id: Optional[int], *, title: str, body: str,
                                  subject_key: str) -> None:
        members = [m for m in await RevisionIntakeService._development_member_ids(
            session, intake.project_id) if m != actor_id]
        if not members:
            return
        from app.services.notification_service import NotificationService
        dev_id = await RevisionIntakeService._development_id(session)
        await NotificationService.notify_team(
            session, intake.project_id, [dev_id] if dev_id else [], members,
            kind="revision_intake", subject_key=subject_key, title=title[:255],
            body=body, link=f"/parts/{intake.part_id}")

    # ------------------------------------------------------------------
    # Links to a change that died (cancelled / rejected without release)
    # ------------------------------------------------------------------
    @staticmethod
    async def unlink_dead_change(session: AsyncSession, intake: RevisionIntake,
                                 user_id: Optional[int], why: str) -> None:
        """The index leaves the dead change it was linked to: the impacted
        item's resulting revision is cleared (so a reopened change cannot
        release it) and the change's changelog says why."""
        if intake.change_id is None:
            return
        change = await session.get(ChangeRequest, intake.change_id)
        if change is None or not _change_is_dead(change):
            return
        items = (await session.execute(
            select(ChangeImpactedItem).where(
                ChangeImpactedItem.change_id == change.id,
                ChangeImpactedItem.resulting_revision_id == intake.revision_id))).scalars().all()
        rev = await session.get(PartRevision, intake.revision_id)
        if rev is not None and rev.originating_change_id == change.id:
            rev.originating_change_id = None
        if not items:
            return
        for item in items:
            item.resulting_revision_id = None
        await session.flush()
        part = await session.get(Part, intake.part_id)
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "intake_unlinked",
            f"Index {rev.revision_name if rev else intake.revision_id} of "
            f"{part.part_number if part else intake.part_id} unlinked: {why}",
            user_id, old_value={"revision_id": intake.revision_id},
            new_value={"intake_id": intake.id})

    @staticmethod
    async def on_change_dead(session: AsyncSession, change: ChangeRequest,
                             user_id: Optional[int]) -> None:
        """A change was cancelled or rejected: every index it was to release
        waits for a new triage. Development is told."""
        if not _change_is_dead(change):
            return
        intakes = (await session.execute(
            select(RevisionIntake).where(
                RevisionIntake.change_id == change.id,
                RevisionIntake.activated_at.is_(None),
                RevisionIntake.status == "decided"))).scalars().all()
        for intake in intakes:
            rev = await session.get(PartRevision, intake.revision_id)
            part = await session.get(Part, intake.part_id)
            name = rev.revision_name if rev else "?"
            number = part.part_number if part else intake.part_id
            await RevisionIntakeService._notify_development(
                session, intake, user_id,
                title=f"Triage again: index {name} of {number}",
                body=(f"{change.change_number} was {change.status}: the index is "
                      f"still pending and needs a new route"),
                subject_key=f"intake:{intake.id}:retriage:{change.id}")

    @staticmethod
    async def activation_blocker(session: AsyncSession, rev: PartRevision,
                                 change: Optional[ChangeRequest]) -> Optional[str]:
        """Why this change (None: a route without a change) may not activate
        the revision, or None. A pending customer index is only activated
        through its own, current intake."""
        intake = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.revision_id == rev.id)
        )).scalar_one_or_none()
        if intake is None or intake.activated_at is not None:
            return None
        where = f" in {change.change_number}" if change is not None else ""
        if intake.status == "superseded":
            newer = (await session.get(RevisionIntake, intake.superseded_by_id)
                     if intake.superseded_by_id else None)
            newer_rev = (await session.get(PartRevision, newer.revision_id)
                         if newer is not None else None)
            return (f"Index {rev.revision_name} was superseded by "
                    f"{newer_rev.revision_name if newer_rev else 'a newer index'}; "
                    f"re-link or remove it{where}")
        if intake.status == "rejected":
            return (f"Index {rev.revision_name} was rejected; "
                    f"re-link or remove it{where}")
        if change is not None and intake.change_id is not None \
                and intake.change_id != change.id:
            other = await session.get(ChangeRequest, intake.change_id)
            return (f"Index {rev.revision_name} was re-triaged to "
                    f"{other.change_number if other else intake.change_id}; "
                    f"re-link or remove it{where}")
        return None

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
                RevisionIntake.status.notin_(CLOSED_STATUSES))
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
            if _v2():
                # minimal C11 (spec §1): a newer index is never refused. It
                # waits for triage on its own; attached to that change it
                # supersedes the old one inside it (_link_item).
                return None
            raise IntakeError(msg)
        return waiting

    @staticmethod
    async def live_changes_for_part(session: AsyncSession, part_id: int,
                                    project_id: Optional[int] = None,
                                    exclude_id: Optional[int] = None) -> list[ChangeRequest]:
        """Every live change (not released, closed, cancelled or rejected)
        whose impacted set holds the part, newest first: triage names them
        all (spec §1), so none of them goes on with an old index unseen."""
        q = (select(ChangeRequest)
             .join(ChangeImpactedItem, ChangeImpactedItem.change_id == ChangeRequest.id)
             .where(ChangeImpactedItem.part_id == part_id,
                    ChangeRequest.status.notin_(NOT_LIVE),
                    ChangeRequest.origin != "engineering_review"))
        if project_id is not None:
            q = q.where(ChangeRequest.project_id == project_id)
        if exclude_id is not None:
            q = q.where(ChangeRequest.id != exclude_id)
        return list(dict.fromkeys((await session.execute(
            q.order_by(ChangeRequest.id.desc()))).scalars().all()))

    @staticmethod
    async def live_change_rows(session: AsyncSession, intakes: list[RevisionIntake],
                               ) -> dict[tuple, list]:
        """The live changes carrying each intake's part, for a whole list in
        one query (R34): (part_id, project_id) -> rows newest first, each
        with only what triage shows (id, number, title, status, lead name,
        customer_relevant), never a full change with its relationships."""
        from types import SimpleNamespace
        keys = {(i.part_id, i.project_id) for i in intakes}
        if not keys:
            return {}
        rows = (await session.execute(
            select(ChangeImpactedItem.part_id, ChangeRequest.id,
                   ChangeRequest.change_number, ChangeRequest.title,
                   ChangeRequest.status, ChangeRequest.customer_relevant,
                   ChangeRequest.project_id, User.full_name)
            .join(ChangeRequest, ChangeImpactedItem.change_id == ChangeRequest.id)
            .outerjoin(User, User.id == ChangeRequest.lead_id)
            .where(ChangeImpactedItem.part_id.in_({p for p, _ in keys}),
                   ChangeRequest.status.notin_(NOT_LIVE),
                   ChangeRequest.origin != "engineering_review")
            .order_by(ChangeRequest.id.desc()))).all()
        out: dict[tuple, list] = {k: [] for k in keys}
        for part_id, cid, number, title, status, cust, proj, lead in rows:
            for key in ((part_id, proj), (part_id, None)):
                if key in out and all(c.id != cid for c in out[key]):
                    out[key].append(SimpleNamespace(
                        id=cid, change_number=number, title=title, status=status,
                        customer_relevant=cust, lead_name=lead))
        return out

    @staticmethod
    async def live_change_for_part(session: AsyncSession, part_id: int,
                                   project_id: Optional[int] = None,
                                   exclude_id: Optional[int] = None) -> Optional[ChangeRequest]:
        """The newest live change whose impacted set holds the part."""
        lives = await RevisionIntakeService.live_changes_for_part(
            session, part_id, project_id, exclude_id)
        return lives[0] if lives else None

    @staticmethod
    async def suggestion(session: AsyncSession, intake: RevisionIntake,
                         lives: Optional[list[ChangeRequest]] = None,
                         ) -> tuple[Optional[str], Optional[ChangeRequest]]:
        """(suggested route, the live change carrying the part): with
        SCOPING_V2 the newest live change that can still take the index
        makes attach_ecr the suggestion; else the phase rule's route (and
        the newest live change, named)."""
        if not _v2():
            return intake.suggested_route, None
        if lives is None:
            lives = await RevisionIntakeService.live_changes_for_part(
                session, intake.part_id, intake.project_id,
                exclude_id=intake.change_id if intake.status == "decided" else None)
        attachable = next((c for c in lives if c.status not in ATTACH_REFUSED), None)
        if attachable is not None:
            return "attach_ecr", attachable
        return intake.suggested_route, (lives[0] if lives else None)

    @staticmethod
    async def _tell_other_live_changes(session: AsyncSession, intake: RevisionIntake,
                                       part: Part, rev: PartRevision,
                                       target: Optional[ChangeRequest], user_id: int,
                                       administrative: Optional[str] = None) -> None:
        """The other live changes carrying the part (not the one the index
        went to): their leads are told once, so a quote or costing built on
        the old index is checked (spec §1, involved people only)."""
        from app.services.notification_service import NotificationService
        others = [c for c in await RevisionIntakeService.live_changes_for_part(
            session, intake.part_id, intake.project_id)
            if target is None or c.id != target.id]
        for c in others:
            if c.lead_id is None or c.lead_id == user_id:
                continue
            where = (f" went to {target.change_number}" if target is not None
                     else f" was activated administratively ({administrative})"
                     if administrative else " was triaged")
            await NotificationService.notify_once(
                session, [c.lead_id], kind="index_other_change",
                subject_key=f"index_other:{intake.id}:{c.id}",
                title=(f"New index {rev.revision_name} of {part.part_number}: "
                       f"check {c.change_number}")[:255],
                body=(f"Index {rev.revision_name} of {part.part_number}{where}. "
                      f"{c.change_number} ({c.status}) also carries the part: check "
                      "whether its assessment, costing or offer still holds."),
                link=f"/changes/{c.id}")

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
            await RevisionIntakeService.unlink_dead_change(
                session, supersedes, user_id,
                f"superseded by the newer index {revision.revision_name}")
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
        await RevisionIntakeService._notify_development(
            session, intake, user_id,
            title=f"Triage index {revision.revision_name} of {part.part_number}",
            body=f"{SOURCE_LABELS[source]}: decide the route for the new index",
            subject_key=f"intake:{intake.id}")
        return intake

    @staticmethod
    async def on_revision_rejected(session: AsyncSession, rev: PartRevision,
                                   user_id: Optional[int]) -> None:
        """The pending customer index itself was rejected: its intake is
        closed (status rejected, audited) and can no longer be triaged or
        activated. Refused while a live change is to release it."""
        from app.services.part_service import ChangelogService
        intake = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.revision_id == rev.id)
        )).scalar_one_or_none()
        if intake is None or intake.activated_at is not None \
                or intake.status in CLOSED_STATUSES:
            return
        msg = await RevisionIntakeService.link_block_message(session, intake)
        if msg:
            change = await session.get(ChangeRequest, intake.change_id)
            raise IntakeError(
                f"Index {rev.revision_name} is linked to {change.change_number}: "
                f"reject or cancel {change.change_number}, or remove the index "
                f"from it, before rejecting the index")
        await RevisionIntakeService.unlink_dead_change(
            session, intake, user_id, "the index was rejected")
        intake.status = "rejected"
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=intake.part_id, revision_id=rev.id,
            action="intake_rejected",
            action_description=(f"Index {rev.revision_name} rejected: its intake is "
                                f"closed without activation"),
            performed_by=user_id, new_value="rejected")

    @staticmethod
    async def on_revision_unrejected(session: AsyncSession, rev: PartRevision,
                                     user_id: Optional[int]) -> None:
        """The rejected index is restored: an intake that its rejection
        closed opens again as pending (waiting for Development's triage,
        audited), unless it still names a change (refused: that link has to
        be settled first) or a newer index superseded it meanwhile."""
        from app.services.part_service import ChangelogService
        intake = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.revision_id == rev.id)
        )).scalar_one_or_none()
        if intake is None or intake.status != "rejected" \
                or intake.activated_at is not None:
            return
        if intake.change_id is not None:
            change = await session.get(ChangeRequest, intake.change_id)
            if change is not None and not _change_is_dead(change):
                raise IntakeError(
                    f"Index {rev.revision_name} is still linked to "
                    f"{change.change_number}: remove it from that change before "
                    f"restoring the index")
        if intake.superseded_by_id is not None:
            raise IntakeError(
                f"Index {rev.revision_name} was superseded by a newer index: "
                f"it cannot be restored")
        other = await RevisionIntakeService.waiting_for_part(session, intake.part_id)
        if other is not None and other.id != intake.id:
            raise IntakeError(
                f"Another index of this part is waiting for triage: settle it "
                f"before restoring {rev.revision_name}")
        intake.change_id = None
        intake.status = "pending"
        intake.route = None
        intake.decided_by = None
        intake.decided_at = None
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=intake.part_id, revision_id=rev.id,
            action="intake_reopened",
            action_description=(f"Index {rev.revision_name} restored: its intake "
                                f"waits for triage again"),
            performed_by=user_id, old_value="rejected", new_value="pending")
        await RevisionIntakeService._notify_development(
            session, intake, user_id,
            title=f"Triage again: index {rev.revision_name}",
            body="The rejected index was restored and needs a route",
            subject_key=f"intake:{intake.id}:reopened:{datetime.utcnow().isoformat()}")

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
        block = await RevisionIntakeService.activation_blocker(session, rev, change)
        if block:
            raise IntakeError(block)
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
                     change_id: Optional[int] = None,
                     what_changed: Optional[list[str]] = None,
                     what_changed_ref: Optional[str] = None,
                     no_change_reason: Optional[str] = None,
                     live_change_reason: Optional[str] = None,
                     customer_driven: Optional[bool] = None) -> RevisionIntake:
        from app.services.part_service import ChangelogService
        if not await RevisionIntakeService.may_triage(session, user):
            raise IntakeForbidden(
                "Only Development decides the route of a new index "
                "(admins: act as Development)")
        if route not in ROUTES:
            raise IntakeError(f"Unknown route '{route}' - one of {', '.join(ROUTES)}")
        if intake.status == "superseded":
            raise IntakeError("This index was superseded by a newer one: triage that one")
        if intake.status == "rejected":
            raise IntakeError("This index was rejected: it cannot be triaged or activated")
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
        suggested, live = await RevisionIntakeService.suggestion(session, intake)
        v2 = _v2()
        if v2 and route == "administrative" and live is not None:
            # spec §1 / R19: a live change carries the part. Activating the
            # index at once is allowed only with a real reason (not 'ok'),
            # and the live changes' leads are told below
            from app.services.cm_rules import reference_refusal
            why = reference_refusal(
                reason, f"{live.change_number} ({live.status}) carries this part: "
                "the reason to activate the index without it", "title block only")
            if why:
                raise IntakeError(why)
        if v2 and route != "administrative":
            await RevisionIntakeService._what_changed(
                intake, what_changed, what_changed_ref, no_change_reason)
        if v2 and route == "full_ecr" and suggested == "attach_ecr" and live is not None:
            # spec §1: the live change carries the part; full_ecr anyway
            # needs a reason pick
            if live_change_reason not in LIVE_CHANGE_REASONS:
                raise IntakeError(
                    f"{live.change_number} ({live.status}) already carries "
                    f"{(await session.get(Part, intake.part_id)).part_number}: attach the "
                    "index to it, or say why it needs its own change (reason pick: "
                    + ", ".join(f"{k} ({v.lower()})" for k, v in LIVE_CHANGE_REASON_LABELS.items())
                    + "; other needs the reason text)")
            if live_change_reason == "other" and not reason:
                raise IntakeError("Other: say why in the reason")
            intake.live_change_reason = live_change_reason
            reason = reason or LIVE_CHANGE_REASON_LABELS[live_change_reason]
        elif route != suggested and not reason:
            raise IntakeError(
                f"Say why you pick {ROUTE_LABELS[route]} instead of the suggested "
                f"{ROUTE_LABELS.get(suggested, suggested)}")
        rev = await session.get(PartRevision, intake.revision_id)
        part = await session.get(Part, intake.part_id)
        if rev is None or part is None:
            raise IntakeError("The revision of this intake no longer exists")
        if _val(rev.status) == RevisionStatus.REJECTED.value:
            raise IntakeError(
                f"Index {rev.revision_name} was rejected: it cannot be triaged or activated")
        if intake.status == "decided":
            # Re-triage: the dead change lets go of the index first.
            await RevisionIntakeService.unlink_dead_change(
                session, intake, user.id, "the index was triaged again")

        change = None
        if route == "full_ecr":
            change = await RevisionIntakeService._start_full_ecr(
                session, intake, part, rev, user, reason, related=live)
        elif route == "attach_ecr":
            change = await RevisionIntakeService._attach(
                session, intake, part, rev, user, change_id, reason,
                customer_driven=customer_driven)
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
        if v2:
            await RevisionIntakeService._tell_other_live_changes(
                session, intake, part, rev, change, user.id,
                administrative=reason if route == "administrative" else None)
        # Project team (spec §18): a Development backup triaging for the
        # project's Development responsible is recorded as "<backup> for <main>".
        from app.services.project_team_service import ProjectTeamService
        dev_id = (await session.execute(
            select(Department.id).where(Department.name == DEVELOPMENT))).scalar_one_or_none()
        si = await ProjectTeamService.stand_in(session, intake.project_id, dev_id, user.id)
        audit_notes = reason
        if si is not None:
            line = await ProjectTeamService.stand_in_note(session, si, user.id)
            audit_notes = f"{line}: {reason}" if reason else line
        await ChangelogService.log_action(
            session, part_id=part.id, revision_id=rev.id, action="intake_decided",
            action_description=(
                f"Index {rev.revision_name} triaged: {ROUTE_LABELS[route]}"
                + (f" ({change.change_number})" if change is not None else "")
                + (f". Reason: {reason}" if reason else "")),
            performed_by=user.id, new_value=route, notes=audit_notes)
        if route == "administrative":
            await RevisionIntakeService.activate(
                session, rev, user.id, note=f"administrative: {reason}")
        return intake

    @staticmethod
    async def _what_changed(intake: RevisionIntake, areas: Optional[list[str]],
                            ref: Optional[str], no_change_reason: Optional[str]) -> None:
        """Spec §1 "What changed" (required): the areas and a file or compare
        reference, or "no visible change" with a reason."""
        from app.services.cm_rules import reference_refusal
        picked = list(dict.fromkeys(areas or []))
        if not picked:
            raise IntakeError(
                "What changed? Pick the areas (geometry, tolerance, material, "
                "colour/grain, other / not sure) or 'no visible change'")
        if NO_VISIBLE_CHANGE in picked:
            if len(picked) > 1:
                raise IntakeError("'No visible change' stands alone")
            why = (no_change_reason or "").strip()
            if len(why) < 5:
                raise IntakeError("No visible change: say why the customer sent a "
                                  "new index (e.g. title block only)")
            intake.what_changed = [NO_VISIBLE_CHANGE]
            intake.no_change_reason = why[:255]
            intake.what_changed_ref = (ref or "").strip()[:255] or None
            return
        bad = [a for a in picked if a not in WHAT_CHANGED_AREAS]
        if bad:
            raise IntakeError(f"Unknown area: {', '.join(bad)}")
        refusal = reference_refusal(ref, "What changed: the file or compare reference")
        if refusal:
            raise IntakeError(refusal)
        intake.what_changed = picked
        intake.what_changed_ref = ref.strip()[:255]
        intake.no_change_reason = None

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
                         rev: PartRevision, user_id: int, *, lead: bool,
                         attach: bool = False,
                         reason: Optional[str] = None,
                         intake: Optional[RevisionIntake] = None) -> None:
        """Link the new index to the change as the part's resulting revision,
        adding the part to the impacted set when it is not there yet.

        ``attach``: the change already existed (attach_ecr). A part it gains
        is an impacted-set edit like any other and gets the same bookkeeping:
        Development's confirmation is cleared (add_impacted_item), the title
        follows the set, and from 'quoted' on the scope change is flagged and
        costing reopened for the departments whose objects moved. A new
        customer index is its own reason. From implementation on the set is
        frozen (IMPACT_LOCKED_STATUSES): the index may still be linked to a
        part the change already carries, never add one."""
        from app.services.change_service import (
            IMPACT_LOCKED_STATUSES, ChangeError, ChangeService)
        from app.services.early_stage_service import EarlyStageService
        await session.refresh(change, ["impacted_items"])
        item = next((i for i in change.impacted_items if i.part_id == part.id), None)
        before = None
        edited = False
        replaced: Optional[str] = None
        if item is not None:
            if item.resulting_revision_id not in (None, rev.id):
                other = await session.get(PartRevision, item.resulting_revision_id)
                replaced = await RevisionIntakeService._supersede_in_change(
                    session, change, part, item, other, rev, intake, user_id)
                if replaced is None:
                    raise IntakeError(
                        f"{part.part_number} already carries revision "
                        f"{other.revision_name if other else item.resulting_revision_id} in "
                        f"{change.change_number}: a second new revision of the same part "
                        f"cannot ride on it")
            elif attach and intake is not None and _v2():
                # the part was on the change on its active index: D replaces it
                active_rev = (await session.get(PartRevision, part.active_revision_id)
                              if part.active_revision_id else None)
                replaced = item.eng_level_before or (
                    active_rev.revision_name if active_rev else None)
        elif change.status in IMPACT_LOCKED_STATUSES:
            raise IntakeError(
                f"{change.change_number} is '{change.status}': its impacted items "
                f"are frozen, so {part.part_number} cannot join it. Start a full "
                f"ECR instead")
        else:
            why = (reason or "").strip() or (
                f"New customer index {rev.revision_name} of {part.part_number}")
            try:
                if attach:
                    before = await EarlyStageService.begin_impact_edit(
                        session, change, why)
                item = await ChangeService.add_impacted_item(
                    session, change, part.id, user_id,
                    is_lead=lead and change.status in SCOPING_STATUSES,
                    eng_level_before=None)
            except ChangeError as e:
                raise IntakeError(str(e))
            edited = attach
        active = (await session.get(PartRevision, part.active_revision_id)
                  if part.active_revision_id else None)
        if item.eng_level_before is None and active is not None:
            item.eng_level_before = active.revision_name
        item.resulting_revision_id = rev.id
        rev.originating_change_id = change.id
        await session.flush()
        if edited:
            await EarlyStageService.finish_impact_edit(
                session, change, user_id, why, before, [part.id])
        await ChangeService.append_changelog(
            session, change, "intake_linked",
            f"New customer index {rev.revision_name} of {part.part_number} linked "
            f"as the resulting revision", user_id,
            new_value={"part_id": part.id, "revision_id": rev.id})
        if change.status == "in_implementation":
            await ChangeService._ensure_check_workflow(session, change, item, user_id)
        if replaced is not None and intake is not None:
            # spec §1: on an impacted item "what changed" drives the follow-up
            from app.services.index_followup_service import IndexFollowupService
            await IndexFollowupService.on_new_index(
                session, change, intake, part.id, replaced, rev.revision_name, user_id)

    @staticmethod
    async def _supersede_in_change(session: AsyncSession, change: ChangeRequest,
                                   part: Part, item: ChangeImpactedItem,
                                   old: Optional[PartRevision], rev: PartRevision,
                                   intake: Optional[RevisionIntake],
                                   user_id: int) -> Optional[str]:
        """Minimal C11 (SCOPING_V2): the newer index D supersedes, inside the
        change, what the part carried there: a pending customer index of this
        change (its intake superseded, the revision archived) or the internal
        minor the change spawned (its check workflow cancelled, archived).
        Returns the replaced revision's name, or None when it may not be
        replaced (anything else, the switch off, validation onward)."""
        if old is None or not _v2() or change.status in ATTACH_REFUSED:
            return None
        from app.services.change_service import ChangeService
        from app.services.part_service import ChangelogService
        old_intake = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.revision_id == old.id)
        )).scalar_one_or_none()
        pending_here = (old_intake is not None and old_intake.activated_at is None
                        and old_intake.change_id == change.id)
        internal_minor = (old.source == "internal"
                          and old.originating_change_id == change.id)
        if not (pending_here or internal_minor):
            return None
        if pending_here:
            old_intake.status = "superseded"
            old_intake.superseded_by_id = intake.id if intake is not None else None
        if internal_minor:
            from app.models.workflow import WfInstance
            from app.services.workflow_service import WorkflowService
            for inst in (await session.execute(select(WfInstance).where(
                    WfInstance.part_revision_id == old.id,
                    WfInstance.status == "active"))).scalars().all():
                await WorkflowService.cancel_workflow(
                    session, inst.id, user_id,
                    reason=f"Index {rev.revision_name} replaced {old.revision_name}")
        old.status = RevisionStatus.ARCHIVED.value
        item.resulting_revision_id = None
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=part.id, revision_id=old.id, action="intake_replaced",
            action_description=(f"{old.revision_name} replaced by the newer index "
                                f"{rev.revision_name} in {change.change_number} (archived)"),
            performed_by=user_id)
        await ChangeService.append_changelog(
            session, change, "intake_replaced",
            f"Index {rev.revision_name} replaces {old.revision_name} of {part.part_number}",
            user_id, new_value={"part_id": part.id, "old_revision_id": old.id,
                                "revision_id": rev.id})
        return old.revision_name

    @staticmethod
    async def _start_full_ecr(session: AsyncSession, intake: RevisionIntake, part: Part,
                              rev: PartRevision, user: User,
                              reason: Optional[str],
                              related: Optional[ChangeRequest] = None) -> ChangeRequest:
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
        if _v2():
            await RevisionIntakeService._hand_over(session, change, intake, part, rev,
                                                   user, related)
            # C9 (spec §1): handed over: the lead schedules scoping while
            # Sales sets the quote deadline (an incomplete capture is logged,
            # not overridden; the deadline is owed before assessment; no lead
            # yet: Project Management's scoping row picks one)
            await ChangeService.transition(
                session, change, "scoping", user.id,
                logged_rules=("capture_incomplete",))
        return change

    @staticmethod
    async def _hand_over(session: AsyncSession, change: ChangeRequest,
                         intake: RevisionIntake, part: Part, rev: PartRevision,
                         user: User, related: Optional[ChangeRequest]) -> None:
        """C9 (spec §1 full_ecr): the customer's files linked (by reference,
        kind customer_file), the Sales owner set by create_change (the
        project's Sales contact), the related live change linked both ways,
        and the Sales owner and the lead told once: set the quote deadline,
        schedule scoping."""
        from app.models.change import ChangeAttachment
        from app.services.change_people import department_members_of_change_org
        from app.services.change_service import ChangeService
        from app.services.notification_service import NotificationService
        files = (await session.execute(select(RevisionFile).where(
            RevisionFile.revision_id == rev.id,
            RevisionFile.is_deleted.is_(False)).order_by(RevisionFile.id))).scalars().all()
        for f in files:
            session.add(ChangeAttachment(
                change_id=change.id, filename=f.filename[:255], stored_path=f.file_path,
                content_type=f.mime_type or "application/octet-stream",
                size_bytes=f.file_size or 0, sha256=f.file_hash or "",
                phase="baseline", kind="customer_file", uploaded_by=user.id))
        if related is not None:
            change.related_change_id = related.id
            change.description = (
                f"{change.description}\nRelated: {related.change_number} ({related.status}) "
                f"also carries {part.part_number}"
                + (f"; own change because: {LIVE_CHANGE_REASON_LABELS.get(intake.live_change_reason, intake.live_change_reason)}"
                   if intake.live_change_reason else ""))
            if related.related_change_id is None:
                related.related_change_id = change.id
            await ChangeService.append_changelog(
                session, related, "related_change",
                f"{change.change_number} started beside it for index "
                f"{rev.revision_name} of {part.part_number}", user.id,
                new_value={"related_change_id": change.id})
        await session.flush()
        if files:
            await ChangeService.append_changelog(
                session, change, "attachment_added",
                f"{len(files)} customer file(s) of index {rev.revision_name} linked",
                user.id, new_value={"revision_id": rev.id,
                                    "filenames": [f.filename for f in files]})
        ids = [change.sales_owner_id] if change.sales_owner_id else []
        if not ids:
            sales = (await session.execute(select(Department.id).where(
                Department.name == "Sales"))).scalar_one_or_none()
            if sales is not None:
                ids = await department_members_of_change_org(session, change, [sales])
        title = (f"New customer index {rev.revision_name} on {part.part_number}: "
                 f"set the quote deadline, kick off ({change.change_number})")[:255]
        await NotificationService.notify_once(
            session, [i for i in ids if i != user.id], kind="intake_handover",
            subject_key=f"intake_handover:{change.id}", title=title,
            body="Sales: set the quote deadline. Lead: schedule scoping.",
            link=f"/changes/{change.id}")
        if change.lead_id not in (None, user.id) and change.lead_id not in ids:
            await NotificationService.notify_once(
                session, [change.lead_id], kind="intake_handover",
                subject_key=f"intake_handover:{change.id}", title=title,
                body="Lead: schedule scoping. Sales sets the quote deadline.",
                link=f"/changes/{change.id}")

    @staticmethod
    async def _attach(session: AsyncSession, intake: RevisionIntake, part: Part,
                      rev: PartRevision, user: User,
                      change_id: Optional[int],
                      reason: Optional[str] = None,
                      customer_driven: Optional[bool] = None) -> ChangeRequest:
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
        from app.services import mother_plants as mp
        internal = (_v2() and not change.customer_relevant
                    and not mp.is_mother_plant(change)
                    and change.origin != "engineering_review")
        if internal and customer_driven is None:
            raise IntakeError(
                f"{change.change_number} is an internal change: is the new index "
                "customer-driven? (yes for a customer drawing: it becomes a "
                "customer change)")
        await RevisionIntakeService._link_item(session, change, part, rev, user.id,
                                               lead=False, attach=True, reason=reason,
                                               intake=intake)
        await ChangeService.append_changelog(
            session, change, "intake_attached",
            f"Index {rev.revision_name} of {part.part_number} attached from the intake",
            user.id, new_value={"intake_id": intake.id})
        if internal:
            intake.customer_driven = bool(customer_driven)
            if customer_driven:
                from app.services.ppap_decision_service import PpapDecisionService
                await PpapDecisionService.flip(
                    session, change, user.id,
                    f"customer index {rev.revision_name} of {part.part_number}")
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
                        RevisionIntake.status.notin_(CLOSED_STATUSES))
        q = RevisionIntakeService._org_scope(q, user)
        return list((await session.execute(
            q.order_by(RevisionIntake.id.desc()))).scalars().all())

    @staticmethod
    async def out(session: AsyncSession, intake: RevisionIntake,
                  can_triage: bool = False,
                  live_rows: Optional[dict] = None) -> dict:
        """One intake as the API shows it. `live_rows`: live_change_rows for
        a whole list (one query), else read for this intake."""
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
        needs_triage = intake.status == "pending" or retriage
        suggested, live, others = intake.suggested_route, None, []
        if needs_triage:
            # spec §1: a live change carrying the part is the suggestion; the
            # others carrying it are named too
            exclude = intake.change_id if intake.status == "decided" else None
            if not _v2():
                lives = []
            elif live_rows is not None:
                lives = [c for c in live_rows.get((intake.part_id, intake.project_id), [])
                         if c.id != exclude]
            else:
                lives = await RevisionIntakeService.live_changes_for_part(
                    session, intake.part_id, intake.project_id, exclude_id=exclude)
            suggested, live = await RevisionIntakeService.suggestion(
                session, intake, lives)
            others = [c for c in lives if live is None or c.id != live.id]
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
            "suggested_route": suggested,
            "phase_route": intake.suggested_route,
            "live_change": ({
                "id": live.id, "change_number": live.change_number,
                "title": live.title, "status": live.status,
                "lead_name": live.lead_name,
                "customer_relevant": live.customer_relevant,
                "attachable": live.status not in ATTACH_REFUSED,
            } if live is not None else None),
            # every other live change carrying the part (their leads are told
            # at triage)
            "other_live_changes": [{
                "id": c.id, "change_number": c.change_number, "status": c.status,
                "lead_name": c.lead_name,
            } for c in others],
            "what_changed": intake.what_changed or [],
            "what_changed_ref": intake.what_changed_ref,
            "no_change_reason": intake.no_change_reason,
            "live_change_reason": intake.live_change_reason,
            "replaced_revision": intake.replaced_revision,
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
            "scoping_v2": _v2(),
            "needs_triage": needs_triage,
            "can_decide": can_triage and needs_triage,
        }

    @staticmethod
    async def my(session: AsyncSession, user: User) -> dict:
        """My Tasks: "Triage index <x> of <part>" for Development, and the
        engineering-review answers owed by the caller's departments."""
        from app.services.engineering_review_service import EngineeringReviewService
        from app.services.project_team_service import TeamRoles
        team = TeamRoles(session, user.id)
        triage = []
        can = await RevisionIntakeService.may_triage(session, user)
        if can:
            for i in await RevisionIntakeService.list(session, user, waiting=True):
                if i.status not in ("pending", "decided"):
                    continue
                row = await RevisionIntakeService.out(session, i, True)
                if not row["needs_triage"]:
                    continue
                # Project team (spec §18): Development's responsible on the
                # part's project is main; other Development members backup.
                role, main = await team.role(
                    i.project_id, await team.department_id(DEVELOPMENT))
                row["role"], row["main_name"] = role, main
                triage.append(row)
        reviews = await EngineeringReviewService.my_open_answers(session, user)
        for r in reviews:
            role, main = await team.role(r.get("project_id"), r["department_id"])
            r["role"], r["main_name"] = role, main
        return {"triage": triage, "review": reviews}
