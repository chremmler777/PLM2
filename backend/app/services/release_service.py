"""Stage 10: the release checklist and the lessons-learned step.

Validation (stage 9) proves the part; this proves the world around it moved
with it — drawings, ERP, packaging, the customer told — and that the team
wrote down what it learned before the change disappears into 'released'.
Both are soft-guarded on in_validation -> released (ChangeService._guard),
after the validation blocker, so an approved transition deviation can still
release a change whose paperwork is knowingly late.

Rows are written only when an item is first answered; reads show the catalog
(release_checklist.py) with unsaved 'open' rows for the rest. The guard does
NOT depend on rows existing: it counts the catalog items without a done/na
row, so a change nobody looked at has 13 open items rather than none.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest
from app.models.change_validation import (
    RELEASE_CHECK_STATUSES, ChangeReleaseCheck,
)
from app.models.entities import User
from app.models.lesson import (
    LESSON_CATEGORIES, LESSON_SEVERITIES, LESSON_TYPES, LessonLearned,
)
from app.models.workflow import Department
from app.services import release_checklist as catalog
from app.services.change_plan_service import PlanConflict, PlanForbidden
from app.services.change_service import ChangeError, ChangeService

CHECK_WINDOW = ("in_implementation", "in_validation")
LESSONS_WINDOW = ("in_implementation", "in_validation")
ANSWERED = ("done", "na")


class ReleaseService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def is_pm_or_lead(session, change, user) -> bool:
        """PM, the change lead, admin: who runs the release."""
        if user.effective_role == "admin" or change.lead_id == user.id:
            return True
        return await ChangeService._user_in_department(session, user, "Project Manager")

    @staticmethod
    async def may_answer(session, change, row: ChangeReleaseCheck, user) -> bool:
        """A member of the item's owner department, PM, the lead, admin."""
        if await ReleaseService.is_pm_or_lead(session, change, user):
            return True
        if row.department_id is None:
            return False
        from app.services.workflow_service import WorkflowService
        return await WorkflowService.actor_in_department(
            session, user, row.department_id)

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    @staticmethod
    async def rows(session: AsyncSession, change: ChangeRequest) -> list[ChangeReleaseCheck]:
        return list((await session.execute(
            select(ChangeReleaseCheck).where(
                ChangeReleaseCheck.change_id == change.id))).scalars().all())

    @staticmethod
    async def _owner_ids(session: AsyncSession) -> dict[str, int]:
        return {n: i for i, n in (await session.execute(
            select(Department.id, Department.name))).all()}

    @staticmethod
    async def view_rows(session: AsyncSession,
                        change: ChangeRequest) -> list[ChangeReleaseCheck]:
        """Every catalog item, in catalog order, WITHOUT writing: an item
        nobody answered yet is an unsaved in-memory 'open' row. A GET must
        never write (two readers racing on the unique key would fail)."""
        existing = {r.check_key: r for r in await ReleaseService.rows(session, change)}
        missing = [k for k in catalog.CHECK_KEYS if k not in existing]
        if missing:
            ids = await ReleaseService._owner_ids(session)
            for key in missing:
                existing[key] = ChangeReleaseCheck(
                    change_id=change.id, check_key=key, status="open",
                    department_id=ids.get(catalog.owner_for(key)))
        return [existing[k] for k in catalog.CHECK_KEYS]

    @staticmethod
    async def _row_for_write(session: AsyncSession, change: ChangeRequest,
                             key: str) -> ChangeReleaseCheck:
        """The persisted row for one item, inserted on first answer. A
        concurrent first answer loses the insert race on the unique key: the
        savepoint rolls back and the winner's row is read instead."""
        from sqlalchemy.exc import IntegrityError
        q = select(ChangeReleaseCheck).where(
            ChangeReleaseCheck.change_id == change.id,
            ChangeReleaseCheck.check_key == key)
        row = (await session.execute(q)).scalar_one_or_none()
        if row is not None:
            return row
        ids = await ReleaseService._owner_ids(session)
        row = ChangeReleaseCheck(change_id=change.id, check_key=key, status="open",
                                 department_id=ids.get(catalog.owner_for(key)))
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            row = (await session.execute(q)).scalar_one()
        return row

    @staticmethod
    async def open_count(session: AsyncSession, change: ChangeRequest) -> int:
        """Catalog items without a done/na answer. Read-only: never seeds."""
        answered = {r.check_key for r in await ReleaseService.rows(session, change)
                    if r.status in ANSWERED}
        return sum(1 for k in catalog.CHECK_KEYS if k not in answered)

    @staticmethod
    async def set_check(session: AsyncSession, change: ChangeRequest, key: str,
                        status: str, note: Optional[str], user: User) -> None:
        if key not in catalog.CHECK_KEYS:
            raise PlanConflict(f"Unknown release check '{key}'", not_found=True)
        if status not in RELEASE_CHECK_STATUSES:
            raise ChangeError(f"Invalid status '{status}' - done, na or open")
        note = (note or "").strip() or None
        if status == "na" and not note:
            raise ChangeError("'Not applicable' needs a note saying why")
        if change.status not in CHECK_WINDOW:
            raise ChangeError(
                "The release checklist is answered during implementation and "
                "validation")
        # Rights are checked on the unsaved view row: a refused caller writes
        # nothing, not even the seed row.
        view = {r.check_key: r for r in await ReleaseService.view_rows(session, change)}
        if not await ReleaseService.may_answer(session, change, view[key], user):
            raise PlanForbidden(
                "Only the owner department, Project Management, the change "
                "lead or an admin may answer this item")
        row = await ReleaseService._row_for_write(session, change, key)
        old = row.status
        row.status = status
        row.note = note
        row.checked_by = user.id if status != "open" else None
        row.checked_at = datetime.utcnow() if status != "open" else None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "release_check",
            f"Release check '{catalog.label_for(key)}': {status}", user.id,
            notes=note, old_value={"status": old},
            new_value={"check_key": key, "status": status},
            for_department_id=row.department_id)

    # ------------------------------------------------------------------
    # Lessons
    # ------------------------------------------------------------------
    @staticmethod
    async def lessons(session: AsyncSession, change: ChangeRequest) -> list[LessonLearned]:
        return list((await session.execute(
            select(LessonLearned).where(LessonLearned.change_id == change.id)
            .order_by(LessonLearned.id))).scalars().all())

    @staticmethod
    async def add_lesson(session: AsyncSession, change: ChangeRequest,
                         spec: dict, user: User) -> LessonLearned:
        title = (spec.get("title") or "").strip()
        description = (spec.get("description") or "").strip()
        if not title or not description:
            raise ChangeError("A lesson needs a title and a description")
        category = spec.get("category") or "other"
        lesson_type = spec.get("lesson_type") or "improvement"
        severity = spec.get("severity") or "medium"
        if category not in LESSON_CATEGORIES:
            raise ChangeError(f"Invalid category '{category}'")
        if lesson_type not in LESSON_TYPES:
            raise ChangeError(f"Invalid lesson type '{lesson_type}'")
        if severity not in LESSON_SEVERITIES:
            raise ChangeError(f"Invalid severity '{severity}'")
        lesson = LessonLearned(
            title=title[:200], description=description,
            project_id=change.project_id, project_ref=change.change_number,
            change_id=change.id, category=category, lesson_type=lesson_type,
            severity=severity,
            recommendation=(spec.get("recommendation") or "").strip() or None,
            status="in_review", created_by=user.id)
        session.add(lesson)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "lesson_added", f"Lesson added: {lesson.title}",
            user.id, new_value={"lesson_id": lesson.id, "category": category})
        return lesson

    @staticmethod
    async def complete_lessons(session: AsyncSession, change: ChangeRequest,
                               none_reason: Optional[str], user: User) -> None:
        if not await ReleaseService.is_pm_or_lead(session, change, user):
            raise PlanForbidden(
                "Only Project Management, the change lead or an admin may "
                "complete the lessons-learned step")
        if change.status not in LESSONS_WINDOW:
            raise ChangeError(
                "The lessons-learned step is completed during implementation "
                "or validation")
        none_reason = (none_reason or "").strip() or None
        count = len(await ReleaseService.lessons(session, change))
        if count == 0 and not none_reason:
            raise ChangeError(
                "Add at least one lesson, or say why there is none to record")
        change.lessons_done_at = datetime.utcnow()
        change.lessons_done_by = user.id
        change.lessons_none_reason = none_reason if count == 0 else None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "lessons_completed",
            (f"Lessons-learned step completed ({count} lesson(s))" if count
             else f"Lessons-learned step completed without lessons: {none_reason}"),
            user.id, notes=none_reason,
            new_value={"lessons": count, "none_reason": change.lessons_none_reason})

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @staticmethod
    async def open_deviation_count(session: AsyncSession,
                                   change: ChangeRequest) -> int:
        """Moves with a plan deviation nobody decided yet, in the one unit
        every surface uses: one per deviation group (one edit), plus every
        open row that belongs to no group. Read-only use of the plan model."""
        from app.services.change_plan_service import ChangePlanService
        return await ChangePlanService.open_deviation_count(session, change)

    @staticmethod
    def deviations_message(n: int) -> str:
        return (f"{n} move{'s' if n != 1 else ''} with plan deviations still "
                "open: lock or escalate them first")

    @staticmethod
    def not_ready_message(progress: dict) -> Optional[str]:
        """The ready-to-go half, in the same words for the guard and the
        Release tab: None when every impacted revision is through its check
        workflow."""
        if progress["ready_to_go"]:
            return None
        pending = sum(1 for e in progress["items"] if not e["ready"])
        if not progress["items"]:
            return "Not ready to go: no impacted revision to release"
        if pending == 1:
            return ("Not ready to go: 1 impacted revision has not completed "
                    "its check workflow")
        return (f"Not ready to go: {pending} impacted revisions have not "
                "completed their check workflow")

    @staticmethod
    async def guard_reason(session: AsyncSession,
                           change: ChangeRequest) -> Optional[str]:
        """The release checklist, lessons and plan deviation half of the
        released guard."""
        n = await ReleaseService.open_count(session, change)
        if n:
            return f"Release checklist incomplete: {n} open"
        if change.lessons_done_at is None:
            return "Lessons learned step not done"
        n = await ReleaseService.open_deviation_count(session, change)
        if n:
            return ReleaseService.deviations_message(n)
        return None

    @staticmethod
    async def blockers(session: AsyncSession, change: ChangeRequest) -> list[str]:
        """Every reason the release would be refused today, in the guard's
        order and words."""
        from app.services.validation_service import ValidationService
        out = []
        blocker = await ValidationService.release_blocker(session, change)
        if blocker:
            out.append(blocker)
        from app.services.validation_issue_service import ValidationIssueService
        blocker = await ValidationIssueService.release_blocker(session, change)
        if blocker:
            out.append(blocker)
        not_ready = ReleaseService.not_ready_message(
            await ChangeService.implementation_progress(session, change))
        if not_ready:
            out.append(not_ready)
        n = await ReleaseService.open_count(session, change)
        if n:
            out.append(f"Release checklist incomplete: {n} open")
        if change.lessons_done_at is None:
            out.append("Lessons learned step not done")
        n = await ReleaseService.open_deviation_count(session, change)
        if n:
            out.append(ReleaseService.deviations_message(n))
        return out

    @staticmethod
    async def state(session: AsyncSession, change: ChangeRequest) -> dict:
        rows = await ReleaseService.view_rows(session, change)
        names = {i: n for i, n in (await session.execute(
            select(Department.id, Department.name))).all()}
        lessons = await ReleaseService.lessons(session, change)
        user_ids = [r.checked_by for r in rows] + [l.created_by for l in lessons] \
            + [change.lessons_done_by]
        from app.services.change_plan_service import ChangePlanService
        users = await ChangePlanService._user_names(session, user_ids)
        weight = change.validated_part_weight_g
        hints = {}
        if weight is not None:
            hints["weight_measured"] = f"Validated part weight on file: {float(weight):g} g"
        hints.update(await ReleaseService.revision_hints(session, change))
        blockers = await ReleaseService.blockers(session, change)
        return {
            "checks": [{
                "key": r.check_key, "label": catalog.label_for(r.check_key),
                "department_id": r.department_id,
                "department_name": names.get(r.department_id)
                or catalog.owner_for(r.check_key),
                "status": r.status, "note": r.note,
                "by_name": users.get(r.checked_by), "at": r.checked_at,
                "hint": hints.get(r.check_key),
            } for r in rows],
            "open_count": sum(1 for r in rows if r.status not in ANSWERED),
            "lessons": {
                "done_at": change.lessons_done_at,
                "done_by_name": users.get(change.lessons_done_by),
                "none_reason": change.lessons_none_reason,
                "items": [ReleaseService.lesson_out(l, users) for l in lessons],
            },
            "can_release": change.status == "in_validation" and not blockers,
            "blockers": blockers,
        }

    @staticmethod
    async def revision_hints(session: AsyncSession, change: ChangeRequest) -> dict:
        """Spec §17: "index updated" and "drawing and 3D data released" read
        the linked revisions: which index each part gets (activated on
        release, or already active) and whether its drawing / 3D files are
        on file."""
        from app.models.part import Part, PartRevision, RevisionFile
        lines_index, lines_files = [], []
        for item in change.impacted_items:
            if item.resulting_revision_id is None:
                continue
            rev = await session.get(PartRevision, item.resulting_revision_id)
            part = await session.get(Part, item.part_id)
            if rev is None or part is None:
                continue
            active = part.active_revision_id == rev.id
            lines_index.append(
                f"{part.part_number} index {rev.revision_name}"
                + (" active" if active else " activated on release"))
            types = set((await session.execute(
                select(RevisionFile.file_type).where(
                    RevisionFile.revision_id == rev.id,
                    RevisionFile.is_deleted.is_(False)))).scalars().all())
            has = [t for t in ("drawing", "cad") if t in types]
            lines_files.append(
                f"{part.part_number} {rev.revision_name}: "
                + (" and ".join({"drawing": "drawing", "cad": "3D"}[t] for t in has)
                   + " on file" if has else ("files on file" if types else "no files yet")))
        out = {}
        if lines_index:
            out["index_updated"] = "; ".join(lines_index)
        if lines_files:
            out["drawing_released"] = "; ".join(lines_files)
        return out

    @staticmethod
    def lesson_out(l: LessonLearned, users: dict) -> dict:
        return {
            "id": l.id, "title": l.title, "description": l.description,
            "category": l.category, "lesson_type": l.lesson_type,
            "severity": l.severity, "recommendation": l.recommendation,
            "status": l.status, "project_id": l.project_id,
            "change_id": l.change_id, "created_by": l.created_by,
            "created_by_name": users.get(l.created_by), "created_at": l.created_at,
        }
