"""Validation issues: the failure branch of stage 9 (spec §12, §12a).

When validation fails technically, the failure becomes an ISSUE with a light
8D shape and a decided route to the fix:

  raise -> contain -> root cause -> route (4-eyes) -> fix actions ->
  re-validation -> closed  (or accepted as a customer concession, or
  transferred to a follow-up change)

The fix routes (internal rework, supplier rework, design change) send the
change back to implementation through the existing loop back and put a
RECOVERY GROUP into the detailed plan: a summary block with one block per fix
action and a re-validation block, linked into what depended on the failed
validation so the plan pushes it. After the baseline every block that moves
is a deviation with the route reason.

Each issue carries an escalation level (1 department, 2 project, 3
management and customer), re-evaluated on every issue change and by the
notification sweep, with history rows, notifications and acknowledgement.

Refusals: ChangeError (400), IssueForbidden (403), IssueNotFound (404).
"""
import math
from datetime import date, datetime, timedelta
from typing import Optional

from app.utils.clock import business_today

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAssessment, ChangeAttachment, ChangeChangelog, ChangeRequest
from app.models.change_validation import ValidationCheck
from app.models.change_validation_issue import (
    COST_BEARERS, CUSTOMER_DECISIONS, FIX_OWNERS, FIX_ROUTES, ISSUE_CATEGORIES,
    ISSUE_DONE_STATUSES, ISSUE_ROUTES, ISSUE_SEVERITIES, ValidationIssue,
    ValidationIssueAction, ValidationIssueEscalation,
)
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from app.services.change_service import ChangeError, ChangeService


class IssueForbidden(Exception):
    """The caller may not do this; mapped to HTTP 403."""


class IssueNotFound(Exception):
    """No such issue / action / escalation on this change; HTTP 404."""


# Where an issue may be raised: validation, or implementation after a loop
# back (the change has been in validation before).
RAISE_STATUSES = ("in_validation", "in_implementation")
# Where an open issue may still be worked on.
WORK_STATUSES = ("approved", "in_implementation", "in_validation")

# Failed check key -> issue category (spec §12 Raise).
CHECK_CATEGORY = {
    "cycle_time": "cycle_time",
    "weight": "material_weight",
    "measured": "dimensional",
    "sampled": "tool",
    "packaging_validated": "packaging",
    "revision_bump": "documentation",
}

PM_DEPARTMENT = "Project Manager"
SALES_DEPARTMENT = "Sales"
MANAGEMENT_DEPARTMENT = "Management"
QUALITY_DEPARTMENT = "Quality"

DEFAULT_FIX_WORKDAYS = 5
REVALIDATION_DAYS = 3
NO_ROUTE_WORKDAYS = 2
ACK_WORKDAYS = 2
LEVEL_NAMES = {1: "department", 2: "project", 3: "management and customer"}


# ----------------------------------------------------------------------
# Working days (Mon-Fri) for the escalation clocks
# ----------------------------------------------------------------------
def add_workdays(d: date, n: int) -> date:
    """d plus n working days (Mon-Fri); n >= 0."""
    step = 0
    while step < n:
        d += timedelta(days=1)
        if d.isoweekday() <= 5:
            step += 1
    return d


def workdays_between(a: date, b: date) -> int:
    """Signed count of working days from a to b (b later: positive)."""
    if a == b:
        return 0
    sign = 1 if b > a else -1
    lo, hi = (a, b) if b > a else (b, a)
    n, d = 0, lo
    while d < hi:
        d += timedelta(days=1)
        if d.isoweekday() <= 5:
            n += 1
    return sign * n


def _baseline_last_day(t) -> date:
    """The inclusive last day of a block's baseline (baseline_finish is
    exclusive); a baselined milestone sits on its baseline start."""
    start = t.baseline_start or t.baseline_finish
    return (t.baseline_finish - timedelta(days=1)
            if t.baseline_finish > start else start)


def _d(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _txt(v, what: str, *, required: bool = True, limit: Optional[int] = None) -> Optional[str]:
    s = (v or "").strip() if isinstance(v, str) or v is None else str(v).strip()
    if required and not s:
        raise ChangeError(f"{what} is required")
    if limit is not None and len(s) > limit:
        raise ChangeError(f"{what} has at most {limit} characters")
    return s or None


class Viewer:
    """Who the caller is on this change, resolved once per request."""

    def __init__(self, user: User, change: ChangeRequest, dept_ids: set,
                 names: dict):
        self.user = user
        self.id = user.id
        self.admin = user.effective_role == "admin"
        # acting as a department drops the personal lead privilege
        from app.services.change_people import holds_lead
        self.lead = holds_lead(change, user)
        self.dept_ids = dept_ids
        self.dept_names = names
        mine = {names.get(i) for i in dept_ids}
        self.pm = PM_DEPARTMENT in mine
        self.sales = SALES_DEPARTMENT in mine
        self.management = MANAGEMENT_DEPARTMENT in mine
        # HARD #3 (C7): a concession is Quality's decision (no admin
        # shortcut): a real admin's own Quality row does not count, the rule
        # of change_people.hard3_blind; acting as Quality does
        self.quality = QUALITY_DEPARTMENT in mine and not self.admin

    @property
    def pm_or_lead(self) -> bool:
        return self.admin or self.pm or self.lead

    @property
    def cost_role(self) -> bool:
        # who RECORDS the extra cost: admin, lead, PM, Sales
        return self.admin or self.lead or self.pm or self.sales

    @property
    def cost_read(self) -> bool:
        # who READS it: the price rule (price_redaction.PriceViewer), which
        # adds Management (P4): it gives the OK on Absorb and concession
        # money, so it sees the amounts it is asked about
        return self.cost_role or self.management

    def in_dept(self, dept_id: Optional[int]) -> bool:
        return dept_id is not None and dept_id in self.dept_ids


class ValidationIssueService:

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    @staticmethod
    async def _dept_names(session: AsyncSession) -> dict[int, str]:
        return dict((await session.execute(
            select(Department.id, Department.name))).all())

    @staticmethod
    def quality_decides_concessions() -> bool:
        """HARD #3 (C7, RELEASE_V2): the customer's yes to a concession is
        filed by Sales (the mail), the decision is a Quality member's."""
        from app.services import cm_switches
        return cm_switches.on("RELEASE_V2")

    @staticmethod
    async def quality_decided(session: AsyncSession,
                              issue: ValidationIssue) -> bool:
        """Was the concession's yes recorded by a Quality member? Off the
        switch, any recorded yes counts (the rule before C7)."""
        return issue.id in await ValidationIssueService.quality_decided_ids(
            session, [issue])

    @staticmethod
    async def quality_decided_ids(session: AsyncSession, issues: list) -> set:
        """The ids of `issues` whose yes was Quality's, in one query at most.
        The flag stored at decision time (acts-as aware, the same rule as a
        Quality override) answers; a row from before migration 119 without
        it falls back to the decider's real membership."""
        if not ValidationIssueService.quality_decides_concessions():
            return {i.id for i in issues}
        out = {i.id for i in issues if i.customer_decided_as_quality}
        legacy = {i.customer_decided_by for i in issues
                  if i.customer_decided_as_quality is None
                  and i.customer_decided_by is not None}
        if legacy:
            members = set((await session.execute(
                select(UserDepartment.user_id)
                .join(Department, Department.id == UserDepartment.department_id)
                .join(User, User.id == UserDepartment.user_id)
                .where(UserDepartment.user_id.in_(legacy),
                       Department.name == QUALITY_DEPARTMENT,
                       Department.is_active.is_(True),
                       User.role != "admin"))).scalars())
            out |= {i.id for i in issues if i.customer_decided_as_quality is None
                    and i.customer_decided_by in members}
        return out

    @staticmethod
    async def check_retired(session: AsyncSession,
                            check: Optional[ValidationCheck]) -> bool:
        """A check its department no longer owes under the current catalog
        (e.g. a cycle time Manufacturing or Process Engineer measured before
        the Tool Engineer alone measured it): read-only, it can no longer be
        answered 'passed' again."""
        if check is None:
            return False
        return ValidationIssueService._retired_in(
            check, await ValidationIssueService._dept_names(session))

    @staticmethod
    def _retired_in(check: Optional[ValidationCheck], names: dict) -> bool:
        """check_retired against department names already loaded."""
        if check is None:
            return False
        from app.services import validation_checklist as catalog
        name = names.get(check.department_id)
        if name is None:
            # an unknown department says nothing about the catalog: the
            # check stays live rather than being retired by accident
            return False
        return check.check_key not in catalog.keys_for(name)

    @staticmethod
    async def _retired_by_issue(session: AsyncSession,
                                issues: list) -> dict[int, bool]:
        """issue id -> its linked check is retired (no longer asked)."""
        cids = {i.check_id for i in issues if i.check_id is not None}
        if not cids:
            return {}
        checks = {c.id: c for c in (await session.execute(
            select(ValidationCheck).where(ValidationCheck.id.in_(cids))
        )).scalars()}
        names = await ValidationIssueService._dept_names(session)
        return {i.id: ValidationIssueService._retired_in(
                    checks.get(i.check_id) if i.check_id is not None else None,
                    names)
                for i in issues}

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
        return dict((await session.execute(
            select(User.id, User.full_name).where(User.id.in_(ids)))).all())

    @staticmethod
    async def viewer(session: AsyncSession, change: ChangeRequest,
                     user: User) -> Viewer:
        from app.services.workflow_service import WorkflowService
        dept_ids = set(await WorkflowService.effective_department_ids(session, user))
        return Viewer(user, change,
                      dept_ids, await ValidationIssueService._dept_names(session))

    @staticmethod
    async def routed_department_ids(session: AsyncSession,
                                    change: ChangeRequest) -> set[int]:
        """Departments working on the change: every assessment row (the
        routing) plus every department that priced implementation work."""
        from app.services.implementation_service import ImplementationService
        ids = set((await session.execute(
            select(ChangeAssessment.department_id).where(
                ChangeAssessment.change_id == change.id))).scalars().all())
        ids.update(await ImplementationService.implementing_department_ids(
            session, change))
        return ids

    @staticmethod
    async def list_issues(session: AsyncSession,
                          change: ChangeRequest) -> list[ValidationIssue]:
        return list((await session.execute(
            select(ValidationIssue).where(ValidationIssue.change_id == change.id)
            .order_by(ValidationIssue.number))).scalars().all())

    @staticmethod
    async def get_issue(session: AsyncSession, change: ChangeRequest,
                        iid: int, *, lock: bool = False) -> ValidationIssue:
        if lock:
            # SELECT ... FOR UPDATE, re-read: two route decisions at once
            # serialise here and the second sees the first's route
            row = (await session.execute(
                select(ValidationIssue).where(ValidationIssue.id == iid)
                .with_for_update()
                .execution_options(populate_existing=True))).scalar_one_or_none()
        else:
            row = await session.get(ValidationIssue, iid)
        if row is None or row.change_id != change.id:
            raise IssueNotFound("Validation issue not found on this change")
        return row

    @staticmethod
    async def actions_of(session: AsyncSession,
                         issue_ids) -> dict[int, list[ValidationIssueAction]]:
        ids = list(issue_ids)
        out: dict[int, list] = {i: [] for i in ids}
        if not ids:
            return out
        for a in (await session.execute(
                select(ValidationIssueAction)
                .where(ValidationIssueAction.issue_id.in_(ids))
                .order_by(ValidationIssueAction.id))).scalars().all():
            out[a.issue_id].append(a)
        return out

    @staticmethod
    async def escalations_of(session: AsyncSession,
                             issue_ids) -> dict[int, list[ValidationIssueEscalation]]:
        ids = list(issue_ids)
        out: dict[int, list] = {i: [] for i in ids}
        if not ids:
            return out
        for e in (await session.execute(
                select(ValidationIssueEscalation)
                .where(ValidationIssueEscalation.issue_id.in_(ids))
                .order_by(ValidationIssueEscalation.id))).scalars().all():
            out[e.issue_id].append(e)
        return out

    @staticmethod
    async def attachments_of(session: AsyncSession,
                             issue_ids) -> dict[int, list[ChangeAttachment]]:
        ids = list(issue_ids)
        out: dict[int, list] = {i: [] for i in ids}
        if not ids:
            return out
        for a in (await session.execute(
                select(ChangeAttachment)
                .where(ChangeAttachment.validation_issue_id.in_(ids))
                .order_by(ChangeAttachment.id))).scalars().all():
            out[a.validation_issue_id].append(a)
        return out

    @staticmethod
    async def open_issues(session: AsyncSession,
                          change: ChangeRequest) -> list[ValidationIssue]:
        return list((await session.execute(
            select(ValidationIssue).where(
                ValidationIssue.change_id == change.id,
                ValidationIssue.status.not_in(ISSUE_DONE_STATUSES))
            .order_by(ValidationIssue.number))).scalars().all())

    @staticmethod
    async def open_count(session: AsyncSession, change: ChangeRequest) -> int:
        return (await session.execute(
            select(func.count()).select_from(ValidationIssue).where(
                ValidationIssue.change_id == change.id,
                ValidationIssue.status.not_in(ISSUE_DONE_STATUSES)))).scalar() or 0

    @staticmethod
    async def release_blocker(session: AsyncSession,
                              change: ChangeRequest) -> Optional[str]:
        """The in_validation -> released soft guard text, or None."""
        n = await ValidationIssueService.open_count(session, change)
        if not n:
            return None
        return f"{n} validation issue{'s' if n != 1 else ''} open"

    @staticmethod
    async def fixing_info(session: AsyncSession,
                          change: ChangeRequest) -> Optional[str]:
        """in_implementation -> in_validation: info only (never a guard)."""
        rows = [i for i in await ValidationIssueService.open_issues(session, change)
                if i.status == "fixing"]
        if not rows:
            return None
        return "Still fixing: " + ", ".join(f"{i.ref} {i.title}" for i in rows)

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------
    @staticmethod
    def _require(ok: bool, message: str) -> None:
        if not ok:
            raise IssueForbidden(message)

    @staticmethod
    def _require_open(issue: ValidationIssue) -> None:
        if not issue.is_open:
            raise ChangeError(f"{issue.ref} is {issue.status}: nothing more to do on it")

    @staticmethod
    def _require_work_window(change: ChangeRequest) -> None:
        if change.status not in WORK_STATUSES:
            raise ChangeError(
                f"Validation issues are worked on while the change is in "
                f"implementation or validation, not '{change.status}'")

    @staticmethod
    def route_options(v: Viewer, issue: ValidationIssue,
                      chk: Optional[ValidationCheck]) -> list[str]:
        """The routes this viewer may decide on this issue (the backend rule
        of decide_route, so the dialog offers nothing it refuses). With
        RELEASE_V2 a concession is Quality's 'Request concession' and a
        follow-up change is Quality's, never on a failed check (HARD #3)."""
        run = v.admin or v.pm or v.lead
        if not ValidationIssueService.fix_rule_on():
            return list(ISSUE_ROUTES) if run else []
        out = list(FIX_ROUTES) if run else []
        if v.quality and not (chk is not None and chk.status == "failed"):
            out.append("follow_up_change")
        return out

    @staticmethod
    def may_confirm_close(v: Viewer, issue: ValidationIssue) -> bool:
        """HARD #3 (RELEASE_V2): who confirms the fix of an issue no check
        closes: a Quality member, or a real member of the owner department
        (an admin account belongs to every department and does not count)."""
        return v.quality or (not v.admin and v.in_dept(issue.department_id))

    @staticmethod
    def _owner_ok(v: Viewer, issue: ValidationIssue) -> bool:
        """Owner department, PM, lead, admin."""
        return v.pm_or_lead or v.in_dept(issue.department_id)

    @staticmethod
    async def _was_in_validation(session: AsyncSession, change: ChangeRequest) -> bool:
        import json
        row = (await session.execute(
            select(ChangeChangelog.id).where(
                ChangeChangelog.change_id == change.id,
                ChangeChangelog.field_name == "status",
                ChangeChangelog.new_value == json.dumps("in_validation")).limit(1)
        )).scalar_one_or_none()
        return row is not None

    @staticmethod
    async def may_raise(session: AsyncSession, change: ChangeRequest,
                        v: Viewer) -> bool:
        if change.status not in RAISE_STATUSES:
            return False
        if change.status == "in_implementation" and not \
                await ValidationIssueService._was_in_validation(session, change):
            return False
        if v.pm_or_lead:
            return True
        routed = await ValidationIssueService.routed_department_ids(session, change)
        return bool(v.dept_ids & routed)

    @staticmethod
    def ack_audience_ok(v: Viewer, issue: ValidationIssue, level: int) -> bool:
        if v.admin:
            return True
        if level <= 1:
            return v.pm or v.in_dept(issue.department_id)
        if level == 2:
            return v.pm or v.lead or v.sales
        return v.pm or v.lead or v.sales or v.management

    @staticmethod
    def may_acknowledge(v: Viewer, issue: ValidationIssue,
                        esc: ValidationIssueEscalation) -> bool:
        """The audience of the level, but never whoever raised that
        escalation (an admin excepted, as for the route)."""
        return (ValidationIssueService.ack_audience_ok(v, issue, esc.level)
                and (v.admin or esc.created_by != v.id))

    # ------------------------------------------------------------------
    # Changelog / notifications
    # ------------------------------------------------------------------
    @staticmethod
    async def _log(session, change, issue: ValidationIssue, action: str,
                   text: str, user_id: Optional[int], *, notes=None, **extra):
        # a sweep-made entry has no actor: the change lead (or the raiser)
        # stands in (performed_by is required), the entry says it was
        # automatic in its text and with the system marker
        actor = user_id or change.lead_id or issue.created_by
        if user_id is None:
            text += " (automatic)"
            extra = {**extra, "system": True}
        # Project team (spec §18): the role the act belongs to, so a backup's
        # act reads "<backup> for <main>". Sweeps are nobody's stand-in.
        role_dept = None
        if user_id is not None:
            role_dept = await ValidationIssueService._act_department(
                session, issue, action)
        await ChangeService.append_changelog(
            session, change, f"validation_issue_{action}",
            f"{issue.ref} {text}", actor, notes=notes,
            new_value={"issue_id": issue.id, "number": issue.number, **extra},
            for_department_id=role_dept)

    # Which role an issue act belongs to (project team, spec §18).
    _ACT_ROLE = {
        "route_decided": "Project Manager", "closed": "Project Manager",
        "customer_decision": "Sales", "fix_quoted": "Sales",
    }
    _ACT_OWNER_DEPT = frozenset({
        "contained", "root_cause", "action_added", "action_done",
        "revalidated", "revalidated_early", "revalidation",
    })

    @staticmethod
    async def _act_department(session, issue: ValidationIssue,
                              action: str) -> Optional[int]:
        if action in ValidationIssueService._ACT_OWNER_DEPT:
            return issue.department_id
        name = ValidationIssueService._ACT_ROLE.get(action)
        if name is None:
            return None
        return (await session.execute(
            select(Department.id).where(Department.name == name))).scalar_one_or_none()

    @staticmethod
    async def change_org_id(session: AsyncSession,
                            change: ChangeRequest) -> Optional[int]:
        """The change's organization (project -> plant -> org), None for a
        change without a project (visible to every organization)."""
        from app.models.entities import Plant, Project
        if change.project_id is None:
            return None
        return (await session.execute(
            select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
            .where(Project.id == change.project_id))).scalar_one_or_none()

    @staticmethod
    async def _dept_members(session, dept_ids, org_id: Optional[int] = None) -> set[int]:
        ids = [i for i in dept_ids if i is not None]
        if not ids:
            return set()
        q = select(UserDepartment.user_id).where(UserDepartment.department_id.in_(ids))
        if org_id is not None:
            # departments are global: only the change's organization is told
            q = q.join(User, User.id == UserDepartment.user_id).where(
                User.organization_id == org_id)
        return set((await session.execute(q)).scalars().all())

    @staticmethod
    async def audience(session: AsyncSession, change: ChangeRequest,
                       issue: ValidationIssue, level: int) -> tuple[set, str]:
        """(user ids, who in words) a level change notifies: members of the
        change's organization only."""
        svc = ValidationIssueService
        org = await svc.change_org_id(session, change)
        pm = await svc._dept_id(session, PM_DEPARTMENT)
        sales = await svc._dept_id(session, SALES_DEPARTMENT)
        if level <= 1 and svc.fix_rule_on() and issue.check_id is not None:
            # §10: a failed check's notice goes to Quality (it owns the Fix
            # pick) and the check's department (it retests), not to PM, who
            # has no task on it
            quality = await svc._dept_id(session, QUALITY_DEPARTMENT)
            return (await svc._dept_members(
                session, [quality, issue.department_id], org),
                "Quality, owner department")
        users = await svc._dept_members(session, [pm], org)
        words = ["Project Manager"]
        if level <= 1:
            users |= await svc._dept_members(session, [issue.department_id], org)
            words.insert(0, "owner department")
            return users, ", ".join(words)
        if change.lead_id:
            users.add(change.lead_id)
        words.append("change lead")
        users |= await svc._dept_members(session, [sales], org)
        words.append("Sales")
        if level >= 3:
            mgmt = await svc._dept_id(session, MANAGEMENT_DEPARTMENT)
            members = await svc._dept_members(session, [mgmt], org) if mgmt else set()
            if members:
                users |= members
                words.append("Management")
            else:
                q = select(User.id).where(User.role == "admin",
                                          User.is_active.is_(True))
                if org is not None:
                    q = q.where(User.organization_id == org)
                users |= set((await session.execute(q)).scalars().all())
                words.append("admins")
            # Mother plant (spec §14): there is no customer of ours; the PM
            # informs the mother plant contact instead.
            from app.services import mother_plants as mp
            if mp.is_mother_plant(change):
                words.append(f"{mp.plant_name(change)} contact via PM")
        return users, ", ".join(words)

    @staticmethod
    def _link(change: ChangeRequest, issue: ValidationIssue) -> str:
        return f"/changes/{change.id}?tab=release&issue={issue.id}"

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------
    @staticmethod
    async def _record_escalation(session, change, issue: ValidationIssue,
                                 level: int, trigger: str, reason: str,
                                 user_id: Optional[int]) -> ValidationIssueEscalation:
        svc = ValidationIssueService
        users, words = await svc.audience(session, change, issue, level)
        esc = ValidationIssueEscalation(
            issue_id=issue.id, level=level, trigger=trigger, reason=reason,
            notified=words, created_by=user_id, created_at=datetime.utcnow())
        session.add(esc)
        old = issue.escalation_level
        issue.escalation_level = level
        # Level 3 is management and customer: Sales informs the customer. A
        # mother-plant change has no customer here: the PM informs the mother
        # plant contact (spec §14), so the customer errand is not raised.
        from app.services import mother_plants as mp
        mother_plant = mp.is_mother_plant(change)
        if level >= 3 and trigger != "deescalate" and not mother_plant:
            issue.customer_inform = True
        body = reason
        if level >= 3 and trigger != "deescalate" and mother_plant:
            body = f"PM: inform the {mp.plant_name(change)} contact. {reason}"
        await session.flush()
        from app.services.notification_service import NotificationService
        await NotificationService.notify_once(
            session, sorted(users - ({user_id} if user_id else set())),
            kind="validation_issue_escalated",
            subject_key=f"vi:{issue.id}:esc:{esc.id}",
            title=(f"{change.change_number} {issue.ref} escalation level {level} "
                   f"({LEVEL_NAMES.get(level, '')}): {issue.title}")[:255],
            body=body, link=svc._link(change, issue))
        await svc._log(session, change, issue, "escalated",
                       f"escalation level {old} -> {level}: {reason}", user_id,
                       notes=reason, level=level, old_level=old, trigger=trigger,
                       escalation_id=esc.id, notified=words)
        return esc

    @staticmethod
    async def plan_context(session: AsyncSession, change: ChangeRequest) -> dict:
        """The detailed plan's dates, read once for every issue of the change."""
        from app.services.change_plan_service import ChangePlanService, e_tasks
        from app.services import plan_engine as eng
        from app.services.change_plan_service import plan_finish
        tasks = await ChangePlanService.tasks(session, change, "detailed")
        summaries = eng.summary_ids(e_tasks(tasks))
        leaves = [t for t in tasks if t.id not in summaries and not t.is_idea]
        # inclusive last days, counted as the plan counts them (a milestone
        # sits on its start day, it does not end the day before)
        base = max((_baseline_last_day(t) for t in leaves
                    if t.baseline_finish is not None), default=None)
        return {"by_id": {t.id: t for t in tasks}, "finish": plan_finish(leaves),
                "baseline": base,
                "cal": ChangePlanService.calendar(change, "detailed")}

    @staticmethod
    def recovery_info(change: ChangeRequest, issue: ValidationIssue,
                      ctx: dict) -> Optional[dict]:
        """The recovery group's finish, the plan finish and the slips, all
        finish dates as INCLUSIVE last days (what the card shows)."""
        t = ctx["by_id"].get(issue.recovery_task_id) if issue.recovery_task_id else None
        if t is None:
            return None

        from app.services.change_plan_service import _last_day
        # The group's dates are its blocks' dates, counted like the plan
        # finish (inclusive last day, a milestone on its start); the
        # summary's own stored duration may lag behind a child that moved.
        kids = [c for c in ctx["by_id"].values() if c.parent_id == t.id]
        if kids:
            start = min(c.start_date for c in kids)
            finish = max(_last_day(c) for c in kids)
        else:
            start = t.start_date
            finish = _last_day(t)
        plan_finish = ctx["finish"]
        base = ctx["baseline"]
        deadline = _d(change.release_due_date)
        slip = (plan_finish - base).days if plan_finish and base else None
        past = (finish - deadline).days if deadline and finish else None
        plan_past = (plan_finish - deadline).days if deadline and plan_finish else None
        return {
            "summary_task_id": t.id,
            "task_id": t.id,
            "revalidation_task_id": issue.revalidation_task_id,
            "release_due_date": deadline,
            "slip_baseline_wd": (workdays_between(base, plan_finish)
                                 if plan_finish and base else None),
            "slip_deadline_wd": (workdays_between(deadline, plan_finish)
                                 if plan_finish and deadline else None),
            "start": start, "finish": finish,
            "plan_finish": plan_finish, "baseline_finish": base,
            "slip_days": slip,
            "slip_workdays": (workdays_between(base, plan_finish)
                              if plan_finish and base else None),
            "release_deadline": deadline,
            "past_deadline_days": past,
            "past_deadline_workdays": (workdays_between(deadline, finish)
                                       if deadline and finish else None),
            "plan_past_deadline_days": plan_past,
            # the recovery pushes the plan past the release deadline: Sales
            # records the customer's timing decision (new_timing/require_fix)
            "needs_timing_decision": bool(plan_past is not None and plan_past > 0
                                          and issue.customer_decision not in
                                          ("new_timing",)),
        }

    @staticmethod
    async def triggers(session: AsyncSession, change: ChangeRequest,
                       issue: ValidationIssue, ctx: dict,
                       history: list, actions: list,
                       today: Optional[date] = None) -> list[tuple]:
        """Every automatic escalation trigger standing now, as
        (level, trigger, reason)."""
        today = today or business_today()
        out = []
        if issue.severity == 3:
            out.append((2, "severity", "Severity 3: blocks production"))
        late = [a for a in actions if a.status == "open" and a.due_date
                and a.due_date < today]
        if late:
            out.append((2, "action_overdue",
                        f"{len(late)} fix action(s) overdue"))
        if issue.route is None and issue.status in ("open", "contained"):
            created = _d(issue.created_at) or today
            if add_workdays(created, NO_ROUTE_WORKDAYS) <= today:
                if not (ValidationIssueService.fix_rule_on()
                        and issue.check_id is not None):
                    out.append((2, "no_route",
                                f"No route decided after {NO_ROUTE_WORKDAYS} "
                                "working days"))
                elif issue.fix_department_id is None:
                    # §10: a failed check has no route; what can stall is
                    # Quality's Fix pick (once it names who and when, the
                    # retest task carries the date: nothing to escalate)
                    out.append((2, "no_fix",
                                f"No Fix pick by Quality after {NO_ROUTE_WORKDAYS} "
                                "working days"))
        rec = ValidationIssueService.recovery_info(change, issue, ctx)
        if rec is not None:
            if rec["slip_days"] is not None and rec["slip_days"] > 0:
                out.append((2, "plan_slip",
                            f"Recovery slips the plan finish {rec['slip_workdays']:+d} "
                            "working days past the baseline"))
            if rec["past_deadline_days"] is not None and rec["past_deadline_days"] > 0:
                out.append((3, "release_deadline",
                            f"Recovery ends {rec['finish'].isoformat()}, "
                            f"{rec['past_deadline_workdays']} working days after "
                            "the release deadline"))
        unacked = [e for e in history if e.level == 2 and e.acknowledged_at is None
                   and e.trigger != "deescalate"]
        if unacked and issue.escalation_level == 2:
            first = _d(unacked[0].created_at) or today
            if add_workdays(first, ACK_WORKDAYS) <= today:
                out.append((3, "unacknowledged",
                            f"Level 2 escalation not acknowledged within "
                            f"{ACK_WORKDAYS} working days"))
        if issue.customer_decision == "require_fix" and issue.route in (
                None, "customer_concession"):
            out.append((3, "require_fix",
                        "Customer requires a fix instead of the concession"))
        return out

    @staticmethod
    async def reevaluate(session: AsyncSession, change: ChangeRequest,
                         issue: Optional[ValidationIssue] = None,
                         user_id: Optional[int] = None,
                         today: Optional[date] = None) -> int:
        """Raise the level of open issues whose triggers stand (never lower
        it: de-escalation is by closing or by PM with a reason). A trigger
        already recorded at a level does not fire again. Returns the number
        of level changes written. Callable from the sweep (user_id None)."""
        svc = ValidationIssueService
        issues = [issue] if issue is not None else await svc.open_issues(session, change)
        issues = [i for i in issues if i.is_open]
        if not issues:
            return 0
        ctx = await svc.plan_context(session, change)
        hist = await svc.escalations_of(session, [i.id for i in issues])
        acts = await svc.actions_of(session, [i.id for i in issues])
        written = 0
        for i in issues:
            seen = {(e.level, e.trigger) for e in hist[i.id]}
            fresh = [t for t in await svc.triggers(
                session, change, i, ctx, hist[i.id], acts[i.id], today)
                if (t[0], t[1]) not in seen and t[0] > i.escalation_level]
            if not fresh:
                continue
            top = max(t[0] for t in fresh)
            at_top = [t for t in fresh if t[0] == top]
            await svc._record_escalation(
                session, change, i, top, at_top[0][1],
                "; ".join(t[2] for t in at_top), user_id)
            written += 1
        return written

    @staticmethod
    async def reevaluate_all(session: AsyncSession,
                             today: Optional[date] = None) -> int:
        """The sweep's entry point: every change with an open issue."""
        from app.models.change import TERMINAL_STATUSES
        ids = (await session.execute(
            select(ValidationIssue.change_id).join(
                ChangeRequest, ChangeRequest.id == ValidationIssue.change_id)
            .where(ValidationIssue.status.not_in(ISSUE_DONE_STATUSES),
                   ChangeRequest.status.not_in(TERMINAL_STATUSES))
            .distinct())).scalars().all()
        n = 0
        for cid in ids:
            # one broken change must not stop the sweep for every other one:
            # its own writes roll back to the savepoint, the rest stand
            try:
                async with session.begin_nested():
                    change = await session.get(ChangeRequest, cid)
                    n += await ValidationIssueService.reevaluate(
                        session, change, today=today)
            except Exception:                              # noqa: BLE001
                import logging
                logging.getLogger(__name__).exception(
                    "validation issue sweep failed for change %s", cid)
        return n

    @staticmethod
    async def escalate(session: AsyncSession, change: ChangeRequest, iid: int,
                       spec: dict, user: User) -> ValidationIssue:
        """Manual escalation by PM, lead or Sales with a reason: to the given
        level (default one up)."""
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        svc._require(v.pm_or_lead or v.sales,
                     "Only Project Management, the change lead, Sales or an admin "
                     "may escalate a validation issue")
        issue = await svc.get_issue(session, change, iid)
        svc._require_open(issue)
        reason = _txt(spec.get("reason"), "A reason")
        level = int(spec.get("level") or issue.escalation_level + 1)
        if level not in (1, 2, 3) or level <= issue.escalation_level:
            raise ChangeError(
                f"{issue.ref} is at level {issue.escalation_level}: escalate to a "
                "higher level (at most 3)")
        await svc._record_escalation(session, change, issue, level, "manual",
                                     reason, user.id)
        return issue

    @staticmethod
    async def deescalate(session: AsyncSession, change: ChangeRequest, iid: int,
                         spec: dict, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        svc._require(v.admin or v.pm,
                     "Only Project Management or an admin may lower an escalation")
        issue = await svc.get_issue(session, change, iid)
        svc._require_open(issue)
        reason = _txt(spec.get("reason"), "A reason")
        level = int(spec.get("level") or issue.escalation_level - 1)
        if level not in (1, 2) or level >= issue.escalation_level:
            raise ChangeError(
                f"{issue.ref} is at level {issue.escalation_level}: lower it to a "
                "level below (at least 1)")
        await svc._record_escalation(session, change, issue, level, "deescalate",
                                     reason, user.id)
        return issue

    @staticmethod
    async def acknowledge(session: AsyncSession, change: ChangeRequest, iid: int,
                          eid: int, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        issue = await svc.get_issue(session, change, iid)
        esc = await session.get(ValidationIssueEscalation, eid)
        if esc is None or esc.issue_id != issue.id:
            raise IssueNotFound("Escalation not found on this issue")
        v = await svc.viewer(session, change, user)
        svc._require(svc.ack_audience_ok(v, issue, esc.level),
                     "Only the people this escalation notified may acknowledge it")
        svc._require(svc.may_acknowledge(v, issue, esc),
                     "Four eyes: an escalation is acknowledged by someone other "
                     "than the person who raised it")
        if esc.acknowledged_at is not None:
            raise ChangeError("This escalation is already acknowledged")
        esc.acknowledged_by = user.id
        esc.acknowledged_at = datetime.utcnow()
        await session.flush()
        await svc._log(session, change, issue, "acknowledged",
                       f"escalation level {esc.level} acknowledged", user.id,
                       escalation_id=esc.id, level=esc.level)
        return issue

    # ------------------------------------------------------------------
    # Raise / edit
    # ------------------------------------------------------------------
    @staticmethod
    def category_for_check(check_key: Optional[str]) -> str:
        return CHECK_CATEGORY.get(check_key or "", "other")

    @staticmethod
    async def prefill(session: AsyncSession, change: ChangeRequest,
                      check_id: int, user: User) -> dict:
        """What "Raise issue" on a failed check starts from."""
        from app.services import validation_checklist as catalog
        svc = ValidationIssueService
        check = await session.get(ValidationCheck, check_id)
        if check is None or check.change_id != change.id:
            raise IssueNotFound("Validation check not found on this change")
        names = await svc._dept_names(session)
        existing = (await session.execute(
            select(ValidationIssue.id).where(
                ValidationIssue.check_id == check.id,
                ValidationIssue.status.not_in(ISSUE_DONE_STATUSES)).limit(1)
        )).scalar_one_or_none()
        label = catalog.label_for(check.check_key, names.get(check.department_id))
        v = await svc.viewer(session, change, user)
        return {
            "check_id": check.id, "check_key": check.check_key,
            "check_status": check.status,
            "title": f"{label} failed"[:200],
            "category": svc.category_for_check(check.check_key),
            "severity": 2, "department_id": check.department_id,
            "department_name": names.get(check.department_id),
            "description": check.note or "",
            "existing_issue_id": existing,
            "can_raise": bool(check.status == "failed" and existing is None
                              and await svc.may_raise(session, change, v)),
        }

    @staticmethod
    async def _check_part(session, change: ChangeRequest, part_id) -> None:
        """An affected part exists and belongs to the change's organization."""
        if part_id is None:
            return
        from app.models.entities import Plant, Project
        from app.models.part import Part
        org = (await session.execute(
            select(Plant.organization_id)
            .join(Project, Project.plant_id == Plant.id)
            .join(Part, Part.project_id == Project.id)
            .where(Part.id == part_id))).first()
        if org is None:
            raise ChangeError(f"Part {part_id} does not exist")
        mine = await ValidationIssueService.change_org_id(session, change)
        if mine is not None and org[0] != mine:
            raise ChangeError(f"Part {part_id} is not a part of this change's "
                              "organization")

    @staticmethod
    async def _check_user(session, change: ChangeRequest, user_id) -> None:
        """An action owner exists and belongs to the change's organization."""
        u = await session.get(User, user_id)
        if u is None:
            raise ChangeError(f"User {user_id} does not exist")
        mine = await ValidationIssueService.change_org_id(session, change)
        if mine is not None and u.organization_id != mine:
            raise ChangeError(f"User {user_id} is not in this change's organization")

    @staticmethod
    async def _check_fields(session, spec: dict) -> None:
        if "category" in spec and spec["category"] not in ISSUE_CATEGORIES:
            raise ChangeError(
                f"Unknown category '{spec['category']}': one of {', '.join(ISSUE_CATEGORIES)}")
        if "severity" in spec and spec["severity"] not in ISSUE_SEVERITIES:
            raise ChangeError("Severity is 1 (low), 2 (medium) or 3 (blocks production)")
        if spec.get("department_id") is not None and \
                await session.get(Department, spec["department_id"]) is None:
            raise ChangeError(f"Department {spec['department_id']} does not exist")
        if "title" in spec:
            spec["title"] = _txt(spec["title"], "A title", limit=200)
        if "description" in spec:
            spec["description"] = _txt(spec["description"], "A description")
        if "affected_tool_ref" in spec:
            spec["affected_tool_ref"] = _txt(spec["affected_tool_ref"],
                                             "The tool reference", required=False,
                                             limit=120)

    @staticmethod
    async def create(session: AsyncSession, change: ChangeRequest, spec: dict,
                     user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        if change.status not in RAISE_STATUSES:
            raise ChangeError(
                "Validation issues are raised while the change is in validation "
                "(or in implementation after a loop back)")
        svc._require(await svc.may_raise(session, change, v),
                     "Only a member of a department working on the change, "
                     "Project Management, the change lead or an admin may raise "
                     "a validation issue")
        spec = {k: val for k, val in spec.items() if val is not None}
        check = None
        key, key_dept = spec.pop("check_key", None), spec.pop("check_department_id", None)
        if spec.get("check_id") is None and key:
            # the frontend names the failed check by key and department
            q = select(ValidationCheck.id).where(
                ValidationCheck.change_id == change.id,
                ValidationCheck.check_key == key)
            if key_dept is not None:
                q = q.where(ValidationCheck.department_id == key_dept)
            found = (await session.execute(q)).scalars().all()
            if len(found) != 1:
                raise ChangeError(
                    f"No single validation check '{key}' on this change"
                    + ("" if key_dept is not None else ": name its department"))
            spec["check_id"] = found[0]
        if spec.get("check_id") is not None:
            check = await session.get(ValidationCheck, spec["check_id"])
            if check is None or check.change_id != change.id:
                raise ChangeError("That validation check is not on this change")
            if check.status != "failed":
                raise ChangeError("An issue is raised from a FAILED validation check")
            if await svc.check_retired(session, check):
                raise ChangeError(
                    "That validation check is no longer asked of its "
                    "department: raise the issue without linking it")
            dup = (await session.execute(
                select(ValidationIssue).where(
                    ValidationIssue.check_id == check.id,
                    ValidationIssue.status.not_in(ISSUE_DONE_STATUSES)).limit(1)
            )).scalar_one_or_none()
            if dup is not None:
                raise ChangeError(
                    f"{dup.ref} is already open for this failed check")
            spec.setdefault("category", svc.category_for_check(check.check_key))
            spec.setdefault("department_id", check.department_id)
        spec.setdefault("category", "other")
        spec.setdefault("severity", 2)
        for k in ("title", "description"):
            spec.setdefault(k, "")
        await svc._check_fields(session, spec)
        await svc._check_part(session, change, spec.get("affected_part_id"))
        number = ((await session.execute(
            select(func.max(ValidationIssue.number)).where(
                ValidationIssue.change_id == change.id))).scalar() or 0) + 1
        issue = ValidationIssue(
            change_id=change.id, number=number, title=spec["title"],
            category=spec["category"], severity=int(spec["severity"]),
            department_id=spec.get("department_id"),
            check_id=check.id if check else None,
            affected_part_id=spec.get("affected_part_id"),
            affected_tool_ref=spec.get("affected_tool_ref"),
            description=spec["description"], status="open",
            escalation_level=1, created_by=user.id,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(issue)
        await session.flush()
        await svc._log(session, change, issue, "raised",
                       f"raised: {issue.title} (severity {issue.severity}, "
                       f"{issue.category})", user.id, notes=issue.description,
                       check_id=issue.check_id, severity=issue.severity,
                       category=issue.category, department_id=issue.department_id)
        # Level 1: the owner department and PM are informed.
        await svc._record_escalation(session, change, issue, 1, "raised",
                                     "Issue raised", user.id)
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    @staticmethod
    async def update(session: AsyncSession, change: ChangeRequest, iid: int,
                     spec: dict, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid)
        svc._require_open(issue)
        spec = dict(spec)
        inform = spec.pop("customer_inform", None)
        fields = {k: val for k, val in spec.items() if k in (
            "title", "description", "severity", "category", "department_id",
            "affected_part_id", "affected_tool_ref")}
        if fields:
            svc._require(v.pm_or_lead or v.in_dept(issue.department_id)
                         or issue.created_by == user.id,
                         "Only the raiser, the owner department, Project Management, "
                         "the change lead or an admin may edit the issue")
        if inform is not None:
            # L2: Sales decides whether the customer must be informed
            svc._require(v.pm_or_lead or v.sales,
                         "Only Sales, Project Management, the change lead or an "
                         "admin decide whether the customer is informed")
            if not inform and issue.route == "customer_concession":
                raise ChangeError("A customer concession always informs the customer")
        # None means "not sent" except for the two nullable references
        clean = {k: val for k, val in fields.items()
                 if val is not None or k in ("affected_part_id", "affected_tool_ref")}
        await svc._check_fields(session, clean)
        if clean.get("affected_part_id") is not None:
            await svc._check_part(session, change, clean["affected_part_id"])
        before = {k: getattr(issue, k) for k in clean}
        for k, val in clean.items():
            setattr(issue, k, val)
        if inform is not None:
            before["customer_inform"] = issue.customer_inform
            issue.customer_inform = bool(inform)
        issue.updated_at = datetime.utcnow()
        await session.flush()
        changed = {k: getattr(issue, k) for k in before if getattr(issue, k) != before[k]}
        if changed:
            await svc._log(session, change, issue, "updated",
                           "updated: " + ", ".join(sorted(changed)), user.id,
                           changed={k: (str(x) if isinstance(x, (date, datetime)) else x)
                                    for k, x in changed.items()})
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    # ------------------------------------------------------------------
    # Containment / root cause
    # ------------------------------------------------------------------
    @staticmethod
    async def contain(session: AsyncSession, change: ChangeRequest, iid: int,
                      text: str, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid)
        svc._require_open(issue)
        svc._require(svc._owner_ok(v, issue),
                     "Only the owner department, Project Management, the change "
                     "lead or an admin may record the containment")
        issue.containment = _txt(text, "The containment")
        issue.contained_at = datetime.utcnow()
        issue.contained_by = user.id
        if issue.status == "open":
            issue.status = "contained"
        issue.updated_at = datetime.utcnow()
        await session.flush()
        await svc._log(session, change, issue, "contained", "contained", user.id,
                       notes=issue.containment)
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    @staticmethod
    async def set_root_cause(session: AsyncSession, change: ChangeRequest, iid: int,
                             text: str, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid)
        svc._require_open(issue)
        svc._require(svc._owner_ok(v, issue),
                     "Only the owner department, Project Management, the change "
                     "lead or an admin may record the root cause")
        issue.root_cause = _txt(text, "The root cause")
        issue.root_cause_at = datetime.utcnow()
        issue.root_cause_by = user.id
        issue.updated_at = datetime.utcnow()
        await session.flush()
        await svc._log(session, change, issue, "root_cause", "root cause recorded",
                       user.id, notes=issue.root_cause)
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    # ------------------------------------------------------------------
    # Route
    # ------------------------------------------------------------------
    @staticmethod
    async def _add_actions(session, change, issue, items: list, user) -> list:
        out = []
        for item in items or []:
            desc = _txt(item.get("description"), "An action description")
            dept = item.get("department_id")
            if dept is not None and await session.get(Department, dept) is None:
                raise ChangeError(f"Department {dept} does not exist")
            owner = item.get("owner_id")
            if owner is not None:
                await ValidationIssueService._check_user(session, change, owner)
            a = ValidationIssueAction(
                issue_id=issue.id, description=desc, owner_id=owner,
                department_id=dept if dept is not None else issue.department_id,
                due_date=_d(item.get("due_date")), status="open",
                created_by=user.id, created_at=datetime.utcnow())
            session.add(a)
            out.append(a)
        if out:
            await session.flush()
        return out

    @staticmethod
    async def decide_route(session: AsyncSession, change: ChangeRequest, iid: int,
                           spec: dict, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid, lock=True)
        route = spec.get("route")
        # HARD #3 (RELEASE_V2): a follow-up change takes an open issue off
        # this change's release, so it is Quality's call (A5-01)
        quality_follow_up = svc.fix_rule_on() and route == "follow_up_change"
        svc._require(v.admin or v.pm or v.lead or (quality_follow_up and v.quality),
                     "Only Project Management, the change lead or an admin decide "
                     "the route")
        # 4-eyes: the route is not decided by the raiser alone, an admin
        # included (A5-01: no admin clears an issue it raised by itself)
        svc._require(issue.created_by != user.id,
                     "Four eyes: the route is decided by someone other than the "
                     "person who raised the issue")
        svc._require_open(issue)
        svc._require_work_window(change)
        if issue.route is not None:
            raise ChangeError(f"The route of {issue.ref} is already decided "
                              f"({issue.route})")
        if route not in ISSUE_ROUTES:
            raise ChangeError(f"Unknown route '{route}': one of {', '.join(ISSUE_ROUTES)}")
        if svc.fix_rule_on():
            # §10 (RELEASE_V2): the concession has one entry point, Quality's
            # 'Request concession' (Sales owner's ask, internal 'not for
            # shipment'); a fix route back to implementation stays the
            # exception beside Quality's Fix task
            if route == "customer_concession":
                raise ChangeError(
                    "A concession is Quality's: a Quality member uses "
                    "'Request concession' on the issue")
            chk = (await session.get(ValidationCheck, issue.check_id)
                   if issue.check_id is not None else None)
            if route == "follow_up_change" and chk is not None \
                    and chk.status == "failed":
                raise ChangeError(
                    f"{issue.ref}'s failed check holds this change's release "
                    "(HARD #3): fix and retest it here, or a concession "
                    "(Quality); a follow-up change does not lift it")
            if route == "follow_up_change":
                svc._require(v.quality,
                             f"{issue.ref} holds this change's release (HARD #3): "
                             "moving it to a follow-up change is Quality's call")
        reason = _txt(spec.get("reason"), "A reason for the route")
        if issue.severity == 3 and not issue.containment:
            raise ChangeError(
                "Severity 3: record the containment before deciding the route")
        if not issue.root_cause and route != "customer_concession":
            raise ChangeError(
                "Record the root cause before deciding the route (only a customer "
                "concession may be decided with the cause still open)")
        inform = spec.get("customer_inform")
        if route == "customer_concession":
            if inform is False:
                raise ChangeError("A customer concession needs the customer informed")
            inform = True
        elif route == "design_change" and inform is None:
            inform = True
        supplier = _txt(spec.get("supplier_name"), "The supplier", required=False,
                        limit=120)
        if route == "supplier_rework" and not supplier:
            raise ChangeError("Supplier rework: name the supplier")

        actions = await svc.actions_of(session, [issue.id])
        new_actions = spec.get("actions") or []
        if route in FIX_ROUTES and not new_actions and not [
                a for a in actions[issue.id] if a.status == "open"]:
            raise ChangeError("A fix route needs at least one fix action")
        issue.route = route
        issue.route_reason = reason
        issue.route_decided_at = datetime.utcnow()
        issue.route_decided_by = user.id
        issue.supplier_name = supplier if route == "supplier_rework" else issue.supplier_name
        if route == "supplier_rework" and spec.get("chargeback") is not None:
            issue.chargeback = bool(spec["chargeback"])
        if inform is not None:
            issue.customer_inform = bool(inform)
        # a new route decision starts a new customer conversation
        if issue.customer_decision == "require_fix":
            issue.customer_decision = None
        issue.updated_at = datetime.utcnow()
        created = await svc._add_actions(session, change, issue, new_actions, user)
        await svc._log(session, change, issue, "route_decided",
                       f"route decided: {route}", user.id, notes=reason,
                       route=route, customer_inform=issue.customer_inform,
                       supplier_name=issue.supplier_name, chargeback=issue.chargeback,
                       action_ids=[a.id for a in created])

        if route in FIX_ROUTES:
            issue.status = "fixing"
            await session.flush()
            if change.status == "in_validation":
                await ChangeService.transition(
                    session, change, "in_implementation", user.id,
                    reason=f"{issue.ref}: {issue.title}: {reason}")
            open_actions = [a for a in (actions[issue.id] + created)
                            if a.status == "open"]
            await svc.build_recovery(session, change, issue, open_actions, user)
        elif route == "customer_concession":
            issue.status = "route_decided"
            if issue.customer_decision == "accept_deviation" and \
                    await svc.has_customer_mail(session, issue) and \
                    await svc.quality_decided(session, issue):
                # Sales recorded the customer's yes (with the mail) before
                # the route: the concession is settled the moment it is
                # decided. Without the mail Sales still owes it and records
                # the decision again (next act "customer").
                await svc._close(session, change, issue, "accepted",
                                 issue.customer_decision_note or reason, user.id,
                                 "closed: accepted by the customer as a concession")
        else:                                         # follow_up_change
            await svc._transfer(session, change, issue, user)
        await session.flush()
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    @staticmethod
    async def _transfer(session, change, issue, user) -> None:
        text = issue.description
        if issue.root_cause:
            text += f"\n\nRoot cause: {issue.root_cause}"
        if issue.containment:
            text += f"\n\nContainment: {issue.containment}"
        follow = await ChangeService.create_change(
            session, project_id=change.project_id,
            title=f"{issue.title} (follow-up {change.change_number} {issue.ref})"[:255],
            change_type=change.change_type, raised_by=user.id,
            reason=f"Follow-up of {change.change_number} {issue.ref}",
            description=text, priority=change.priority, lead_id=change.lead_id,
            customer_relevant=change.customer_relevant)
        issue.follow_up_change_id = follow.id
        issue.status = "transferred"
        issue.closed_at = datetime.utcnow()
        issue.closed_by = user.id
        issue.closure_note = f"Transferred to {follow.change_number}"
        await session.flush()
        await ValidationIssueService._finish_recovery(session, change, issue, user.id)
        await ValidationIssueService._log(
            session, change, issue, "transferred",
            f"transferred to follow-up change {follow.change_number}", user.id,
            follow_up_change_id=follow.id,
            follow_up_change_number=follow.change_number)
        await ChangeService.append_changelog(
            session, follow, "follow_up_of",
            f"Follow-up of {change.change_number} {issue.ref}: {issue.title}",
            user.id, new_value={"change_id": change.id, "issue_id": issue.id})

    # ------------------------------------------------------------------
    # Recovery group in the detailed plan (§12a)
    # ------------------------------------------------------------------
    @staticmethod
    def _fix_duration(cal, start: date, due: Optional[date]) -> int:
        if due is not None and due >= start:
            return max(1, cal.span(start, due + timedelta(days=1)))
        if cal.working:
            return DEFAULT_FIX_WORKDAYS
        return math.ceil(DEFAULT_FIX_WORKDAYS * 7 / 5)

    @staticmethod
    async def _recovery_task_ids(session, change: ChangeRequest, tasks) -> set[int]:
        """Every block of every recovery group on the change: the summaries,
        their children (fix blocks, re-validation)."""
        rows = (await session.execute(
            select(ValidationIssue.recovery_task_id,
                   ValidationIssue.revalidation_task_id).where(
                ValidationIssue.change_id == change.id))).all()
        ids = {x for r in rows for x in r if x is not None}
        ids |= {a for a in (await session.execute(
            select(ValidationIssueAction.plan_task_id)
            .join(ValidationIssue, ValidationIssue.id == ValidationIssueAction.issue_id)
            .where(ValidationIssue.change_id == change.id,
                   ValidationIssueAction.plan_task_id.is_not(None)))).scalars().all()}
        grew = True
        while grew:                      # descendants of the summaries
            more = {t.id for t in tasks if t.parent_id in ids and t.id not in ids}
            ids |= more
            grew = bool(more)
        return ids

    @staticmethod
    async def build_recovery(session: AsyncSession, change: ChangeRequest,
                             issue: ValidationIssue, actions: list,
                             user: User) -> Optional[int]:
        """The recovery group: summary "Recovery VI-n: <title>" after the
        failed validation block, one block per fix action, "Re-validation
        VI-n", FS links chaining them and linking the re-validation into
        whatever depended on the failed validation. Before the baseline it
        goes through ChangePlanService.apply_changes (one ChangeSet with temp
        ids); after it, apply_changes refuses structural edits, so the blocks
        are written here and every block the recovery pushes is a deviation
        (reason "VI-n: <route reason>", caused_by = the recovery group).
        Returns the summary id, or None when there is no detailed plan."""
        from app.services.change_plan_service import ChangePlanService
        tasks = await ChangePlanService.tasks(session, change, "detailed")
        if not tasks:
            return None
        from app.services import plan_engine as eng
        from app.services.change_plan_service import e_tasks
        cal = ChangePlanService.calendar(change, "detailed")
        links = await ChangePlanService.links(session, change, "detailed")
        summaries = eng.summary_ids(e_tasks(tasks))
        leaves = [t for t in tasks if t.id not in summaries and not t.is_idea]
        anchor = None
        check_dept = None
        if issue.check_id:
            chk = await session.get(ValidationCheck, issue.check_id)
            check_dept = chk.department_id if chk else None
        # Other issues' recovery groups are not the failed validation: a
        # second recovery runs in parallel off the same validation block and
        # feeds the same dependents, never chained after another recovery.
        recovery = await ValidationIssueService._recovery_task_ids(
            session, change, tasks)
        vals = [t for t in leaves if t.kind == "validation" and t.id not in recovery]
        if vals:
            anchor = max(vals, key=lambda t: (t.end_date, t.sort_order))
        today = cal.snap(business_today())
        start = max(anchor.end_date, today) if anchor else today
        start = cal.snap(start)
        names = await ValidationIssueService._dept_names(session)
        owner_dept = issue.department_id
        lane = names.get(owner_dept) if owner_dept else None
        reason = f"{issue.ref}: {issue.route_reason}"
        succ_ids = []
        if anchor is not None:
            succ_ids = [lk.to_task_id for lk in links
                        if lk.from_task_id == anchor.id
                        and lk.to_task_id not in recovery]
        rv_dept = check_dept or owner_dept

        blocks = []                       # (key, spec)
        blocks.append(("sum", {
            "name": f"Recovery {issue.ref}: {issue.title}"[:200], "kind": "work",
            "lane": lane, "department_id": owner_dept, "start_date": start,
            "duration_days": 0, "notes": reason}))
        act_keys = []
        for n, a in enumerate(actions, 1):
            dept = a.department_id or owner_dept
            dur = ValidationIssueService._fix_duration(cal, start, a.due_date)
            key = f"act{n}"
            act_keys.append((key, a))
            blocks.append((key, {
                "name": f"Fix {issue.ref}: {a.description}"[:200], "kind": "work",
                "lane": names.get(dept) if dept else lane, "department_id": dept,
                "start_date": start, "duration_days": dur, "parent": "sum"}))
        act_end = max((cal.end_date(start, b["duration_days"])
                       for k, b in blocks if k.startswith("act")), default=start)
        blocks.append(("rv", {
            "name": f"Re-validation {issue.ref}", "kind": "validation",
            "lane": names.get(rv_dept) if rv_dept else lane,
            "department_id": rv_dept, "start_date": cal.snap(act_end),
            "duration_days": REVALIDATION_DAYS, "parent": "sum"}))
        new_links = []                    # (from, to) keys or ids
        if anchor is not None:
            new_links.append((anchor.id, "sum"))
        for key, _a in act_keys:
            new_links.append((key, "rv"))
        for sid in succ_ids:
            new_links.append(("rv", sid))

        tmp = {k: f"vi{issue.id}-{k}" for k, _ in blocks}
        ups = []
        for k, b in blocks:
            u = {kk: vv for kk, vv in b.items() if kk != "parent"}
            u["id"] = tmp[k]
            u["start_date"] = u["start_date"].isoformat()
            if b.get("parent"):
                u["parent_id"] = tmp[b["parent"]]
            ups.append(u)
        changeset = {
            "tasks_upsert": ups,
            "links_upsert": [
                {"from_task_id": tmp.get(f, f) if isinstance(f, str) else f,
                 "to_task_id": tmp.get(t, t) if isinstance(t, str) else t,
                 "type": "FS", "lag_days": 0} for f, t in new_links]}
        if not ChangePlanService.baselined(change, "detailed"):
            res = await ChangePlanService.apply_changes(
                session, change, "detailed", changeset, user, reason=reason)
        else:
            # every block the recovery pushes is a deviation caused by it
            res = await ChangePlanService.add_blocks_after_baseline(
                session, change, user, changeset, reason,
                caused_by_task_id=tmp["sum"],
                label=f"Recovery {issue.ref} added to the detailed plan",
                extra={"issue_id": issue.id})
        ids = {k: res["id_map"][tmp[k]] for k, _ in blocks}
        issue.recovery_task_id = ids["sum"]
        issue.revalidation_task_id = ids["rv"]
        for key, a in act_keys:
            a.plan_task_id = ids[key]
        await session.flush()
        return ids["sum"]

    # ------------------------------------------------------------------
    # Customer
    # ------------------------------------------------------------------
    @staticmethod
    async def has_customer_mail(session: AsyncSession, issue: ValidationIssue) -> bool:
        return bool((await session.execute(
            select(func.count()).select_from(ChangeAttachment).where(
                ChangeAttachment.validation_issue_id == issue.id,
                ChangeAttachment.kind == "customer_email"))).scalar())

    @staticmethod
    async def customer_mail_at(session: AsyncSession,
                               issue: ValidationIssue) -> Optional[datetime]:
        """When the (last) customer mail was filed into the issue."""
        return (await session.execute(
            select(func.max(ChangeAttachment.created_at)).where(
                ChangeAttachment.validation_issue_id == issue.id,
                ChangeAttachment.kind == "customer_email"))).scalar()

    ATTACH_KINDS = ("general", "customer_email")

    @staticmethod
    def frozen_attachment_reason(issue: ValidationIssue,
                                 att: ChangeAttachment) -> Optional[str]:
        """Why a document filed into an issue can no longer be removed (409
        for everyone but an admin), or None."""
        if att.kind == "customer_email" and issue.status == "accepted":
            return (f"{issue.ref} was accepted as a concession on this customer "
                    "mail: it is the record and cannot be removed")
        return None

    @staticmethod
    async def frozen_attachment(session: AsyncSession,
                                att: ChangeAttachment) -> Optional[str]:
        if att.validation_issue_id is None:
            return None
        issue = await session.get(ValidationIssue, att.validation_issue_id)
        return (ValidationIssueService.frozen_attachment_reason(issue, att)
                if issue is not None else None)

    @staticmethod
    async def check_attach(session: AsyncSession, change: ChangeRequest,
                           iid: int, kind: str, actor: Optional[User]) -> ValidationIssue:
        """Filing a document into an issue (ChangeService.add_attachment):
        evidence (general) or the customer's mail (customer_email), while
        the issue is open, by the owner department, PM, lead, Sales, the
        raiser or an admin."""
        svc = ValidationIssueService
        issue = await svc.get_issue(session, change, iid)
        if kind not in svc.ATTACH_KINDS:
            raise ChangeError(
                "A validation issue holds evidence (general) and customer mails "
                "(customer_email) only")
        if not issue.is_open:
            raise ChangeError(f"{issue.ref} is {issue.status}: its record is closed")
        if actor is not None:
            v = await svc.viewer(session, change, actor)
            svc._require(svc._owner_ok(v, issue) or v.sales
                         or issue.created_by == actor.id,
                         "Only the owner department, Project Management, the "
                         "change lead, Sales or an admin may file documents into "
                         "this issue")
        return issue

    @staticmethod
    def customer_options(v: Viewer, issue: ValidationIssue) -> list[str]:
        """The customer decisions this viewer may record on the issue (the
        rule of customer_decision): Sales or an admin; on a concession with
        RELEASE_V2 the yes is Quality's alone (HARD #3)."""
        svc = ValidationIssueService
        if svc.quality_decides_concessions():
            # Quality gives the yes, on a concession it requested; what else
            # the customer said (fix, new timing) Sales records
            others = ([d for d in CUSTOMER_DECISIONS if d != "accept_deviation"]
                      if v.admin or v.sales else [])
            if issue.route == "customer_concession":
                return (["accept_deviation"] if v.quality else []) + others
            return others
        return list(CUSTOMER_DECISIONS) if v.admin or v.sales else []

    @staticmethod
    async def customer_decision(session: AsyncSession, change: ChangeRequest,
                                iid: int, spec: dict, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid)
        decision = spec.get("decision")
        concession = (issue.route == "customer_concession"
                      and svc.quality_decides_concessions())
        if (decision == "accept_deviation" and not concession
                and svc.quality_decides_concessions()):
            # one entry point: the customer's yes to a deviation is a
            # concession, which Quality requests first (spec §0, §10)
            raise ChangeError(
                "The customer's yes to a deviation is a concession: Quality "
                "uses 'Request concession' on the issue first")
        if concession and decision == "accept_deviation":
            # HARD #3 (C7): the one exit from a failed check is Quality's
            # decision once the customer's mail is filed; no admin shortcut.
            svc._require(v.quality,
                         "Quality decides the concession: Sales files the "
                         "customer's mail into the issue, a Quality member "
                         "accepts it")
        else:
            svc._require(v.admin or v.sales,
                         "Only Sales records the customer's decision")
        if (concession and decision == "accept_deviation"
                and issue.status == "accepted"
                and not await svc.quality_decided(session, issue)):
            # An accepted concession whose yes was not Quality's (Sales
            # before the rule): Quality confirms it, so HARD #3's one exit
            # is never used up without counting (no dead end, R18).
            note = _txt(spec.get("note"), "A note on the customer decision")
            issue.customer_decision_note = note
            issue.customer_decided_at = datetime.utcnow()
            issue.customer_decided_by = user.id
            issue.customer_decided_as_quality = True
            issue.updated_at = datetime.utcnow()
            await session.flush()
            await svc._log(session, change, issue, "customer_decision",
                           "concession confirmed by Quality", user.id,
                           notes=note, decision=decision)
            return issue
        svc._require_open(issue)
        if decision not in CUSTOMER_DECISIONS:
            raise ChangeError(
                f"Unknown decision '{decision}': one of {', '.join(CUSTOMER_DECISIONS)}")
        note = _txt(spec.get("note"), "A note on the customer decision")
        if decision == "accept_deviation" and issue.route == "customer_concession" \
                and not await svc.has_customer_mail(session, issue):
            raise ChangeError(
                "A concession is closed only with the customer's mail: file it "
                "into the issue (kind customer_email) first")
        new_date = _d(spec.get("new_release_due_date") or spec.get("new_date"))
        if decision == "new_timing" and new_date is None:
            raise ChangeError("New timing: give the new date the customer agreed")
        if decision == "new_timing" and new_date < business_today():
            raise ChangeError(
                f"New timing: {new_date.isoformat()} is in the past; give the "
                "date the customer agreed from today on")
        if concession and decision == "accept_deviation" and svc.fix_rule_on():
            # §10: a concession is for a quantity of parts or until a date
            issue.concession_quantity, until = svc._concession_bounds(spec)
            spec = {**spec, "concession_until": until}
        issue.customer_decision = decision
        issue.customer_decision_note = note
        issue.customer_decided_at = datetime.utcnow()
        issue.customer_decided_by = user.id
        issue.customer_decided_as_quality = v.quality
        issue.customer_inform = True
        if spec.get("concession_until") is not None:
            issue.concession_until = _d(spec["concession_until"])
        issue.updated_at = datetime.utcnow()
        await session.flush()
        await svc._log(session, change, issue, "customer_decision",
                       f"customer decision: {decision}", user.id, notes=note,
                       decision=decision,
                       concession_until=(issue.concession_until.isoformat()
                                         if issue.concession_until else None),
                       new_date=new_date.isoformat() if new_date else None)

        if decision == "accept_deviation" and issue.route == "customer_concession":
            await svc._close(session, change, issue, "accepted", note, user.id,
                             "closed: accepted by the customer as a concession")
        elif decision == "require_fix" and issue.route == "customer_concession":
            # the concession is off: the route is decided again
            await svc._log(session, change, issue, "reopened",
                           "route reopened: the customer requires a fix", user.id,
                           notes=note, old_route=issue.route)
            issue.route = None
            issue.route_reason = None
            issue.route_decided_at = None
            issue.route_decided_by = None
            issue.status = "contained" if issue.containment else "open"
            await session.flush()
        elif decision == "new_timing":
            issue.new_timing_date = new_date
            # end of the agreed day, like every other deadline writer; the
            # reason keeps what it said and adds this issue's note
            prior = (change.release_due_reason or "").strip()
            entry = f"{issue.ref}: {note}"
            await ChangeService._apply_release_deadline(
                session, change,
                datetime.combine(new_date, datetime.max.time().replace(microsecond=0)),
                f"{prior}; {entry}" if prior else entry, user.id)
            await svc._escalate_recovery_deviations(session, change, issue, note, user)
        await session.flush()
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    @staticmethod
    async def _escalate_recovery_deviations(session, change, issue, note, user) -> None:
        """The deviations the recovery created go to the customer together:
        one escalation record referencing the issue."""
        from app.models.change_impl import ImplementationEscalation
        from app.models.change_plan import ChangePlanDeviation
        devs = list((await session.execute(
            select(ChangePlanDeviation).where(
                ChangePlanDeviation.change_id == change.id,
                ChangePlanDeviation.status == "open",
                ChangePlanDeviation.reason.like(f"{issue.ref}:%")))).scalars().all())
        esc = None
        if issue.customer_escalation_id:
            esc = await session.get(ImplementationEscalation, issue.customer_escalation_id)
        if esc is None:
            esc = ImplementationEscalation(
                change_id=change.id, direction="customer",
                note=f"{issue.ref} {issue.title}: new timing agreed. {note}",
                created_by=user.id, created_at=datetime.utcnow())
            session.add(esc)
            await session.flush()
            issue.customer_escalation_id = esc.id
        now = datetime.utcnow()
        for d in devs:
            d.status = "escalated"
            d.escalation_id = esc.id
            d.decided_by = user.id
            d.decided_at = now
            d.decision_note = f"{issue.ref}: new timing agreed with the customer"
        await session.flush()
        # the recovery's group(s) settle with their rows; settle_groups keeps
        # an escalation on a group only when every one of its rows points at
        # it, so the recovery's escalation lands only on a group that is
        # wholly this recovery's (not one with rows escalated elsewhere)
        from app.models.change_plan import ChangePlanDeviationGroup
        from app.services.change_plan_service import ChangePlanService
        gids = {d.group_id for d in devs if d.group_id is not None}
        await ChangePlanService.settle_groups(session, gids)
        for gid in gids:
            g = await session.get(ChangePlanDeviationGroup, gid)
            if (g is not None and g.status == "escalated"
                    and g.escalation_id == esc.id):
                g.decided_by, g.decided_at = user.id, now
                g.decision_note = f"{issue.ref}: new timing agreed with the customer"
        await session.flush()
        if devs:
            await ChangeService.append_changelog(
                session, change, "deviation_escalated",
                f"{len(devs)} recovery deviation(s) of {issue.ref} escalated to "
                "the customer", user.id, notes=note,
                new_value={"deviation_ids": [d.id for d in devs],
                           "escalation_id": esc.id, "issue_id": issue.id})

    # ------------------------------------------------------------------
    # Cost
    # ------------------------------------------------------------------
    @staticmethod
    async def set_cost(session: AsyncSession, change: ChangeRequest, iid: int,
                       spec: dict, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        svc._require(v.cost_role,
                     "Only Project Management, Sales, the change lead or an admin "
                     "record the extra cost")
        issue = await svc.get_issue(session, change, iid)
        # Open or not: a late invoice lands after the issue closed, like the
        # quote of the fix (mark_fix_quoted). Audited either way.
        late = not issue.is_open
        cost = spec.get("extra_cost")
        bearer = spec.get("cost_bearer")
        if cost is not None:
            cost = round(float(cost), 2)
            if cost < 0:
                raise ChangeError("The extra cost is zero or more")
        if bearer is not None and bearer not in COST_BEARERS:
            raise ChangeError(
                f"Unknown cost bearer '{bearer}': one of {', '.join(COST_BEARERS)}")
        if cost and bearer is None:
            raise ChangeError("Say who bears the extra cost")
        old = {"extra_cost": issue.extra_cost, "cost_bearer": issue.cost_bearer}
        issue.extra_cost = cost
        issue.cost_bearer = bearer
        if bearer != "customer":
            issue.fix_quoted_at = None
            issue.fix_quoted_by = None
        issue.updated_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "validation_issue_cost",
            f"{issue.ref} extra cost recorded ({bearer or 'none'})"
            + (f" after the issue was {issue.status}" if late else ""), user.id,
            old_value={"issue_id": issue.id, **old},
            new_value={"issue_id": issue.id, "number": issue.number,
                       "extra_cost": cost, "cost_bearer": bearer,
                       "after_close": late})
        return issue

    @staticmethod
    async def mark_fix_quoted(session: AsyncSession, change: ChangeRequest, iid: int,
                              note: Optional[str], user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        svc._require(v.admin or v.sales, "Only Sales quotes the fix")
        issue = await svc.get_issue(session, change, iid)
        if issue.cost_bearer != "customer":
            raise ChangeError("Only a fix the customer pays for is quoted")
        if issue.fix_quoted_at is not None:
            raise ChangeError("The fix is already quoted")
        issue.fix_quoted_at = datetime.utcnow()
        issue.fix_quoted_by = user.id
        await session.flush()
        await svc._log(session, change, issue, "fix_quoted",
                       "fix quoted to the customer", user.id,
                       notes=(note or "").strip() or None)
        return issue

    # ------------------------------------------------------------------
    # Fix actions
    # ------------------------------------------------------------------
    @staticmethod
    async def add_action(session: AsyncSession, change: ChangeRequest, iid: int,
                         spec: dict, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid)
        svc._require_open(issue)
        svc._require(svc._owner_ok(v, issue),
                     "Only the owner department, Project Management, the change "
                     "lead or an admin may add fix actions")
        created = await svc._add_actions(session, change, issue, [spec], user)
        if issue.status == "revalidation":
            issue.status = "fixing"
        issue.updated_at = datetime.utcnow()
        await session.flush()
        await svc._log(session, change, issue, "action_added",
                       f"fix action added: {created[0].description}", user.id,
                       action_id=created[0].id)
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    @staticmethod
    def _may_do_action(v: Viewer, issue: ValidationIssue,
                       a: ValidationIssueAction) -> bool:
        return (v.pm_or_lead or a.owner_id == v.id or v.in_dept(a.department_id)
                or v.in_dept(issue.department_id))

    @staticmethod
    async def action_done(session: AsyncSession, change: ChangeRequest, iid: int,
                          aid: int, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid)
        a = await session.get(ValidationIssueAction, aid)
        if a is None or a.issue_id != issue.id:
            raise IssueNotFound("Fix action not found on this issue")
        svc._require_open(issue)
        svc._require(svc._may_do_action(v, issue, a),
                     "Only the action's owner, its department, the owner "
                     "department, Project Management, the change lead or an "
                     "admin may mark it done")
        if a.status == "done":
            raise ChangeError("That action is already done")
        a.status = "done"
        a.done_at = datetime.utcnow()
        a.done_by = user.id
        await session.flush()
        await svc._log(session, change, issue, "action_done",
                       f"fix action done: {a.description}", user.id, action_id=a.id)
        acts = (await svc.actions_of(session, [issue.id]))[issue.id]
        if issue.status == "fixing" and all(x.status == "done" for x in acts):
            chk = (await session.get(ValidationCheck, issue.check_id)
                   if issue.check_id else None)
            if chk is not None and chk.status == "passed":
                # the linked check passed again while actions were still
                # open ("revalidated early"): the last action closes it
                await svc._log(session, change, issue, "revalidated",
                               "re-validated: the linked check had passed, the "
                               "last fix action is done", user.id,
                               check_id=chk.id)
                await svc._close(session, change, issue, "closed",
                                 "Re-validated: the linked check passed", user.id)
                return issue
            issue.status = "revalidation"
            await session.flush()
            await svc._log(session, change, issue, "revalidation",
                           "all fix actions done: ready for re-validation", user.id)
        issue.updated_at = datetime.utcnow()
        await session.flush()
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    # ------------------------------------------------------------------
    # Re-validation / close
    # ------------------------------------------------------------------
    @staticmethod
    async def _finish_recovery(session: AsyncSession, change: ChangeRequest,
                               issue: ValidationIssue,
                               user_id: Optional[int]) -> list[int]:
        """The issue is done: its recovery blocks (fix blocks and the
        re-validation) are done too. A block not at 100% goes to 100% with
        its actual dates filled where missing (start: the planned start,
        never after today; finish: today, the last worked day). An issue
        accepted or transferred never fixed anything: its blocks are marked
        done the same way with a note saying so. Returns the block ids."""
        from app.models.change_plan import ChangePlanTask
        ids = {a.plan_task_id for a in (await ValidationIssueService.actions_of(
            session, [issue.id]))[issue.id] if a.plan_task_id}
        if issue.revalidation_task_id:
            ids.add(issue.revalidation_task_id)
        if not ids:
            return []
        today = business_today()
        note = None
        if issue.status == "accepted":
            note = f"{issue.ref} accepted by the customer as a concession: not fixed"
        elif issue.status == "transferred":
            note = f"{issue.ref} transferred to a follow-up change: not fixed here"
        done = []
        for t in (await session.execute(
                select(ChangePlanTask).where(ChangePlanTask.id.in_(ids),
                                             ChangePlanTask.change_id == change.id)
        )).scalars().all():
            if int(t.progress_pct or 0) >= 100 and t.actual_finish is not None:
                continue
            t.progress_pct = 100
            if t.actual_start is None:
                t.actual_start = min(t.start_date, today)
            if t.actual_finish is None:
                t.actual_finish = max(today, t.actual_start)
            if note and note not in (t.notes or ""):
                t.notes = f"{t.notes}\n{note}" if t.notes else note
            if user_id is not None:
                t.updated_by = user_id
            done.append(t.id)
        if done:
            await session.flush()
        return done

    @staticmethod
    async def _close(session: AsyncSession, change: ChangeRequest,
                     issue: ValidationIssue, status: str, note: Optional[str],
                     user_id: int, text: str = "closed") -> None:
        """Every way an issue ends in 'closed' or 'accepted': the record,
        the changelog and the recovery blocks marked done."""
        issue.status = status
        issue.closed_at = datetime.utcnow()
        issue.closed_by = user_id
        issue.closure_note = note
        issue.updated_at = datetime.utcnow()
        await session.flush()
        blocks = await ValidationIssueService._finish_recovery(
            session, change, issue, user_id)
        await ValidationIssueService._log(
            session, change, issue, "closed", text, user_id, notes=note,
            status=status, **({"plan_task_ids_done": blocks} if blocks else {}))

    @staticmethod
    async def on_check_answered(session: AsyncSession, change: ChangeRequest,
                                check: ValidationCheck, user: User) -> dict:
        """Hook for ValidationService.record_check (or the router): a PASSED
        answer closes every open issue linked to the check (re-validated); a
        FAILED answer sends issues waiting for re-validation back to fixing.
        Returns {closed: [ids], reopened: [ids], offer_raise: bool} where
        offer_raise says the check failed and has no open issue yet."""
        svc = ValidationIssueService
        linked = list((await session.execute(
            select(ValidationIssue).where(
                ValidationIssue.check_id == check.id,
                ValidationIssue.status.not_in(ISSUE_DONE_STATUSES)))).scalars().all())
        closed, reopened, early = [], [], []
        if check.status == "passed":
            acts = await svc.actions_of(session, [i.id for i in linked])
            for i in linked:
                if i.status == "fixing" and any(a.status == "open" for a in acts[i.id]):
                    # passed before the fix actions are done: stays open
                    # ("revalidated early") and closes with the last action
                    await svc._log(session, change, i, "revalidated_early",
                                   "the linked check passed while fix actions are "
                                   "still open: closes when they are done", user.id,
                                   check_id=check.id)
                    early.append(i.id)
                    continue
                await svc._log(session, change, i, "revalidated",
                               "re-validated: the linked check passed", user.id,
                               check_id=check.id)
                await svc._close(session, change, i, "closed",
                                 "Re-validated: the linked check passed", user.id)
                closed.append(i.id)
        elif check.status == "failed":
            for i in linked:
                if i.status == "revalidation":
                    i.status = "fixing"
                    await session.flush()
                    await svc._log(session, change, i, "reopened",
                                   "re-validation failed again: back to fixing",
                                   user.id, check_id=check.id)
                    reopened.append(i.id)
        return {"closed": closed, "reopened": reopened, "revalidated_early": early,
                "offer_raise": check.status == "failed" and not linked}

    @staticmethod
    async def close(session: AsyncSession, change: ChangeRequest, iid: int,
                    note: str, user: User) -> ValidationIssue:
        svc = ValidationIssueService
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid)
        rules = svc.quality_decides_concessions()
        svc._require(v.admin or v.pm or v.lead
                     or (rules and (v.quality or (
                         issue.check_id is None and svc.may_confirm_close(v, issue)))),
                     "Only Project Management, the change lead or an admin close "
                     "an issue")
        svc._require_open(issue)
        note = _txt(note, "A closure note")
        # A check no longer asked can never pass again: its issue closes
        # with a note, like an unlinked one, whatever step it is at.
        retired = issue.check_id is not None and await svc.check_retired(
            session, await session.get(ValidationCheck, issue.check_id))
        if issue.check_id is not None and not retired:
            raise ChangeError(
                f"{issue.ref} is linked to a validation check: it closes when "
                "that check is answered 'passed' again")
        if not retired and issue.status not in ("revalidation", "open", "contained"):
            raise ChangeError(
                f"{issue.ref} is {issue.status}: finish the fix actions first "
                "(an issue closes from re-validation, or before a route when "
                "it was raised in error)")
        if (not retired and issue.status in ("open", "contained")
                and svc.quality_decides_concessions()):
            # HARD #3: an open issue holds the release; closing it as raised
            # in error is Quality's call with the evidence, never a free-text
            # shortcut of the run team or an admin
            svc._require(v.quality,
                         "An open validation issue holds the release: only a "
                         "Quality member closes it as raised in error")
            from app.services.cm_rules import reference_refusal
            refusal = reference_refusal(
                note, "Why it was raised in error (measurement, drawing or "
                      "document reference)")
            if refusal:
                raise ChangeError(refusal)
        elif svc.quality_decides_concessions():
            # HARD #3 (A5-01): an issue no check closes still holds the
            # release. Unlinked: whoever closes it confirms the fix with
            # evidence, Quality or the owner department, never an admin
            # account on its own. A check no longer asked (the catalog took
            # it away): the run team closes it, naming why.
            if not retired:
                svc._require(svc.may_confirm_close(v, issue),
                             f"{issue.ref} holds the release: Quality or the "
                             "owner department confirms the fix and closes it")
            else:
                svc._require(v.admin or v.pm or v.lead,
                             "Only Project Management, the change lead or an "
                             "admin close an issue")
            from app.services.cm_rules import reference_refusal
            refusal = reference_refusal(
                note, "Why it closes (measuring report, trial or document "
                      "reference)" if retired else
                      "How the fix was confirmed (measuring report, trial or "
                      "document reference)")
            if refusal:
                raise ChangeError(refusal)
        await svc._close(session, change, issue, "closed", note, user.id)
        return issue

    # ------------------------------------------------------------------
    # §10 (RELEASE_V2): a FAIL raises its issue; the Fix task (Quality picks
    # who fixes and a retest date) and the concession run in parallel
    # ------------------------------------------------------------------
    #: Quality's fix pick -> the department that fixes (other: named)
    FIX_DEPARTMENTS = {"process_parameters": "Process Engineer",
                       "tool_at_supplier": "Tool Engineer"}
    FIX_OWNER_WORDS = {"process_parameters": "process parameters",
                       "tool_at_supplier": "tool at supplier", "other": "other"}
    #: a concession about to expire is told this many working days before
    CONCESSION_REMIND_WD = 10

    @staticmethod
    def fix_rule_on() -> bool:
        from app.services import cm_switches
        return cm_switches.on("RELEASE_V2")

    @staticmethod
    async def check_line(session: AsyncSession, change: ChangeRequest,
                         check: ValidationCheck) -> str:
        """'Part weight validated 516.2 g vs 495-515' style words of a failed
        check: the last measurement against the limits, else its value and
        note. Used by the issue, the status line and the urgent notice."""
        from app.models.change_validation import ValidationMeasurement
        from app.services import validation_checklist as catalog
        names = await ValidationIssueService._dept_names(session)
        dept = names.get(check.department_id)
        label = catalog.label_for(check.check_key, dept)
        unit = catalog.computed_unit(check.check_key, dept)
        m = (await session.execute(
            select(ValidationMeasurement)
            .where(ValidationMeasurement.check_id == check.id)
            .order_by(ValidationMeasurement.id.desc()).limit(1))).scalar_one_or_none()
        if m is not None and unit is not None:
            def f(v):
                return f"{float(v):g}"
            worst = (m.max_value if check.upper_limit is not None
                     and float(m.max_value) > float(check.upper_limit)
                     else m.min_value)
            limits = (f" vs {f(check.lower_limit)}-{f(check.upper_limit)}"
                      if check.lower_limit is not None else "")
            return f"{label} {f(worst)} {unit[1]}{limits}"
        shown = f" {float(check.value):g}" if check.value is not None else ""
        return f"{label}{shown}" + (f" ({check.note})" if check.note else "")

    @staticmethod
    async def on_check_failed(session: AsyncSession, change: ChangeRequest,
                              check: ValidationCheck, user: User):
        """A check turned FAILED (RELEASE_V2): its issue is raised at once
        (VI-n, linked, owner = the check's department) unless one is open,
        so Quality's Fix task exists without a manual raise; the Sales
        owner hears of a failed weight; an urgent change's Management (no
        Management members: Project Management) gets the status line now."""
        svc = ValidationIssueService
        if not svc.fix_rule_on():
            return None
        if change.status not in ("in_implementation", "in_validation"):
            # nobody could work an issue raised on a released or closed
            # change (the work window): no issue, no notices
            return None
        issue = (await session.execute(
            select(ValidationIssue).where(
                ValidationIssue.check_id == check.id,
                ValidationIssue.status.not_in(ISSUE_DONE_STATUSES)).limit(1)
        )).scalar_one_or_none()
        line = await svc.check_line(session, change, check)
        if issue is None and not await svc.check_retired(session, check):
            number = ((await session.execute(
                select(func.max(ValidationIssue.number)).where(
                    ValidationIssue.change_id == change.id))).scalar() or 0) + 1
            from app.services import validation_checklist as catalog
            names = await svc._dept_names(session)
            label = catalog.label_for(check.check_key, names.get(check.department_id))
            issue = ValidationIssue(
                change_id=change.id, number=number,
                title=f"{label} failed"[:200],
                category=svc.category_for_check(check.check_key), severity=2,
                department_id=check.department_id, check_id=check.id,
                description=line, status="open", escalation_level=1,
                created_by=user.id, created_at=datetime.utcnow(),
                updated_at=datetime.utcnow())
            session.add(issue)
            await session.flush()
            await svc._log(session, change, issue, "raised",
                           f"raised from the failed check: {line}", user.id,
                           notes=line, check_id=check.id, severity=2,
                           category=issue.category, automatic=True,
                           department_id=issue.department_id)
            await svc._record_escalation(session, change, issue, 1, "raised",
                                         f"Validation failed: {line}", user.id)
            await svc.reevaluate(session, change, issue, user.id)
        from app.services.notification_service import NotificationService
        from app.services import validation_checklist as catalog
        if (check.check_key == catalog.WEIGHT_KEY and change.sales_owner_id
                and change.sales_owner_id != user.id):
            await NotificationService.notify_once(
                session, [change.sales_owner_id], kind="validation_weight_failed",
                subject_key=f"vc:{check.id}:failed",
                title=f"{change.change_number}: weight check failed"[:255],
                body=f"{line}. Fix and retest, or a concession (Quality); "
                     "the quote may need the new weight.",
                link=f"/changes/{change.id}?tab=release")
        from app.services.due_rules import is_urgent
        if is_urgent(change):
            org = await svc.change_org_id(session, change)
            mgmt = await svc._dept_id(session, MANAGEMENT_DEPARTMENT)
            users = await svc._dept_members(session, [mgmt], org) if mgmt else set()
            if not users:     # P4 default until Management is seeded
                users = await svc._dept_members(
                    session, [await svc._dept_id(session, PM_DEPARTMENT)], org)
            status_line = (await svc.release_line(session, change)) or line
            await NotificationService.notify_once(
                session, sorted(users - {user.id}), kind="validation_urgent_fail",
                subject_key=f"vc:{check.id}:urgent_fail",
                title=f"{change.change_number} (urgent): validation failed"[:255],
                body=status_line, link=f"/changes/{change.id}?tab=release")
        return issue

    @staticmethod
    async def set_fix(session: AsyncSession, change: ChangeRequest, iid: int,
                      spec: dict, user: User) -> ValidationIssue:
        """Quality's Fix task (§10): who fixes (process parameters / tool at
        supplier / other + department) and the retest date. May be set
        again (a new owner or date). The check's own department retests."""
        svc = ValidationIssueService
        if not svc.fix_rule_on():
            raise ChangeError("The Fix task is part of the release rules "
                              "(RELEASE_V2), switched off")
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid, lock=True)
        svc._require(v.quality, "Quality picks who fixes and the retest date")
        svc._require_open(issue)
        svc._require_work_window(change)
        kind = spec.get("owner")
        if kind not in FIX_OWNERS:
            raise ChangeError("Who fixes: process parameters, tool at supplier "
                              "or other (with the department)")
        dept_id = spec.get("department_id")
        if kind in svc.FIX_DEPARTMENTS and dept_id is None:
            dept_id = await svc._dept_id(session, svc.FIX_DEPARTMENTS[kind])
        from app.services.change_people import department_is_active
        if dept_id is None or not await department_is_active(session, dept_id):
            raise ChangeError("Name the department that fixes it (an active "
                              "department)")
        supplier = _txt(spec.get("supplier_name"), "The supplier", required=False,
                        limit=120)
        if kind == "tool_at_supplier":
            if not supplier and not issue.supplier_name:
                raise ChangeError("Tool at supplier: name the supplier")
            issue.supplier_name = supplier or issue.supplier_name
        due = _d(spec.get("retest_due"))
        if due is None:
            raise ChangeError("Give the retest date")
        if due < business_today():
            raise ChangeError(f"The retest date {due.isoformat()} is in the past")
        old = (issue.fix_owner_kind, issue.fix_department_id, issue.retest_due)
        issue.fix_owner_kind = kind
        issue.fix_department_id = dept_id
        issue.retest_due = due
        issue.fix_set_by = user.id
        issue.fix_set_at = datetime.utcnow()
        issue.updated_at = datetime.utcnow()
        await session.flush()
        names = await svc._dept_names(session)
        await svc._log(session, change, issue, "fix_set",
                       f"fix: {names.get(dept_id)} ({svc.FIX_OWNER_WORDS[kind]}), "
                       f"retest {due.isoformat()}", user.id,
                       owner=kind, department_id=dept_id,
                       retest_due=due.isoformat(),
                       **({"previous": {"owner": old[0], "department_id": old[1],
                                        "retest_due": old[2].isoformat()}}
                          if old[0] else {}))
        await svc._notify_fix(session, change, issue, names, user)
        return issue

    @staticmethod
    async def _notify_fix(session, change: ChangeRequest, issue: ValidationIssue,
                          names: dict, user: User) -> None:
        """§10 (R5/R33): Quality's pick tells the fix department and the
        check's department (it retests), once per pick; a department with
        no real member here: the lead (no lead: PM), who coordinates."""
        from app.services.change_people import department_members_of_change_org
        from app.services.notification_service import NotificationService
        chk = (await session.get(ValidationCheck, issue.check_id)
               if issue.check_id is not None else None)
        retest_dept = chk.department_id if chk is not None else issue.department_id
        users: set[int] = set()
        for did in {issue.fix_department_id, retest_dept} - {None}:
            members = await department_members_of_change_org(
                session, change, [did], real_only=True)
            if not members:
                if change.lead_id:
                    members = [change.lead_id]
                else:
                    pm = await ValidationIssueService._dept_id(session, PM_DEPARTMENT)
                    members = await department_members_of_change_org(
                        session, change, [pm] if pm else [], real_only=True)
            users |= set(members)
        due = issue.retest_due.strftime("%a %d %b")
        await NotificationService.notify_once(
            session, sorted(users - {user.id}), kind="task_new",
            subject_key=(f"vi:{issue.id}:fix:{issue.fix_department_id}:"
                         f"{issue.retest_due.isoformat()}"),
            title=(f"{change.change_number} {issue.ref}: fix by "
                   f"{names.get(issue.fix_department_id)}, retest {due}")[:255],
            body=(f"{issue.description}. Fix: {names.get(issue.fix_department_id)}"
                  f" ({ValidationIssueService.FIX_OWNER_WORDS.get(issue.fix_owner_kind, '')}); "
                  f"retest by {names.get(retest_dept)} on {due} in validation."),
            link=ValidationIssueService._link(change, issue))

    @staticmethod
    def is_concession(issue: ValidationIssue) -> bool:
        return issue.route == "customer_concession"

    @staticmethod
    async def request_concession(session: AsyncSession, change: ChangeRequest,
                                 iid: int, spec: dict, user: User) -> ValidationIssue:
        """Quality asks for a concession beside the fix (§10). A customer
        change: the issue's route becomes the concession and the Sales owner
        asks the customer ("Waiting for customer"); Quality decides once the
        customer's mail is filed. An internal change: the parts are "not for
        shipment" and Quality decides now, for a quantity or until a date."""
        svc = ValidationIssueService
        if not svc.fix_rule_on():
            raise ChangeError("Request concession is part of the release rules "
                              "(RELEASE_V2), switched off")
        v = await svc.viewer(session, change, user)
        issue = await svc.get_issue(session, change, iid, lock=True)
        svc._require(v.quality, "A concession is Quality's: only a Quality "
                                "member requests and decides it")
        svc._require_open(issue)
        svc._require_work_window(change)
        if issue.route not in (None, "customer_concession"):
            raise ChangeError(
                f"{issue.ref} is already on the route '{issue.route}': the fix "
                "runs there; a concession is asked on an issue without a route")
        note = _txt(spec.get("note"), "What the concession covers")
        if not change.customer_relevant:
            if not spec.get("not_for_shipment"):
                raise ChangeError("Internal change: confirm the parts are not "
                                  "for shipment")
            qty, until = svc._concession_bounds(spec)
            issue.route = "customer_concession"
            issue.route_reason = f"Concession (internal, not for shipment): {note}"
            issue.route_decided_at = datetime.utcnow()
            issue.route_decided_by = user.id
            issue.concession_requested_at = datetime.utcnow()
            issue.concession_requested_by = user.id
            issue.concession_not_for_shipment = True
            issue.concession_quantity = qty
            issue.concession_until = until
            issue.customer_decision = "accept_deviation"
            issue.customer_decision_note = note
            issue.customer_decided_at = datetime.utcnow()
            issue.customer_decided_by = user.id
            issue.customer_decided_as_quality = True
            await session.flush()
            await svc._log(session, change, issue, "concession",
                           "concession accepted by Quality (internal, not for "
                           "shipment)", user.id, notes=note,
                           quantity=qty, until=until.isoformat() if until else None)
            await svc._close(session, change, issue, "accepted", note, user.id,
                             "closed: accepted under concession (not for shipment)")
            return issue
        if issue.route == "customer_concession":
            raise ChangeError(f"A concession on {issue.ref} is already asked")
        issue.route = "customer_concession"
        issue.route_reason = f"Concession requested by Quality: {note}"
        issue.route_decided_at = datetime.utcnow()
        issue.route_decided_by = user.id
        issue.customer_inform = True
        issue.concession_requested_at = datetime.utcnow()
        issue.concession_requested_by = user.id
        issue.status = "route_decided"
        issue.updated_at = datetime.utcnow()
        await session.flush()
        await svc._log(session, change, issue, "concession_requested",
                       "concession requested: the Sales owner asks the customer",
                       user.id, notes=note)
        if change.sales_owner_id:
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [change.sales_owner_id], kind="task_new",
                subject_key=f"vi:{issue.id}:concession",
                title=(f"{change.change_number} {issue.ref}: ask the customer "
                       "for a concession")[:255],
                body=f"{issue.description}. {note}",
                link=svc._link(change, issue))
        await svc.reevaluate(session, change, issue, user.id)
        return issue

    @staticmethod
    def _concession_bounds(spec: dict):
        """(quantity, until): a concession is for a quantity or until a date."""
        qty = spec.get("quantity")
        if qty in ("", None):
            qty = None
        else:
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                raise ChangeError("The quantity is a whole number of parts")
            if qty < 1:
                raise ChangeError("The quantity is at least 1 part")
        until = _d(spec.get("concession_until") or spec.get("until"))
        if until is not None and until < business_today():
            raise ChangeError(f"The concession ends {until.isoformat()}, in the past")
        if qty is None and until is None:
            raise ChangeError("A concession is for a quantity of parts or until a date")
        return qty, until

    @staticmethod
    def concession_in_force(issue: ValidationIssue,
                            today: Optional[date] = None) -> bool:
        """A concession is for a quantity or until a date (§10): after that
        date it no longer covers the failed check (HARD #3 holds again)."""
        return (issue.concession_until is None
                or issue.concession_until >= (today or business_today()))

    @staticmethod
    async def active_concessions(session: AsyncSession,
                                 change: ChangeRequest) -> list[dict]:
        """Accepted concessions still in force (§10-§11 header): 'Accepted
        under concession VI-n until <date>' or 'for n parts'."""
        rows = (await session.execute(
            select(ValidationIssue).where(
                ValidationIssue.change_id == change.id,
                ValidationIssue.status == "accepted",
                ValidationIssue.route == "customer_concession")
            .order_by(ValidationIssue.number))).scalars().all()
        today = business_today()
        out = []
        for i in rows:
            if not ValidationIssueService.concession_in_force(i, today):
                continue
            bound = (f" until {i.concession_until.isoformat()}" if i.concession_until
                     else f" for {i.concession_quantity} parts"
                     if i.concession_quantity else "")
            out.append({"id": i.id, "ref": i.ref, "until": i.concession_until,
                        "quantity": i.concession_quantity,
                        "not_for_shipment": bool(i.concession_not_for_shipment),
                        "text": f"Accepted under concession {i.ref}{bound}"
                                + (" (not for shipment)"
                                   if i.concession_not_for_shipment else "")})
        return out

    @staticmethod
    async def release_line(session: AsyncSession, change: ChangeRequest) -> Optional[str]:
        """§10 status line, one per failed check not covered: 'Not
        releasable: weight 516.2 g vs 495-515; fix: Process Engineer, retest
        Thu 22 Oct; concession: none'. None when nothing failed."""
        svc = ValidationIssueService
        if not svc.fix_rule_on():
            return None
        failed = (await session.execute(
            select(ValidationCheck).where(ValidationCheck.change_id == change.id,
                                          ValidationCheck.status == "failed")
            .order_by(ValidationCheck.id))).scalars().all()
        if not failed:
            return None
        names = await svc._dept_names(session)
        issues = {i.check_id: i for i in (await session.execute(
            select(ValidationIssue).where(
                ValidationIssue.change_id == change.id,
                ValidationIssue.check_id.in_([c.id for c in failed]))
            .order_by(ValidationIssue.id))).scalars().all()}
        from app.services.change_people import real_member_names
        fix_depts = {i.fix_department_id for i in issues.values() if i.fix_department_id}
        people = await real_member_names(session, change, fix_depts)
        today = business_today()
        parts = []
        for c in failed:
            if await svc.check_retired(session, c):
                continue
            i = issues.get(c.id)
            accepted = (i is not None and i.status == "accepted"
                        and svc.is_concession(i)
                        and await svc.quality_decided(session, i))
            if accepted and svc.concession_in_force(i, today):
                continue
            line = await svc.check_line(session, change, c)
            fix = "fix: not assigned (Quality)"
            if i is not None and i.fix_department_id is not None:
                who = people.get(i.fix_department_id) or []
                fix = (f"fix: {names.get(i.fix_department_id)}"
                       # §10 'Process (Payne)': the person when there is one
                       + (f" ({who[0]})" if len(who) == 1 else
                          " (no member here: the lead coordinates)" if not who else "")
                       + (f", retest {i.retest_due.strftime('%a %d %b')}"
                          if i.retest_due else ""))
            conc = "concession: none"
            if accepted:
                conc = (f"concession {i.ref} expired "
                        f"{i.concession_until.isoformat()}")
            elif i is not None and svc.is_concession(i) and i.is_open:
                if await svc.has_customer_mail(session, i):
                    conc = "concession: Quality decides"
                else:
                    asked = (i.customer_decided_at if i.customer_decision == "pending"
                             else i.concession_requested_at or i.route_decided_at)
                    conc = ("concession: waiting for customer (Sales owner"
                            + (f", asked {asked.date().isoformat()}" if asked else "")
                            + ")")
            parts.append(f"{line}; {fix}; {conc}")
        return ("Not releasable: " + " | ".join(parts)) if parts else None

    @staticmethod
    async def remind_expiring_concessions(session: AsyncSession) -> int:
        """Sweep: an accepted concession ending within 10 working days tells
        the Quality member who decided it (inactive or gone from Quality:
        the change's Quality members) and the lead, once (§10)."""
        svc = ValidationIssueService
        if not svc.fix_rule_on():
            return 0
        today = business_today()
        horizon = add_workdays(today, svc.CONCESSION_REMIND_WD)
        rows = (await session.execute(
            select(ValidationIssue).where(
                ValidationIssue.status == "accepted",
                ValidationIssue.route == "customer_concession",
                ValidationIssue.concession_until.isnot(None),
                ValidationIssue.concession_until >= today,
                ValidationIssue.concession_until <= horizon,
                ValidationIssue.concession_reminded_at.is_(None)))).scalars().all()
        from app.services.notification_service import NotificationService
        n = 0
        for i in rows:
            change = await session.get(ChangeRequest, i.change_id)
            if change is None:
                continue
            org = await svc.change_org_id(session, change)
            quality = await svc._dept_id(session, QUALITY_DEPARTMENT)
            members = await svc._dept_members(session, [quality], org)
            decider = (await session.get(User, i.customer_decided_by)
                       if i.customer_decided_by else None)
            users = ({decider.id} if decider is not None and decider.is_active
                     and decider.id in members else set(members))
            if change.lead_id:
                users.add(change.lead_id)
            await NotificationService.notify_once(
                session, sorted(users), kind="concession_expiring",
                subject_key=f"vi:{i.id}:expiring",
                title=(f"{change.change_number} {i.ref}: concession ends "
                       f"{i.concession_until.isoformat()}")[:255],
                body="Fixed and retested by then, or a new concession",
                link=svc._link(change, i))
            i.concession_reminded_at = datetime.utcnow()
            n += 1
        if n:
            await session.flush()
        return n

    # ------------------------------------------------------------------
    # Out
    # ------------------------------------------------------------------
    @staticmethod
    def _step(issue: ValidationIssue) -> str:
        if issue.status in ISSUE_DONE_STATUSES:
            return "closed"
        if issue.status in ("fixing", "revalidation"):
            return issue.status
        if issue.route is not None:
            return "route"
        if issue.root_cause:
            return "root_cause"
        if issue.containment:
            return "contained"
        return "raised"

    @staticmethod
    def _step_note(change: ChangeRequest, issue: ValidationIssue,
                   retired: bool = False) -> Optional[str]:
        """Why the next step waits, when it waits on the change and not on
        anybody's act (or why a retired check's issue closes by hand)."""
        if issue.is_open and retired:
            return ("The check it was raised on is no longer asked; close it "
                    "with a note")
        if issue.is_open and issue.status == "revalidation" and \
                issue.check_id is not None and change.status != "in_validation":
            return ("Re-check after implementation, when the change is back "
                    "in validation")
        return None

    # Acts that are not a step of the issue: never the primary button (the
    # frontend's QUIET list), add_action excepted when it is the only way on.
    QUIET_ACTS = ("edit", "attach", "escalate", "add_action", "concession_request",
                  "refix")

    @staticmethod
    def _needs_new_action(issue: ValidationIssue, actions: list) -> bool:
        """Fixing with no open action (the re-validation failed after every
        action was done): only a new fix action moves the issue on."""
        return issue.status == "fixing" and not any(
            a.status == "open" for a in actions)

    @staticmethod
    async def next_acts(session: AsyncSession, change: ChangeRequest,
                        issue: ValidationIssue, v: Viewer, actions: list,
                        escalations: list) -> tuple[list, Optional[str], list]:
        """(next_acts, primary, extra_acts) for the viewer. next_acts is
        ORDERED: the first entry outside QUIET_ACTS is the one primary
        button. Names: acknowledge contain root_cause route customer
        action_done recheck close cost add_action escalate edit attach.
        extra_acts carries the acts the card does not know yet: quote_fix,
        deescalate (and cost on a done issue: a late invoice).

        Every open state has an act for someone: raised/contained -> contain,
        root_cause, route; route_decided (concession) -> customer (Sales,
        until the customer's yes is on file with the mail); fixing ->
        action_done, or add_action as the primary when the re-validation
        failed with every action done; revalidation -> recheck (the check's
        department answers the linked check again) or close (no check)."""
        svc = ValidationIssueService
        if not issue.is_open:
            if (v.quality and issue.status == "accepted"
                    and issue.route == "customer_concession"
                    and not await svc.quality_decided(session, issue)):
                # HARD #3: a concession accepted without Quality's yes waits
                # for Quality to confirm it before it counts at release
                return ["customer"], "customer", []
            # a late invoice or the quote of the fix still land after close
            extra = []
            if v.cost_role:
                extra.append("cost")
            if (v.admin or v.sales) and issue.cost_bearer == "customer" and \
                    issue.fix_quoted_at is None:
                extra.append("quote_fix")
            return [], None, extra
        acts: list[str] = []
        # acts offered as an option, never the one primary button
        options: set[str] = set()
        owner = svc._owner_ok(v, issue)
        decided = issue.route is not None
        if any(e.acknowledged_at is None and e.trigger != "deescalate"
               and e.level >= 2 and svc.may_acknowledge(v, issue, e)
               for e in escalations):
            acts.append("acknowledge")
        if not decided and not issue.containment and owner:
            acts.append("contain")
        if not decided and not issue.root_cause and owner:
            acts.append("root_cause")
        chk = await session.get(ValidationCheck, issue.check_id) \
            if issue.check_id is not None else None
        # 4 eyes for everyone, an admin included (A5-01)
        can_route = bool(svc.route_options(v, issue, chk)) and issue.created_by != v.id
        route_ready = (not decided and can_route and change.status in WORK_STATUSES
                       and not (issue.severity == 3 and not issue.containment))
        if route_ready and (v.admin or v.pm or v.lead):
            acts.append("route")
        # with RELEASE_V2 Quality decides once Sales filed the customer's
        # mail; before that the card waits on Sales (spec §10)
        quality_concession = (v.quality and issue.route == "customer_concession"
                              and svc.quality_decides_concessions()
                              and await svc.has_customer_mail(session, issue))
        if ((v.admin or v.sales) and issue.customer_inform and (
                issue.customer_decision in (None, "pending")
                or issue.route == "customer_concession")) or quality_concession:
            # an open concession always waits on the customer (a yes recorded
            # before the route without the mail is recorded again with it);
            # with RELEASE_V2 Quality gives the yes once the mail is filed
            acts.append("customer")
        if svc.fix_rule_on() and v.quality and change.status in WORK_STATUSES:
            # §10: Quality's Fix task (who fixes, retest date) on a failed
            # check, and the concession beside it
            # the concession runs in parallel: asking the customer does not
            # take the Fix pick away, and a pick may be changed (refix)
            if chk is not None and chk.status == "failed" \
                    and issue.route in (None, "customer_concession"):
                acts.append("fix" if issue.fix_department_id is None else "refix")
            if issue.route is None:
                acts.append("concession_request")
            if route_ready and "route" not in acts:
                # a follow-up change is Quality's (HARD #3), beside the
                # concession: an option, the run team routes the fix
                acts.append("route")
                options.add("route")
        if any(a.status == "open" and svc._may_do_action(v, issue, a) for a in actions):
            acts.append("action_done")
        # a check no longer asked of its department can never pass again:
        # nobody re-checks it, the issue closes with a note at any open step
        retired = svc._retired_in(chk, v.dept_names)
        # the check is answered again in validation only: while the change is
        # back in implementation the re-check waits (step_note says so)
        fix_retest = (svc.fix_rule_on() and issue.fix_department_id is not None
                      and chk is not None and chk.status == "failed"
                      and issue.route not in FIX_ROUTES)
        if (issue.status == "revalidation" or fix_retest) and issue.check_id is not None \
                and not retired and change.status == "in_validation":
            dept = chk.department_id if chk else issue.department_id
            if svc.quality_decides_concessions():
                # HARD #3: the one rule of the check form and the retest
                # (ValidationService.write_rights): its own department; PM
                # or the lead only when it has no member here; never a real
                # admin
                if v.admin:
                    pass
                elif v.in_dept(dept):
                    acts.append("recheck")
                elif (v.lead or v.pm) and dept is not None:
                    from app.services.validation_service import ValidationService
                    if (await ValidationService.write_rights(
                            session, change, [dept], v.user)).get(dept):
                        acts.append("recheck")
            elif v.admin or v.pm or v.in_dept(dept):
                acts.append("recheck")
        if svc.quality_decides_concessions():
            # HARD #3: an issue no check closes is closed by Quality or its
            # owner department with evidence (A5-01); an open one is closed
            # as raised in error by Quality only (A5-08)
            if (issue.check_id is None and issue.status == "revalidation"
                    and svc.may_confirm_close(v, issue)) \
                    or (retired and (v.admin or v.pm or v.lead)):
                acts.append("close")
            elif v.quality and issue.check_id is None \
                    and issue.status in ("open", "contained"):
                # raised in error: an option beside the route
                acts.append("close")
                options.add("close")
        elif (v.admin or v.pm or v.lead) and (
                retired or (issue.check_id is None
                            and issue.status == "revalidation")):
            acts.append("close")
        if v.cost_role and issue.extra_cost is None:
            acts.append("cost")
        if owner and issue.route in FIX_ROUTES:
            acts.append("add_action")
        if (v.pm_or_lead or v.sales) and issue.escalation_level < 3:
            acts.append("escalate")
        if v.pm_or_lead or v.in_dept(issue.department_id) or issue.created_by == v.id:
            acts.append("edit")
        if owner or v.sales:
            acts.append("attach")
        extra = []
        if (v.admin or v.sales) and issue.cost_bearer == "customer" and \
                issue.fix_quoted_at is None:
            extra.append("quote_fix")
        if (v.admin or v.pm) and issue.escalation_level > 1:
            extra.append("deescalate")
        primary = next((a for a in acts if a not in svc.QUIET_ACTS
                        and a not in options), None)
        if svc._needs_new_action(issue, actions) and "add_action" in acts and \
                primary in (None, "cost", "customer"):
            # re-validation failed with every action done: the next step is
            # a new fix action
            primary = "add_action"
        return acts, primary, extra

    @staticmethod
    async def out_many(session: AsyncSession, change: ChangeRequest,
                       issues: list, user: User) -> list[dict]:
        from app.models.part import Part
        from app.services import validation_checklist as catalog
        svc = ValidationIssueService
        if not issues:
            return []
        v = await svc.viewer(session, change, user)
        ids = [i.id for i in issues]
        acts = await svc.actions_of(session, ids)
        escs = await svc.escalations_of(session, ids)
        atts = await svc.attachments_of(session, ids)
        names = await svc._dept_names(session)
        users = await svc._user_names(session, [
            x for i in issues for x in (
                i.created_by, i.contained_by, i.root_cause_by, i.route_decided_by,
                i.customer_decided_by, i.closed_by, i.fix_quoted_by, i.fix_set_by)]
            + [x for lst in acts.values() for a in lst for x in (a.owner_id, a.done_by, a.created_by)]
            + [x for lst in escs.values() for e in lst for x in (e.created_by, e.acknowledged_by)]
            + [a.uploaded_by for lst in atts.values() for a in lst])
        checks = {}
        cids = [i.check_id for i in issues if i.check_id]
        if cids:
            checks = {c.id: c for c in (await session.execute(
                select(ValidationCheck).where(ValidationCheck.id.in_(cids)))).scalars()}
        parts = {}
        pids = [i.affected_part_id for i in issues if i.affected_part_id]
        if pids:
            parts = dict((await session.execute(
                select(Part.id, Part.part_number).where(Part.id.in_(pids)))).all())
        follows = {}
        fids = [i.follow_up_change_id for i in issues if i.follow_up_change_id]
        if fids:
            follows = dict((await session.execute(
                select(ChangeRequest.id, ChangeRequest.change_number)
                .where(ChangeRequest.id.in_(fids)))).all())
        ctx = await svc.plan_context(session, change)
        today = business_today()
        # The extra cost is stated in the change's costing currency (its
        # costing plant's), the same one the actual costs are booked in.
        from app.services import costing_rates
        currency = await costing_rates.costing_currency_or_none(session, change)
        retired = await svc._retired_by_issue(session, issues)
        out = []
        for i in issues:
            c = checks.get(i.check_id)
            next_acts, primary, extra_acts = await svc.next_acts(
                session, change, i, v, acts[i.id], escs[i.id])
            hist = [{
                "id": e.id, "level": e.level, "trigger": e.trigger,
                "reason": e.reason, "notified": e.notified,
                "created_by": e.created_by, "created_by_name": users.get(e.created_by),
                "created_at": e.created_at,
                "acknowledged_by": e.acknowledged_by,
                "acknowledged_by_name": users.get(e.acknowledged_by),
                "acknowledged_at": e.acknowledged_at,
                "needs_ack": (e.acknowledged_at is None and e.level >= 2
                              and e.trigger != "deescalate"),
                "can_acknowledge": bool(
                    i.is_open and e.acknowledged_at is None and e.level >= 2
                    and e.trigger != "deescalate"
                    and svc.may_acknowledge(v, i, e)),
            } for e in escs[i.id]]
            latest = hist[-1] if hist else None
            out.append({
                "id": i.id, "change_id": i.change_id, "number": i.number,
                "ref": i.ref, "title": i.title, "category": i.category,
                "severity": i.severity, "department_id": i.department_id,
                "department_name": names.get(i.department_id),
                "check_id": i.check_id,
                "check_key": c.check_key if c else None,
                "check_department_id": c.department_id if c else None,
                "check": ({"id": c.id, "check_key": c.check_key,
                           "label": catalog.label_for(c.check_key,
                                                      names.get(c.department_id)),
                           "department_id": c.department_id,
                           "department_name": names.get(c.department_id),
                           "status": c.status} if c else None),
                "affected_part_id": i.affected_part_id,
                "affected_part_number": parts.get(i.affected_part_id),
                "affected_tool_ref": i.affected_tool_ref,
                "description": i.description,
                "containment": i.containment, "contained_at": i.contained_at,
                "contained_by": i.contained_by,
                "contained_by_name": users.get(i.contained_by),
                "root_cause": i.root_cause, "root_cause_at": i.root_cause_at,
                "root_cause_by": i.root_cause_by,
                "root_cause_by_name": users.get(i.root_cause_by),
                "route": i.route, "route_reason": i.route_reason,
                "route_decided_at": i.route_decided_at,
                "route_decided_by": i.route_decided_by,
                "route_decided_by_name": users.get(i.route_decided_by),
                "supplier_name": i.supplier_name, "chargeback": bool(i.chargeback),
                "customer_inform": bool(i.customer_inform),
                "customer_decision": i.customer_decision,
                "customer_decision_note": i.customer_decision_note,
                "customer_decided_at": i.customer_decided_at,
                "customer_decided_by": i.customer_decided_by,
                "customer_decided_by_name": users.get(i.customer_decided_by),
                "concession_until": i.concession_until,
                "concession_quantity": i.concession_quantity,
                "concession_not_for_shipment": bool(i.concession_not_for_shipment),
                "concession_requested_at": i.concession_requested_at,
                # §10 Fix task: who fixes and the retest date (Quality's pick)
                "fix_owner_kind": i.fix_owner_kind,
                "fix_department_id": i.fix_department_id,
                "fix_department_name": names.get(i.fix_department_id),
                "retest_due": i.retest_due,
                "fix_set_by_name": users.get(i.fix_set_by),
                "new_timing_date": i.new_timing_date,
                "customer_escalation_id": i.customer_escalation_id,
                "cost_visible": v.cost_read,
                "extra_cost": i.extra_cost if v.cost_read else None,
                "cost_set": i.extra_cost is not None,
                "currency": currency,
                "cost_bearer": i.cost_bearer,
                "fix_quoted_at": i.fix_quoted_at,
                "fix_quoted_by_name": users.get(i.fix_quoted_by),
                "can_supplement_offer": bool(
                    i.cost_bearer == "customer" and change.status in ("quoting", "quoted")),
                "follow_up_change_id": i.follow_up_change_id,
                "follow_up_change_number": follows.get(i.follow_up_change_id),
                "status": i.status, "step": svc._step(i), "is_open": i.is_open,
                "step_note": svc._step_note(change, i, retired.get(i.id, False)),
                "check_retired": retired.get(i.id, False),
                "closed_at": i.closed_at, "closed_by": i.closed_by,
                "closed_by_name": users.get(i.closed_by),
                "closure_note": i.closure_note,
                "created_by": i.created_by,
                "created_by_name": users.get(i.created_by),
                "created_at": i.created_at, "updated_at": i.updated_at,
                "actions": [{
                    "id": a.id, "issue_id": a.issue_id, "description": a.description,
                    "owner_id": a.owner_id, "owner_name": users.get(a.owner_id),
                    "department_id": a.department_id,
                    "department_name": names.get(a.department_id),
                    "due_date": a.due_date, "status": a.status,
                    "overdue": bool(a.status == "open" and a.due_date
                                    and a.due_date < today),
                    "done_at": a.done_at, "done_by": a.done_by,
                    "done_by_name": users.get(a.done_by),
                    "plan_task_id": a.plan_task_id,
                    "can_done": bool(i.is_open and a.status == "open"
                                     and svc._may_do_action(v, i, a)),
                    "created_by": a.created_by, "created_at": a.created_at,
                } for a in acts[i.id]],
                "attachments": [{
                    "id": a.id, "filename": a.filename, "kind": a.kind,
                    "content_type": a.content_type, "size_bytes": a.size_bytes,
                    "phase": a.phase, "validation_issue_id": a.validation_issue_id,
                    "uploaded_by": a.uploaded_by,
                    "uploaded_by_name": users.get(a.uploaded_by),
                    "created_at": a.created_at,
                    # the attachment DELETE rule: uploader, lead, PM, admin;
                    # the customer's mail of an accepted concession is the
                    # record (admin only)
                    "can_delete": bool(
                        (v.admin or a.uploaded_by == v.id or v.lead or v.pm)
                        and (v.admin or svc.frozen_attachment_reason(i, a) is None)),
                } for a in atts[i.id]],
                "has_customer_mail": any(a.kind == "customer_email" for a in atts[i.id]),
                "escalation_level": i.escalation_level,
                "escalations": hist,
                "escalation": {
                    "level": i.escalation_level,
                    "level_name": LEVEL_NAMES.get(i.escalation_level),
                    "unacknowledged": any(h["needs_ack"] for h in hist),
                    "latest": latest, "history": hist,
                },
                "recovery": svc.recovery_info(change, i, ctx),
                "next_acts": next_acts, "primary_act": primary,
                "extra_acts": extra_acts,
                "customer_options": svc.customer_options(v, i),
                # the routes the route dialog may offer this viewer
                "route_options": svc.route_options(v, i, checks.get(i.check_id)),
                # HARD #3: closing it needs a reference, not a free note
                "close_needs_ref": svc.quality_decides_concessions(),
                # §10: the Fix task and the bounded concession apply
                "fix_rule": svc.fix_rule_on(),
            })
        return out

    @staticmethod
    async def out_one(session, change, issue, user) -> dict:
        await session.refresh(issue)
        return (await ValidationIssueService.out_many(session, change, [issue], user))[0]

    @staticmethod
    async def summary(session: AsyncSession, change: ChangeRequest) -> dict:
        """Cockpit: open issues and the highest open escalation level."""
        issues = await ValidationIssueService.open_issues(session, change)
        top = max(issues, key=lambda i: (i.escalation_level, i.severity, -i.number),
                  default=None)
        informed_at = None
        if top is not None:
            informed_at = top.customer_decided_at
        return {
            "open_count": len(issues),
            "fixing_count": sum(1 for i in issues if i.status == "fixing"),
            "highest_level": top.escalation_level if top else None,
            "top": ({"id": top.id, "ref": top.ref, "title": top.title,
                     "level": top.escalation_level, "status": top.status,
                     "customer_inform": bool(top.customer_inform),
                     "customer_decided_at": informed_at} if top else None),
            "blocker": await ValidationIssueService.release_blocker(session, change),
            "open": [{"id": i.id, "ref": i.ref, "title": i.title,
                      "status": i.status, "level": i.escalation_level,
                      "severity": i.severity} for i in issues],
        }

    # ------------------------------------------------------------------
    # My actions (cockpit) - wired into ChangeService.my_actions in phase 2
    # ------------------------------------------------------------------
    ACT_KINDS = {
        "contain": ("validation_issue_contain", "Record the containment for {ref}"),
        "root_cause": ("validation_issue_root_cause", "Find the root cause of {ref}"),
        "route": ("validation_issue_route", "Decide the route for {ref}"),
        "action_done": ("validation_issue_action", "Finish the fix actions of {ref}"),
        "customer": ("validation_issue_customer", "Record the customer decision on {ref}"),
        "quote_fix": ("validation_issue_quote", "Quote the fix of {ref}"),
        "close": ("validation_issue_close", "Close {ref} after re-validation"),
        "recheck": ("validation_issue_recheck",
                    "Answer the linked validation check of {ref} again"),
        "add_action": ("validation_issue_add_action",
                       "Re-validation of {ref} failed: add a new fix action"),
        "fix": ("validation_issue_fix",
                "Fix {ref}: pick who fixes and the retest date"),
        "fix_work": ("validation_issue_fix_work", "Fix {ref}: {what}, retest {when}"),
    }
    #: §10 (RELEASE_V2) the concession's two tasks: Sales asks the customer
    #: and files the mail; Quality decides once it is filed
    CONCESSION_ASK = "Ask the customer about the concession for {ref} and file the mail"
    CONCESSION_DECIDE = "Decide concession {ref}: for a quantity or until a date"

    @staticmethod
    async def my_actions(session: AsyncSession, change: ChangeRequest,
                         user: User) -> list[dict]:
        """The viewer's owed acts on this change's open issues, plus one
        "Acknowledge escalation VI-n (level x)" per unacknowledged level-2/3
        escalation they were notified of."""
        svc = ValidationIssueService
        issues = await svc.open_issues(session, change)
        if not issues:
            return []
        v = await svc.viewer(session, change, user)
        ids = [i.id for i in issues]
        acts = await svc.actions_of(session, ids)
        escs = await svc.escalations_of(session, ids)
        retired = await svc._retired_by_issue(session, issues)
        from app.services.change_people import staffed_department_ids
        fix_depts = {i.fix_department_id for i in issues if i.fix_department_id}
        # §10: a fix department with no real member here hands its work task
        # to the lead (no lead: PM), never to nobody
        unstaffed_fix = (fix_depts - await staffed_department_ids(
            session, change, fix_depts)) if fix_depts and svc.fix_rule_on() else set()
        coordinates = v.lead or (change.lead_id is None and v.pm)
        pm_dept = await svc._dept_id(session, PM_DEPARTMENT)
        quality_dept = await svc._dept_id(session, QUALITY_DEPARTMENT)
        out = []
        for i in issues:
            possible, _primary, extra = await svc.next_acts(
                session, change, i, v, acts[i.id], escs[i.id])
            possible = possible + extra
            owed = []
            if "contain" in possible and not i.containment and i.severity == 3 \
                    and i.route is None and v.in_dept(i.department_id):
                owed.append("contain")
            # §10 (RELEASE_V2): a failed check's issue runs on Quality's Fix
            # task; the 8D steps stay on the card, they are not tasks
            light = svc.fix_rule_on() and i.check_id is not None
            if "root_cause" in possible and not i.root_cause and i.route is None \
                    and v.in_dept(i.department_id) and not light:
                owed.append("root_cause")
            if "route" in possible and not v.admin and not light \
                    and (v.pm or v.lead):
                # Quality's follow-up pick is an option, not a task
                owed.append("route")
            if "action_done" in possible and any(
                    a.status == "open" and (a.owner_id == v.id or v.in_dept(a.department_id))
                    for a in acts[i.id]):
                owed.append("action_done")
            concession = (i.route == "customer_concession"
                          and svc.quality_decides_concessions())
            mail = (await svc.has_customer_mail(session, i)) if concession else False
            if "customer" in possible and not v.admin and i.customer_inform and (
                    i.customer_decision in (None, "pending")
                    or i.route == "customer_concession") and not (
                    # Sales' part of a concession ends with the filed mail
                    concession and mail and not v.quality):
                owed.append("customer")
            if "quote_fix" in possible and not v.admin:
                owed.append("quote_fix")
            if "close" in possible and not v.admin and (
                    i.status == "revalidation" or retired.get(i.id)):
                owed.append("close")
            chk_dept = None
            if "recheck" in possible and not v.admin:
                chk = (await session.get(ValidationCheck, i.check_id)
                       if i.check_id is not None else None)
                chk_dept = chk.department_id if chk is not None else i.department_id
                # a department with no member here: the retest is the lead's
                # task (no lead: PM's), like its fix work
                if v.in_dept(chk_dept) or coordinates:
                    owed.append("recheck")
            if "fix" in possible and not v.admin:
                owed.append("fix")
            fix_fallback = (i.fix_department_id in unstaffed_fix and coordinates)
            if (svc.fix_rule_on() and i.fix_department_id is not None
                    and (v.in_dept(i.fix_department_id) or fix_fallback)
                    and not v.admin
                    and i.route not in FIX_ROUTES and "recheck" not in owed
                    and i.check_id is not None
                    and getattr(await session.get(ValidationCheck, i.check_id),
                                "status", None) == "failed"):
                owed.append("fix_work")
            if "add_action" in possible and not v.admin and \
                    svc._needs_new_action(i, acts[i.id]) and \
                    (v.pm or v.in_dept(i.department_id)):
                owed.append("add_action")
            for key in owed:
                kind, label = svc.ACT_KINDS[key]
                item = {"kind": kind, "target_tab": "release", "issue_id": i.id}
                if key == "fix_work":
                    label = label.format(
                        ref=i.ref, what=i.description,
                        when=i.retest_due.strftime("%a %d %b") if i.retest_due else "-")
                    if not v.in_dept(i.fix_department_id):
                        name = (await svc._dept_names(session)).get(i.fix_department_id)
                        label += f" ({name} has no member here: you coordinate)"
                elif key == "customer" and concession:
                    label = (svc.CONCESSION_DECIDE if v.quality and mail
                             else svc.CONCESSION_ASK).format(ref=i.ref)
                else:
                    label = label.format(ref=i.ref)
                if key == "close" and svc.quality_decides_concessions():
                    item["role_department_id"] = (
                        quality_dept if v.quality else i.department_id)
                if key == "recheck" and i.retest_due is not None:
                    label = f"Retest for {i.ref} by {i.retest_due.strftime('%a %d %b')}"
                if key == "recheck" and not v.in_dept(chk_dept):
                    name = (await svc._dept_names(session)).get(chk_dept)
                    label += f" ({name} has no member here: you coordinate)"
                    item["role_department_id"] = pm_dept
                item["label"] = label
                if key in ("fix_work", "recheck") and i.retest_due is not None:
                    item["due_date"] = datetime.combine(i.retest_due, datetime.max.time().replace(microsecond=0))
                elif key == "fix":
                    from app.services.due_rules import task_due
                    item["due_date"] = task_due(i.created_at, change, "validation_issue_fix")
                elif key == "customer" and concession:
                    # a few working days from the ask (Sales) or the filed
                    # mail (Quality), not the change's fallback due
                    from app.services.due_rules import task_due
                    since = ((await svc.customer_mail_at(session, i)) if v.quality and mail
                             else i.concession_requested_at or i.route_decided_at
                             or i.created_at)
                    item["due_date"] = task_due(since, change, "validation_issue_customer")
                    if v.quality and mail:
                        item["role_department_id"] = quality_dept
                if key == "fix_work":
                    item["role_department_id"] = (
                        i.fix_department_id if v.in_dept(i.fix_department_id) else pm_dept)
                elif key == "fix":
                    # Quality's pick (TeamRoles: main and backup within Quality)
                    item["role_department_id"] = quality_dept
                if key == "customer" and i.route == "customer_concession" and (
                        (v.quality and svc.quality_decides_concessions()
                         and await svc.has_customer_mail(session, i))
                        or (v.sales and not svc.quality_decides_concessions())):
                    # a concession to decide (Needs you): Quality's once the
                    # customer mail is filed (spec §0 "Concession: Quality
                    # only"); Sales only waits on the customer meanwhile.
                    # Switched off, Sales records the decision as before.
                    item["concession"] = True
                # Project team (spec §18): the department that owes the act,
                # so the task lists can tell main from backup. Route, close,
                # customer and quote follow their fixed role (KIND_DEPARTMENT).
                if key == "action_done":
                    mine = [a for a in acts[i.id] if a.status == "open"
                            and (a.owner_id == v.id or v.in_dept(a.department_id))]
                    if not any(a.owner_id == v.id for a in mine) and mine:
                        item["role_department_id"] = mine[0].department_id
                elif key in ("contain", "root_cause", "recheck", "add_action") \
                        and v.in_dept(i.department_id):
                    item["role_department_id"] = i.department_id
                out.append(item)
            for e in escs[i.id]:
                if e.acknowledged_at is None and e.level >= 2 and \
                        e.trigger != "deescalate" and \
                        svc.may_acknowledge(v, i, e) and not v.admin:
                    out.append({
                        "kind": "validation_issue_escalation",
                        "label": f"Acknowledge escalation {i.ref} (level {e.level})",
                        "target_tab": "release", "issue_id": i.id,
                        "escalation_id": e.id, "level": e.level})
        return out
