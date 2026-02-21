"""Core entity models: Organization, Plant, User, Project."""
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.database import Base


class Organization(Base):
    """Organization - root entity for multi-tenancy."""
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plants: Mapped[list["Plant"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class Plant(Base):
    """Manufacturing plant/facility within an organization."""
    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(50))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="plants")
    projects: Mapped[list["Project"]] = relationship(back_populates="plant", cascade="all, delete-orphan")


class User(Base):
    """User account with authentication and authorization."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="viewer")  # admin, engineer, viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # MFA fields (Phase 7 - encryption of secret in Phase 8)
    mfa_secret: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_backup_codes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Password policy (Phase 7)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_history: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    data_clearance: Mapped[str] = mapped_column(String(20), default="internal")  # public, internal, confidential, strictly_confidential

    # Password reset fields
    password_reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    # Account lockout
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="users")
    uploaded_files: Mapped[list["CADFile"]] = relationship(
        back_populates="uploaded_by_user",
        foreign_keys="[CADFile.uploaded_by]"
    )
    workflow_roles: Mapped[list["UserWorkflowRole"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    """Project container for CAD files and articles."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"))
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")  # active, completed, archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plant: Mapped["Plant"] = relationship(back_populates="projects")
    files: Mapped[list["CADFile"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class CADFile(Base):
    """CAD file with versioning and 3D viewer support."""
    __tablename__ = "cad_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # File info
    filename: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int] = mapped_column(Integer)
    file_type: Mapped[str] = mapped_column(String(50))
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Metadata
    part_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    part_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[str] = mapped_column(String(20), default="A")

    # Versioning
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_file_id: Mapped[int | None] = mapped_column(ForeignKey("cad_files.id"), nullable=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True)
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status and hierarchy
    status: Mapped[str] = mapped_column(String(20), default="published")
    index_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    child_revision: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Encryption (Phase 7)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    encryption_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Data classification (Phase 6)
    data_classification: Mapped[str] = mapped_column(String(20), default="confidential")

    # Soft Delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # File Locking
    locked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Viewer (3D conversion)
    viewer_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    has_viewer: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="files")
    uploaded_by_user: Mapped["User | None"] = relationship(back_populates="uploaded_files", foreign_keys="[CADFile.uploaded_by]")
    revisions: Mapped[list["CADFile"]] = relationship(
        back_populates="parent_file",
        remote_side=[id],
        foreign_keys=[parent_file_id]
    )
    parent_file: Mapped["CADFile | None"] = relationship(
        back_populates="revisions",
        remote_side=[parent_file_id],
        foreign_keys=[parent_file_id]
    )


class UserWorkflowRole(Base):
    """Junction table for multi-assignment of workflow roles to users."""
    __tablename__ = "user_workflow_roles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    workflow_role: Mapped[str] = mapped_column(String(50), primary_key=True)
    # Values: tool_engineer, apqp, mfg_engineer, project_manager, sales, quality

    user: Mapped["User"] = relationship(back_populates="workflow_roles")


class AuditLog(Base):
    """Tamper-proof audit log with hash chaining."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    old_values: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    new_values: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Hash chaining (Phase 6)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    log_level: Mapped[str] = mapped_column(String(10), default="info")
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])


class LoginHistory(Base):
    """Authentication event tracking for security audit."""
    __tablename__ = "login_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(20))  # login_success, login_failed, logout, mfa_*
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])
