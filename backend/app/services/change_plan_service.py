"""The change plan (stages 4-8): quote plan, detailed plan, timing validation,
tracker and deviations.

One engine for two plans. The QUOTE plan is Sales' rough timeline while the
offer is written, seeded from the costing (lead times and support hours are
already there, nobody should retype them into a Gantt). The DETAILED plan is
a copy of it after acceptance that every responsible team confirms; "Timing
validated" freezes a baseline on it, and from then on dates only move as
deviations with a reason, because the baseline is what the customer was told.

The math is deliberately plain: calendar days, finish-to-start links, a
forward pass that only ever pushes tasks later, and a textbook critical path.
Anything cleverer (working calendars, lags, resource levelling) belongs in
MS Project, which is why the plan exports MSPDI.
"""
import csv
import io
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional
from xml.etree import ElementTree as ET

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import BLOCKING_LETTERS, ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.change_impl import ImplementationEscalation
from app.models.change_plan import (
    FEEDBACK_VERDICTS, PLAN_KINDS, TASK_KINDS,
    ChangePlanDeviation, ChangePlanFeedback, ChangePlanTask,
)
from app.models.entities import User
from app.models.workflow import Department
from app.services.change_service import ChangeError, ChangeService


class PlanForbidden(Exception):
    """The caller may not do this; mapped to HTTP 403 in the router."""


class PlanConflict(Exception):
    """The request collides with existing state; mapped to HTTP 409."""

    def __init__(self, message: str, **extra):
        super().__init__(message)
        self.extra = extra


# Where each plan may be edited. The quote plan belongs to the offer, so it
# freezes when the customer has accepted; the detailed plan belongs to the
# implementation and freezes when validation starts.
QUOTE_WINDOW = ("costing", "quoting", "quoted")
DETAILED_WINDOW = ("approved", "in_implementation")
# Progress (percent, actual dates) is tracker work: implementation only.
PROGRESS_WINDOW = ("in_implementation",)
FEEDBACK_WINDOW = ("approved", "in_implementation")
TIMING_VALIDATION_WINDOW = ("approved", "in_implementation")

# Structural fields: what the plan IS. Frozen on the detailed plan once the
# baseline is set — after that only dates move, and only as deviations.
STRUCTURAL_FIELDS = ("name", "kind", "lane", "department_id", "predecessors",
                     "is_idea", "sort_order")
DATE_FIELDS = ("start_date", "duration_days")
PROGRESS_FIELDS = ("progress_pct", "actual_start", "actual_finish")
FREE_FIELDS = ("notes",)
WRITABLE_FIELDS = STRUCTURAL_FIELDS + DATE_FIELDS + PROGRESS_FIELDS + FREE_FIELDS

EDITOR_DEPARTMENTS = ("Sales", "Project Manager", "Scheduling")
DEVIATION_DEPARTMENTS = ("Sales", "Project Manager")

# Template constants (spec §4, quote plan seed).
ORDER_OFFSET_DAYS = 7
SAMPLING_DAYS = 5
VALIDATION_DAYS = 7
CUSTOMER_APPROVAL_DAYS = 14
BANK_BUILD_DAYS = 10
FALLBACK_IMPLEMENTATION_DAYS = 20
MIN_BUFFER_DAYS = 5
TOOL_DEPARTMENT = "Tool Engineer"

MSPDI_NS = "http://schemas.microsoft.com/project"


def _issue(code: str, message: str, task_id: Optional[int] = None) -> dict:
    return {"code": code, "message": message, "task_id": task_id}


def _as_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _last_day(t) -> date:
    """The inclusive last day a block occupies: end - 1 for real work, the
    start itself for a milestone."""
    dur = int(t.duration_days or 0)
    return t.start_date + timedelta(days=dur - 1) if dur > 0 else t.start_date


# ----------------------------------------------------------------------
# Pure plan math (no session): shared by the API, the guard and the tests
# ----------------------------------------------------------------------
def topo_order(tasks: list) -> Optional[list]:
    """Tasks ordered so every predecessor comes first; None on a cycle.
    Unknown predecessor ids are ignored here (validation reports them)."""
    by_id = {t.id: t for t in tasks}
    indeg = {t.id: 0 for t in tasks}
    succ: dict[int, list[int]] = defaultdict(list)
    for t in tasks:
        for p in set(t.predecessors or []):
            if p in by_id and p != t.id:
                indeg[t.id] += 1
                succ[p].append(t.id)
            elif p == t.id:
                return None
    ready = sorted((tid for tid, d in indeg.items() if d == 0),
                   key=lambda i: (by_id[i].sort_order, i))
    out = []
    while ready:
        tid = ready.pop(0)
        out.append(by_id[tid])
        for s in succ[tid]:
            indeg[s] -= 1
            if indeg[s] == 0:
                ready.append(s)
        ready.sort(key=lambda i: (by_id[i].sort_order, i))
    return out if len(out) == len(tasks) else None


def plan_finish(tasks: list) -> Optional[date]:
    """Inclusive last day of the committed (non-idea) plan."""
    real = [t for t in tasks if not t.is_idea] or []
    return max((_last_day(t) for t in real), default=None)


def critical_path(tasks: list) -> dict[int, int]:
    """Slack in days per non-idea task (forward/backward pass over FS links
    with the dates as planned). Empty on a cycle: a cyclic plan has no path."""
    real = [t for t in tasks if not t.is_idea]
    order = topo_order(real)
    if order is None or not order:
        return {}
    ids = {t.id for t in real}
    succ: dict[int, list] = defaultdict(list)
    for t in real:
        for p in set(t.predecessors or []):
            if p in ids:
                succ[p].append(t)
    project_end = max(t.end_date for t in real)
    late_finish: dict[int, date] = {}
    for t in reversed(order):
        nexts = succ.get(t.id) or []
        lf = min((late_finish[s.id] - timedelta(days=int(s.duration_days or 0))
                  for s in nexts), default=project_end)
        late_finish[t.id] = lf
    return {t.id: (late_finish[t.id] - t.end_date).days for t in real}


def validate_plan(tasks: list, *, plan: str,
                  release_due: Optional[date] = None) -> dict:
    """Errors block timing validation; warnings are advice."""
    errors, warnings = [], []
    ids = {t.id for t in tasks}
    by_id = {t.id: t for t in tasks}
    for t in tasks:
        if not (t.name or "").strip():
            errors.append(_issue("empty_name", "A block has no name", t.id))
        if int(t.duration_days or 0) < 0:
            errors.append(_issue(
                "negative_duration", f"'{t.name}' has a negative duration", t.id))
        for p in t.predecessors or []:
            if p not in ids:
                errors.append(_issue(
                    "unknown_predecessor",
                    f"'{t.name}' depends on a block that does not exist ({p})", t.id))
            elif t.start_date < by_id[p].end_date:
                errors.append(_issue(
                    "dependency_violation",
                    f"'{t.name}' starts before '{by_id[p].name}' ends", t.id))
    if topo_order(tasks) is None:
        errors.append(_issue("cycle", "The dependencies form a loop"))

    real = [t for t in tasks if not t.is_idea]
    if real:
        finish = plan_finish(real)
        start = min(t.start_date for t in real)
        span = (max(t.end_date for t in real) - start).days
        if release_due is not None and finish is not None and finish > release_due:
            warnings.append(_issue(
                "after_release_deadline",
                f"The plan finishes on {finish.isoformat()}, after the release "
                f"deadline {release_due.isoformat()}"))
        buffers = [t for t in real if t.kind == "buffer"]
        if not buffers:
            warnings.append(_issue("no_buffer", "The plan has no buffer block"))
        else:
            buffer_days = sum(int(t.duration_days or 0) for t in buffers)
            if span > 0 and buffer_days < 0.05 * span:
                warnings.append(_issue(
                    "thin_buffer",
                    f"Buffer of {buffer_days} days is less than 5% of the "
                    f"{span}-day plan"))
    downtimes = [t for t in tasks if t.kind == "downtime"]
    if downtimes:
        first_down = min(t.start_date for t in downtimes)
        for t in tasks:
            if t.kind == "bank_build" and t.end_date > first_down:
                warnings.append(_issue(
                    "bank_build_late",
                    f"'{t.name}' ends after the first downtime starts "
                    f"({first_down.isoformat()})", t.id))
    if plan == "detailed" and any(t.is_idea for t in tasks):
        warnings.append(_issue(
            "idea_blocks", "The detailed plan still contains idea blocks"))
    for t in tasks:
        if not (t.lane or "").strip() and t.department_id is None:
            warnings.append(_issue(
                "no_owner", f"'{t.name}' has no lane and no department", t.id))
    return {"errors": errors, "warnings": warnings}


class ChangePlanService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def is_editor(session: AsyncSession, change: ChangeRequest,
                        user: User) -> bool:
        """Admin, the change lead, Sales, Project Management, Scheduling —
        the people who own the promise to the customer and the shop plan.
        Acts-as aware through _user_in_department."""
        if user.effective_role == "admin" or change.lead_id == user.id:
            return True
        for name in EDITOR_DEPARTMENTS:
            if await ChangeService._user_in_department(session, user, name):
                return True
        return False

    @staticmethod
    async def may_validate_timing(session, change, user) -> bool:
        """Same set as the editors: whoever may shape the plan may declare it
        agreed, once every team has said so."""
        return await ChangePlanService.is_editor(session, change, user)

    @staticmethod
    async def may_decide_deviation(session, change, user) -> bool:
        """PM, Sales, the lead, admin: accepting a slip internally or taking
        it to the customer are the two commercial answers to it."""
        if user.effective_role == "admin" or change.lead_id == user.id:
            return True
        for name in DEVIATION_DEPARTMENTS:
            if await ChangeService._user_in_department(session, user, name):
                return True
        return False

    @staticmethod
    def _window(plan: str) -> tuple:
        return QUOTE_WINDOW if plan == "quote" else DETAILED_WINDOW

    @staticmethod
    def baselined(change: ChangeRequest, plan: str) -> bool:
        return plan == "detailed" and change.timing_validated_at is not None

    @staticmethod
    def _check_plan(plan: str) -> None:
        if plan not in PLAN_KINDS:
            raise ChangeError(f"Unknown plan '{plan}' - one of quote, detailed")

    @staticmethod
    async def _require_edit(session, change, plan, user, *, structural: bool):
        ChangePlanService._check_plan(plan)
        if not await ChangePlanService.is_editor(session, change, user):
            raise PlanForbidden(
                "Only Sales, Project Management, Scheduling, the change lead "
                "or an admin may edit the plan")
        if change.status not in ChangePlanService._window(plan):
            raise ChangeError(
                f"The {plan} plan is read-only while the change is "
                f"'{change.status}'")
        if structural and ChangePlanService.baselined(change, plan):
            raise ChangeError(
                "Timing was validated: the detailed plan's structure is "
                "frozen, only dates move (as deviations with a reason)")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def tasks(session: AsyncSession, change: ChangeRequest,
                    plan: str) -> list[ChangePlanTask]:
        return list((await session.execute(
            select(ChangePlanTask)
            .where(ChangePlanTask.change_id == change.id,
                   ChangePlanTask.plan == plan)
            .order_by(ChangePlanTask.sort_order, ChangePlanTask.id)
        )).scalars().all())

    @staticmethod
    async def _dept_names(session: AsyncSession) -> dict[int, str]:
        return {i: n for i, n in (await session.execute(
            select(Department.id, Department.name))).all()}

    @staticmethod
    async def _dept_id(session: AsyncSession, name: str) -> Optional[int]:
        return (await session.execute(
            select(Department.id).where(Department.name == name).limit(1)
        )).scalar_one_or_none()

    @staticmethod
    async def _user_names(session: AsyncSession, ids) -> dict[int, str]:
        ids = {i for i in ids if i is not None}
        if not ids:
            return {}
        return {i: n for i, n in (await session.execute(
            select(User.id, User.full_name).where(User.id.in_(ids)))).all()}

    @staticmethod
    def task_out(t: ChangePlanTask, slack: dict, critical: set,
                 dept_names: dict) -> dict:
        return {
            "id": t.id, "change_id": t.change_id, "plan": t.plan,
            "name": t.name, "lane": t.lane, "department_id": t.department_id,
            "department_name": dept_names.get(t.department_id),
            "kind": t.kind, "is_idea": bool(t.is_idea),
            "start_date": t.start_date, "duration_days": int(t.duration_days or 0),
            "end_date": t.end_date,
            "predecessors": list(t.predecessors or []),
            "sort_order": t.sort_order, "progress_pct": int(t.progress_pct or 0),
            "actual_start": t.actual_start, "actual_finish": t.actual_finish,
            "baseline_start": t.baseline_start,
            "baseline_finish": t.baseline_finish,
            "source_position_id": t.source_position_id, "notes": t.notes,
            "created_by": t.created_by, "created_at": t.created_at,
            "updated_by": t.updated_by, "updated_at": t.updated_at,
            "slack_days": slack.get(t.id),
            "is_critical": t.id in critical,
        }

    @staticmethod
    async def deadlines(session: AsyncSession, change: ChangeRequest) -> list[dict]:
        from app.models.change_offer import ChangeOffer
        out = []
        if change.required_by_date is not None:
            out.append({"key": "quote", "label": "Quote deadline",
                        "date": _as_date(change.required_by_date)})
        if change.release_due_date is not None:
            out.append({"key": "release", "label": "Release deadline",
                        "date": _as_date(change.release_due_date)})
        offer = (await session.execute(
            select(ChangeOffer).where(
                ChangeOffer.change_id == change.id,
                ChangeOffer.status.in_(("sent", "accepted")))
            .order_by(ChangeOffer.version.desc()).limit(1)
        )).scalar_one_or_none()
        if offer is not None and offer.valid_until is not None:
            out.append({"key": "offer_valid_until", "label": "Offer valid until",
                        "date": offer.valid_until})
        return out

    @staticmethod
    async def get_plan(session: AsyncSession, change: ChangeRequest,
                       plan: str, user: User) -> dict:
        ChangePlanService._check_plan(plan)
        tasks = await ChangePlanService.tasks(session, change, plan)
        slack = critical_path(tasks)
        critical = {t.id for t in tasks
                    if not t.is_idea and slack.get(t.id) == 0
                    and (int(t.duration_days or 0) > 0 or t.kind == "milestone")}
        names = await ChangePlanService._dept_names(session)
        editor = await ChangePlanService.is_editor(session, change, user)
        in_window = change.status in ChangePlanService._window(plan)
        baselined = ChangePlanService.baselined(change, plan)

        progress_ids: list[int] = []
        if plan == "detailed" and change.status in PROGRESS_WINDOW:
            task_depts = {t.department_id for t in tasks if t.department_id}
            if editor:
                progress_ids = sorted(task_depts)
            else:
                from app.services.workflow_service import WorkflowService
                mine = set(await WorkflowService.effective_department_ids(session, user))
                progress_ids = sorted(task_depts & mine)

        real = [t for t in tasks if not t.is_idea]
        start = min((t.start_date for t in real), default=None)
        finish = plan_finish(real)
        span = ((max(t.end_date for t in real) - start).days if real else 0)
        return {
            "plan": plan,
            "tasks": [ChangePlanService.task_out(t, slack, critical, names)
                      for t in tasks],
            "revision": int(change.plan_revision or 0),
            "baseline_set": any(t.baseline_start is not None for t in tasks),
            "can_edit": bool(editor and in_window and not baselined),
            "can_edit_dates": bool(editor and in_window),
            "progress_department_ids": progress_ids,
            "summary": {
                "start": start, "finish": finish, "duration_days": span,
                "buffer_days": sum(int(t.duration_days or 0) for t in real
                                   if t.kind == "buffer"),
                "critical_ids": sorted(critical),
                "ideas": sum(1 for t in tasks if t.is_idea),
            },
            "validation": validate_plan(
                tasks, plan=plan, release_due=_as_date(change.release_due_date)),
            "deadlines": await ChangePlanService.deadlines(session, change),
        }

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------
    @staticmethod
    async def _template(session: AsyncSession, change: ChangeRequest,
                        plan: str, user_id: int) -> list[ChangePlanTask]:
        """The quote plan template (spec §4) built from the costing.

        Every date is derived: the order lands a week after today or the
        quote deadline, whichever is later, and every other block hangs off
        it by its links, so the first Gantt Sales sees is already a plan and
        not a list of bars to drag into place."""
        names = await ChangePlanService._dept_names(session)
        ids_by_name = {n: i for i, n in names.items()}
        today = date.today()
        anchor = max(today, _as_date(change.required_by_date) or today) \
            + timedelta(days=ORDER_OFFSET_DAYS)

        tasks: list[ChangePlanTask] = []

        def add(name, kind, start, duration, *, lane=None, dept_id=None,
                preds=(), is_idea=False, source=None) -> ChangePlanTask:
            t = ChangePlanTask(
                change_id=change.id, plan=plan, name=name, kind=kind,
                lane=lane, department_id=dept_id, is_idea=is_idea,
                start_date=start, duration_days=duration,
                predecessors=[p.id for p in preds], sort_order=len(tasks) + 1,
                progress_pct=0, source_position_id=source,
                created_by=user_id, updated_by=user_id)
            session.add(t)
            tasks.append(t)
            return t

        async def flush():
            await session.flush()

        def after(*preds) -> date:
            return max((p.end_date for p in preds), default=anchor)

        order = add("Customer order / go-ahead", "milestone", anchor, 0,
                    lane="Customer")
        await flush()

        positions = list((await session.execute(
            select(CostingPosition).where(CostingPosition.change_id == change.id)
            .order_by(CostingPosition.department_id, CostingPosition.id)
        )).scalars().all())

        work_tail: list[ChangePlanTask] = []
        if positions:
            eng_by_dept: dict[int, ChangePlanTask] = {}
            for dept_id in sorted({p.department_id for p in positions}):
                hours = sum(float(p.hours or 0.0) for p in positions
                            if p.department_id == dept_id
                            and p.kind == "support_effort")
                if hours <= 0:
                    continue
                working = math.ceil(hours / 8.0)
                days = max(1, math.ceil(working * 7 / 5))
                dname = names.get(dept_id, f"Department {dept_id}")
                eng_by_dept[dept_id] = add(
                    f"{dname} engineering", "work", after(order), days,
                    lane=dname, dept_id=dept_id, preds=(order,))
            await flush()
            for p in positions:
                if p.kind != "external":
                    continue
                days = p.effective_lead_time_calendar_days
                if not days or days <= 0:
                    continue
                offer = p.chosen_offer or p.favorite_offer
                vendor = offer.vendor_name if offer is not None else p.vendor_name
                dname = names.get(p.department_id, f"Department {p.department_id}")
                pred = eng_by_dept.get(p.department_id) or order
                kind = "downtime" if dname == TOOL_DEPARTMENT else "supplier"
                t = add(p.label + (f" - {vendor}" if vendor else ""), kind,
                        after(pred), int(days), lane=dname,
                        dept_id=p.department_id, preds=(pred,), source=p.id)
                work_tail.append(t)
            await flush()
            if not work_tail:
                work_tail = list(eng_by_dept.values())

        if not work_tail:
            # No costing to plan from: one honest block that says "the work"
            # rather than an empty gap between the order and sampling.
            work_tail = [add("Implementation", "work", after(order),
                             FALLBACK_IMPLEMENTATION_DAYS, lane=TOOL_DEPARTMENT,
                             dept_id=ids_by_name.get(TOOL_DEPARTMENT),
                             preds=(order,))]
            await flush()

        downtimes = [t for t in work_tail if t.kind == "downtime"]
        if downtimes:
            first = min(t.start_date for t in downtimes)
            add("Bank build (idea)", "bank_build",
                first - timedelta(days=BANK_BUILD_DAYS), BANK_BUILD_DAYS,
                lane="Scheduling", dept_id=ids_by_name.get("Scheduling"),
                is_idea=True)

        sampling = add("Sampling / trial", "sampling", after(*work_tail),
                       SAMPLING_DAYS, lane=TOOL_DEPARTMENT,
                       dept_id=ids_by_name.get(TOOL_DEPARTMENT), preds=work_tail)
        await flush()
        validation = add("Measurement and validation", "validation",
                         after(sampling), VALIDATION_DAYS, lane="APQP",
                         dept_id=ids_by_name.get("APQP"), preds=(sampling,))
        await flush()
        approval = add("Customer approval (PPAP / ISIR)", "customer",
                       after(validation), CUSTOMER_APPROVAL_DAYS,
                       lane="Customer", preds=(validation,))
        await flush()
        chain = (approval.end_date - anchor).days
        buffer = add("Safety buffer", "buffer", after(approval),
                     max(MIN_BUFFER_DAYS, math.ceil(chain * 0.10)),
                     lane="Project Manager",
                     dept_id=ids_by_name.get("Project Manager"),
                     preds=(approval,))
        await flush()
        add("Start of production (change)", "milestone", after(buffer), 0,
            lane="Customer", preds=(buffer,))
        await flush()
        return tasks

    @staticmethod
    async def _clear(session, change, plan) -> None:
        for t in await ChangePlanService.tasks(session, change, plan):
            await session.delete(t)
        await session.flush()

    @staticmethod
    async def seed(session: AsyncSession, change: ChangeRequest, plan: str,
                   user: User, *, replace: bool = False) -> None:
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=True)
        existing = await ChangePlanService.tasks(session, change, plan)
        if existing and not replace:
            raise PlanConflict(
                f"The {plan} plan already has blocks - pass replace to seed it again")
        if existing:
            await ChangePlanService._clear(session, change, plan)

        source = "costing"
        if plan == "quote":
            created = await ChangePlanService._template(
                session, change, plan, user.id)
        else:
            quote = await ChangePlanService.tasks(session, change, "quote")
            if quote:
                source = "quote plan"
                created = await ChangePlanService._copy(
                    session, change, quote, "detailed", user.id)
            else:
                created = await ChangePlanService._template(
                    session, change, plan, user.id)
        if plan == "detailed":
            change.plan_revision = int(change.plan_revision or 0) + 1
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "plan_seeded",
            f"{plan.capitalize()} plan seeded from the {source} "
            f"({len(created)} blocks)", user.id,
            new_value={"plan": plan, "tasks": len(created), "source": source,
                       "replaced": bool(existing)})

    @staticmethod
    async def _copy(session, change, source: list, plan: str,
                    user_id: int) -> list[ChangePlanTask]:
        """Copy blocks into another plan, remapping ids in the links. Ideas
        stay ideas: whether the parallel bank build happens is decided on the
        detailed plan, not lost in the copy."""
        id_map: dict[int, ChangePlanTask] = {}
        for t in source:
            n = ChangePlanTask(
                change_id=change.id, plan=plan, name=t.name, lane=t.lane,
                department_id=t.department_id, kind=t.kind, is_idea=t.is_idea,
                start_date=t.start_date, duration_days=t.duration_days,
                predecessors=[], sort_order=t.sort_order, progress_pct=0,
                source_position_id=t.source_position_id, notes=t.notes,
                created_by=user_id, updated_by=user_id)
            session.add(n)
            id_map[t.id] = n
        await session.flush()
        for t in source:
            id_map[t.id].predecessors = [
                id_map[p].id for p in (t.predecessors or []) if p in id_map]
        await session.flush()
        return list(id_map.values())

    # ------------------------------------------------------------------
    # Task writes
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise(t: ChangePlanTask) -> None:
        # A milestone is a moment: a duration on it is a typo, fixed silently
        # rather than reported (spec: milestone_duration normalised on write).
        if t.kind == "milestone":
            t.duration_days = 0

    @staticmethod
    def _check_fields(spec: dict, plan_ids: set, own_id: Optional[int]) -> None:
        if "name" in spec and not (spec["name"] or "").strip():
            raise ChangeError("A block needs a name")
        if "kind" in spec and spec["kind"] not in TASK_KINDS:
            raise ChangeError(f"Unknown block kind '{spec['kind']}'")
        if "duration_days" in spec:
            if spec["duration_days"] is None or int(spec["duration_days"]) < 0:
                raise ChangeError("Duration must be zero or more days")
        if "start_date" in spec and spec["start_date"] is None:
            raise ChangeError("A block needs a start date")
        if "predecessors" in spec:
            preds = spec["predecessors"] or []
            for p in preds:
                if own_id is not None and p == own_id:
                    raise ChangeError("A block cannot depend on itself")
                if p not in plan_ids:
                    raise ChangeError(f"Predecessor {p} is not a block of this plan")
        if "progress_pct" in spec:
            v = spec["progress_pct"]
            if v is None or not 0 <= int(v) <= 100:
                raise ChangeError("Progress must be between 0 and 100")

    @staticmethod
    async def _bump(change: ChangeRequest, plan: str) -> None:
        """Every edit of the detailed plan before its baseline invalidates the
        teams' confirmations: they confirmed a plan that no longer exists."""
        if plan == "detailed" and change.timing_validated_at is None:
            change.plan_revision = int(change.plan_revision or 0) + 1

    @staticmethod
    async def add_task(session: AsyncSession, change: ChangeRequest,
                       plan: str, spec: dict, user: User) -> ChangePlanTask:
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=True)
        existing = await ChangePlanService.tasks(session, change, plan)
        spec = {k: v for k, v in spec.items() if k in WRITABLE_FIELDS}
        spec.setdefault("kind", "work")
        spec.setdefault("duration_days", 0)
        for required in ("name", "start_date"):
            if spec.get(required) in (None, ""):
                raise ChangeError(f"'{required}' is required")
        ChangePlanService._check_fields(spec, {t.id for t in existing}, None)
        t = ChangePlanTask(
            change_id=change.id, plan=plan, name=spec["name"].strip(),
            kind=spec["kind"], lane=spec.get("lane"),
            department_id=spec.get("department_id"),
            is_idea=bool(spec.get("is_idea") or False),
            start_date=spec["start_date"],
            duration_days=int(spec["duration_days"]),
            predecessors=list(spec.get("predecessors") or []),
            sort_order=spec.get("sort_order")
            or (max((x.sort_order for x in existing), default=0) + 1),
            progress_pct=0, notes=spec.get("notes"),
            created_by=user.id, updated_by=user.id)
        ChangePlanService._normalise(t)
        session.add(t)
        await session.flush()
        await ChangePlanService._bump(change, plan)
        await ChangeService.append_changelog(
            session, change, "plan_task_added",
            f"{plan.capitalize()} plan: block '{t.name}' added", user.id,
            new_value={"plan": plan, "task_id": t.id, "name": t.name,
                       "start": t.start_date.isoformat(),
                       "duration_days": t.duration_days})
        return t

    @staticmethod
    async def _get_task(session, change, tid: int) -> ChangePlanTask:
        t = await session.get(ChangePlanTask, tid)
        if t is None or t.change_id != change.id:
            raise PlanConflict("Plan block not found on this change", not_found=True)
        return t

    @staticmethod
    async def _may_progress(session, change, task, user) -> bool:
        if change.status not in PROGRESS_WINDOW or task.plan != "detailed":
            return False
        if await ChangePlanService.is_editor(session, change, user):
            return True
        if task.department_id is None:
            return False
        from app.services.workflow_service import WorkflowService
        return await WorkflowService.actor_in_department(
            session, user, task.department_id)

    @staticmethod
    async def update_task(session: AsyncSession, change: ChangeRequest,
                          tid: int, spec: dict, user: User,
                          *, reason: Optional[str] = None) -> ChangePlanTask:
        task = await ChangePlanService._get_task(session, change, tid)
        spec = {k: v for k, v in spec.items() if k in WRITABLE_FIELDS}
        if not spec:
            raise ChangeError("Nothing to update")
        plan = task.plan
        progress_only = all(k in PROGRESS_FIELDS for k in spec)
        if progress_only:
            if not await ChangePlanService._may_progress(session, change, task, user):
                raise PlanForbidden(
                    "Progress is reported on the detailed plan during "
                    "implementation, by the block's department or a plan editor")
        else:
            structural = any(k in STRUCTURAL_FIELDS for k in spec)
            await ChangePlanService._require_edit(
                session, change, plan, user, structural=structural)
            if any(k in PROGRESS_FIELDS for k in spec) and not \
                    await ChangePlanService._may_progress(session, change, task, user):
                raise ChangeError(
                    "Progress is reported during implementation only")
        siblings = await ChangePlanService.tasks(session, change, plan)
        ChangePlanService._check_fields(spec, {t.id for t in siblings}, task.id)

        date_spec = {k: spec.pop(k) for k in DATE_FIELDS if k in spec}
        before = {k: getattr(task, k) for k in spec}
        for k, v in spec.items():
            if k == "name":
                v = v.strip()
            if k == "predecessors":
                v = list(v or [])
            if k == "is_idea":
                v = bool(v)
            setattr(task, k, v)
        task.updated_by = user.id
        ChangePlanService._normalise(task)

        moved = []
        if date_spec:
            moved = await ChangePlanService._apply_dates(
                session, change, plan, siblings,
                {task.id: date_spec}, user, reason=reason)
        await session.flush()
        if spec and not progress_only and not moved:
            # _apply_dates already counted the revision for this call.
            await ChangePlanService._bump(change, plan)
        if spec or moved:
            fields = sorted(list(spec) + list(date_spec))
            await ChangeService.append_changelog(
                session, change, "plan_task_updated",
                f"{plan.capitalize()} plan: block '{task.name}' updated "
                f"({', '.join(fields)})", user.id,
                old_value={k: _json(v) for k, v in before.items()} or None,
                new_value={"plan": plan, "task_id": task.id,
                           **{k: _json(getattr(task, k)) for k in fields}})
        return task

    @staticmethod
    async def bulk_update(session: AsyncSession, change: ChangeRequest,
                          plan: str, updates: list[dict], user: User,
                          *, reason: Optional[str] = None) -> None:
        """Block move / resize of a selection: one call, one changelog entry,
        and after the baseline one deviation per task with the same reason."""
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=False)
        siblings = await ChangePlanService.tasks(session, change, plan)
        by_id = {t.id: t for t in siblings}
        changes: dict[int, dict] = {}
        for u in updates:
            tid = u.get("id")
            if tid not in by_id:
                raise ChangeError(f"Block {tid} is not part of the {plan} plan")
            d = {k: u[k] for k in DATE_FIELDS if u.get(k) is not None}
            ChangePlanService._check_fields(d, set(by_id), tid)
            if d:
                changes[tid] = d
        if not changes:
            raise ChangeError("Nothing to update")
        moved = await ChangePlanService._apply_dates(
            session, change, plan, siblings, changes, user, reason=reason)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "plan_task_updated",
            f"{plan.capitalize()} plan: {len(moved)} block(s) moved", user.id,
            new_value={"plan": plan, "task_ids": moved})

    @staticmethod
    async def _apply_dates(session, change, plan, siblings: list,
                           changes: dict[int, dict], user: User,
                           *, reason: Optional[str]) -> list[int]:
        """Apply start/duration edits. Before the baseline this is simply an
        edit (and bumps the revision). After it every changed block becomes a
        deviation: old and new dates, slip against its baseline end, and what
        the move did to the finish of the whole plan."""
        by_id = {t.id: t for t in siblings}
        baselined = ChangePlanService.baselined(change, plan)
        reason = (reason or "").strip()
        if baselined and not reason:
            raise ChangeError(
                "Timing was validated: a reason is required to move a date")
        finish_before = plan_finish(siblings)
        olds: dict[int, tuple] = {}
        moved = []
        for tid, d in changes.items():
            t = by_id[tid]
            old = (t.start_date, t.end_date)
            if "start_date" in d:
                t.start_date = d["start_date"]
            if "duration_days" in d:
                t.duration_days = int(d["duration_days"])
            ChangePlanService._normalise(t)
            t.updated_by = user.id
            if (t.start_date, t.end_date) != old:
                olds[tid] = old
                moved.append(tid)
        if not moved:
            return []
        if not baselined:
            await ChangePlanService._bump(change, plan)
            return moved
        finish_after = plan_finish(siblings)
        impact = ((finish_after - finish_before).days
                  if finish_after and finish_before else 0)
        devs = []
        for tid in moved:
            t = by_id[tid]
            base_end = t.baseline_finish or olds[tid][1]
            dev = ChangePlanDeviation(
                change_id=change.id, task_id=tid,
                old_start=olds[tid][0], old_end=olds[tid][1],
                new_start=t.start_date, new_end=t.end_date,
                slip_days=(t.end_date - base_end).days,
                finish_impact_days=impact, reason=reason, status="open",
                created_by=user.id)
            session.add(dev)
            devs.append(dev)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "plan_deviation",
            f"Plan deviation on {len(devs)} block(s), finish impact "
            f"{impact:+d} days: {reason}", user.id, notes=reason,
            new_value={"deviation_ids": [d.id for d in devs],
                       "task_ids": moved, "finish_impact_days": impact})
        return moved

    @staticmethod
    async def delete_task(session: AsyncSession, change: ChangeRequest,
                          tid: int, user: User) -> None:
        task = await ChangePlanService._get_task(session, change, tid)
        await ChangePlanService._require_edit(
            session, change, task.plan, user, structural=True)
        for t in await ChangePlanService.tasks(session, change, task.plan):
            if tid in (t.predecessors or []):
                t.predecessors = [p for p in t.predecessors if p != tid]
        gone = {"plan": task.plan, "task_id": task.id, "name": task.name}
        await session.delete(task)
        await session.flush()
        await ChangePlanService._bump(change, gone["plan"])
        await ChangeService.append_changelog(
            session, change, "plan_task_removed",
            f"{gone['plan'].capitalize()} plan: block '{gone['name']}' removed",
            user.id, old_value=gone)

    @staticmethod
    async def schedule(session: AsyncSession, change: ChangeRequest,
                       plan: str, user: User) -> list[int]:
        """Forward pass: every block that starts before its latest
        predecessor ends moves to that end, cascading. Never pulls a block
        earlier — slack somebody left on purpose is not the tool's to take."""
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=True)
        tasks = await ChangePlanService.tasks(session, change, plan)
        order = topo_order(tasks)
        if order is None:
            raise ChangeError("The dependencies form a loop - fix it before scheduling")
        by_id = {t.id: t for t in tasks}
        moved = []
        for t in order:
            ends = [by_id[p].end_date for p in (t.predecessors or []) if p in by_id]
            if ends and t.start_date < max(ends):
                t.start_date = max(ends)
                t.updated_by = user.id
                moved.append(t.id)
        await session.flush()
        if moved:
            await ChangePlanService._bump(change, plan)
            await ChangeService.append_changelog(
                session, change, "plan_task_updated",
                f"{plan.capitalize()} plan scheduled: {len(moved)} block(s) "
                "pushed after their predecessors", user.id,
                new_value={"plan": plan, "task_ids": moved, "scheduled": True})
        return moved

    # ------------------------------------------------------------------
    # Feedback and timing validation
    # ------------------------------------------------------------------
    @staticmethod
    async def required_department_ids(session: AsyncSession,
                                       change: ChangeRequest) -> list[int]:
        """Every department with an R or A assessment on the change, plus
        Scheduling (it builds the bank) and Sales (it tells the customer)."""
        ids = {a.department_id for a in change.assessments
               if a.rasic_letter in BLOCKING_LETTERS}
        for name in ("Scheduling", "Sales"):
            did = await ChangePlanService._dept_id(session, name)
            if did is not None:
                ids.add(did)
        return sorted(ids)

    @staticmethod
    async def feedback_state(session: AsyncSession,
                             change: ChangeRequest) -> dict:
        required = await ChangePlanService.required_department_ids(session, change)
        rows = list((await session.execute(
            select(ChangePlanFeedback)
            .where(ChangePlanFeedback.change_id == change.id)
            .order_by(ChangePlanFeedback.id))).scalars().all())
        latest: dict[int, ChangePlanFeedback] = {}
        for r in rows:
            latest[r.department_id] = r
        names = await ChangePlanService._dept_names(session)
        users = await ChangePlanService._user_names(
            session, [r.created_by for r in latest.values()]
            + [change.timing_validated_by])
        revision = int(change.plan_revision or 0)
        out = []
        for did in sorted(required, key=lambda i: (names.get(i) or "", i)):
            r = latest.get(did)
            out.append({
                "department_id": did, "department_name": names.get(did),
                "verdict": r.verdict if r else None,
                "note": r.note if r else None,
                "by_name": users.get(r.created_by) if r else None,
                "at": r.created_at if r else None,
                "stale": bool(r is not None and r.plan_revision < revision),
            })
        return {
            "revision": revision, "required": out,
            "all_confirmed": bool(out) and all(
                e["verdict"] == "confirmed" and not e["stale"] for e in out),
            "validated_at": change.timing_validated_at,
            "validated_by_name": users.get(change.timing_validated_by),
        }

    @staticmethod
    async def post_feedback(session: AsyncSession, change: ChangeRequest,
                            department_id: int, verdict: str,
                            note: Optional[str], user: User) -> None:
        from app.services.workflow_service import WorkflowService
        if verdict not in FEEDBACK_VERDICTS:
            raise ChangeError(f"Invalid verdict '{verdict}' - confirmed or concern")
        note = (note or "").strip() or None
        if verdict == "concern" and not note:
            raise ChangeError("A concern needs a note saying what is wrong with the plan")
        if not (user.effective_role == "admin"
                or await WorkflowService.actor_in_department(
                    session, user, department_id)):
            raise PlanForbidden(
                "Only a member of that department may answer for it")
        if change.status not in FEEDBACK_WINDOW:
            raise ChangeError(
                "The detailed plan is confirmed while the change is approved "
                "or in implementation")
        if not await ChangePlanService.tasks(session, change, "detailed"):
            raise ChangeError("There is no detailed plan to confirm yet")
        row = ChangePlanFeedback(
            change_id=change.id, department_id=department_id,
            plan_revision=int(change.plan_revision or 0), verdict=verdict,
            note=note, created_by=user.id)
        session.add(row)
        await session.flush()
        dept = await session.get(Department, department_id)
        await ChangeService.append_changelog(
            session, change, "plan_feedback",
            f"Detailed plan {verdict} by "
            f"{dept.name if dept else department_id} (revision {row.plan_revision})",
            user.id, notes=note,
            new_value={"department_id": department_id, "verdict": verdict,
                       "plan_revision": row.plan_revision})

    @staticmethod
    async def validate_timing(session: AsyncSession, change: ChangeRequest,
                              user: User) -> None:
        if not await ChangePlanService.may_validate_timing(session, change, user):
            raise PlanForbidden(
                "Only Project Management, Scheduling, Sales, the change lead "
                "or an admin may validate the timing")
        if change.status not in TIMING_VALIDATION_WINDOW:
            raise ChangeError(
                "Timing is validated while the change is approved or in "
                "implementation")
        tasks = await ChangePlanService.tasks(session, change, "detailed")
        if not tasks:
            raise ChangeError("The detailed plan is empty - seed it first")
        errors = validate_plan(tasks, plan="detailed")["errors"]
        if errors:
            raise ChangeError(
                "The detailed plan has errors: "
                + "; ".join(e["message"] for e in errors))
        if any(t.is_idea for t in tasks):
            raise ChangeError(
                "Idea blocks are still in the detailed plan - make them real "
                "blocks or remove them")
        state = await ChangePlanService.feedback_state(session, change)
        missing = [e["department_name"] or str(e["department_id"])
                   for e in state["required"]
                   if e["verdict"] != "confirmed" or e["stale"]]
        if missing:
            raise ChangeError(
                "Not every responsible team has confirmed the current plan: "
                + ", ".join(missing))
        for t in tasks:
            t.baseline_start = t.start_date
            t.baseline_finish = t.end_date
        again = change.timing_validated_at is not None
        change.timing_validated_at = datetime.utcnow()
        change.timing_validated_by = user.id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "timing_validated",
            ("Timing re-validated, baseline reset" if again
             else "Timing validated, baseline set")
            + f" (revision {int(change.plan_revision or 0)}, "
            f"finish {plan_finish(tasks).isoformat()})",
            user.id,
            new_value={"revision": int(change.plan_revision or 0),
                       "tasks": len(tasks),
                       "finish": plan_finish(tasks).isoformat()})

    # ------------------------------------------------------------------
    # Deviations
    # ------------------------------------------------------------------
    @staticmethod
    async def list_deviations(session: AsyncSession,
                              change: ChangeRequest) -> list[dict]:
        rows = (await session.execute(
            select(ChangePlanDeviation, ChangePlanTask.name)
            .join(ChangePlanTask, ChangePlanTask.id == ChangePlanDeviation.task_id,
                  isouter=True)
            .where(ChangePlanDeviation.change_id == change.id)
            .order_by(ChangePlanDeviation.id.desc()))).all()
        users = await ChangePlanService._user_names(
            session, [d.created_by for d, _ in rows] + [d.decided_by for d, _ in rows])
        return [{
            "id": d.id, "task_id": d.task_id, "task_name": name,
            "old_start": d.old_start, "old_end": d.old_end,
            "new_start": d.new_start, "new_end": d.new_end,
            "slip_days": d.slip_days, "finish_impact_days": d.finish_impact_days,
            "reason": d.reason, "status": d.status,
            "decided_by": d.decided_by, "decided_by_name": users.get(d.decided_by),
            "decided_at": d.decided_at, "decision_note": d.decision_note,
            "escalation_id": d.escalation_id,
            "created_by": d.created_by, "created_by_name": users.get(d.created_by),
            "created_at": d.created_at,
        } for d, name in rows]

    @staticmethod
    async def _get_deviation(session, change, did) -> ChangePlanDeviation:
        d = await session.get(ChangePlanDeviation, did)
        if d is None or d.change_id != change.id:
            raise PlanConflict("Deviation not found on this change", not_found=True)
        return d

    @staticmethod
    async def lock_deviation(session: AsyncSession, change: ChangeRequest,
                             did: int, note: Optional[str], user: User) -> None:
        if not await ChangePlanService.may_decide_deviation(session, change, user):
            raise PlanForbidden(
                "Only Project Management, Sales, the change lead or an admin "
                "may decide a plan deviation")
        d = await ChangePlanService._get_deviation(session, change, did)
        if d.status != "open":
            raise ChangeError(f"The deviation is already {d.status}")
        d.status = "locked"
        d.decided_by = user.id
        d.decided_at = datetime.utcnow()
        d.decision_note = (note or "").strip() or None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "deviation_locked",
            f"Plan deviation #{d.id} accepted internally", user.id,
            notes=d.decision_note,
            new_value={"deviation_id": d.id, "slip_days": d.slip_days})

    @staticmethod
    async def escalate_deviation(session: AsyncSession, change: ChangeRequest,
                                 did: int, note: str, user: User) -> None:
        if not await ChangePlanService.may_decide_deviation(session, change, user):
            raise PlanForbidden(
                "Only Project Management, Sales, the change lead or an admin "
                "may decide a plan deviation")
        note = (note or "").strip()
        if not note:
            raise ChangeError("Escalating to the customer needs a note")
        d = await ChangePlanService._get_deviation(session, change, did)
        if d.status != "open":
            raise ChangeError(f"The deviation is already {d.status}")
        esc = ImplementationEscalation(
            change_id=change.id, direction="customer", note=note,
            created_by=user.id, created_at=datetime.utcnow())
        session.add(esc)
        await session.flush()
        d.status = "escalated"
        d.escalation_id = esc.id
        d.decided_by = user.id
        d.decided_at = datetime.utcnow()
        d.decision_note = note
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "deviation_escalated",
            f"Plan deviation #{d.id} escalated to the customer", user.id,
            notes=note,
            new_value={"deviation_id": d.id, "escalation_id": esc.id,
                       "slip_days": d.slip_days,
                       "finish_impact_days": d.finish_impact_days})

    @staticmethod
    async def open_deviation_count(session: AsyncSession,
                                   change: ChangeRequest) -> int:
        return (await session.execute(
            select(func.count()).select_from(ChangePlanDeviation).where(
                ChangePlanDeviation.change_id == change.id,
                ChangePlanDeviation.status == "open"))).scalar() or 0

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------
    @staticmethod
    def mspdi_xml(change: ChangeRequest, plan: str,
                  tasks: list[ChangePlanTask]) -> bytes:
        """MS Project XML (MSPDI). Durations are elapsed days (format 8)
        because ours are calendar days, and every block carries a
        start-no-earlier-than constraint on its own date so MS Project opens
        the plan as we drew it instead of re-scheduling it on its calendar.
        Idea blocks are proposals, not work, and are left out."""
        real = [t for t in tasks if not t.is_idea]
        ET.register_namespace("", MSPDI_NS)

        def el(parent, tag, text=None):
            e = ET.SubElement(parent, f"{{{MSPDI_NS}}}{tag}")
            if text is not None:
                e.text = str(text)
            return e

        def ts(d: date) -> str:
            return f"{d.isoformat()}T08:00:00"

        def dur(days: int) -> str:
            return f"PT{24 * int(days)}H0M0S"

        root = ET.Element(f"{{{MSPDI_NS}}}Project")
        title = f"{change.change_number} {plan} plan"
        el(root, "SaveVersion", 14)
        el(root, "Name", f"{change.change_number}-{plan}.xml")
        el(root, "Title", f"{title}: {change.title}")
        el(root, "ScheduleFromStart", 1)
        start = min((t.start_date for t in real), default=date.today())
        finish = max((t.end_date for t in real), default=start)
        el(root, "StartDate", ts(start))
        el(root, "FinishDate", ts(finish))
        el(root, "CalendarUID", 1)
        el(root, "DefaultStartTime", "08:00:00")
        el(root, "MinutesPerDay", 480)
        el(root, "MinutesPerWeek", 2400)
        el(root, "DaysPerMonth", 20)
        el(root, "DurationFormat", 8)

        cals = el(root, "Calendars")
        cal = el(cals, "Calendar")
        el(cal, "UID", 1)
        el(cal, "Name", "Standard")
        el(cal, "IsBaseCalendar", 1)
        days = el(cal, "WeekDays")
        for day_type in range(1, 8):
            wd = el(days, "WeekDay")
            el(wd, "DayType", day_type)
            el(wd, "DayWorking", 1)
            wts = el(wd, "WorkingTimes")
            for a, b in (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")):
                wt = el(wts, "WorkingTime")
                el(wt, "FromTime", a)
                el(wt, "ToTime", b)

        uid = {t.id: i for i, t in enumerate(real, start=1)}
        tasks_el = el(root, "Tasks")
        for t in real:
            n = uid[t.id]
            d = int(t.duration_days or 0)
            te = el(tasks_el, "Task")
            el(te, "UID", n)
            el(te, "ID", n)
            el(te, "Name", t.name)
            el(te, "Type", 1)
            el(te, "IsNull", 0)
            el(te, "OutlineNumber", n)
            el(te, "OutlineLevel", 1)
            el(te, "Start", ts(t.start_date))
            el(te, "Finish", ts(t.end_date))
            el(te, "Duration", dur(d))
            el(te, "DurationFormat", 8)
            el(te, "Milestone", 1 if t.kind == "milestone" else 0)
            el(te, "Summary", 0)
            el(te, "PercentComplete", int(t.progress_pct or 0))
            if t.actual_start:
                el(te, "ActualStart", ts(t.actual_start))
            if t.actual_finish:
                el(te, "ActualFinish", ts(t.actual_finish))
            el(te, "ConstraintType", 4)
            el(te, "ConstraintDate", ts(t.start_date))
            notes = " | ".join(x for x in (
                f"Lane: {t.lane}" if t.lane else None,
                f"Kind: {t.kind}", t.notes) if x)
            el(te, "Notes", notes)
            for p in t.predecessors or []:
                if p in uid:
                    link = el(te, "PredecessorLink")
                    el(link, "PredecessorUID", uid[p])
                    el(link, "Type", 1)
                    el(link, "CrossProject", 0)
                    el(link, "LinkLag", 0)
                    el(link, "LagFormat", 8)
            if t.baseline_start and t.baseline_finish:
                bl = el(te, "Baseline")
                el(bl, "Number", 0)
                el(bl, "Start", ts(t.baseline_start))
                el(bl, "Finish", ts(t.baseline_finish))
                el(bl, "Duration", dur((t.baseline_finish - t.baseline_start).days))
                el(bl, "DurationFormat", 8)

        lanes = sorted({t.lane for t in real if t.lane})
        rid = {lane: i for i, lane in enumerate(lanes, start=1)}
        res_el = el(root, "Resources")
        for lane, i in rid.items():
            r = el(res_el, "Resource")
            el(r, "UID", i)
            el(r, "ID", i)
            el(r, "Name", lane)
            el(r, "Type", 1)
        asg_el = el(root, "Assignments")
        n = 0
        for t in real:
            if t.lane in rid:
                n += 1
                a = el(asg_el, "Assignment")
                el(a, "UID", n)
                el(a, "TaskUID", uid[t.id])
                el(a, "ResourceUID", rid[t.lane])
                el(a, "Units", 1)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def csv_export(tasks: list[ChangePlanTask]) -> bytes:
        """One row per block, finish as the inclusive last day (what a person
        reading a spreadsheet means by 'finish')."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "Name", "Lane", "Kind", "Start", "Finish",
                    "Duration days", "Predecessors", "Progress",
                    "Baseline start", "Baseline finish"])
        for t in tasks:
            bl_last = None
            if t.baseline_start and t.baseline_finish:
                bl_last = (t.baseline_finish - timedelta(days=1)
                           if t.baseline_finish > t.baseline_start
                           else t.baseline_start)
            w.writerow([
                t.id, t.name + (" (idea)" if t.is_idea else ""), t.lane or "",
                t.kind, t.start_date.isoformat(), _last_day(t).isoformat(),
                int(t.duration_days or 0),
                ";".join(str(p) for p in t.predecessors or []),
                int(t.progress_pct or 0),
                t.baseline_start.isoformat() if t.baseline_start else "",
                bl_last.isoformat() if bl_last else "",
            ])
        return buf.getvalue().encode("utf-8")


def _json(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v
