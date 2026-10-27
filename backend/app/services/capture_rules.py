"""Capture and the urgent path (ECR-solid spec §2, §3 "Urgent"; switch
SCOPING_V2).

- Customer change complete: a typed customer file (kind customer_file, or
  a filed customer mail) and the quote deadline.
- Internal change complete: description, one evidence file or photo, and
  "what is wrong today" as a number with its unit, with the target.
- Urgent (priority 'critical'): the need-by date (release_due_date) and a
  reason pick (URGENT_REASONS); refused without them. Evidence is optional
  since the PM captures (Christoph 2026-10-27).
  Mother-plant changes keep their own SOP and are left out.
- Urgent proceed: "Need-by realistic? yes / only with start at risk / no
  (proposed date)"; on a customer change anything but yes gives Sales "Tell
  customer: new date or start at risk?" at once (need_by_open), answered
  with a mail or reference. An internal change has no customer and no Sales
  owner: 'no' is recorded and its lead (else raiser) is told; start at
  risk (a customer go-ahead, §7a) is not offered.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeAttachment, ChangeRequest, NEED_BY_CHECKS, URGENT_REASONS,
)
from app.services import cm_switches

#: Attachment kinds that are the customer's own files.
CUSTOMER_FILE_KINDS = ("customer_file", "customer_email")
URGENT_REASON_LABELS = {
    "line_stop": "Customer line stop / down", "safety": "Safety",
    "quality_escape": "Quality escape", "launch_date": "Launch date at risk",
    "customer_demand": "Customer demand", "other": "Other",
}


def v2() -> bool:
    return cm_switches.on("SCOPING_V2")


def _plain(change: ChangeRequest) -> bool:
    """A customer or internal change of ours (not a mother-plant change,
    not an engineering review)."""
    from app.services import mother_plants as mp
    return (not mp.is_mother_plant(change)
            and getattr(change, "origin", None) != "engineering_review")


def is_urgent(change: ChangeRequest) -> bool:
    return getattr(change, "priority", None) == "critical"


def urgent_refusal(change: ChangeRequest) -> Optional[str]:
    """Why this urgent change is not complete, or None (switch on only)."""
    if not cm_switches.on("SCOPING_V2") or not is_urgent(change) or not _plain(change):
        return None
    if change.release_due_date is None:
        return "Urgent: set the need-by date"
    if change.release_due_date.date() < datetime.utcnow().date():
        return (f"Urgent: the need-by date ({change.release_due_date:%d %b}) is in "
                "the past: pick today or a later date")
    if change.urgent_reason not in URGENT_REASONS:
        return ("Urgent: pick the reason (line stop, safety, quality escape, "
                "launch date, customer demand, other)")
    return None


async def missing(session: AsyncSession, change: ChangeRequest) -> list[str]:
    """The §2 parts of a complete capture kickoff_missing adds (switch on):
    the customer file of a customer change, the problem and target of an
    internal one, the urgent need-by and reason."""
    if not cm_switches.on("SCOPING_V2") or not _plain(change):
        return []
    out: list[str] = []
    if change.customer_relevant:
        typed = (await session.execute(
            select(func.count()).select_from(ChangeAttachment).where(
                ChangeAttachment.change_id == change.id,
                ChangeAttachment.kind.in_(CUSTOMER_FILE_KINDS)))).scalar() or 0
        if not typed:
            out.append("customer file")
    else:
        if change.problem_value is None or not (change.problem_unit or "").strip():
            out.append("what is wrong today")
        if change.target_value is None:
            out.append("target")
    if is_urgent(change):
        if change.release_due_date is None:
            out.append("need-by date")
        if change.urgent_reason not in URGENT_REASONS:
            out.append("urgent reason")
    return out


def need_by_open(change: ChangeRequest) -> bool:
    """Sales owes "Tell customer: new date or start at risk?" (customer
    changes only)."""
    return (cm_switches.on("SCOPING_V2") and bool(change.customer_relevant)
            and change.need_by_check in ("at_risk", "no")
            and change.need_by_told_at is None
            and change.status not in ("closed", "cancelled", "rejected"))


def _goes_on_as_customer(change: ChangeRequest) -> bool:
    """The cost carrier proceed goes on with (the open meeting's pick)."""
    from app.services.ppap_decision_service import carrier
    return carrier(change) == "customer"


def need_by_refusal(change: ChangeRequest, answer: Optional[str],
                    proposed: Optional[datetime]) -> Optional[str]:
    """Why the urgent proceed's "Need-by realistic?" answer is missing or
    incomplete, or None (switch off, not urgent, a mother-plant change)."""
    if not cm_switches.on("SCOPING_V2") or not is_urgent(change) or not _plain(change):
        return None
    customer = _goes_on_as_customer(change)
    # start at risk exists only for a customer change with §7a switched on;
    # off, nothing starts before the PO
    at_risk = customer and cm_switches.on("START_AT_RISK")
    allowed = NEED_BY_CHECKS if at_risk else ("yes", "no")
    if answer not in allowed:
        due = change.release_due_date.strftime("%d %b") if change.release_due_date else "-"
        return (f"Urgent: is the need-by date ({due}) realistic? Answer yes, "
                + ("only with start at risk, " if at_risk else "")
                + "or no with a proposed date"
                + ("" if at_risk or not customer else " (no start before PO)"))
    if answer == "no" and proposed is None:
        return "Need-by not realistic: propose a date"
    if answer == "no":
        floor = datetime.utcnow().date()
        if change.release_due_date is not None:
            floor = max(floor, change.release_due_date.date())
        if proposed.date() <= floor:
            return (f"Need-by not realistic: propose a date after {floor:%d %b} "
                    "(after today and after the need-by)")
    return None


async def check_need_by(session: AsyncSession, change: ChangeRequest, user_id: int,
                        answer: Optional[str], proposed: Optional[datetime]) -> None:
    """At proceed of an urgent change: need-by realistic? Refuses without an
    answer; 'no' needs the proposed date. Not 'yes' notifies the Sales contact
    (else Sales) once on a customer change, the lead (else the raiser) on
    an internal one."""
    from app.services.change_service import ChangeError, ChangeService
    if not cm_switches.on("SCOPING_V2") or not is_urgent(change) or not _plain(change):
        return
    why = need_by_refusal(change, answer, proposed)
    if why:
        raise ChangeError(why)
    change.need_by_check = answer
    change.need_by_proposed = proposed if answer == "no" else None
    change.need_by_checked_by = user_id
    change.need_by_checked_at = datetime.utcnow()
    change.need_by_told_at = change.need_by_told_ref = change.need_by_told_by = None
    await session.flush()
    await ChangeService.append_changelog(
        session, change, "need_by_checked",
        f"Need-by realistic? {answer}"
        + (f" (proposed {proposed:%d %b %Y})" if answer == "no" and proposed else ""),
        user_id, new_value={"answer": answer,
                            "proposed": str(proposed) if proposed else None})
    if answer != "yes":
        await _notify_sales(session, change, user_id)


async def _notify_sales(session: AsyncSession, change: ChangeRequest, actor_id: int) -> None:
    """Customer change: the Sales contact, else Sales, gets the tell task's
    notice. Internal: the lead, else the raiser, is told (no task)."""
    from app.models.workflow import Department
    from app.services.change_people import department_members_of_change_org
    from app.services.notification_service import NotificationService
    what = ("only with start at risk" if change.need_by_check == "at_risk"
            else f"not realistic, proposed {change.need_by_proposed:%d %b}"
            if change.need_by_proposed else "not realistic")
    if not _goes_on_as_customer(change):
        who = change.lead_id or change.raised_by
        if who is not None and who != actor_id:
            await NotificationService.notify_once(
                session, [who], kind="need_by_tell",
                subject_key=f"need_by_internal:{change.id}:"
                            f"{change.need_by_checked_at:%Y%m%d%H%M%S}",
                title=f"Urgent need-by not realistic: {change.change_number}"[:255],
                body=f"Internal urgent change: the need-by date is {what}",
                link=f"/changes/{change.id}?tab=overview")
        return
    ids = [change.sales_owner_id] if change.sales_owner_id else []
    if not ids:
        sales = (await session.execute(select(Department.id).where(
            Department.name == "Sales"))).scalar_one_or_none()
        if sales is not None:
            ids = await department_members_of_change_org(session, change, [sales])
    await NotificationService.notify_once(
        session, [i for i in ids if i != actor_id], kind="need_by_tell",
        subject_key=f"need_by_tell:{change.id}:{change.need_by_checked_at:%Y%m%d%H%M%S}",
        title=f"Tell customer: new date or start at risk? {change.change_number}"[:255],
        body=f"Urgent change: the need-by date is {what}",
        link=f"/changes/{change.id}?tab=overview&task=need_by_tell")


async def tell_customer(session: AsyncSession, change: ChangeRequest, user, *,
                        ref: Optional[str] = None, mail_id: Optional[int] = None) -> None:
    """Sales told the customer (a filed mail or a reference)."""
    from app.services.change_service import ChangeError, ChangeService
    from app.services.cm_rules import reference_refusal
    if not need_by_open(change):
        raise ChangeError("Nothing to tell the customer about the need-by date")
    if not await ChangeService.member_of(session, user, "Sales"):
        from app.services.index_followup_service import FollowupForbidden
        raise FollowupForbidden("Sales tells the customer")
    if mail_id is not None:
        mail = await session.get(ChangeAttachment, mail_id)
        if mail is None or mail.change_id != change.id or mail.kind != "customer_email":
            raise ChangeError("Pick a customer mail filed on this change")
        evidence = f"Mail: {mail.filename}"
    else:
        why = reference_refusal(ref, "The mail to the customer or its reference",
                                "Mail to the buyer 15 Oct")
        if why:
            raise ChangeError(why)
        evidence = ref.strip()
    change.need_by_told_ref = evidence[:255]
    change.need_by_told_by = user.id
    change.need_by_told_at = datetime.utcnow()
    await session.flush()
    await ChangeService.append_changelog(
        session, change, "need_by_told", f"Customer told about the need-by: {evidence}",
        user.id, new_value={"ref": evidence})
