"""Lessons learned endpoints - strict lifecycle, actions, evidence, comments, KPIs.

Lifecycle (server-enforced, no other edges):
in_review -accept-> in_work -owner sends-> verification -verified-> closed
    `-reject-> rejected           ^---- send back with feedback ----'
"""
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import Project
from app.models.lesson import (
    LessonLearned, LessonAction, LessonComment, LessonReference, LessonFile,
    LESSON_CATEGORIES, LESSON_TYPES, LESSON_SEVERITIES, LESSON_TRANSITIONS,
    REJECT_CATEGORIES, STALE_AFTER_DAYS,
)
from app.models.workflow import Department
from app.services.notification_service import NotificationService

# Which lesson fields may be edited in which state. Status itself is never
# patchable; transitions happen only via the /transition endpoint.
EDITABLE_FIELDS = {
    "in_review": {
        "title", "description", "category", "lesson_type", "severity",
        "root_cause", "recommendation", "tags", "owner_id", "department_id",
        "target_date", "project_id", "clear_project", "project_ref",
    },
    # Reviewed content is locked once accepted; analysis and planning stay open
    "in_work": {
        "root_cause", "recommendation", "tags", "owner_id", "target_date",
        "project_id", "clear_project", "project_ref",
    },
    "verification": {"project_id", "clear_project", "project_ref"},
    "closed": set(),
    "rejected": set(),
}

# States in which actions and evidence files may be modified
WORKABLE_STATES = ("in_review", "in_work")

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
    target_date: Optional[datetime] = None


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
    target_date: Optional[datetime] = None


class TransitionRequest(BaseModel):
    status: str
    # closing (verification -> closed)
    effectiveness_verified: Optional[bool] = None
    effectiveness_note: Optional[str] = None
    # rejecting (in_review -> rejected)
    reject_category: Optional[str] = None
    reject_reason: Optional[str] = None
    # sending back (verification -> in_work)
    feedback: Optional[str] = None


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


def _state_entered_at(l: LessonLearned) -> datetime | None:
    """When the lesson entered its current state."""
    if l.status == "in_review":
        return l.created_at
    if l.status == "in_work":
        return l.accepted_at or l.created_at
    if l.status == "verification":
        return l.verification_requested_at or l.created_at
    if l.status == "closed":
        return l.closed_at
    return l.updated_at  # rejected


def _lesson_dict(l: LessonLearned, project_name: str | None = None,
                 open_actions: int = 0, total_actions: int = 0) -> dict:
    now = datetime.utcnow()
    entered = _state_entered_at(l)
    days_in_state = round((now - entered).total_seconds() / 86400, 1) if entered else None

    stale = False
    if l.status in STALE_AFTER_DAYS and days_in_state is not None:
        stale = days_in_state > STALE_AFTER_DAYS[l.status]
    target_overdue = bool(
        l.status == "in_work" and l.target_date and l.target_date < now
    )

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
        "target_date": l.target_date.isoformat() if l.target_date else None,
        "target_overdue": target_overdue,
        "reject_category": l.reject_category,
        "reject_reason": l.reject_reason,
        "created_by": l.created_by,
        "created_at": l.created_at.isoformat() if l.created_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
        "accepted_at": l.accepted_at.isoformat() if l.accepted_at else None,
        "verification_requested_at": l.verification_requested_at.isoformat() if l.verification_requested_at else None,
        "closed_at": l.closed_at.isoformat() if l.closed_at else None,
        "effectiveness_note": l.effectiveness_note,
        "effectiveness_verified_at": l.effectiveness_verified_at.isoformat() if l.effectiveness_verified_at else None,
        "days_in_state": days_in_state,
        "stale": stale,
        "open_actions": open_actions,
        "total_actions": total_actions,
        "allowed_transitions": list(LESSON_TRANSITIONS.get(l.status, ())),
        "editable_fields": sorted(EDITABLE_FIELDS.get(l.status, set())),
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
    mine: bool = False,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(LessonLearned)
    if mine:
        stmt = stmt.where(LessonLearned.owner_id == current_user.id)
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

    # Time to review: capture (= submission) -> accepted into work
    review_durations = [
        (l.accepted_at - l.created_at).total_seconds() / 86400
        for l in lessons
        if l.accepted_at and l.created_at and l.accepted_at >= l.created_at
    ]
    avg_time_to_review_days = round(sum(review_durations) / len(review_durations), 1) if review_durations else None

    # Time to close: capture -> closed, plus on-time rate vs target date
    closed_lessons = [l for l in lessons if l.status == "closed" and l.closed_at]
    close_durations = [
        (l.closed_at - l.created_at).total_seconds() / 86400
        for l in closed_lessons if l.created_at and l.closed_at >= l.created_at
    ]
    avg_time_to_close_days = round(sum(close_durations) / len(close_durations), 1) if close_durations else None
    with_target = [l for l in closed_lessons if l.target_date]
    on_time = [l for l in with_target if l.closed_at <= l.target_date]
    on_time_close_rate = round(len(on_time) / len(with_target), 2) if with_target else None

    # Implementation rate: of accepted lessons, how many made it to closed
    accepted = [l for l in lessons if l.status in ("in_work", "verification", "closed")]
    implementation_rate = round(len(closed_lessons) / len(accepted), 2) if accepted else None

    # Severity x category heatmap and monthly capture-to-close cycle trend
    heatmap: dict[str, dict[str, int]] = {}
    for l in lessons:
        heatmap.setdefault(l.severity, {})
        heatmap[l.severity][l.category] = heatmap[l.severity].get(l.category, 0) + 1
    cycle_by_month: dict[str, list[float]] = {}
    for l in closed_lessons:
        if l.created_at and l.closed_at >= l.created_at:
            month = l.closed_at.strftime("%Y-%m")
            cycle_by_month.setdefault(month, []).append(
                (l.closed_at - l.created_at).total_seconds() / 86400
            )
    cycle_time_trend = {
        month: round(sum(vals) / len(vals), 1)
        for month, vals in sorted(cycle_by_month.items())
    }

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
        "avg_time_to_close_days": avg_time_to_close_days,
        "on_time_close_rate": on_time_close_rate,
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
        "heatmap": heatmap,
        "cycle_time_trend": cycle_time_trend,
        "by_reject_category": {
            cat: sum(1 for l in lessons if l.reject_category == cat)
            for cat in REJECT_CATEGORIES
            if any(l.reject_category == cat for l in lessons)
        },
        "references_total": len(references),
        "reuse_rate": reuse_rate,
        "unlinked": sum(1 for l in lessons if l.project_id is None),
        "in_review_queue": sum(1 for l in lessons if l.status == "in_review"),
        "stale_lessons": sum(1 for l in lessons if _lesson_dict(l)["stale"]),
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


@router.get("/check-duplicates", response_model=List[dict])
async def check_duplicates(
    title: str = Query(..., min_length=3),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Word-overlap duplicate guard for the capture form. Warns, never blocks."""
    words = {w for w in re.findall(r"[a-zà-ü0-9]{3,}", title.lower())}
    if not words:
        return []
    lessons = (await db.execute(
        select(LessonLearned.id, LessonLearned.title, LessonLearned.status)
    )).all()
    matches = []
    for lid, ltitle, lstatus in lessons:
        other = {w for w in re.findall(r"[a-zà-ü0-9]{3,}", ltitle.lower())}
        if not other:
            continue
        overlap = len(words & other) / min(len(words), len(other))
        if overlap >= 0.5:
            matches.append({"id": lid, "title": ltitle, "status": lstatus, "score": round(overlap, 2)})
    return sorted(matches, key=lambda m: -m["score"])[:5]


@router.get("/tags", response_model=List[dict])
async def list_tags(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Distinct tags with usage counts, for autocomplete."""
    rows = (await db.execute(
        select(LessonLearned.tags).where(LessonLearned.tags.is_not(None))
    )).scalars().all()
    counts: dict[str, int] = {}
    for raw in rows:
        for tag in raw.split(","):
            tag = tag.strip().lower()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda x: -x[1])]


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    f = (await db.execute(select(LessonFile).where(LessonFile.id == file_id))).scalar_one_or_none()
    if not f or not os.path.exists(f.stored_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(f.stored_path, filename=f.filename, media_type=f.content_type or "application/octet-stream")


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    f = (await db.execute(select(LessonFile).where(LessonFile.id == file_id))).scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    lesson = await _get_lesson(db, f.lesson_id)
    if lesson.status not in WORKABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Evidence can only be modified in {WORKABLE_STATES}, lesson is '{lesson.status}'",
        )
    try:
        if os.path.exists(f.stored_path):
            os.remove(f.stored_path)
    except OSError:
        logger.warning("Could not remove stored file %s", f.stored_path)
    await db.delete(f)
    await db.commit()
    return {"status": "success"}


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

    # Creation lands directly in the review queue — no draft/submit step
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
        target_date=body.target_date,
        status="in_review",
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
    if lesson.department_id:
        await NotificationService.notify_departments(
            db, [lesson.department_id],
            title=f"New lesson awaiting review: {lesson.title}",
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
    files = (await db.execute(
        select(LessonFile).where(LessonFile.lesson_id == lesson_id).order_by(LessonFile.id)
    )).scalars().all()
    data["files"] = [
        {
            "id": f.id,
            "filename": f.filename,
            "size_bytes": f.size_bytes,
            "content_type": f.content_type,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in files
    ]
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
    allowed_fields = EDITABLE_FIELDS.get(lesson.status, set())

    # Strict editability: reject any provided field not editable in this state
    provided = {k for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not body.clear_project:
        provided.discard("clear_project")
    illegal = provided - allowed_fields
    if illegal:
        raise HTTPException(
            status_code=409,
            detail=f"Field(s) {sorted(illegal)} are not editable in state '{lesson.status}'",
        )

    _validate_enums(body.category, body.lesson_type, body.severity)

    project_name = None
    if body.clear_project:
        lesson.project_id = None
    elif body.project_id is not None:
        project = await _check_project(db, body.project_id)
        lesson.project_id = body.project_id
        project_name = project.name

    previous_owner = lesson.owner_id
    previous_target = lesson.target_date
    for field in ("title", "description", "project_ref", "category", "lesson_type",
                  "severity", "root_cause", "recommendation", "tags", "owner_id",
                  "department_id", "target_date"):
        value = getattr(body, field)
        if value is not None:
            setattr(lesson, field, value.strip() if isinstance(value, str) else value)

    actor = current_user.full_name or current_user.username
    # Owner / target changes after acceptance are audited (and owner can never be cleared)
    if lesson.status == "in_work":
        if lesson.owner_id != previous_owner:
            db.add(LessonComment(
                lesson_id=lesson.id, user_id=current_user.id, is_system=True,
                body=f"Responsible changed by {actor}",
            ))
        if lesson.target_date != previous_target:
            db.add(LessonComment(
                lesson_id=lesson.id, user_id=current_user.id, is_system=True,
                body=f"Target date changed to {lesson.target_date:%Y-%m-%d} by {actor}",
            ))

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
    now = datetime.utcnow()
    actor = current_user.full_name or current_user.username

    allowed = LESSON_TRANSITIONS.get(lesson.status, ())
    if body.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {lesson.status} to {body.status}; allowed: {list(allowed)}",
        )

    async def _open_action_count() -> int:
        return (await db.execute(
            select(func.count(LessonAction.id)).where(
                LessonAction.lesson_id == lesson_id, LessonAction.status == "open"
            )
        )).scalar() or 0

    audit_suffix = ""

    # --- Accept: in_review -> in_work ---
    if body.status == "in_work" and lesson.status == "in_review":
        missing = []
        if not lesson.owner_id:
            missing.append("responsible owner")
        if not lesson.target_date:
            missing.append("target date")
        total_actions = (await db.execute(
            select(func.count(LessonAction.id)).where(LessonAction.lesson_id == lesson_id)
        )).scalar() or 0
        if total_actions == 0:
            missing.append("at least one action")
        if missing:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot accept: define {', '.join(missing)} first",
            )
        lesson.accepted_at = now

    # --- Reject: in_review -> rejected (terminal, categorized) ---
    if body.status == "rejected":
        if body.reject_category not in REJECT_CATEGORIES:
            raise HTTPException(
                status_code=409,
                detail=f"Rejection requires a category: {list(REJECT_CATEGORIES)}",
            )
        if not (body.reject_reason or "").strip():
            raise HTTPException(status_code=409, detail="Rejection requires a reason")
        lesson.reject_category = body.reject_category
        lesson.reject_reason = body.reject_reason.strip()
        audit_suffix = f" ({body.reject_category}: {lesson.reject_reason})"

    # --- Send to verification: in_work -> verification (owner sends, work done) ---
    if body.status == "verification":
        open_count = await _open_action_count()
        if open_count:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot send to verification: {open_count} action(s) still open",
            )
        if current_user.id != lesson.owner_id and current_user.role != "admin":
            raise HTTPException(
                status_code=409,
                detail="Only the responsible owner can send a lesson to verification",
            )
        lesson.verification_requested_at = now

    # --- Verification outcome ---
    if body.status == "closed":
        if body.effectiveness_verified is not True:
            raise HTTPException(
                status_code=409,
                detail="Effectiveness verification required to close: confirm the recommendation worked (effectiveness_verified=true)",
            )
        lesson.closed_at = now
        lesson.effectiveness_note = body.effectiveness_note
        lesson.effectiveness_verified_by = current_user.id
        lesson.effectiveness_verified_at = now

    if body.status == "in_work" and lesson.status == "verification":
        # Send back with mandatory feedback
        if not (body.feedback or "").strip():
            raise HTTPException(status_code=409, detail="Sending back requires feedback")
        lesson.verification_requested_at = None
        audit_suffix = f" (feedback: {body.feedback.strip()})"

    old_status = lesson.status
    lesson.status = body.status

    db.add(LessonComment(
        lesson_id=lesson.id, user_id=current_user.id, is_system=True,
        body=f"Status changed {old_status} → {body.status} by {actor}{audit_suffix}",
    ))

    # Notifications
    if body.status == "rejected":
        recipients = {lesson.created_by} - {current_user.id}
        await NotificationService.notify_users(
            db, list(recipients),
            title=f"Lesson rejected ({body.reject_category}): {lesson.title}",
            body=lesson.reject_reason,
            link="/lessons",
        )
    if body.status == "in_work":
        recipients = {lesson.created_by}
        if lesson.owner_id:
            recipients.add(lesson.owner_id)
        recipients.discard(current_user.id)
        title = (
            f"Lesson sent back to work: {lesson.title}"
            if old_status == "verification"
            else f"Lesson accepted into work: {lesson.title}"
        )
        await NotificationService.notify_users(
            db, list(recipients), title=title, body=body.feedback, link="/lessons",
        )
    if body.status == "verification" and lesson.department_id:
        await NotificationService.notify_departments(
            db, [lesson.department_id],
            title=f"Lesson awaiting verification: {lesson.title}",
            link="/lessons",
        )
    if body.status == "closed":
        recipients = {lesson.created_by}
        if lesson.owner_id:
            recipients.add(lesson.owner_id)
        recipients.discard(current_user.id)
        await NotificationService.notify_users(
            db, list(recipients),
            title=f"Lesson closed (effectiveness verified): {lesson.title}",
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
    if lesson.status not in WORKABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Actions can only be modified in {WORKABLE_STATES}, lesson is '{lesson.status}'",
        )

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
    lesson = await _get_lesson(db, action.lesson_id)
    if lesson.status not in WORKABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Actions can only be modified in {WORKABLE_STATES}, lesson is '{lesson.status}'",
        )

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
    lesson = await _get_lesson(db, action.lesson_id)
    if lesson.status not in WORKABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Actions can only be modified in {WORKABLE_STATES}, lesson is '{lesson.status}'",
        )
    await db.delete(action)
    await db.commit()
    return {"status": "success"}


@router.post("/{lesson_id}/files", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_file(
    lesson_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach evidence (photos, reports, 8D sheets) — in_review and in_work only."""
    lesson = await _get_lesson(db, lesson_id)
    if lesson.status not in WORKABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Evidence can only be modified in {WORKABLE_STATES}, lesson is '{lesson.status}'",
        )
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    uploads_dir = os.path.join(os.getcwd(), "uploads", "lessons", str(lesson_id))
    os.makedirs(uploads_dir, exist_ok=True)
    safe_name = os.path.basename(file.filename or "evidence.bin")
    stored_path = os.path.join(uploads_dir, f"{uuid.uuid4().hex}_{safe_name}")
    with open(stored_path, "wb") as fh:
        fh.write(contents)

    lf = LessonFile(
        lesson_id=lesson_id,
        filename=safe_name,
        stored_path=stored_path,
        content_type=file.content_type,
        size_bytes=len(contents),
        sha256=hashlib.sha256(contents).hexdigest(),
        uploaded_by=current_user.id,
    )
    db.add(lf)
    await db.commit()
    return {
        "id": lf.id,
        "lesson_id": lesson_id,
        "filename": lf.filename,
        "size_bytes": lf.size_bytes,
        "content_type": lf.content_type,
        "created_at": lf.created_at.isoformat() if lf.created_at else None,
    }


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
    lesson = await _get_lesson(db, lesson_id)
    if lesson.status in ("closed", "rejected"):
        raise HTTPException(status_code=409, detail=f"Lesson is {lesson.status} and read-only")
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
