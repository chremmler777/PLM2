"""Prefill the project team (migration 097, project_responsibles) for the
Brose 1994, Brose 2277 and VW426 Atlas projects, as the owner decided on
2026-09-25:

    Project Manager         Cody
    Manufacturing Engineer  Russ
    Tool Engineer           Dale
    APQP                    George (VW426: Apurva M.)
    Development             Christoph

Projects and users are matched by name, case-insensitive: projects on code,
then name, then "code or name contains"; users on the known username, then
the e-mail local part, then first name (+ last initial) in the full name or
the username split on '.', '_', '-' and spaces, then a prefix / close match.
The best tier that finds anybody wins; when it finds more than one, the row
is AMBIGUOUS and nothing is guessed: resolve it with --project-id / --user-id.

Dry run by default: prints every proposed row and every problem. --apply
writes, and only when no row has a problem (unless --partial). Idempotent: a
row that already names the user is left alone. It never replaces another
responsible (unless --replace) and never adds a department membership (unless
--add-membership): the service only counts a responsible who is an active
member of the department in the project's organization.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/prefill_project_team.py [--apply] [--actor-id N] \\
        [--project-id VW426=33] [--user-id Russ=41] [--add-membership]
"""
from __future__ import annotations

import argparse
import asyncio
import difflib
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.entities import Plant, Project, User
from app.models.workflow import Department, ProjectResponsible, UserDepartment
from app.services.project_team_service import DEVELOPMENT, PM

# Department names are the role keys ProjectTeamService looks up
# (Department.name == ...). PM and DEVELOPMENT come from the service itself.
MFG = "Manufacturing Engineer"
TOOL = "Tool Engineer"
APQP = "APQP"


@dataclass(frozen=True)
class Person:
    label: str                       # how the owner named them
    first: str                       # first name
    last_initial: str = ""           # "M" for "Apurva M."
    usernames: tuple[str, ...] = ()  # known hub usernames (strongest match)


CODY = Person("Cody", "cody", usernames=("cody.hrtyanski",))
RUSS = Person("Russ", "russ")
DALE = Person("Dale", "dale", usernames=("dale.perry",))
GEORGE = Person("George", "george")
APURVA = Person("Apurva M.", "apurva", "m", usernames=("apurvam",))
CHRISTOPH = Person("Christoph", "christoph", usernames=("christoph.demmler",))

BASE_TEAM = {PM: CODY, MFG: RUSS, TOOL: DALE, APQP: GEORGE, DEVELOPMENT: CHRISTOPH}

# project token -> {department name: person}
TEAM: dict[str, dict[str, Person]] = {
    "1994": dict(BASE_TEAM),
    "2277": dict(BASE_TEAM),
    "VW426": {**BASE_TEAM, APQP: APURVA},
}

OK_STATUSES = {"set", "unchanged", "replace"}


@dataclass
class Row:
    project_token: str
    department: str
    person: str
    status: str                      # set | unchanged | replace | <problem>
    project_id: Optional[int] = None
    project_label: str = ""
    department_id: Optional[int] = None
    user_id: Optional[int] = None
    user_label: str = ""
    add_membership: bool = False
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in OK_STATUSES


@dataclass
class Plan:
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[Row]:
        return [r for r in self.rows if not r.ok]


# ----------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------
def _tokens(*texts: Optional[str]) -> list[list[str]]:
    """Each text split into lowercase name tokens."""
    return [[t for t in re.split(r"[\s._\-@]+", x.lower()) if t] for x in texts if x]


def _user_label(u: User) -> str:
    name = u.full_name if u.full_name and u.full_name != u.username else ""
    return f"#{u.id} {u.username}" + (f" ({name})" if name else "")


def _project_label(p: Project) -> str:
    return f"#{p.id} {p.code} {p.name}"


def match_users(person: Person, users: list[User]) -> tuple[list[User], str]:
    """The users of the best tier that finds anybody, and the tier's name."""
    first, initial = person.first.lower(), person.last_initial.lower()
    hints = {h.lower() for h in person.usernames}

    def local(u: User) -> str:
        return (u.email or "").split("@")[0].lower()

    def name_hit(u: User) -> bool:
        for toks in _tokens(u.full_name, u.username):
            if toks and toks[0] == first and (
                    not initial or any(t.startswith(initial) for t in toks[1:])):
                return True
        if initial and (u.username or "").lower() == first + initial:
            return True
        return False

    def fuzzy_hit(u: User) -> bool:
        for toks in _tokens(u.full_name, u.username):
            if toks and (toks[0].startswith(first)
                         or difflib.SequenceMatcher(None, toks[0], first).ratio() >= 0.8):
                return not initial or any(t.startswith(initial) for t in toks[1:])
        return False

    tiers = [
        ("username", lambda u: (u.username or "").lower() in hints),
        ("e-mail", lambda u: local(u) in hints),
        ("name", name_hit),
        ("fuzzy", fuzzy_hit),
    ]
    for tier, hit in tiers:
        found = [u for u in users if hit(u)]
        if found:
            return found, tier
    return [], ""


def match_projects(token: str, projects: list[Project]) -> tuple[list[Project], str]:
    t = token.lower()
    tiers = [
        ("code", lambda p: (p.code or "").lower() == t),
        ("name", lambda p: (p.name or "").lower() == t),
        ("contains", lambda p: t in (p.code or "").lower() or t in (p.name or "").lower()),
    ]
    for tier, hit in tiers:
        found = [p for p in projects if hit(p)]
        if found:
            return found, tier
    return [], ""


# ----------------------------------------------------------------------
# Plan and apply
# ----------------------------------------------------------------------
async def plan_team(session: AsyncSession, team: dict[str, dict[str, Person]] = TEAM,
                    project_ids: Optional[dict[str, int]] = None,
                    user_ids: Optional[dict[str, int]] = None,
                    add_membership: bool = False, replace: bool = False) -> Plan:
    """Every (project, department) row of `team`, resolved against the DB.
    `project_ids` / `user_ids` pin a token / person label to an id (the way
    to resolve an ambiguity). Reads only."""
    project_ids = {k.lower(): v for k, v in (project_ids or {}).items()}
    user_ids = {k.lower(): v for k, v in (user_ids or {}).items()}
    plan = Plan()

    projects = list((await session.execute(select(Project))).scalars().all())
    users_all = list((await session.execute(select(User))).scalars().all())
    active = [u for u in users_all if u.is_active]
    by_id = {u.id: u for u in users_all}
    depts = {d.name: d for d in (await session.execute(select(Department))).scalars().all()}
    org_of = dict((await session.execute(
        select(Project.id, Plant.organization_id).join(Plant, Plant.id == Project.plant_id)
    )).all())
    members = {(uid, did) for uid, did in (await session.execute(
        select(UserDepartment.user_id, UserDepartment.department_id))).all()}
    current = {(r.project_id, r.department_id): r.user_id for r in (await session.execute(
        select(ProjectResponsible))).scalars().all()}

    # Resolve each person once, so a problem is reported once per person.
    resolved: dict[str, tuple[Optional[User], str]] = {}
    for person in {p for roles in team.values() for p in roles.values()}:
        pinned = user_ids.get(person.label.lower())
        if pinned is not None:
            u = by_id.get(pinned)
            resolved[person.label] = ((u, "") if u is not None and u.is_active else
                                      (None, f"no_user: --user-id {person.label}={pinned} "
                                             "is not an active user"))
            continue
        found, tier = match_users(person, active)
        if len(found) == 1:
            resolved[person.label] = (found[0], "")
            others = [u for u in active if u.id != found[0].id and
                      match_users(Person(person.label, person.first, person.last_initial),
                                  [u])[0]]
            if others:
                plan.notes.append(
                    f"{person.label}: matched {_user_label(found[0])} by {tier}; also "
                    f"similar: {', '.join(_user_label(u) for u in others)}")
        elif found:
            resolved[person.label] = (None, "ambiguous_user: " + ", ".join(
                _user_label(u) for u in found) + f" (by {tier}); pin with --user-id "
                f"'{person.label}=<id>'")
        else:
            inactive = [u for u in users_all if not u.is_active
                        and match_users(person, [u])[0]]
            hint = (f"; inactive matches: {', '.join(_user_label(u) for u in inactive)}"
                    if inactive else "; users are created on first hub login")
            resolved[person.label] = (None, "no_user: nobody matches" + hint)

    for token, roles in team.items():
        pinned = project_ids.get(token.lower())
        if pinned is not None:
            found = [p for p in projects if p.id == pinned]
            tier = "--project-id"
        else:
            found, tier = match_projects(token, projects)
        project = found[0] if len(found) == 1 else None
        if project is None:
            status = ("ambiguous_project: " + ", ".join(_project_label(p) for p in found)
                      + f" (by {tier}); pin with --project-id {token}=<id>"
                      if found else "no_project: nothing matches")
            for dept_name, person in roles.items():
                kind, _, why = status.partition(": ")
                plan.rows.append(Row(token, dept_name, person.label, kind, detail=why))
            continue
        org_id = org_of.get(project.id)
        for dept_name, person in roles.items():
            row = Row(token, dept_name, person.label, "set", project_id=project.id,
                      project_label=_project_label(project))
            plan.rows.append(row)
            dept = depts.get(dept_name)
            if dept is None:
                row.status, row.detail = "no_department", f"no department named {dept_name!r}"
                continue
            row.department_id = dept.id
            if not dept.is_active:
                row.status, row.detail = "department_inactive", f"{dept_name} is inactive"
                continue
            user, problem = resolved[person.label]
            if user is None:
                row.status, _, row.detail = problem.partition(": ")
                continue
            row.user_id, row.user_label = user.id, _user_label(user)
            if org_id is not None and user.organization_id != org_id:
                row.status = "wrong_org"
                row.detail = (f"user is in organization {user.organization_id}, "
                              f"the project in {org_id}")
                continue
            if (user.id, dept.id) not in members:
                if add_membership:
                    row.add_membership = True
                else:
                    row.status = "not_member"
                    row.detail = (f"not a member of {dept_name}; add the membership in "
                                  "PLM or rerun with --add-membership")
                    continue
            have = current.get((project.id, dept.id))
            if have == user.id:
                row.status = "unchanged"
            elif have is not None:
                who = by_id.get(have)
                was = _user_label(who) if who else f"#{have}"
                if replace:
                    row.status, row.detail = "replace", f"replaces {was}"
                else:
                    row.status = "taken"
                    row.detail = f"already {was}; rerun with --replace to overwrite"
    return plan


async def apply_plan(session: AsyncSession, plan: Plan,
                     actor_id: Optional[int] = None) -> dict[str, int]:
    """Write the ok rows of the plan (the caller commits)."""
    counts = {"set": 0, "replace": 0, "unchanged": 0, "memberships": 0}
    for row in plan.rows:
        if not row.ok:
            continue
        if row.add_membership:
            exists = (await session.execute(select(UserDepartment).where(
                UserDepartment.user_id == row.user_id,
                UserDepartment.department_id == row.department_id))).scalar_one_or_none()
            if exists is None:
                session.add(UserDepartment(user_id=row.user_id,
                                           department_id=row.department_id))
                counts["memberships"] += 1
        if row.status == "unchanged":
            counts["unchanged"] += 1
            continue
        rec = (await session.execute(select(ProjectResponsible).where(
            ProjectResponsible.project_id == row.project_id,
            ProjectResponsible.department_id == row.department_id))).scalar_one_or_none()
        if rec is None:
            rec = ProjectResponsible(project_id=row.project_id,
                                     department_id=row.department_id)
            session.add(rec)
        rec.user_id = row.user_id
        rec.set_by = actor_id
        rec.set_at = datetime.utcnow()
        counts[row.status] += 1
    await session.flush()
    return counts


def print_plan(plan: Plan, out=sys.stdout) -> None:
    last = None
    for r in plan.rows:
        if r.project_token != last:
            last = r.project_token
            print(f"\n== {r.project_token}: {r.project_label or '(unresolved)'}", file=out)
        mark = "  " if r.ok else "!!"
        who = r.user_label or r.person
        extra = " +membership" if r.add_membership else ""
        detail = f"  [{r.detail}]" if r.detail else ""
        print(f" {mark} {r.department:<24} {who:<40} {r.status}{extra}{detail}", file=out)
    for n in plan.notes:
        print(f"\n   note: {n}", file=out)
    print(f"\n{len(plan.rows)} rows, {len(plan.problems)} with a problem.", file=out)


def _pairs(values: list[str], flag: str) -> dict[str, int]:
    out = {}
    for v in values or []:
        key, sep, num = v.rpartition("=")
        if not sep or not key or not num.isdigit():
            raise SystemExit(f"{flag} expects NAME=ID, got {v!r}")
        out[key] = int(num)
    return out


async def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--partial", action="store_true",
                    help="with --apply: write the ok rows even when others have a problem")
    ap.add_argument("--replace", action="store_true",
                    help="overwrite a responsible someone else already set")
    ap.add_argument("--add-membership", action="store_true",
                    help="add the department membership a matched user lacks")
    ap.add_argument("--actor-id", type=int, default=None, help="recorded as set_by")
    ap.add_argument("--project-id", action="append", default=[], metavar="TOKEN=ID")
    ap.add_argument("--user-id", action="append", default=[], metavar="NAME=ID")
    args = ap.parse_args(argv)

    engine = create_async_engine(os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./plm.db"))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as s:
            plan = await plan_team(s, TEAM, _pairs(args.project_id, "--project-id"),
                                   _pairs(args.user_id, "--user-id"),
                                   add_membership=args.add_membership, replace=args.replace)
            print_plan(plan)
            if not args.apply:
                print("\nDRY RUN - nothing written.")
                return 0 if not plan.problems else 2
            if plan.problems and not args.partial:
                print("\nNOT APPLIED: resolve the rows marked !! first (or --partial).")
                return 2
            counts = await apply_plan(s, plan, args.actor_id)
            await s.commit()
            print(f"\nAPPLIED: {counts}")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
