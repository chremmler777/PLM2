"""Part and revision models - core PLM entities with RFQ/ENG/FREEZE/ECR phases."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean, Float, JSON, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base
import enum


class RevisionPhase(str, enum.Enum):
    """Revision phase in the product lifecycle."""
    RFQ_PHASE = "rfq_phase"           # RFQ1, RFQ2, etc
    ENGINEERING_PHASE = "engineering"  # ENG1, ENG1.1, ENG2, etc
    DESIGN_FREEZE_PHASE = "freeze"    # IND1, IND2, etc
    ECN_PHASE = "ecn"                 # ECR1.1, ECR2.1, etc


class RevisionStatus(str, enum.Enum):
    """Status of a revision within its phase."""
    DRAFT = "draft"                    # Initial creation
    IN_PROGRESS = "in_progress"        # Work in progress
    IN_REVIEW = "in_review"            # Awaiting approval
    APPROVED = "approved"              # Approved and confirmed
    REJECTED = "rejected"              # Proposal explicitly rejected by user
    ARCHIVED = "archived"              # Proposal superseded by new major version
    FROZEN = "frozen"                  # Design freeze locked
    CANCELLED = "cancelled"            # Obsolete or cancelled


class TestDataStatus(str, enum.Enum):
    """Status of a test/proposal revision."""
    UNCONFIRMED = "unconfirmed"        # Proposal created but not yet confirmed
    APPROVED = "approved"              # Proposal approved and becomes official
    REJECTED = "rejected"              # Proposal rejected


class Part(Base):
    """Engineering part with revision history (replaces Article)."""
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))

    # Identity
    part_number: Mapped[str] = mapped_column(String(100), index=True)  # org-scoped unique
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    part_type: Mapped[str] = mapped_column(String(50))  # purchased, internal_mfg, sub_assembly
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)  # For purchased parts

    # Data classification
    data_classification: Mapped[str] = mapped_column(String(20), default="confidential")

    # Hierarchy - for sub-assemblies containing other parts
    parent_part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id"), nullable=True)

    # Current active revision (denormalized for quick access)
    active_revision_id: Mapped[int | None] = mapped_column(ForeignKey("part_revisions.id"), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by])
    updated_by_user: Mapped["User | None"] = relationship(foreign_keys=[updated_by])

    parent_part: Mapped["Part | None"] = relationship(
        back_populates="child_parts",
        remote_side=[id],
        foreign_keys=[parent_part_id]
    )
    child_parts: Mapped[list["Part"]] = relationship(
        back_populates="parent_part",
        remote_side=[parent_part_id],
        foreign_keys=[parent_part_id],
        cascade="all, delete-orphan"
    )

    revisions: Mapped[list["PartRevision"]] = relationship(
        back_populates="part",
        cascade="all, delete-orphan",
        foreign_keys="[PartRevision.part_id]",
        lazy="selectin"
    )
    changelog: Mapped[list["RevisionChangelog"]] = relationship(
        back_populates="part",
        cascade="all, delete-orphan",
        foreign_keys="[RevisionChangelog.part_id]"
    )


class PartRevision(Base):
    """Revision of a part with RFQ/ENG/FREEZE/ECR lifecycle."""
    __tablename__ = "part_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))

    # Revision Identity - human-friendly names: RFQ1, ENG1, ENG1.1, IND1, ECR1.1, IND2, etc
    revision_name: Mapped[str] = mapped_column(String(20), index=True)  # RFQ1, ENG1, ENG1.1, IND1, ECR1.1, IND2

    # Phase tracking
    phase: Mapped[str] = mapped_column(Enum(RevisionPhase, values_callable=lambda x: [e.value for e in x], native_enum=False), index=True)
    status: Mapped[str] = mapped_column(Enum(RevisionStatus, values_callable=lambda x: [e.value for e in x], native_enum=False), default=RevisionStatus.DRAFT.value)

    # Test data status (for engineering iterations and ECN proposals)
    test_data_status: Mapped[str | None] = mapped_column(Enum(TestDataStatus, values_callable=lambda x: [e.value for e in x], native_enum=False), nullable=True)

    # Hierarchy - link to parent revision (for ENG1.1→ENG1, IND2→IND1, ECR1.1→IND1, etc)
    parent_revision_id: Mapped[int | None] = mapped_column(ForeignKey("part_revisions.id"), nullable=True)

    # For proposals: which revision does this replace when approved
    # e.g., ENG1.1 approved becomes ENG2 (supersedes ENG1)
    supersedes_revision_id: Mapped[int | None] = mapped_column(ForeignKey("part_revisions.id"), nullable=True)

    # Metadata
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # What changed
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # Why the change
    impact_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)  # Impact of changes

    # Design Freeze specific
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    frozen_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Cancellation tracking
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Approval tracking
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Relationships
    part: Mapped["Part"] = relationship(back_populates="revisions", foreign_keys=[part_id])
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by])
    updated_by_user: Mapped["User | None"] = relationship(foreign_keys=[updated_by])
    frozen_by_user: Mapped["User | None"] = relationship(foreign_keys=[frozen_by])
    cancelled_by_user: Mapped["User | None"] = relationship(foreign_keys=[cancelled_by])
    approved_by_user: Mapped["User | None"] = relationship(foreign_keys=[approved_by])

    parent_revision: Mapped["PartRevision | None"] = relationship(
        back_populates="children",
        remote_side=[id],
        foreign_keys=[parent_revision_id]
    )
    children: Mapped[list["PartRevision"]] = relationship(
        back_populates="parent_revision",
        remote_side=[parent_revision_id],
        foreign_keys=[parent_revision_id],
        cascade="all, delete-orphan"
    )

    files: Mapped[list["RevisionFile"]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan"
    )
    changelog_entries: Mapped[list["RevisionChangelog"]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        foreign_keys="[RevisionChangelog.revision_id]"
    )


class RevisionFile(Base):
    """File attached to a revision - CAD, pictures, drawings, documents."""
    __tablename__ = "revision_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("part_revisions.id"))

    # File identity
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(50))  # picture, cad, drawing, document, test_result
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(500))

    # CAD metadata (for CAD files only)
    cad_format: Mapped[str | None] = mapped_column(String(20), nullable=True)  # step, iges, stl, etc
    cad_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Metadata as JSON

    # File integrity
    file_hash: Mapped[str] = mapped_column(String(64))  # SHA-256

    # Encryption (Phase 7)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    encryption_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 3D Viewer support
    viewer_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # glTF conversion
    has_viewer: Mapped[bool] = mapped_column(Boolean, default=False)

    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Relationships
    revision: Mapped["PartRevision"] = relationship(back_populates="files", foreign_keys=[revision_id])
    uploaded_by_user: Mapped["User"] = relationship(foreign_keys=[uploaded_by])


class RevisionChangelog(Base):
    """Audit trail - complete changelog of all changes to a part/revision."""
    __tablename__ = "revision_changelogs"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"))
    revision_id: Mapped[int | None] = mapped_column(ForeignKey("part_revisions.id"), nullable=True)

    # Action description
    action: Mapped[str] = mapped_column(String(50))
    # Values: created, status_changed, approved, rejected, frozen, cancelled, file_uploaded, metadata_updated, parent_updated

    action_description: Mapped[str] = mapped_column(Text)  # Human-readable description

    # What changed
    field_name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Which field was changed
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON serialized

    # File reference (if file-related action)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("revision_files.id"), nullable=True)

    # Who did it
    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Context
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # Additional context/reason
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Hash chaining for tamper detection (Phase 6)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256 of previous entry
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256 of this entry

    # Relationships
    part: Mapped["Part"] = relationship(back_populates="changelog", foreign_keys=[part_id])
    revision: Mapped["PartRevision | None"] = relationship(back_populates="changelog_entries", foreign_keys=[revision_id])
    performed_by_user: Mapped["User"] = relationship(foreign_keys=[performed_by])


# Import needed models for relationships
from app.models.entities import Project, User
