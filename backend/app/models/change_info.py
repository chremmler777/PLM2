"""Mother-plant changes (spec §14, migration 093): the team is informed.

One row per informed department. "Send information" creates them; a member
of the department acknowledges with "Read and understood", optionally with a
note back. Open receipts are information in Blocked by, never a gate.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


class ChangeInfoReceipt(Base):
    __tablename__ = "change_info_receipts"
    __table_args__ = (
        UniqueConstraint("change_id", "department_id",
                         name="uq_change_info_receipt"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("wf_departments.id"))
    sent_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    sent_by_user: Mapped["User"] = relationship(
        foreign_keys=[sent_by], lazy="selectin")
    acknowledged_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[acknowledged_by], lazy="selectin")

    @property
    def is_open(self) -> bool:
        return self.acknowledged_at is None

    @property
    def sent_by_name(self) -> Optional[str]:
        return self.sent_by_user.full_name if self.sent_by_user else None

    @property
    def acknowledged_by_name(self) -> Optional[str]:
        u = self.acknowledged_by_user
        return u.full_name if u is not None else None
