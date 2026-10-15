"""Capture and the urgent path (ECR-solid spec §2, §3 "Urgent"; switch
SCOPING_V2).

- Customer change complete: a typed customer file (kind customer_file, or
  a filed customer mail) and the quote deadline.
- Internal change complete: description, one evidence file or photo, and
  "what is wrong today" as a number with its unit, with the target.
- Urgent (priority 'critical'): the need-by date (release_due_date), a
  reason pick (URGENT_REASONS) and its evidence; refused without them.
  Mother-plant changes keep their own SOP and are left out.
- Urgent proceed: "Need-by realistic? yes / only with start at risk / no
  (proposed date)"; anything but yes gives Sales "Tell customer: new date or
  start at risk?" at once (need_by_open), answered with a mail or reference.
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
    if change.urgent_reason not in URGENT_REASONS:
        return ("Urgent: pick the reason (line stop, safety, quality escape, "
                "launch date, customer demand, other)")
    from app.services.cm_rules import reference_refusal
    return reference_refusal(change.urgent_evidence, "Urgent: the evidence")


async def missing(session: AsyncSession, change: ChangeRequest) -> list[str]:
    """The §2 parts of a complete capture kickoff_missing adds (switch on):
    the customer file of a customer change, the problem and target of an
    internal one, the urgent need-by, reason and evidence."""
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
        from app.services.cm_rules import reference_refusal
        if change.release_due_date is None:
            out.append("need-by date")
        if (change.urgent_reason not in URGENT_REASONS
                or reference_refusal(change.urgent_evidence)):
            out.append("urgent reason and evidence")
    return out


def need_by_open(change: ChangeRequest) -> bool:
    """Sales owes "Tell customer: new date or start at risk?"."""
    return (cm_switches.on("SCOPING_V2") and change.need_by_check in ("at_risk", "no")
            and change.need_by_told_at is None
            and change.status not in ("closed", "cancelled", "rejected"))


async def check_need_by(session: AsyncSession, change: ChangeRequest, user_id: int,
                        answer: Optional[str], proposed: Optional[datetime]) -> None:
    """At proceed of an urgent change: need-by realistic? Refuses without an
    answer; 'no' needs the proposed date. Not 'yes' notifies the Sales owner
    (else Sales) once."""
    from app.services.change_service import ChangeError, ChangeService
    if not cm_switches.on("SCOPING_V2") or not is_urgent(change) or not _plain(change):
        return
    if answer not in NEED_BY_CHECKS:
        due = change.release_due_date.strftime("%d %b") if change.release_due_date else "-"
        raise ChangeError(f"Urgent: is the need-by date ({due}) realistic? Answer yes, "
                          "only with start at risk, or no with a proposed date")
    if answer == "no" and proposed is None:
        raise ChangeError("Need-by not realistic: propose a date")
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
    from app.models.workflow import Department
    from app.services.change_people import department_members_of_change_org
    from app.services.notification_service import NotificationService
    ids = [change.sales_owner_id] if change.sales_owner_id else []
    if not ids:
        sales = (await session.execute(select(Department.id).where(
            Department.name == "Sales"))).scalar_one_or_none()
        if sales is not None:
            ids = await department_members_of_change_org(session, change, [sales])
    what = ("only with start at risk" if change.need_by_check == "at_risk"
            else f"not realistic, proposed {change.need_by_proposed:%d %b}"
            if change.need_by_proposed else "not realistic")
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
        why = reference_refusal(ref, "The mail to the customer or its reference")
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
