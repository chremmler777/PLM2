"""Per-department costing pipeline (live ECR test, 2026-10-14).

A department does not wait for the whole team: once it has submitted its
assessment as feasible (or feasible with conditions) and its checklist owes a
cost input (ChangeService.owes_costing_input), it opens, fills and FINALIZES
its own costing while the change is still in assessment. The change still
moves in_assessment -> costing only when every assessment is in; a department
that finalized early stays finalized, so costing can be complete the moment
the change enters it.

Finalized is the department's answer, stored on its assessment row
(details.costing_finalized_at / _by, no migration). The row is the right
home: when the assessment is superseded (back to scoping after a "not
feasible") the rows go and with them every finalization, so early costing is
back to draft with the answer it was built on. Positions and lines stay as
the department's draft.

Rules:
- window: the change is in costing, or in assessment and the department owes
  costing (submitted feasible, checklist marked something impacted);
- a finalized department's members no longer write its figures (PM and admin
  still may, as everywhere in costing); the department reopens its own input
  while costing is open (in assessment or costing);
- finalizing needs at least one cost line or position: a zero line is an
  answer, nothing at all is silence.
"""
from datetime import datetime
import json
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.entities import User

COSTING_VERDICTS = ("feasible", "feasible_with_conditions")
# The statuses a department's costing can be open in.
OPEN_STATUSES = ("in_assessment", "costing")


class EarlyCostingError(ValueError):
    """Refused finalize/reopen; mapped to HTTP 400 (403 for rights)."""


class EarlyCostingForbidden(EarlyCostingError):
    pass


def _rows(change: ChangeRequest, department_id: int) -> list[ChangeAssessment]:
    return sorted((a for a in change.assessments if a.department_id == department_id),
                  key=lambda a: (a.stage_order, a.id or 0))


def owes(change: ChangeRequest, department_id: int) -> bool:
    """The department answered feasible and its answer owes a cost input."""
    from app.services.change_service import ChangeService
    return any(a.verdict in COSTING_VERDICTS and ChangeService.owes_costing_input(a)
               for a in _rows(change, department_id))


def has_costing_verdict(change: ChangeRequest, department_id: int) -> bool:
    return any(a.verdict in COSTING_VERDICTS for a in _rows(change, department_id))


def costing_open_for(change: ChangeRequest, department_id: int) -> bool:
    """Is the costing window open for this department right now?"""
    if change.status == "costing":
        return True
    return change.status == "in_assessment" and owes(change, department_id)


def finalized_row(change: ChangeRequest, department_id: int) -> Optional[ChangeAssessment]:
    return next((a for a in _rows(change, department_id)
                 if a.details_dict.get("costing_finalized_at")), None)


def is_finalized(change: ChangeRequest, department_id: int) -> bool:
    return finalized_row(change, department_id) is not None


def owed_department_ids(change: ChangeRequest) -> list[int]:
    """Departments that owe a cost input: a feasible answer that is not a
    "nothing impacted"."""
    return sorted({a.department_id for a in change.assessments
                   if owes(change, a.department_id)})


def finalized_department_ids(change: ChangeRequest) -> list[int]:
    return sorted({a.department_id for a in change.assessments
                   if a.details_dict.get("costing_finalized_at")})


def _set_details(a: ChangeAssessment, **kv) -> None:
    d = a.details_dict
    for k, v in kv.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    a.details = json.dumps(d) if d else None


async def _may_act(session: AsyncSession, change: ChangeRequest,
                   department_id: int, actor: User) -> bool:
    """The department itself, or the people who run costing (PM, admin)."""
    from app.services.meeting_service import MeetingService
    from app.services.workflow_service import WorkflowService
    if (actor.effective_role == "admin"
            or await MeetingService.user_is_pm_member(session, actor)):
        return True
    return await WorkflowService.actor_in_department(session, actor, department_id)


async def _has_answer(session: AsyncSession, change: ChangeRequest,
                      department_id: int) -> bool:
    from app.models.change_cost import AssessmentCostLine, CostingPosition
    lines = (await session.execute(
        select(func.count(AssessmentCostLine.id))
        .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
        .where(ChangeAssessment.change_id == change.id,
               ChangeAssessment.department_id == department_id))).scalar() or 0
    if lines:
        return True
    positions = (await session.execute(
        select(func.count(CostingPosition.id)).where(
            CostingPosition.change_id == change.id,
            CostingPosition.department_id == department_id))).scalar() or 0
    return bool(positions)


async def finalize(session: AsyncSession, change: ChangeRequest,
                   department_id: int, actor: User) -> ChangeAssessment:
    from app.services.change_service import ChangeService
    if not await _may_act(session, change, department_id, actor):
        raise EarlyCostingForbidden(
            "Only a member of that department, Project Management or an admin "
            "may finalize its costing")
    if change.status not in OPEN_STATUSES:
        raise EarlyCostingError("Costing is not open on this change")
    if not has_costing_verdict(change, department_id):
        raise EarlyCostingError(
            "The department has not submitted a feasible assessment: there is "
            "no costing to finalize")
    if not costing_open_for(change, department_id):
        raise EarlyCostingError(
            "The department's assessment marked nothing impacted: it owes no "
            "costing input")
    if is_finalized(change, department_id):
        raise EarlyCostingError("The department's costing is already finalized")
    if not await _has_answer(session, change, department_id):
        raise EarlyCostingError(
            "Enter at least one cost line or position before you finalize "
            "(a zero line says the department costs nothing)")
    anchor = next((a for a in _rows(change, department_id)
                   if a.verdict in COSTING_VERDICTS), None)
    _set_details(anchor, costing_finalized_at=datetime.utcnow().isoformat(),
                 costing_finalized_by=actor.id)
    await session.flush()
    await ChangeService.append_changelog(
        session, change, "costing_finalized",
        f"Costing finalized for dept {department_id}"
        + (" during assessment" if change.status == "in_assessment" else ""),
        actor.id, new_value={"department_id": department_id,
                             "status": change.status},
        for_department_id=department_id)
    return anchor


async def reopen(session: AsyncSession, change: ChangeRequest,
                 department_id: int, actor: User,
                 reason: Optional[str] = None) -> None:
    """Back to draft: the department changes its figures again. Only while
    costing is open; once closed (quoting) costing is reopened as a whole."""
    from app.services.change_service import ChangeService
    if not await _may_act(session, change, department_id, actor):
        raise EarlyCostingForbidden(
            "Only a member of that department, Project Management or an admin "
            "may reopen its costing")
    if change.status not in OPEN_STATUSES:
        raise EarlyCostingError(
            "Costing is closed: reopen costing for the change first")
    rows = [a for a in _rows(change, department_id)
            if a.details_dict.get("costing_finalized_at")]
    if not rows:
        raise EarlyCostingError("The department's costing is not finalized")
    for a in rows:
        _set_details(a, costing_finalized_at=None, costing_finalized_by=None)
    await session.flush()
    note = (reason or "").strip() or None
    await ChangeService.append_changelog(
        session, change, "costing_input_reopened",
        f"Costing input reopened for dept {department_id}"
        + (f": {note}" if note else ""),
        actor.id, new_value={"department_id": department_id}, notes=note,
        for_department_id=department_id)


def state(change: ChangeRequest) -> dict:
    """The progress line: who owes, who finalized, who is still open."""
    owed = owed_department_ids(change)
    done = set(finalized_department_ids(change))
    return {"owed": owed, "finalized": sorted(done & set(owed)),
            "pending": [d for d in owed if d not in done]}
