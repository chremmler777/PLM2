"""Cost-assessment models digitizing the GB-CM-0001 department tabs:
per-department×plant rates, the seeded activity catalog, per-line costs, the
three D1 gates, and the costing positions that price what hours×rate cannot."""
from datetime import date, datetime

from sqlalchemy import (
    String, Text, DateTime, Date, Float, Integer, Boolean, Numeric, ForeignKey, JSON,
)
from sqlalchemy import false as sa_false
from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base
from app.utils.clock import business_today

COST_KINDS = ("one_time", "lifecycle")

# What a costing position IS.
#   internal_effort  the time this department spent on the assessment itself
#   support_effort   the time it expects to spend supporting implementation
#   external         work that leaves the house, priced by a supplier
# internal_effort / support_effort: the two standing answers every department
# owes. own_time: any further line of the department's hours (valued at its
# rate). external: money spent outside, estimated or quoted.
# machine_time: hours x the machine class rate; sampling: trials x the
# sampling price of the class (both from the cost sheet, spec §15a).
COSTING_POSITION_KINDS = ("internal_effort", "support_effort", "own_time", "external",
                          "machine_time", "sampling")
# The kinds whose hours are the department's own labour, priced at the
# effective labour rate of the cost sheet.
LABOUR_KINDS = ("internal_effort", "support_effort", "own_time", "external")
# The standing answers: at most ONE row per change, department and kind (the
# partial unique index below, migration 101). A second save of the same
# answer (blur + click) merges into the first instead of adding a line.
STANDING_KINDS = ("internal_effort", "support_effort")
_STANDING_WHERE = text("kind IN ('internal_effort', 'support_effort')")
# How an EXTERNAL position gets its number: a house estimate, or real vendor
# offers. Effort positions are always estimates — the field is stored uniformly
# so the column never has to be read conditionally, but only external positions
# are allowed to say "quote".
COSTING_PRICINGS = ("estimate", "quote")
# Spec §4: what a position's number stands on. rate: hours x the department
# rate; quote: a supplier's quote (quote_ref + file); same_as: an earlier part
# + what differs; estimate: a house number + its reference.
COSTING_BASES = ("rate", "quote", "same_as", "estimate")
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
    effective_from: Mapped[date] = mapped_column(Date, default=lambda: business_today())


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
    # None = no rate was found when the line was priced (099): never 0.
    rate_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    internal_cost: Mapped[float] = mapped_column(Float, default=0.0)
    external_cost: Mapped[float] = mapped_column(Float, default=0.0)
    # Lifecycle lines price the change per part: minutes added (or, negative,
    # saved) on every shot for the life of the programme.
    minutes_per_part: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where rate_snapshot came from (098): the plant's currency, the cost
    # sheet version (None for the department_rate fallback) and the source.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    cost_sheet_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("cost_sheet_versions.id"), nullable=True)
    rate_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

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
    __table_args__ = (
        Index("uq_costing_positions_standing", "change_id", "department_id", "kind",
              unique=True, postgresql_where=_STANDING_WHERE,
              sqlite_where=_STANDING_WHERE),
    )

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
    # Who the house number came from, on an estimated external line ("Hasco,
    # by phone"). A quoted line names its vendors on the offers instead.
    vendor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hours: Mapped[float | None] = mapped_column(
        Numeric(10, 2, asdecimal=False), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_unit: Mapped[str] = mapped_column(
        String(20), default="calendar_days", server_default="calendar_days")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing inputs of the cost-sheet kinds (098): the labour position that
    # picks a position rate (Engineer, Technician; None = department
    # default), the machine class of machine_time / sampling lines, and the
    # number of trials of a sampling line.
    labour_position: Mapped[str | None] = mapped_column(String(80), nullable=True)
    machine_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("cost_sheet_machine_classes.id"), nullable=True)
    trials: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A named press of a machine_time / sampling line (105): its own rate in
    # the cost sheet beats the class rate; None = priced on the class.
    machine_id: Mapped[int | None] = mapped_column(
        ForeignKey("cost_sheet_machines.id"), nullable=True)
    # The rate snapshot, written when the line is priced (created, or its
    # pricing inputs changed) and read by the summation from then on, so a
    # later cost sheet version never moves a costed line under its owner.
    # rate_on None = no snapshot: never priced, or no rate was found when
    # it was (priced live then, "cannot price", never 0). currency is the
    # money currency of the line (est_cost, offers: the costing plant's);
    # rate_currency the currency of the rate (099), which the cost sheet row
    # may state differently.
    rate: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    rate_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    rate_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cost_sheet_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("cost_sheet_versions.id"), nullable=True)
    cost_sheet_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_match: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rate_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    rate_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Spec §4 costing positions (C25, migration 129): the basis of the
    # number (COSTING_BASES; NULL legacy = read from kind and pricing), its
    # reference (estimate: earlier tool, supplier figure + date), the part it
    # is the same as and what differs; and, once an offer was sent or the
    # internal approval given on an estimate, how the quote compares
    # (estimate_check pending | within | above | settled: the open price it
    # caused was absorbed or accepted; estimate_over = by how much).
    basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    basis_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    basis_part_id: Mapped[int | None] = mapped_column(
        ForeignKey("parts.id"), nullable=True)
    basis_differs: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A3-07 (spec §4 [R3]): how many of what a money line stands for
    # ("2 inserts"); NULL on lines entered before migration 142.
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estimate_check: Mapped[str | None] = mapped_column(String(10), nullable=True)
    estimate_over: Mapped[float | None] = mapped_column(
        Numeric(14, 2, asdecimal=False), nullable=True)
    # Christoph 2026-11-09 (158): a spare part line says whether it is
    # needed for the change. True: its delivery counts for the lead time
    # (it may be the time leader); False: it is excluded from every lead-time
    # roll-up; None: not answered yet (counts, and Finalize asks for it).
    time_critical: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def effective_basis(self) -> str:
        """The basis, read from kind and pricing where none was named."""
        if self.kind != "external":
            return "rate"
        if self.pricing == "quote":
            return "quote"
        return self.basis if self.basis in ("same_as", "estimate") else "estimate"

    @property
    def estimated(self) -> bool:
        """Shown as 'estimated' on the offer and the approval (spec §4): an
        external line priced on an estimate with money on it."""
        return (self.kind == "external" and self.pricing != "quote"
                and bool(self.est_cost))

    offers: Mapped[list["CostingOffer"]] = relationship(
        back_populates="position", cascade="all, delete-orphan",
        lazy="selectin", order_by="CostingOffer.id",
    )

    # An offer is either an ALTERNATIVE (a full quote: one of them is bought,
    # the star says which the department recommends) or a PART (a partial
    # quote: always counted, summed with the other parts). A line may carry
    # both: parts that add up plus alternatives for the remainder.
    @property
    def alternatives(self) -> list["CostingOffer"]:
        return [o for o in self.offers if not o.is_partial]

    @property
    def parts(self) -> list["CostingOffer"]:
        return [o for o in self.offers if o.is_partial]

    @property
    def per_piece(self) -> float:
        """Christoph 2026-11-08: a spare part line (unit 'pcs') is priced per
        piece: its prices count amount x price, transport once on top."""
        if self.kind == "external" and (self.quantity_unit or "") == "pcs" and (self.quantity or 0) > 0:
            return float(self.quantity)
        return 1.0

    def offer_total(self, offer: "CostingOffer") -> float:
        """An offer's invoiced total on this line (amount x price + transport)."""
        return offer.total_cost + float(offer.cost or 0.0) * (self.per_piece - 1.0)

    @property
    def parts_cost(self) -> float:
        return float(sum(self.offer_total(o) for o in self.parts))

    @property
    def favorite_offer(self) -> "CostingOffer | None":
        """The alternative this position is priced from: the department's
        favorite, or — with exactly one alternative — that one; a single offer
        needs no vote to be the answer. Several alternatives without a vote
        give None: the department has not finished the job."""
        alts = self.alternatives
        if not alts:
            return None
        for offer in alts:
            if offer.favorite:
                return offer
        return alts[0] if len(alts) == 1 else None

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
            return self._quoted_total(self.favorite_offer)
        return None if self.est_cost is None else float(self.est_cost) * self.per_piece

    def _quoted_total(self, alternative: "CostingOffer | None") -> float | None:
        """Parts always add up; the alternative that counts is added on top.
        None when nothing has been quoted, or when alternatives exist and
        none of them counts yet."""
        if not self.offers:
            return None
        if self.alternatives and alternative is None:
            return None
        return self.parts_cost + (self.offer_total(alternative) if alternative else 0.0)

    def counted_offers(self, alternative: "CostingOffer | None") -> list["CostingOffer"]:
        return self.parts + ([alternative] if alternative else [])

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
        if chosen is not None and self.kind == "external" and self.pricing == "quote":
            return self._quoted_total(chosen)
        return self.effective_cost

    @property
    def is_spare_part(self) -> bool:
        """A spare part line: external, and its notes or label say so
        ("From the assessment: Spare part required", "Spare part: <name>")."""
        if self.kind != "external":
            return False
        text = f"{self.notes or ''} {self.label or ''}".lower()
        return "spare part" in text or "ersatzteil" in text

    @property
    def counts_for_lead_time(self) -> bool:
        """Christoph 2026-11-09: a spare part that is not time critical does
        not set the lead time (the tool change favourite does). Unanswered
        counts: the safe side until the department says."""
        return not (self.is_spare_part and self.time_critical is False)

    @property
    def _lead_time_source(self):
        """(days, unit) — the favorite offer's dates when the supplier is the
        one who set them, the position's own otherwise. Same precedence as
        effective_cost: on a quoted position the chosen offer IS the answer,
        and the offer's own dates beat a stale estimate typed above it."""
        if self.kind == "external" and self.pricing == "quote":
            # The slowest of what is counted: parts wait in parallel, the
            # line is done when the last of them lands.
            dated = [o for o in self.counted_offers(self.favorite_offer)
                     if o.lead_time_days is not None]
            if dated:
                slowest = max(dated, key=lambda o: o.lead_time_calendar_days or 0)
                return slowest.lead_time_days, slowest.lead_time_unit
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


class DepartmentCostCategory(Base):
    """A cost category a department added to its own list.

    The coded categories (app/services/costing_tags.py) are the reviewed
    baseline; this is the department's extension — added from the costing
    table, typed money or time so the line under it knows what to ask for.
    Keys are namespaced per department. Soft-deleted: off the dropdown, rows
    filed under it keep their key.
    """
    __tablename__ = "department_cost_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("wf_departments.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120))
    entry_type: Mapped[str] = mapped_column(String(10), default="money")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


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
    # A PARTIAL quote covers part of the line and is always counted, summed
    # with the other parts. A full quote (the default) is an alternative:
    # one of them is bought, the star recommends which.
    is_partial: Mapped[bool] = mapped_column(
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
    # C25 (migration 129): the supplier's quote number, its date, how long it
    # holds. A quoted position finalizes only with a quote_ref and a file.
    quote_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quoted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

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
    # yes|no|na, None until someone decides it (a seeded gate is undecided)
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    change: Mapped["ChangeRequest"] = relationship(back_populates="gates")


# Spec §4 "Waiting on supplier" (one state everywhere): the phase a wait
# belongs to. costing: a supplier quote the department waits for;
# implementation: the supplier's delivery (a tool change, a part).
SUPPLIER_WAIT_PHASES = ("costing", "implementation")
# How a wait ended: the quote / delivery came in, the lead priced the
# department on its estimate instead (§5), or it was not needed after all.
SUPPLIER_WAIT_ENDS = ("received", "price_on_estimate", "not_needed")


class SupplierWait(Base):
    """A department waits on a supplier (spec §4, migration 128): vendor,
    asked on, expected by. The one wait that pauses the late clock with the
    customer's (spec §0): the department's task is due at expected-by; the
    header says "Waiting on <vendor> since <date>"; close costing lists it
    and the lead picks "Wait for <vendor>" or "Price on estimate"."""
    __tablename__ = "supplier_waits"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    phase: Mapped[str] = mapped_column(String(20), default="costing")
    vendor_name: Mapped[str] = mapped_column(String(120))
    asked_on: Mapped[date] = mapped_column(Date)
    expected_by: Mapped[date] = mapped_column(Date)
    # what it is for: the costing position a quote prices (optional)
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("costing_positions.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def chip(self, today: date | None = None) -> str:
        """'day 9 of 21': days since asked against the days it was given."""
        today = today or business_today()
        span = max((self.expected_by - self.asked_on).days, 1)
        day = max((today - self.asked_on).days + 1, 1)
        return f"day {day} of {span}"
