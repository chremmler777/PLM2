"""Cost-assessment models digitizing the GB-CM-0001 department tabs:
per-department×plant rates, the seeded activity catalog, per-line costs, the
three D1 gates, and the costing positions that price what hours×rate cannot."""
from datetime import date, datetime

from sqlalchemy import (
    String, Text, DateTime, Date, Float, Integer, Boolean, Numeric, ForeignKey,
)
from sqlalchemy import false as sa_false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

COST_KINDS = ("one_time", "lifecycle")

# What a costing position IS.
#   internal_effort  the time this department spent on the assessment itself
#   support_effort   the time it expects to spend supporting implementation
#   external         work that leaves the house, priced by a supplier
COSTING_POSITION_KINDS = ("internal_effort", "support_effort", "external")
# How an EXTERNAL position gets its number: a house estimate, or real vendor
# offers. Effort positions are always estimates — the field is stored uniformly
# so the column never has to be read conditionally, but only external positions
# are allowed to say "quote".
COSTING_PRICINGS = ("estimate", "quote")
# What "30 days" means. A tool shop quotes working days; a planning board
# usually means the calendar. Rolling the two up together understates the
# timeline, so the unit is recorded rather than assumed.
LEAD_TIME_UNITS = ("business_days", "calendar_days")


def to_calendar_days(days: int | None, unit: str | None) -> int | None:
    """Lead time in calendar days, whatever unit it was given in.

    Five working days are seven calendar days, so business days scale by 7/5
    and round UP — a lead time that lands mid-weekend is not delivered on the
    Saturday. Every roll-up compares in this unit, because comparing a max
    across mixed units is how a supplier's 30 working days quietly became four
    weeks on the plan.
    """
    if days is None:
        return None
    if unit == "business_days":
        return -(-days * 7 // 5)      # ceil without importing math
    return days
GATE_KEYS = ("feasibility", "budget", "release")
GATE_DECISIONS = ("yes", "no", "na")
# Which transition each gate guards (additive; see Global Constraints).
GATE_TARGET_STATUS = {"feasibility": "in_assessment", "budget": "costing", "release": "in_implementation"}


class DepartmentRate(Base):
    """Hourly rate for a department at a plant (from the Std.-Sätze sheet)."""
    __tablename__ = "department_rate"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    hourly_rate: Mapped[float] = mapped_column(Float)
    min_factor: Mapped[float] = mapped_column(Float, default=1.0)
    effective_from: Mapped[date] = mapped_column(Date, default=date.today)


class AssessmentActivity(Base):
    """A predefined cost-line activity offered to a department (its selection list)."""
    __tablename__ = "assessment_activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AssessmentCostLine(Base):
    """One cost line on a department's assessment tab (per plant, one-time or lifecycle)."""
    __tablename__ = "assessment_cost_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("change_assessments.id"), index=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), index=True)
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_activity.id"), nullable=True)
    activity_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_kind: Mapped[str] = mapped_column(String(20), default="one_time")
    demand_hours: Mapped[float] = mapped_column(Float, default=0.0)
    rate_snapshot: Mapped[float] = mapped_column(Float, default=0.0)
    internal_cost: Mapped[float] = mapped_column(Float, default=0.0)
    external_cost: Mapped[float] = mapped_column(Float, default=0.0)
    # Lifecycle lines price the change per part: minutes added (or, negative,
    # saved) on every shot for the life of the programme.
    minutes_per_part: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped["ChangeAssessment"] = relationship(back_populates="cost_lines")


class CostingPosition(Base):
    """One thing that has to be paid for, owned by one department.

    Deliberately not a cost line: a cost line is hours × the department's rate
    at a plant, which is the wrong shape for a supplier's price. A position is
    a label ("new hot runner nozzle"), an optional tag so positions can be
    counted across changes, and either an estimate or a set of vendor offers.
    Positions ADD to the cost-line math; they do not replace it.
    """
    __tablename__ = "costing_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("wf_departments.id"), index=True)

    label: Mapped[str] = mapped_column(String(200))
    # Free text at write time; GET /reference/costing-tags only suggests.
    tag: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(30), default="external", server_default="external")
    pricing: Mapped[str] = mapped_column(
        String(20), default="estimate", server_default="estimate")

    # asdecimal=False: every consumer of these is float math (the summation,
    # the P&L snapshot, JSON), and mixing Decimal into it buys nothing but
    # TypeErrors.
    est_cost: Mapped[float | None] = mapped_column(
        Numeric(14, 2, asdecimal=False), nullable=True)
    hours: Mapped[float | None] = mapped_column(
        Numeric(10, 2, asdecimal=False), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_unit: Mapped[str] = mapped_column(
        String(20), default="calendar_days", server_default="calendar_days")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    offers: Mapped[list["CostingOffer"]] = relationship(
        back_populates="position", cascade="all, delete-orphan",
        lazy="selectin", order_by="CostingOffer.id",
    )

    @property
    def favorite_offer(self) -> "CostingOffer | None":
        """The offer this position is priced from: the department's favorite,
        or — when nobody has voted yet — the first one that came in. A single
        offer needs no vote to be the answer."""
        if not self.offers:
            return None
        for offer in self.offers:
            if offer.favorite:
                return offer
        return min(self.offers, key=lambda o: o.id)

    @property
    def recommended_offer(self) -> "CostingOffer | None":
        """The department's actual VOTE, or None if it never cast one.

        Deliberately not favorite_offer: that property falls back to the first
        offer so a position with a single quote still has a price, which is
        the right rule for MONEY and the wrong one for a RECOMMENDATION. A
        fallback here would invent an opinion the department never expressed
        and then demand Sales justify disagreeing with it.
        """
        for offer in self.offers:
            if offer.favorite:
                return offer
        return None

    @property
    def chosen_offer(self) -> "CostingOffer | None":
        """The offer SALES decided on, if they have decided. Never falls back
        to the favorite: the whole point of the column is that "the department
        recommended A" and "we are buying from A" are different statements,
        and a fallback would make the second one unfalsifiable."""
        for offer in self.offers:
            if offer.chosen:
                return offer
        return None

    @property
    def effective_cost(self) -> float | None:
        """What this position actually costs, whichever way it is priced.

        A quoted external position is worth its favorite offer plus shipping,
        unless the offer already includes it. Everything else — an estimated
        external position, both effort kinds — is worth its estimate. None
        means nobody has said yet, which is not the same as zero.
        """
        if self.kind == "external" and self.pricing == "quote":
            offer = self.favorite_offer
            if offer is None:
                return None
            total = float(offer.cost or 0.0)
            if not offer.shipping_included:
                total += float(offer.shipping_cost or 0.0)
            return total
        return None if self.est_cost is None else float(self.est_cost)

    @property
    def quoted_cost(self) -> float | None:
        """What this position costs in the OFFER — the money Sales is putting
        in front of the customer.

        Identical to effective_cost until Sales decides against the
        department's recommendation, and the chosen offer's price from then
        on. effective_cost deliberately stays favorite-driven: it is the
        department's own number, the one it defends in the costing meeting,
        and rewriting it under the department's feet would leave nobody able
        to see that the buyer moved the price.
        """
        chosen = self.chosen_offer
        if chosen is not None:
            return chosen.total_cost
        return self.effective_cost

    @property
    def _lead_time_source(self):
        """(days, unit) — the favorite offer's dates when the supplier is the
        one who set them, the position's own otherwise. Same precedence as
        effective_cost: on a quoted position the chosen offer IS the answer,
        and the offer's own dates beat a stale estimate typed above it."""
        if self.kind == "external" and self.pricing == "quote":
            offer = self.favorite_offer
            if offer is not None and offer.lead_time_days is not None:
                return offer.lead_time_days, offer.lead_time_unit
        return self.lead_time_days, self.lead_time_unit

    @property
    def effective_lead_time_days(self) -> int | None:
        """The lead time that counts, in the unit it was given in."""
        return self._lead_time_source[0]

    @property
    def effective_lead_time_unit(self) -> str:
        return self._lead_time_source[1] or "calendar_days"

    @property
    def effective_lead_time_calendar_days(self) -> int | None:
        """The same lead time in calendar days — what every roll-up compares
        and reports, so business and calendar quotes can share one max."""
        days, unit = self._lead_time_source
        return to_calendar_days(days, unit)


class CostingOffer(Base):
    """One vendor's answer to an external costing position.

    Several offers per position is the normal case — comparing them IS the
    work. `favorite` records which one the department would take; who actually
    gets the order is Sales' decision later, and is not modelled here.
    """
    __tablename__ = "costing_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("costing_positions.id"), index=True)

    vendor_name: Mapped[str] = mapped_column(String(120))
    cost: Mapped[float] = mapped_column(
        Numeric(14, 2, asdecimal=False), default=0.0, server_default="0")
    # Either a separate line, or declared part of the price. Both happen.
    shipping_cost: Mapped[float | None] = mapped_column(
        Numeric(14, 2, asdecimal=False), nullable=True)
    shipping_included: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false())
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_unit: Mapped[str] = mapped_column(
        String(20), default="calendar_days", server_default="calendar_days")
    favorite: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false())
    # Sales' DECISION, as against `favorite` above, which is the department's
    # recommendation. Two facts, two columns: which supplier the engineers
    # wanted and which one the buyer took are different questions, and the
    # only interesting one is asked when the answers differ. chosen_reason is
    # required (in the service) exactly then — overruling your own engineers
    # is allowed, doing it anonymously and without saying why is not.
    chosen: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa_false())
    chosen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    chosen_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    chosen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)

    position: Mapped["CostingPosition"] = relationship(back_populates="offers")

    @property
    def lead_time_calendar_days(self) -> int | None:
        """This vendor's promise on the calendar, for comparing offers whose
        quotes are written in different units."""
        return to_calendar_days(self.lead_time_days, self.lead_time_unit)

    @property
    def total_cost(self) -> float:
        """Price as it will actually be invoiced: shipping added unless the
        vendor said it is already in there."""
        total = float(self.cost or 0.0)
        if not self.shipping_included:
            total += float(self.shipping_cost or 0.0)
        return total


class ChangeGate(Base):
    """One of the three D1 'Final assessment' gates on a change."""
    __tablename__ = "change_gate"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    gate_key: Mapped[str] = mapped_column(String(20))  # feasibility|budget|release
    decision: Mapped[str] = mapped_column(String(10), default="na")  # yes|no|na
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="gates")
