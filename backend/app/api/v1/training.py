"""ECR training: attest, practise, publish, roster, export. /api/v1/training.

Modelled 1:1 on TWOS (TWOS app/api/v1/training.py). The shape, once:

    attest ──► pending_tasks ──pass every task──► active
                     ▲                              │
                     └── publish a new version ◄────┘ (active row: superseded,
                         a new pending row carries the attestation forward)

What differs from TWOS (ruling 2026-09-25): nothing is blocked. The record is
kept exactly as TWOS keeps it, but the gate that would refuse ECR actions to
somebody without an active sign-off is OFF unless switched on
(env TRAINING_GATE, or the org setting 'training_gate'). enforce_training_gate
below is wired onto the change routers and returns at once while it is off.

Nothing in this module reads or writes an operational change record.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.training import (
    AttemptResult,
    SignoffStatus,
    TrainerSource,
    TrainingAttempt,
    TrainingSignoff,
    TrainingVersion,
)
from app.services import training as svc
from app.services.audit_service import AuditService
from app.version import SOFTWARE_VERSION

router = APIRouter(prefix="/training", tags=["training"])


# ---------------------------------------------------------------------------
# The words the trainee reads (TWOS wording, adapted)
# ---------------------------------------------------------------------------

#: Phrased as an entitlement, not a formality. A person confirming training
#: they never had is the failure this record exists to prevent, and the only
#: lever against it is saying plainly that refusing is the correct answer.
ATTESTATION_NOTICE = (
    "Training on the ECR process is part of your job, and receiving it is your "
    "right. It is held in person, by your lead or a trained colleague.\n\n"
    "If that training has not taken place yet, do not confirm. Nothing is lost "
    "by waiting and nothing is gained by agreeing early: this record is read by "
    "auditors, and it should say what actually happened. Ask for your session. "
    "You are entitled to it."
)

ASSESSMENT_NOTICE = (
    "What follows is a short practical check. You do the things your role does "
    "most often in a change, on the real screens, in a training copy.\n\n"
    "Nothing you do here reaches the live system. No change, answer or deadline "
    "created in this exercise exists outside your own browser. You may retry as "
    "often as you like; every attempt is recorded, to show where the material "
    "needs to be clearer, not to catch you out."
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TaskState(BaseModel):
    key: str
    passed: bool
    attempts: int


class RoleState(BaseModel):
    role: str
    label: str
    departments: list[str]
    required_version: int
    code_version: int
    status: Optional[str]
    cleared: bool
    retrain_due: bool
    open_reason: Optional[str]
    training_date: Optional[date]
    attested_at: Optional[datetime]
    trainer_name: Optional[str]
    trainer_source: Optional[str]
    tasks_passed_at: Optional[datetime]
    software_version: Optional[str]
    signoff_id: Optional[int]
    tasks: list[TaskState]
    retrain_since: Optional[datetime]
    retrain_summary: Optional[str]
    attestation_carried_forward: bool


class CatalogRole(BaseModel):
    role: str
    label: str
    departments: list[str]
    code_version: int
    required_version: int
    tasks: list[str]


class TrainingStatus(BaseModel):
    user_id: int
    software_version: str
    #: Every owed role is signed off at its required version.
    cleared: bool
    #: False when none of the user's departments owes a training role.
    has_roles: bool
    roles: list[RoleState]
    catalog: list[CatalogRole]
    gate_enabled: bool
    gate_source: str
    can_manage: bool
    acting_as: Optional[str]
    attestation_notice: str
    assessment_notice: str


class AttestBody(BaseModel):
    role: str
    training_date: date
    trainer_name: str = Field(min_length=1, max_length=255)
    trainer_user_id: Optional[int] = None
    #: The explicit "yes, this training took place". Refusing is a valid
    #: outcome, so it is a value and not implied by submitting.
    confirmed: bool


class AttemptBody(BaseModel):
    role: str
    task_key: str = Field(min_length=1, max_length=80)
    result: str
    detail: Optional[dict] = None
    duration_seconds: Optional[int] = Field(default=None, ge=0)


class AttemptResponse(BaseModel):
    task_key: str
    attempt_no: int
    result: str
    role_state: RoleState


class RosterEntry(BaseModel):
    """Attendance at a session the recorder witnessed."""
    user_id: int
    role: str
    training_date: date
    trainer_name: str = Field(min_length=1, max_length=255)


class PublishBody(BaseModel):
    role: str
    summary: str = Field(min_length=1)


class VersionRead(BaseModel):
    id: int
    role: str
    version: int
    summary: str
    software_version: Optional[str]
    published_at: datetime
    published_by: str


class RosterRow(BaseModel):
    signoff_id: int
    user_id: int
    email: str
    display_name: Optional[str]
    role: str
    label: str
    version: int
    required_version: int
    status: str
    cleared: bool
    training_date: Optional[date]
    attested_at: Optional[datetime]
    trainer_name: Optional[str]
    trainer_source: Optional[str]
    tasks_passed_at: Optional[datetime]
    software_version: Optional[str]
    attempts: int
    failed_attempts: int
    recorded_by: Optional[str]
    superseded_at: Optional[datetime]
    carried_from_id: Optional[int]


class RosterResponse(BaseModel):
    items: list[RosterRow]
    required_versions: dict[str, int]
    software_version: str
    pending: int
    active: int


class GateBody(BaseModel):
    training_gate: bool


class GateRead(BaseModel):
    training_gate: bool
    source: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _actor(user: User) -> str:
    return user.email or user.username or ""


async def _audit(db: AsyncSession, user: User, *, entity_id: int, action: str,
                 payload: dict) -> None:
    """Training events land in the audit trail everybody already reads."""
    await AuditService.record(
        db, entity_type="training_signoff" if entity_id else "training",
        entity_id=entity_id, action=action, user_id=user.id, new_values=payload,
    )


async def _require_manage(db: AsyncSession, user: User) -> None:
    if not await svc.can_manage(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only an admin, Quality or Project Management keeps the training records.",
        )


def _check_role(role: str) -> None:
    if role not in svc.CURRICULA:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{role!r} is not a training role. Roles: {', '.join(svc.ROLE_ORDER)}.",
        )


async def _current_signoff(db: AsyncSession, user_id: int, role: str,
                           version: int) -> Optional[TrainingSignoff]:
    return (await db.execute(
        select(TrainingSignoff)
        .options(selectinload(TrainingSignoff.attempts))
        .where(
            TrainingSignoff.user_id == user_id,
            TrainingSignoff.role == role,
            TrainingSignoff.version == version,
        )
    )).scalar_one_or_none()


async def _latest_publication(db: AsyncSession, role: str) -> Optional[TrainingVersion]:
    return (await db.execute(
        select(TrainingVersion)
        .where(TrainingVersion.role == role)
        .order_by(TrainingVersion.version.desc())
        .limit(1)
    )).scalar_one_or_none()


def _role_state(role: str, required_version: int, signoff: Optional[TrainingSignoff],
                publication: Optional[TrainingVersion], *, retrain_due: bool = False,
                open_reason: Optional[str] = None) -> RoleState:
    cur = svc.CURRICULA[role]
    keys = svc.tasks_for(role, required_version)
    passed = svc.passed_task_keys(signoff) if signoff else set()
    counts: dict[str, int] = {}
    if signoff:
        for a in signoff.attempts:
            counts[a.task_key] = counts.get(a.task_key, 0) + 1
    cleared = signoff is not None and signoff.status == SignoffStatus.active
    if not cleared and open_reason is None:
        open_reason = svc.open_reason_for(signoff, signoff.status if signoff else None)
    republished = publication is not None and required_version > svc.IMPLICIT_VERSION
    return RoleState(
        role=role,
        label=cur.label,
        departments=list(cur.departments),
        required_version=required_version,
        code_version=cur.code_version,
        status=signoff.status if signoff else None,
        cleared=cleared,
        retrain_due=retrain_due or bool(
            not cleared and signoff is not None and signoff.carried_from_id),
        open_reason=None if cleared else open_reason,
        training_date=signoff.training_date if signoff else None,
        attested_at=signoff.attested_at if signoff else None,
        trainer_name=signoff.trainer_name if signoff else None,
        trainer_source=signoff.trainer_source if signoff else None,
        tasks_passed_at=signoff.tasks_passed_at if signoff else None,
        software_version=signoff.software_version if signoff else None,
        signoff_id=signoff.id if signoff else None,
        tasks=[TaskState(key=k, passed=k in passed, attempts=counts.get(k, 0))
               for k in keys],
        retrain_since=publication.published_at if republished else None,
        retrain_summary=publication.summary if republished else None,
        attestation_carried_forward=bool(signoff and signoff.carried_from_id),
    )


async def _owed_role(db: AsyncSession, user: User, role: str) -> int:
    """The required version for a role this user owes; 403 otherwise."""
    _check_role(role)
    if role not in await svc.roles_for_user(db, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"None of your departments owes the {svc.CURRICULA[role].label} training. "
            "Practise it instead; nothing is recorded for a role you do not hold.",
        )
    return (await svc.required_versions(db))[role]


# ---------------------------------------------------------------------------
# The trainee's own view
# ---------------------------------------------------------------------------

@router.get("/status", response_model=TrainingStatus)
async def training_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TrainingStatus:
    """Everything the Training page needs, for whoever is asking."""
    roles = await svc.roles_for_user(db, user)
    required = await svc.required_versions(db)
    clearances = await svc.clearance_for(db, user.id, roles)

    states: list[RoleState] = []
    for rc in clearances:
        signoff = None
        if rc.signoff is not None:
            signoff = await _current_signoff(db, user.id, rc.role, rc.required_version)
        states.append(_role_state(
            rc.role, rc.required_version, signoff,
            await _latest_publication(db, rc.role),
            retrain_due=rc.retrain_due, open_reason=rc.reason,
        ))

    enabled, source = await svc.gate_state(db, user.organization_id)
    dept = getattr(request.state, "acts_as_department", None)
    return TrainingStatus(
        user_id=user.id,
        software_version=SOFTWARE_VERSION,
        cleared=all(s.cleared for s in states),
        has_roles=bool(states),
        roles=states,
        catalog=[
            CatalogRole(role=c.role, label=c.label, departments=list(c.departments),
                        code_version=c.code_version, required_version=required[c.role],
                        tasks=list(c.tasks))
            for c in svc.CURRICULA.values()
        ],
        gate_enabled=enabled,
        gate_source=source,
        can_manage=await svc.can_manage(db, user),
        acting_as=dept.name if dept is not None else None,
        attestation_notice=ATTESTATION_NOTICE,
        assessment_notice=ASSESSMENT_NOTICE,
    )


@router.post("/attest", response_model=RoleState, status_code=status.HTTP_201_CREATED)
async def attest(
    body: AttestBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RoleState:
    """"I was trained, on this date, by this person."

    Refusing is a supported outcome and is simply not calling this endpoint,
    which is why `confirmed` must be true rather than assumed.
    """
    want = await _owed_role(db, user, body.role)
    if not body.confirmed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Confirm that the training took place, or leave this and ask for your session.",
        )
    if body.training_date > date.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The training date is in the future. Enter the day the session was held.",
        )
    trainer_name = body.trainer_name.strip()
    if not trainer_name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Name the person who trained you.")
    if body.trainer_user_id is not None and body.trainer_user_id == user.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Name the person who trained you. Nobody trains themselves.")
    if await _current_signoff(db, user.id, body.role, want) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You already have a {svc.CURRICULA[body.role].label} training record "
            f"at version {want}.",
        )

    row = TrainingSignoff(
        user_id=user.id,
        email_snapshot=_actor(user),
        display_name=user.full_name or user.username,
        role=body.role,
        version=want,
        training_date=body.training_date,
        attested_at=datetime.utcnow(),
        trainer_user_id=body.trainer_user_id,
        trainer_name=trainer_name,
        trainer_source=TrainerSource.self_declared,
        status=SignoffStatus.pending_tasks,
    )
    db.add(row)
    await db.flush()
    await _audit(db, user, entity_id=row.id, action="training.attested", payload={
        "role": row.role, "version": row.version,
        "training_date": body.training_date.isoformat(),
        "trainer_name": trainer_name, "software_version": SOFTWARE_VERSION,
    })
    await db.commit()
    row = await _current_signoff(db, user.id, body.role, want)
    return _role_state(body.role, want, row, await _latest_publication(db, body.role))


@router.post("/attempts", response_model=AttemptResponse,
             status_code=status.HTTP_201_CREATED)
async def record_attempt(
    body: AttemptBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AttemptResponse:
    """Record one go at one task, pass or fail.

    The browser scores the task, because the task is scored against sandbox
    state only the browser holds (same trade as TWOS: the price of "training
    never touches the real database"). The record is still worth keeping:
    it says a named person sat down in front of a named trainer and did the
    work.
    """
    if body.result not in AttemptResult.ALL:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "result must be 'passed' or 'failed'.")
    want = await _owed_role(db, user, body.role)
    signoff = await _current_signoff(db, user.id, body.role, want)
    if signoff is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Name who trained you before starting the practical tasks.")
    if signoff.status == SignoffStatus.superseded:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This training record has been superseded.")
    valid = svc.tasks_for(body.role, want)
    if body.task_key not in valid:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{body.task_key!r} is not a task of {body.role} version {want}.",
        )

    prior = sum(1 for a in signoff.attempts if a.task_key == body.task_key)
    attempt = TrainingAttempt(
        signoff_id=signoff.id, user_id=signoff.user_id, role=signoff.role,
        version=signoff.version, task_key=body.task_key, attempt_no=prior + 1,
        result=body.result, detail=body.detail, duration_seconds=body.duration_seconds,
    )
    signoff.attempts.append(attempt)
    await db.flush()

    completed = svc.maybe_stamp_tasks_passed(signoff, datetime.utcnow(), SOFTWARE_VERSION)
    await _audit(db, user, entity_id=signoff.id, action="training.attempt", payload={
        "role": signoff.role, "version": signoff.version, "task_key": body.task_key,
        "attempt_no": attempt.attempt_no, "result": body.result,
        "duration_seconds": body.duration_seconds,
    })
    if completed:
        await _audit(db, user, entity_id=signoff.id, action="training.tasks_passed",
                     payload={
                         "role": signoff.role, "version": signoff.version,
                         "tasks": list(valid), "total_attempts": len(signoff.attempts),
                         "software_version": signoff.software_version,
                     })
    await db.commit()
    signoff = await _current_signoff(db, user.id, body.role, want)
    return AttemptResponse(
        task_key=body.task_key, attempt_no=attempt.attempt_no, result=body.result,
        role_state=_role_state(body.role, want, signoff,
                               await _latest_publication(db, body.role)),
    )


# ---------------------------------------------------------------------------
# Versions: re-training on change
# ---------------------------------------------------------------------------

def _version_read(r: TrainingVersion) -> VersionRead:
    return VersionRead(id=r.id, role=r.role, version=r.version, summary=r.summary,
                       software_version=r.software_version,
                       published_at=r.published_at, published_by=r.published_by)


@router.get("/versions", response_model=list[VersionRead])
async def list_versions(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[VersionRead]:
    rows = (await db.execute(
        select(TrainingVersion).order_by(TrainingVersion.role,
                                         TrainingVersion.version.desc())
    )).scalars().all()
    return [_version_read(r) for r in rows]


@router.post("/versions", response_model=VersionRead,
             status_code=status.HTTP_201_CREATED)
async def publish_version(
    body: PublishBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VersionRead:
    """Require a new version of a role's material, from this moment.

    Every active row at the previous version becomes superseded, and a new
    pending row opens at the new version carrying the attestation forward.
    What is repeated is the practical check, not the paperwork. With the gate
    off this blocks nobody; the person sees "re-training due" on their page.
    """
    await _require_manage(db, user)
    _check_role(body.role)
    summary = body.summary.strip()
    if not summary:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Say what changed. It is what everybody re-training reads.")
    old_version = (await svc.required_versions(db))[body.role]
    new_version = old_version + 1
    now = datetime.utcnow()

    publication = TrainingVersion(
        role=body.role, version=new_version, summary=summary,
        software_version=SOFTWARE_VERSION, published_at=now,
        published_by=_actor(user), published_by_user_id=user.id,
    )
    db.add(publication)

    previous = (await db.execute(
        select(TrainingSignoff).where(
            TrainingSignoff.role == body.role,
            TrainingSignoff.version == old_version,
            TrainingSignoff.status != SignoffStatus.superseded,
        )
    )).scalars().all()

    carried = 0
    for old in previous:
        old.superseded_at = now
        old.status = svc.recompute_status(old)
        # Only an attested record carries anything forward.
        if old.attested_at is None:
            continue
        db.add(TrainingSignoff(
            user_id=old.user_id, email_snapshot=old.email_snapshot,
            display_name=old.display_name, role=old.role, version=new_version,
            training_date=old.training_date, attested_at=old.attested_at,
            trainer_user_id=old.trainer_user_id, trainer_name=old.trainer_name,
            trainer_source=old.trainer_source, recorded_by=old.recorded_by,
            recorded_by_user_id=old.recorded_by_user_id,
            status=SignoffStatus.pending_tasks, carried_from_id=old.id,
        ))
        carried += 1
    await db.flush()
    await _audit(db, user, entity_id=0, action="training.version_published", payload={
        "role": body.role, "version": new_version, "previous_version": old_version,
        "superseded": len(previous), "carried_forward": carried,
        "software_version": SOFTWARE_VERSION, "summary": summary,
    })
    await db.commit()
    return _version_read(publication)


# ---------------------------------------------------------------------------
# Roster: attendance, the audit list, the CSV
# ---------------------------------------------------------------------------

def _roster_row(r: TrainingSignoff, required: dict[str, int]) -> RosterRow:
    want = required.get(r.role, svc.IMPLICIT_VERSION)
    return RosterRow(
        signoff_id=r.id, user_id=r.user_id, email=r.email_snapshot,
        display_name=r.display_name, role=r.role,
        label=svc.CURRICULA[r.role].label if r.role in svc.CURRICULA else r.role,
        version=r.version, required_version=want, status=r.status,
        cleared=r.status == SignoffStatus.active and r.version == want,
        training_date=r.training_date, attested_at=r.attested_at,
        trainer_name=r.trainer_name, trainer_source=r.trainer_source,
        tasks_passed_at=r.tasks_passed_at, software_version=r.software_version,
        attempts=len(r.attempts),
        failed_attempts=sum(1 for a in r.attempts if a.result == AttemptResult.failed),
        recorded_by=r.recorded_by, superseded_at=r.superseded_at,
        carried_from_id=r.carried_from_id,
    )


async def _roster_rows(db: AsyncSession, *, role: Optional[str],
                       include_superseded: bool) -> tuple[list[RosterRow], dict[str, int]]:
    stmt = (
        select(TrainingSignoff)
        .options(selectinload(TrainingSignoff.attempts))
        .order_by(TrainingSignoff.role, TrainingSignoff.email_snapshot,
                  TrainingSignoff.version.desc())
    )
    if role:
        stmt = stmt.where(TrainingSignoff.role == role)
    if not include_superseded:
        stmt = stmt.where(TrainingSignoff.status != SignoffStatus.superseded)
    rows = (await db.execute(stmt)).scalars().all()
    required = await svc.required_versions(db)
    return [_roster_row(r, required) for r in rows], required


@router.get("/roster", response_model=RosterResponse)
async def roster(
    role: Optional[str] = Query(None),
    include_superseded: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RosterResponse:
    """Who is trained, on what, since when. Superseded rows on request."""
    await _require_manage(db, user)
    items, required = await _roster_rows(db, role=role,
                                         include_superseded=include_superseded)
    live = [i for i in items if i.version == i.required_version]
    return RosterResponse(
        items=items, required_versions=required, software_version=SOFTWARE_VERSION,
        pending=sum(1 for i in live if i.status == SignoffStatus.pending_tasks),
        active=sum(1 for i in live if i.status == SignoffStatus.active),
    )


@router.post("/roster", response_model=RosterRow, status_code=status.HTTP_201_CREATED)
async def record_roster_entry(
    body: RosterEntry,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RosterRow:
    """Attendance at a session the recorder witnessed. The practical tasks are
    still owed, and they are the only thing owed."""
    await _require_manage(db, user)
    _check_role(body.role)
    if body.training_date > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "The training date is in the future.")
    trainee = await db.get(User, body.user_id)
    if trainee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"User {body.user_id} not found")
    want = (await svc.required_versions(db))[body.role]
    if await _current_signoff(db, trainee.id, body.role, want) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{trainee.email} already has a {svc.CURRICULA[body.role].label} record "
            f"at version {want}.",
        )
    row = TrainingSignoff(
        user_id=trainee.id, email_snapshot=trainee.email or trainee.username,
        display_name=trainee.full_name or trainee.username, role=body.role,
        version=want, training_date=body.training_date,
        attested_at=datetime.utcnow(), trainer_name=body.trainer_name.strip(),
        trainer_source=TrainerSource.roster, recorded_by=_actor(user),
        recorded_by_user_id=user.id, status=SignoffStatus.pending_tasks,
    )
    db.add(row)
    await db.flush()
    await _audit(db, user, entity_id=row.id, action="training.roster_recorded", payload={
        "role": row.role, "version": row.version, "trainee_user_id": row.user_id,
        "training_date": body.training_date.isoformat(),
        "trainer_name": row.trainer_name, "software_version": SOFTWARE_VERSION,
    })
    await db.commit()
    row = await _current_signoff(db, trainee.id, body.role, want)
    return _roster_row(row, await svc.required_versions(db))


class PersonRow(BaseModel):
    user_id: int
    name: str
    email: str
    #: The training roles this person's departments owe.
    roles: list[str]


@router.get("/people", response_model=list[PersonRow])
async def people(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PersonRow]:
    """Active users in a department that owes a training role, with the roles.

    The roster's picker and its "not started" count. Readable by whoever keeps
    the records, which is why it exists next to /users (admin only).
    """
    await _require_manage(db, user)
    from app.models.workflow import Department, UserDepartment

    rows = (await db.execute(
        select(User.id, User.full_name, User.username, User.email, Department.name)
        .join(UserDepartment, UserDepartment.user_id == User.id)
        .join(Department, Department.id == UserDepartment.department_id)
        .where(User.is_active.is_(True), Department.is_active.is_(True))
        .order_by(User.full_name, User.id)
    )).all()
    by_user: dict[int, dict] = {}
    for uid, full_name, username, email, dept in rows:
        entry = by_user.setdefault(uid, {"name": full_name or username, "email": email,
                                         "depts": set()})
        entry["depts"].add(dept)
    out = []
    for uid, e in by_user.items():
        roles = svc.roles_for_departments(e["depts"])
        if roles:
            out.append(PersonRow(user_id=uid, name=e["name"], email=e["email"], roles=roles))
    return out


@router.get("/roster.csv")
async def roster_csv(
    role: Optional[str] = Query(None),
    include_superseded: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """The same record as a file. Defaults to the whole history: a file is taken
    away and read once."""
    await _require_manage(db, user)
    items, _ = await _roster_rows(db, role=role, include_superseded=include_superseded)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "user_id", "email", "name", "role", "role_label", "version",
        "required_version", "software_version", "status", "cleared",
        "training_date", "attested_at", "trainer", "trainer_source",
        "tasks_passed_at", "attempts", "failed_attempts", "recorded_by",
        "superseded_at", "carried_from_signoff_id",
    ])
    for i in items:
        w.writerow([
            i.user_id, i.email, i.display_name or "", i.role, i.label, i.version,
            i.required_version, i.software_version or "", i.status,
            "yes" if i.cleared else "no", i.training_date or "", i.attested_at or "",
            i.trainer_name or "", i.trainer_source or "", i.tasks_passed_at or "",
            i.attempts, i.failed_attempts, i.recorded_by or "", i.superseded_at or "",
            i.carried_from_id or "",
        ])
    stamp = datetime.utcnow().date().isoformat()
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="ecr-training-{stamp}.csv"'},
    )


# ---------------------------------------------------------------------------
# The gate switch (default off)
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=GateRead)
async def read_gate(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GateRead:
    enabled, source = await svc.gate_state(db, user.organization_id)
    return GateRead(training_gate=enabled, source=source)


@router.put("/settings", response_model=GateRead)
async def write_gate(
    body: GateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GateRead:
    """Switch the gate for this organisation. Real admins only; refused while
    the environment pins it."""
    if not user.is_real_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only an admin may switch the training gate.")
    _, source = await svc.gate_state(db, user.organization_id)
    if source == "env":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The training gate is set by the TRAINING_GATE environment "
                            "variable on this installation.")
    await svc.set_gate(db, user.organization_id, body.training_gate, user.id)
    await _audit(db, user, entity_id=0, action="training.gate_switched",
                 payload={"training_gate": body.training_gate})
    await db.commit()
    enabled, source = await svc.gate_state(db, user.organization_id)
    return GateRead(training_gate=enabled, source=source)


# ---------------------------------------------------------------------------
# The gate itself: wired onto the change routers, off by default
# ---------------------------------------------------------------------------

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
TRAINING_REQUIRED_HEADER = "X-Training-Required"


async def enforce_training_gate(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Refuse a change action to somebody whose owed training is not signed off.

    Returns at once for reads, and whenever the gate is off, which is the
    default and the ruling (2026-09-25). The user is resolved only once the
    gate is known to be on, so while it is off this costs one small settings
    read per write and nothing else.

    The refusal is a 403 whose detail is a plain sentence (every error path in
    the frontend renders detail as text) plus the X-Training-Required header
    naming the open roles, for anything that wants to link to the Training
    page.
    """
    if request.method in SAFE_METHODS:
        return
    if not await svc.gate_may_be_on(db):
        return
    user = await get_current_user(request, db)
    if not await svc.gate_enabled(db, user.organization_id):
        return
    blocking = await svc.blocking_roles(db, user)
    if not blocking:
        return
    labels = ", ".join(rc.label for rc in blocking)
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Training required: finish the ECR training for {labels} on the Training "
        "page first.",
        headers={TRAINING_REQUIRED_HEADER: ",".join(rc.role for rc in blocking)},
    )
