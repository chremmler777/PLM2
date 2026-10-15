"""Start at risk (ECR-solid spec §7a; P8 decided: yes, urgent only; switch
START_AT_RISK, default ON).

An urgent customer change may start before the customer's PO: Sales (or the
run team) files the customer's go-ahead, Quality adds one line of quality
risks, and a Project Management member (who sees prices; second: an admin)
approves it, never the one who asked. The change goes to 'approved' with the
price open (`price_open`): Send offer / supplement and the Customer answer
stay available, the customer's acceptance or an Absorb clears it, and close
is HARD-blocked until then (#9). PM and Quality sign-off rows come at once,
bound to the last offer sent (else the costing at approval); release checks
them (HARD #9).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAttachment, ChangeRequest
from app.models.entities import User
from app.models.workflow import Department
from app.services import cm_switches
from app.services.change_service import ChangeError, ChangeService

#: Where a change may start at risk: costing closed or the quote out, no yes.
START_STATUSES = ("costing", "quoting", "quoted")
#: The soft rules the start passes, named in the changelog (the PM member's
#: approval is the decision; the price stays open).
LOGGED_RULES = ("costing_not_finalized", "scope_change_uncovered", "price_drop")


class StartAtRiskForbidden(ChangeError):
    """The caller may not do this: 403."""


def started(change: ChangeRequest) -> bool:
    return change.start_at_risk_approved_at is not None


def refusal(change: ChangeRequest) -> Optional[str]:
    """Why this change cannot start at risk now (None: it can be asked)."""
    if not cm_switches.on("START_AT_RISK"):
        return "Start at risk is switched off: no start before the PO"
    if not change.customer_relevant:
        return "An internal change is approved internally, not started at risk"
    if change.priority != "critical":
        return "Start at risk is for urgent changes only (P8)"
    if change.status not in START_STATUSES:
        return ("Start at risk is asked once costing runs and until the "
                f"customer's yes; this change is '{change.status}'")
    if change.customer_response == "accepted":
        return "The customer accepted: approve it the normal way"
    return None


class StartAtRiskService:

    @staticmethod
    async def _member(session: AsyncSession, user: User, name: str) -> bool:
        from app.services.early_stage_service import EarlyStageService
        return await EarlyStageService._member_of(session, user, name)

    @staticmethod
    async def request(session: AsyncSession, change: ChangeRequest, user: User, *,
                      attachment_id: Optional[int] = None,
                      ref: Optional[str] = None) -> ChangeRequest:
        """Sales or the run team file the customer's go-ahead."""
        why = refusal(change)
        if why:
            raise ChangeError(why)
        if started(change):
            raise ChangeError("This change already started at risk")
        from app.services.early_stage_service import EarlyStageService
        roles = await EarlyStageService._roles(session, change, user)
        if not (roles["sales"] or roles["run_team"]):
            raise StartAtRiskForbidden(
                "Sales or the run team ask to start at risk")
        if attachment_id:
            att = await session.get(ChangeAttachment, int(attachment_id))
            if (att is None or att.change_id != change.id
                    or att.kind not in ("customer_email", "customer_file", "general")):
                raise ChangeError("Pick the customer's mail or file filed on this change")
            evidence = f"Mail: {att.filename}"[:255]
        else:
            from app.services.cm_rules import reference_refusal
            why = reference_refusal(ref, "The customer's go-ahead (a filed mail or its reference)",
                                    "Mail 15 Oct: start tooling now, PO follows")
            if why:
                raise ChangeError(why)
            evidence = ref.strip()[:255]
        change.start_at_risk_evidence = evidence
        change.start_at_risk_requested_by = user.id
        change.start_at_risk_requested_at = datetime.utcnow()
        # a renewed ask needs a fresh Quality line
        change.start_at_risk_quality_note = None
        change.start_at_risk_quality_by = None
        change.start_at_risk_quality_at = None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "start_at_risk_requested",
            f"Start at risk asked: {evidence}", user.id, notes=evidence)
        from app.services.notification_service import NotificationService
        depts = [d for (d,) in (await session.execute(
            select(Department.id).where(Department.name.in_(
                ("Quality", "Project Manager"))))).all()]
        await NotificationService.notify_departments_once(
            session, depts, change=change, kind="decision_needed",
            subject_key=f"start_at_risk:{change.id}:{int(change.start_at_risk_requested_at.timestamp())}",
            title=f"Start at risk asked: Quality line, then PM approval: "
                  f"{change.change_number}"[:255],
            body=evidence, link=f"/changes/{change.id}?tab=offer")
        return change

    @staticmethod
    async def quality_line(session: AsyncSession, change: ChangeRequest, user: User,
                           note: str) -> ChangeRequest:
        """Quality adds one line of quality risks."""
        if change.start_at_risk_requested_at is None or started(change):
            raise ChangeError("No start at risk is waiting for Quality's line")
        if not (await StartAtRiskService._member(session, user, "Quality")
                or user.effective_role == "admin"):
            raise StartAtRiskForbidden("A Quality member adds the quality risks")
        note = " ".join((note or "").split())
        if len(note) < 10:
            raise ChangeError(
                "One line of quality risks (10+ characters), e.g. 'no PPAP before "
                "SOP; first lot 100 % checked'")
        change.start_at_risk_quality_note = note[:500]
        change.start_at_risk_quality_by = user.id
        change.start_at_risk_quality_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "start_at_risk_quality",
            f"Start at risk: quality risks: {change.start_at_risk_quality_note}",
            user.id, notes=change.start_at_risk_quality_note)
        return change

    @staticmethod
    async def approve(session: AsyncSession, change: ChangeRequest,
                      user: User) -> ChangeRequest:
        """A Project Management member (second: an admin), never the asker:
        the change goes to 'approved' with the price open."""
        why = refusal(change)
        if why:
            raise ChangeError(why)
        if change.start_at_risk_requested_at is None:
            raise ChangeError("Nobody asked to start at risk")
        if change.start_at_risk_quality_note is None:
            raise ChangeError("Quality adds its line of quality risks first")
        is_pm = await StartAtRiskService._member(session, user, "Project Manager")
        if not (is_pm or user.effective_role == "admin"):
            raise StartAtRiskForbidden(
                "A Project Management member (who sees the price) approves a start "
                "at risk; second: an admin")
        if user.id == change.start_at_risk_requested_by:
            raise StartAtRiskForbidden(
                "The one who asked does not approve the start at risk (4-eyes)")
        now = datetime.utcnow()
        change.start_at_risk_approved_by = user.id
        change.start_at_risk_approved_at = now
        if not change.price_open:
            change.price_open = True
            await ChangeService.append_changelog(
                session, change, "price_opened",
                "Started at risk: the price is open until the customer accepts "
                "an offer or the money is absorbed", user.id,
                field_name="price_open", old_value=False, new_value=True)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "start_at_risk_approved",
            f"Start at risk approved: {change.start_at_risk_evidence}; quality "
            f"risks: {change.start_at_risk_quality_note}", user.id)
        await ChangeService.transition(
            session, change, "approved", user.id,
            reason="Started at risk (§7a): the customer's go-ahead, no PO yet",
            logged_rules=LOGGED_RULES)
        return change

    @staticmethod
    async def state(session: AsyncSession, change: ChangeRequest) -> dict:
        from app.services.change_plan_service import ChangePlanService
        names = await ChangePlanService._user_names(session, [
            change.start_at_risk_requested_by, change.start_at_risk_quality_by,
            change.start_at_risk_approved_by])
        return {
            "available": refusal(change) is None and not started(change),
            "refusal": refusal(change) if not started(change) else None,
            "evidence": change.start_at_risk_evidence,
            "requested_by_name": names.get(change.start_at_risk_requested_by),
            "requested_by": change.start_at_risk_requested_by,
            "requested_at": change.start_at_risk_requested_at,
            "quality_note": change.start_at_risk_quality_note,
            "quality_by_name": names.get(change.start_at_risk_quality_by),
            "approved_by_name": names.get(change.start_at_risk_approved_by),
            "approved_at": change.start_at_risk_approved_at,
            "price_open": change.price_open,
        }
