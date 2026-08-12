"""The negotiation loop at 'quoted': rounds with the customer and their result.

The quote goes out and the answer is rarely a plain yes. What comes back is a
sequence of rounds — a call, a meeting, a mail thread — each moving something,
until one of them ends it. Those rounds are the record behind the go-ahead:
without them the accepted price is a number nobody can explain six months later.

Who may write is the quote rule everywhere else: Sales owns the customer
relationship, so a Sales member, the change lead or an admin records the
rounds (ChangeService.user_can_set_quoted_price — acts-as aware). Who may READ
is the commercial crowd: the same people who see the costing numbers, because a
negotiation round IS a costing number in a sentence.

Deciding the go-ahead itself is NOT here: acceptance (with its mandatory
release deadline) is existing, built mechanics and stays the only way a quoted
change moves on. This module records what that decision is taken on.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeNegotiation, ChangeRequest, NEGOTIATION_CHANNELS,
)
from app.models.entities import User
from app.services.change_service import ChangeService, ChangeError

# Rounds are recorded while the offer is out with the customer and nowhere
# else: before 'quoted' there is nothing to negotiate about, after it the
# decision has already been taken on the record they left.
NEGOTIATION_STATUS = "quoted"


class NegotiationService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def may_read(session: AsyncSession, change: ChangeRequest,
                       actor: User) -> bool:
        """The commercial crowd: admin, the change lead, Project Management,
        Sales. Same set that reads the summation and the costing positions —
        a counter price is one of those numbers."""
        from app.services.meeting_service import MeetingService
        if actor.effective_role == "admin" or change.lead_id == actor.id:
            return True
        if await MeetingService.user_is_pm_member(session, actor):
            return True
        return await ChangeService._user_in_department(session, actor, "Sales")

    @staticmethod
    def may_delete(row: "ChangeNegotiation", actor: User) -> bool:
        """Taking a round back is the author's own correction — not Sales'
        collective one. An admin keeps the janitorial override."""
        return actor.effective_role == "admin" or row.created_by == actor.id

    @staticmethod
    async def may_write(session: AsyncSession, change: ChangeRequest,
                        actor: User) -> bool:
        """Whoever may write the price may write what the customer said about
        it: admin, the change lead, or a Sales member."""
        return await ChangeService.user_can_set_quoted_price(
            session, actor, change)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def list_rounds(session: AsyncSession,
                          change: ChangeRequest) -> list[ChangeNegotiation]:
        return list((await session.execute(
            select(ChangeNegotiation)
            .where(ChangeNegotiation.change_id == change.id)
            .order_by(ChangeNegotiation.id))).scalars().all())

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    @staticmethod
    async def record_round(
        session: AsyncSession, change: ChangeRequest, actor: User, *,
        channel: str, note: str, counter_price: Optional[float] = None,
        is_final: bool = False,
    ) -> ChangeNegotiation:
        if change.status != NEGOTIATION_STATUS:
            raise ChangeError(
                "Negotiation rounds can only be recorded while the quote is "
                "out with the customer (status 'quoted')")
        if channel not in NEGOTIATION_CHANNELS:
            raise ChangeError(f"Invalid channel '{channel}'")
        if not (note or "").strip():
            raise ChangeError("A negotiation round must record its result")
        if counter_price is not None and counter_price < 0:
            raise ChangeError("A counter price cannot be negative")

        row = ChangeNegotiation(
            change_id=change.id, channel=channel, note=note.strip(),
            counter_price=counter_price, is_final=bool(is_final),
            created_by=actor.id)
        session.add(row)
        await session.flush()
        if row.is_final:
            # One negotiation, one result: a newly declared final round demotes
            # whatever was final before it (the parties came back to the table),
            # rather than refusing — refusing would leave the true result
            # unrecordable.
            await NegotiationService._clear_other_finals(session, change, row.id)
            await ChangeService.append_changelog(
                session, change, "negotiation_final",
                f"Negotiation closed ({channel}): {row.note}", actor.id,
                new_value={"negotiation_id": row.id, "channel": channel,
                           "counter_price": row.counter_price})
        else:
            await ChangeService.append_changelog(
                session, change, "negotiation_round",
                f"Negotiation round #{row.id} recorded ({channel})", actor.id,
                new_value={"negotiation_id": row.id, "channel": channel,
                           "counter_price": row.counter_price})
        return row

    @staticmethod
    async def _clear_other_finals(session: AsyncSession, change: ChangeRequest,
                                  keep_id: int) -> None:
        rows = (await session.execute(
            select(ChangeNegotiation).where(
                ChangeNegotiation.change_id == change.id,
                ChangeNegotiation.is_final.is_(True),
                ChangeNegotiation.id != keep_id))).scalars().all()
        for r in rows:
            r.is_final = False
        if rows:
            await session.flush()

    @staticmethod
    async def get_round(session: AsyncSession, change: ChangeRequest,
                        negotiation_id: int) -> ChangeNegotiation:
        row = await session.get(ChangeNegotiation, negotiation_id)
        if row is None or row.change_id != change.id:
            raise ChangeError("Negotiation round not found on this change")
        return row

    @staticmethod
    async def delete_round(
        session: AsyncSession, change: ChangeRequest,
        row: ChangeNegotiation, actor: User,
    ) -> None:
        """Typo repair, not history rewriting: only the author (or an admin)
        may take a round back, and only while the negotiation is still running.
        The changelog entry the round wrote stays where it is."""
        if change.status != NEGOTIATION_STATUS:
            raise ChangeError(
                "A negotiation round can only be removed while the change is "
                "still 'quoted'")
        if not NegotiationService.may_delete(row, actor):
            raise ChangeError(
                "Only the author of a negotiation round or an admin may "
                "remove it")
        gone = {"negotiation_id": row.id, "channel": row.channel,
                "is_final": row.is_final}
        await session.delete(row)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "negotiation_removed",
            f"Negotiation round #{gone['negotiation_id']} removed", actor.id,
            old_value=gone)
