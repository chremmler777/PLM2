"""The scope change card (ECR-solid spec §6 [R3], migration 133).

From 'quoted' on the customer may add or change something. One card per
request, three steps with an owner each:

1. requested: Sales records what the customer wants (P/N, what, by when,
   the customer's mail or its reference). The lead decides.
2. re-costed: the lead accepts (the departments to re-cost, preticked from
   the routing) or refuses (Sales tells the customer). After approval an
   added part may become its own linked change instead. Each department
   marks its re-costing done; the last one hands Sales "Revise offer".
3. accepted: the next offer (or supplement, after approval) sent while the
   card is ready carries it ('offered'); the customer's answer to it
   settles the card (accepted, or dropped on a decline). An offer sent
   while re-costing runs says "subject to final costing" and covers nothing.

kind: 'customer' (Sales' button), 'customer_index' (a recheck found an
effect at quoted or later, §1), 'po_differs' (the PO differs from the
offer at acceptance, §7). A card opened after approval (post_accept)
opens the price (HARD #9) instead of holding the approval.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

SCOPE_KINDS = ("customer", "customer_index", "po_differs")
SCOPE_STATUSES = ("requested", "recosting", "ready", "offered", "accepted",
                  "refused", "dropped", "moved", "absorbed")
#: Still open: holds scope_change_uncovered (SOFT).
SCOPE_OPEN = ("requested", "recosting", "ready", "offered")
#: Not yet in an offer sent after re-costing: the departments' work is open.
SCOPE_UNCOSTED = ("requested", "recosting", "ready")


class ChangeScopeChange(Base):
    __tablename__ = "change_scope_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="customer")
    status: Mapped[str] = mapped_column(String(12), default="requested")
    part_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    what: Mapped[str] = mapped_column(Text)
    expects_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # opened after approval: the price is open, approval not held
    post_accept: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # the departments that re-cost, and the ones done
    department_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    departments_done: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recost_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    offer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_change_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recheck_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # refused: Sales told the customer (reference)
    told_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    told_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    told_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
