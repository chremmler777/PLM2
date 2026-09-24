"""Database models for PLM application."""
from app.models.database import Base, get_db, init_db, AsyncSessionLocal, engine
from app.models.entities import (
    Organization, Plant, User, Project, CADFile,
    UserWorkflowRole, AuditLog, LoginHistory
)
from app.models.catalog import CatalogPart
from app.models.paint import Paint, PartPaint, PartPaintLayer
from app.models.part import (
    Part, PartRevision, RevisionFile, RevisionChangelog,
    RevisionPhase, RevisionStatus, TestDataStatus, PartBOMItem, PartRelation
)
from app.models.notification import Notification
from app.models.lesson import LessonLearned, LessonAction, LessonComment, LessonReference, LessonFile
from app.models.quality import PPAPSubmission, PPAPElement
from app.models.supplier import Supplier
from app.models.timing import ProjectMilestone
from app.models.sep import SepGate, SepWorkItem, SepItemAudit, SepRisk, SepItemFile
from app.models.forms import FormDefinition, FormInstance, FormEvent
from app.models.change import (
    ChangeRequest, ChangeImpactedItem, ChangeAssessment, ChangeAttachment, ChangeChangelog,
    ChangeTransitionDeviation, change_affected_plants,
)
from app.models.change_cost import (
    DepartmentRate, AssessmentActivity, AssessmentCostLine, ChangeGate,
    CostingPosition, CostingOffer,
)
from app.models.change_impl import (
    ImplementationBooking, ImplementationReport, ImplementationEscalation,
)
from app.models.change_validation import ValidationCheck
from app.models.workflow import (
    Department, UserDepartment, WfTemplate, WfStage, WfStep, WfStepRasic, WfTemplateHistory,
    WfInstance, WfInstanceTask, CheckWorkflowStandard,
)
from app.models.dfm import DfmTopic, DfmEntry, DfmEntryFile, DfmAuditEvent
from app.models.field_note import FieldNote, FieldNoteComment

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
    "CatalogPart",
    "Paint",
    "PartPaint",
    "PartPaintLayer",
    "Part",
    "PartRevision",
    "RevisionFile",
    "RevisionChangelog",
    "RevisionPhase",
    "RevisionStatus",
    "TestDataStatus",
    "DfmTopic",
    "DfmEntry",
    "DfmEntryFile",
    "DfmAuditEvent",
    "FieldNote",
    "FieldNoteComment",
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
    "CostingPosition",
    "CostingOffer",
    "ImplementationBooking",
    "ImplementationReport",
    "ImplementationEscalation",
    "ValidationCheck",
    "FormDefinition",
    "FormInstance",
    "FormEvent",
]
