"""Quality module models - PPAP submissions per revision."""
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

# AIAG PPAP elements (standard 18)
PPAP_ELEMENTS = [
    "Design Records",
    "Engineering Change Documents",
    "Customer Engineering Approval",
    "Design FMEA",
    "Process Flow Diagram",
    "Process FMEA",
    "Control Plan",
    "Measurement System Analysis (MSA)",
    "Dimensional Results",
    "Material / Performance Test Results",
    "Initial Process Studies (SPC)",
    "Qualified Laboratory Documentation",
    "Appearance Approval Report",
    "Sample Production Parts",
    "Master Sample",
    "Checking Aids",
    "Customer-Specific Requirements",
    "Part Submission Warrant (PSW)",
]

# Which element indexes (0-based) are required per submission level.
# Level 1: PSW (+ appearance report where applicable) submitted to customer.
# Level 2: PSW with product samples and limited supporting data.
# Level 3 (default): PSW with product samples and complete supporting data.
# Level 4: PSW and other requirements as defined by the customer.
# Level 5: PSW with complete supporting data reviewed at supplier's site.
PPAP_REQUIRED_BY_LEVEL: dict[int, set[int]] = {
    1: {12, 17},
    2: {0, 8, 9, 12, 13, 17},
    3: {0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17},
    4: {17},
    5: set(range(18)),
}


class PPAPSubmission(Base):
    """A PPAP package for one part revision."""
    __tablename__ = "ppap_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("part_revisions.id"), index=True)

    level: Mapped[int] = mapped_column(Integer, default=3)  # 1-5
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft, submitted, approved, rejected
    customer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    elements: Mapped[list["PPAPElement"]] = relationship(
        back_populates="submission", cascade="all, delete-orphan", order_by="PPAPElement.position"
    )


class PPAPElement(Base):
    """One checklist element of a PPAP submission."""
    __tablename__ = "ppap_elements"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("ppap_submissions.id"), index=True)

    position: Mapped[int] = mapped_column(Integer)  # 1-18
    name: Mapped[str] = mapped_column(String(120))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, attached, approved, rejected, na
    file_id: Mapped[int | None] = mapped_column(ForeignKey("revision_files.id"), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission: Mapped["PPAPSubmission"] = relationship(back_populates="elements")
