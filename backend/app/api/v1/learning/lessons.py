"""Lessons learned endpoints - capture, lifecycle, actions, comments, stats."""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import Project
from app.models.lesson import (
    LessonLearned, LessonAction, LessonComment, LessonReference,
    LESSON_CATEGORIES, LESSON_TYPES, LESSON_SEVERITIES, LESSON_TRANSITIONS,
)
from app.models.workflow import Department
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lessons", tags=["lessons"])


class LessonCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=3)
    project_id: Optional[int] = None
    project_ref: Optional[str] = Field(None, max_length=200)
    category: str = "other"
    lesson_type: str = "problem"
    severity: str = "medium"
    root_cause: Optional[str] = None
    recommendation: Optional[str] = None
    tags: Optional[str] = Field(None, max_length=300)
    owner_id: Optional[int] = None
    department_id: Optional[int] = None


class LessonUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = Field(None, min_length=3)
    project_id: Optional[int] = None
    clear_project: bool = False
    project_ref: Optional[str] = Field(None, max_length=200)
    category: Optional[str] = None
    lesson_type: Optional[str] = None
    severity: Optional[str] = None
    root_cause: Optional[str] = None
    recommendation: Optional[str] = None
    tags: Optional[str] = Field(None, max_length=300)
    owner_id: Optional[int] = None
    department_id: Optional[int] = None


class TransitionRequest(BaseModel):
    status: str
    effectiveness_verified: Optional[bool] = None
    effectiveness_note: Optional[str] = None


class ReferenceCreate(BaseModel):
    project_id: int
    milestone_id: Optional[int] = None
    note: Optional[str] = None


class ActionCreate(BaseModel):
    description: str = Field(..., min_length=3)
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None


class ActionUpdate(BaseModel):
    description: Optional[str] = Field(None, min_length=3)
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = Field(None, description="open or done")


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1)


def _validate_enums(category: Optional[str], lesson_type: Optional[str], severity: Optional[str]) -> None:
    if category is not None and category not in LESSON_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {LESSON_CATEGORIES}")
    if lesson_type is not None and lesson_type not in LESSON_TYPES:
        raise HTTPException(status_code=400, detail=f"lesson_type must be one of {LESSON_TYPES}")
    if severity is not None and severity not in LESSON_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {LESSON_SEVERITIES}")


async def _check_project(db: AsyncSession, project_id: int) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_lesson(db: AsyncSession, lesson_id: int) -> LessonLearned:
    lesson = (await db.execute(
        select(LessonLearned).where(LessonLearned.id == lesson_id)
    )).scalar_one_or_none()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson


def _lesson_dict(l: LessonLearned, project_name: str | None = None,
                 open_actions: int = 0, total_actions: int = 0) -> dict:
    return {
        "id": l.id,
        "title": l.title,
        "project_id": l.project_id,
        "project_name": project_name,
        "project_ref": l.project_ref,
        "category": l.category,
        "lesson_type": l.lesson_type,
        "severity": l.severity,
        "description": l.description,
        "root_cause": l.root_cause,
        "recommendation": l.recommendation,
        "tags": l.tags,
        "status": l.status,
        "owner_id": l.owner_id,
        "department_id": l.department_id,
        "created_by": l.created_by,
        "created_at": l.created_at.isoformat() if l.created_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
        "submitted_at": l.submitted_at.isoformat() if l.submitted_at else None,
        "approved_at": l.approved_at.isoformat() if l.approved_at else None,
        "closed_at": l.closed_at.isoformat() if l.closed_at else None,
        "effectiveness_note": l.effectiveness_note,
        "effectiveness_verified_at": l.effectiveness_verified_at.isoformat() if l.effectiveness_verified_at else None,
        "open_actions": open_actions,
        "total_actions": total_actions,
        "allowed_transitions": list(LESSON_TRANSITIONS.get(l.status, ())),
    }


def _action_dict(a: LessonAction, assignee_name: str | None = None) -> dict:
    now = datetime.utcnow()
    return {
        "id": a.id,
        "lesson_id": a.lesson_id,
        "description": a.description,
        "assignee_id": a.assignee_id,
        "assignee_name": assignee_name,
        "due_date": a.due_date.isoformat() if a.due_date else None,
        "status": a.status,
        "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        "overdue": a.status == "open" and a.due_date is not None and a.due_date < now,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


async def _user_names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    result = await db.execute(select(User.id, User.full_name, User.username).where(User.id.in_(user_ids)))
    return {uid: (full_name or username) for uid, full_name, username in result.all()}


@router.get("", response_model=List[dict])
async def list_lessons(
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    lesson_type: Optional[str] = None,
    severity: Optional[str] = None,
    project_id: Optional[int] = None,
    unlinked: bool = False,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(LessonLearned)
    if status_filter:
        stmt = stmt.where(LessonLearned.status == status_filter)
    if category:
        stmt = stmt.where(LessonLearned.category == category)
    if lesson_type:
        stmt = stmt.where(LessonLearned.lesson_type == lesson_type)
    if severity:
        stmt = stmt.where(LessonLearned.severity == severity)
    if project_id is not None:
        stmt = stmt.where(LessonLearned.project_id == project_id)
    if unlinked:
        stmt = stmt.where(LessonLearned.project_id.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            LessonLearned.title.ilike(like),
            LessonLearned.description.ilike(like),
            LessonLearned.tags.ilike(like),
            LessonLearned.project_ref.ilike(like),
        ))
    stmt = stmt.order_by(LessonLearned.created_at.desc(), LessonLearned.id.desc())
    lessons = (await db.execute(stmt)).scalars().all()

    # action counts per lesson
    counts: dict[int, tuple[int, int]] = {}
    if lessons:
        rows = (await db.execute(
            select(
                LessonAction.lesson_id,
                func.count(LessonAction.id),
                func.sum(case((LessonAction.status == "open", 1), else_=0)),
            ).where(LessonAction.lesson_id.in_([l.id for l in lessons]))
            .group_by(LessonAction.lesson_id)
        )).all()
        for lesson_id, total, open_cnt in rows:
            counts[lesson_id] = (int(open_cnt or 0), int(total or 0))

    # project names
    project_ids = {l.project_id for l in lessons if l.project_id}
    project_names: dict[int, str] = {}
    if project_ids:
        rows = (await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))).all()
        project_names = dict(rows)

    return [
        _lesson_dict(
            l,
            project_name=project_names.get(l.project_id) if l.project_id else None,
            open_actions=counts.get(l.id, (0, 0))[0],
            total_actions=counts.get(l.id, (0, 0))[1],
        )
        for l in lessons
    ]


@router.get("/stats", response_model=dict)
async def lesson_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    by_status_rows = (await db.execute(
        select(LessonLearned.status, func.count(LessonLearned.id)).group_by(LessonLearned.status)
    )).all()
    by_category_rows = (await db.execute(
        select(LessonLearned.category, func.count(LessonLearned.id)).group_by(LessonLearned.category)
    )).all()
    by_type_rows = (await db.execute(
        select(LessonLearned.lesson_type, func.count(LessonLearned.id)).group_by(LessonLearned.lesson_type)
    )).all()
    total = (await db.execute(select(func.count(LessonLearned.id)))).scalar() or 0
    unlinked = (await db.execute(
        select(func.count(LessonLearned.id)).where(LessonLearned.project_id.is_(None))
    )).scalar() or 0
    open_actions = (await db.execute(
        select(func.count(LessonAction.id)).where(LessonAction.status == "open")
    )).scalar() or 0
    overdue_actions = (await db.execute(
        select(func.count(LessonAction.id)).where(
            LessonAction.status == "open",
            LessonAction.due_date.is_not(None),
            LessonAction.due_date < datetime.utcnow(),
        )
    )).scalar() or 0

    return {
        "total": total,
        "unlinked": unlinked,
        "open_actions": open_actions,
        "overdue_actions": overdue_actions,
        "by_status": {s: c for s, c in by_status_rows},
        "by_category": {s: c for s, c in by_category_rows},
        "by_type": {s: c for s, c in by_type_rows},
    }


@router.get("/assignable-users", response_model=List[dict])
async def assignable_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Active users for owner/assignee pickers (not admin-gated, unlike /users)."""
    result = await db.execute(
        select(User.id, User.full_name, User.username)
        .where(User.is_active.is_(True))
        .order_by(User.full_name, User.username)
    )
    return [{"id": uid, "name": full_name or username} for uid, full_name, username in result.all()]


@router.get("/my-actions", response_model=List[dict])
async def my_actions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Open lesson actions assigned to the current user, for the My Tasks page."""
    rows = (await db.execute(
        select(LessonAction, LessonLearned)
        .join(LessonLearned, LessonAction.lesson_id == LessonLearned.id)
        .where(LessonAction.assignee_id == current_user.id, LessonAction.status == "open")
        .order_by(LessonAction.due_date.is_(None), LessonAction.due_date, LessonAction.id)
    )).all()
    return [
        {
            **_action_dict(a),
            "lesson_id": l.id,
            "lesson_title": l.title,
            "lesson_status": l.status,
            "lesson_severity": l.severity,
        }
        for a, l in rows
    ]


@router.get("/kpis", response_model=dict)
async def lesson_kpis(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Governance KPIs: review cycle time, implementation, overdue accountability, reuse."""
    now = datetime.utcnow()
    lessons = (await db.execute(select(LessonLearned))).scalars().all()
    actions = (await db.execute(select(LessonAction))).scalars().all()
    references = (await db.execute(select(LessonReference))).scalars().all()

    # Review cycle time: submitted -> approved
    review_durations = [
        (l.approved_at - l.submitted_at).total_seconds() / 86400
        for l in lessons
        if l.approved_at and l.submitted_at and l.approved_at >= l.submitted_at
    ]
    avg_time_to_review_days = round(sum(review_durations) / len(review_durations), 1) if review_durations else None

    # Implementation rate: of lessons that were approved, how many got implemented/closed
    reached_approval = [l for l in lessons if l.status in ("approved", "implemented", "closed")]
    implemented = [l for l in reached_approval if l.status in ("implemented", "closed")]
    implementation_rate = round(len(implemented) / len(reached_approval), 2) if reached_approval else None

    done_actions = [a for a in actions if a.status == "done"]
    action_completion_rate = round(len(done_actions) / len(actions), 2) if actions else None

    overdue = [a for a in actions if a.status == "open" and a.due_date and a.due_date < now]

    # Overdue by assignee
    names = await _user_names(db, {a.assignee_id for a in overdue if a.assignee_id})
    by_assignee: dict[int | None, int] = {}
    for a in overdue:
        by_assignee[a.assignee_id] = by_assignee.get(a.assignee_id, 0) + 1
    overdue_by_assignee = sorted(
        (
            {"assignee_id": uid, "name": names.get(uid, "Unassigned") if uid else "Unassigned", "count": c}
            for uid, c in by_assignee.items()
        ),
        key=lambda x: -x["count"],
    )

    # Overdue by department (via the action's lesson)
    lesson_by_id = {l.id: l for l in lessons}
    dept_counts: dict[int | None, int] = {}
    for a in overdue:
        dept_id = lesson_by_id[a.lesson_id].department_id if a.lesson_id in lesson_by_id else None
        dept_counts[dept_id] = dept_counts.get(dept_id, 0) + 1
    dept_ids = {d for d in dept_counts if d is not None}
    dept_names: dict[int, str] = {}
    if dept_ids:
        rows = (await db.execute(select(Department.id, Department.name).where(Department.id.in_(dept_ids)))).all()
        dept_names = dict(rows)
    overdue_by_department = sorted(
        (
            {"department_id": did, "name": dept_names.get(did, "No department") if did else "No department", "count": c}
            for did, c in dept_counts.items()
        ),
        key=lambda x: -x["count"],
    )

    # Distribution
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_month: dict[str, int] = {}
    for l in lessons:
        by_category[l.category] = by_category.get(l.category, 0) + 1
        by_severity[l.severity] = by_severity.get(l.severity, 0) + 1
        by_status[l.status] = by_status.get(l.status, 0) + 1
        if l.created_at:
            month = l.created_at.strftime("%Y-%m")
            by_month[month] = by_month.get(month, 0) + 1

    # Reuse: distinct lessons referenced on projects / non-draft lessons
    referenced_lessons = {r.lesson_id for r in references}
    non_draft = [l for l in lessons if l.status != "draft"]
    reuse_rate = round(len(referenced_lessons) / len(non_draft), 2) if non_draft else None

    return {
        "total_lessons": len(lessons),
        "avg_time_to_review_days": avg_time_to_review_days,
        "implementation_rate": implementation_rate,
        "action_completion_rate": action_completion_rate,
        "open_actions": sum(1 for a in actions if a.status == "open"),
        "overdue_actions": len(overdue),
        "overdue_by_assignee": overdue_by_assignee,
        "overdue_by_department": overdue_by_department,
        "by_category": by_category,
        "by_severity": by_severity,
        "by_status": by_status,
        "by_month": dict(sorted(by_month.items())),
        "references_total": len(references),
        "reuse_rate": reuse_rate,
        "unlinked": sum(1 for l in lessons if l.project_id is None),
        "in_review_queue": sum(1 for l in lessons if l.status in ("submitted", "in_review")),
    }


@router.get("/projects/{project_id}/references", response_model=List[dict])
async def project_references(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lessons that were reviewed/applied for this project (reuse record)."""
    rows = (await db.execute(
        select(LessonReference, LessonLearned)
        .join(LessonLearned, LessonReference.lesson_id == LessonLearned.id)
        .where(LessonReference.project_id == project_id)
        .order_by(LessonReference.id.desc())
    )).all()
    names = await _user_names(db, {r.created_by for r, _ in rows})
    return [
        {
            "id": r.id,
            "lesson_id": l.id,
            "lesson_title": l.title,
            "lesson_status": l.status,
            "lesson_category": l.category,
            "note": r.note,
            "created_by_name": names.get(r.created_by),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r, l in rows
    ]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    body: LessonCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_enums(body.category, body.lesson_type, body.severity)
    project_name = None
    if body.project_id is not None:
        project = await _check_project(db, body.project_id)
        project_name = project.name

    lesson = LessonLearned(
        title=body.title.strip(),
        description=body.description.strip(),
        project_id=body.project_id,
        project_ref=(body.project_ref or "").strip() or None,
        category=body.category,
        lesson_type=body.lesson_type,
        severity=body.severity,
        root_cause=body.root_cause,
        recommendation=body.recommendation,
        tags=body.tags,
        owner_id=body.owner_id,
        department_id=body.department_id,
        created_by=current_user.id,
    )
    db.add(lesson)
    await db.flush()

    if lesson.owner_id and lesson.owner_id != current_user.id:
        await NotificationService.notify_users(
            db, [lesson.owner_id],
            title=f"You own a new lesson: {lesson.title}",
            link="/lessons",
        )
    await db.commit()
    return _lesson_dict(lesson, project_name=project_name)


@router.get("/{lesson_id}", response_model=dict)
async def get_lesson(
    lesson_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_lesson(db, lesson_id)

    actions = (await db.execute(
        select(LessonAction).where(LessonAction.lesson_id == lesson_id).order_by(LessonAction.id)
    )).scalars().all()
    comments = (await db.execute(
        select(LessonComment).where(LessonComment.lesson_id == lesson_id).order_by(LessonComment.id)
    )).scalars().all()

    user_ids = {a.assignee_id for a in actions if a.assignee_id}
    user_ids |= {c.user_id for c in comments}
    if lesson.owner_id:
        user_ids.add(lesson.owner_id)
    user_ids.add(lesson.created_by)
    names = await _user_names(db, user_ids)

    project_name = None
    if lesson.project_id:
        project = (await db.execute(select(Project).where(Project.id == lesson.project_id))).scalar_one_or_none()
        project_name = project.name if project else None

    data = _lesson_dict(
        lesson, project_name=project_name,
        open_actions=sum(1 for a in actions if a.status == "open"),
        total_actions=len(actions),
    )
    data["owner_name"] = names.get(lesson.owner_id) if lesson.owner_id else None
    data["created_by_name"] = names.get(lesson.created_by)
    data["actions"] = [_action_dict(a, names.get(a.assignee_id) if a.assignee_id else None) for a in actions]
    data["comments"] = [
        {
            "id": c.id,
            "user_id": c.user_id,
            "user_name": names.get(c.user_id),
            "body": c.body,
            "is_system": c.is_system,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in comments
    ]
    return data


@router.patch("/{lesson_id}", response_model=dict)
async def update_lesson(
    lesson_id: int,
    body: LessonUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_lesson(db, lesson_id)
    if lesson.status == "closed":
        raise HTTPException(status_code=409, detail="Closed lessons are read-only")

    _validate_enums(body.category, body.lesson_type, body.severity)

    project_name = None
    if body.clear_project:
        lesson.project_id = None
    elif body.project_id is not None:
        project = await _check_project(db, body.project_id)
        lesson.project_id = body.project_id
        project_name = project.name

    previous_owner = lesson.owner_id
    for field in ("title", "description", "project_ref", "category", "lesson_type",
                  "severity", "root_cause", "recommendation", "tags", "owner_id", "department_id"):
        value = getattr(body, field)
        if value is not None:
            setattr(lesson, field, value.strip() if isinstance(value, str) else value)

    if lesson.owner_id and lesson.owner_id != previous_owner and lesson.owner_id != current_user.id:
        await NotificationService.notify_users(
            db, [lesson.owner_id],
            title=f"You are now the owner of lesson: {lesson.title}",
            link="/lessons",
        )

    await db.commit()
    return _lesson_dict(lesson, project_name=project_name)


@router.post("/{lesson_id}/transition", response_model=dict)
async def transition_lesson(
    lesson_id: int,
    body: TransitionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_lesson(db, lesson_id)

    allowed = LESSON_TRANSITIONS.get(lesson.status, ())
    if body.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {lesson.status} to {body.status}; allowed: {list(allowed)}",
        )

    if body.status == "approved" and not lesson.owner_id:
        raise HTTPException(
            status_code=409,
            detail="Assign an owner before approving — someone must be accountable for implementation",
        )

    if body.status == "closed":
        open_count = (await db.execute(
            select(func.count(LessonAction.id)).where(
                LessonAction.lesson_id == lesson_id, LessonAction.status == "open"
            )
        )).scalar() or 0
        if open_count:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot close: {open_count} action(s) still open",
            )
        if body.effectiveness_verified is not True:
            raise HTTPException(
                status_code=409,
                detail="Effectiveness verification required to close: confirm the recommendation worked (effectiveness_verified=true)",
            )

    old_status = lesson.status
    lesson.status = body.status
    if body.status == "submitted":
        lesson.submitted_at = datetime.utcnow()
    if body.status == "approved":
        lesson.approved_at = datetime.utcnow()
    if body.status == "closed":
        lesson.closed_at = datetime.utcnow()
        lesson.effectiveness_note = body.effectiveness_note
        lesson.effectiveness_verified_by = current_user.id
        lesson.effectiveness_verified_at = datetime.utcnow()

    actor = current_user.full_name or current_user.username
    db.add(LessonComment(
        lesson_id=lesson.id, user_id=current_user.id, is_system=True,
        body=f"Status changed {old_status} → {body.status} by {actor}",
    ))

    # Notifications
    if body.status == "submitted" and lesson.department_id:
        await NotificationService.notify_departments(
            db, [lesson.department_id],
            title=f"Lesson submitted for review: {lesson.title}",
            link="/lessons",
        )
    if body.status in ("approved", "rejected"):
        recipients = {lesson.created_by}
        if lesson.owner_id:
            recipients.add(lesson.owner_id)
        recipients.discard(current_user.id)
        await NotificationService.notify_users(
            db, list(recipients),
            title=f"Lesson {body.status}: {lesson.title}",
            link="/lessons",
        )

    await db.commit()
    return _lesson_dict(lesson)


@router.post("/{lesson_id}/actions", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_action(
    lesson_id: int,
    body: ActionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_lesson(db, lesson_id)
    if lesson.status == "closed":
        raise HTTPException(status_code=409, detail="Closed lessons are read-only")

    action = LessonAction(
        lesson_id=lesson_id,
        description=body.description.strip(),
        assignee_id=body.assignee_id,
        due_date=body.due_date,
        created_by=current_user.id,
    )
    db.add(action)
    await db.flush()

    if action.assignee_id and action.assignee_id != current_user.id:
        await NotificationService.notify_users(
            db, [action.assignee_id],
            title=f"Action assigned to you on lesson: {lesson.title}",
            body=action.description,
            link="/lessons",
        )
    await db.commit()
    return _action_dict(action)


@router.patch("/actions/{action_id}", response_model=dict)
async def update_action(
    action_id: int,
    body: ActionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    action = (await db.execute(
        select(LessonAction).where(LessonAction.id == action_id)
    )).scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if body.status is not None:
        if body.status not in ("open", "done"):
            raise HTTPException(status_code=400, detail="status must be open or done")
        action.status = body.status
        action.completed_at = datetime.utcnow() if body.status == "done" else None
    if body.description is not None:
        action.description = body.description.strip()
    if body.due_date is not None:
        action.due_date = body.due_date
    if body.assignee_id is not None and body.assignee_id != action.assignee_id:
        action.assignee_id = body.assignee_id
        if body.assignee_id != current_user.id:
            lesson = await _get_lesson(db, action.lesson_id)
            await NotificationService.notify_users(
                db, [body.assignee_id],
                title=f"Action assigned to you on lesson: {lesson.title}",
                body=action.description,
                link="/lessons",
            )

    await db.commit()
    return _action_dict(action)


@router.delete("/actions/{action_id}")
async def delete_action(
    action_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    action = (await db.execute(
        select(LessonAction).where(LessonAction.id == action_id)
    )).scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    await db.delete(action)
    await db.commit()
    return {"status": "success"}


@router.post("/{lesson_id}/references", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_reference(
    lesson_id: int,
    body: ReferenceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a lesson as reviewed/applied for a project (counts toward reuse rate)."""
    lesson = await _get_lesson(db, lesson_id)
    await _check_project(db, body.project_id)

    existing = (await db.execute(
        select(LessonReference).where(
            LessonReference.lesson_id == lesson_id,
            LessonReference.project_id == body.project_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Lesson already referenced for this project")

    ref = LessonReference(
        lesson_id=lesson_id,
        project_id=body.project_id,
        milestone_id=body.milestone_id,
        note=body.note,
        created_by=current_user.id,
    )
    db.add(ref)
    await db.commit()
    return {"id": ref.id, "lesson_id": lesson_id, "project_id": body.project_id, "note": ref.note}


@router.post("/{lesson_id}/comments", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_comment(
    lesson_id: int,
    body: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_lesson(db, lesson_id)
    comment = LessonComment(lesson_id=lesson_id, user_id=current_user.id, body=body.body.strip())
    db.add(comment)
    await db.commit()
    return {
        "id": comment.id,
        "user_id": comment.user_id,
        "user_name": current_user.full_name or current_user.username,
        "body": comment.body,
        "is_system": False,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }
