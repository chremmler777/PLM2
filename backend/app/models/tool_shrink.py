"""Tool shrinkage decision record: which shrinkage a tool's steel is cut with, where that value
came from and why it was chosen, and after the first trials whether it was right.

A decision holds either one combined value or parallel + normal. One row per decision. A new decision supersedes the current one (history stays). The current
decision's values are what parts.tool_shrink_parallel_pct / _normal_pct hold. After the
trial the decision is verified with the measured shrinkage; the result is reported back to
MaterialDB as a shrinkage experience of the material, so the next tool sees it."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

SHRINK_SOURCE_KINDS = ("datasheet", "supplier", "ktx_experience", "own")
SHRINK_VERDICTS = ("correct", "offset", "wrong")
SHRINK_FEEDBACK = ("sent", "failed", "skipped")


class ToolShrinkDecision(Base):
    __tablename__ = "tool_shrink_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="current")  # current | superseded

    # Either one combined value, or parallel + normal (113)
    parallel_pct: Mapped[float | None] = mapped_column(Numeric(5, 3, asdecimal=False), nullable=True)
    normal_pct: Mapped[float | None] = mapped_column(Numeric(5, 3, asdecimal=False), nullable=True)
    combined_pct: Mapped[float | None] = mapped_column(Numeric(5, 3, asdecimal=False), nullable=True)
    # Where the value came from: datasheet, supplier statement, KTX tool experience, own value
    source_kind: Mapped[str] = mapped_column(String(20))
    source_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    materialdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    material_label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Every candidate shown when the decision was taken (MaterialDB values can change later)
    candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # After the trial: the shrinkage the parts really showed
    measured_parallel_pct: Mapped[float | None] = mapped_column(Numeric(5, 3, asdecimal=False), nullable=True)
    measured_normal_pct: Mapped[float | None] = mapped_column(Numeric(5, 3, asdecimal=False), nullable=True)
    measured_combined_pct: Mapped[float | None] = mapped_column(Numeric(5, 3, asdecimal=False), nullable=True)
    measured_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    next_time_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Report to MaterialDB
    feedback_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    feedback_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
