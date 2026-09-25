"""Engineering review: the light track for a new customer index (spec
2026-09-25 §17), origin "engineering_review". Reuses the side-track pattern
of the mother-plant changes (§14).

    captured -> scoping (Development locks the impact) -> review -> released
    -> closed

- The triage (Development) starts it straight at scoping, lead item = the
  part, the pending index as the item's resulting revision.
- Locking the impact opens the review: the departments serving the locked
  parts are asked (tools -> Tool Engineer, stations and EOAT ->
  Manufacturing Engineer, gauges -> APQP), always Packaging Engineer for
  articles (no packaging category exists) and Development.
- Each answers "no impact" or "impact" with a note (a note is required for
  "impact").
- Every answer "no impact": the pending revision is activated and the
  change is released and closed, at once.
- Any "impact": Development escalates it to a full ECR (one click,
  audited): the change becomes a customer change in scoping, the review
  answers stay as the scoping input.

No costing, offer or timing: those statuses are refused (review_refusal).
Refusals: ChangeError (400), ReviewForbidden (403), ReviewNotFound (404).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest
from app.models.entities import User
from app.models.part import Part, PartRevision
from app.models.revision_intake import REVIEW_ANSWERS, ChangeReviewAnswer, RevisionIntake
from app.models.workflow import Department, UserDepartment

logger = logging.getLogger(__name__)

ORIGIN = "engineering_review"
# Statuses the review may still take; everything else is the full ECR's.
REVIEW_STATUSES = ("captured", "scoping", "released", "closed", "rejected",
                   "cancelled", "on_hold")
ANSWER_LABELS = {"no_impact": "No impact", "impact": "Impact"}
# Served object category -> the department that answers for it.
DEPARTMENT_BY_CATEGORY = {
    "tool": "Tool Engineer",
    "assembly_equipment": "Manufacturing Engineer",
    "eoat": "Manufacturing Engineer",
    "gauge": "APQP",
}
PACKAGING = "Packaging Engineer"
DEVELOPMENT = "Development"
# The order the review lists its departments in.
ORDER = (DEVELOPMENT, "Tool Engineer", "Manufacturing Engineer", "APQP", PACKAGING)


class ReviewForbidden(PermissionError):
    """Mapped to HTTP 403."""


class ReviewNotFound(LookupError):
    """Mapped to HTTP 404."""


def is_review(change) -> bool:
    return getattr(change, "origin", None) == ORIGIN


def review_refusal(change, to_status: str) -> Optional[str]:
    """The hard rule: an engineering review never enters assessment,
    costing, quote or implementation. Shared by transition() and the button
    offer (EarlyStageService.hard_refusal)."""
    if is_review(change) and to_status not in REVIEW_STATUSES:
        return ("An engineering review is released by its review answers; "
                "escalate it to a full ECR for assessment, costing and quote")
    if (is_review(change) and to_status == "released"):
        return "An engineering review is released when every department answered \"no impact\""
    return None


class EngineeringReviewService:

    # ------------------------------------------------------------------
    # Start (from the triage)
    # ------------------------------------------------------------------
    @staticmethod
    async def start(session: AsyncSession, intake: RevisionIntake, part: Part,
                    rev: PartRevision, user: User,
                    reason: Optional[str]) -> ChangeRequest:
        from app.services.change_service import ChangeService
        from app.services.revision_intake_service import RevisionIntakeService
        change = await ChangeService.create_change(
            session, project_id=intake.project_id,
            title=f"Engineering review index {rev.revision_name}: {part.part_number} {part.name}"[:255],
            change_type="physical_part", raised_by=user.id,
            reason=reason or "New customer index, engineering review",
            description=RevisionIntakeService._description(intake, part, rev, reason),
            customer_relevant=False, lead_id=user.id)
        change.origin = ORIGIN
        await RevisionIntakeService._link_item(session, change, part, rev, user.id, lead=True)
        change.status = "scoping"
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "status_changed",
            "captured -> scoping (engineering review from the intake)", user.id,
            field_name="status", old_value="captured", new_value="scoping")
        await ChangeService.append_changelog(
            session, change, "intake_started",
            f"Engineering review started from the intake of index {rev.revision_name} "
            f"({part.part_number})", user.id, new_value={"intake_id": intake.id})
        return change

    # ------------------------------------------------------------------
    # Departments asked
    # ------------------------------------------------------------------
    @staticmethod
    async def department_names(session: AsyncSession, part_ids: list[int]) -> list[str]:
        from app.services.change_service import ChangeService
        by_category = await ChangeService.served_objects(session, part_ids)
        names = {DEVELOPMENT}
        for category in by_category:
            if category in DEPARTMENT_BY_CATEGORY:
                names.add(DEPARTMENT_BY_CATEGORY[category])
        if "article" in by_category:
            names.add(PACKAGING)
        return [n for n in ORDER if n in names]

    @staticmethod
    async def answers(session: AsyncSession, change: ChangeRequest) -> list[ChangeReviewAnswer]:
        return list((await session.execute(
            select(ChangeReviewAnswer).where(ChangeReviewAnswer.change_id == change.id)
            .order_by(ChangeReviewAnswer.id))).scalars().all())

    @staticmethod
    async def on_impact_locked(session: AsyncSession, change: ChangeRequest,
                               user_id: int) -> None:
        """The impact lock opens the review: one answer row per department
        serving the locked set (missing ones added on a re-lock; unanswered
        rows of departments no longer concerned removed)."""
        if not is_review(change) or change.status != "scoping":
            return
        from app.services.change_service import ChangeService
        names = await EngineeringReviewService.department_names(
            session, [i.part_id for i in change.impacted_items])
        depts = {d.name: d for d in (await session.execute(
            select(Department).where(Department.name.in_(names),
                                     Department.is_active.is_(True)))).scalars().all()}
        wanted = [depts[n].id for n in names if n in depts]
        rows = await EngineeringReviewService.answers(session, change)
        have = {r.department_id for r in rows}
        for r in rows:
            if r.department_id not in wanted and r.answer is None:
                await session.delete(r)
        new = [d for d in wanted if d not in have]
        for did in new:
            session.add(ChangeReviewAnswer(change_id=change.id, department_id=did))
        await session.flush()
        if new:
            by_id = {d.id: d.name for d in depts.values()}
            await ChangeService.append_changelog(
                session, change, "review_opened",
                "Engineering review asks " + ", ".join(by_id[d] for d in new), user_id,
                new_value={"department_ids": new})
            members = set((await session.execute(
                select(UserDepartment.user_id).where(
                    UserDepartment.department_id.in_(new)))).scalars().all())
            members.discard(user_id)
            if members:
                from app.services.notification_service import NotificationService
                await NotificationService.notify_once(
                    session, sorted(members), kind="change_review",
                    subject_key=f"change:{change.id}:review",
                    title=f"{change.change_number}: engineering review, impact or no impact?"[:255],
                    body=change.title, link=f"/changes/{change.id}?tab=review")
        await EngineeringReviewService.maybe_release(session, change, user_id)

    # ------------------------------------------------------------------
    # Answer, release, escalate
    # ------------------------------------------------------------------
    @staticmethod
    async def _my_department_ids(session: AsyncSession, user: User) -> set[int]:
        from app.services.workflow_service import WorkflowService
        return set(await WorkflowService.effective_department_ids(session, user))

    @staticmethod
    async def answer(session: AsyncSession, change: ChangeRequest, department_id: int,
                     answer: str, user: User, note: Optional[str] = None) -> ChangeReviewAnswer:
        from app.services.change_service import ChangeError, ChangeService
        if not is_review(change):
            raise ChangeError("This change is not an engineering review")
        if change.status != "scoping" or change.impact_confirmed_at is None:
            raise ChangeError(
                "The review is answered once Development locked the impact, while "
                "the change is in scoping")
        if answer not in REVIEW_ANSWERS:
            raise ChangeError("Answer 'no_impact' or 'impact'")
        row = (await session.execute(
            select(ChangeReviewAnswer).where(
                ChangeReviewAnswer.change_id == change.id,
                ChangeReviewAnswer.department_id == department_id))).scalar_one_or_none()
        if row is None:
            raise ReviewNotFound("This department is not asked in this review")
        if (user.effective_role != "admin"
                and department_id not in await EngineeringReviewService._my_department_ids(session, user)):
            raise ReviewForbidden("Only a member of the asked department may answer for it")
        note = (note or "").strip() or None
        if answer == "impact" and not note:
            raise ChangeError("Say what the impact is: a note is required")
        old = row.answer
        row.answer = answer
        row.note = note
        row.answered_by = user.id
        row.answered_at = datetime.utcnow()
        await session.flush()
        dept = await session.get(Department, department_id)
        await ChangeService.append_changelog(
            session, change, "review_answered",
            f"{dept.name if dept else department_id}: {ANSWER_LABELS[answer]}"
            + (f" ({note})" if note else ""), user.id, notes=note,
            old_value={"answer": old} if old else None,
            new_value={"department_id": department_id, "answer": answer})
        await EngineeringReviewService.maybe_release(session, change, user.id)
        return row

    @staticmethod
    async def maybe_release(session: AsyncSession, change: ChangeRequest,
                            user_id: int) -> bool:
        """Every department answered "no impact": activate and close."""
        if not is_review(change) or change.status != "scoping" \
                or change.impact_confirmed_at is None:
            return False
        rows = await EngineeringReviewService.answers(session, change)
        if not rows or any(r.answer != "no_impact" for r in rows):
            return False
        await EngineeringReviewService._release_and_close(session, change, user_id)
        return True

    @staticmethod
    async def _release_and_close(session: AsyncSession, change: ChangeRequest,
                                 user_id: int) -> None:
        from app.services.change_service import ChangeService
        from app.services.revision_intake_service import RevisionIntakeService
        activated = []
        await session.refresh(change, ["impacted_items"])
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
                continue
            rev = await session.get(PartRevision, item.resulting_revision_id)
            if rev is None:
                continue
            await RevisionIntakeService.activate(
                session, rev, user_id,
                note=f"engineering review {change.change_number}, no impact", change=change)
            item.eng_level_after = rev.revision_name
            activated.append(rev.revision_name)
        now = datetime.utcnow()
        change.released_at = now
        change.released_by = user_id
        change.status = "released"
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "review_released",
            "Every department answered no impact: "
            + (f"index {', '.join(activated)} activated" if activated else "nothing to activate"),
            user_id, new_value={"activated": activated})
        await ChangeService.append_changelog(
            session, change, "status_changed", "scoping -> released (engineering review)",
            user_id, field_name="status", old_value="scoping", new_value="released")
        change.status = "closed"
        change.closed_at = now
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "status_changed", "released -> closed (engineering review)",
            user_id, field_name="status", old_value="released", new_value="closed")

    @staticmethod
    async def escalate(session: AsyncSession, change: ChangeRequest, user: User,
                       note: Optional[str] = None) -> ChangeRequest:
        """One click by Development, audited: the review becomes a full ECR
        (customer change) in scoping; the answers stay as its input."""
        from app.services.change_service import ChangeError, ChangeService
        if not is_review(change):
            raise ChangeError("This change is not an engineering review")
        if not await ChangeService._user_in_department(session, user, DEVELOPMENT):
            raise ReviewForbidden(
                "Only Development escalates a review to a full ECR (admins: act as Development)")
        if change.status not in ("captured", "scoping"):
            raise ChangeError("Only an open review (captured or scoping) can be escalated")
        rows = await EngineeringReviewService.answers(session, change)
        impacts = [r for r in rows if r.answer == "impact"]
        note = (note or "").strip() or None
        if not impacts and not note:
            raise ChangeError(
                "No department reported an impact: say why the review becomes a full ECR")
        names = dict((await session.execute(select(Department.id, Department.name))).all())
        summary = "; ".join(f"{names.get(r.department_id, r.department_id)}: {r.note}"
                            for r in impacts)
        change.origin = "customer"
        change.customer_relevant = True
        now = datetime.utcnow()
        for intake in (await session.execute(
                select(RevisionIntake).where(RevisionIntake.change_id == change.id))).scalars():
            intake.escalated_at = now
            intake.escalated_by = user.id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "review_escalated",
            "Escalated to a full ECR" + (f": {note}" if note else "")
            + (f". Impact reported by {summary}" if summary else ""),
            user.id, notes=note, field_name="origin",
            old_value={"origin": ORIGIN}, new_value={"origin": "customer",
                                                     "impacts": summary or None})
        return change

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def state(session: AsyncSession, change: ChangeRequest, user: User) -> dict:
        """The Review tab: departments with their answers and objects, and
        the caller's rights. Kept readable after an escalation (the review is
        the scoping input then)."""
        from app.services.change_service import ChangeService
        rows = await EngineeringReviewService.answers(session, change)
        names = dict((await session.execute(select(Department.id, Department.name))).all())
        mine = await EngineeringReviewService._my_department_ids(session, user)
        is_admin = user.effective_role == "admin"
        open_review = is_review(change) and change.status == "scoping" \
            and change.impact_confirmed_at is not None
        by_category = await ChangeService.served_objects(
            session, [i.part_id for i in change.impacted_items])
        objects_by_dept: dict[str, list[dict]] = {}
        for category, pairs in by_category.items():
            dept = DEPARTMENT_BY_CATEGORY.get(category) or (
                DEVELOPMENT if category == "article" else None)
            for part, via in pairs:
                for d in ([dept] if dept else []) + ([PACKAGING] if category == "article" else []):
                    objects_by_dept.setdefault(d, []).append({
                        "id": part.id, "number": part.part_number, "name": part.name,
                        "item_category": part.item_category, "via_part_id": via})
        intake = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.change_id == change.id)
            .order_by(RevisionIntake.id.desc()).limit(1))).scalar_one_or_none()
        revisions = []
        for item in change.impacted_items:
            if item.resulting_revision_id:
                rev = await session.get(PartRevision, item.resulting_revision_id)
                part = await session.get(Part, item.part_id)
                if rev is not None:
                    revisions.append({
                        "part_id": item.part_id,
                        "part_number": part.part_number if part else None,
                        "revision_id": rev.id, "revision_name": rev.revision_name,
                        "status": rev.status.value if hasattr(rev.status, "value") else rev.status,
                        "active": part is not None and part.active_revision_id == rev.id})
        may_escalate = await ChangeService._user_in_department(session, user, DEVELOPMENT)
        return {
            "change_id": change.id,
            "is_review": is_review(change),
            "escalated": intake is not None and intake.escalated_at is not None,
            "escalated_at": intake.escalated_at if intake else None,
            "impact_locked": change.impact_confirmed_at is not None,
            "open": open_review,
            "answers": [{
                "id": r.id, "department_id": r.department_id,
                "department_name": names.get(r.department_id),
                "answer": r.answer,
                "answer_label": ANSWER_LABELS.get(r.answer) if r.answer else None,
                "note": r.note, "answered_by_name": r.answered_by_name,
                "answered_at": r.answered_at,
                "objects": objects_by_dept.get(names.get(r.department_id), []),
                "can_answer": open_review and (is_admin or r.department_id in mine),
            } for r in rows],
            "open_count": sum(1 for r in rows if r.answer is None),
            "impact_count": sum(1 for r in rows if r.answer == "impact"),
            "revisions": revisions,
            "intake_id": intake.id if intake else None,
            "can_escalate": (is_review(change) and change.status in ("captured", "scoping")
                             and may_escalate),
        }

    @staticmethod
    async def my_actions(session: AsyncSession, change: ChangeRequest, user: User,
                         dept_ids: set) -> list[dict]:
        if not is_review(change) or change.status != "scoping":
            return []
        out: list[dict] = []
        rows = await EngineeringReviewService.answers(session, change)
        if change.impact_confirmed_at is not None:
            names = dict((await session.execute(select(Department.id, Department.name))).all())
            for r in rows:
                if r.answer is None and r.department_id in dept_ids:
                    out.append({"kind": "review_answer",
                                "label": f"Answer the engineering review for "
                                         f"{names.get(r.department_id, r.department_id)}",
                                "target_tab": "review", "department_id": r.department_id})
        if any(r.answer == "impact" for r in rows):
            from app.services.change_service import ChangeService
            if await ChangeService._user_in_department(session, user, DEVELOPMENT):
                out.append({"kind": "review_escalate",
                            "label": "Impact reported: escalate to a full ECR",
                            "target_tab": "review"})
        return out

    @staticmethod
    async def my_open_answers(session: AsyncSession, user: User) -> list[dict]:
        """My Tasks: open review answers of the caller's departments."""
        dept_ids = await EngineeringReviewService._my_department_ids(session, user)
        if not dept_ids:
            return []
        from app.services.change_service import _org_scope
        q = select(ChangeRequest).where(
            ChangeRequest.origin == ORIGIN, ChangeRequest.status == "scoping",
            ChangeRequest.impact_confirmed_at.is_not(None),
            ChangeRequest.id.in_(select(ChangeReviewAnswer.change_id).where(
                ChangeReviewAnswer.department_id.in_(dept_ids),
                ChangeReviewAnswer.answer.is_(None))))
        changes = (await session.execute(_org_scope(q, user))).scalars().all()
        names = dict((await session.execute(select(Department.id, Department.name))).all())
        out = []
        for c in changes:
            for r in await EngineeringReviewService.answers(session, c):
                if r.answer is None and r.department_id in dept_ids:
                    out.append({"change_id": c.id, "change_number": c.change_number,
                                "title": c.title, "department_id": r.department_id,
                                "department_name": names.get(r.department_id)})
        return out
