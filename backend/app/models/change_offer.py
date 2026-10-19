"""The customer offer: versioned, sent, valid for 30 days from receipt.

One row per version. A version is a draft while Sales builds it and frozen
once sent — what the customer holds must stay readable exactly as it was
sent, so the next round is a NEW version with a "what changed" note rather
than an edit of the old one. The business content lives in `data` (JSON) on
purpose: the offer's shape (factors, risk surcharges, free fields) is what
Sales iterates on, and a column per knob would mean a migration per idea.
total_one_time and piece_price_delta are denormalised from it so lists and
the P&L never have to recompute an offer to show its number.
"""
from datetime import date, datetime

from sqlalchemy import (
    Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

OFFER_STATUSES = ("draft", "sent", "superseded", "accepted", "declined")
OFFER_KINDS = ("offer", "supplement")
# How long an offer holds, counted from the day the customer received it.
OFFER_VALIDITY_DAYS = 30


class ChangeOffer(Base):
    __tablename__ = "change_offers"
    __table_args__ = (
        UniqueConstraint("change_id", "version", name="uq_change_offer_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("change_requests.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(15), default="draft", server_default="draft")
    # ECR-solid §6 (migration 134): 'offer' (the quote) or 'supplement'
    # (after approval: the changed positions only; the status stays).
    kind: Mapped[str] = mapped_column(
        String(12), default="offer", server_default="offer")
    currency: Mapped[str] = mapped_column(
        String(3), default="EUR", server_default="EUR")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    total_one_time: Mapped[float | None] = mapped_column(
        Numeric(14, 2, asdecimal=False), nullable=True)
    piece_price_delta: Mapped[float | None] = mapped_column(
        Numeric(12, 4, asdecimal=False), nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    received_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ECR-solid §7 (migration 133): what the customer's yes rests on (C12):
    # {kind: file|mail|po, ref, attachment_id, po_match: yes|no, differs,
    # total, indexes}; and who recorded the answer on this version.
    accept_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answered_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
