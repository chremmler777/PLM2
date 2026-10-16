"""ppap_decision and the customer flip (ECR-solid spec §0 "Customer flip",
§3 "Internal", HARD #7; switch SCOPING_V2).

- ppap_decision: on an internal change Quality answers, from scoping open,
  "Parameters / tool / material / cycle time changed on any part?" Nothing is
  preselected. 'no' names its basis (control plan / process sheet / customer
  spec) and a reference; 'yes' names the parts and flips the change to a
  customer change. An internal change proceeds only once it is answered
  (HARD #7).
- The customer flip (ppap 'yes', or a customer index on an internal change):
  customer_relevant, the project's Sales contact as Sales owner, the project
  PM as lead; the Sales owner answers "notification only" (filed mail or a
  reference) or "offer needed" (the quote deadline). Proceed waits for that
  answer. "Notification only": the customer is told, the money stays ours,
  so the change goes back to what it was before the flip (lead, cost
  carrier; internal_approval, HARD #8) with the notification on the record.
  That answer is the only way back: the lead's PATCH and the room's cost
  carrier cannot drop a flip (HARD #7). "Offer needed" at approved or later leaves the
  price open (HARD #9 at close) until a supplement is accepted or the money
  is absorbed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAttachment, ChangeRequest, SCOPING_STATUSES
from app.models.entities import User
from app.services import cm_switches
from app.services.change_service import ChangeError, ChangeService

PPAP_ANSWERS = ("no", "yes")
PPAP_BASES = ("control_plan", "process_sheet", "customer_spec")
FLIP_ANSWERS = ("notification", "offer")
#: Statuses from which a flip leaves the price open (spec §0 [R4]).
AFTER_APPROVAL = ("approved", "in_implementation", "in_validation", "released")


class PpapForbidden(ChangeError):
    """The caller may not give this answer: 403."""


def carrier(change: ChangeRequest) -> str:
    """The cost carrier the change goes on with: while it is captured or
    scoped, an undecided scoping meeting's pick (proceed applies it, see
    MeetingService._apply_cost_carrier), else the change's own."""
    if change.status in SCOPING_STATUSES:
        room = next((m.cost_carrier for m in reversed(change.meetings or [])
                     if m.decision is None and m.cost_carrier), None)
        if room:
            return room
    return "customer" if change.customer_relevant else "internal"


def applies(change: ChangeRequest) -> bool:
    """Does this change owe Quality's ppap_decision? One of ours (not a
    mother-plant change or an engineering review) that goes on as internal:
    internal now, or a customer change the scoping meeting set to internal
    (else proceed would turn it internal past the gate). SCOPING_V2 on. A
    change that flipped keeps its recorded answer."""
    return (cm_switches.on("SCOPING_V2")
            and getattr(change, "origin", None) in ("customer", "internal")
            and carrier(change) == "internal")


def flip_open(change: ChangeRequest) -> bool:
    """A flip whose Sales answer is still owed."""
    return change.customer_flip_at is not None and change.flip_answer is None


def flip_holds(change: ChangeRequest) -> bool:
    """The change flipped (ppap 'yes' or a customer index) and Sales did not
    answer 'notification only': it stays a customer change. Only that answer
    takes it back to internal; the lead's PATCH and the room's cost carrier
    may not (else HARD #7's consequence is dropped and the customer is never
    told)."""
    return change.customer_flip_at is not None and change.flip_answer != "notification"


def back_to_internal_refusal(change: ChangeRequest) -> Optional[str]:
    """Why the change may not be set back to internal here, or None."""
    if not cm_switches.on("SCOPING_V2") or not flip_holds(change):
        return None
    why = f" ({change.customer_flip_reason})" if change.customer_flip_reason else ""
    who = f"{change.sales_owner_name}'s" if change.sales_owner_name else "Sales'"
    return (f"{change.change_number} became a customer change{why}. Only "
            f"{who} answer 'notification only' takes it back to internal. "
            "No override lifts it")


class PpapDecisionService:

    @staticmethod
    def proceed_refusal(change: ChangeRequest) -> Optional[str]:
        """HARD #7: why 'proceed' (scoping -> in_assessment) is refused, or
        None."""
        if not cm_switches.on("SCOPING_V2"):
            return None
        if applies(change) and change.ppap_decision is None:
            return ("Proceed waits for Quality's PPAP decision (parameters / "
                    "tool / material / cycle time changed on any part?). No "
                    "override lifts it")
        if flip_open(change):
            who = change.sales_owner_name or "Sales"
            return (f"The change became a customer change; proceed waits for "
                    f"{who}: customer notification only, or offer needed?")
        return None

    @staticmethod
    async def notify_owed(session: AsyncSession, change: ChangeRequest,
                          actor_id: Optional[int] = None) -> None:
        """Decision needed (spec §0 Notifications, immediate): Quality's
        members of the change's organization, once per change, when the
        change is in scoping and owes the PPAP decision (entering scoping,
        or a meeting that sets the carrier to internal)."""
        if change.status != "scoping" or change.ppap_decision is not None:
            return
        from sqlalchemy import inspect as sa_inspect
        if "meetings" in sa_inspect(change).unloaded:
            await session.refresh(change, ["meetings"])     # a fresh change
        if not applies(change):
            return
        from app.models.workflow import Department
        from app.services.change_people import department_members_of_change_org
        from app.services.notification_service import NotificationService
        quality = (await session.execute(select(Department.id).where(
            Department.name == "Quality", Department.is_active.is_(True)))
        ).scalar_one_or_none()
        if quality is None:
            return
        ids = [i for i in await department_members_of_change_org(session, change, [quality])
               if i != actor_id]
        await NotificationService.notify_once(
            session, ids, kind="ppap_decision", subject_key=f"ppap_decision:{change.id}",
            title=f"PPAP decision needed: {change.change_number}"[:255],
            body=(f"'{change.title}': parameters / tool / material / cycle time "
                  "changed on any part? Proceed waits for your answer."),
            link=f"/changes/{change.id}?tab=scoping&task=ppap_decision")

    @staticmethod
    async def decide(
        session: AsyncSession, change: ChangeRequest, user: User, answer: str, *,
        basis: Optional[str] = None, ref: Optional[str] = None,
        part_ids: Optional[list[int]] = None,
    ) -> ChangeRequest:
        """Quality's ppap_decision (one member; an admin acts as Quality)."""
        if not cm_switches.on("SCOPING_V2"):
            raise ChangeError("The ppap_decision is switched off (SCOPING_V2)")
        if not applies(change):
            raise ChangeError("Only a change that goes on as internal owes the "
                              "PPAP decision")
        if change.status not in SCOPING_STATUSES:
            raise ChangeError("The PPAP decision is answered during capture or scoping")
        if not await ChangeService.member_of(session, user, "Quality"):
            raise PpapForbidden("Only a Quality member answers the PPAP decision "
                                "(admins: act as Quality)")
        if answer not in PPAP_ANSWERS:
            raise ChangeError("Answer no or yes: parameters / tool / material / "
                              "cycle time changed on any part?")
        if answer == "no":
            if basis not in PPAP_BASES:
                raise ChangeError("Say what 'no' is based on: the control plan, "
                                  "the process sheet or the customer spec")
            from app.services.cm_rules import reference_refusal
            why = reference_refusal(ref, "The reference of that document",
                                    "CP-4711 rev 3")
            if why:
                raise ChangeError(why)
            change.ppap_part_ids = None
            change.ppap_basis = basis
            change.ppap_ref = ref.strip()
        else:
            impacted = {i.part_id for i in change.impacted_items}
            picked = list(dict.fromkeys(part_ids or []))
            if not impacted:
                who = change.lead_name or "The lead"
                raise ChangeError(f"No impacted parts yet: {who} adds them first "
                                  "(Impacted tab, a task in My Tasks); then pick the parts")
            if not picked:
                raise ChangeError("Pick the parts whose parameters, tool, material "
                                  "or cycle time changed")
            if set(picked) - impacted:
                raise ChangeError("Pick parts of this change's impacted set (part_ids "
                                  "are part ids, not impacted-item ids)")
            change.ppap_part_ids = picked
            change.ppap_basis = None
            change.ppap_ref = (ref or "").strip() or None
        change.ppap_decision = answer
        change.ppap_decided_by = user.id
        change.ppap_decided_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "ppap_decided",
            f"ppap_decision: {answer}"
            + (f" ({basis}: {change.ppap_ref})" if answer == "no"
               else f" ({len(change.ppap_part_ids)} part(s))"),
            user.id, field_name="ppap_decision", new_value={
                "answer": answer, "basis": change.ppap_basis,
                "ref": change.ppap_ref, "part_ids": change.ppap_part_ids})
        if answer == "yes":
            await PpapDecisionService.flip(
                session, change, user.id, "ppap_decision yes: the customer must be told")
        return change

    @staticmethod
    async def flip(session: AsyncSession, change: ChangeRequest, user_id: int,
                   why: str) -> ChangeRequest:
        """The customer flip (spec §0): customer change, the project's Sales
        contact as Sales owner, the project PM as lead, and the Sales task
        "Customer notification or offer needed?". Idempotent. A customer
        change the scoping meeting set to internal flips too (the room's
        carrier goes back to customer)."""
        if carrier(change) == "customer":
            return change
        from app.services import mother_plants as mp
        if mp.is_mother_plant(change):
            raise ChangeError(f"A change from {mp.plant_name(change)} is not "
                              "customer relevant here")
        if change.status in ("closed", "cancelled", "rejected"):
            raise ChangeError(f"A {change.status} change does not flip")
        from app.services.project_team_service import ProjectTeamService
        old_lead = change.lead_id
        before = {"customer_relevant": bool(change.customer_relevant),
                  "origin": change.origin, "lead_id": old_lead,
                  "sales_owner_id": change.sales_owner_id}
        change.customer_relevant = True
        change.origin = "customer"
        change.sales_owner_id = await ChangeService.default_sales_owner_id(
            session, change.project_id, True, "customer")
        pm = await ProjectTeamService.responsible_user_id(
            session, change.project_id, "Project Manager")
        if pm is not None:
            change.lead_id = pm
        change.customer_flip_at = datetime.utcnow()
        change.customer_flip_reason = why[:255]
        change.flip_answer = change.flip_ref = None
        change.flip_answered_by = change.flip_answered_at = None
        # [R4] past approval the price opens only with Sales' "offer needed"
        # (answer_flip), never on the flip itself
        after_approval = change.status in AFTER_APPROVAL
        # the room's cost carrier follows: an undecided meeting that said
        # 'internal' would flip it back at proceed
        rooms = []
        for m in change.meetings:
            if m.decision is None and m.cost_carrier == "internal":
                m.cost_carrier = "customer"
                rooms.append(m.id)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "customer_flip",
            f"Internal change became a customer change: {why}", user_id,
            field_name="customer_relevant",
            # what 'notification only' restores (answer_flip)
            old_value={**before, "meeting_ids": rooms},
            new_value={"customer_relevant": True, "lead_id": change.lead_id,
                       "sales_owner_id": change.sales_owner_id})
        await PpapDecisionService._notify_flip(session, change, after_approval)
        return change

    @staticmethod
    async def _notify_flip(session: AsyncSession, change: ChangeRequest,
                           after_approval: bool) -> None:
        """Task newly theirs (spec §0 Notifications): the Sales owner (else
        Sales) and the new lead, once per change."""
        from app.models.workflow import Department
        from app.services.notification_service import NotificationService
        from app.services.change_people import department_members_of_change_org
        ids: list[int] = []
        if change.sales_owner_id is not None:
            ids.append(change.sales_owner_id)
        else:
            sales = (await session.execute(select(Department.id).where(
                Department.name == "Sales"))).scalar_one_or_none()
            if sales is not None:
                ids += await department_members_of_change_org(session, change, [sales])
        ids = list(dict.fromkeys(ids))
        past = (" It is past approval: an offer is a supplement; the price "
                "stays open until it is accepted or absorbed."
                if after_approval else "")
        if ids:
            await NotificationService.notify_once(
                session, ids, kind="customer_flip",
                subject_key=f"customer_flip:{change.id}",
                title=f"Customer notification or offer needed? {change.change_number}"[:255],
                body=(f"'{change.title}' became a customer change "
                      f"({change.customer_flip_reason}). Answer: notification "
                      "only (the mail or its reference) or offer needed (the "
                      "quote deadline)." + past),
                link=f"/changes/{change.id}?tab=scoping&task=customer_flip")
        # the new lead: told, not asked (Sales answers)
        if change.lead_id is not None and change.lead_id not in ids:
            who = change.sales_owner_name or "Sales"
            await NotificationService.notify_once(
                session, [change.lead_id], kind="customer_flip",
                subject_key=f"customer_flip_lead:{change.id}",
                title=f"You lead {change.change_number}: it became a customer change"[:255],
                body=(f"'{change.title}' ({change.customer_flip_reason}). {who} "
                      "answers whether the customer needs only a notification "
                      "or an offer; proceed waits for it." + past),
                link=f"/changes/{change.id}?tab=scoping")

    @staticmethod
    async def answer_flip(
        session: AsyncSession, change: ChangeRequest, user: User, answer: str, *,
        ref: Optional[str] = None, mail_id: Optional[int] = None,
        quote_deadline: Optional[datetime] = None,
    ) -> ChangeRequest:
        """The Sales owner's answer to the flip (any Sales member may act):
        notification only (a filed customer mail or a reference) or offer
        needed (the quote deadline)."""
        if not flip_open(change):
            raise ChangeError("No customer flip waits for an answer")
        if not await ChangeService.member_of(session, user, "Sales"):
            raise PpapForbidden("Sales answers: notification only or offer needed")
        if answer not in FLIP_ANSWERS:
            raise ChangeError("Answer 'notification only' or 'offer needed'")
        if answer == "notification":
            evidence = None
            if mail_id is not None:
                mail = await session.get(ChangeAttachment, mail_id)
                if (mail is None or mail.change_id != change.id
                        or mail.kind != "customer_email"):
                    raise ChangeError("Pick a customer mail filed on this change")
                evidence = f"Mail: {mail.filename}"
            else:
                from app.services.cm_rules import reference_refusal
                why = reference_refusal(ref, "The notification's mail or reference",
                                        "Mail to the buyer 15 Oct")
                if why:
                    raise ChangeError(why)
                evidence = ref.strip()
            change.flip_ref = evidence[:255]
            # the customer is told; the money stays ours: the change goes
            # back to what it was before the flip (internal_approval, HARD
            # #8): its lead, cost carrier, origin and the room's carrier
            await PpapDecisionService._undo_flip(session, change)
        else:
            if quote_deadline is None:
                raise ChangeError("Offer needed: set the quote deadline")
            if quote_deadline.date() < datetime.utcnow().date():
                raise ChangeError("The quote deadline is in the past: pick today "
                                  "or a later date")
            if change.required_by_date != quote_deadline:
                old = change.required_by_date
                change.required_by_date = quote_deadline
                change.required_by_set_by = user.id
                change.required_by_set_at = datetime.utcnow()
                await ChangeService.append_changelog(
                    session, change, "deadline_set",
                    f"Quote deadline {old} -> {quote_deadline} (customer flip)",
                    user.id, field_name="required_by_date",
                    old_value=str(old) if old else None, new_value=str(quote_deadline))
            change.flip_ref = None
            if change.status in AFTER_APPROVAL:
                # [R4] past approval every offer is a supplement: the money
                # stays open until it is accepted or absorbed (HARD #9)
                await ChangeService.open_price(
                    session, change, "Customer flip after approval, offer needed: "
                    "the price is open until the supplement is accepted or "
                    "absorbed", user.id)
        change.flip_answer = answer
        change.flip_answered_by = user.id
        change.flip_answered_at = datetime.utcnow()
        await session.flush()
        if answer == "notification":
            # a flip from a customer index left the decision unanswered: back
            # to internal it is owed again (HARD #7), so Quality is told
            await PpapDecisionService.notify_owed(session, change, user.id)
        await ChangeService.append_changelog(
            session, change, "customer_flip_answered",
            f"Customer flip: {'notification only' if answer == 'notification' else 'offer needed'}"
            + (f" ({change.flip_ref}); the money stays ours: back to before the flip"
               if answer == "notification" else "")
            + ("; price open until the supplement is accepted or absorbed"
               if answer == "offer" and change.price_open else ""), user.id,
            new_value={"answer": answer, "ref": change.flip_ref,
                       "customer_relevant": change.customer_relevant,
                       "price_open": change.price_open})
        return change

    @staticmethod
    async def _undo_flip(session: AsyncSession, change: ChangeRequest) -> None:
        """'Notification only': restore what the flip changed, from its
        changelog row (customer_relevant, origin, Sales owner, the lead while
        that person is still active, the rooms it moved to customer). A flip
        logged before that record existed goes back to internal, no Sales
        owner (C10), the lead kept when unknown."""
        import json
        from app.models.change import ChangeChangelog
        row = (await session.execute(
            select(ChangeChangelog.old_value).where(
                ChangeChangelog.change_id == change.id,
                ChangeChangelog.action == "customer_flip")
            .order_by(ChangeChangelog.id.desc()).limit(1))).scalar_one_or_none()
        try:
            before = json.loads(row) if row else {}
        except ValueError:
            before = {}
        if not isinstance(before, dict):
            before = {}
        change.customer_relevant = bool(before.get("customer_relevant", False))
        change.origin = before.get("origin") or (
            "customer" if change.customer_relevant else "internal")
        change.sales_owner_id = (before.get("sales_owner_id")
                                 if change.customer_relevant else None)
        old_lead = before.get("lead_id")
        if old_lead is not None and old_lead != change.lead_id:
            lead = await session.get(User, old_lead)
            if lead is not None and lead.is_active:
                change.lead_id = old_lead
        rooms = before.get("meeting_ids")
        for m in change.meetings:
            if m.decision is not None or m.cost_carrier != "customer":
                continue
            if rooms is None or m.id in rooms:
                m.cost_carrier = "internal"
