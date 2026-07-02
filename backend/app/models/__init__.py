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
    RevisionPhase, RevisionStatus, TestDataStatus, PartBOMItem, PartRelation
)
from app.models.notification import Notification
from app.models.lesson import LessonLearned, LessonAction, LessonComment, LessonReference, LessonFile
from app.models.quality import PPAPSubmission, PPAPElement
from app.models.supplier import Supplier
from app.models.timing import ProjectMilestone
from app.models.sep import SepGate, SepWorkItem, SepItemAudit, SepRisk
from app.models.change import (
    ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeAttachment, ChangeChangelog,
    ChangeTransitionDeviation, change_affected_plants,
)
from app.models.change_cost import (
    DepartmentRate, AssessmentActivity, AssessmentCostLine, ChangeGate,
)
from app.models.workflow import (
    Department, UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic, WfTemplateHistory,
    WfInstance, WfInstanceTask, CheckWorkflowStandard,
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
    "CheckWorkflowStandard",
    # New workflow instance models (Phase 3c)
    "WfInstance",
    "WfInstanceTask",
    # Legacy workflow models
    "WorkflowTemplate",
    "WorkflowStep",
    "WorkflowInstance",
    "WorkflowTask",
    "ChangeRequest",
    "ChangeImpactedItem",
    "ChangeAssessment",
    "ChangeAttachment",
    "ChangeChangelog",
    "ChangeTransitionDeviation",
    "change_affected_plants",
    "DepartmentRate",
    "AssessmentActivity",
    "AssessmentCostLine",
    "ChangeGate",
]
