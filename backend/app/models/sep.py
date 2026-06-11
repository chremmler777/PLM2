"""SEP Q-Gate models - strict stage-gate process per GB-DP-0001 SEP matrix.

A project activates SEP, which copies the seeded template (7 gates, 232 work
items) into project-owned rows. Gates run strictly in sequence; closing a gate
requires PM + Quality sign-off and locks its items.
"""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

SEP_ITEM_STATUSES = ("open", "done", "not_applicable")
SEP_GATE_STATUSES = ("pending", "in_progress", "closed")
SEP_RISK_STATUSES = ("open", "started", "finished")

# Risk priority thresholds from the matrix: RKZ = (Q + C + S) * probability
SEP_RISK_PRIORITIES = (
    (0.4, "low"),
    (0.8, "medium"),
    (1.0, "high"),
)  # above 1.0 -> very_high (project goal at risk)


def risk_priority(rkz: float) -> str:
    for limit, name in SEP_RISK_PRIORITIES:
        if rkz <= limit:
            return name
    return "very_high"


class SepGate(Base):
    """One Q-gate (K0/RG1 .. A/RG7) of a project's SEP run."""
    __tablename__ = "sep_gates"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)

    code: Mapped[str] = mapped_column(String(20))  # e.g. "K0/RG1"
    seq: Mapped[int] = mapped_column(Integer)  # 1..7, strict order
    phase_de: Mapped[str] = mapped_column(String(200))
    phase_en: Mapped[str] = mapped_column(String(200))

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    target_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    milestone_id: Mapped[int | None] = mapped_column(ForeignKey("project_milestones.id"), nullable=True)

    # Dual sign-off (Project Manager AND Quality) closes and locks the gate
    pm_signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    pm_signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quality_signed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    quality_signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items: Mapped[list["SepWorkItem"]] = relationship(
        back_populates="gate", cascade="all, delete-orphan", order_by="SepWorkItem.item_no"
    )
    risks: Mapped[list["SepRisk"]] = relationship(
        back_populates="gate", cascade="all, delete-orphan", order_by="SepRisk.id"
    )


class SepWorkItem(Base):
    """One checklist work item within a gate (copied from the template)."""
    __tablename__ = "sep_work_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    gate_id: Mapped[int] = mapped_column(ForeignKey("sep_gates.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)

    item_no: Mapped[int] = mapped_column(Integer)
    title_de: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    psp_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    department: Mapped[str] = mapped_column(String(80))

    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    gate: Mapped["SepGate"] = relationship(back_populates="items")


class SepItemAudit(Base):
    """Audit trail for work item changes (who/when/field/old->new)."""
    __tablename__ = "sep_item_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("sep_work_items.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    field: Mapped[str] = mapped_column(String(30))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SepRisk(Base):
    """Gate-level risk entry per the matrix risk assessment tab.

    rkz = (q_impact + c_impact + s_impact) * probability; priority derived
    via risk_priority(). A yellow/red gate cannot be signed off unless every
    risk has countermeasure + due date + responsible.
    """
    __tablename__ = "sep_risks"

    id: Mapped[int] = mapped_column(primary_key=True)
    gate_id: Mapped[int] = mapped_column(ForeignKey("sep_gates.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)

    effect: Mapped[str] = mapped_column(Text)  # "Auswirkung" - what is at risk
    q_impact: Mapped[float] = mapped_column(Float, default=0.0)  # quality, 0..1
    c_impact: Mapped[float] = mapped_column(Float, default=0.0)  # cost, 0..1
    s_impact: Mapped[float] = mapped_column(Float, default=0.0)  # schedule, 0..1
    probability: Mapped[float] = mapped_column(Float, default=0.0)  # EWS, 0..1

    countermeasure: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    gate: Mapped["SepGate"] = relationship(back_populates="risks")

    @property
    def rkz(self) -> float:
        return round((self.q_impact + self.c_impact + self.s_impact) * self.probability, 3)

    @property
    def priority(self) -> str:
        return risk_priority(self.rkz)
