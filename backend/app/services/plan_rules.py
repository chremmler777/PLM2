"""Planning rules on the change plans (Christoph 2026-11-09).

The plan engine knows links and calendars; it does not know what a block IS.
These rules do, from what a block already carries (kind, name, lane, owner
department and the costing category of the position it was seeded from):

  a. a tool change may only start once its MOLD bank build is finished
     (it never overlaps the bank build: the molded stock is built first);
  b. a (mold) trial may only start once the tool changes and gauge changes
     are finished: trial start >= the latest of their ends;
  c. an assembly trial may only start once the line (assembly) changes are
     finished;
  d. a line change may only start once its ASSEMBLY bank build is finished.

A bank build applies to the changes it links to (any link type); a bank
build without such a link applies to every change of its pair (mold bank ->
tool changes, assembly bank -> line changes).

Committed blocks only are enforced: a violation between two committed blocks
is an error (and a write that creates one is refused), one that involves an
idea is a warning (an idea is a proposal, not a promise). Old data already
breaking a rule does not block unrelated edits; only a NEW violation does.

The same classifier and rules run in the browser (frontend
components/changes/plan/planRules.ts) so a drag is refused before it is
sent; this module is the authority.
"""
import re
from datetime import date, timedelta
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.display import fmt_date

# ---------------------------------------------------------------- roles
TOOL_CHANGE = "tool_change"
GAUGE_CHANGE = "gauge_change"
LINE_CHANGE = "line_change"
MOLD_BANK = "mold_bank_build"
ASSEMBLY_BANK = "assembly_bank_build"
TRIAL = "trial"
ASSEMBLY_TRIAL = "assembly_trial"
ROLES = (TOOL_CHANGE, GAUGE_CHANGE, LINE_CHANGE, MOLD_BANK, ASSEMBLY_BANK,
         TRIAL, ASSEMBLY_TRIAL)
ROLE_LABELS = {
    TOOL_CHANGE: "Tool change", GAUGE_CHANGE: "Gauge change",
    LINE_CHANGE: "Line change", MOLD_BANK: "Mold bank build",
    ASSEMBLY_BANK: "Assembly bank build", TRIAL: "Trial",
    ASSEMBLY_TRIAL: "Assembly trial",
}

# Costing categories (services/costing_tags.py) of the seeding position.
TOOL_TAGS = {"tool_change", "steel_insert", "hot_runner", "tool_transfer"}
GAUGE_TAGS = {"gauge_change", "measurement_equipment"}
LINE_TAGS = {"fixture_change", "eoat_change", "equipment_change", "line_layout"}
#: bought alongside, never a change of the tool / line itself
NEUTRAL_TAGS = {"spare_part"}
#: the department that owns assembly equipment (engineering review map)
ASSEMBLY_DEPARTMENTS = {"Manufacturing Engineer"}

ASSEMBLY_RX = re.compile(r"assembl|montage|\bline\b|linie", re.I)
GAUGE_RX = re.compile(r"gauge|lehre|checking fixture|pr(?:ue|ü)fmittel", re.I)
TOOL_RX = re.compile(r"tool change|tool rework|werkzeug(?:ä|ae)nderung", re.I)
LINE_RX = re.compile(r"line change|assembly line|linien(?:ä|ae)nderung", re.I)


def classify(kind: Optional[str], name: Optional[str], lane: Optional[str],
             department_name: Optional[str], tag: Optional[str]) -> Optional[str]:
    """What a block is for the planning rules, or None (not part of them).
    Mirrored 1:1 in frontend planRules.ts `classify`."""
    kind = kind or "work"
    name = name or ""
    owners = {(lane or "").strip(), (department_name or "").strip()}
    assembly_owner = bool(owners & ASSEMBLY_DEPARTMENTS)
    if kind == "bank_build":
        return ASSEMBLY_BANK if (ASSEMBLY_RX.search(name) or assembly_owner) \
            else MOLD_BANK
    if kind == "sampling":
        return ASSEMBLY_TRIAL if (ASSEMBLY_RX.search(name) or assembly_owner) \
            else TRIAL
    if kind not in ("work", "supplier", "downtime"):
        return None
    if tag in NEUTRAL_TAGS:
        return None
    if tag in GAUGE_TAGS or GAUGE_RX.search(name):
        return GAUGE_CHANGE
    if tag in LINE_TAGS or LINE_RX.search(name) \
            or (kind in ("supplier", "downtime") and assembly_owner):
        return LINE_CHANGE
    if tag in TOOL_TAGS or kind == "downtime" or TOOL_RX.search(name):
        return TOOL_CHANGE
    return None


# ---------------------------------------------------------------- rules
def _end(t) -> date:
    """Exclusive end (the day the block is finished by)."""
    return t.end_date


def _last(t) -> date:
    d = int(t.duration_days or 0)
    return t.end_date - timedelta(days=1) if d > 0 else t.start_date


def check(tasks: list, links: Iterable, roles: dict) -> list[dict]:
    """Every rule violation of a plan as dicts {code, message, task_id,
    other_id, idea}. `roles`: task id -> role. Summary blocks never count."""
    parents = {t.parent_id for t in tasks if getattr(t, "parent_id", None)}
    leaves = [t for t in tasks if t.id not in parents]
    by_role: dict[str, list] = {r: [] for r in ROLES}
    for t in leaves:
        r = roles.get(t.id)
        if r in by_role:
            by_role[r].append(t)
    linked: dict[int, set] = {}
    for lk in links or []:
        linked.setdefault(lk.from_task_id, set()).add(lk.to_task_id)
    out: list[dict] = []

    def add(code, msg, t, other):
        out.append({"code": code, "message": msg, "task_id": t.id,
                    "other_id": other.id,
                    "idea": bool(t.is_idea or other.is_idea)})

    def banks(bank_role, change_role, code, what, bank_word):
        for b in by_role[bank_role]:
            own = [c for c in by_role[change_role] if c.id in linked.get(b.id, ())]
            for c in own or by_role[change_role]:
                if c.start_date < _end(b):
                    add(code,
                        f"{what} '{c.name}' starts {fmt_date(c.start_date)}, "
                        f"before the {bank_word} bank build '{b.name}' is "
                        f"finished ({fmt_date(_last(b))}): the {what.lower()} "
                        f"may only start after the {bank_word} bank build",
                        c, b)

    banks(MOLD_BANK, TOOL_CHANGE, "tool_change_during_bank_build",
          "Tool change", "mold")
    banks(ASSEMBLY_BANK, LINE_CHANGE, "line_change_during_bank_build",
          "Line change", "assembly")

    def trials(trial_role, pre_roles, code, what, needs):
        pre = [p for r in pre_roles for p in by_role[r]]
        for tr in by_role[trial_role]:
            late = [p for p in pre if tr.start_date < _end(p)]
            if not late:
                continue
            p = max(late, key=_end)
            add(code,
                f"{what} '{tr.name}' starts {fmt_date(tr.start_date)}, before "
                f"'{p.name}' is finished ({fmt_date(_last(p))}): {needs}",
                tr, p)

    trials(TRIAL, (TOOL_CHANGE, GAUGE_CHANGE), "trial_before_change_done",
           "Trial", "a trial may only start once the tool and gauge "
           "changes are finished")
    trials(ASSEMBLY_TRIAL, (LINE_CHANGE,), "assembly_trial_before_line_done",
           "Assembly trial", "an assembly trial may only start once the line "
           "change is finished")
    return out


def violation_keys(found: list[dict]) -> set:
    return {(v["code"], v["task_id"], v["other_id"])
            for v in found if not v["idea"]}


def as_issues(found: list[dict]) -> dict:
    """Into the plan's validation shape: committed -> errors, ideas -> warnings."""
    errors, warnings = [], []
    for v in found:
        item = {"code": v["code"], "message": v["message"], "task_id": v["task_id"]}
        (warnings if v["idea"] else errors).append(item)
    return {"errors": errors, "warnings": warnings}


# ---------------------------------------------------------------- plan I/O
async def roles_of(session: AsyncSession, tasks: list) -> tuple[dict, dict]:
    """({task id -> role or None}, {position id -> costing tag}) of the
    stored blocks."""
    from app.models.change_cost import CostingPosition
    from app.models.workflow import Department
    names = dict((await session.execute(
        select(Department.id, Department.name))).all())
    pos_ids = {t.source_position_id for t in tasks if t.source_position_id}
    tags = {}
    if pos_ids:
        tags = dict((await session.execute(
            select(CostingPosition.id, CostingPosition.tag)
            .where(CostingPosition.id.in_(pos_ids)))).all())
    return {t.id: classify(t.kind, t.name, t.lane, names.get(t.department_id),
                           tags.get(t.source_position_id))
            for t in tasks}, tags


async def evaluate(session: AsyncSession, change, plan: str) -> dict:
    """{roles, tags, violations} of a stored plan (pending session state
    included: queries autoflush)."""
    from app.services.change_plan_service import ChangePlanService
    tasks = await ChangePlanService.tasks(session, change, plan)
    links = await ChangePlanService.links(session, change, plan)
    roles, tags = await roles_of(session, tasks)
    return {"roles": roles, "tags": tags,
            "violations": check(tasks, links, roles)}


async def snapshot(session: AsyncSession, change, plan: str) -> set:
    return violation_keys((await evaluate(session, change, plan))["violations"])


async def refuse_new(session: AsyncSession, change, plan: str, before: set) -> None:
    """Raise PlanRuleError when the edit created a rule violation between
    committed blocks that was not there before."""
    from app.services.change_plan_service import PlanRuleError
    found = (await evaluate(session, change, plan))["violations"]
    new = [v for v in found if not v["idea"]
           and (v["code"], v["task_id"], v["other_id"]) not in before]
    if new:
        raise PlanRuleError(new[0]["message"], new[0]["code"])


# ---------------------------------------------------------------- reset
def reset_blocked_reason(change, plan: str, editor: bool) -> Optional[str]:
    """Why the plan may not be reset or deleted now (None: it may)."""
    from app.services.change_plan_service import ChangePlanService as S
    if not editor:
        return ("Only Sales, Project Management, Logistics, the change lead "
                "or an admin may reset or delete the plan")
    if plan == "quote" and S.offer_accepted(change):
        return ("The quote plan cannot be reset or deleted: the customer "
                "accepted the offer on it, so it is the timing the customer "
                "agreed. Timing changes go into the detailed plan once the "
                "change is approved.")
    if change.status not in S._window(plan):
        return (f"The {plan} plan cannot be reset or deleted while the change "
                f"is '{change.status}'")
    if S.baselined(change, plan):
        return ("The detailed plan cannot be reset or deleted: timing was "
                "validated (the baseline is what the customer was told). "
                "Dates now only move as deviations with a reason.")
    return None


async def reset_plan(session: AsyncSession, change, plan: str, user, *,
                     reseed: bool) -> None:
    """Delete every block and link of the plan; with `reseed` seed it again
    (quote: from the costing, detailed: from the quote plan). Logged in the
    change log; refused with the reason of reset_blocked_reason."""
    from app.services.change_plan_service import (
        ChangePlanService as S, PlanForbidden, PlanRuleError,
    )
    from app.services.change_service import ChangeService
    S._check_plan(plan)
    editor = await S.is_editor(session, change, user)
    why = reset_blocked_reason(change, plan, editor)
    if why:
        if not editor:
            raise PlanForbidden(why)
        raise PlanRuleError(why, "plan_locked")
    existing = await S.tasks(session, change, plan)
    if existing:
        await S._clear(session, change, plan)
    if plan == "detailed":
        # the teams confirmed a plan that is gone
        change.plan_revision = int(change.plan_revision or 0) + 1
    word = "reset" if reseed else "deleted"
    await ChangeService.append_changelog(
        session, change, "plan_reset" if reseed else "plan_deleted",
        f"{plan.capitalize()} plan {word}: {len(existing)} block(s) removed"
        + (", seeded again" if reseed else ", left empty"), user.id,
        old_value={"plan": plan, "tasks": len(existing)},
        new_value={"plan": plan, "reseed": reseed})
    if reseed:
        await S.seed(session, change, plan, user)
