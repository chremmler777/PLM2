"""Catalog parts — purchasable/standard parts referenced by Part BOMs.

Extracted from the retired legacy article module (Phase D); the
catalog_parts table is shared with the live Part stack.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


class CatalogPart(Base):
    """Global org-scoped parts catalog."""
    __tablename__ = "catalog_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    part_number: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    part_type: Mapped[str] = mapped_column(String(20))  # purchased | manufactured
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('organization_id', 'part_number', name='uq_catalog_part_org_number'),
    )

    organization: Mapped["Organization"] = relationship(foreign_keys=[organization_id])
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by])


# Forward references for type hints
from app.models.entities import Organization, User  # noqa: E402
