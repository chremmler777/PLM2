"""The 'decision needed' immediate notices (ECR-solid spec §0
Notifications, close-out A6-02): when a decision first becomes owed, the
people who decide hear it once, by mail (ecr_mail.MAIL_KINDS):

- a PM or Quality sign-off owed after the customer's yes (COMMERCIAL_V2),
  key chg:<id>:sign:<side>:<offer id>; a re-sign stays task_new
  (ChangeService._ask_resign);
- the internal approval (HARD #8) once costing waits only on it
  (COMMERCIAL_V2), key chg:<id>:internal_approval;
- a concession for Quality to decide once the customer's mail is filed
  (RELEASE_V2), key vi:<id>:concession_decide.

One notice per item ever (include_read): the My Tasks row is the reminder."""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Department
from app.services import cm_switches

KIND = "decision_needed"
SIDE_DEPARTMENT = {"pm": "Project Manager", "quality": "Quality"}
SIDE_WORDS = {"pm": "PM", "quality": "Quality"}


async def _members(session: AsyncSession, change, dept_name: str,
                   exclude=()) -> list[int]:
    """F11: the project team's owner of the side (responsible, else its
    backup, else the members), never `exclude` (the actor, 4-eyes)."""
    from app.services.change_people import team_owner_ids
    ids = [i for (i,) in (await session.execute(select(Department.id).where(
        Department.name == dept_name, Department.is_active.is_(True)))).all()]
    return await team_owner_ids(session, change.project_id, ids,
                                exclude=exclude, real_only=True)


async def _send(session: AsyncSession, ids: Iterable[int], key: str, title: str,
                body: str, link: str) -> int:
    from app.services.notification_service import NotificationService
    return await NotificationService.notify_once(
        session, sorted(set(i for i in ids if i)), kind=KIND, subject_key=key,
        title=title[:255], body=body, link=link, include_read=True)


async def sign_off_owed(session: AsyncSession, change, sides: list[str], offer,
                        actor_id: Optional[int]) -> int:
    """First sign-off owed on `offer` (nobody signed that side yet): the
    side's department members, never the actor nor the other side's signer
    (4-eyes)."""
    if not cm_switches.on("COMMERCIAL_V2") or offer is None:
        return 0
    sent = 0
    what = "supplement" if getattr(offer, "kind", None) == "supplement" else "offer"
    for side in sides:
        if (change.pm_signed_by if side == "pm" else change.quality_signed_by) is not None:
            continue      # a re-sign: ChangeService._ask_resign tells the signer
        other = change.quality_signed_by if side == "pm" else change.pm_signed_by
        ids = await _members(session, change, SIDE_DEPARTMENT[side],
                             exclude=(actor_id, other))
        sent += await _send(
            session, ids, f"chg:{change.id}:sign:{side}:{offer.id}",
            f"{SIDE_WORDS[side]} sign-off needed: {change.change_number}",
            f"The customer accepted {what} v{offer.version}: sign off for "
            f"{SIDE_WORDS[side]}.",
            f"/changes/{change.id}?tab=overview")
    return sent


async def internal_approval_owed(session: AsyncSession, change,
                                 actor_id: Optional[int]) -> int:
    """HARD #8 owed: an internal change in costing, every department's
    costing finalized, no approval yet. The approvers (never the raiser)."""
    if (not cm_switches.on("COMMERCIAL_V2") or change.customer_relevant
            or change.status != "costing" or change.internal_approved_at is not None):
        return 0
    from app.services.change_service import ChangeService
    if (cm_switches.on("ASSESSMENT_V2")
            and await ChangeService.costing_pending_department_ids(session, change)):
        return 0
    ids = await ChangeService.internal_approver_ids(session, change)
    return await _send(
        session, [i for i in ids if i != actor_id],
        f"chg:{change.id}:internal_approval",
        f"Internal approval needed: {change.change_number}",
        "Costing is finalized: approve the internal spend (cost, volume, saving).",
        f"/changes/{change.id}?tab=offer")


async def concession_owed(session: AsyncSession, change, issue,
                          actor_id: Optional[int]) -> int:
    """Quality decides a requested concession once the customer's mail is
    filed (spec §10): Quality's members of the change's organization."""
    from app.services.validation_issue_service import ValidationIssueService as svc
    if (not cm_switches.on("RELEASE_V2") or not svc.quality_decides_concessions()
            or issue.route != "customer_concession" or not issue.is_open):
        return 0
    ids = await _members(session, change, "Quality", exclude=(actor_id,))
    return await _send(
        session, ids, f"vi:{issue.id}:concession_decide",
        f"{change.change_number} {issue.ref}: Quality decides the concession",
        "The customer's mail is filed: accept the concession (quantity or "
        "until a date) or decline it.",
        svc._link(change, issue))
