"""Costing positions and the vendor offers under them.

The rule the whole module exists to enforce: a position is priced EITHER by a
house estimate OR by a supplier's offer, never by both at once, and the number
the summation reads is derived from whichever applies (CostingPosition.
effective_cost) rather than copied into a field somebody has to remember to
update.

Who may write is the costing rule everywhere else in this module: while the
change is IN costing, the department writes its own rows; Project Management
and admins write anyone's, because they routinely fill numbers in on someone's
behalf during the costing meeting. Who may READ is wider — the people
accountable for the change as a whole see every department's positions, a
department sees its own.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeAttachment, ChangeRequest
from app.models.change_cost import (
    COSTING_BASES, COSTING_POSITION_KINDS, COSTING_PRICINGS, LEAD_TIME_UNITS,
    STANDING_KINDS,
    CostingOffer, CostingPosition,
)
from app.models.entities import User


class CostingPositionError(ValueError):
    """Invalid position/offer operation; mapped to HTTP 400 in the router."""


# Fields a PUT may change. department_id is not among them: moving a position
# to another department would move money out of one budget into another with
# no record of it — delete and re-add instead.
_POSITION_FIELDS = ("label", "tag", "kind", "pricing", "est_cost", "vendor_name",
                    "hours", "lead_time_days", "lead_time_unit", "notes",
                    "labour_position", "machine_class_id", "trials", "machine_id",
                    "basis", "basis_ref", "basis_part_id", "basis_differs")
_OFFER_FIELDS = ("vendor_name", "cost", "shipping_cost", "shipping_included",
                 "lead_time_days", "lead_time_unit", "favorite", "is_partial",
                 "quote_ref", "quoted_on", "valid_until")


class CostingPositionForbidden(CostingPositionError):
    """A costing act the caller has no right to: 403."""


class CostingPositionService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def may_write(session: AsyncSession, change: ChangeRequest,
                        department_id: int, actor: User) -> bool:
        """A member of that department while its costing is open and not
        finalized, or the people who run costing (PM, admin) at any time.

        Open (early_costing.costing_open_for): the change is in costing, or
        in assessment and the department has submitted a feasible answer
        that owes a cost input (per-department pipeline, 2026-10-14). A
        finalized department reopens its input before it writes again.

        The status window is deliberate: positions are the costing phase's
        working numbers, and letting them move after the total was approved
        would make the approved total a lie."""
        from app.services import early_costing
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        if (actor.effective_role == "admin"
                or await MeetingService.user_is_pm_member(session, actor)):
            return True
        if early_costing.costing_open_for(change, department_id):
            if early_costing.is_finalized(change, department_id):
                return False
        else:
            # Spec §16: an impact edit after the quote reopens costing for
            # the departments it touched, until a newer offer or an
            # approved deviation covers it.
            if not (change.scope_changed_after_quote
                    and department_id in (change.scope_change_department_ids or [])):
                return False
            from app.services.early_stage_service import EarlyStageService
            state = await EarlyStageService.scope_change_state(session, change)
            if state is None or state["covered"]:
                return False
        return await WorkflowService.actor_in_department(
            session, actor, department_id)

    @staticmethod
    async def may_choose_vendor(session: AsyncSession, change: ChangeRequest,
                                actor: User) -> bool:
        """Who decides which supplier gets the order: Sales, the change lead,
        or an admin — the same set that may put a price in front of the
        customer, because choosing the vendor IS setting the price.

        Deliberately NOT the department that raised the position. The
        department recommends (its favorite offer); it does not decide. The
        window is 'quoting': the decision belongs to the moment the offer is
        being written, when the costing is finished and the price is being
        put together. Admins are exempt from the window, as everywhere else in
        this module, because they record decisions after the fact.
        """
        from app.services.change_service import ChangeService
        if actor.effective_role == "admin":
            return True
        if change.status != "quoting":
            return False
        return await ChangeService.user_can_set_quoted_price(
            session, actor, change)

    @staticmethod
    async def readable_department_ids(
        session: AsyncSession, change: ChangeRequest, actor: User,
    ) -> set | None:
        """Which departments' positions this caller may see. None means all —
        PM, Sales, Management, the change lead and admins price the change as a whole, so
        seeing one department's numbers without the others would be useless to
        them. Everyone else sees their own departments."""
        # P4: the one price rule (PriceViewer: admin, the lead, PM, Sales,
        # Management) - whoever reads the summation reads every position.
        from app.services.price_redaction import PriceViewer
        from app.services.workflow_service import WorkflowService
        if await PriceViewer(session, actor).may_read(change):
            return None
        return set(await WorkflowService.effective_department_ids(session, actor))

    @staticmethod
    async def quote_department_ids(
        session: AsyncSession, attachments,
    ) -> dict[int, int | None]:
        """attachment id -> the department whose costing position the vendor
        quote belongs to, for every vendor_quote / offer-linked attachment in
        `attachments`. None when the offer or position is gone (an orphaned
        quote has no owner, so only the full readers may see it)."""
        quotes = [a for a in attachments
                  if a.costing_offer_id is not None or a.kind == "vendor_quote"]
        if not quotes:
            return {}
        offer_ids = {a.costing_offer_id for a in quotes
                     if a.costing_offer_id is not None}
        dept_by_offer: dict[int, int] = {}
        if offer_ids:
            dept_by_offer = dict((await session.execute(
                select(CostingOffer.id, CostingPosition.department_id)
                .join(CostingPosition,
                      CostingPosition.id == CostingOffer.position_id)
                .where(CostingOffer.id.in_(offer_ids)))).all())
        return {a.id: dept_by_offer.get(a.costing_offer_id) for a in quotes}

    @staticmethod
    async def unreadable_attachment_ids(
        session: AsyncSession, change: ChangeRequest, actor: User,
        attachments,
    ) -> set[int]:
        """The vendor quotes among `attachments` that `actor` may not read: a
        quote is its offer's price on paper, so it follows the same rule as
        the position it belongs to (readable_department_ids)."""
        visible = await CostingPositionService.readable_department_ids(
            session, change, actor)
        if visible is None:
            return set()
        owners = await CostingPositionService.quote_department_ids(
            session, attachments)
        return {aid for aid, dept in owners.items()
                if dept is None or dept not in visible}

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def list_positions(
        session: AsyncSession, change: ChangeRequest,
        department_ids: set | None = None,
    ) -> list[CostingPosition]:
        q = (select(CostingPosition)
             .where(CostingPosition.change_id == change.id)
             .order_by(CostingPosition.department_id, CostingPosition.id))
        if department_ids is not None:
            if not department_ids:
                return []
            q = q.where(CostingPosition.department_id.in_(department_ids))
        return list((await session.execute(q)).scalars().all())

    @staticmethod
    async def serialize(session: AsyncSession,
                        positions: list[CostingPosition]) -> list[dict]:
        """Positions with their offers, and each offer with the quote
        documents filed against it. One query for the documents however many
        offers there are."""
        offer_ids = [o.id for p in positions for o in p.offers]
        docs: dict[int, list[dict]] = {}
        if offer_ids:
            rows = (await session.execute(
                select(ChangeAttachment)
                .where(ChangeAttachment.costing_offer_id.in_(offer_ids))
                .order_by(ChangeAttachment.id))).scalars().all()
            for att in rows:
                docs.setdefault(att.costing_offer_id, []).append({
                    "id": att.id, "filename": att.filename,
                    "size_bytes": att.size_bytes, "kind": att.kind,
                    "uploaded_by": att.uploaded_by,
                    "uploaded_by_name": att.uploaded_by_name,
                    "created_at": att.created_at,
                })
        # Who stamped each decision, by name: "chosen by user 41" is not a
        # record anybody can act on, and making the frontend fetch the user
        # directory to render a wrap-up line is a round trip that goes stale.
        chooser_ids = {o.chosen_by for p in positions for o in p.offers
                       if o.chosen_by is not None}
        choosers: dict[int, str] = {}
        if chooser_ids:
            choosers = dict((await session.execute(
                select(User.id, User.full_name).where(
                    User.id.in_(chooser_ids)))).all())
        # The rate each line is priced with and where it comes from (cost
        # sheet version, department, position), or "No rate in the cost
        # sheet". One lookup per position of the change it belongs to.
        from app.services import costing_rates
        pricing: dict[int, dict] = {}
        by_change: dict[int, list] = {}
        for p in positions:
            by_change.setdefault(p.change_id, []).append(p)
        for change_id, rows in by_change.items():
            change = await session.get(ChangeRequest, change_id)
            if change is not None:
                pricing.update(await costing_rates.describe_positions(
                    session, change, rows))
        basis_parts = {p.basis_part_id for p in positions if p.basis_part_id}
        part_numbers: dict[int, str] = {}
        if basis_parts:
            from app.models.part import Part
            part_numbers = dict((await session.execute(
                select(Part.id, Part.part_number).where(Part.id.in_(basis_parts)))).all())
        out = []
        for p in positions:
            # Two different questions, two different properties:
            # favorite_offer is the offer this position is PRICED from (with
            # the single-offer fallback), recommended_offer is the vote the
            # department actually cast — and only a real vote can be
            # diverged from.
            priced_from = p.favorite_offer
            favorite = p.recommended_offer
            chosen = p.chosen_offer
            out.append({
                "id": p.id, "change_id": p.change_id,
                "department_id": p.department_id, "label": p.label,
                "tag": p.tag, "kind": p.kind, "pricing": p.pricing,
                "est_cost": p.est_cost, "vendor_name": p.vendor_name, "hours": p.hours,
                "labour_position": p.labour_position,
                "machine_class_id": p.machine_class_id, "trials": p.trials,
                "machine_id": p.machine_id,
                **pricing.get(p.id, {}),
                "basis": p.effective_basis, "basis_ref": p.basis_ref,
                "basis_part_id": p.basis_part_id,
                "basis_part_number": part_numbers.get(p.basis_part_id),
                "basis_differs": p.basis_differs, "estimated": p.estimated,
                "estimate_check": p.estimate_check, "estimate_over": p.estimate_over,
                "lead_time_days": p.lead_time_days,
                "lead_time_unit": p.lead_time_unit, "notes": p.notes,
                "created_by": p.created_by, "created_at": p.created_at,
                "updated_at": p.updated_at,
                "effective_cost": p.effective_cost,
                "effective_lead_time_days": p.effective_lead_time_days,
                "effective_lead_time_unit": p.effective_lead_time_unit,
                "effective_lead_time_calendar_days":
                    p.effective_lead_time_calendar_days,
                "favorite_offer_id": priced_from.id if priced_from else None,
                "parts_cost": p.parts_cost,
                # The department RECOMMENDS, Sales DECIDES. Both sides ride on
                # the position so a wrap-up line reads "recommended: A ·
                # chosen: B (reason)" without joining anything.
                "recommended_vendor": favorite.vendor_name if favorite else None,
                "recommended_cost": favorite.total_cost if favorite else None,
                "chosen_offer_id": chosen.id if chosen else None,
                "chosen_vendor": chosen.vendor_name if chosen else None,
                "chosen_cost": chosen.total_cost if chosen else None,
                "chosen_reason": chosen.chosen_reason if chosen else None,
                "chosen_by_name": (choosers.get(chosen.chosen_by)
                                   if chosen else None),
                "chosen_at": chosen.chosen_at if chosen else None,
                # True when Sales went against the recommendation. Computed
                # here so every screen draws the same conclusion from it.
                "choice_diverges": bool(
                    chosen is not None and favorite is not None
                    and chosen.id != favorite.id),
                # The money in the offer: the chosen vendor's price once there
                # is one, the department's own effective_cost until then.
                "quoted_cost": p.quoted_cost,
                "offers": [{
                    "id": o.id, "position_id": o.position_id,
                    "vendor_name": o.vendor_name, "cost": o.cost,
                    "shipping_cost": o.shipping_cost,
                    "shipping_included": o.shipping_included,
                    "lead_time_days": o.lead_time_days,
                    "lead_time_unit": o.lead_time_unit,
                    "lead_time_calendar_days": o.lead_time_calendar_days,
                    "favorite": o.favorite, "is_partial": o.is_partial,
                    "total_cost": o.total_cost,
                    "chosen": o.chosen, "chosen_reason": o.chosen_reason,
                    "chosen_by": o.chosen_by,
                    "chosen_by_name": choosers.get(o.chosen_by),
                    "chosen_at": o.chosen_at,
                    "created_by": o.created_by, "created_at": o.created_at,
                    "quote_ref": o.quote_ref, "quoted_on": o.quoted_on,
                    "valid_until": o.valid_until,
                    "attachments": docs.get(o.id, []),
                } for o in p.offers],
            })
        return out

    @staticmethod
    async def get_position(session: AsyncSession, change: ChangeRequest,
                           position_id: int) -> CostingPosition:
        p = await session.get(CostingPosition, position_id)
        if p is None or p.change_id != change.id:
            raise CostingPositionError(
                f"Costing position {position_id} not found on this change")
        return p

    @staticmethod
    async def get_offer(session: AsyncSession, change: ChangeRequest,
                        offer_id: int) -> CostingOffer:
        o = await session.get(CostingOffer, offer_id)
        if o is None:
            raise CostingPositionError(f"Offer {offer_id} not found")
        position = await session.get(CostingPosition, o.position_id)
        if position is None or position.change_id != change.id:
            raise CostingPositionError(
                f"Offer {offer_id} not found on this change")
        return o

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @staticmethod
    def _validate(position: CostingPosition) -> None:
        if not (position.label or "").strip():
            raise CostingPositionError("A costing position needs a label")
        if position.kind not in COSTING_POSITION_KINDS:
            raise CostingPositionError(
                f"Invalid position kind '{position.kind}'")
        if position.pricing not in COSTING_PRICINGS:
            raise CostingPositionError(
                f"Invalid pricing '{position.pricing}'")
        # Effort is never quoted — nobody sends an offer for our own hours. The
        # value is normalized rather than rejected so a UI that keeps one
        # pricing toggle for the whole form cannot produce an error.
        if position.kind != "external":
            position.pricing = "estimate"
        if position.lead_time_days is not None and position.lead_time_days < 0:
            raise CostingPositionError("Lead time cannot be negative")
        if position.lead_time_unit not in LEAD_TIME_UNITS:
            raise CostingPositionError(
                f"Invalid lead time unit '{position.lead_time_unit}'")
        # Hours are accepted on EVERY kind, external included: the department's
        # own time around a supplier's work (specifying it, chasing it, taking
        # it back in) is real effort and is not an estimate of the vendor's
        # price.
        if position.hours is not None and position.hours < 0:
            raise CostingPositionError("Hours cannot be negative")
        if position.trials is not None and position.trials < 0:
            raise CostingPositionError("Trials cannot be negative")
        if position.labour_position is not None:
            position.labour_position = position.labour_position.strip()[:80] or None
        # machine_time and sampling are priced by the cost sheet alone: an
        # estimate typed next to them would be counted twice.
        if position.kind in ("machine_time", "sampling"):
            position.est_cost = None
            position.vendor_name = None
            position.labour_position = None
        else:
            position.machine_class_id = None
            position.machine_id = None
        if position.kind != "sampling":
            position.trials = None
        # Spec §4 basis: own time is hours x the rate, a quoted line stands on
        # its quote; an estimated external line is an estimate (+ reference)
        # or "same as" a part (+ what differs). Normalised, not refused.
        if position.basis is not None and position.basis not in COSTING_BASES:
            raise CostingPositionError(
                f"Invalid basis '{position.basis}': rate, quote, same_as or estimate")
        if position.kind != "external":
            position.basis = "rate"
        elif position.pricing == "quote":
            position.basis = "quote"
        elif position.basis in ("rate", "quote"):
            position.basis = None
        if position.basis != "same_as":
            position.basis_part_id = None
            position.basis_differs = None
        for f in ("basis_ref", "basis_differs"):
            v = getattr(position, f)
            setattr(position, f, (v or "").strip() or None)

    @staticmethod
    async def _check_machine_class(session: AsyncSession, change: ChangeRequest,
                                   position: CostingPosition) -> None:
        """A named machine class must be one of the org's classes, a named
        machine one of the org's synced MachineDB machines."""
        if position.machine_class_id is None and position.machine_id is None:
            return
        from app.models.cost_sheet import CostSheetMachineClass
        from app.models.cost_sheet_machines import CostSheetMachine
        from app.services import costing_rates
        org_id = await costing_rates.change_org_id(session, change)
        if position.machine_class_id is not None:
            c = await session.get(CostSheetMachineClass, position.machine_class_id)
            if c is None or c.organization_id != org_id:
                raise CostingPositionError(
                    f"Unknown machine class {position.machine_class_id}")
        if position.machine_id is not None:
            m = await session.get(CostSheetMachine, position.machine_id)
            if m is None or m.organization_id != org_id:
                raise CostingPositionError(f"Unknown machine {position.machine_id}")

    @staticmethod
    def _validate_offer(offer: CostingOffer, position: CostingPosition) -> None:
        if position.kind != "external":
            raise CostingPositionError(
                "Only an external position can carry vendor offers")
        if not (offer.vendor_name or "").strip():
            raise CostingPositionError("An offer needs a vendor name")
        if offer.cost is None or offer.cost < 0:
            raise CostingPositionError("An offer needs a cost of zero or more")
        if offer.shipping_cost is not None and offer.shipping_cost < 0:
            raise CostingPositionError("Shipping cost cannot be negative")
        if offer.lead_time_days is not None and offer.lead_time_days < 0:
            raise CostingPositionError("Lead time cannot be negative")
        if offer.lead_time_unit not in LEAD_TIME_UNITS:
            raise CostingPositionError(
                f"Invalid lead time unit '{offer.lead_time_unit}'")
        # A part is always counted; the star and Sales' choice are for
        # alternatives. Normalised rather than refused: switching a starred
        # offer to 'part' simply drops the star.
        if offer.is_partial:
            offer.favorite = False
        if (offer.quoted_on is not None and offer.valid_until is not None
                and offer.valid_until < offer.quoted_on):
            raise CostingPositionError("Valid until: on or after the quote date")

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    @staticmethod
    async def _standing(session: AsyncSession, change_id: int,
                        department_id: int, kind: str):
        return (await session.execute(
            select(CostingPosition).where(
                CostingPosition.change_id == change_id,
                CostingPosition.department_id == department_id,
                CostingPosition.kind == kind)
            .order_by(CostingPosition.id).limit(1))).scalar_one_or_none()

    @staticmethod
    async def create_position(
        session: AsyncSession, change: ChangeRequest, spec: dict, actor: User,
    ) -> CostingPosition:
        department_id = spec["department_id"]
        # Only a routed department has costs on this change; anything else is
        # a typo that would land money in a department nobody asked.
        routed = (await session.execute(
            select(ChangeAssessment.id).where(
                ChangeAssessment.change_id == change.id,
                ChangeAssessment.department_id == department_id).limit(1)
        )).scalar_one_or_none()
        if routed is None:
            raise CostingPositionError(
                f"Department {department_id} has no assessment on this change")
        kind = spec.get("kind") or "external"
        if kind in STANDING_KINDS:
            # One standing answer per department: a second save (the effort
            # row fires on blur AND on the save click) updates the first
            # instead of adding a duplicate line (final walk P2-1).
            existing = await CostingPositionService._standing(
                session, change.id, department_id, kind)
            if existing is not None:
                return await CostingPositionService.update_position(
                    session, change, existing,
                    {k: v for k, v in spec.items()
                     if k in _POSITION_FIELDS and k != "kind"}, actor)
        position = CostingPosition(
            change_id=change.id, department_id=department_id,
            label=(spec.get("label") or "").strip(),
            tag=(spec.get("tag") or None),
            kind=spec.get("kind") or "external",
            pricing=spec.get("pricing") or "estimate",
            est_cost=spec.get("est_cost"), hours=spec.get("hours"),
            vendor_name=((spec.get("vendor_name") or "").strip() or None),
            lead_time_days=spec.get("lead_time_days"),
            lead_time_unit=spec.get("lead_time_unit") or "calendar_days",
            notes=spec.get("notes"), created_by=actor.id,
            labour_position=spec.get("labour_position"),
            machine_class_id=spec.get("machine_class_id"),
            machine_id=spec.get("machine_id"),
            trials=spec.get("trials"),
            basis=spec.get("basis"), basis_ref=spec.get("basis_ref"),
            basis_part_id=spec.get("basis_part_id"),
            basis_differs=spec.get("basis_differs"),
        )
        CostingPositionService._validate(position)
        await CostingPositionService._check_machine_class(session, change, position)
        # Priced now, from the cost sheet valid today: the snapshot stays on
        # the line until its pricing inputs change.
        from app.services import costing_rates
        await costing_rates.snapshot_position(session, change, position)
        if kind in STANDING_KINDS:
            # Two saves racing past the lookup above: the unique index
            # (migration 101) refuses the second insert; it merges then.
            from sqlalchemy.exc import IntegrityError
            try:
                async with session.begin_nested():
                    session.add(position)
                    await session.flush()
            except IntegrityError:
                existing = await CostingPositionService._standing(
                    session, change.id, department_id, kind)
                if existing is None:
                    raise
                return await CostingPositionService.update_position(
                    session, change, existing,
                    {k: v for k, v in spec.items()
                     if k in _POSITION_FIELDS and k != "kind"}, actor)
        else:
            session.add(position)
            await session.flush()
        # A just-added row has no loaded `offers` collection, and effective_cost
        # reads it — an async lazy load here would raise MissingGreenlet.
        await session.refresh(position, ["offers"])
        await CostingPositionService._log(
            session, change, "costing_position_added",
            f"Costing position '{position.label}' added for dept "
            f"{department_id}", actor, position)
        return position

    @staticmethod
    async def update_position(
        session: AsyncSession, change: ChangeRequest,
        position: CostingPosition, spec: dict, actor: User,
    ) -> CostingPosition:
        from app.services import costing_rates
        before = {f: getattr(position, f) for f in costing_rates.PRICING_FIELDS}
        new_kind = spec.get("kind")
        if (new_kind in STANDING_KINDS and new_kind != position.kind
                and await CostingPositionService._standing(
                    session, change.id, position.department_id, new_kind)):
            raise CostingPositionError(
                "This department already has that standing effort line: "
                "edit it instead")
        for field in _POSITION_FIELDS:
            if field in spec:
                setattr(position, field, spec[field])
        if position.label:
            position.label = position.label.strip()
        CostingPositionService._validate(position)
        await CostingPositionService._check_machine_class(session, change, position)
        # Re-priced only when what the rate depends on moved, or the line has
        # no rate yet (never priced, or none was found: Finance may have added
        # it since): a typo fixed in the label keeps its snapshot.
        if (position.rate_on is None or position.rate is None
                or any(getattr(position, f) != before[f]
                       for f in costing_rates.PRICING_FIELDS)):
            # The line's own class or named machine edited is an explicit
            # move: it is not kept frozen on the class it was priced on.
            moved = any(getattr(position, f) != before[f]
                        for f in ("machine_class_id", "machine_id"))
            await costing_rates.snapshot_position(session, change, position,
                                                  freeze=not moved)
        position.updated_at = datetime.utcnow()
        await session.flush()
        await CostingPositionService._log(
            session, change, "costing_position_updated",
            f"Costing position '{position.label}' updated", actor, position)
        return position

    @staticmethod
    async def delete_position(
        session: AsyncSession, change: ChangeRequest,
        position: CostingPosition, actor: User,
    ) -> list[str]:
        """Returns the stored paths of the quote documents that went with it,
        for the router to unlink — the same contract delete_attachment uses."""
        paths = []
        for offer in list(position.offers):
            paths += await CostingPositionService._detach_documents(
                session, offer)
        label, department_id = position.label, position.department_id
        await session.delete(position)
        await session.flush()
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "costing_position_deleted",
            f"Costing position '{label}' removed from dept {department_id}",
            actor.id, old_value={"label": label, "department_id": department_id},
            for_department_id=department_id)
        return paths

    @staticmethod
    async def create_offer(
        session: AsyncSession, change: ChangeRequest,
        position: CostingPosition, spec: dict, actor: User,
    ) -> CostingOffer:
        offer = CostingOffer(
            position_id=position.id,
            vendor_name=(spec.get("vendor_name") or "").strip(),
            cost=spec.get("cost"),
            shipping_cost=spec.get("shipping_cost"),
            shipping_included=bool(spec.get("shipping_included") or False),
            lead_time_days=spec.get("lead_time_days"),
            lead_time_unit=spec.get("lead_time_unit") or "calendar_days",
            favorite=bool(spec.get("favorite") or False),
            is_partial=bool(spec.get("is_partial") or False),
            quote_ref=(spec.get("quote_ref") or "").strip() or None,
            quoted_on=spec.get("quoted_on"), valid_until=spec.get("valid_until"),
            created_by=actor.id,
        )
        CostingPositionService._validate_offer(offer, position)
        session.add(offer)
        await session.flush()
        was = position.estimate_check
        CostingPositionService._quote_after_commit(change, position, offer)
        if was is None and position.estimate_check == "pending":
            await CostingPositionService._tell_check_pending(
                session, change, position, actor)
        if offer.favorite:
            await CostingPositionService._clear_other_favorites(
                session, position, offer)
        await session.refresh(position, ["offers"])
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "costing_offer_added",
            f"Offer from {offer.vendor_name} on '{position.label}': "
            f"{offer.total_cost}", actor.id,
            new_value={"position_id": position.id, "offer_id": offer.id,
                       "vendor_name": offer.vendor_name,
                       "total_cost": offer.total_cost},
            for_department_id=position.department_id)
        return offer

    @staticmethod
    async def update_offer(
        session: AsyncSession, change: ChangeRequest, offer: CostingOffer,
        spec: dict, actor: User,
    ) -> CostingOffer:
        position = await session.get(CostingPosition, offer.position_id)
        for field in _OFFER_FIELDS:
            if field in spec:
                setattr(offer, field, spec[field])
        if offer.vendor_name:
            offer.vendor_name = offer.vendor_name.strip()
        CostingPositionService._validate_offer(offer, position)
        await session.flush()
        was = position.estimate_check
        CostingPositionService._quote_after_commit(change, position, offer)
        if was is None and position.estimate_check == "pending":
            await CostingPositionService._tell_check_pending(
                session, change, position, actor)
        if offer.favorite:
            await CostingPositionService._clear_other_favorites(
                session, position, offer)
        await session.refresh(position, ["offers"])
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "costing_offer_updated",
            f"Offer from {offer.vendor_name} on '{position.label}' updated",
            actor.id,
            new_value={"position_id": position.id, "offer_id": offer.id,
                       "favorite": offer.favorite,
                       "total_cost": offer.total_cost},
            for_department_id=position.department_id)
        return offer

    @staticmethod
    async def delete_offer(
        session: AsyncSession, change: ChangeRequest, offer: CostingOffer,
        actor: User,
    ) -> list[str]:
        position = await session.get(CostingPosition, offer.position_id)
        paths = await CostingPositionService._detach_documents(session, offer)
        vendor = offer.vendor_name
        await session.delete(offer)
        await session.flush()
        await session.refresh(position, ["offers"])
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, "costing_offer_deleted",
            f"Offer from {vendor} on '{position.label}' removed", actor.id,
            old_value={"position_id": position.id, "vendor_name": vendor},
            for_department_id=position.department_id)
        return paths

    @staticmethod
    async def choose_offer(
        session: AsyncSession, change: ChangeRequest, offer: CostingOffer,
        reason: str | None, actor: User,
    ) -> CostingOffer:
        """Sales decides which vendor gets the order.

        Two rules, and they are the whole feature:

        One decision per position — choosing an offer un-chooses its siblings,
        the same way voting for a favorite un-votes the others. A position with
        two chosen offers is a purchase order nobody can execute.

        A reason is REQUIRED when the decision diverges from the department's
        recommendation, and optional when it agrees. Going with the engineers
        needs no defence; going around them does, and the person who did it is
        stamped on the row. Re-deciding is allowed and audited: a supplier can
        fall over a week after the decision, and forcing that correction to
        happen by deleting offers would erase the history of the first call.
        """
        position = await session.get(CostingPosition, offer.position_id)
        await session.refresh(position, ["offers"])
        if position.kind != "external":
            raise CostingPositionError(
                "Only an external position has a vendor to choose")
        if offer.is_partial:
            raise CostingPositionError(
                "A partial quote is always counted — the decision is between "
                "the full quotes (alternatives)")
        # The department's VOTE, not the pricing fallback: a position nobody
        # voted on carries no recommendation to diverge from, so choosing any
        # of its offers needs no defence.
        favorite = position.recommended_offer
        diverges = favorite is not None and favorite.id != offer.id
        reason = (reason or "").strip()
        if diverges and not reason:
            raise CostingPositionError(
                f"Choosing {offer.vendor_name} over the department's "
                f"recommendation "
                f"({favorite.vendor_name}) needs a reason — the decision is "
                "Sales' to make and Sales' to account for")

        previous = position.chosen_offer
        for other in position.offers:
            if other.id != offer.id and other.chosen:
                other.chosen = False
                # The stamp goes with the flag: a chosen_by on an offer nobody
                # is buying from is a name against a decision that was reversed.
                other.chosen_reason = None
                other.chosen_by = None
                other.chosen_at = None
        offer.chosen = True
        offer.chosen_reason = reason or None
        offer.chosen_by = actor.id
        offer.chosen_at = datetime.utcnow()
        await session.flush()
        await session.refresh(position, ["offers"])

        from app.services.change_service import ChangeService
        if diverges:
            description = (
                f"Vendor chosen against the department recommendation: "
                f"{offer.vendor_name} instead of {favorite.vendor_name} on "
                f"'{position.label}' — {reason}")
        else:
            description = (f"Vendor chosen: {offer.vendor_name} on "
                           f"'{position.label}'")
        await ChangeService.append_changelog(
            session, change, "vendor_chosen", description, actor.id,
            field_name="chosen_offer_id",
            old_value=({"offer_id": previous.id,
                        "vendor_name": previous.vendor_name}
                       if previous is not None else None),
            new_value={"position_id": position.id, "offer_id": offer.id,
                       "vendor_name": offer.vendor_name,
                       "total_cost": offer.total_cost,
                       "recommended_vendor": (favorite.vendor_name
                                              if favorite else None),
                       "diverges_from_recommendation": diverges},
            notes=reason or None)
        return offer

    # ------------------------------------------------------------------
    @staticmethod
    def estimate_check_open(change: ChangeRequest, position: CostingPosition) -> bool:
        """Spec §4 [R4]: the quote-vs-estimate comparison can be made on this
        position now: an estimated line, an offer sent or the internal
        approval given on it, the comparison not yet made (pending: a quote
        with a number came in; None: the department records the quote that
        came in, in the same step). Any status from then on but closed."""
        from app.services import cm_switches
        return (cm_switches.on("ASSESSMENT_V2") and position.estimated
                and position.estimate_check in (None, "pending")
                and (change.quoted_at is not None
                     or change.internal_approved_at is not None)
                and change.status not in ("closed", "cancelled", "rejected"))

    @staticmethod
    async def checkable_position_ids(session: AsyncSession, change: ChangeRequest,
                                     positions: list[CostingPosition],
                                     actor: User) -> set[int]:
        """The positions this caller may compare with their estimate (served
        as can_check_estimate, R24: the same rule as POST .../estimate-check).
        One membership lookup for the list."""
        open_ = [p for p in positions
                 if CostingPositionService.estimate_check_open(change, p)]
        if not open_:
            return set()
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        if (actor.effective_role == "admin"
                or await MeetingService.user_is_pm_member(session, actor)):
            return {p.id for p in open_}
        mine = set(await WorkflowService.effective_department_ids(session, actor))
        return {p.id for p in open_ if p.department_id in mine}

    @staticmethod
    async def _tell_check_pending(session: AsyncSession, change: ChangeRequest,
                                  position: CostingPosition, actor: User) -> None:
        """A quote came in on the estimate after the offer or approval (spec
        §4 [R4]): the department is asked once (task newly theirs), unless
        it entered the quote itself."""
        from app.services.notification_service import NotificationService
        from app.services.workflow_service import WorkflowService
        if await WorkflowService.actor_in_department(
                session, actor, position.department_id):
            return
        await NotificationService.notify_departments_once(
            session, [position.department_id], change=change, kind="task_new",
            subject_key=f"estimate_check:{position.id}",
            title=f"Quote vs your estimate: {change.change_number}"[:255],
            body=(f"A supplier quote came in on '{position.label}', estimated at "
                  f"{position.est_cost:.2f}: within +5 % or above by how much?"),
            link=f"/changes/{change.id}?tab=costing")

    @staticmethod
    def _quote_after_commit(change: ChangeRequest, position: CostingPosition,
                            offer: CostingOffer) -> None:
        """Spec §4 [R4]: an estimated position gets its supplier quote (an
        offer with a quote number) after an offer went to the customer or
        the internal approval was given on the estimate: the department
        compares it with its estimate before it finalizes (pending)."""
        from app.services import cm_switches
        if (cm_switches.on("ASSESSMENT_V2") and position.estimate_check is None
                and position.est_cost and (offer.quote_ref or "").strip()
                and (change.quoted_at is not None
                     or change.internal_approved_at is not None)):
            position.estimate_check = "pending"

    @staticmethod
    async def estimate_check(session: AsyncSession, change: ChangeRequest,
                             position: CostingPosition, actor: User,
                             verdict: str, over: Optional[float] = None,
                             quote: Optional[dict] = None,
                             ) -> CostingPosition:
        """Spec §4 [R4] "Quote vs your estimate: within +5 % / above by x",
        nothing preselected. Above: the price is open again (price_open,
        HARD #9 at close) and one task goes out: a customer change to Sales
        ("Estimate low by x: send supplement or absorb"), an internal one to
        the approver and the lead ("absorb with a reason"). The Absorb (or
        the customer's acceptance of a supplement) clears it. With no check
        pending yet, the department records the quote that came in (supplier,
        quote number, amount) in the same step."""
        from app.services import cm_switches
        from app.services.change_service import ChangeService
        from app.services.early_costing import _may_act
        if not cm_switches.on("ASSESSMENT_V2"):
            raise CostingPositionError("The estimate check is switched off (ASSESSMENT_V2)")
        if not await _may_act(session, change, position.department_id, actor):
            raise CostingPositionForbidden(
                "Only a member of that department, Project Management or an "
                "admin compares its quote with its estimate")
        if not CostingPositionService.estimate_check_open(change, position):
            raise CostingPositionError(
                "Nothing to compare: no quote came in on an estimate an offer "
                "or approval was given on")
        if verdict not in ("within", "above"):
            raise CostingPositionError("Say how the quote compares: within or above")
        if verdict == "above" and not (over and over > 0):
            raise CostingPositionError("Above: by how much (the amount over the estimate)")
        if position.estimate_check is None:
            # the quote came in and is compared in one step: the supplier,
            # its quote number (evidence) and the amount
            from app.services.cm_rules import reference_refusal
            q = quote or {}
            if not (q.get("vendor_name") or "").strip():
                raise CostingPositionError(
                    "Name the supplier whose quote came in, with its quote number")
            why = reference_refusal((q.get("quote_ref") or "").strip(),
                                    "Give the supplier's quote number",
                                    "Q-2026-4471")
            if why:
                raise CostingPositionError(why)
            # compared right here: no "pending" ask for the department
            position.estimate_check = verdict
            await CostingPositionService.create_offer(
                session, change, position,
                {"vendor_name": q["vendor_name"], "cost": q.get("cost"),
                 "quote_ref": q["quote_ref"], "quoted_on": q.get("quoted_on")},
                actor)
        position.estimate_check = verdict
        position.estimate_over = float(over) if verdict == "above" else None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "estimate_checked",
            f"Quote vs estimate on '{position.label}': "
            + ("within +5 %" if verdict == "within" else f"above by {float(over):.2f}"),
            actor.id, new_value={"position_id": position.id, "verdict": verdict,
                                 "over": position.estimate_over},
            for_department_id=position.department_id)
        if verdict == "above":
            await ChangeService.open_price(
                session, change, f"Quote above the estimate on '{position.label}': "
                "the price is open (supplement or absorb)", actor.id)
            await session.flush()
            from app.services.notification_service import NotificationService
            key = f"estimate_low:{position.id}"
            body = f"'{position.label}' was estimated at {position.est_cost:.2f}."
            link = f"/changes/{change.id}?tab=offer"
            ids: list = []
            if change.customer_relevant:
                title = (f"Estimate low by {float(over):.2f}: send supplement or "
                         f"absorb: {change.change_number}")
                if change.sales_owner_id:
                    ids = [change.sales_owner_id]
                else:
                    # no Sales owner: all of Sales, as the other Sales notices
                    from app.models.workflow import Department
                    sales = (await session.execute(select(Department.id).where(
                        Department.name == "Sales"))).scalar_one_or_none()
                    if sales is not None:
                        await NotificationService.notify_departments_once(
                            session, [sales], change=change, kind="task_new", subject_key=key,
                            title=title[:255], body=body, link=link)
            else:
                # the internal exit is the Absorb override: the lead (PM
                # without a lead) proposes it, the approver decides it on the
                # deviation's own task (HARD #9); there is no re-approval
                # step. Both recipients read prices (lead, PM member).
                if change.lead_id:
                    ids = [change.lead_id]
                else:
                    from app.services.change_people import department_members_of_change_org
                    from app.models.workflow import Department
                    pm = (await session.execute(select(Department.id).where(
                        Department.name == "Project Manager"))).scalars().all()
                    ids = await department_members_of_change_org(session, change, pm)
                title = (f"Cost {float(over):.2f} above the approved estimate: "
                         + ("re-approve or absorb (reason)" if change.status == "costing"
                            else "ask to absorb with a reason")
                         + f": {change.change_number}")
                if change.status == "costing":
                    # A3-05 (spec §4 [R4]): in costing the approver
                    # re-approves the new total; no amount (R23)
                    approvers = await ChangeService.internal_approver_ids(session, change)
                    await NotificationService.notify_once(
                        session, [i for i in approvers
                                  if i and i != actor.id and i not in ids],
                        kind="task_new", subject_key=f"{key}:approver",
                        title=("Cost above the approved estimate: re-approve or "
                               f"absorb (reason): {change.change_number}")[:255],
                        body=f"A quote on '{position.label}' came in above its estimate.",
                        link=link)
            await NotificationService.notify_once(
                session, [i for i in ids if i and i != actor.id], kind="task_new",
                subject_key=key, title=title[:255], body=body, link=link)
        return position

    @staticmethod
    async def _clear_other_favorites(
        session: AsyncSession, position: CostingPosition, keep: CostingOffer,
    ) -> None:
        """One favorite per position: voting for one offer is voting against
        the others, so the flag moves rather than accumulating."""
        rows = (await session.execute(
            select(CostingOffer).where(
                CostingOffer.position_id == position.id,
                CostingOffer.id != keep.id,
                CostingOffer.favorite.is_(True)))).scalars().all()
        for other in rows:
            other.favorite = False
        if rows:
            await session.flush()

    @staticmethod
    async def _detach_documents(session: AsyncSession,
                                offer: CostingOffer) -> list[str]:
        """A quote document has no meaning without its offer, so it goes with
        it. Paths come back so the router can unlink the files."""
        rows = (await session.execute(
            select(ChangeAttachment).where(
                ChangeAttachment.costing_offer_id == offer.id))).scalars().all()
        paths = [a.stored_path for a in rows]
        for att in rows:
            await session.delete(att)
        if rows:
            await session.flush()
        return paths

    @staticmethod
    async def _log(session: AsyncSession, change: ChangeRequest, action: str,
                   description: str, actor: User,
                   position: CostingPosition) -> None:
        from app.services.change_service import ChangeService
        await ChangeService.append_changelog(
            session, change, action, description, actor.id,
            new_value={"position_id": position.id,
                       "department_id": position.department_id,
                       "label": position.label, "kind": position.kind,
                       "pricing": position.pricing,
                       "effective_cost": position.effective_cost},
            for_department_id=position.department_id)
