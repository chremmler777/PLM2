"""Database models for PLM application."""
from app.models.database import Base, get_db, init_db, AsyncSessionLocal, engine
from app.models.entities import (
    Organization, Plant, User, Project, CADFile,
    UserWorkflowRole, AuditLog, LoginHistory
)
from app.models.article import (
    Article, ArticleRevision, ArticleDocument, BOM, BOMItem, CatalogPart
)
from app.models.part import (
    Part, PartRevision, RevisionFile, RevisionChangelog,
    RevisionPhase, RevisionStatus, TestDataStatus
)
from app.models.workflow import (
    Department, WfTemplate, WfStage, WfStep, WfStepRasic, WfTemplateHistory,
    WfInstance, WfInstanceTask,
    WorkflowTemplate, WorkflowStep, WorkflowInstance, WorkflowTask
)

__all__ = [
    "Base",
    "get_db",
    "init_db",
    "AsyncSessionLocal",
    "engine",
    "Organization",
    "Plant",
    "User",
    "Project",
    "CADFile",
    "UserWorkflowRole",
    "AuditLog",
    "LoginHistory",
    "Article",
    "ArticleRevision",
    "ArticleDocument",
    "BOM",
    "BOMItem",
    "CatalogPart",
    "Part",
    "PartRevision",
    "RevisionFile",
    "RevisionChangelog",
    "RevisionPhase",
    "RevisionStatus",
    "TestDataStatus",
    # New workflow template models
    "Department",
    "WfTemplate",
    "WfStage",
    "WfStep",
    "WfStepRasic",
    "WfTemplateHistory",
    # New workflow instance models (Phase 3c)
    "WfInstance",
    "WfInstanceTask",
    # Legacy workflow models
    "WorkflowTemplate",
    "WorkflowStep",
    "WorkflowInstance",
    "WorkflowTask",
]
