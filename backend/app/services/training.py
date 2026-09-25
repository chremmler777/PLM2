"""What each ECR training role has to prove, and whether a user has proved it.

Modelled 1:1 on TWOS (TWOS app/services/training.py, docs/training.md). The
curriculum lives in code, next to the practical tasks in the frontend
(frontend/src/training/tasks.ts), so a screen and the task that exercises it
ship together. The database records only what was *published* and who
*satisfied* it.

The task keys declared here are the contract with the browser. They are
spelled out literally in tests/test_training.py and in
frontend/src/training/tasks.test.ts, so a rename is a deliberate two-file
change, and the browser refuses to start a curriculum whose keys it cannot
score.

Roles, split by what the person does in a change (ruling 2026-09-25):

    project_management  Project Manager
    sales               Sales
    engineering         Development, Tool Engineer, Manufacturing Engineer,
                        Process Engineer, APQP, Packaging Engineer
    scheduling          Scheduling
    quality             Quality
    finance             Finance

A user owes the roles their departments map to. While a real admin acts as a
department (X-Acts-As-Department) they owe exactly that department's role, so
the switch is also how an admin walks a role's training.

Task results are scored in the browser, as in TWOS. A practical task runs
the real screens against a training copy that lives only in the trainee's
browser (frontend/src/training/sandbox), so only the browser can see whether
the work was done; the server records the verdict it is sent. The record says
that a named person, trained by a named trainer, sat the tasks; it is not
proof against somebody forging requests to the attempts endpoint.

While a real admin acts as a department the training is practice only: the
API refuses attestations and attempts (see app/api/v1/training.py), so the
record never carries an entry that was really an admin walking a view.

No blocking (ruling 2026-09-25): the record is kept, but the gate that would
refuse ECR actions to an untrained user is OFF unless switched on (env
TRAINING_GATE or the org setting 'training_gate'). See gate_enabled and
app/api/v1/training.py enforce_training_gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.training import AttemptResult, SignoffStatus, TrainingSignoff, TrainingVersion
from app.models.workflow import Department


@dataclass(frozen=True)
class Curriculum:
    role: str
    #: Human label, used in every message the trainee reads.
    label: str
    #: The PLM2 departments (wf_departments.name) that owe this role.
    departments: tuple[str, ...]
    #: The version of the material this code ships. The *required* version is
    #: whatever has been published (required_versions), which normally lags
    #: behind this: publishing is the act that asks people to re-train.
    code_version: int
    #: Ordered task keys; the order the trainee works through them.
    tasks: tuple[str, ...]


#: At most five tasks per role, five to eight minutes. Same ceiling as TWOS,
#: asserted on both sides: an assessment somebody takes between two meetings
#: has to stay short. Raising it has to be argued, not edited.
MAX_TASKS_PER_ROLE = 5

CURRICULA: dict[str, Curriculum] = {
    "project_management": Curriculum(
        role="project_management",
        label="Project Management",
        departments=("Project Manager",),
        code_version=1,
        tasks=("pm_set_priority",),
    ),
    "sales": Curriculum(
        role="sales",
        label="Sales",
        departments=("Sales",),
        code_version=1,
        tasks=("sales_start_change",),
    ),
    "engineering": Curriculum(
        role="engineering",
        label="Engineers",
        departments=(
            "Development",
            "Tool Engineer",
            "Manufacturing Engineer",
            "Process Engineer",
            "APQP",
            "Packaging Engineer",
        ),
        code_version=1,
        tasks=("eng_answer_checklist_row", "eng_submit_assessment"),
    ),
    "scheduling": Curriculum(
        role="scheduling",
        label="Scheduling",
        departments=("Scheduling",),
        code_version=1,
        tasks=("sch_answer_checklist_row",),
    ),
    "quality": Curriculum(
        role="quality",
        label="Quality",
        departments=("Quality",),
        code_version=1,
        tasks=("qa_answer_checklist_row",),
    ),
    "finance": Curriculum(
        role="finance",
        label="Finance",
        departments=("Finance",),
        code_version=1,
        tasks=("fin_answer_checklist_row",),
    ),
}

ROLE_ORDER: tuple[str, ...] = tuple(CURRICULA)

#: department name -> training role
DEPARTMENT_ROLE: dict[str, str] = {
    dept: cur.role for cur in CURRICULA.values() for dept in cur.departments
}

#: Who may publish a new version, record attendance and export the roster,
#: besides a real admin. The departments that own the process and its audit.
MANAGE_DEPARTMENTS: tuple[str, ...] = ("Quality", "Project Manager")

#: Version 1 is required whether or not anyone published it.
IMPLICIT_VERSION = 1

#: org_settings key for the gate. "1"/"true" means on; anything else off.
GATE_SETTING_KEY = "training_gate"


# ---------------------------------------------------------------- roles

async def _department_names(db: AsyncSession, user) -> list[str]:
    from app.services.workflow_service import WorkflowService

    ids = await WorkflowService.effective_department_ids(db, user)
    if not ids:
        return []
    rows = (await db.execute(
        select(Department.name).where(Department.id.in_(ids))
    )).all()
    return [n for (n,) in rows]


def roles_for_departments(names: list[str] | set[str]) -> list[str]:
    """The training roles these departments owe, in a stable order."""
    held = {DEPARTMENT_ROLE[n] for n in names if n in DEPARTMENT_ROLE}
    return [r for r in ROLE_ORDER if r in held]


async def roles_for_user(db: AsyncSession, user) -> list[str]:
    """The training roles this user owes (acts-as honoured)."""
    return roles_for_departments(await _department_names(db, user))


async def roles_held(db: AsyncSession, user_id: int) -> list[str]:
    """The roles a user owes through their real memberships (acts-as ignored).

    What a roster entry is checked against: attendance is only recorded for
    a role the trainee's own departments owe.
    """
    from app.services.workflow_service import WorkflowService

    ids = await WorkflowService.get_user_department_ids(db, user_id)
    if not ids:
        return []
    rows = (await db.execute(
        select(Department.name).where(Department.id.in_(ids))
    )).all()
    return roles_for_departments([n for (n,) in rows])


async def can_manage(db: AsyncSession, user) -> bool:
    """Publish, roster, export: a real admin, or Quality / Project Management.

    Acting as a department does not lend its rights here in either direction:
    a real admin keeps them, a department member keeps theirs.
    """
    if getattr(user, "is_real_admin", False):
        return True
    from app.services.workflow_service import WorkflowService

    ids = await WorkflowService.get_user_department_ids(db, user.id)
    if not ids:
        return False
    rows = (await db.execute(
        select(Department.name).where(Department.id.in_(ids))
    )).all()
    return any(n in MANAGE_DEPARTMENTS for (n,) in rows)


# ---------------------------------------------------------------- versions

async def required_versions(db: AsyncSession) -> dict[str, int]:
    """Role -> the version currently required: the highest published, else 1.

    Never the code version: shipping version 2 of the material must not ask
    anybody to re-train. Publishing chooses that moment.
    """
    rows = (await db.execute(
        select(TrainingVersion.role, TrainingVersion.version)
    )).all()
    highest: dict[str, int] = {r: IMPLICIT_VERSION for r in CURRICULA}
    for role, version in rows:
        if role in highest and version > highest[role]:
            highest[role] = version
    return highest


def tasks_for(role: str, version: int) -> tuple[str, ...]:
    """The task keys a sign-off at this version needs passing attempts for.

    Only the shipped curriculum is known to code; an older version is history,
    read and never re-attempted, so the shipped list is the right answer for
    anything still being worked on.
    """
    cur = CURRICULA.get(role)
    return cur.tasks if cur else ()


# ---------------------------------------------------------------- status

def recompute_status(signoff: TrainingSignoff) -> str:
    """The one place a sign-off's status is decided, from its own stamps."""
    if signoff.superseded_at is not None:
        return SignoffStatus.superseded
    if signoff.tasks_passed_at is None:
        return SignoffStatus.pending_tasks
    return SignoffStatus.active


def passed_task_keys(signoff: TrainingSignoff) -> set[str]:
    return {a.task_key for a in signoff.attempts if a.result == AttemptResult.passed}


def all_tasks_passed(signoff: TrainingSignoff) -> bool:
    required = set(tasks_for(signoff.role, signoff.version))
    return bool(required) and required <= passed_task_keys(signoff)


def maybe_stamp_tasks_passed(signoff: TrainingSignoff, now: datetime,
                             software_version: str) -> bool:
    """Stamp the pass, and the software version it was passed on. Idempotent.

    This is the moment the record becomes real, so it is where the version is
    captured, not at attestation: "assessed on ECR 1.0" is a claim an auditor
    can use, "named a trainer while 1.0 was running" is not.
    """
    if signoff.tasks_passed_at is None and all_tasks_passed(signoff):
        signoff.tasks_passed_at = now
        signoff.software_version = software_version
        signoff.status = recompute_status(signoff)
        return True
    return False


RETRAIN_REASON = (
    "The material for this role was updated. Your training record carried "
    "forward; the short practical tasks are taken again for the new version."
)

OPEN_REASONS = {
    None: "Training has not been recorded for this role yet.",
    SignoffStatus.pending_tasks: "The practical tasks have not all been passed yet.",
    SignoffStatus.superseded: (
        "The material for this role was updated. The practical tasks are taken "
        "again for the new version."
    ),
}


def open_reason_for(signoff: Optional[TrainingSignoff], status_key: Optional[str]) -> str:
    """Why this role is not signed off yet, in the words the person reads."""
    if (signoff is not None and signoff.carried_from_id is not None
            and signoff.status == SignoffStatus.pending_tasks):
        return RETRAIN_REASON
    return OPEN_REASONS[status_key]


@dataclass(frozen=True)
class RoleClearance:
    role: str
    label: str
    required_version: int
    signoff: Optional[TrainingSignoff]
    cleared: bool
    #: True when the person held an active record at an older version: a new
    #: version was published and the tasks are due again.
    retrain_due: bool
    reason: Optional[str]


async def clearance_for(db: AsyncSession, user_id: int, roles: list[str]) -> list[RoleClearance]:
    """Per owed role: the row at the required version, and whether it clears."""
    if not roles:
        return []
    required = await required_versions(db)
    rows = (await db.execute(
        select(TrainingSignoff).where(
            TrainingSignoff.user_id == user_id,
            TrainingSignoff.role.in_(roles),
        )
    )).scalars().all()
    by_key = {(r.role, r.version): r for r in rows}
    out: list[RoleClearance] = []
    for role in roles:
        want = required[role]
        row = by_key.get((role, want))
        cleared = row is not None and row.status == SignoffStatus.active
        older = [r for (rl, v), r in by_key.items() if rl == role and v < want]
        retrain_due = not cleared and (
            (row is not None and row.carried_from_id is not None)
            or (row is None and bool(older))
        )
        status_key = row.status if row is not None else (
            SignoffStatus.superseded if older else None)
        out.append(RoleClearance(
            role=role,
            label=CURRICULA[role].label,
            required_version=want,
            signoff=row,
            cleared=cleared,
            retrain_due=retrain_due,
            reason=None if cleared else open_reason_for(row, status_key),
        ))
    return out


# ---------------------------------------------------------------- the gate

async def _org_setting(db: AsyncSession, org_id: int, key: str) -> Optional[str]:
    from app.models.cost_sheet import OrgSetting

    return (await db.execute(select(OrgSetting.value).where(
        OrgSetting.organization_id == org_id, OrgSetting.key == key))).scalar_one_or_none()


async def gate_state(db: AsyncSession, org_id: Optional[int]) -> tuple[bool, str]:
    """(enabled, source). Source is 'env', 'org' or 'default'.

    The environment wins when set, so an installation can pin it either way;
    otherwise the org setting; otherwise off. Off is the ruling (2026-09-25):
    training is recorded, it does not block ECR actions.
    """
    env = get_settings().training_gate
    if env is not None:
        return bool(env), "env"
    if org_id is not None:
        raw = await _org_setting(db, org_id, GATE_SETTING_KEY)
        if raw is not None:
            return raw.strip().lower() in ("1", "true", "on", "yes"), "org"
    return False, "default"


async def gate_enabled(db: AsyncSession, org_id: Optional[int]) -> bool:
    return (await gate_state(db, org_id))[0]


async def set_gate(db: AsyncSession, org_id: int, enabled: bool,
                   user_id: Optional[int]) -> None:
    from app.models.cost_sheet import OrgSetting

    row = (await db.execute(select(OrgSetting).where(
        OrgSetting.organization_id == org_id,
        OrgSetting.key == GATE_SETTING_KEY))).scalar_one_or_none()
    if row is None:
        row = OrgSetting(organization_id=org_id, key=GATE_SETTING_KEY)
        db.add(row)
    row.value = "1" if enabled else "0"
    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    await db.flush()


async def blocking_roles(db: AsyncSession, user) -> list[RoleClearance]:
    """The roles that would refuse this user an ECR action if the gate were on.

    Acting-as is exempt, like the TWOS role simulation: it is an admin walking
    a department's view, and refusing it would take away the one way to see
    what that department sees.
    """
    if getattr(user, "acts_as_department_id", None) is not None:
        return []
    roles = await roles_for_user(db, user)
    return [rc for rc in await clearance_for(db, user.id, roles) if not rc.cleared]
