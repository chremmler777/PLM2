"""The scope change card (ECR-solid spec §6 [R3], COMMERCIAL_V2).

See app/models/change_scope.py for the three steps. This service keeps the
card and the change's older bookkeeping in step: a card that re-costs sets
`scope_changed_after_quote` / `scope_change_department_ids`, so the
departments' costing stays open (costing_position_service) exactly as it did
for an impact edit after the quote, and `EarlyStageService.scope_change_state`
reads the cards when a change has any.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest
from app.models.change_scope import (
    SCOPE_OPEN, SCOPE_UNCOSTED, ChangeScopeChange,
)
from app.models.entities import User
from app.models.workflow import Department
from app.services import cm_switches
from app.services.change_service import ChangeError, ChangeService

#: From here on the customer may add or change something (spec §6).
CARD_STATUSES = ("quoted", "approved", "in_implementation", "in_validation")
#: Past approval an added part is its own linked change.
POST_APPROVAL = ("approved", "in_implementation", "in_validation")


#: The text a card's price opening starts with (_maybe_close_price reads it).
_OPENED_BY = "Scope change #"


def _settled_without_money(card: ChangeScopeChange) -> bool:
    """Refused, moved to its own change, or confirmed to the customer at no
    cost: the card asks the customer for no money."""
    return card.status in ("refused", "moved") or (
        card.status == "accepted" and card.offer_id is None and card.told_at is not None)


class ScopeChangeForbidden(ChangeError):
    """The caller may not do this: 403."""


async def cards(session: AsyncSession, change_ids: list[int]) -> list[ChangeScopeChange]:
    if not change_ids:
        return []
    return list((await session.execute(
        select(ChangeScopeChange).where(ChangeScopeChange.change_id.in_(change_ids))
        .order_by(ChangeScopeChange.id))).scalars().all())


async def open_cards(session: AsyncSession, change: ChangeRequest) -> list[ChangeScopeChange]:
    return [c for c in await cards(session, [change.id]) if c.status in SCOPE_OPEN]


async def card_holding_price(session: AsyncSession, change: ChangeRequest,
                             settled_offer_id: Optional[int]) -> Optional[ChangeScopeChange]:
    """A4-05 (spec §6 [R4]): a card opened after approval keeps the price
    open until its own supplement is accepted or absorbed. When a version
    is settled (accepted, its lower total OK'd), the open price closes only
    if no such card is still open that this version does not carry (one
    opened after it went out, or one still re-costed when it did: "subject
    to final costing"). The same reading as _maybe_close_price."""
    return next((c for c in await cards(session, [change.id])
                 if c.post_accept and c.status in SCOPE_OPEN
                 and (settled_offer_id is None or c.offer_id != settled_offer_id)), None)


async def no_cost_ids(session: AsyncSession, rows: list[ChangeScopeChange]) -> set[int]:
    """The ready cards every routed department re-costed as 'no cost
    impact' (its latest word per department): nothing to price, Sales
    confirms it to the customer instead of a supplement or new version.
    One changelog query for all of them (My Tasks batches)."""
    ready = {c.id: c for c in rows if c.status == "ready" and c.department_ids}
    if not ready:
        return set()
    import json
    from app.models.change import ChangeChangelog
    logs = (await session.execute(
        select(ChangeChangelog.new_value).where(
            ChangeChangelog.change_id.in_({c.change_id for c in ready.values()}),
            ChangeChangelog.action == "scope_change_recosted")
        .order_by(ChangeChangelog.id))).scalars().all()
    word: dict = {}
    for raw in logs:
        try:
            v = json.loads(raw or "null")
        except ValueError:
            continue
        if isinstance(v, dict) and v.get("scope_change_id") in ready:
            word[(v["scope_change_id"], v.get("department_id"))] = bool(v.get("no_cost"))
    return {cid for cid, c in ready.items()
            if all(word.get((cid, d)) for d in c.department_ids)}


def label(card: ChangeScopeChange) -> str:
    """"#3 886.198: second variant" for messages and the offer line."""
    head = f"#{card.id}" + (f" {card.part_number}" if card.part_number else "")
    return f"{head}: {card.what}"[:200]


async def guard_text(session: AsyncSession, change: ChangeRequest,
                     to_status: str) -> Optional[str]:
    """SOFT `scope_change_uncovered` (spec §6): an open card holds
    quoted -> approved (a card opened after approval opens the price
    instead), -> in_implementation and -> released.
    Override: a Project Management or Management member."""
    if not cm_switches.on("COMMERCIAL_V2"):
        return None
    if to_status == "approved" and change.status == "quoted":
        held = [c for c in await open_cards(session, change) if not c.post_accept]
    elif to_status in ("in_implementation", "released"):
        held = await open_cards(session, change)
    else:
        return None
    if not held:
        return None
    return ("Scope change not covered by an offer: "
            + "; ".join(f"{label(c)} ({c.status})" for c in held))


class ScopeChangeService:

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------
    @staticmethod
    async def _roles(session, change, user) -> dict:
        from app.services.early_stage_service import EarlyStageService
        return await EarlyStageService._roles(session, change, user)

    @staticmethod
    async def may_request(session: AsyncSession, change: ChangeRequest, user: User) -> bool:
        """Sales (and the run team) put the customer's wish on the record."""
        if user.effective_role == "viewer":
            return False
        r = await ScopeChangeService._roles(session, change, user)
        return r["sales"] or r["run_team"]

    # ------------------------------------------------------------------
    # 1. requested
    # ------------------------------------------------------------------
    @staticmethod
    async def request(session: AsyncSession, change: ChangeRequest, user: User, *,
                      what: str, part_number: Optional[str] = None,
                      expects_by: Optional[date] = None,
                      attachment_id: Optional[int] = None, ref: Optional[str] = None,
                      kind: str = "customer", system: bool = False,
                      department_ids: Optional[list[int]] = None,
                      recheck_id: Optional[int] = None,
                      from_customer: bool = False) -> ChangeScopeChange:
        """Sales: "Customer wants to add or change something" (from quoted
        on). The customer's mail (filed on the change) or its reference is
        the evidence; what the customer expects by when drives the dues.
        `system` cards (a recheck effect, a PO that differs) skip the
        rights and the evidence: their source is on the record already."""
        if not cm_switches.on("COMMERCIAL_V2"):
            raise ChangeError("Scope change cards are switched off (COMMERCIAL_V2)")
        if not change.customer_relevant:
            raise ChangeError("An internal change has no customer offer to change")
        if change.status not in CARD_STATUSES:
            raise ChangeError(
                "The customer adds or changes something once the offer is out "
                f"(quoted) and until validation; this change is '{change.status}'")
        if not system and not await ScopeChangeService.may_request(session, change, user):
            raise ScopeChangeForbidden(
                "Sales records what the customer wants (or the lead, Project "
                "Management, an admin)")
        what = (what or "").strip()
        if len(what) < 5:
            raise ChangeError("Say what the customer wants, in a few words")
        evidence = None
        if not system:
            from app.services.cm_rules import reference_refusal
            if attachment_id:
                att = await ChangeService.customer_evidence_file(
                    session, change, attachment_id, from_customer=from_customer,
                    actor_id=user.id,
                    what="Pick a customer mail or file filed on this change")
                # spec §6 step 1: the customer's mail after the offer date
                from app.services.offer_service import OfferService
                sent = await OfferService.latest_sent(session, change)
                if (sent is not None and sent.sent_at is not None
                        and att.created_at is not None and att.created_at < sent.sent_at):
                    raise ChangeError(
                        f"'{att.filename}' was filed {att.created_at:%d %b %Y}, before "
                        f"v{sent.version} went out ({sent.sent_at:%d %b %Y}): the "
                        "customer's new wish is in a mail after the offer")
                evidence = f"Mail: {att.filename}"[:255]
            else:
                why = reference_refusal(ref, "The customer's mail or its reference",
                                        "Mail 15 Oct from the buyer, EC 2026-114")
                if why:
                    raise ChangeError(why)
                evidence = ref.strip()[:255]
            from app.utils.clock import business_today
            if expects_by is not None and expects_by < business_today():
                raise ChangeError("The date the customer expects it is in the past")
        # spec §6 [R4]: a card opened after approval opens the price; before
        # it (a PO that differs at the customer's yes included, §7) it holds
        # the approval (SOFT scope_change_uncovered)
        post_accept = change.status in POST_APPROVAL
        card = ChangeScopeChange(
            change_id=change.id, kind=kind, status="requested",
            part_number=(part_number or "").strip()[:100] or None, what=what,
            expects_by=expects_by, evidence_ref=evidence or (ref or None),
            attachment_id=int(attachment_id) if attachment_id else None,
            post_accept=post_accept, requested_by=user.id,
            requested_at=datetime.utcnow(), recheck_id=recheck_id)
        session.add(card)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scope_change_requested",
            f"Scope change {label(card)} ({kind})", user.id,
            new_value={"scope_change_id": card.id, "kind": kind,
                       "part_number": card.part_number}, notes=evidence)
        if post_accept:
            # spec §6 [R4]: after the customer's yes the money is open until
            # a supplement covering it is accepted or it is absorbed. Logged
            # also when open already: the card is one cause of it (the text
            # names the card: _maybe_close_price reads it back)
            await ChangeService.open_price(
                session, change, f"{_OPENED_BY}{card.id} after acceptance: the "
                "price is open until its supplement is accepted or absorbed", user.id)
        if department_ids is not None:
            await ScopeChangeService._start_recost(session, change, card, department_ids,
                                                   user.id)
            return card
        from app.services.notification_service import NotificationService
        deciders = [change.lead_id] if change.lead_id else []
        if deciders:
            await NotificationService.notify_once(
                session, [i for i in deciders if i != user.id], kind="decision_needed",
                subject_key=f"scope_change:{card.id}:decide",
                title=f"Scope change requested: accept or refuse: {change.change_number}"[:255],
                body=label(card), link=f"/changes/{change.id}?tab=offer")
        else:
            await NotificationService.notify_departments_once(
                session, [d for d in [await ScopeChangeService._dept_id(session, "Project Manager")]
                          if d is not None], change=change, kind="decision_needed",
                subject_key=f"scope_change:{card.id}:decide",
                title=f"Scope change requested: accept or refuse: {change.change_number}"[:255],
                body=label(card), link=f"/changes/{change.id}?tab=offer")
        return card

    @staticmethod
    async def _dept_id(session: AsyncSession, name: str) -> Optional[int]:
        return (await session.execute(
            select(Department.id).where(Department.name == name))).scalar_one_or_none()

    # ------------------------------------------------------------------
    # 2. re-costed
    # ------------------------------------------------------------------
    @staticmethod
    async def _card(session, change, card_id) -> ChangeScopeChange:
        card = await session.get(ChangeScopeChange, card_id)
        if card is None or card.change_id != change.id:
            raise ChangeError("Scope change not found on this change")
        return card

    @staticmethod
    async def decide(session: AsyncSession, change: ChangeRequest, card_id: int,
                     user: User, decision: str, *,
                     department_ids: Optional[list[int]] = None,
                     note: Optional[str] = None) -> ChangeScopeChange:
        """The lead (run team): accept (the departments re-cost), refuse
        (Sales tells the customer, a reason), or after approval for an added
        part 'new_change' (its own linked change, its own quote and dates)."""
        card = await ScopeChangeService._card(session, change, card_id)
        if card.status != "requested":
            raise ChangeError(f"Scope change #{card.id} is {card.status}, not requested")
        if not (await ScopeChangeService._roles(session, change, user))["run_team"]:
            raise ScopeChangeForbidden(
                "The change lead decides a scope change (or Project Management, an admin)")
        note = (note or "").strip() or None
        now = datetime.utcnow()
        if decision == "refuse":
            if note is None or len(note) < 5:
                raise ChangeError("Refuse: say why (Sales tells the customer)")
            card.status, card.decided_by, card.decided_at = "refused", user.id, now
            card.decision_note, card.closed_at = note, now
            await session.flush()
            await ChangeService.append_changelog(
                session, change, "scope_change_refused",
                f"Scope change {label(card)} refused: {note}", user.id,
                new_value={"scope_change_id": card.id}, notes=note)
            await ScopeChangeService._maybe_close_price(session, change, user.id)
            # §7: the card may be the last thing the approval waited on
            await ChangeService.try_auto_approve(session, change, user.id)
            return card
        if decision == "new_change":
            if change.status not in POST_APPROVAL:
                raise ChangeError(
                    "Before approval an added part joins this change: accept it")
            new = await ChangeService.create_change(
                session, project_id=change.project_id,
                title=(f"{card.part_number or 'Scope change'} - from "
                       f"{change.change_number}: {card.what}")[:200],
                change_type=change.change_type, raised_by=card.requested_by,
                description=(f"Scope change #{card.id} of {change.change_number} "
                             f"after its approval: {card.what}"
                             + (f" (customer: {card.evidence_ref})" if card.evidence_ref else "")),
                customer_relevant=True, sales_owner_id=change.sales_owner_id)
            new.related_change_id = change.id
            if change.related_change_id is None:
                change.related_change_id = new.id
            await ScopeChangeService._copy_card_file(session, card, new, user.id)
            card.status, card.decided_by, card.decided_at = "moved", user.id, now
            card.new_change_id, card.decision_note, card.closed_at = new.id, note, now
            await session.flush()
            await ChangeService.append_changelog(
                session, change, "scope_change_moved",
                f"Scope change {label(card)}: its own change {new.change_number}",
                user.id, new_value={"scope_change_id": card.id, "new_change_id": new.id})
            await ScopeChangeService._maybe_close_price(session, change, user.id)
            return card
        if decision != "accept":
            raise ChangeError("Decide accept, refuse or new_change")
        if card.question_open:
            raise ChangeError(
                f"Scope change #{card.id} waits for the customer's answer "
                f"(Sales): {card.question['text']}")
        routed = {a.department_id for a in change.assessments}
        ids = sorted({int(d) for d in (department_ids or [])})
        if not ids:
            raise ChangeError("Accept: pick the departments that re-cost it")
        stray = [d for d in ids if d not in routed]
        if stray:
            raise ChangeError("Only departments routed on this change re-cost it")
        # nobody can mark an inactive department's re-costing done
        idle = [n for (n,) in (await session.execute(
            select(Department.name).where(Department.id.in_(ids),
                                          Department.is_active.is_(False)))).all()]
        if idle:
            raise ChangeError(
                f"{', '.join(sorted(idle))} is inactive: nobody can re-cost for it; "
                "pick an active department")
        await ScopeChangeService._take_part(session, change, card, user)
        card.decided_by, card.decided_at, card.decision_note = user.id, now, note
        await ScopeChangeService._start_recost(session, change, card, ids, user.id)
        return card

    @staticmethod
    async def _take_part(session: AsyncSession, change: ChangeRequest,
                         card: ChangeScopeChange, user: User) -> None:
        """Spec §6 step 2: an added part gets the intake live-change check
        and joins the impacted set (a logged impact edit, the card is the
        reason). After approval an added part is its own change (refused
        here: 'new change'); a P/N not in PLM yet is said in the log."""
        if not card.part_number:
            return
        from app.models.part import Part
        from app.services.early_stage_service import EarlyStageService
        from app.services.revision_intake_service import RevisionIntakeService
        part = (await session.execute(
            select(Part).where(Part.project_id == change.project_id,
                               Part.part_number == card.part_number))).scalars().first()
        await session.refresh(change, ["impacted_items"])
        if part is not None and any(i.part_id == part.id for i in change.impacted_items):
            return                        # a change to a part already on it
        if change.status in POST_APPROVAL:
            raise ChangeError(
                f"{card.part_number} is not on this change: after approval an "
                "added part is its own linked change (decide 'new change')")
        if part is None:
            await ChangeService.append_changelog(
                session, change, "scope_change_part_unknown",
                f"Scope change #{card.id}: {card.part_number} is not in PLM yet; "
                "add it to the impacted items once it is created", user.id,
                new_value={"scope_change_id": card.id})
            return
        lives = await RevisionIntakeService.live_changes_for_part(
            session, part.id, change.project_id, exclude_id=change.id)
        await ChangeService.add_impacted_item(
            session, change, part.id, user.id,
            impact_note=f"Scope change #{card.id}: {card.what}"[:500])
        await EarlyStageService.recompose_title(session, change, user.id)
        live = (f"; {', '.join(f'{c.change_number} ({c.status})' for c in lives)} "
                "also carries it") if lives else ""
        await ChangeService.append_changelog(
            session, change, "impact_edited_by_scope_change",
            f"{card.part_number} added to the impacted items by scope change "
            f"#{card.id}{live}", user.id,
            new_value={"scope_change_id": card.id, "part_ids": [part.id],
                       "live_change_ids": [c.id for c in lives]},
            notes=card.what)
        if lives and change.related_change_id is None:
            # spec §1: related both ways, as for a full ECR next to a live one
            change.related_change_id = lives[0].id
            if lives[0].related_change_id is None:
                lives[0].related_change_id = change.id

    @staticmethod
    async def _copy_card_file(session: AsyncSession, card: ChangeScopeChange,
                              new: ChangeRequest, actor_id: int) -> None:
        """The new linked change gets the customer's mail the card was
        opened on (its own copy of the file: deleting one never removes the
        other)."""
        if not card.attachment_id:
            return
        import os
        import shutil
        import uuid
        from app.models.change import ChangeAttachment
        att = await session.get(ChangeAttachment, card.attachment_id)
        if att is None or not att.stored_path or not os.path.exists(att.stored_path):
            return
        base = os.path.dirname(os.path.dirname(att.stored_path))
        folder = os.path.join(base, str(new.id))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{uuid.uuid4().hex}_{att.filename}")
        shutil.copyfile(att.stored_path, path)
        session.add(ChangeAttachment(
            change_id=new.id, filename=att.filename, stored_path=path,
            content_type=att.content_type, size_bytes=att.size_bytes,
            sha256=att.sha256, uploaded_by=actor_id, kind=att.kind))
        await session.flush()
        await ChangeService.append_changelog(
            session, new, "attachment_added",
            f"Attached {att.filename} (from scope change #{card.id})", actor_id)

    @staticmethod
    async def _start_recost(session: AsyncSession, change: ChangeRequest,
                            card: ChangeScopeChange, ids: list[int], actor_id: int) -> None:
        """The departments' costing opens again for this card (the legacy
        flag keeps costing_position_service's door open); each owner is told
        once, due two working days out (or before what the customer expects)."""
        from app.services.due_rules import add_wd
        due = add_wd(datetime.utcnow(), 2).date()
        if card.expects_by is not None:
            due = max(min(due, card.expects_by), add_wd(datetime.utcnow(), 1).date())
        card.status = "recosting"
        card.department_ids = sorted(set(card.department_ids or []) | set(ids))
        card.departments_done = [d for d in (card.departments_done or []) if d not in ids]
        card.recost_due = due
        change.scope_changed_after_quote = True
        change.scope_changed_at = datetime.utcnow()
        change.scope_change_reason = f"Scope change {label(card)}"[:500]
        change.scope_change_department_ids = sorted(
            set(change.scope_change_department_ids or []) | set(ids))
        await session.flush()
        names = dict((await session.execute(
            select(Department.id, Department.name).where(Department.id.in_(ids)))).all())
        await ChangeService.append_changelog(
            session, change, "scope_change_recosting",
            f"Scope change {label(card)}: re-costing by "
            + ", ".join(names.get(d, f"dept {d}") for d in ids)
            + f", due {due.isoformat()}", actor_id,
            new_value={"scope_change_id": card.id, "department_ids": ids})
        from app.services.notification_service import NotificationService
        await NotificationService.notify_departments_once(
            session, ids, change=change, kind="task_new",
            subject_key=f"scope_change:{card.id}:recost",
            title=f"Re-cost a scope change by {due.strftime('%a %d %b')}: "
                  f"{change.change_number}"[:255],
            body=label(card), link=f"/changes/{change.id}?tab=costing")

    @staticmethod
    async def department_cost_moved(session: AsyncSession, change: ChangeRequest,
                                    department_id: int) -> bool:
        """Did the department's costing move against what the customer has
        priced (the accepted offer and supplements, else the last version
        sent)? Money only, compared per costing line (R4: evidence that the
        re-costing happened)."""
        from app.services.offer_service import OfferService, _num, normalise
        dept = await session.get(Department, department_id)
        name = dept.name if dept is not None else None
        fresh, _ = await OfferService._costing_basis(session, change)
        now: dict = {}
        for l in fresh:
            if l.get("department") == name:
                now[l["key"]] = now.get(l["key"], 0.0) + _num(l.get("source_amount"))
        offers = await OfferService.list_offers(session, change)
        priced_by = [o for o in offers if o.status == "accepted"] or \
            [o for o in offers if o.sent_at is not None][:1]
        priced: dict = {}
        for o in priced_by:
            for l in normalise(o.data).get("cost_lines") or []:
                if l.get("include", True) and l.get("key") and l.get("department") == name:
                    priced[l["key"]] = priced.get(l["key"], 0.0) + _num(
                        l.get("source_amount", l.get("amount")))
        return any(abs(now.get(k, 0.0) - priced.get(k, 0.0)) > 0.005
                   for k in set(now) | set(priced))

    @staticmethod
    async def recosted(session: AsyncSession, change: ChangeRequest, card_id: int,
                       user: User, department_id: int,
                       no_cost_note: Optional[str] = None) -> ChangeScopeChange:
        """A department's re-costing is done; the last one hands Sales
        "Revise offer" (or "Send supplement" after approval). Only a member
        of the department says so (acts-as honoured), and only with evidence
        (R4): its costing moved against what the customer has priced, or a
        "no cost impact" statement (why, 15+ characters) on the record."""
        card = await ScopeChangeService._card(session, change, card_id)
        if card.status != "recosting":
            raise ChangeError(f"Scope change #{card.id} is {card.status}, not re-costing")
        if department_id not in (card.department_ids or []):
            raise ChangeError("This department does not re-cost this scope change")
        from app.services.workflow_service import WorkflowService
        dept = await session.get(Department, department_id)
        dname = dept.name if dept is not None else f"dept {department_id}"
        if not await WorkflowService.actor_in_department(session, user, department_id):
            raise ScopeChangeForbidden(
                f"A member of {dname} marks its re-costing done (the run team "
                "may override 'scope change not covered' instead)")
        note = " ".join((no_cost_note or "").split()) or None
        if note is not None:
            if len(note) < 15:
                raise ChangeError(
                    "No cost impact: say why in a sentence (15+ characters), e.g. "
                    "'same insert, only the engraving text changes'")
        elif not await ScopeChangeService.department_cost_moved(session, change, department_id):
            raise ChangeError(
                f"{dname}'s costing did not change against the offer: update the "
                "costing positions first, or mark 'No cost impact' and say why")
        done = set(card.departments_done or []) | {department_id}
        card.departments_done = sorted(done)
        await ChangeService.append_changelog(
            session, change, "scope_change_recosted",
            f"Scope change #{card.id}: {dname} "
            + ("no cost impact" if note else "re-costed"),
            user.id, new_value={"scope_change_id": card.id, "department_id": department_id,
                                "no_cost": note is not None},
            notes=note, for_department_id=department_id)
        if done >= set(card.department_ids or []):
            card.status = "ready"
            await session.flush()
            from app.services.notification_service import NotificationService
            post = change.status in POST_APPROVAL
            if card.id in await no_cost_ids(session, [card]):
                # nothing to price: no version, no supplement (R5)
                what = "Confirm to the customer at no cost"
            else:
                what = "Send supplement" if post else "Revise offer"
            title = f"{what}: scope change re-costed: {change.change_number}"[:255]
            # spec §0: involved people only: the Sales contact (the row shows
            # to all of Sales); no owner: Sales
            if change.sales_owner_id is not None:
                await NotificationService.notify_once(
                    session, [change.sales_owner_id], kind="task_new",
                    subject_key=f"scope_change:{card.id}:ready", title=title,
                    body=label(card), link=f"/changes/{change.id}?tab=offer")
            else:
                await NotificationService.notify_departments_once(
                    session, [d for d in [await ScopeChangeService._dept_id(session, "Sales")]
                              if d is not None], change=change, kind="task_new",
                    subject_key=f"scope_change:{card.id}:ready", title=title,
                    body=label(card), link=f"/changes/{change.id}?tab=offer")
        await session.flush()
        return card

    # ------------------------------------------------------------------
    # 1b. missing info is a question (spec §6 step 1)
    # ------------------------------------------------------------------
    @staticmethod
    def customer_copy(change: ChangeRequest, card: ChangeScopeChange) -> Optional[str]:
        """The mail text Sales copies for the card's question (spec §0 [R4])."""
        if not card.question:
            return None
        # F9: no CR / article / project number of ours in the customer copy
        from app.services.customer_refs import customer_title
        name = customer_title(change.title)
        where = f" for part {card.part_number}" if card.part_number else ""
        return "\n".join([
            f"Subject: {name}: question on your change wish",
            "", "Hello,", "",
            f"For your wish \"{card.what}\"{where} on {name} "
            "we need your answer before we can cost it:",
            "", card.question["text"],
            "", "Thank you, and best regards"])

    @staticmethod
    async def _notify_sales(session: AsyncSession, change: ChangeRequest, *,
                            subject_key: str, title: str, body: str, skip: int) -> None:
        """The Sales contact (the row shows to all of Sales); none: Sales."""
        from app.services.notification_service import NotificationService
        if change.sales_owner_id is not None:
            if change.sales_owner_id != skip:
                await NotificationService.notify_once(
                    session, [change.sales_owner_id], kind="task_new",
                    subject_key=subject_key, title=title[:255], body=body,
                    link=f"/changes/{change.id}?tab=offer")
            return
        await NotificationService.notify_departments_once(
            session, [d for d in [await ScopeChangeService._dept_id(session, "Sales")]
                      if d is not None], change=change, kind="task_new",
            subject_key=subject_key, title=title[:255], body=body,
            link=f"/changes/{change.id}?tab=offer")

    @staticmethod
    async def ask(session: AsyncSession, change: ChangeRequest, card_id: int,
                  user: User, text: Optional[str]) -> ChangeScopeChange:
        """Missing info on a requested card is a question to the customer:
        the lead (run team) or Sales asks; Sales keeps it (a task with the
        mail text to copy); it holds the accept until Sales files the
        customer's answer. A refusal does not wait for it."""
        card = await ScopeChangeService._card(session, change, card_id)
        if card.status != "requested":
            raise ChangeError(
                f"Scope change #{card.id} is {card.status}: a question is asked "
                "before it is decided")
        if card.question_open:
            raise ChangeError(
                f"Scope change #{card.id} already asks: {card.question['text']}")
        if not await ScopeChangeService.may_request(session, change, user):
            raise ScopeChangeForbidden(
                "The change lead, Project Management or Sales asks the customer")
        text = " ".join((text or "").split())
        if len(text) < 10:
            raise ChangeError(
                "Say what the customer must answer, in a sentence (10+ characters), "
                "e.g. 'Which grain: K31 or K45?'")
        card.question = {"text": text[:1000], "by": user.id,
                         "at": datetime.utcnow().isoformat()}
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scope_change_question",
            f"Scope change #{card.id}: question to the customer: {text}"[:500], user.id,
            new_value={"scope_change_id": card.id}, notes=text)
        await ScopeChangeService._notify_sales(
            session, change, subject_key=f"scope_change:{card.id}:question",
            title=f"Ask the customer: scope change #{card.id}: {change.change_number}",
            body=text, skip=user.id)
        return card

    @staticmethod
    async def answer(session: AsyncSession, change: ChangeRequest, card_id: int,
                     user: User, answer: Optional[str], *,
                     attachment_id: Optional[int] = None, ref: Optional[str] = None,
                     from_customer: bool = False) -> ChangeScopeChange:
        """Sales files the customer's answer (Confirmed: the customer's mail
        or document filed on the change, or its reference); the lead
        decides the card next."""
        card = await ScopeChangeService._card(session, change, card_id)
        if not card.question_open:
            raise ChangeError(f"Scope change #{card.id} has no open question")
        r = await ScopeChangeService._roles(session, change, user)
        if not r["sales"] and user.effective_role != "admin":
            raise ScopeChangeForbidden("Sales files the customer's answer")
        answer = " ".join((answer or "").split())
        if len(answer) < 2:
            raise ChangeError("Write the customer's answer")
        if attachment_id:
            att = await ChangeService.customer_evidence_file(
                session, change, attachment_id, from_customer=from_customer,
                actor_id=user.id, what="Pick the customer's mail or file filed on this change")
            evidence = f"Mail: {att.filename}"[:255]
        else:
            from app.services.cm_rules import reference_refusal
            why = reference_refusal(ref, "The customer's mail or its reference",
                                    "Mail 17 Oct from the buyer")
            if why:
                raise ChangeError(why)
            evidence = ref.strip()[:255]
        card.question = {**card.question, "answer": answer[:1000], "ref": evidence,
                         "attachment_id": int(attachment_id) if attachment_id else None,
                         "answered_by": user.id,
                         "answered_at": datetime.utcnow().isoformat()}
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scope_change_answered",
            f"Scope change #{card.id}: the customer answered ({evidence}): {answer}"[:500],
            user.id, new_value={"scope_change_id": card.id}, notes=answer)
        from app.services.notification_service import NotificationService
        if change.lead_id and change.lead_id != user.id:
            await NotificationService.notify_once(
                session, [change.lead_id], kind="decision_needed",
                subject_key=f"scope_change:{card.id}:answered",
                title=f"Customer answered: accept or refuse scope change #{card.id}: "
                      f"{change.change_number}"[:255],
                body=answer, link=f"/changes/{change.id}?tab=offer")
        return card

    @staticmethod
    async def told(session: AsyncSession, change: ChangeRequest, card_id: int,
                   user: User, ref: Optional[str]) -> ChangeScopeChange:
        """Sales told the customer: the scope change is refused, or (every
        department re-costed it at no cost) it is done at no price change.
        The second settles the card (accepted, no offer) and may be the last
        thing the approval or an open price waited on."""
        card = await ScopeChangeService._card(session, change, card_id)
        free = card.status == "ready" and card.id in await no_cost_ids(session, [card])
        if not free and (card.status != "refused" or card.told_at is not None):
            raise ChangeError(
                "Nothing to tell: the card is not a refusal waiting to be told, "
                "nor re-costed at no cost")
        if not (await ScopeChangeService._roles(session, change, user))["sales"] \
                and user.effective_role != "admin":
            raise ScopeChangeForbidden("Sales tells the customer")
        from app.services.cm_rules import reference_refusal
        why = reference_refusal(ref, "The mail to the customer or its reference",
                                "Mail 16 Oct to the buyer")
        if why:
            raise ChangeError(why)
        now = datetime.utcnow()
        card.told_ref, card.told_by, card.told_at = ref.strip()[:255], user.id, now
        if free:
            card.status, card.closed_at = "accepted", now
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scope_change_accepted" if free else "scope_change_told",
            (f"Scope change {label(card)}: no cost impact, customer told it "
             f"comes at no price change ({card.told_ref})" if free else
             f"Scope change #{card.id}: customer told it is refused ({card.told_ref})"),
            user.id, new_value={"scope_change_id": card.id, "no_cost": free})
        if free:
            await ScopeChangeService._maybe_close_price(session, change, user.id)
            await ChangeService.try_auto_approve(session, change, user.id)
        return card

    # ------------------------------------------------------------------
    # 3. accepted (hooks from OfferService.send and the customer answer)
    # ------------------------------------------------------------------
    @staticmethod
    async def on_offer_sent(session: AsyncSession, change: ChangeRequest, offer,
                            actor_id: int) -> list[str]:
        """An offer (or supplement) sent: cards ready go into it ('offered');
        cards still being re-costed are named on it as "subject to final
        costing" and stay open. Returns those lines (the offer prints them)."""
        if not cm_switches.on("COMMERCIAL_V2"):
            return []
        lines = []
        for card in await open_cards(session, change):
            if card.status == "ready":
                card.status, card.offer_id = "offered", offer.id
                await ChangeService.append_changelog(
                    session, change, "scope_change_offered",
                    f"Scope change #{card.id} in v{offer.version}", actor_id,
                    new_value={"scope_change_id": card.id, "offer_id": offer.id})
            elif card.status in ("requested", "recosting"):
                lines.append(f"Scope change {card.part_number or ('#' + str(card.id))}: "
                             "subject to final costing")
        await session.flush()
        return lines

    @staticmethod
    async def on_customer_answer(session: AsyncSession, change: ChangeRequest, offer,
                                 accepted: bool, actor_id: int) -> None:
        """The customer's answer to the offer that carries cards settles
        them: accepted, or dropped on a decline."""
        if offer is None:
            return
        for card in await open_cards(session, change):
            if card.status == "offered" and card.offer_id is not None \
                    and card.offer_id <= offer.id:
                card.status = "accepted" if accepted else "dropped"
                card.closed_at = datetime.utcnow()
                await ChangeService.append_changelog(
                    session, change, f"scope_change_{card.status}",
                    f"Scope change #{card.id} {card.status} with v{offer.version}",
                    actor_id, new_value={"scope_change_id": card.id})
        await session.flush()

    @staticmethod
    async def on_absorbed(session: AsyncSession, change: ChangeRequest, actor_id: int) -> None:
        """Absorb (HARD #9's exit) settles the cards opened after the
        customer's yes: their money is not asked."""
        for card in await open_cards(session, change):
            if card.post_accept:
                card.status, card.closed_at = "absorbed", datetime.utcnow()
                await ChangeService.append_changelog(
                    session, change, "scope_change_absorbed",
                    f"Scope change #{card.id} absorbed", actor_id,
                    new_value={"scope_change_id": card.id})
        await session.flush()

    @staticmethod
    async def _maybe_close_price(session: AsyncSession, change: ChangeRequest,
                                 actor_id: int) -> None:
        """A card settled with no money asked (refused, moved to its own
        change, or confirmed at no cost) closes the open price again, but
        only when the price was opened by cards alone: every price_open row
        since it last closed is a card's opening, each of those cards is
        settled that way, and no card opened after approval is still open.
        Any other cause (a supplement out or declined, a quote above the
        estimate, a flip after approval, a start at risk) keeps it open:
        HARD #9's exits are the customer's acceptance or Absorb (4-eyes)."""
        if not change.price_open:
            return
        cards_now = await cards(session, [change.id])
        if any(c.post_accept and c.status in SCOPE_OPEN for c in cards_now):
            return
        import json
        import re
        from app.models.change import ChangeChangelog
        rows = (await session.execute(
            select(ChangeChangelog.action, ChangeChangelog.action_description,
                   ChangeChangelog.old_value, ChangeChangelog.new_value).where(
                ChangeChangelog.change_id == change.id,
                ChangeChangelog.field_name == "price_open")
            .order_by(ChangeChangelog.id.desc()))).all()
        chain, first_was = [], None
        for action, text, was, value in rows:
            if value == json.dumps(False):
                break                       # the price closed here last
            chain.append((action, text or ""))
            first_was = was
        if not chain or first_was != json.dumps(False):
            return      # opened with no row first (a legacy cause): keep it
        by_id = {c.id: c for c in cards_now}
        for action, text in chain:
            m = re.match(rf"{re.escape(_OPENED_BY)}(\d+) ", text)
            card = by_id.get(int(m.group(1))) if (m and action == "price_opened") else None
            if card is None or not _settled_without_money(card):
                return
        change.price_open = False
        await ChangeService.append_changelog(
            session, change, "price_closed",
            "Open price closed: the scope change that opened it asks no money",
            actor_id, field_name="price_open", old_value=True, new_value=False)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def serialize(session: AsyncSession, change: ChangeRequest) -> list[dict]:
        rows = await cards(session, [change.id])
        if not rows:
            return []
        dept_ids = {d for c in rows for d in (c.department_ids or [])}
        names = dict((await session.execute(
            select(Department.id, Department.name).where(Department.id.in_(dept_ids))
        )).all()) if dept_ids else {}
        from app.services.change_plan_service import ChangePlanService
        users = await ChangePlanService._user_names(
            session, [c.requested_by for c in rows] + [c.decided_by for c in rows]
            + [(c.question or {}).get("by") for c in rows])
        free = await no_cost_ids(session, rows)
        out = []
        for c in rows:
            done = set(c.departments_done or [])
            out.append({
                "id": c.id, "kind": c.kind, "status": c.status,
                "part_number": c.part_number, "what": c.what,
                "expects_by": c.expects_by, "evidence_ref": c.evidence_ref,
                "post_accept": c.post_accept,
                "requested_by_name": users.get(c.requested_by), "requested_at": c.requested_at,
                "decided_by_name": users.get(c.decided_by), "decision_note": c.decision_note,
                "departments": [{"id": d, "name": names.get(d, f"dept {d}"),
                                 "done": d in done} for d in (c.department_ids or [])],
                "waiting_for": [names.get(d, f"dept {d}") for d in (c.department_ids or [])
                                if d not in done] if c.status == "recosting" else [],
                "recost_due": c.recost_due, "offer_id": c.offer_id,
                "new_change_id": c.new_change_id, "told_at": c.told_at,
                "told_ref": c.told_ref,
                # ready with no cost anywhere: Sales confirms, nothing to price
                "no_cost": c.id in free,
                # step 1: missing info is a question (Sales asks the customer)
                "question": ({**{k: c.question.get(k) for k in (
                    "text", "at", "answer", "ref", "answered_at")},
                    "open": c.question_open,
                    "by_name": users.get(c.question.get("by")),
                    "customer_copy": (ScopeChangeService.customer_copy(change, c)
                                      if c.question_open else None)}
                    if c.question else None),
            })
        return out
