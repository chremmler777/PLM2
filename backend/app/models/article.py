"""Article and revision models - core PLM entities."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base


class Article(Base):
    """Product article with revision hierarchy."""
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))

    # Identity
    article_number: Mapped[str] = mapped_column(String(100), index=True)  # org-scoped unique
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    article_type: Mapped[str] = mapped_column(String(50))  # injection_tool, assembly_equipment, purchased_part
    sourcing_type: Mapped[str] = mapped_column(String(20), default="internal")  # internal, external

    # Data classification (Phase 6)
    data_classification: Mapped[str] = mapped_column(String(20), default="confidential")

    # Current active revision (denormalized for quick access)
    active_revision_id: Mapped[int | None] = mapped_column(ForeignKey("article_revisions.id"), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Relationships
    organization: Mapped["Organization"] = relationship(foreign_keys=[organization_id])
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by])
    revisions: Mapped[list["ArticleRevision"]] = relationship(
        back_populates="article",
        cascade="all, delete-orphan",
        foreign_keys="[ArticleRevision.article_id]",
        lazy="selectin"
    )
    boms: Mapped[list["BOM"]] = relationship(back_populates="article", cascade="all, delete-orphan")


class ArticleRevision(Base):
    """Revision of an article with lifecycle states."""
    __tablename__ = "article_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"))

    # Revision Identity
    revision: Mapped[str] = mapped_column(String(20))  # !1, !2, 1, 1.1, etc.
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Status Lifecycle
    status: Mapped[str] = mapped_column(String(30))
    # Values: draft, rfq, in_review, approved, in_implementation, released, rejected, canceled, superseded

    # RFQ Tracking
    rfq_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)

    # Parent for version tree (enables revert)
    parent_revision_id: Mapped[int | None] = mapped_column(ForeignKey("article_revisions.id"), nullable=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("article_revisions.id"), nullable=True)

    # Revision Lifecycle Type
    revision_type: Mapped[str] = mapped_column(String(20), default="engineering")
    # Values: 'engineering' (!1, !2), 'released' (1, 2), 'change' (1.1, 1.2)

    # For child revisions: link to parent index
    parent_index_id: Mapped[int | None] = mapped_column(ForeignKey("article_revisions.id"), nullable=True)

    # Metadata
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Relationships
    article: Mapped["Article"] = relationship(back_populates="revisions", foreign_keys=[article_id])
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by])
    released_by_user: Mapped["User | None"] = relationship(foreign_keys=[released_by])
    documents: Mapped[list["ArticleDocument"]] = relationship(back_populates="revision", cascade="all, delete-orphan")
    workflow_instances: Mapped[list["WorkflowInstance"]] = relationship(
        back_populates="article_revision",
        foreign_keys="[WorkflowInstance.article_revision_id]"
    )
    wf_instances: Mapped[list["WfInstance"]] = relationship(
        back_populates="revision",
        foreign_keys="[WfInstance.revision_id]"
    )


class ArticleDocument(Base):
    """Document attached to a revision (CAD file, drawing, specification, etc.)."""
    __tablename__ = "article_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("article_revisions.id"))

    # Document Type
    document_type: Mapped[str] = mapped_column(String(50))
    # Values: cad_drawing, 2d_drawing, specification, datasheet, quote, other

    # Link to existing CADFile or standalone document
    cad_file_id: Mapped[int | None] = mapped_column(ForeignKey("cad_files.id"), nullable=True)

    # Or standalone document metadata
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Metadata
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Relationships
    revision: Mapped["ArticleRevision"] = relationship(back_populates="documents")
    cad_file: Mapped["CADFile | None"] = relationship(foreign_keys=[cad_file_id])
    uploaded_by_user: Mapped["User"] = relationship(foreign_keys=[uploaded_by])


class BOM(Base):
    """Bill of Materials - hierarchical component structure."""
    __tablename__ = "boms"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"))
    revision_id: Mapped[int | None] = mapped_column(ForeignKey("article_revisions.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft, released, obsolete
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    article: Mapped["Article"] = relationship(back_populates="boms")
    revision: Mapped["ArticleRevision | None"] = relationship(foreign_keys=[revision_id])
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by])
    items: Mapped[list["BOMItem"]] = relationship(back_populates="bom", cascade="all, delete-orphan")


class BOMItem(Base):
    """Item in a BOM - references another article or generic component."""
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    bom_id: Mapped[int] = mapped_column(ForeignKey("boms.id"))
    parent_item_id: Mapped[int | None] = mapped_column(ForeignKey("bom_items.id"), nullable=True)
    child_article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id"), nullable=True)

    item_number: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    bom: Mapped["BOM"] = relationship(back_populates="items")
    parent_item: Mapped["BOMItem | None"] = relationship(remote_side=[id])
    child_article: Mapped["Article | None"] = relationship(foreign_keys=[child_article_id])


# Import needed models for relationships
from app.models.entities import Organization, User, CADFile
