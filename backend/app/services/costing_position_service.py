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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeAttachment, ChangeRequest
from app.models.change_cost import (
    COSTING_POSITION_KINDS, COSTING_PRICINGS, LEAD_TIME_UNITS,
    CostingOffer, CostingPosition,
)
from app.models.entities import User


class CostingPositionError(ValueError):
    """Invalid position/offer operation; mapped to HTTP 400 in the router."""


# Fields a PUT may change. department_id is not among them: moving a position
# to another department would move money out of one budget into another with
# no record of it — delete and re-add instead.
_POSITION_FIELDS = ("label", "tag", "kind", "pricing", "est_cost", "hours",
                    "lead_time_days", "lead_time_unit", "notes")
_OFFER_FIELDS = ("vendor_name", "cost", "shipping_cost", "shipping_included",
                 "lead_time_days", "lead_time_unit", "favorite")


class CostingPositionService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def may_write(session: AsyncSession, change: ChangeRequest,
                        department_id: int, actor: User) -> bool:
        """A member of that department while the change is in costing, or the
        people who run costing (PM, admin) at any time.

        The status window is deliberate: positions are the costing phase's
        working numbers, and letting them move after the total was approved
        would make the approved total a lie."""
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        if (actor.effective_role == "admin"
                or await MeetingService.user_is_pm_member(session, actor)):
            return True
        if change.status != "costing":
            return False
        return await WorkflowService.actor_in_department(
            session, actor, department_id)

    @staticmethod
    async def readable_department_ids(
        session: AsyncSession, change: ChangeRequest, actor: User,
    ) -> set | None:
        """Which departments' positions this caller may see. None means all —
        PM, Sales, the change lead and admins price the change as a whole, so
        seeing one department's numbers without the others would be useless to
        them. Everyone else sees their own departments."""
        from app.services.change_service import ChangeService
        from app.services.meeting_service import MeetingService
        from app.services.workflow_service import WorkflowService
        if (actor.effective_role == "admin" or change.lead_id == actor.id
                or await MeetingService.user_is_pm_member(session, actor)
                or await ChangeService._user_in_department(
                    session, actor, "Sales")):
            return None
        return set(await WorkflowService.effective_department_ids(session, actor))

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
        out = []
        for p in positions:
            favorite = p.favorite_offer
            out.append({
                "id": p.id, "change_id": p.change_id,
                "department_id": p.department_id, "label": p.label,
                "tag": p.tag, "kind": p.kind, "pricing": p.pricing,
                "est_cost": p.est_cost, "hours": p.hours,
                "lead_time_days": p.lead_time_days,
                "lead_time_unit": p.lead_time_unit, "notes": p.notes,
                "created_by": p.created_by, "created_at": p.created_at,
                "updated_at": p.updated_at,
                "effective_cost": p.effective_cost,
                "effective_lead_time_days": p.effective_lead_time_days,
                "effective_lead_time_unit": p.effective_lead_time_unit,
                "effective_lead_time_calendar_days":
                    p.effective_lead_time_calendar_days,
                "favorite_offer_id": favorite.id if favorite else None,
                "offers": [{
                    "id": o.id, "position_id": o.position_id,
                    "vendor_name": o.vendor_name, "cost": o.cost,
                    "shipping_cost": o.shipping_cost,
                    "shipping_included": o.shipping_included,
                    "lead_time_days": o.lead_time_days,
                    "lead_time_unit": o.lead_time_unit,
                    "lead_time_calendar_days": o.lead_time_calendar_days,
                    "favorite": o.favorite, "total_cost": o.total_cost,
                    "created_by": o.created_by, "created_at": o.created_at,
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

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
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
        position = CostingPosition(
            change_id=change.id, department_id=department_id,
            label=(spec.get("label") or "").strip(),
            tag=(spec.get("tag") or None),
            kind=spec.get("kind") or "external",
            pricing=spec.get("pricing") or "estimate",
            est_cost=spec.get("est_cost"), hours=spec.get("hours"),
            lead_time_days=spec.get("lead_time_days"),
            lead_time_unit=spec.get("lead_time_unit") or "calendar_days",
            notes=spec.get("notes"), created_by=actor.id,
        )
        CostingPositionService._validate(position)
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
        for field in _POSITION_FIELDS:
            if field in spec:
                setattr(position, field, spec[field])
        if position.label:
            position.label = position.label.strip()
        CostingPositionService._validate(position)
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
            actor.id, old_value={"label": label, "department_id": department_id})
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
            created_by=actor.id,
        )
        CostingPositionService._validate_offer(offer, position)
        session.add(offer)
        await session.flush()
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
                       "total_cost": offer.total_cost})
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
                       "total_cost": offer.total_cost})
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
            old_value={"position_id": position.id, "vendor_name": vendor})
        return paths

    # ------------------------------------------------------------------
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
                       "effective_cost": position.effective_cost})
