"""Per-department costing pipeline (live ECR test, 2026-10-14).

A department does not wait for the whole team: once it has submitted its
assessment as feasible (or feasible with conditions) and its checklist owes a
cost input (ChangeService.owes_costing_input), it opens, fills and FINALIZES
its own costing while the change is still in assessment. The change still
moves in_assessment -> costing only when every assessment is in; a department
that finalized early stays finalized, so costing can be complete the moment
the change enters it.

Finalized is the department's answer, stored on its assessment row
(details.costing_finalized_at / _by, no migration). The row is the right
home: when the assessment is superseded (back to scoping after a "not
feasible") the rows go and with them every finalization and every cost line
(lines hang off the rows and are deleted with them). Positions hang off the
change and stay as the department's draft, but the summation and the quote
basis leave out the positions of a department whose answer was superseded
until it answers feasible again (uncounted_position_department_ids), so a
torn-down routing prices nothing it no longer stands behind.

A finalization covers the answers it was given on: a later-stage row of the
same department submitted after costing_finalized_at (stages wake at
costing, EarlyStageService.wake_later_stages) makes the department draft
again, back in costing_pending with a costing_input task.

Rules:
- window: the change is in costing, or in assessment and the department owes
  costing (submitted feasible, checklist marked something impacted);
- a finalized department's members no longer write its figures (PM and admin
  still may, as everywhere in costing); the department reopens its own input
  while costing is open (in assessment or costing);
- finalizing needs at least one cost line with non-zero hours or money, or
  one position: the zero lines seeded from the checklist are not an answer.
"""
from datetime import datetime
import json
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import User

COSTING_VERDICTS = ("feasible", "feasible_with_conditions")
# The statuses a department's costing can be open in.
OPEN_STATUSES = ("in_assessment", "costing")


class EarlyCostingError(ValueError):
    """Refused finalize/reopen; mapped to HTTP 400 (403 for rights)."""


class EarlyCostingForbidden(EarlyCostingError):
    pass


def _rows(change: ChangeRequest, department_id: int) -> list[ChangeAssessment]:
    return sorted((a for a in change.assessments if a.department_id == department_id),
                  key=lambda a: (a.stage_order, a.id or 0))


def owes(change: ChangeRequest, department_id: int) -> bool:
    """The department answered feasible and its answer owes a cost input."""
    from app.services.change_service import ChangeService
    return any(a.verdict in COSTING_VERDICTS and ChangeService.owes_costing_input(a)
               for a in _rows(change, department_id))


def has_costing_verdict(change: ChangeRequest, department_id: int) -> bool:
    return any(a.verdict in COSTING_VERDICTS for a in _rows(change, department_id))


def costing_open_for(change: ChangeRequest, department_id: int) -> bool:
    """Is the costing window open for this department right now?"""
    if change.status == "costing":
        return True
    return change.status == "in_assessment" and owes(change, department_id)


def _parse(ts) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except (TypeError, ValueError):
        return None


def finalized_row(change: ChangeRequest, department_id: int) -> Optional[ChangeAssessment]:
    """The row carrying the department's finalization, while it still holds:
    no row of the department was submitted after it (a later stage woken at
    costing reopens the answer the finalization was given on)."""
    rows = _rows(change, department_id)
    row = next((a for a in rows if a.details_dict.get("costing_finalized_at")), None)
    if row is None:
        return None
    at = _parse(row.details_dict.get("costing_finalized_at"))
    if at is not None and any(a.submitted_at is not None and a.submitted_at > at
                              for a in rows):
        return None
    return row


def is_finalized(change: ChangeRequest, department_id: int) -> bool:
    return finalized_row(change, department_id) is not None


def owed_department_ids(change: ChangeRequest) -> list[int]:
    """Departments that owe a cost input: a feasible answer that is not a
    "nothing impacted"."""
    return sorted({a.department_id for a in change.assessments
                   if owes(change, a.department_id)})


def finalized_department_ids(change: ChangeRequest) -> list[int]:
    return sorted({a.department_id for a in change.assessments
                   if is_finalized(change, a.department_id)})


async def uncounted_position_department_ids(session: AsyncSession,
                                            change_id: int) -> set[int]:
    """Departments whose positions the summation and the quote basis leave
    out: their assessment was superseded (back to scoping after a "not
    feasible", see EarlyStageService.supersede_assessments) and they have no
    feasible answer on record since. The positions stay as the department's
    draft and count again once it answers feasible on the rebuilt routing.
    A department never routed (a position Project Management filed for it)
    is not affected: nothing of it was superseded."""
    from app.models.change import ChangeChangelog
    superseded: set[int] = set()
    for raw in (await session.execute(
            select(ChangeChangelog.old_value).where(
                ChangeChangelog.change_id == change_id,
                ChangeChangelog.action == "assessment_superseded"))).scalars():
        try:
            dept = (json.loads(raw) or {}).get("department_id") if raw else None
        except (TypeError, ValueError):
            dept = None
        if isinstance(dept, int):
            superseded.add(dept)
    if not superseded:
        return set()
    answered = set((await session.execute(
        select(ChangeAssessment.department_id).where(
            ChangeAssessment.change_id == change_id,
            ChangeAssessment.verdict.in_(COSTING_VERDICTS)))).scalars().all())
    return superseded - answered


async def clear_finalization(session: AsyncSession, change: ChangeRequest,
                             department_id: int, actor_id: Optional[int],
                             reason: str) -> bool:
    """Reopen a department's finalization as a side effect (no rights check:
    the caller already holds the right for the act that caused it). Audited
    as costing_input_reopened with the reason. False: nothing to reopen."""
    from app.services.change_service import ChangeService
    if not is_finalized(change, department_id):
        return False
    for a in _rows(change, department_id):
        if a.details_dict.get("costing_finalized_at"):
            _set_details(a, costing_finalized_at=None, costing_finalized_by=None,
                         costing_no_cost=None)
    await session.flush()
    await ChangeService.append_changelog(
        session, change, "costing_input_reopened",
        f"Costing input reopened for dept {department_id}: {reason}",
        actor_id, new_value={"department_id": department_id, "reason": reason},
        notes=reason, for_department_id=department_id)
    return True


def _set_details(a: ChangeAssessment, **kv) -> None:
    d = a.details_dict
    for k, v in kv.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    a.details = json.dumps(d) if d else None


async def _may_act(session: AsyncSession, change: ChangeRequest,
                   department_id: int, actor: User) -> bool:
    """The department itself, or the people who run costing (PM, admin)."""
    from app.services.meeting_service import MeetingService
    from app.services.workflow_service import WorkflowService
    if (actor.effective_role == "admin"
            or await MeetingService.user_is_pm_member(session, actor)):
        return True
    return await WorkflowService.actor_in_department(session, actor, department_id)


async def _has_answer(session: AsyncSession, change: ChangeRequest,
                      department_id: int) -> bool:
    """A cost line with hours or money, the assessment-effort hours, or a
    position. The zero-hour lines
    seeded from the checklist (CostService.seed_from_checklist) are a
    starting grid, not an answer."""
    from app.models.change_cost import AssessmentCostLine, CostingPosition
    L = AssessmentCostLine
    lines = (await session.execute(
        select(func.count(L.id))
        .join(ChangeAssessment, ChangeAssessment.id == L.assessment_id)
        .where(ChangeAssessment.change_id == change.id,
               ChangeAssessment.department_id == department_id,
               or_(func.coalesce(L.demand_hours, 0) != 0,
                   func.coalesce(L.internal_cost, 0) != 0,
                   func.coalesce(L.external_cost, 0) != 0,
                   func.coalesce(L.minutes_per_part, 0) != 0)))).scalar() or 0
    if lines:
        return True
    # Audit 2026-10-29 (P2-2): hours on the standing "Assessment effort" row
    # live on the assessment (effort_hours) and are an answer too
    if any((a.effort_hours or 0) > 0 for a in _rows(change, department_id)):
        return True
    positions = (await session.execute(
        select(func.count(CostingPosition.id)).where(
            CostingPosition.change_id == change.id,
            CostingPosition.department_id == department_id))).scalar() or 0
    return bool(positions)


async def finalize(session: AsyncSession, change: ChangeRequest,
                   department_id: int, actor: User) -> ChangeAssessment:
    from app.services.change_service import ChangeService
    if not await _may_act(session, change, department_id, actor):
        raise EarlyCostingForbidden(
            "Only a member of that department, Project Management or an admin "
            "may finalize its costing")
    if change.status not in OPEN_STATUSES:
        raise EarlyCostingError("Costing is not open on this change")
    if not has_costing_verdict(change, department_id):
        raise EarlyCostingError(
            "The department has not submitted a feasible assessment: there is "
            "no costing to finalize")
    # owes() itself, not costing_open_for: in costing the window is open for
    # everybody, but a department whose checklist marked nothing impacted
    # still has nothing to finalize.
    if not owes(change, department_id):
        raise EarlyCostingError(
            "The department's assessment marked nothing impacted: it owes no "
            "costing input")
    if is_finalized(change, department_id):
        raise EarlyCostingError("The department's costing is already finalized")
    await _refuse_while_waiting(session, change, department_id)
    await _refuse_thin_basis(session, change, department_id)
    await _refuse_transport_missing(session, change, department_id)
    empty, _ = await _empty_lines(session, change, department_id)
    if empty:
        raise EarlyCostingError(". ".join(empty))
    if await _costing_hours_missing(session, change, department_id):
        raise EarlyCostingError("Book the hours you spent on costing first (Book hours)")
    if await _support_hours_missing(session, change, department_id):
        raise EarlyCostingError("Enter the implementation support hours first (0 is allowed)")
    if not await _has_answer(session, change, department_id):
        raise EarlyCostingError(
            "Nothing to finalize yet: enter hours or an amount on at least one "
            "cost line, or add a position (the zero lines seeded from the "
            "checklist are not an answer)")
    from app.services import supplier_wait_service as _sw
    for x in await _sw.open_waits(session, [change.id], "costing"):
        if x.department_id == department_id:
            x.closed_at = datetime.utcnow()
            x.closed_by = actor.id
            x.close_reason = "not_received"
    anchor = next((a for a in _rows(change, department_id)
                   if a.verdict in COSTING_VERDICTS), None)
    _set_details(anchor, costing_finalized_at=datetime.utcnow().isoformat(),
                 costing_finalized_by=actor.id)
    await session.flush()
    await ChangeService.append_changelog(
        session, change, "costing_finalized",
        f"Costing finalized for dept {department_id}"
        + (" during assessment" if change.status == "in_assessment" else ""),
        actor.id, new_value={"department_id": department_id,
                             "status": change.status},
        for_department_id=department_id)
    # HARD #8: finalized above the approved total -> the approver again
    await ChangeService.withdraw_outgrown_internal_approval(session, change, actor.id)
    # A6-02: the last finalize makes the internal approval owed
    from app.services.decision_notices import internal_approval_owed
    await internal_approval_owed(session, change, actor.id)
    return anchor


async def _refuse_while_waiting(session: AsyncSession, change: ChangeRequest,
                                department_id: int) -> None:
    """Spec §4/§5 (ASSESSMENT_V2): an open supplier wait holds the
    department's costing until the quote is in or the lead prices it on the
    estimate."""
    from app.services import cm_switches, supplier_wait_service as waits
    if not cm_switches.on("ASSESSMENT_V2"):
        return
    w = (await waits.open_by_department(session, [change.id], "costing")).get(
        (change.id, department_id))
    if w is not None:
        # Christoph 2026-11-08: a quoted line needs one quote; the shops still
        # out are closed as not received at finalize
        from app.models.change_cost import CostingPosition
        holding = []
        for x in await waits.open_waits(session, [change.id], "costing"):
            if x.department_id != department_id:
                continue
            pos = await session.get(CostingPosition, x.position_id) if x.position_id else None
            if pos is not None and pos.offers:
                continue
            holding.append(x)
        w = holding[0] if holding else None
    if w is not None:
        raise EarlyCostingError(
            f"{waits.line(w)}: close the wait when the quote is in, or the lead "
            "decides to price it on your estimate")


def transport_missing(offer) -> bool:
    """Christoph 2026-11-08: "transport none is not ok, mark red but 0 is
    allowed". A supplier quote states its transport: 0 (shipping_included
    False, shipping_cost 0) counts as entered, an empty field
    (shipping_cost None, e.g. shipping_included True with no amount) does not."""
    return offer.shipping_cost is None


def _transport_gaps(positions) -> list[tuple]:
    """(position, offer) of every counted offer of a quoted external line,
    spare parts included, whose transport is not entered."""
    out = []
    for p in positions:
        if p.kind != "external" or p.pricing != "quote" or not p.offers:
            continue
        for o in p.counted_offers(p.favorite_offer):
            if transport_missing(o):
                out.append((p, o))
    return out


async def _refuse_transport_missing(session: AsyncSession, change: ChangeRequest,
                                    department_id: int) -> None:
    from app.models.change_cost import CostingPosition
    rows = (await session.execute(select(CostingPosition).where(
        CostingPosition.change_id == change.id,
        CostingPosition.department_id == department_id,
        CostingPosition.kind == "external"))).scalars().all()
    gaps = _transport_gaps(rows)
    if gaps:
        raise EarlyCostingError(
            "Enter the transport of the quote (0 is allowed): "
            + ", ".join(f"'{p.label}' ({o.vendor_name})" for p, o in gaps))


async def _refuse_thin_basis(session: AsyncSession, change: ChangeRequest,
                            department_id: int) -> None:
    """Spec §4 costing positions (C25, ASSESSMENT_V2): every external number
    stands on something. A quoted position finalizes only with its counted
    offer(s) carrying the supplier's quote number and the quote file; an
    estimated one names its reference (earlier tool, supplier figure +
    date) or the part it is the same as and what differs; a quote that
    arrived after an offer or approval on the estimate is compared with it
    first."""
    from app.models.change import ChangeAttachment
    from app.models.change_cost import CostingPosition
    from app.services import cm_switches
    from app.services.cm_rules import reference_refusal, says_what
    if not cm_switches.on("ASSESSMENT_V2"):
        return
    positions = (await session.execute(
        select(CostingPosition).where(
            CostingPosition.change_id == change.id,
            CostingPosition.department_id == department_id,
            CostingPosition.kind == "external"))).scalars().all()
    if not positions:
        return
    offer_ids = [o.id for p in positions for o in p.offers]
    filed = set((await session.execute(
        select(ChangeAttachment.costing_offer_id).where(
            ChangeAttachment.costing_offer_id.in_(offer_ids)))).scalars().all()) \
        if offer_ids else set()
    quotes, estimates, checks = [], [], []
    for p in positions:
        if "spare part" in ((p.notes or "") + " " + p.label).lower() and p.pricing == "quote":
            if not p.counted_offers(p.favorite_offer):
                quotes.append(f"'{p.label}' (no offer, or no favourite among several)")
            continue
        if p.estimate_check == "pending":
            checks.append(f"'{p.label}'")
        if p.pricing == "quote":
            counted = p.counted_offers(p.favorite_offer)
            if not counted:
                quotes.append(f"'{p.label}' (no offer, or no favourite among several)")
            for o in counted:
                # A3-10 (R4): the quote number is a reference id, not 'tbd'.
                # Audit 2026-10-29 (P2-1): name only what is missing, the
                # file was attached and the message still asked for it
                missing = ([] if reference_refusal(o.quote_ref) is None
                           else ["the quote number (field 'Quote no.' under the offer)"]) \
                    + ([] if o.id in filed else ["the quote file"])
                if missing:
                    quotes.append(f"'{p.label}' ({o.vendor_name}: {' and '.join(missing)})")
        elif p.est_cost:
            ok = (p.basis_part_id is not None and len(p.basis_differs or "") >= 5
                  if p.basis == "same_as" else says_what(p.basis_ref))
            if not ok:
                estimates.append(f"'{p.label}'")
    why = []
    if quotes:
        why.append("Quoted positions are missing: " + ", ".join(quotes))
    if estimates:
        why.append("Estimated positions need their basis: the reference (an "
                   "earlier tool, the supplier's figure and its date) or 'same "
                   "as' a part and what differs: " + ", ".join(estimates))
    if checks:
        why.append("Compare the quote with your estimate first (within +5 % or "
                   "above by how much): " + ", ".join(checks))
    if why:
        raise EarlyCostingError(". ".join(why))


async def _empty_lines(session: AsyncSession, change: ChangeRequest,
                       department_id: int) -> tuple[list[str], list[int]]:
    """Christoph 2026-11-08: a line carried from the assessment (or added)
    with nothing on it: an external estimate without a price, an own-time
    line without hours. Returns (reasons, position ids)."""
    from app.models.change_cost import CostingPosition
    rows = (await session.execute(select(CostingPosition).where(
        CostingPosition.change_id == change.id,
        CostingPosition.department_id == department_id,
        CostingPosition.kind.in_(("external", "own_time"))))).scalars().all()
    price = [p for p in rows if p.kind == "external" and p.pricing != "quote"
             and not (p.est_cost or 0) > 0]
    hours = [p for p in rows if p.kind == "own_time" and not (p.hours or 0) > 0]
    why = []
    if price:
        why.append("Enter the price of: " + ", ".join(f"'{p.label}'" for p in price))
    if hours:
        why.append("Enter the hours of: " + ", ".join(f"'{p.label}'" for p in hours))
    return why, [p.id for p in price + hours]


async def _costing_hours_missing(session: AsyncSession, change: ChangeRequest,
                                 department_id: int) -> bool:
    """Christoph 2026-11-08: costing is work too: at least one booking of the
    department after its assessment was submitted (switch
    ASSESSMENT_HOURS_REQUIRED)."""
    from app.services import cm_switches
    from app.models.change_impl import ImplementationBooking
    if not cm_switches.ASSESSMENT_HOURS_REQUIRED:
        return False
    since = max((a.submitted_at for a in _rows(change, department_id) if a.submitted_at),
                default=None)
    q = select(func.count(ImplementationBooking.id)).where(
        ImplementationBooking.change_id == change.id,
        ImplementationBooking.department_id == department_id)
    if since is not None:
        q = q.where(ImplementationBooking.booked_at >= since)
    return not ((await session.execute(q)).scalar() or 0)


async def _support_hours_missing(session: AsyncSession, change, department_id: int) -> bool:
    """Christoph 2026-11-08: the implementation support estimate is mandatory
    (red until entered; 0 is an answer)."""
    hours = (await session.execute(select(CostingPosition.hours).where(
        CostingPosition.change_id == change.id,
        CostingPosition.department_id == department_id,
        CostingPosition.kind == "support_effort"))).scalars().all()
    return not any(h is not None for h in hours)


async def finalize_reasons(session: AsyncSession, change: ChangeRequest,
                           department_id: int) -> dict:
    """Christoph 2026-11-08: what still stops the department's Finalize, one
    short item per point and line (banner tag + words), and the lines that
    miss something (red marks). Same rules as finalize()."""
    from app.models.change import ChangeAttachment
    from app.models.change_cost import CostingPosition
    from app.services import cm_switches, supplier_wait_service as waits
    from app.services.cm_rules import reference_refusal, says_what
    from app.core.display import fmt_date
    if change.status not in OPEN_STATUSES or not owes(change, department_id) \
            or is_finalized(change, department_id):
        return {"reasons": [], "items": [], "position_ids": []}
    items: list[dict] = []
    ids: list[int] = []
    rows = (await session.execute(select(CostingPosition).where(
        CostingPosition.change_id == change.id,
        CostingPosition.department_id == department_id))).scalars().all()
    labels = {p.id: p.label for p in rows}
    if cm_switches.on("ASSESSMENT_V2"):
        quoted_lines = {p.id for p in rows if p.offers}
        for w in await waits.open_waits(session, [change.id], "costing"):
            if w.department_id == department_id and w.position_id not in quoted_lines:
                where = f" ({labels[w.position_id]})" if w.position_id in labels else ""
                items.append({"tag": "waiting", "text":
                              f"{w.vendor_name}{where}: quote expected {fmt_date(w.expected_by)}"})
    ext = [p for p in rows if p.kind == "external"]
    offer_ids = [o.id for p in ext for o in p.offers]
    filed = set((await session.execute(
        select(ChangeAttachment.costing_offer_id).where(
            ChangeAttachment.costing_offer_id.in_(offer_ids)))).scalars().all()) if offer_ids else set()
    for p in ext:
        if "spare part" in ((p.notes or "") + " " + p.label).lower() and not (p.quantity or 0) > 0:
            items.append({"tag": "amount_missing", "text": f"{p.label}: enter the amount"})
            ids.append(p.id)
        if p.estimate_check == "pending":
            items.append({"tag": "compare", "text": f"{p.label}: compare the quote with your estimate"})
            ids.append(p.id)
        if p.pricing == "quote":
            if not p.offers:
                items.append({"tag": "quote_missing", "text": f"{p.label}: no quote received yet"})
                ids.append(p.id)
                continue
            fav = p.favorite_offer
            if not p.counted_offers(fav):
                items.append({"tag": "favourite", "text": f"{p.label}: pick the favourite"})
                ids.append(p.id)
                continue
            for o in p.counted_offers(fav):
                if transport_missing(o):
                    items.append({"tag": "transport_missing",
                                  "text": f"{p.label}: {o.vendor_name} transport missing (0 allowed)"})
                    ids.append(p.id)
            # a spare part may be a catalogue buy: its quote file / no. is optional
            spare = "spare part" in ((p.notes or "") + " " + p.label).lower()
            for o in ([] if spare else p.counted_offers(fav)):
                miss = ([] if reference_refusal(o.quote_ref) is None else ["quote no."]) \
                    + ([] if o.id in filed else ["quote file"])
                if miss:
                    items.append({"tag": "quote_missing",
                                  "text": f"{p.label} – {o.vendor_name}: {' and '.join(miss)} missing"})
                    ids.append(p.id)
        else:
            if not (p.est_cost or 0) > 0:
                items.append({"tag": "price_missing", "text": f"{p.label}: enter the estimated price"})
                ids.append(p.id)
            elif not (p.basis_part_id is not None and len(p.basis_differs or "") >= 5
                      if p.basis == "same_as" else says_what(p.basis_ref)):
                items.append({"tag": "basis_missing", "text": f"{p.label}: say what the estimate is based on"})
                ids.append(p.id)
    for p in rows:
        if p.kind == "own_time" and not (p.hours or 0) > 0:
            items.append({"tag": "hours_missing", "text": f"{p.label}: enter the hours"})
            ids.append(p.id)
    if not items and not await _has_answer(session, change, department_id):
        items.append({"tag": "empty", "text": "Nothing entered yet: hours or an amount on one line"})
    if await _costing_hours_missing(session, change, department_id):
        items.append({"tag": "book_hours", "text": "Book the hours you spent on costing (Book hours)"})
    if await _support_hours_missing(session, change, department_id):
        items.append({"tag": "support_hours", "text": "Implementation support: enter the hours (0 allowed)"})
    # Christoph 2026-11-08: the quote status per line as info (no blocker):
    # received quotes, and shops still out on a line that already has one
    info: list[dict] = []
    for p in ext:
        if p.pricing != "quote":
            continue
        for o in p.offers:
            info.append({"tag": "received", "info": True,
                         "text": f"{p.label} – {o.vendor_name}: quote received"
                         + (" (favourite)" if o.favorite else "")})
    if cm_switches.on("ASSESSMENT_V2"):
        quoted = {p.id for p in ext if p.offers}
        for w in await waits.open_waits(session, [change.id], "costing"):
            if w.department_id == department_id and w.position_id in quoted:
                info.append({"tag": "waiting_info", "info": True,
                             "text": f"{w.vendor_name} ({labels.get(w.position_id, '')}): still out, "
                                     "closed as not received at finalize"})
    return {"reasons": [i["text"] for i in items], "items": items + info,
            "position_ids": sorted(set(ids))}


#: Spec §4 "<Dept> has no cost" (C18): why a department that owes a costing
#: input has none. absorbed carries the hours it absorbs (0 refused).
NO_COST_REASONS = ("no_work", "absorbed", "supplier")


def no_cost_of(change: ChangeRequest, department_id: int) -> Optional[dict]:
    """The department's "no cost" answer while its finalization holds."""
    row = finalized_row(change, department_id)
    return row.details_dict.get("costing_no_cost") if row is not None else None


async def no_cost(session: AsyncSession, change: ChangeRequest, department_id: int,
                  actor: User, reason: str, hours: Optional[float] = None
                  ) -> ChangeAssessment:
    """C18 (ASSESSMENT_V2): one button instead of an invented zero. The
    department says it has no cost: no work / absorbed (with the hours it
    absorbs, 0 refused) / the supplier does it (and pays). Refused while the
    department has a costing position, a non-zero cost line or an open
    supplier wait, naming the colleague. Finalizes its costing."""
    from app.models.change_cost import AssessmentCostLine, CostingPosition
    from app.services import cm_switches, supplier_wait_service as waits
    from app.services.change_service import ChangeService
    if not cm_switches.on("ASSESSMENT_V2"):
        raise EarlyCostingError("'No cost' is switched off (ASSESSMENT_V2)")
    if not await _may_act(session, change, department_id, actor):
        raise EarlyCostingForbidden(
            "Only a member of that department, Project Management or an admin "
            "may say the department has no cost")
    if change.status not in OPEN_STATUSES:
        raise EarlyCostingError("Costing is not open on this change")
    if not owes(change, department_id):
        raise EarlyCostingError(
            "The department owes no costing input on this change")
    if is_finalized(change, department_id):
        raise EarlyCostingError("The department's costing is already finalized")
    if reason not in NO_COST_REASONS:
        raise EarlyCostingError("Say why: no_work, absorbed or supplier")
    if reason == "absorbed" and not (hours and hours > 0):
        raise EarlyCostingError(
            "Absorbed: give the hours you absorb (an estimate; 0 is no work)")
    w = (await waits.open_by_department(session, [change.id], "costing")).get(
        (change.id, department_id))
    if w is not None:
        who = await session.get(User, w.created_by)
        raise EarlyCostingError(
            f"{who.full_name if who else 'A colleague'} has an open supplier "
            f"quote ({waits.line(w)}): close it first")
    pos = (await session.execute(
        select(CostingPosition).where(
            CostingPosition.change_id == change.id,
            CostingPosition.department_id == department_id)
        .order_by(CostingPosition.id).limit(1))).scalar_one_or_none()
    if pos is not None:
        who = await session.get(User, pos.created_by)
        raise EarlyCostingError(
            f"{who.full_name if who else 'A colleague'} has a cost position "
            f"'{pos.label}' for the department: delete it first, or finalize "
            "the costing with it")
    L = AssessmentCostLine
    priced = (await session.execute(
        select(func.count(L.id))
        .join(ChangeAssessment, ChangeAssessment.id == L.assessment_id)
        .where(ChangeAssessment.change_id == change.id,
               ChangeAssessment.department_id == department_id,
               or_(func.coalesce(L.demand_hours, 0) != 0,
                   func.coalesce(L.internal_cost, 0) != 0,
                   func.coalesce(L.external_cost, 0) != 0,
                   func.coalesce(L.minutes_per_part, 0) != 0)))).scalar() or 0
    if priced:
        raise EarlyCostingError(
            "The department has cost lines with hours or money: clear them "
            "first, or finalize the costing with them")
    anchor = next((a for a in _rows(change, department_id)
                   if a.verdict in COSTING_VERDICTS), None)
    answer = {"reason": reason, **({"hours": float(hours)} if reason == "absorbed" else {})}
    _set_details(anchor, costing_finalized_at=datetime.utcnow().isoformat(),
                 costing_finalized_by=actor.id, costing_no_cost=answer)
    await session.flush()
    words = (f"absorbed ({float(hours):g} h)" if reason == "absorbed"
             else {"no_work": "no work", "supplier": "the supplier does it"}[reason])
    await ChangeService.append_changelog(
        session, change, "costing_no_cost",
        f"No cost for dept {department_id}: {words}", actor.id,
        new_value={"department_id": department_id, **answer},
        for_department_id=department_id)
    from app.services.decision_notices import internal_approval_owed
    await internal_approval_owed(session, change, actor.id)
    return anchor


async def reopen(session: AsyncSession, change: ChangeRequest,
                 department_id: int, actor: User,
                 reason: Optional[str] = None) -> None:
    """Back to draft: the department changes its figures again. Only while
    costing is open; once closed (quoting) costing is reopened as a whole."""
    from app.services.change_service import ChangeService
    if not await _may_act(session, change, department_id, actor):
        raise EarlyCostingForbidden(
            "Only a member of that department, Project Management or an admin "
            "may reopen its costing")
    if change.status not in OPEN_STATUSES:
        raise EarlyCostingError(
            "Costing is closed: reopen costing for the change first")
    rows = [a for a in _rows(change, department_id)
            if a.details_dict.get("costing_finalized_at")]
    if not rows or not is_finalized(change, department_id):
        raise EarlyCostingError("The department's costing is not finalized")
    for a in rows:
        _set_details(a, costing_finalized_at=None, costing_finalized_by=None,
                     costing_no_cost=None)
    await session.flush()
    note = (reason or "").strip() or None
    await ChangeService.append_changelog(
        session, change, "costing_input_reopened",
        f"Costing input reopened for dept {department_id}"
        + (f": {note}" if note else ""),
        actor.id, new_value={"department_id": department_id}, notes=note,
        for_department_id=department_id)


def state(change: ChangeRequest) -> dict:
    """The progress line: who owes, who finalized, who is still open."""
    owed = owed_department_ids(change)
    done = set(finalized_department_ids(change))
    return {"owed": owed, "finalized": sorted(done & set(owed)),
            "pending": [d for d in owed if d not in done],
            # C18: departments that said "no cost", with why
            "no_cost": {d: nc for d in sorted(done & set(owed))
                        if (nc := no_cost_of(change, d))}}
