"""The change plan (stages 4-8): quote plan, detailed plan, timing validation,
tracker and deviations.

One engine for two plans. The QUOTE plan is Sales' rough timeline while the
offer is written, seeded from the costing (lead times and support hours are
already there, nobody should retype them into a Gantt). The DETAILED plan is
a copy of it after acceptance that every responsible team confirms; "Timing
validated" freezes a baseline on it, and from then on dates only move as
deviations with a reason, because the baseline is what the customer was told.

The scheduling math (calendars, FS/SS/FF/SF links with lag, constraints,
slack, critical path, summary rollup) lives in app.services.plan_engine,
which the frontend Gantt engine mirrors rule for rule (shared vectors in
tests/data/gantt_vectors.json). This module owns the rules around it: who
may change what, when, and what a change leaves behind (revision bumps,
deviations, changelog).
"""
import csv
import io
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from app.utils.clock import business_today

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.change import BLOCKING_LETTERS, ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.change_impl import ImplementationEscalation
from app.models.change_plan import (
    CONSTRAINT_TYPES, FEEDBACK_VERDICTS, LINK_TYPES, PLAN_KINDS, TASK_KINDS,
    ChangePlanDeviation, ChangePlanDeviationGroup, ChangePlanFeedback,
    ChangePlanLink, ChangePlanTask,
)
from app.core.display import fmt_date
from app.models.entities import User
from app.models.workflow import Department
from app.services import plan_engine as eng
from app.services.change_service import ChangeError, ChangeService


class PlanForbidden(Exception):
    """The caller may not do this; mapped to HTTP 403 in the router."""


class PlanRuleError(ChangeError):
    """A plan rule refusal with a machine-readable code (HTTP 400, detail
    {"message", "code"})."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


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
DEVIATION_DECISION_WINDOW = ("approved", "in_implementation", "in_validation")

# Structural fields: what the plan IS. Frozen on the detailed plan once the
# baseline is set; after that only dates move, and only as deviations.
STRUCTURAL_FIELDS = ("name", "kind", "lane", "department_id", "predecessors",
                     "is_idea", "sort_order", "parent_id", "constraint_type",
                     "constraint_date")
DATE_FIELDS = ("start_date", "duration_days")
PROGRESS_FIELDS = ("progress_pct", "actual_start", "actual_finish")
FREE_FIELDS = ("notes",)
WRITABLE_FIELDS = STRUCTURAL_FIELDS + DATE_FIELDS + PROGRESS_FIELDS + FREE_FIELDS

EDITOR_DEPARTMENTS = ("Sales", "Project Manager", "Scheduling")
DEVIATION_DEPARTMENTS = ("Sales", "Project Manager")

# Template constants (spec §4, quote plan seed), in calendar days.
ORDER_OFFSET_DAYS = 7
SAMPLING_DAYS = 5
VALIDATION_DAYS = 7
CUSTOMER_APPROVAL_DAYS = 14
BANK_BUILD_DAYS = 10
FALLBACK_IMPLEMENTATION_DAYS = 20
MIN_BUFFER_DAYS = 5
TOOL_DEPARTMENT = "Tool Engineer"
NAME_MAX = 200

MSPDI_NS = eng.MSPDI_NS
CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def _issue(code: str, message: str, task_id: Optional[int] = None) -> dict:
    return {"code": code, "message": message, "task_id": task_id}


_as_date = eng.as_date


def _last_day(t) -> date:
    """The inclusive last day a block occupies: end - 1 for real work, the
    start itself for a milestone."""
    dur = int(t.duration_days or 0)
    return t.end_date - timedelta(days=1) if dur > 0 else t.start_date


def _csv_cell(v):
    """Spreadsheet formula injection: a cell a spreadsheet would evaluate is
    quoted as text."""
    if isinstance(v, str) and v.startswith(CSV_DANGEROUS):
        return "'" + v
    return v


# ----------------------------------------------------------------------
# Pure plan math (no session): shared by the API, the guard and the tests
# ----------------------------------------------------------------------
def legacy_links(tasks: list) -> list:
    """FS links from the legacy `predecessors` lists (rows written before
    088, and plain task objects in tests)."""
    out = []
    for t in tasks:
        for p in t.predecessors or []:
            out.append(eng.ELink(from_id=p, to_id=t.id, type="FS", lag=0))
    return out


def e_links(links) -> list:
    """ChangePlanLink rows (or ELinks) as engine links."""
    if links is None:
        return None
    out = []
    for lk in links:
        if isinstance(lk, eng.ELink):
            out.append(lk)
        else:
            out.append(eng.ELink(from_id=lk.from_task_id, to_id=lk.to_task_id,
                                 type=lk.type or "FS", lag=int(lk.lag_days or 0),
                                 id=lk.id))
    return out


def e_tasks(tasks: list) -> list:
    return [eng.ETask(
        id=t.id, start=t.start_date, duration=int(t.duration_days or 0),
        constraint_type=getattr(t, "constraint_type", None),
        constraint_date=getattr(t, "constraint_date", None),
        parent_id=getattr(t, "parent_id", None), name=t.name or "",
        progress=int(getattr(t, "progress_pct", 0) or 0),
        idea=bool(getattr(t, "is_idea", False)),
        started=getattr(t, "actual_start", None) is not None) for t in tasks]


def _cal(cal) -> eng.Calendar:
    return cal if cal is not None else eng.Calendar()


def topo_order(tasks: list, links=None) -> Optional[list]:
    """Tasks ordered so every predecessor comes first; None on a cycle.
    Unknown ids are ignored here (validation reports them)."""
    lks = e_links(links) if links is not None else legacy_links(tasks)
    by_id = {t.id: t for t in tasks}
    if any(lk.from_id == lk.to_id for lk in lks):
        return None
    order = eng.topo([t.id for t in tasks], lks)
    return None if order is None else [by_id[i] for i in order]


def plan_finish(tasks: list) -> Optional[date]:
    """Inclusive last day of the committed (non-idea) plan."""
    real = [t for t in tasks if not t.is_idea] or []
    return max((_last_day(t) for t in real), default=None)


def analyse_plan(tasks: list, links=None, cal=None) -> eng.PlanResult:
    """Slack, critical path, rollup and WBS over the dates as they stand.
    Idea blocks take part in the rollup but not in the backward pass (an
    idea is a proposal, not a path): their slack is None."""
    lks = e_links(links) if links is not None else legacy_links(tasks)
    return eng.analyse(e_tasks(tasks), lks, _cal(cal))


def critical_path(tasks: list, links=None, cal=None) -> dict:
    """Total slack per non-idea leaf block. Empty on a cycle: a cyclic plan
    has no path."""
    res = analyse_plan(tasks, links, cal)
    if res.cycle:
        return {}
    return {tid: r.total_slack for tid, r in res.tasks.items()
            if not r.is_summary and r.total_slack is not None}


def validate_plan(tasks: list, *, plan: str, release_due: Optional[date] = None,
                  links=None, cal=None) -> dict:
    """Errors block timing validation; warnings are advice."""
    cal = _cal(cal)
    lks = e_links(links) if links is not None else legacy_links(tasks)
    found = eng.engine_issues(e_tasks(tasks), lks, cal)
    errors, warnings = list(found["errors"]), list(found["warnings"])

    summaries = eng.summary_ids(e_tasks(tasks))
    leaves = [t for t in tasks if t.id not in summaries]
    real = [t for t in leaves if not t.is_idea]
    if real:
        finish = plan_finish(real)
        start = min(t.start_date for t in real)
        span = cal.span(start, max(t.end_date for t in real))
        if release_due is not None and finish is not None and finish > release_due:
            warnings.append(_issue(
                "after_release_deadline",
                f"The plan finishes on {fmt_date(finish)}, after the release "
                f"deadline {fmt_date(release_due)}"))
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
    downtimes = [t for t in leaves if t.kind == "downtime"]
    if downtimes:
        first_down = min(t.start_date for t in downtimes)
        for t in leaves:
            if t.kind == "bank_build" and t.end_date > first_down:
                warnings.append(_issue(
                    "bank_build_late",
                    f"'{t.name}' ends after the first downtime starts "
                    f"({fmt_date(first_down)})", t.id))
    # A link out of an idea does not drive its successor (the idea follows,
    # it never pushes committed work): say so when the idea overlaps it.
    by_id = {t.id: t for t in tasks}
    late_pairs = set()
    for lk in lks:
        p, q = by_id.get(lk.from_id), by_id.get(lk.to_id)
        if p is not None and q is not None and p.is_idea and not q.is_idea \
                and p.id not in summaries and p.end_date > q.start_date \
                and (p.id, q.id) not in late_pairs:
            late_pairs.add((p.id, q.id))
            warnings.append(_issue(
                "bank_build_late",
                f"'{p.name}' (idea) ends after '{q.name}' starts "
                f"({fmt_date(q.start_date)})", p.id))
    if plan == "detailed" and any(t.is_idea for t in tasks):
        warnings.append(_issue(
            "idea_blocks", "The detailed plan still contains idea blocks"))
    for t in leaves:
        if not (t.lane or "").strip() and t.department_id is None:
            warnings.append(_issue(
                "no_owner", f"'{t.name}' has no lane and no department", t.id))
    return {"errors": errors, "warnings": warnings}


def chain_buffer_days(tasks: list, links=None) -> int:
    """Buffer days that protect the finish: buffer blocks that end the plan
    or lead to a block that does (along the links, through summaries). A
    buffer on a dead-end branch protects nothing."""
    lks = e_links(links) if links is not None else legacy_links(tasks)
    summaries = eng.summary_ids(e_tasks(tasks))
    real = [t for t in tasks if not t.is_idea and t.id not in summaries]
    if not real:
        return 0
    # the walk never goes through an idea: only a committed path counts
    ideas = {t.id for t in tasks if t.is_idea and t.id not in summaries}
    ets = [x for x in e_tasks(tasks) if x.id not in ideas]
    lks = [lk for lk in lks if lk.from_id not in ideas and lk.to_id not in ideas]
    end = max(t.end_date for t in real)
    finish_ids = {t.id for t in real if t.end_date == end}
    total = 0
    for b in real:
        if b.kind != "buffer":
            continue
        if b.id in finish_ids or finish_ids & set(eng.downstream(ets, lks, [b.id])):
            total += int(b.duration_days or 0)
    return total


def _pred_notation(links: list, t_id: int) -> str:
    """MS Project notation of a block's predecessors: 12, 13SS+2d, 14FF-1d."""
    parts = []
    for lk in links:
        if lk.to_task_id != t_id:
            continue
        lag = int(lk.lag_days or 0)
        if lk.type == "FS" and not lag:
            parts.append(str(lk.from_task_id))
        else:
            parts.append(f"{lk.from_task_id}{lk.type}"
                         + (f"{lag:+d}d" if lag else ""))
    return ";".join(parts)


class ChangePlanService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def is_editor(session: AsyncSession, change: ChangeRequest,
                        user: User) -> bool:
        """Admin, the change lead, Sales, Project Management, Scheduling:
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
    def offer_accepted(change: ChangeRequest) -> bool:
        """The customer said yes: the change stays 'quoted' until it is
        approved, but the quote plan is what was accepted."""
        return (change.accepted_offer_id is not None
                or change.customer_response == "accepted")

    @staticmethod
    def in_window(change: ChangeRequest, plan: str) -> bool:
        """The plan may be edited now: its status window, and for the quote
        plan only until the customer has accepted the offer."""
        if change.status not in ChangePlanService._window(plan):
            return False
        return not (plan == "quote" and ChangePlanService.offer_accepted(change))

    @staticmethod
    def _require_window(change: ChangeRequest, plan: str,
                        what: Optional[str] = None) -> None:
        what = what or f"The {plan} plan"
        if change.status not in ChangePlanService._window(plan):
            raise ChangeError(
                f"{what} is read-only while the change is '{change.status}'")
        if plan == "quote" and ChangePlanService.offer_accepted(change):
            raise ChangeError(
                f"{what} is read-only: the customer accepted the offer on it. "
                "Timing changes go into the detailed plan once the change is "
                "approved.")

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
        ChangePlanService._require_window(change, plan)
        if structural and ChangePlanService.baselined(change, plan):
            raise ChangeError(
                "Timing was validated: the detailed plan's structure is "
                "frozen, only dates move (as deviations with a reason)")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    def _calendars(change: ChangeRequest) -> dict:
        """plan -> calendar JSON (or None). change.plan_calendar holds one
        calendar per plan; the older flat shape (one calendar for both
        plans) still reads as that calendar for each."""
        raw = change.plan_calendar or {}
        if not isinstance(raw, dict):
            return {}
        if "mode" in raw or "workdays" in raw or "holidays" in raw:
            return {k: raw for k in PLAN_KINDS}
        return {k: raw.get(k) for k in PLAN_KINDS if raw.get(k)}

    @staticmethod
    def calendar(change: ChangeRequest, plan: str = "quote") -> eng.Calendar:
        """The plan's own calendar: the quote plan's units stay what the
        offer was written in while the detailed plan changes its own."""
        return eng.Calendar.from_json(ChangePlanService._calendars(change).get(plan))

    @staticmethod
    def auto(change: ChangeRequest, plan: str) -> bool:
        """Automatic scheduling (default on): an edit pushes the blocks its
        links drive, as the Gantt does, before the baseline too."""
        raw = ChangePlanService._calendars(change).get(plan) or {}
        return bool(raw.get("auto", True))

    @staticmethod
    def calendar_out(change: ChangeRequest, plan: str) -> dict:
        return {**ChangePlanService.calendar(change, plan).to_json(),
                "auto": ChangePlanService.auto(change, plan)}

    @staticmethod
    def _store_calendar(change: ChangeRequest, plan: str, cal: eng.Calendar,
                        auto: Optional[bool] = None) -> None:
        keep = ChangePlanService.auto(change, plan) if auto is None else bool(auto)
        cals = {k: v for k, v in ChangePlanService._calendars(change).items() if v}
        cals[plan] = {**cal.to_json(), "auto": keep}
        change.plan_calendar = cals          # a new dict: JSON change tracked

    @staticmethod
    def _attach(tasks: list, cal: eng.Calendar) -> None:
        for t in tasks:
            t._plan_cal = cal

    @staticmethod
    async def tasks(session: AsyncSession, change: ChangeRequest,
                    plan: str) -> list[ChangePlanTask]:
        """The plan's blocks in outline order (parents before children,
        siblings by sort_order), with the plan calendar attached so
        end_date counts the right days."""
        rows = list((await session.execute(
            select(ChangePlanTask)
            .where(ChangePlanTask.change_id == change.id,
                   ChangePlanTask.plan == plan)
            .order_by(ChangePlanTask.sort_order, ChangePlanTask.id)
        )).scalars().all())
        ChangePlanService._attach(rows, ChangePlanService.calendar(change, plan))
        by_id = {t.id: t for t in rows}
        return [by_id[i] for i, _ in eng.dfs_order(e_tasks(rows))]

    @staticmethod
    async def links(session: AsyncSession, change: ChangeRequest,
                    plan: str) -> list[ChangePlanLink]:
        return list((await session.execute(
            select(ChangePlanLink)
            .where(ChangePlanLink.change_id == change.id,
                   ChangePlanLink.plan == plan)
            .order_by(ChangePlanLink.id))).scalars().all())

    @staticmethod
    def _legacy_extra(tasks: list, links: list) -> list:
        """FS links a row's legacy `predecessors` list still names and no
        link covers (a row written by pre-088 code): shown and used for the
        math on read, never written. Migration 088 converted the rest."""
        ids = {t.id for t in tasks}
        linked = {frozenset((lk.from_task_id, lk.to_task_id)) for lk in links}
        out = []
        for lk in legacy_links(tasks):
            try:
                pid = int(lk.from_id)
            except (TypeError, ValueError):
                continue
            pair = frozenset((pid, lk.to_id))
            if pid == lk.to_id or pid not in ids or pair in linked:
                continue
            linked.add(pair)
            out.append(eng.ELink(from_id=pid, to_id=lk.to_id, type="FS", lag=0))
        return out

    @staticmethod
    async def _flush_links(session) -> None:
        """Flush new or changed links; the unique pair index turns a race
        (two requests linking the same pair) into a plain refusal."""
        try:
            await session.flush()
        except IntegrityError:
            raise ChangeError("These two blocks are already linked")

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
    def link_out(lk: ChangePlanLink) -> dict:
        return {"id": lk.id, "from_task_id": lk.from_task_id,
                "to_task_id": lk.to_task_id, "type": lk.type,
                "lag_days": int(lk.lag_days or 0), "legacy": False}

    @staticmethod
    def task_out(t: ChangePlanTask, res: eng.PlanResult, dept_names: dict,
                 *, preds: list, wbs: str, is_summary: bool) -> dict:
        r = res.tasks.get(t.id)
        slack = r.total_slack if r is not None else None
        progress = int(t.progress_pct or 0)
        if is_summary and r is not None:
            progress = r.progress
        return {
            "id": t.id, "change_id": t.change_id, "plan": t.plan,
            "name": t.name, "lane": t.lane, "department_id": t.department_id,
            "department_name": dept_names.get(t.department_id),
            "kind": t.kind, "is_idea": bool(t.is_idea),
            "start_date": t.start_date, "duration_days": int(t.duration_days or 0),
            "end_date": t.end_date,
            "predecessors": preds,
            "parent_id": t.parent_id,
            "constraint_type": t.constraint_type,
            "constraint_date": t.constraint_date,
            "wbs": wbs, "is_summary": is_summary,
            "sort_order": t.sort_order, "progress_pct": progress,
            "actual_start": t.actual_start, "actual_finish": t.actual_finish,
            "baseline_start": t.baseline_start,
            "baseline_finish": t.baseline_finish,
            "source_position_id": t.source_position_id, "notes": t.notes,
            "created_by": t.created_by, "created_at": t.created_at,
            "updated_by": t.updated_by, "updated_at": t.updated_at,
            "slack_days": slack,
            "total_slack": slack,
            "free_slack": r.free_slack if r is not None else None,
            "is_critical": bool(r is not None and slack is not None
                                and not t.is_idea and r.critical),
        }

    @staticmethod
    async def deadlines(session: AsyncSession, change: ChangeRequest) -> list[dict]:
        from app.models.change_offer import ChangeOffer
        out = []
        # the quote deadline matters until the quote is out, and only when
        # a customer is quoted at all (same rule as the change's deadline)
        if change.required_by_date is not None and change.customer_relevant \
                and change.quoted_at is None:
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
        # once the customer accepted, the offer's validity is history
        if offer is not None and offer.status != "accepted" \
                and offer.valid_until is not None:
            out.append({"key": "offer_valid_until", "label": "Offer valid until",
                        "date": offer.valid_until})
        return out

    @staticmethod
    async def get_plan(session: AsyncSession, change: ChangeRequest,
                       plan: str, user: User) -> dict:
        ChangePlanService._check_plan(plan)
        cal = ChangePlanService.calendar(change, plan)
        links = await ChangePlanService.links(session, change, plan)
        tasks = await ChangePlanService.tasks(session, change, plan)
        math_links = e_links(links) + ChangePlanService._legacy_extra(tasks, links)
        res = analyse_plan(tasks, math_links, cal)
        all_e = e_tasks(tasks)
        summaries = eng.summary_ids(all_e)
        wbs = dict(eng.dfs_order(all_e))
        preds: dict = defaultdict(list)
        for lk in math_links:
            if lk.type == "FS":
                preds[lk.to_id].append(lk.from_id)
        critical = sorted(
            t.id for t in tasks
            if not t.is_idea and t.id not in summaries
            and t.id in res.tasks and res.tasks[t.id].total_slack is not None
            and res.tasks[t.id].critical)
        names = await ChangePlanService._dept_names(session)
        editor = await ChangePlanService.is_editor(session, change, user)
        in_window = ChangePlanService.in_window(change, plan)
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

        real = [t for t in tasks if not t.is_idea and t.id not in summaries]
        start = min((t.start_date for t in real), default=None)
        finish = plan_finish(real)
        span = (cal.span(start, max(t.end_date for t in real)) if real else 0)
        return {
            "plan": plan,
            "tasks": [ChangePlanService.task_out(
                t, res, names, preds=preds.get(t.id, []), wbs=wbs.get(t.id, ""),
                is_summary=t.id in summaries) for t in tasks],
            # stored links, then legacy predecessor links the math also uses
            # (id null, read-only) so the browser schedules the same plan
            "links": [ChangePlanService.link_out(lk) for lk in links] + [
                {"id": None, "from_task_id": lk.from_id, "to_task_id": lk.to_id,
                 "type": "FS", "lag_days": 0, "legacy": True}
                for lk in math_links[len(links):]],
            "calendar": ChangePlanService.calendar_out(change, plan),
            "revision": int(change.plan_revision or 0),
            "baseline_set": any(t.baseline_start is not None for t in tasks),
            "can_edit": bool(editor and in_window and not baselined),
            "can_edit_dates": bool(editor and in_window),
            "progress_department_ids": progress_ids,
            "summary": {
                "start": start, "finish": finish, "duration_days": span,
                "buffer_days": chain_buffer_days(tasks, math_links),
                "critical_ids": critical,
                "ideas": sum(1 for t in tasks if t.is_idea),
            },
            "validation": validate_plan(
                tasks, plan=plan, release_due=_as_date(change.release_due_date),
                links=math_links, cal=cal),
            "deadlines": await ChangePlanService.deadlines(session, change),
        }

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------
    @staticmethod
    def _tdays(cal: eng.Calendar, calendar_days: int) -> int:
        """A template duration given in calendar days, in the plan's unit."""
        if not cal.working or calendar_days <= 0:
            return calendar_days
        return max(1, math.ceil(calendar_days * len(cal.workdays) / 7))

    @staticmethod
    def _lead_days(p: CostingPosition) -> tuple[Optional[int], Optional[str]]:
        """(calendar-day lead time, vendor) from ONE offer: Sales' chosen one,
        else the favourite, so the block's name and its length always speak
        about the same supplier."""
        offer = p.chosen_offer or p.favorite_offer
        vendor = offer.vendor_name if offer is not None else p.vendor_name
        if p.pricing == "quote" and offer is not None:
            dated = [o for o in p.counted_offers(offer)
                     if o.lead_time_days is not None]
            if dated:
                slowest = max(dated, key=lambda o: o.lead_time_calendar_days or 0)
                return slowest.lead_time_calendar_days, vendor
        return p.effective_lead_time_calendar_days, vendor

    @staticmethod
    async def _template(session: AsyncSession, change: ChangeRequest,
                        plan: str, user_id: int) -> list[ChangePlanTask]:
        """The quote plan template (spec §4) built from the costing.

        Every date is derived: the order lands a week after today or the
        quote deadline, whichever is later, and every other block hangs off
        it by its links, so the first Gantt Sales sees is already a plan and
        not a list of bars to drag into place."""
        cal = ChangePlanService.calendar(change, plan)
        names = await ChangePlanService._dept_names(session)
        ids_by_name = {n: i for i, n in names.items()}
        today = business_today()
        anchor = cal.snap(max(today, _as_date(change.required_by_date) or today)
                          + timedelta(days=ORDER_OFFSET_DAYS))

        tasks: list[ChangePlanTask] = []
        pending_links: list[tuple] = []
        td = ChangePlanService._tdays

        def add(name, kind, start, duration, *, lane=None, dept_id=None,
                preds=(), is_idea=False, source=None) -> ChangePlanTask:
            t = ChangePlanTask(
                change_id=change.id, plan=plan, name=(name or "")[:NAME_MAX],
                kind=kind, lane=lane, department_id=dept_id, is_idea=is_idea,
                start_date=cal.snap(start), duration_days=duration,
                predecessors=[], sort_order=len(tasks) + 1,
                progress_pct=0, source_position_id=source,
                created_by=user_id, updated_by=user_id)
            t._plan_cal = cal
            session.add(t)
            tasks.append(t)
            for p in preds:
                pending_links.append((p, t))
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
                days = (max(1, working) if cal.working
                        else max(1, math.ceil(working * 7 / 5)))
                dname = names.get(dept_id, f"Department {dept_id}")
                eng_by_dept[dept_id] = add(
                    f"{dname} engineering", "work", after(order), days,
                    lane=dname, dept_id=dept_id, preds=(order,))
            await flush()
            for p in positions:
                if p.kind != "external":
                    continue
                days, vendor = ChangePlanService._lead_days(p)
                if not days or days <= 0:
                    continue
                dname = names.get(p.department_id, f"Department {p.department_id}")
                pred = eng_by_dept.get(p.department_id) or order
                kind = "downtime" if dname == TOOL_DEPARTMENT else "supplier"
                t = add(p.label + (f" - {vendor}" if vendor else ""), kind,
                        after(pred), td(cal, int(days)), lane=dname,
                        dept_id=p.department_id, preds=(pred,), source=p.id)
                work_tail.append(t)
            await flush()
            if not work_tail:
                work_tail = list(eng_by_dept.values())

        if not work_tail:
            # No costing to plan from: one honest block that says "the work"
            # rather than an empty gap between the order and sampling.
            work_tail = [add("Implementation", "work", after(order),
                             td(cal, FALLBACK_IMPLEMENTATION_DAYS),
                             lane=TOOL_DEPARTMENT,
                             dept_id=ids_by_name.get(TOOL_DEPARTMENT),
                             preds=(order,))]
            await flush()

        downtimes = [t for t in work_tail if t.kind == "downtime"]
        if downtimes:
            first = min(t.start_date for t in downtimes)
            bank_days = td(cal, BANK_BUILD_DAYS)
            bank_start = (cal.date_at(cal.idx(first) - bank_days) if cal.working
                          else first - timedelta(days=BANK_BUILD_DAYS))
            add("Bank build (idea)", "bank_build", bank_start, bank_days,
                lane="Scheduling", dept_id=ids_by_name.get("Scheduling"),
                is_idea=True)

        sampling = add("Sampling / trial", "sampling", after(*work_tail),
                       td(cal, SAMPLING_DAYS), lane=TOOL_DEPARTMENT,
                       dept_id=ids_by_name.get(TOOL_DEPARTMENT), preds=work_tail)
        await flush()
        validation = add("Measurement and validation", "validation",
                         after(sampling), td(cal, VALIDATION_DAYS), lane="APQP",
                         dept_id=ids_by_name.get("APQP"), preds=(sampling,))
        await flush()
        approval = add("Customer approval (PPAP / ISIR)", "customer",
                       after(validation), td(cal, CUSTOMER_APPROVAL_DAYS),
                       lane="Customer", preds=(validation,))
        await flush()
        chain = cal.span(anchor, approval.end_date)
        buffer = add("Safety buffer", "buffer", after(approval),
                     max(td(cal, MIN_BUFFER_DAYS), math.ceil(chain * 0.10)),
                     lane="Project Manager",
                     dept_id=ids_by_name.get("Project Manager"),
                     preds=(approval,))
        await flush()
        add("Start of production (change)", "milestone", after(buffer), 0,
            lane="Customer", preds=(buffer,))
        await flush()
        for p, t in pending_links:
            session.add(ChangePlanLink(
                change_id=change.id, plan=plan, from_task_id=p.id,
                to_task_id=t.id, type="FS", lag_days=0, created_by=user_id))
        await flush()
        return tasks

    @staticmethod
    async def _clear(session, change, plan) -> None:
        for lk in await ChangePlanService.links(session, change, plan):
            await session.delete(lk)
        tasks = await ChangePlanService.tasks(session, change, plan)
        for t in tasks:
            t.parent_id = None
        await session.flush()
        for t in tasks:
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
        """Copy blocks into another plan, remapping ids in parents and links.
        Ideas stay ideas: whether the parallel bank build happens is decided
        on the detailed plan, not lost in the copy. The copy takes the
        source plan's calendar: the durations are in its units."""
        src_plan = source[0].plan if source else None
        cal = ChangePlanService.calendar(change, src_plan or plan)
        if src_plan and src_plan != plan:
            ChangePlanService._store_calendar(
                change, plan, cal, auto=ChangePlanService.auto(change, src_plan))
        id_map: dict[int, ChangePlanTask] = {}
        for t in source:
            n = ChangePlanTask(
                change_id=change.id, plan=plan, name=t.name, lane=t.lane,
                department_id=t.department_id, kind=t.kind, is_idea=t.is_idea,
                start_date=t.start_date, duration_days=t.duration_days,
                predecessors=[], sort_order=t.sort_order, progress_pct=0,
                constraint_type=t.constraint_type,
                constraint_date=t.constraint_date,
                source_position_id=t.source_position_id, notes=t.notes,
                created_by=user_id, updated_by=user_id)
            n._plan_cal = cal
            session.add(n)
            id_map[t.id] = n
        await session.flush()
        for t in source:
            if t.parent_id in id_map:
                id_map[t.id].parent_id = id_map[t.parent_id].id
        for lk in await ChangePlanService.links(session, change, src_plan):
            if lk.from_task_id in id_map and lk.to_task_id in id_map:
                session.add(ChangePlanLink(
                    change_id=change.id, plan=plan,
                    from_task_id=id_map[lk.from_task_id].id,
                    to_task_id=id_map[lk.to_task_id].id,
                    type=lk.type, lag_days=lk.lag_days, created_by=user_id))
        await session.flush()
        return list(id_map.values())

    # ------------------------------------------------------------------
    # Task writes
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise(t: ChangePlanTask, cal: Optional[eng.Calendar] = None) -> None:
        # A milestone is a moment: a duration on it is a typo, fixed silently
        # rather than reported (spec: milestone_duration normalised on write).
        if t.kind == "milestone":
            t.duration_days = 0
        # In working mode a block starts on a working day.
        if cal is not None and cal.working and t.start_date is not None:
            t.start_date = cal.snap(t.start_date)

    @staticmethod
    def _check_actuals(start: Optional[date], finish: Optional[date], *,
                       check=("actual_start", "actual_finish"),
                       name: Optional[str] = None) -> None:
        """Actual dates report what happened: not later than today (server
        date, one day of slack for a browser a timezone ahead), and a block
        does not finish before it started. `check`: the dates being written
        (a stored one is not refused again for being in the future)."""
        latest = business_today() + timedelta(days=1)
        of = f" of '{name}'" if name else ""
        for k, d in (("actual_start", start), ("actual_finish", finish)):
            if k in check and d is not None and d > latest:
                raise ChangeError(
                    f"The {k.replace('_', ' ')}{of} {fmt_date(d)} is in the "
                    "future: report it when it has happened")
        if start is not None and finish is not None and finish < start:
            raise ChangeError(
                f"The actual finish{of} {fmt_date(finish)} is before its "
                f"actual start {fmt_date(start)}")

    @staticmethod
    async def _check_fields(session, spec: dict, plan_ids: set,
                            own_id: Optional[int],
                            current: Optional[ChangePlanTask] = None) -> None:
        """`current`: the block being edited, whose stored actual dates
        count where the spec leaves one of them out."""
        if "name" in spec:
            name = (spec["name"] or "").strip()
            if not name:
                raise ChangeError("A block needs a name")
            if len(name) > NAME_MAX:
                raise ChangeError(f"A block name has at most {NAME_MAX} characters")
        if "kind" in spec and spec["kind"] not in TASK_KINDS:
            raise ChangeError(f"Unknown block kind '{spec['kind']}'")
        if "duration_days" in spec:
            if spec["duration_days"] is None or int(spec["duration_days"]) < 0:
                raise ChangeError("Duration must be zero or more days")
            if int(spec["duration_days"]) > eng.MAX_DURATION_DAYS:
                raise ChangeError(
                    f"Duration is at most {eng.MAX_DURATION_DAYS} days")
        if "start_date" in spec and spec["start_date"] is None:
            raise ChangeError("A block needs a start date")
        if "sort_order" in spec and spec["sort_order"] is None:
            raise ChangeError("The sort order is a number")
        for k in ("start_date", "constraint_date", "actual_start", "actual_finish"):
            d = _as_date(spec.get(k))
            if d is not None and not eng.MIN_YEAR <= d.year <= eng.MAX_YEAR:
                raise ChangeError(
                    f"Dates lie between {eng.MIN_YEAR} and {eng.MAX_YEAR}")
        # Actual dates report what happened: not later than today (server
        # date, one day of slack for a browser a timezone ahead).
        ChangePlanService._check_actuals(
            _as_date(spec["actual_start"]) if "actual_start" in spec
            else getattr(current, "actual_start", None),
            _as_date(spec["actual_finish"]) if "actual_finish" in spec
            else getattr(current, "actual_finish", None),
            check=[k for k in ("actual_start", "actual_finish") if k in spec])
        if "predecessors" in spec:
            for p in spec["predecessors"] or []:
                if own_id is not None and p == own_id:
                    raise ChangeError("A block cannot depend on itself")
                if p not in plan_ids:
                    raise ChangeError(f"Predecessor {p} is not a block of this plan")
        if spec.get("parent_id") is not None:
            if own_id is not None and spec["parent_id"] == own_id:
                raise ChangeError("A block cannot sit under itself")
            if spec["parent_id"] not in plan_ids:
                raise ChangeError(
                    f"Parent {spec['parent_id']} is not a block of this plan")
        if "constraint_type" in spec:
            ct = spec["constraint_type"]
            if ct is not None and ct not in CONSTRAINT_TYPES:
                raise ChangeError(
                    f"Unknown constraint '{ct}' - one of {', '.join(CONSTRAINT_TYPES)}")
        if "progress_pct" in spec:
            v = spec["progress_pct"]
            if v is None or not 0 <= int(v) <= 100:
                raise ChangeError("Progress must be between 0 and 100")
        if spec.get("department_id") is not None:
            if await session.get(Department, spec["department_id"]) is None:
                raise ChangeError(
                    f"Department {spec['department_id']} does not exist")

    @staticmethod
    def _check_parent(by_id: dict, tid: int, parent_id: Optional[int]) -> None:
        """A block cannot move under one of its own descendants."""
        p = parent_id
        seen = set()
        while p is not None and p not in seen:
            if p == tid:
                raise ChangeError("A block cannot sit under one of its own sub-blocks")
            seen.add(p)
            p = by_id[p].parent_id if p in by_id else None

    @staticmethod
    def _set_constraint(t: ChangePlanTask, spec: dict) -> None:
        if "constraint_type" not in spec and "constraint_date" not in spec:
            return
        ct = spec.get("constraint_type", t.constraint_type)
        cd = spec.get("constraint_date", t.constraint_date)
        if ct in (None, "asap"):
            t.constraint_type, t.constraint_date = None, None
            return
        if cd is None:
            raise ChangeError(f"The constraint '{ct}' needs a date")
        t.constraint_type, t.constraint_date = ct, _as_date(cd)

    @staticmethod
    def _structure_issues(tasks: list, links: list) -> set:
        """MS Project's rules for summaries and the outline depth, as
        (code, task id): summary_pin (mso/mfo on a summary),
        summary_finish_link (FF/SF into a summary), depth (deeper than
        MAX_OUTLINE_DEPTH levels)."""
        by_id = {t.id: t for t in tasks}
        summaries = {t.parent_id for t in tasks if t.parent_id in by_id}
        out = set()
        for sid in summaries:
            if by_id[sid].constraint_type in eng.PIN_CONSTRAINTS:
                out.add(("summary_pin", sid))
            if getattr(by_id[sid], "is_idea", False):
                out.add(("summary_idea", sid))
        for lk in links:
            if lk.to_task_id in summaries and lk.type in eng.FINISH_TARGET_LINKS:
                out.add(("summary_finish_link", lk.to_task_id))
        for t in tasks:
            depth, p, seen = 1, t.parent_id, {t.id}
            while p in by_id and p not in seen:
                seen.add(p)
                depth += 1
                p = by_id[p].parent_id
            if depth > eng.MAX_OUTLINE_DEPTH:
                out.add(("depth", t.id))
        return out

    @staticmethod
    def _check_structure(before: set, tasks: list, links: list) -> None:
        """Refuse an edit that breaks a summary rule or the depth cap (old
        data already breaking one does not block unrelated edits)."""
        new = ChangePlanService._structure_issues(tasks, links) - before
        if not new:
            return
        by_id = {t.id: t for t in tasks}
        code, tid = sorted(new, key=lambda x: (x[0], str(x[1])))[0]
        name = by_id[tid].name if tid in by_id else str(tid)
        if code == "summary_pin":
            raise ChangeError(
                f"'{name}' is a summary block: it cannot have a must-start-on or "
                "must-finish-on constraint (its dates follow the blocks under "
                "it); remove the constraint or put it on a block under it")
        if code == "summary_idea":
            raise PlanRuleError(
                f"'{name}' has blocks under it: a summary cannot be an idea "
                "(mark the blocks under it as ideas instead), and an idea "
                "cannot hold blocks", "summary_idea")
        if code == "summary_finish_link":
            raise ChangeError(
                f"'{name}' is a summary block: a finish-to-finish or "
                "start-to-finish link into it is not allowed; link to a block "
                "under it")
        raise ChangeError(
            f"'{name}' would sit deeper than {eng.MAX_OUTLINE_DEPTH} outline levels")

    @staticmethod
    async def _bump(change: ChangeRequest, plan: str) -> None:
        """Every edit of the detailed plan before its baseline invalidates the
        teams' confirmations: they confirmed a plan that no longer exists."""
        if plan == "detailed" and change.timing_validated_at is None:
            change.plan_revision = int(change.plan_revision or 0) + 1

    @staticmethod
    async def _set_preds(session, change, plan, task_id: int, pred_ids: list,
                         links: list, user_id: int, by_id: dict) -> None:
        """Legacy `predecessors` write: the block's FS links become exactly
        these (existing lags kept); SS/FF/SF links are left alone. A new
        link passes the same checks as any link (no self link, no second
        link between two blocks, whatever its direction)."""
        want = []
        for p in pred_ids or []:
            if p not in want:
                want.append(p)
        for lk in list(links):
            if lk.to_task_id == task_id and lk.type == "FS" \
                    and lk.from_task_id not in want:
                links.remove(lk)
                await session.delete(lk)
        await session.flush()               # deletes before inserts (unique pair)
        have = {lk.from_task_id for lk in links if lk.to_task_id == task_id}
        for p in want:
            if p in have:
                continue
            ChangePlanService._check_link(by_id, links, p, task_id, "FS", 0)
            lk = ChangePlanLink(change_id=change.id, plan=plan, from_task_id=p,
                                to_task_id=task_id, type="FS", lag_days=0,
                                created_by=user_id)
            session.add(lk)
            links.append(lk)
        await ChangePlanService._flush_links(session)

    @staticmethod
    async def _rollup(session, change, plan) -> None:
        """Summary blocks carry the span of their children, stored so every
        reader (exports, offer, deviations) sees consistent dates."""
        await session.flush()
        tasks = await ChangePlanService.tasks(session, change, plan)
        summaries = eng.summary_ids(e_tasks(tasks))
        if not summaries:
            return
        cal = ChangePlanService.calendar(change, plan)
        res = eng.analyse(e_tasks(tasks), [], cal)
        by_id = {t.id: t for t in tasks}
        for sid in summaries:
            r = res.tasks[sid]
            t = by_id[sid]
            t.start_date = r.start
            t.duration_days = max(0, r.end_idx - r.start_idx)
        await session.flush()

    @staticmethod
    def _new_task(change, plan, spec: dict, sort_order: int, user_id: int,
                  cal: eng.Calendar) -> ChangePlanTask:
        t = ChangePlanTask(
            change_id=change.id, plan=plan, name=spec["name"].strip(),
            kind=spec.get("kind") or "work", lane=spec.get("lane"),
            department_id=spec.get("department_id"),
            is_idea=bool(spec.get("is_idea") or False),
            start_date=_as_date(spec["start_date"]),
            duration_days=int(spec.get("duration_days") or 0),
            predecessors=[], sort_order=spec.get("sort_order") or sort_order,
            progress_pct=0, notes=spec.get("notes"),
            source_position_id=spec.get("source_position_id"),
            created_by=user_id, updated_by=user_id)
        t._plan_cal = cal
        ChangePlanService._set_constraint(t, spec)
        ChangePlanService._normalise(t, cal)
        return t

    @staticmethod
    async def add_task(session: AsyncSession, change: ChangeRequest,
                       plan: str, spec: dict, user: User) -> ChangePlanTask:
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=True)
        cal = ChangePlanService.calendar(change, plan)
        links = await ChangePlanService.links(session, change, plan)
        existing = await ChangePlanService.tasks(session, change, plan)
        spec = {k: v for k, v in spec.items() if k in WRITABLE_FIELDS}
        spec.setdefault("kind", "work")
        spec.setdefault("duration_days", 0)
        for required in ("name", "start_date"):
            if spec.get(required) in (None, ""):
                raise ChangeError(f"'{required}' is required")
        await ChangePlanService._check_fields(
            session, spec, {t.id for t in existing}, None)
        before = ChangePlanService._structure_issues(existing, links)
        t = ChangePlanService._new_task(
            change, plan, spec,
            max((x.sort_order for x in existing), default=0) + 1, user.id, cal)
        t.parent_id = spec.get("parent_id")
        session.add(t)
        await session.flush()
        if spec.get("predecessors"):
            await ChangePlanService._set_preds(
                session, change, plan, t.id, spec["predecessors"], links, user.id,
                {x.id: x for x in existing + [t]})
        ChangePlanService._check_structure(before, existing + [t], links)
        if spec.get("predecessors") or spec.get("constraint_type") \
                or spec.get("parent_id"):
            await ChangePlanService._auto_push(
                change, plan, existing + [t], links, [], [t.id], user)
        await ChangePlanService._rollup(session, change, plan)
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
        t._plan_cal = ChangePlanService.calendar(change, t.plan)
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
    def _apply_fields(t: ChangePlanTask, spec: dict, user_id: int) -> None:
        """Every non-date, non-link field of a (checked) spec."""
        for k, v in spec.items():
            if k in DATE_FIELDS or k in ("predecessors", "constraint_type",
                                         "constraint_date"):
                continue
            if k == "name":
                v = v.strip()
            if k == "is_idea":
                v = bool(v)
            setattr(t, k, v)
        ChangePlanService._set_constraint(t, spec)
        t.updated_by = user_id

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
        by_id = {t.id: t for t in siblings}
        await ChangePlanService._check_fields(
            session, spec, set(by_id), task.id, task)
        if "parent_id" in spec:
            ChangePlanService._check_parent(by_id, task.id, spec["parent_id"])
        summaries = eng.summary_ids(e_tasks(siblings))
        if task.id in summaries and any(k in DATE_FIELDS for k in spec):
            raise ChangeError(
                "A summary block's dates come from the blocks under it")
        links = await ChangePlanService.links(session, change, plan)
        before_issues = ChangePlanService._structure_issues(siblings, links)

        date_spec = {k: spec.pop(k) for k in DATE_FIELDS if k in spec}
        before = {k: getattr(task, k) for k in spec if k != "predecessors"}
        ChangePlanService._apply_fields(task, spec, user.id)
        if "predecessors" in spec:
            before["predecessors"] = [lk.from_task_id for lk in links
                                      if lk.to_task_id == task.id and lk.type == "FS"]
            await ChangePlanService._set_preds(
                session, change, plan, task.id, spec["predecessors"] or [],
                links, user.id, by_id)
        ChangePlanService._normalise(task)
        ChangePlanService._check_structure(before_issues, siblings, links)

        moved = []
        if date_spec:
            moved = await ChangePlanService._apply_dates(
                session, change, plan, siblings,
                {task.id: date_spec}, user, reason=reason, bump=False)
        relinked = any(k in spec for k in ("predecessors", "constraint_type",
                                           "constraint_date", "parent_id"))
        pushed = [x for x in await ChangePlanService._auto_push(
            change, plan, siblings, links, moved, [task.id] if relinked else [],
            user) if x != task.id]
        moved = list(dict.fromkeys(moved + pushed))
        await ChangePlanService._rollup(session, change, plan)
        if (spec and not progress_only) or moved:
            await ChangePlanService._bump(change, plan)
        if spec or moved:
            fields = sorted(list(spec) + list(date_spec))
            names = {t.id: t.name for t in siblings}
            await ChangeService.append_changelog(
                session, change, "plan_task_updated",
                f"{plan.capitalize()} plan: block '{task.name}' updated "
                f"({', '.join(fields)})"
                + (f"; pushed along its links: "
                   f"{', '.join(repr(names[x]) for x in pushed)}" if pushed else ""),
                user.id,
                old_value={k: _json(v) for k, v in before.items()} or None,
                new_value={"plan": plan, "task_id": task.id,
                           **{k: _json(getattr(task, k)) for k in fields
                              if k != "predecessors"},
                           "pushed_ids": pushed})
        return task

    @staticmethod
    async def bulk_update(session: AsyncSession, change: ChangeRequest,
                          plan: str, updates: list[dict], user: User,
                          *, reason: Optional[str] = None) -> None:
        """Block move / resize of a selection: one call, one changelog entry,
        and after the baseline one deviation per task with the same reason.
        Summary blocks in the selection are skipped: their dates follow."""
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=False)
        siblings = await ChangePlanService.tasks(session, change, plan)
        by_id = {t.id: t for t in siblings}
        summaries = eng.summary_ids(e_tasks(siblings))
        changes: dict[int, dict] = {}
        for u in updates:
            tid = u.get("id")
            if tid not in by_id:
                raise ChangeError(f"Block {tid} is not part of the {plan} plan")
            if tid in summaries:
                continue
            d = {k: u[k] for k in DATE_FIELDS if u.get(k) is not None}
            await ChangePlanService._check_fields(session, d, set(by_id), tid)
            if d:
                changes[tid] = d
        if not changes:
            raise ChangeError("Nothing to update")
        moved = await ChangePlanService._apply_dates(
            session, change, plan, siblings, changes, user, reason=reason)
        moved = list(dict.fromkeys(moved + await ChangePlanService._auto_push(
            change, plan, siblings, await ChangePlanService.links(session, change, plan),
            moved, [], user)))
        await ChangePlanService._rollup(session, change, plan)
        await ChangeService.append_changelog(
            session, change, "plan_task_updated",
            f"{plan.capitalize()} plan: {len(moved)} block(s) moved", user.id,
            new_value={"plan": plan, "task_ids": moved})

    @staticmethod
    def _record_moved(change, ids) -> None:
        """Blocks the server moved by itself in this request (automatic
        push, cascade, schedule): the routes answer them as `moved_ids`."""
        got = getattr(change, "_plan_moved_ids", None)
        if got is None:
            got = []
            change._plan_moved_ids = got
        for i in ids:
            if i not in got:
                got.append(i)

    @staticmethod
    def take_moved(change, exclude=()) -> list[int]:
        """The blocks the server moved in this request, minus those the
        client sent; resets the record."""
        got = getattr(change, "_plan_moved_ids", None) or []
        change._plan_moved_ids = []
        skip = set(exclude)
        return [i for i in got if i not in skip]

    @staticmethod
    async def _auto_push(change, plan, tasks: list, links: list, sources,
                         also, user: User) -> list[int]:
        """Automatic scheduling before the baseline: what the edit drives
        moves along its links (later only; pinned and started blocks stay),
        the same forward pass the Gantt runs, so an API client gets the plan
        the UI shows. No deviations: nothing was promised yet. After the
        baseline _apply_dates cascades (with deviations) instead."""
        sources, also = list(dict.fromkeys(sources)), list(dict.fromkeys(also))
        if (not sources and not also) or ChangePlanService.baselined(change, plan) \
                or not ChangePlanService.auto(change, plan):
            return []
        cal = ChangePlanService.calendar(change, plan)
        res, _cause = eng.push(e_tasks(tasks), e_links(links), cal, sources,
                               also=also)
        by_id = {t.id: t for t in tasks}
        moved = []
        for tid in res.moved:
            t = by_id[tid]
            if t.start_date != res.tasks[tid].start:
                t.start_date = res.tasks[tid].start
                t.updated_by = user.id
                moved.append(tid)
        ChangePlanService._record_moved(change, moved)
        return moved

    @staticmethod
    async def _apply_dates(session, change, plan, siblings: list,
                           changes: dict[int, dict], user: User,
                           *, reason: Optional[str], bump: bool = True) -> list[int]:
        """Apply start/duration edits. Before the baseline this is simply an
        edit (and bumps the revision). After it every changed block becomes a
        deviation: old and new dates, slip against its baseline end, and what
        the move did to the finish of the whole plan. After the baseline a
        move also pushes its successors along their links (a forward pass
        over what the moved blocks drive, never earlier, pinned blocks
        stay): each pushed block gets its own deviation with the same reason
        and the block that caused it. Returns every moved block."""
        cal = ChangePlanService.calendar(change, plan)
        by_id = {t.id: t for t in siblings}
        baselined = ChangePlanService.baselined(change, plan)
        reason = (reason or "").strip()
        if baselined and not reason:
            raise ChangeError(
                "Timing was validated: a reason is required to move a date")
        summaries = eng.summary_ids(e_tasks(siblings))
        finish_before = plan_finish([t for t in siblings if t.id not in summaries])
        olds: dict[int, tuple] = {}
        moved = []
        for tid, d in changes.items():
            t = by_id[tid]
            old = (t.start_date, t.end_date)
            if "start_date" in d:
                t.start_date = _as_date(d["start_date"])
            if "duration_days" in d:
                t.duration_days = int(d["duration_days"])
            ChangePlanService._normalise(t, cal)
            t.updated_by = user.id
            if (t.start_date, t.end_date) != old:
                olds[tid] = old
                moved.append(tid)
        if not moved:
            return []
        if not baselined:
            if bump:
                await ChangePlanService._bump(change, plan)
            return moved
        links = await ChangePlanService.links(session, change, plan)
        res, cause = eng.cascade(e_tasks(siblings), e_links(links), cal, moved)
        caused: dict[int, int] = {}
        for tid in res.moved:
            t = by_id[tid]
            old = (t.start_date, t.end_date)
            t.start_date = res.tasks[tid].start
            t.updated_by = user.id
            if (t.start_date, t.end_date) != old and tid not in olds:
                olds[tid] = old
                caused[tid] = cause[tid]
            # a block the user moved AND its moved predecessor pushed keeps
            # its one deviation (old dates from before the edit)
        pushed = [t.id for t in siblings if t.id in caused]   # outline order
        ChangePlanService._record_moved(change, pushed)
        finish_after = plan_finish([t for t in siblings if t.id not in summaries])
        impact = ((finish_after - finish_before).days
                  if finish_after and finish_before else 0)
        group = await ChangePlanService._new_group(
            session, change, moved[0], reason, user)
        devs = []
        for tid in moved + pushed:
            t = by_id[tid]
            base_end = t.baseline_finish or olds[tid][1]
            dev = ChangePlanDeviation(
                change_id=change.id, task_id=tid, group_id=group.id,
                caused_by_task_id=caused.get(tid),
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
            f"Plan deviation on {len(devs)} block(s)"
            + (f" ({len(pushed)} pushed by their links)" if pushed else "")
            + f", finish impact {impact:+d} days: {reason}", user.id, notes=reason,
            new_value={"deviation_ids": [d.id for d in devs],
                       "group_id": group.id,
                       "task_ids": moved + pushed, "pushed_ids": pushed,
                       "finish_impact_days": impact})
        return moved + pushed

    @staticmethod
    async def _remove_task(session, change, plan, task: ChangePlanTask,
                           tasks: list, links: list) -> None:
        """Drop a block, its links, and hang its children on its parent."""
        for lk in list(links):
            if task.id in (lk.from_task_id, lk.to_task_id):
                links.remove(lk)
                await session.delete(lk)
        for t in tasks:
            if t.parent_id == task.id:
                t.parent_id = task.parent_id
        await session.flush()
        await session.delete(task)
        await session.flush()

    @staticmethod
    async def delete_task(session: AsyncSession, change: ChangeRequest,
                          tid: int, user: User) -> None:
        task = await ChangePlanService._get_task(session, change, tid)
        await ChangePlanService._require_edit(
            session, change, task.plan, user, structural=True)
        tasks = await ChangePlanService.tasks(session, change, task.plan)
        links = await ChangePlanService.links(session, change, task.plan)
        gone = {"plan": task.plan, "task_id": task.id, "name": task.name}
        await ChangePlanService._remove_task(
            session, change, task.plan, task, tasks, links)
        await ChangePlanService._rollup(session, change, gone["plan"])
        await ChangePlanService._bump(change, gone["plan"])
        await ChangeService.append_changelog(
            session, change, "plan_task_removed",
            f"{gone['plan'].capitalize()} plan: block '{gone['name']}' removed",
            user.id, old_value=gone)

    @staticmethod
    async def schedule(session: AsyncSession, change: ChangeRequest,
                       plan: str, user: User,
                       *, reason: Optional[str] = None) -> list[int]:
        """Forward pass over every link type, lag and constraint: blocks move
        later when a link or constraint needs it, never earlier (only a
        must-start-on / must-finish-on pins a block to its date). Slack
        somebody left on purpose is not the tool's to take. After the
        baseline it needs a reason and every moved block is a deviation."""
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=False)
        baselined = ChangePlanService.baselined(change, plan)
        if baselined and not (reason or "").strip():
            raise ChangeError(
                "Timing was validated: a reason is required to schedule the plan")
        cal = ChangePlanService.calendar(change, plan)
        links = await ChangePlanService.links(session, change, plan)
        tasks = await ChangePlanService.tasks(session, change, plan)
        res = eng.schedule(e_tasks(tasks), e_links(links), cal)
        if res.cycle:
            raise ChangeError("The dependencies form a loop - fix it before scheduling")
        by_id = {t.id: t for t in tasks}
        if baselined:
            moved = await ChangePlanService._apply_dates(
                session, change, plan, tasks,
                {tid: {"start_date": res.tasks[tid].start} for tid in res.moved},
                user, reason=reason)
            ChangePlanService._record_moved(change, moved)
            await ChangePlanService._rollup(session, change, plan)
            return moved
        moved = []
        for tid in res.moved:
            t = by_id[tid]
            t.start_date = res.tasks[tid].start
            t.updated_by = user.id
            moved.append(tid)
        ChangePlanService._record_moved(change, moved)
        await ChangePlanService._rollup(session, change, plan)
        if moved:
            await ChangePlanService._bump(change, plan)
            await ChangeService.append_changelog(
                session, change, "plan_task_updated",
                f"{plan.capitalize()} plan scheduled: {len(moved)} block(s) "
                "moved by their links and constraints", user.id,
                new_value={"plan": plan, "task_ids": moved, "scheduled": True})
        return moved

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------
    @staticmethod
    def _check_link(by_id: dict, links: list, frm, to, typ: str, lag,
                    own_id: Optional[int] = None) -> None:
        if frm not in by_id or to not in by_id:
            raise ChangeError("Both ends of a link must be blocks of the same plan")
        if frm == to:
            raise ChangeError("A block cannot depend on itself")
        if typ not in LINK_TYPES:
            raise ChangeError(f"Unknown link type '{typ}' - one of FS, SS, FF, SF")
        try:
            lag = int(lag or 0)
        except (TypeError, ValueError):
            raise ChangeError("The lag must be a whole number of days")
        if abs(lag) > eng.MAX_LAG_DAYS:
            raise ChangeError(f"A lag is at most {eng.MAX_LAG_DAYS} days either way")
        if typ in eng.FINISH_TARGET_LINKS and any(
                t.parent_id == to for t in by_id.values()):
            raise ChangeError(
                f"'{by_id[to].name}' is a summary block: a {typ} link into it is "
                "not allowed (MS Project refuses it); link to a block under it")
        for lk in links:
            if lk.id != own_id and lk is not own_id and \
                    {lk.from_task_id, lk.to_task_id} == {frm, to}:
                raise ChangeError("These two blocks are already linked")

    @staticmethod
    async def _get_link(session, change, lid: int) -> ChangePlanLink:
        lk = await session.get(ChangePlanLink, lid)
        if lk is None or lk.change_id != change.id:
            raise PlanConflict("Plan link not found on this change", not_found=True)
        return lk

    @staticmethod
    async def add_link(session: AsyncSession, change: ChangeRequest, plan: str,
                       spec: dict, user: User) -> ChangePlanLink:
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=True)
        tasks = await ChangePlanService.tasks(session, change, plan)
        links = await ChangePlanService.links(session, change, plan)
        by_id = {t.id: t for t in tasks}
        typ = (spec.get("type") or "FS").upper()
        lag = int(spec.get("lag_days") or 0)
        ChangePlanService._check_link(by_id, links, spec.get("from_task_id"),
                                      spec.get("to_task_id"), typ, lag)
        lk = ChangePlanLink(change_id=change.id, plan=plan,
                            from_task_id=spec["from_task_id"],
                            to_task_id=spec["to_task_id"], type=typ,
                            lag_days=lag, created_by=user.id)
        session.add(lk)
        await ChangePlanService._flush_links(session)
        links.append(lk)
        await ChangePlanService._auto_push(change, plan, tasks, links, [],
                                           [lk.to_task_id], user)
        await ChangePlanService._rollup(session, change, plan)
        await ChangePlanService._bump(change, plan)
        await ChangeService.append_changelog(
            session, change, "plan_link_added",
            f"{plan.capitalize()} plan: '{by_id[lk.from_task_id].name}' -> "
            f"'{by_id[lk.to_task_id].name}' ({typ}{lag:+d}d)", user.id,
            new_value={"plan": plan, **ChangePlanService.link_out(lk)})
        return lk

    @staticmethod
    async def update_link(session: AsyncSession, change: ChangeRequest, lid: int,
                          spec: dict, user: User) -> ChangePlanLink:
        lk = await ChangePlanService._get_link(session, change, lid)
        await ChangePlanService._require_edit(
            session, change, lk.plan, user, structural=True)
        tasks = await ChangePlanService.tasks(session, change, lk.plan)
        links = await ChangePlanService.links(session, change, lk.plan)
        by_id = {t.id: t for t in tasks}
        before = ChangePlanService.link_out(lk)
        typ = (spec.get("type") or lk.type).upper()
        lag = int(spec["lag_days"]) if spec.get("lag_days") is not None \
            else int(lk.lag_days or 0)
        ChangePlanService._check_link(by_id, links, lk.from_task_id,
                                      lk.to_task_id, typ, lag, own_id=lk.id)
        lk.type, lk.lag_days = typ, lag
        await session.flush()
        await ChangePlanService._auto_push(change, lk.plan, tasks, links, [],
                                           [lk.to_task_id], user)
        await ChangePlanService._rollup(session, change, lk.plan)
        await ChangePlanService._bump(change, lk.plan)
        await ChangeService.append_changelog(
            session, change, "plan_link_updated",
            f"{lk.plan.capitalize()} plan: link '{by_id[lk.from_task_id].name}' "
            f"-> '{by_id[lk.to_task_id].name}' now {typ}{lag:+d}d", user.id,
            old_value=before,
            new_value={"plan": lk.plan, **ChangePlanService.link_out(lk)})
        return lk

    @staticmethod
    async def delete_link(session: AsyncSession, change: ChangeRequest, lid: int,
                          user: User) -> str:
        lk = await ChangePlanService._get_link(session, change, lid)
        plan = lk.plan
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=True)
        gone = {"plan": plan, **ChangePlanService.link_out(lk)}
        await session.delete(lk)
        await session.flush()
        await ChangePlanService._bump(change, plan)
        await ChangeService.append_changelog(
            session, change, "plan_link_removed",
            f"{plan.capitalize()} plan: link removed", user.id, old_value=gone)
        return plan

    # ------------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------------
    @staticmethod
    async def set_calendar(session: AsyncSession, change: ChangeRequest,
                           spec: dict, user: User, plan: str = "quote") -> None:
        """The calendar of ONE plan. Durations keep their numbers and are
        read in the new unit, so every end date of that plan may move: only
        inside the plan's edit window, and refused on the detailed plan once
        timing is validated (the baseline is in the old unit). The other
        plan keeps its calendar, so a frozen quote plan never moves."""
        ChangePlanService._check_plan(plan)
        if not await ChangePlanService.is_editor(session, change, user):
            raise PlanForbidden(
                "Only Sales, Project Management, Scheduling, the change lead "
                "or an admin may edit the plan")
        ChangePlanService._require_window(
            change, plan, f"The {plan} plan calendar")
        if ChangePlanService.baselined(change, plan):
            raise ChangeError(
                "Timing was validated: the plan calendar is frozen with the baseline")
        before = ChangePlanService._calendars(change).get(plan)
        old = ChangePlanService.calendar(change, plan)
        if set(spec) <= {"auto", "convert"}:
            # the automatic scheduling switch alone: nothing moves, the
            # plan is the same plan (no revision bump); nothing at all (or
            # only `convert`) is a no-op
            if spec.get("auto") is None or \
                    bool(spec["auto"]) == ChangePlanService.auto(change, plan):
                return
            ChangePlanService._store_calendar(change, plan, old, auto=spec["auto"])
            await session.flush()
            await ChangeService.append_changelog(
                session, change, "plan_calendar",
                f"{plan.capitalize()} plan: automatic scheduling "
                + ("on" if spec["auto"] else "off"), user.id,
                old_value=before,
                new_value={"plan": plan, **ChangePlanService.calendar_out(change, plan)})
            return
        # fields left out keep the plan's current calendar
        mode = spec.get("mode") or old.mode
        if mode not in eng.CALENDAR_MODES:
            raise ChangeError("The calendar mode is 'calendar' or 'working'")
        workdays = spec.get("workdays")
        workdays = old.workdays if workdays is None else workdays
        try:
            workdays = sorted({int(d) for d in workdays})
        except (TypeError, ValueError):
            raise ChangeError("Workdays are numbers 1 (Monday) to 7 (Sunday)")
        if any(d < 1 or d > 7 for d in workdays):
            raise ChangeError("Workdays are numbers 1 (Monday) to 7 (Sunday)")
        if mode == "working" and not workdays:
            raise ChangeError("A working calendar needs at least one workday")
        try:
            holidays = sorted({_as_date(h) for h in (
                spec["holidays"] if spec.get("holidays") is not None
                else old.holidays)})
        except ValueError:
            raise ChangeError("Holidays are dates (YYYY-MM-DD)")
        if any(not eng.MIN_YEAR <= h.year <= eng.MAX_YEAR for h in holidays):
            raise ChangeError(
                f"Holidays lie between {eng.MIN_YEAR} and {eng.MAX_YEAR}")
        if len(holidays) > eng.MAX_HOLIDAYS:
            raise ChangeError(f"At most {eng.MAX_HOLIDAYS} holidays")
        cal = eng.Calendar(mode, workdays, holidays)
        auto = spec.get("auto")
        if cal.to_json() == old.to_json():
            # the same calendar again: only the switch (if sent) can change
            if auto is None or bool(auto) == ChangePlanService.auto(change, plan):
                return
            return await ChangePlanService.set_calendar(
                session, change, {"auto": auto}, user, plan=plan)
        ChangePlanService._store_calendar(change, plan, cal, auto=auto)
        tasks = await ChangePlanService.tasks(session, change, plan)
        links = await ChangePlanService.links(session, change, plan)
        converted = 0
        if spec.get("convert") and old.working != cal.working:
            # keep the real length, rounded half up both ways so a round
            # trip does not inflate: calendar -> working d * n / 7, working
            # -> calendar d * 7 / n (n = working days a week)
            n = len(cal.workdays if cal.working else old.workdays) or 5
            num, den = (n, 7) if cal.working else (7, n)

            def conv(d: int, cap: int, what: str) -> int:
                d = int(d or 0)
                v = math.floor(abs(d) * num / den + 0.5)
                if v > cap:
                    raise ChangeError(
                        f"Converted, a {what} would be {v} days, more than {cap}")
                return (1 if d >= 0 else -1) * v
            summaries = eng.summary_ids(e_tasks(tasks))
            for t in tasks:
                if t.id not in summaries and int(t.duration_days or 0) > 0:
                    # real work stays real work (never a milestone)
                    t.duration_days = max(1, conv(t.duration_days,
                                                  eng.MAX_DURATION_DAYS, "duration"))
                    converted += 1
            for lk in links:
                if lk.lag_days:
                    lk.lag_days = conv(lk.lag_days, eng.MAX_LAG_DAYS, "lag")
        for t in tasks:
            ChangePlanService._normalise(t, cal)
        pushed = []
        if tasks and ChangePlanService.auto(change, plan):
            # snapping and converting may break links: automatic scheduling
            # repairs them (later only; pinned and started blocks stay)
            ets = e_tasks(tasks)
            cons = eng._constraints(ets)
            free = [x.id for x in ets
                    if eng._pin(cons.get(x.id, []), cal, 0) is None]
            pushed = await ChangePlanService._auto_push(
                change, plan, tasks, links, [], free, user)
        await ChangePlanService._rollup(session, change, plan)
        if tasks:
            await ChangePlanService._bump(change, plan)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "plan_calendar",
            f"{plan.capitalize()} plan calendar set to {mode} days"
            + (f" ({len(holidays)} holidays)" if holidays else "")
            + (f", {converted} durations converted" if converted else "")
            + (f", {len(pushed)} block(s) rescheduled" if pushed else ""), user.id,
            old_value=before,
            new_value={"plan": plan, **ChangePlanService.calendar_out(change, plan),
                       "converted": bool(spec.get("convert")), "pushed_ids": pushed})

    # ------------------------------------------------------------------
    # Batch (one Gantt ChangeSet per user action)
    # ------------------------------------------------------------------
    @staticmethod
    async def apply_changes(session: AsyncSession, change: ChangeRequest,
                            plan: str, changes: dict, user: User,
                            *, reason: Optional[str] = None) -> dict:
        """Apply a whole ChangeSet atomically (the router commits only when
        this returns). New blocks and links may carry client temp ids (any
        string, e.g. "tmp-3") that other entries of the same set reference.
        Returns {"id_map": {temp: id}, "link_id_map": {temp: id}}."""
        ChangePlanService._check_plan(plan)
        ups = list(changes.get("tasks_upsert") or [])
        dels = list(changes.get("tasks_delete") or [])
        lups = list(changes.get("links_upsert") or [])
        ldels = list(changes.get("links_delete") or [])
        if not (ups or dels or lups or ldels):
            raise ChangeError("Nothing to change")
        cal = ChangePlanService.calendar(change, plan)
        links = await ChangePlanService.links(session, change, plan)
        tasks = await ChangePlanService.tasks(session, change, plan)
        by_id = {t.id: t for t in tasks}
        link_by_id = {lk.id: lk for lk in links}
        before_issues = ChangePlanService._structure_issues(tasks, links)

        def is_existing(v) -> bool:
            return isinstance(v, int) and not isinstance(v, bool) and v in by_id

        def fields(u):
            return {k: v for k, v in u.items() if k in WRITABLE_FIELDS}

        for u in ups:
            tid = u.get("id")
            if isinstance(tid, int) and not isinstance(tid, bool) and tid not in by_id:
                raise PlanConflict(f"Plan block {tid} not found on this plan",
                                   not_found=True)
        creates = [u for u in ups if not is_existing(u.get("id"))]
        # An entry naming an existing block and no field is a no-op.
        updates = [u for u in ups if is_existing(u.get("id")) and fields(u)]
        for what, items in (("block", creates), ("link", [
                x for x in lups if not (isinstance(x.get("id"), int)
                                        and not isinstance(x.get("id"), bool))])):
            temp = [str(x["id"]) for x in items if x.get("id") is not None]
            dup = sorted({x for x in temp if temp.count(x) > 1})
            if dup:
                raise ChangeError(
                    f"The temporary {what} id {dup[0]} is used twice in one change set")
        if not (creates or updates or dels or lups or ldels):
            return {"id_map": {}, "link_id_map": {}}
        progress_only = (not creates and not dels and not lups and not ldels
                         and all(all(k in PROGRESS_FIELDS for k in fields(u))
                                 for u in updates))
        if progress_only:
            for u in updates:
                if not await ChangePlanService._may_progress(
                        session, change, by_id[u["id"]], user):
                    raise PlanForbidden(
                        "Progress is reported on the detailed plan during "
                        "implementation, by the block's department or a plan editor")
        else:
            structural = bool(creates or dels or lups or ldels) or any(
                k in STRUCTURAL_FIELDS for u in updates for k in fields(u))
            await ChangePlanService._require_edit(
                session, change, plan, user, structural=structural)
            if any(k in PROGRESS_FIELDS for u in updates for k in fields(u)):
                for u in updates:
                    if any(k in PROGRESS_FIELDS for k in fields(u)) and not \
                            await ChangePlanService._may_progress(
                                session, change, by_id[u["id"]], user):
                        raise ChangeError(
                            "Progress is reported during implementation only")

        id_map: dict[str, int] = {}
        link_id_map: dict[str, int] = {}

        def ref(v):
            if isinstance(v, bool):
                raise ChangeError(f"Unknown block reference {v!r}")
            if isinstance(v, int) and v in by_id:
                return v
            if v is not None and str(v) in id_map:
                return id_map[str(v)]
            raise ChangeError(f"Unknown block reference {v!r}")

        # 1. deletes
        del_ids = set()
        for d in dels:
            if not is_existing(d):
                raise PlanConflict(f"Plan block {d} not found on this plan",
                                   not_found=True)
            del_ids.add(d)
        for lid in ldels:
            lk = link_by_id.get(lid)
            if lk is None:
                raise PlanConflict(f"Plan link {lid} not found on this plan",
                                   not_found=True)
            if lk in links:
                links.remove(lk)
                await session.delete(lk)
        for d in del_ids:
            t = by_id[d]
            await ChangePlanService._remove_task(session, change, plan, t, tasks, links)
            tasks.remove(t)
            del by_id[d]

        # 2. creates (parents and links resolved after every id exists)
        next_sort = max((t.sort_order for t in tasks), default=0) + 1
        new_tasks = []
        for u in creates:
            spec = fields(u)
            spec.setdefault("kind", "work")
            for required in ("name", "start_date"):
                if spec.get(required) in (None, ""):
                    raise ChangeError(f"'{required}' is required for a new block")
            await ChangePlanService._check_fields(
                session, {k: v for k, v in spec.items()
                          if k not in ("parent_id", "predecessors")}, set(), None)
            t = ChangePlanService._new_task(change, plan, spec, next_sort,
                                            user.id, cal)
            next_sort += 1
            session.add(t)
            new_tasks.append((u, t))
        await session.flush()
        for u, t in new_tasks:
            if u.get("id") is not None:
                id_map[str(u["id"])] = t.id
            by_id[t.id] = t
            tasks.append(t)
        for u, t in new_tasks:
            if u.get("parent_id") is not None:
                t.parent_id = ref(u["parent_id"])
        for u, t in new_tasks:
            if t.parent_id is not None:
                ChangePlanService._check_parent(by_id, t.id, t.parent_id)
            if u.get("predecessors"):
                await ChangePlanService._set_preds(
                    session, change, plan, t.id, [ref(p) for p in u["predecessors"]],
                    links, user.id, by_id)

        # 3. updates on existing blocks
        summaries = eng.summary_ids(e_tasks(tasks))
        date_changes: dict[int, dict] = {}
        touched = []
        for u in updates:
            t = by_id.get(u["id"])
            if t is None:
                continue                         # deleted in the same set
            spec = fields(u)
            if "parent_id" in spec and spec["parent_id"] is not None:
                spec["parent_id"] = ref(spec["parent_id"])
            if "predecessors" in spec:
                spec["predecessors"] = [ref(p) for p in spec["predecessors"] or []]
            await ChangePlanService._check_fields(
                session, spec, set(by_id), t.id, t)
            if "parent_id" in spec:
                ChangePlanService._check_parent(by_id, t.id, spec["parent_id"])
            d = {k: spec.pop(k) for k in DATE_FIELDS if k in spec}
            if d and t.id in summaries:
                same = {"start_date": lambda v: _as_date(v) == t.start_date,
                        "duration_days": lambda v: int(v) == int(t.duration_days or 0)}
                if any(v is not None and not same[k](v) for k, v in d.items()):
                    raise ChangeError(
                        f"'{t.name}' is a summary block: its dates come from the "
                        "blocks under it")
            elif d:
                date_changes[t.id] = d
            ChangePlanService._apply_fields(t, spec, user.id)
            if "predecessors" in spec:
                await ChangePlanService._set_preds(
                    session, change, plan, t.id, spec["predecessors"], links, user.id,
                    by_id)
            ChangePlanService._normalise(t)
            if spec:
                touched.append(t.id)
        moved = []
        if date_changes:
            moved = await ChangePlanService._apply_dates(
                session, change, plan, tasks, date_changes, user,
                reason=reason, bump=False)

        # 4. links (their targets, like blocks given new links or
        # constraints, may move themselves under automatic scheduling)
        push_keys = ("predecessors", "constraint_type", "constraint_date", "parent_id")
        relinked = [t.id for u, t in new_tasks
                    if any(u.get(k) for k in push_keys)]
        relinked += [u["id"] for u in updates if any(k in u for k in push_keys)
                     and u["id"] in by_id]
        for item in lups:
            lid = item.get("id")
            typ = (item.get("type") or "FS").upper()
            if isinstance(lid, int) and not isinstance(lid, bool):
                lk = link_by_id.get(lid)
                if lk is None or lk not in links:
                    raise PlanConflict(f"Plan link {lid} not found on this plan",
                                       not_found=True)
                frm = ref(item["from_task_id"]) if "from_task_id" in item \
                    else lk.from_task_id
                to = ref(item["to_task_id"]) if "to_task_id" in item \
                    else lk.to_task_id
                typ = (item.get("type") or lk.type).upper()
                lag = int(item["lag_days"]) if item.get("lag_days") is not None \
                    else int(lk.lag_days or 0)
                ChangePlanService._check_link(by_id, links, frm, to, typ, lag,
                                              own_id=lk.id)
                lk.from_task_id, lk.to_task_id, lk.type, lk.lag_days = \
                    frm, to, typ, lag
                relinked.append(to)
            else:
                frm, to = ref(item.get("from_task_id")), ref(item.get("to_task_id"))
                lag = int(item.get("lag_days") or 0)
                ChangePlanService._check_link(by_id, links, frm, to, typ, lag)
                lk = ChangePlanLink(change_id=change.id, plan=plan,
                                    from_task_id=frm, to_task_id=to, type=typ,
                                    lag_days=lag, created_by=user.id)
                session.add(lk)
                links.append(lk)
                relinked.append(to)
                await ChangePlanService._flush_links(session)
                if lid is not None:
                    link_id_map[str(lid)] = lk.id
        await ChangePlanService._flush_links(session)

        ChangePlanService._check_structure(before_issues, tasks, links)
        moved = list(dict.fromkeys(moved + await ChangePlanService._auto_push(
            change, plan, tasks, links, moved, relinked, user)))
        await ChangePlanService._rollup(session, change, plan)
        if creates or dels or lups or ldels or moved or (touched and not progress_only):
            await ChangePlanService._bump(change, plan)
        await ChangeService.append_changelog(
            session, change, "plan_changes",
            f"{plan.capitalize()} plan changed: {len(creates)} added, "
            f"{len(updates)} updated, {len(dels)} removed, "
            f"{len(lups)} link(s) set, {len(ldels)} link(s) removed", user.id,
            notes=(reason or None),
            new_value={"plan": plan, "added": [t.id for _, t in new_tasks],
                       "updated": sorted(set(touched) | set(moved)),
                       "removed": sorted(del_ids), "links_set": len(lups),
                       "links_removed": len(ldels)})
        return {"id_map": id_map, "link_id_map": link_id_map}

    # ------------------------------------------------------------------
    # System path: new blocks in a baselined detailed plan
    # ------------------------------------------------------------------
    @staticmethod
    async def add_blocks_after_baseline(
            session: AsyncSession, change: ChangeRequest, user: User,
            changeset: dict, reason: str, caused_by_task_id=None, *,
            label: Optional[str] = None, extra: Optional[dict] = None) -> dict:
        """Insert new blocks (and links) into the baselined detailed plan.
        The structure is frozen for people; this is the one system path that
        may add to it (a validation issue's recovery group). What the new
        blocks push along their links moves (the post-baseline cascade) and
        every such move is a deviation with `reason`, caused by
        `caused_by_task_id` (an existing id or a temp id of the set; None:
        the new block that pushed it). Each new top-level block is a
        deviation too (it was not in the promise). Revision bump as any
        detailed edit (none after the baseline).

        changeset: {"tasks_upsert": [new blocks with temp ids, parent_id may
        be a temp id], "links_upsert": [{from_task_id, to_task_id, type,
        lag_days}, ids temp or existing]}. Returns PlanOut + id_map +
        link_id_map + moved_ids (the existing blocks it moved)."""
        plan = "detailed"
        if not ChangePlanService.baselined(change, plan):
            raise ChangeError("The detailed plan has no baseline: edit it directly")
        reason = (reason or "").strip()
        if not reason:
            raise ChangeError("A reason is required to change a validated plan")
        cal = ChangePlanService.calendar(change, plan)
        links = await ChangePlanService.links(session, change, plan)
        tasks = await ChangePlanService.tasks(session, change, plan)
        by_id = {t.id: t for t in tasks}
        before_issues = ChangePlanService._structure_issues(tasks, links)
        summaries = eng.summary_ids(e_tasks(tasks))
        finish_before = plan_finish([t for t in tasks if t.id not in summaries])
        ups = list(changeset.get("tasks_upsert") or [])
        lups = list(changeset.get("links_upsert") or [])
        if not ups:
            raise ChangeError("No blocks to add")
        temp = []
        for u in ups:
            tid = u.get("id")
            if tid is None or (isinstance(tid, int) and not isinstance(tid, bool)):
                raise ChangeError("New blocks carry a temporary id (a string)")
            temp.append(str(tid))
        if len(set(temp)) != len(temp):
            raise ChangeError("A temporary block id is used twice in one change set")
        next_sort = max((t.sort_order for t in tasks), default=0) + 1
        made = []
        for u in ups:
            spec = {k: v for k, v in u.items() if k in WRITABLE_FIELDS
                    and k not in ("parent_id", "predecessors")}
            spec.setdefault("kind", "work")
            for required in ("name", "start_date"):
                if spec.get(required) in (None, ""):
                    raise ChangeError(f"'{required}' is required for a new block")
            await ChangePlanService._check_fields(session, spec, set(), None)
            t = ChangePlanService._new_task(change, plan, spec, next_sort,
                                            user.id, cal)
            next_sort += 1
            session.add(t)
            made.append((u, t))
        await session.flush()
        id_map = {str(u["id"]): t.id for u, t in made}
        for _u, t in made:
            by_id[t.id] = t
            tasks.append(t)

        def ref(v):
            if isinstance(v, int) and not isinstance(v, bool) and v in by_id:
                return v
            if v is not None and str(v) in id_map:
                return id_map[str(v)]
            raise ChangeError(f"Unknown block reference {v!r}")
        for u, t in made:
            if u.get("parent_id") is not None:
                t.parent_id = ref(u["parent_id"])
                ChangePlanService._check_parent(by_id, t.id, t.parent_id)
        link_id_map: dict = {}
        for item in lups:
            frm, to = ref(item.get("from_task_id")), ref(item.get("to_task_id"))
            typ = (item.get("type") or "FS").upper()
            lag = int(item.get("lag_days") or 0)
            ChangePlanService._check_link(by_id, links, frm, to, typ, lag)
            lk = ChangePlanLink(change_id=change.id, plan=plan, from_task_id=frm,
                                to_task_id=to, type=typ, lag_days=lag,
                                created_by=user.id)
            session.add(lk)
            links.append(lk)
            await ChangePlanService._flush_links(session)
            if item.get("id") is not None:
                link_id_map[str(item["id"])] = lk.id
        ChangePlanService._check_structure(before_issues, tasks, links)

        new_ids = {t.id for _u, t in made}
        parents = {t.parent_id for t in tasks if t.parent_id is not None}
        leaves_new = [t.id for _u, t in made if t.id not in parents]
        res, cause = eng.push(e_tasks(tasks), e_links(links), cal, leaves_new)
        cause_id = ref(caused_by_task_id) if caused_by_task_id is not None else None
        olds: dict = {}
        caused: dict = {}
        for tid in res.moved:
            t = by_id[tid]
            if t.start_date == res.tasks[tid].start:
                continue
            if tid not in new_ids:
                olds[tid] = (t.start_date, t.end_date)
                caused[tid] = cause_id if cause_id is not None else cause.get(tid)
            t.start_date = res.tasks[tid].start
            t.updated_by = user.id
        await ChangePlanService._rollup(session, change, plan)
        summaries = eng.summary_ids(e_tasks(tasks))
        finish_after = plan_finish([t for t in tasks if t.id not in summaries])
        impact = ((finish_after - finish_before).days
                  if finish_after and finish_before else 0)
        devs = []
        for _u, t in made:
            if t.parent_id in new_ids:
                continue                  # the top-level new block stands for it
            devs.append(ChangePlanDeviation(
                change_id=change.id, task_id=t.id, caused_by_task_id=None,
                old_start=t.start_date, old_end=t.start_date,
                new_start=t.start_date, new_end=t.end_date,
                slip_days=(t.end_date - t.start_date).days,
                finish_impact_days=impact, reason=reason, status="open",
                created_by=user.id))
        pushed = [t.id for t in tasks if t.id in olds]          # outline order
        for tid in pushed:
            t = by_id[tid]
            old_start, old_end = olds[tid]
            base_end = t.baseline_finish or old_end
            devs.append(ChangePlanDeviation(
                change_id=change.id, task_id=tid, caused_by_task_id=caused[tid],
                old_start=old_start, old_end=old_end,
                new_start=t.start_date, new_end=t.end_date,
                slip_days=(t.end_date - base_end).days,
                finish_impact_days=impact, reason=reason, status="open",
                created_by=user.id))
        top = [t.id for _u, t in made if t.parent_id not in new_ids]
        group = await ChangePlanService._new_group(
            session, change, cause_id if cause_id is not None else top[0],
            reason, user)
        for d in devs:
            d.group_id = group.id
            session.add(d)
        await session.flush()
        ChangePlanService._record_moved(change, pushed)
        await ChangePlanService._bump(change, plan)
        await ChangeService.append_changelog(
            session, change, "plan_deviation",
            (label or f"{len(made)} block(s) added to the validated plan")
            + f": {len(devs)} deviation(s), finish impact {impact:+d} days: "
            f"{reason}", user.id, notes=reason,
            new_value={"deviation_ids": [d.id for d in devs],
                       "task_ids": [d.task_id for d in devs],
                       "added": sorted(new_ids), "finish_impact_days": impact,
                       "group_id": group.id,
                       **(extra or {})})
        out = await ChangePlanService.get_plan(session, change, plan, user)
        return {**out, "id_map": id_map, "link_id_map": link_id_map,
                "moved_ids": ChangePlanService.take_moved(change)}

    # ------------------------------------------------------------------
    # MSPDI import
    # ------------------------------------------------------------------
    @staticmethod
    async def import_mspdi(session: AsyncSession, change: ChangeRequest,
                           plan: str, content: bytes, user: User,
                           *, replace: bool = False) -> dict:
        """Blocks, outline (summaries), links with type and lag, constraints,
        percent complete, actual dates, the baseline (number 0) and the
        calendar from an MS Project XML file. Appends to the plan, or
        replaces it with `replace`. The file's calendar becomes THIS plan's
        calendar when the plan holds only imported blocks afterwards (the
        other plan keeps its own). Returns {"tasks": n, "links": n,
        "warnings": [str]}: what was skipped and why."""
        await ChangePlanService._require_edit(
            session, change, plan, user, structural=True)
        try:
            parsed = eng.parse_mspdi(content)
        except eng.MspdiError as e:
            raise ChangeError(str(e))
        except (ValueError, OverflowError, RecursionError) as e:
            raise ChangeError(f"The file could not be read as MS Project XML ({e})")
        rows = parsed["tasks"]
        warnings = list(parsed.get("warnings") or [])
        if not rows:
            raise ChangeError("The file has no tasks to import")
        existing = await ChangePlanService.tasks(session, change, plan)
        if existing and replace:
            await ChangePlanService._clear(session, change, plan)
            existing = []
        if not existing:
            ChangePlanService._store_calendar(change, plan, parsed["calendar"])
        elif parsed["calendar"].to_json() != \
                ChangePlanService.calendar(change, plan).to_json():
            warnings.append(
                "The file's calendar differs from the plan's; the plan keeps "
                "its calendar (import with replace to take the file's)")
        # Progress is tracker work (the detailed plan in implementation); a
        # baseline is only ever set by "Timing validated", never by a file.
        tracking = plan == "detailed" and change.status in PROGRESS_WINDOW
        if not tracking and any(r.get("progress") or r.get("actual_start")
                                or r.get("actual_finish") for r in rows):
            warnings.append(
                "Percent complete and actual dates were not imported: progress "
                "is reported on the detailed plan during implementation")
        if tracking:
            # the file's actual dates follow the same rules as typed ones:
            # one that breaks them is left out with a warning, like the
            # parser does with a date in the future
            for r in rows:
                for k in ("actual_start", "actual_finish"):
                    try:
                        ChangePlanService._check_actuals(
                            _as_date(r.get(k)) if k == "actual_start" else None,
                            _as_date(r.get(k)) if k == "actual_finish" else None,
                            name=r.get("name"))
                    except ChangeError as e:
                        warnings.append(f"{e}; not imported")
                        r[k] = None
                try:
                    ChangePlanService._check_actuals(
                        _as_date(r.get("actual_start")),
                        _as_date(r.get("actual_finish")), name=r.get("name"))
                except ChangeError as e:
                    warnings.append(f"{e}; the actual finish was not imported")
                    r["actual_finish"] = None
        if any(r.get("baseline_start") for r in rows):
            warnings.append(
                "The file's baseline was not imported: the baseline is set by "
                "validating the timing")
        parents = {r.get("parent_uid") for r in rows if r.get("parent_uid")}
        for r in rows:
            if r["uid"] in parents and r.get("idea"):
                r["idea"] = False
                warnings.append(f"'{r['name']}' has tasks under it: its idea "
                                "flag was cleared (a summary cannot be an idea)")
        cal = ChangePlanService.calendar(change, plan)
        old_links = await ChangePlanService.links(session, change, plan)
        before_issues = ChangePlanService._structure_issues(existing, old_links)
        names = await ChangePlanService._dept_names(session)
        ids_by_name = {n: i for i, n in names.items()}
        sort = max((t.sort_order for t in existing), default=0) + 1
        by_uid: dict[str, ChangePlanTask] = {}
        for r in rows:
            kind = r.get("kind") if r.get("kind") in TASK_KINDS else (
                "milestone" if r["milestone"] else "work")
            t = ChangePlanTask(
                change_id=change.id, plan=plan, name=r["name"][:NAME_MAX],
                kind=kind, lane=(r.get("lane") or None) and r["lane"][:80],
                department_id=ids_by_name.get(r.get("lane")),
                is_idea=bool(r.get("idea")), start_date=r["start"],
                duration_days=int(r["duration"]), predecessors=[],
                sort_order=sort,
                progress_pct=int(r.get("progress") or 0) if tracking else 0,
                actual_start=r.get("actual_start") if tracking else None,
                actual_finish=r.get("actual_finish") if tracking else None,
                notes=r.get("notes"),
                constraint_type=r.get("constraint_type"),
                constraint_date=r.get("constraint_date"),
                created_by=user.id, updated_by=user.id)
            t._plan_cal = cal
            ChangePlanService._normalise(t, cal)
            sort += 1
            session.add(t)
            by_uid[r["uid"]] = t
        await session.flush()
        for r in rows:
            if r.get("parent_uid") in by_uid:
                by_uid[r["uid"]].parent_id = by_uid[r["parent_uid"]].id
        seen = set()
        n_links = 0
        new_links = []
        for lk in parsed["links"]:
            a, b = by_uid.get(lk["from_uid"]), by_uid.get(lk["to_uid"])
            if a is None or b is None or a is b:
                if a is None or b is None:
                    warnings.append(
                        f"A link to an unknown task (UID {lk['from_uid']}) was skipped")
                continue
            pair = frozenset((a.id, b.id))
            if pair in seen:
                continue
            seen.add(pair)
            new_links.append(ChangePlanLink(
                change_id=change.id, plan=plan, from_task_id=a.id,
                to_task_id=b.id, type=lk["type"], lag_days=int(lk["lag"]),
                created_by=user.id))
        for lk in new_links:
            session.add(lk)
            n_links += 1
        ChangePlanService._check_structure(
            before_issues, existing + list(by_uid.values()), old_links + new_links)
        await ChangePlanService._rollup(session, change, plan)
        await ChangePlanService._bump(change, plan)
        await ChangeService.append_changelog(
            session, change, "plan_imported",
            f"{plan.capitalize()} plan: {len(rows)} block(s) and {n_links} "
            f"link(s) imported from MS Project"
            + (" (replaced)" if replace else ""), user.id,
            new_value={"plan": plan, "tasks": len(rows), "links": n_links,
                       "replaced": bool(replace), "calendar": cal.to_json(),
                       "warnings": warnings})
        return {"tasks": len(rows), "links": n_links, "warnings": warnings}

    # ------------------------------------------------------------------
    # Feedback and timing validation
    # ------------------------------------------------------------------
    @staticmethod
    async def required_department_ids(session: AsyncSession,
                                       change: ChangeRequest) -> list[int]:
        """Every department with an R or A assessment on the change, plus
        Scheduling (it builds the bank) and Sales (it tells the customer).
        A mother-plant change (spec §14) has no assessments and no customer
        here: the informed departments and Scheduling confirm."""
        from app.services import mother_plants as mp
        ids = {a.department_id for a in change.assessments
               if a.rasic_letter in BLOCKING_LETTERS}
        names = ("Scheduling", "Sales")
        if mp.is_mother_plant(change):
            from app.services.mother_plant_service import MotherPlantService
            ids |= set(await MotherPlantService.informed_department_ids(
                session, change))
            names = ("Scheduling",)
        for name in names:
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
        if await session.get(Department, department_id) is None:
            raise ChangeError(f"Department {department_id} does not exist")
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
                       "plan_revision": row.plan_revision},
            for_department_id=department_id)

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
        errors = validate_plan(
            tasks, plan="detailed",
            links=await ChangePlanService.links(session, change, "detailed"),
            cal=ChangePlanService.calendar(change, "detailed"))["errors"]
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
        cause = aliased(ChangePlanTask)
        rows = (await session.execute(
            select(ChangePlanDeviation, ChangePlanTask.name, cause.name)
            .join(ChangePlanTask, ChangePlanTask.id == ChangePlanDeviation.task_id,
                  isouter=True)
            .join(cause, cause.id == ChangePlanDeviation.caused_by_task_id,
                  isouter=True)
            .where(ChangePlanDeviation.change_id == change.id)
            .order_by(ChangePlanDeviation.id.desc()))).all()
        users = await ChangePlanService._user_names(
            session, [d.created_by for d, _, _ in rows]
            + [d.decided_by for d, _, _ in rows])
        return [{
            "id": d.id, "task_id": d.task_id, "task_name": name,
            "group_id": d.group_id,
            "caused_by_task_id": d.caused_by_task_id,
            "caused_by_task_name": cause_name,
            "old_start": d.old_start, "old_end": d.old_end,
            "new_start": d.new_start, "new_end": d.new_end,
            "slip_days": d.slip_days, "finish_impact_days": d.finish_impact_days,
            "reason": d.reason, "status": d.status,
            "decided_by": d.decided_by, "decided_by_name": users.get(d.decided_by),
            "decided_at": d.decided_at, "decision_note": d.decision_note,
            "escalation_id": d.escalation_id,
            "created_by": d.created_by, "created_by_name": users.get(d.created_by),
            "created_at": d.created_at,
        } for d, name, cause_name in rows]

    @staticmethod
    async def _get_deviation(session, change, did) -> ChangePlanDeviation:
        d = await session.get(ChangePlanDeviation, did)
        if d is None or d.change_id != change.id:
            raise PlanConflict("Deviation not found on this change", not_found=True)
        return d

    @staticmethod
    def _check_decision_window(change: ChangeRequest) -> None:
        if change.status not in DEVIATION_DECISION_WINDOW:
            raise ChangeError(
                "Plan deviations are decided while the change is approved, in "
                "implementation or in validation")

    @staticmethod
    async def lock_deviation(session: AsyncSession, change: ChangeRequest,
                             did: int, note: Optional[str], user: User) -> None:
        if not await ChangePlanService.may_decide_deviation(session, change, user):
            raise PlanForbidden(
                "Only Project Management, Sales, the change lead or an admin "
                "may decide a plan deviation")
        d = await ChangePlanService._get_deviation(session, change, did)
        ChangePlanService._check_decision_window(change)
        if d.status != "open":
            raise ChangeError(f"The deviation is already {d.status}")
        note = (note or "").strip() or None
        await ChangePlanService._claim_open(
            session, [d], status="locked", decided_by=user.id,
            decided_at=datetime.utcnow(), decision_note=note)
        await ChangePlanService.settle_groups(session, [d.group_id])
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
        ChangePlanService._check_decision_window(change)
        if d.status != "open":
            raise ChangeError(f"The deviation is already {d.status}")
        now = datetime.utcnow()
        await ChangePlanService._claim_open(
            session, [d], status="escalated", decided_by=user.id,
            decided_at=now, decision_note=note)
        # the escalation exists only once the row is ours
        esc = await ChangePlanService._new_escalation(
            session, change, note, user, now, [d])
        await ChangePlanService.settle_groups(session, [d.group_id])
        await ChangeService.append_changelog(
            session, change, "deviation_escalated",
            f"Plan deviation #{d.id} escalated to the customer", user.id,
            notes=note,
            new_value={"deviation_id": d.id, "escalation_id": esc.id,
                       "slip_days": d.slip_days,
                       "finish_impact_days": d.finish_impact_days})

    DECIDED_JUST_NOW = ("Someone else decided part of this move just now; "
                        "reload")

    @staticmethod
    async def _claim_open(session, rows: list[ChangePlanDeviation],
                          **values) -> None:
        """Decide rows read as open, atomically: one UPDATE that only takes
        rows still open in the database (a concurrent decision holds the
        row lock; once it commits, the WHERE re-checks and skips the row).
        Anything short of every row is a 409 and the caller's transaction
        is rolled back, so a move is never half decided by two people."""
        ids = [d.id for d in rows]
        claimed = set((await session.execute(
            update(ChangePlanDeviation)
            .where(ChangePlanDeviation.id.in_(ids),
                   ChangePlanDeviation.status == "open")
            .values(**values)
            .returning(ChangePlanDeviation.id)
            .execution_options(synchronize_session=False))).scalars().all())
        if claimed != set(ids):
            raise PlanConflict(ChangePlanService.DECIDED_JUST_NOW)
        for d in rows:                 # keep the loaded objects in step
            for k, v in values.items():
                setattr(d, k, v)
        await session.flush()

    @staticmethod
    async def _new_escalation(session, change, note: str, user: User,
                              now: datetime, rows: list[ChangePlanDeviation]
                              ) -> ImplementationEscalation:
        """One customer escalation for rows already claimed as escalated."""
        esc = ImplementationEscalation(
            change_id=change.id, direction="customer", note=note,
            created_by=user.id, created_at=now)
        session.add(esc)
        await session.flush()
        await session.execute(
            update(ChangePlanDeviation)
            .where(ChangePlanDeviation.id.in_([d.id for d in rows]))
            .values(escalation_id=esc.id)
            .execution_options(synchronize_session=False))
        for d in rows:
            d.escalation_id = esc.id
        await session.flush()
        return esc

    @staticmethod
    async def open_deviation_count(session: AsyncSession,
                                   change: ChangeRequest) -> int:
        """Decisions still to take: one per edit (group) with an open row,
        plus every open row that belongs to no group (older rows)."""
        rows = (await session.execute(
            select(ChangePlanDeviation.group_id, func.count())
            .where(ChangePlanDeviation.change_id == change.id,
                   ChangePlanDeviation.status == "open")
            .group_by(ChangePlanDeviation.group_id))).all()
        return sum(n if gid is None else 1 for gid, n in rows)

    # ------------------------------------------------------------------
    # Deviation groups: one edit, one decision
    # ------------------------------------------------------------------
    @staticmethod
    async def _new_group(session, change, root_task_id, reason: str,
                         user: User) -> ChangePlanDeviationGroup:
        g = ChangePlanDeviationGroup(
            change_id=change.id, root_task_id=root_task_id, reason=reason,
            status="open", created_by=user.id)
        session.add(g)
        await session.flush()
        return g

    @staticmethod
    async def settle_groups(session, group_ids) -> None:
        """Re-derive a group's summary from its rows.

        ChangePlanDeviationGroup.status and its decided fields are derived
        and informational only: the rows are the truth (every guard and count
        reads the rows). A group with an open row is open; otherwise it takes
        its rows' common status, or "mixed" when they differ. escalation_id
        is kept only when every row points at that same escalation; a mixed
        group carries no decision (decided_by/at, note, escalation null),
        because no single decision covers it."""
        for gid in {g for g in group_ids if g is not None}:
            g = await session.get(ChangePlanDeviationGroup, gid)
            if g is None:
                continue
            rows = (await session.execute(
                select(ChangePlanDeviation.status,
                       ChangePlanDeviation.escalation_id).where(
                    ChangePlanDeviation.group_id == gid))).all()
            statuses = {st for st, _ in rows}
            escs = {e for _, e in rows}
            if "open" in statuses or not statuses:
                g.status = "open"
            elif len(statuses) == 1:
                g.status = statuses.pop()
            else:
                g.status = "mixed"
                g.decided_by = g.decided_at = g.decision_note = None
            g.escalation_id = (escs.pop() if len(escs) == 1
                               and g.status != "mixed" else None)
        await session.flush()

    @staticmethod
    async def _open_group(session, change, gid: int, user: User):
        """The group and its open rows, after the same checks as a row."""
        if not await ChangePlanService.may_decide_deviation(session, change, user):
            raise PlanForbidden(
                "Only Project Management, Sales, the change lead or an admin "
                "may decide a plan deviation")
        g = (await session.execute(
            select(ChangePlanDeviationGroup)
            .where(ChangePlanDeviationGroup.id == gid)
            .with_for_update())).scalar_one_or_none()
        if g is None or g.change_id != change.id:
            raise PlanConflict("Deviation group not found on this change",
                               not_found=True)
        ChangePlanService._check_decision_window(change)
        rows = list((await session.execute(
            select(ChangePlanDeviation).where(
                ChangePlanDeviation.group_id == g.id,
                ChangePlanDeviation.status == "open")
            .order_by(ChangePlanDeviation.id))).scalars().all())
        if not rows:
            raise ChangeError("Every deviation of this move is already decided")
        return g, rows

    @staticmethod
    async def lock_group(session: AsyncSession, change: ChangeRequest,
                         gid: int, note: Optional[str], user: User
                         ) -> ChangePlanDeviationGroup:
        """Accept every open row of one edit internally, in one go."""
        g, rows = await ChangePlanService._open_group(session, change, gid, user)
        note = (note or "").strip() or None
        now = datetime.utcnow()
        await ChangePlanService._claim_open(
            session, rows, status="locked", decided_by=user.id,
            decided_at=now, decision_note=note)
        g.decided_by, g.decided_at, g.decision_note = user.id, now, note
        await session.flush()
        await ChangePlanService.settle_groups(session, [g.id])
        await ChangeService.append_changelog(
            session, change, "deviation_locked",
            f"{len(rows)} plan deviation(s) of one move accepted internally",
            user.id, notes=note,
            new_value={"group_id": g.id, "deviation_ids": [d.id for d in rows],
                       "slip_days": max(d.slip_days for d in rows)})
        return g

    @staticmethod
    async def escalate_group(session: AsyncSession, change: ChangeRequest,
                             gid: int, note: str, user: User
                             ) -> ChangePlanDeviationGroup:
        """Take one edit to the customer: one escalation record, every open
        row of the group escalated under it, one changelog entry."""
        note = (note or "").strip()
        if not note:
            raise ChangeError("Escalating to the customer needs a note")
        g, rows = await ChangePlanService._open_group(session, change, gid, user)
        now = datetime.utcnow()
        await ChangePlanService._claim_open(
            session, rows, status="escalated", decided_by=user.id,
            decided_at=now, decision_note=note)
        # the escalation exists only once every row is ours
        esc = await ChangePlanService._new_escalation(
            session, change, note, user, now, rows)
        g.decided_by, g.decided_at, g.decision_note = user.id, now, note
        g.escalation_id = esc.id
        await session.flush()
        await ChangePlanService.settle_groups(session, [g.id])
        await ChangeService.append_changelog(
            session, change, "deviation_escalated",
            f"{len(rows)} plan deviation(s) of one move escalated to the "
            "customer", user.id, notes=note,
            new_value={"group_id": g.id, "deviation_ids": [d.id for d in rows],
                       "escalation_id": esc.id,
                       "slip_days": max(d.slip_days for d in rows),
                       "finish_impact_days": max(
                           d.finish_impact_days for d in rows)})
        return g

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------
    @staticmethod
    def mspdi_xml(change: ChangeRequest, plan: str, tasks: list[ChangePlanTask],
                  links: Optional[list] = None) -> bytes:
        """MS Project XML (MSPDI). Calendar mode exports elapsed days (format
        8), working mode working days (format 7) on the plan's workdays and
        holidays. Links carry type and lag, summaries their outline level.
        A block without its own constraint gets start-no-earlier-than on its
        start, so MS Project opens the plan as drawn instead of pulling it to
        the project start. Idea blocks are proposals, not work, and are left
        out (their children hang on the nearest exported parent)."""
        cal = ChangePlanService.calendar(change, plan)
        ChangePlanService._attach(tasks, cal)
        links = links if links is not None else []
        real = [t for t in tasks if not t.is_idea]
        real_ids = {t.id for t in real}
        by_id = {t.id: t for t in tasks}

        def exported_parent(t):
            p = t.parent_id
            seen = set()
            while p is not None and p not in real_ids and p not in seen:
                seen.add(p)
                p = by_id[p].parent_id if p in by_id else None
            return p if p in real_ids else None

        ets = [eng.ETask(id=t.id, start=t.start_date,
                         duration=int(t.duration_days or 0),
                         parent_id=exported_parent(t), name=t.name) for t in real]
        order = eng.dfs_order(ets)
        summaries = eng.summary_ids(ets)
        real_by_id = {t.id: t for t in real}
        rows = []
        for tid, wbs in order:
            t = real_by_id[tid]
            notes = " | ".join(x for x in (
                f"Lane: {t.lane}" if t.lane else None,
                f"Kind: {t.kind}", t.notes) if x)
            rows.append({
                "key": t.id, "name": t.name, "start": t.start_date,
                "duration": int(t.duration_days or 0), "end": t.end_date,
                "milestone": t.kind == "milestone" and tid not in summaries,
                "level": wbs.count(".") + 1, "outline": wbs,
                "summary": tid in summaries,
                "progress": int(t.progress_pct or 0),
                "actual_start": t.actual_start, "actual_finish": t.actual_finish,
                "constraint_type": t.constraint_type,
                "constraint_date": t.constraint_date,
                "notes": notes, "lane": t.lane, "kind": t.kind,
                "baseline_start": t.baseline_start,
                "baseline_finish": t.baseline_finish,
            })
        lk_rows = [{"from": lk.from_task_id, "to": lk.to_task_id,
                    "type": lk.type, "lag": int(lk.lag_days or 0)}
                   for lk in links
                   if lk.from_task_id in real_ids and lk.to_task_id in real_ids]
        return eng.build_mspdi(
            name=f"{change.change_number} {change.title}",
            title=f"{change.change_number} {plan} plan: {change.title}",
            cal=cal, tasks=rows, links=lk_rows)

    @staticmethod
    def csv_export(tasks: list[ChangePlanTask], links: Optional[list] = None) -> bytes:
        """One row per block, finish as the inclusive last day (what a person
        reading a spreadsheet means by 'finish'). Predecessors in MS Project
        notation (12, 13SS+2d). Text cells a spreadsheet would run as a
        formula are quoted."""
        links = links or []
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
            w.writerow([_csv_cell(v) for v in (
                t.id, t.name + (" (idea)" if t.is_idea and not t.name.rstrip()
                                .lower().endswith("(idea)") else ""), t.lane or "",
                t.kind, t.start_date.isoformat(), _last_day(t).isoformat(),
                int(t.duration_days or 0),
                _pred_notation(links, t.id),
                int(t.progress_pct or 0),
                t.baseline_start.isoformat() if t.baseline_start else "",
                bl_last.isoformat() if bl_last else "",
            )])
        return buf.getvalue().encode("utf-8")


def _json(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v
