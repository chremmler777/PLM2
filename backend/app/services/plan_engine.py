"""Gantt 2.0 plan engine: pure scheduling math, no database.

The same rules run in the browser (frontend/src/components/gantt/engine) and
both sides assert the shared vectors in backend/tests/data/gantt_vectors.json.
So every rule here is written to be re-implementable line by line:

Calendar
- mode "calendar": every day counts, workdays and holidays are ignored by the
  math (they only shade the chart). mode "working": a day counts when its ISO
  weekday (Mon=1..Sun=7) is in workdays and it is not a holiday.
- Everything is computed on a day INDEX: idx(d) = number of counting days
  before d (calendar mode: the ordinal). A task occupies the indices
  [start_idx, start_idx + duration). A non-counting start date therefore
  lands on the next counting day.
- Dates back from indices: start = the counting day with that index; the
  exclusive end of a task with duration > 0 is the day AFTER its last counting
  day; a milestone (duration 0) ends on its start.

Links (lag in the calendar's units, negative = lead), with es/ef the start
and exclusive end index of predecessor P and the successor's duration d:
  FS: start >= P.ef + lag      SS: start >= P.es + lag
  FF: end   >= P.ef + lag      SF: end   >= P.es + lag

Forward pass ("schedule"): es = max(own start, snet date, every link
requirement): a task only ever moves LATER. mso pins the start, mfo pins the
end (both may move a task earlier and ignore links). fnlt never moves a task.
Start constraint dates (snet, mso) are start dates; finish constraint dates
(fnlt, mfo) are EXCLUSIVE end dates, like end_date.

Backward pass: project end = max ef over leaf tasks; lf = min(project end,
each successor's requirement, fnlt date); mso/mfo tasks cap lf at their own
ef. total slack = lf - ef, free slack = min over successors of the room
before that link binds (project end - ef without successors), never more
than total slack. critical = total slack <= 0.

Summary tasks (a task some other task names as parent) roll up: start/end =
min/max of the children, slack = min of the children, critical when any
child is, progress weighted by child duration. A link or constraint on a
summary applies to every leaf below it (MS Project behaviour; warning
`summary_link`). Idea blocks are scheduled forward but left out of the
backward pass (slack null, never critical). The project end is the max ef of
non-idea leaves. A cycle stops the pass: blocks keep their dates, slack null.
"""
from __future__ import annotations

import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

LINK_TYPES = ("FS", "SS", "FF", "SF")
CONSTRAINT_TYPES = ("asap", "snet", "fnlt", "mso", "mfo")
START_CONSTRAINTS = ("snet", "mso")
FINISH_CONSTRAINTS = ("fnlt", "mfo")
CALENDAR_MODES = ("calendar", "working")
DEFAULT_WORKDAYS = [1, 2, 3, 4, 5]

# A Monday, so the weekly arithmetic in Calendar.idx starts on ISO day 1.
_EPOCH = date(2000, 1, 3)


def as_date(v) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


# ----------------------------------------------------------------------
# Calendar
# ----------------------------------------------------------------------
class Calendar:
    """Counting days for one plan. See the module doc for the rules."""

    def __init__(self, mode: str = "calendar", workdays: Iterable = DEFAULT_WORKDAYS,
                 holidays: Iterable = ()):
        wd = sorted({int(d) for d in (workdays or []) if 1 <= int(d) <= 7})
        self.mode = mode if mode in CALENDAR_MODES else "calendar"
        self.workdays = wd
        self.holidays = sorted({as_date(h) for h in (holidays or []) if h})
        # A working calendar without a single working day would never finish
        # anything; it degrades to elapsed days rather than looping forever.
        self.working = self.mode == "working" and bool(wd)
        self._wd = set(wd)
        self._hol = [h for h in self.holidays if h.isoweekday() in self._wd]
        self._holset = set(self._hol)
        self._per_week = len(wd)
        # _prefix[k] = counting weekdays among the first k days of a week
        self._prefix = [0]
        for k in range(7):
            self._prefix.append(self._prefix[-1] + (1 if (k + 1) in self._wd else 0))

    @classmethod
    def from_json(cls, data: Optional[dict]) -> "Calendar":
        data = data or {}
        return cls(data.get("mode") or "calendar",
                   data.get("workdays") if data.get("workdays") is not None
                   else DEFAULT_WORKDAYS,
                   data.get("holidays") or [])

    def to_json(self) -> dict:
        return {"mode": self.mode, "workdays": list(self.workdays),
                "holidays": [h.isoformat() for h in self.holidays]}

    def is_work(self, d: date) -> bool:
        if not self.working:
            return True
        return d.isoweekday() in self._wd and d not in self._holset

    def idx(self, d: date) -> int:
        """Counting days before d."""
        if not self.working:
            return d.toordinal()
        weeks, rem = divmod(d.toordinal() - _EPOCH.toordinal(), 7)
        return (weeks * self._per_week + self._prefix[rem]
                - bisect_left(self._hol, d))

    def date_at(self, i: int) -> date:
        """The counting day whose index is i."""
        if not self.working:
            return date.fromordinal(i)
        weeks = i // self._per_week
        guess = _EPOCH + timedelta(days=weeks * 7)
        lo = guess - timedelta(days=14)
        while self.idx(lo + timedelta(days=1)) > i:
            lo -= timedelta(days=28)
        hi = guess + timedelta(days=14)
        while self.idx(hi + timedelta(days=1)) < i + 1:
            hi += timedelta(days=28 + len(self._hol))
        # smallest d with idx(d + 1) >= i + 1
        while lo < hi:
            mid = lo + timedelta(days=(hi - lo).days // 2)
            if self.idx(mid + timedelta(days=1)) >= i + 1:
                hi = mid
            else:
                lo = mid + timedelta(days=1)
        return lo

    def end_from_idx(self, start_i: int, end_i: int) -> date:
        if end_i <= start_i:
            return self.date_at(start_i)
        return self.date_at(end_i - 1) + timedelta(days=1)

    def snap(self, d: date) -> date:
        """The first counting day on or after d."""
        return self.date_at(self.idx(d))

    def end_date(self, start: date, duration: int) -> date:
        s = self.idx(start)
        return self.end_from_idx(s, s + max(int(duration or 0), 0))

    def span(self, start: date, end: date) -> int:
        """Duration in counting days between a start and an exclusive end."""
        return max(0, self.idx(end) - self.idx(start))

    def last_day(self, start: date, duration: int) -> date:
        """Inclusive last day: end - 1 for real work, the start for a
        milestone."""
        if int(duration or 0) <= 0:
            return self.snap(start)
        return self.end_date(start, duration) - timedelta(days=1)


# ----------------------------------------------------------------------
# Engine input / output
# ----------------------------------------------------------------------
@dataclass
class ETask:
    id: object
    start: date
    duration: int
    constraint_type: Optional[str] = None
    constraint_date: Optional[date] = None
    parent_id: object = None
    name: str = ""
    progress: int = 0
    idea: bool = False


@dataclass
class ELink:
    from_id: object
    to_id: object
    type: str = "FS"
    lag: int = 0
    id: object = None


@dataclass
class TaskResult:
    start: date
    end: date
    start_idx: int
    end_idx: int
    total_slack: Optional[int] = None
    free_slack: Optional[int] = None
    critical: bool = False
    is_summary: bool = False
    progress: int = 0
    wbs: str = ""


@dataclass
class PlanResult:
    tasks: dict = field(default_factory=dict)       # id -> TaskResult
    cycle: bool = False
    moved: list = field(default_factory=list)       # ids whose start changed


def tree(tasks: list[ETask]) -> tuple[dict, list]:
    """children by parent id (known parents only) and the roots, each list
    in input order. A parent loop is broken by treating its members as
    roots."""
    ids = {t.id for t in tasks}
    parent = {t.id: (t.parent_id if t.parent_id in ids and t.parent_id != t.id
                     else None) for t in tasks}
    # break parent cycles
    for t in tasks:
        seen, p = {t.id}, parent[t.id]
        while p is not None:
            if p in seen:
                parent[t.id] = None
                break
            seen.add(p)
            p = parent[p]
    children: dict = defaultdict(list)
    roots = []
    for t in tasks:
        if parent[t.id] is None:
            roots.append(t.id)
        else:
            children[parent[t.id]].append(t.id)
    return children, roots


def dfs_order(tasks: list[ETask]) -> list:
    """Ids in outline order (parents before children, siblings in input
    order) with the WBS number of each."""
    children, roots = tree(tasks)
    out = []

    def walk(ids, prefix):
        for n, tid in enumerate(ids, start=1):
            wbs = f"{prefix}{n}"
            out.append((tid, wbs))
            walk(children.get(tid, []), wbs + ".")
    walk(roots, "")
    return out


def summary_ids(tasks: list[ETask]) -> set:
    children, _ = tree(tasks)
    return {p for p, c in children.items() if c}


def _ancestors(tasks: list[ETask]) -> dict:
    """id -> [parent, grandparent, ...] (known parents, loops broken)."""
    children, _ = tree(tasks)
    parent = {c: p for p, cs in children.items() for c in cs}
    out = {}
    for t in tasks:
        chain, p = [], parent.get(t.id)
        while p is not None:
            chain.append(p)
            p = parent.get(p)
        out[t.id] = chain
    return out


def _leaves_under(tasks: list[ETask]) -> dict:
    """id -> the leaf ids at or below it."""
    children, _ = tree(tasks)
    memo: dict = {}

    def walk(tid):
        if tid not in memo:
            kids = children.get(tid, [])
            memo[tid] = [tid] if not kids else [x for k in kids for x in walk(k)]
        return memo[tid]
    return {t.id: walk(t.id) for t in tasks}


def leaf_links(tasks: list[ETask], links: list[ELink]) -> list[ELink]:
    """Links as the math uses them: a link on a summary applies to every
    leaf below it (MS Project behaviour). A link between a block and its own
    ancestor, a self link and a link to an unknown id are dropped."""
    ids = {t.id for t in tasks}
    under = _leaves_under(tasks)
    anc = _ancestors(tasks)
    out = []
    for lk in links:
        f, t = lk.from_id, lk.to_id
        if f not in ids or t not in ids or f == t:
            continue
        if f in anc[t] or t in anc[f]:
            continue
        for a in under[f]:
            for b in under[t]:
                if a != b:
                    out.append(ELink(from_id=a, to_id=b, type=lk.type,
                                     lag=int(lk.lag or 0), id=lk.id))
    return out


def _constraints(tasks: list[ETask]) -> dict:
    """leaf id -> [(type, date)]: its own constraint first, then those of
    its summaries, nearest first (a summary's constraint applies to every
    leaf below it)."""
    by_id = {t.id: t for t in tasks}
    anc = _ancestors(tasks)
    out = {}
    for t in tasks:
        cs = []
        for x in [t.id] + anc[t.id]:
            y = by_id[x]
            if y.constraint_type and y.constraint_type != "asap" and y.constraint_date:
                cs.append((y.constraint_type, y.constraint_date))
        out[t.id] = cs
    return out


def topo(ids: list, links: list[ELink]) -> Optional[list]:
    """Ids ordered so every predecessor comes first (stable on input order);
    None on a cycle."""
    import heapq
    pos = {i: n for n, i in enumerate(ids)}
    indeg = {i: 0 for i in ids}
    succ: dict = defaultdict(list)
    for lk in links:
        if lk.from_id in pos and lk.to_id in pos:
            if lk.from_id == lk.to_id:
                return None
            indeg[lk.to_id] += 1
            succ[lk.from_id].append(lk.to_id)
    ready = [(pos[i], i) for i in ids if indeg[i] == 0]
    heapq.heapify(ready)
    out = []
    while ready:
        _, i = heapq.heappop(ready)
        out.append(i)
        for s in succ[i]:
            indeg[s] -= 1
            if indeg[s] == 0:
                heapq.heappush(ready, (pos[s], s))
    return out if len(out) == len(ids) else None


def _req_start(lk: ELink, p_es: int, p_ef: int, dur: int) -> int:
    lag = int(lk.lag or 0)
    if lk.type == "SS":
        return p_es + lag
    if lk.type == "FF":
        return p_ef + lag - dur
    if lk.type == "SF":
        return p_es + lag - dur
    return p_ef + lag                                  # FS


def _pin(cons: list, cal: Calendar, dur: int) -> Optional[int]:
    """Start index a must-start-on / must-finish-on pins the block to."""
    for ct, cd in cons:
        if ct == "mso":
            return cal.idx(cd)
        if ct == "mfo":
            return cal.idx(cd) - dur
    return None


def compute(tasks: list[ETask], links: list[ELink], cal: Calendar,
            *, move: bool = True, pull: bool = False) -> PlanResult:
    """Forward pass (move=True: the schedule; move=False: the dates as they
    stand), backward pass over non-idea blocks, slack, critical path and
    summary rollup. pull=True: blocks without a predecessor start at the
    project start instead of keeping their own start."""
    res = PlanResult()
    by_id = {t.id: t for t in tasks}
    summaries = summary_ids(tasks)
    leaves = [t.id for t in tasks if t.id not in summaries]
    llinks = leaf_links(tasks, links)
    cons = _constraints(tasks)
    order = topo(leaves, llinks)
    preds: dict = defaultdict(list)
    succs: dict = defaultdict(list)
    for lk in llinks:
        preds[lk.to_id].append(lk)
        succs[lk.from_id].append(lk)

    es: dict = {}
    ef: dict = {}
    project_start = min((cal.idx(by_id[t].start) for t in leaves), default=0)
    if order is None:
        res.cycle = True
        for tid in leaves:
            t = by_id[tid]
            es[tid] = cal.idx(t.start)
            ef[tid] = es[tid] + max(int(t.duration or 0), 0)
    else:
        for tid in order:
            t = by_id[tid]
            dur = max(int(t.duration or 0), 0)
            own = cal.idx(t.start)
            pin = _pin(cons[tid], cal, dur) if move else None
            if not move:
                s = own
            elif pin is not None:
                s = pin
            else:
                s = project_start if pull else own
                for ct, cd in cons[tid]:
                    if ct == "snet":
                        s = max(s, cal.idx(cd))
                for lk in preds[tid]:
                    s = max(s, _req_start(lk, es[lk.from_id], ef[lk.from_id], dur))
            es[tid], ef[tid] = s, s + dur

    for tid in leaves:
        t = by_id[tid]
        start = cal.date_at(es[tid])
        res.tasks[tid] = TaskResult(
            start=start, end=cal.end_from_idx(es[tid], ef[tid]),
            start_idx=es[tid], end_idx=ef[tid],
            progress=int(t.progress or 0))
        if move and start != t.start:
            res.moved.append(tid)

    real = [tid for tid in (order or []) if not by_id[tid].idea]
    if order is not None and real:
        project_end = max(ef[tid] for tid in real)
        lf: dict = {}
        for tid in reversed(real):
            dur = ef[tid] - es[tid]
            f = project_end
            for lk in succs[tid]:
                s = lk.to_id
                if s not in lf:
                    continue                      # an idea successor
                lag = int(lk.lag or 0)
                ls_s = lf[s] - (ef[s] - es[s])
                if lk.type == "SS":
                    f = min(f, ls_s - lag + dur)
                elif lk.type == "FF":
                    f = min(f, lf[s] - lag)
                elif lk.type == "SF":
                    f = min(f, lf[s] - lag + dur)
                else:
                    f = min(f, ls_s - lag)
            for ct, cd in cons[tid]:
                if ct == "fnlt":
                    f = min(f, cal.idx(cd))
            if _pin(cons[tid], cal, dur) is not None:
                f = min(f, ef[tid])
            lf[tid] = f
        for tid in real:
            total = lf[tid] - ef[tid]
            free = None
            for lk in succs[tid]:
                s = lk.to_id
                if s not in lf:
                    continue
                lag = int(lk.lag or 0)
                room = {"SS": es[s] - lag - es[tid],
                        "FF": ef[s] - lag - ef[tid],
                        "SF": ef[s] - lag - es[tid]}.get(
                            lk.type, es[s] - lag - ef[tid])
                free = room if free is None else min(free, room)
            if free is None:
                free = project_end - ef[tid]
            r = res.tasks[tid]
            r.total_slack = total
            r.free_slack = min(free, total)
            r.critical = total <= 0

    # summary rollup, children first
    children, roots = tree(tasks)

    def roll(tid):
        kids = children.get(tid, [])
        if not kids:
            return res.tasks[tid]
        rs = [roll(k) for k in kids]
        weight = sum(max(r.end_idx - r.start_idx, 0) for r in rs)
        if weight > 0:
            prog = round(sum(r.progress * max(r.end_idx - r.start_idx, 0)
                             for r in rs) / weight)
        else:
            prog = round(sum(r.progress for r in rs) / len(rs))
        slacks = [r.total_slack for r in rs if r.total_slack is not None]
        frees = [r.free_slack for r in rs if r.free_slack is not None]
        r = TaskResult(
            start=min(x.start for x in rs), end=max(x.end for x in rs),
            start_idx=min(x.start_idx for x in rs),
            end_idx=max(x.end_idx for x in rs),
            total_slack=min(slacks) if slacks else None,
            free_slack=min(frees) if frees else None,
            critical=any(x.critical for x in rs), is_summary=True,
            progress=prog)
        res.tasks[tid] = r
        return r
    for rt in roots:
        roll(rt)
    for tid, wbs in dfs_order(tasks):
        res.tasks[tid].wbs = wbs
    return res


def schedule(tasks: list[ETask], links: list[ELink], cal: Calendar,
             *, pull: bool = False) -> PlanResult:
    return compute(tasks, links, cal, move=True, pull=pull)


def analyse(tasks: list[ETask], links: list[ELink], cal: Calendar) -> PlanResult:
    return compute(tasks, links, cal, move=False)


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def issue(code: str, message: str, task_id=None) -> dict:
    return {"code": code, "message": message, "task_id": task_id}


def _lag_txt(lag: int) -> str:
    return f" (lag {lag:+d}d)" if lag else ""


def engine_issues(tasks: list[ETask], links: list[ELink], cal: Calendar) -> dict:
    """The scheduling issues on the dates as they stand. Errors:
    negative_duration, empty_name, unknown_predecessor, dependency_violation,
    cycle. Warnings: constraint_conflict (also a link a pinned block breaks),
    summary_link (a link on a summary, applied to every block under it)."""
    errors, warnings = [], []
    by_id = {t.id: t for t in tasks}
    summaries = summary_ids(tasks)
    anc = _ancestors(tasks)
    for t in tasks:
        if not (t.name or "").strip():
            errors.append(issue("empty_name", "A block has no name", t.id))
        if int(t.duration or 0) < 0:
            errors.append(issue(
                "negative_duration", f"'{t.name}' has a negative duration", t.id))
    for lk in links:
        if lk.from_id not in by_id or lk.to_id not in by_id:
            owner = lk.to_id if lk.to_id in by_id else None
            name = by_id[owner].name if owner is not None else "A block"
            errors.append(issue(
                "unknown_predecessor",
                f"'{name}' depends on a block that does not exist ({lk.from_id})",
                owner))
            continue
        f, t = by_id[lk.from_id], by_id[lk.to_id]
        if lk.from_id in anc[lk.to_id] or lk.to_id in anc[lk.from_id]:
            warnings.append(issue(
                "summary_link",
                f"The link between '{f.name}' and '{t.name}' joins a summary "
                "and a block under it and is not used for scheduling", lk.to_id))
        elif lk.from_id in summaries or lk.to_id in summaries:
            warnings.append(issue(
                "summary_link",
                f"The link from '{f.name}' to '{t.name}' is on a summary block: "
                "it applies to every block under it", lk.to_id))
    leaves = [t.id for t in tasks if t.id not in summaries]
    llinks = leaf_links(tasks, links)
    if topo(leaves, llinks) is None or any(lk.from_id == lk.to_id for lk in links):
        errors.append(issue("cycle", "The dependencies form a loop"))

    cons = _constraints(tasks)

    def se(t):
        s = cal.idx(t.start)
        return s, s + max(int(t.duration or 0), 0)

    seen = set()
    for lk in llinks:
        p, s = by_id[lk.from_id], by_id[lk.to_id]
        ps, pe = se(p)
        ss, sfin = se(s)
        lag = int(lk.lag or 0)
        need = _req_start(lk, ps, pe, sfin - ss)
        if ss < need and (p.id, s.id, lk.type, lag) not in seen:
            seen.add((p.id, s.id, lk.type, lag))
            verb = {"FS": ("starts", "ends"), "SS": ("starts", "starts"),
                    "FF": ("ends", "ends"), "SF": ("ends", "starts")}[
                        lk.type if lk.type in LINK_TYPES else "FS"]
            text = f"'{s.name}' {verb[0]} before '{p.name}' {verb[1]}{_lag_txt(lag)}"
            if _pin(cons[s.id], cal, sfin - ss) is not None:
                warnings.append(issue(
                    "constraint_conflict", text + ", pinned by its constraint",
                    s.id))
            else:
                errors.append(issue("dependency_violation", text, s.id))

    for t in tasks:
        if t.id in summaries:
            continue
        s, e = se(t)
        for ct, cdate in cons[t.id]:
            c, cd = cal.idx(cdate), cdate.isoformat()
            bad = None
            if ct == "snet" and s < c:
                bad = f"'{t.name}' starts before its start-no-earlier-than date {cd}"
            elif ct == "mso" and s != c:
                bad = f"'{t.name}' does not start on its must-start-on date {cd}"
            elif ct == "mfo" and e != c:
                bad = f"'{t.name}' does not end on its must-finish-on date {cd}"
            elif ct == "fnlt" and e > c:
                bad = f"'{t.name}' ends after its finish-no-later-than date {cd}"
            if bad:
                warnings.append(issue("constraint_conflict", bad, t.id))
    return {"errors": errors, "warnings": warnings}


# ----------------------------------------------------------------------
# MS Project XML (MSPDI)
# ----------------------------------------------------------------------
MSPDI_NS = "http://schemas.microsoft.com/project"
MSPDI_LINK_TYPE = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}
MSPDI_LINK_TYPE_BACK = {v: k for k, v in MSPDI_LINK_TYPE.items()}
MSPDI_CONSTRAINT = {"asap": 0, "mso": 2, "mfo": 3, "snet": 4, "fnlt": 7}
MSPDI_CONSTRAINT_BACK = {v: k for k, v in MSPDI_CONSTRAINT.items()}
# Elapsed duration / lag formats (plus their "estimated" twins, +32).
_ELAPSED_FORMATS = {4, 6, 8, 10, 12, 20, 36, 38, 40, 42, 44, 52}
MINUTES_PER_WORKDAY = 480
# Custom fields shared with the frontend exporter: block kind in Text1, idea
# flag in Flag1.
FIELD_TEXT1 = "188743731"
FIELD_FLAG1 = "188743752"
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def xml_text(v) -> str:
    """XML 1.0 forbids most control characters; a pasted name must not make
    the file unreadable for MS Project."""
    return _ILLEGAL_XML.sub("", str(v))


def lag_tenths(days: int, cal: Calendar) -> tuple[int, int]:
    """(LinkLag in tenths of minutes, LagFormat)."""
    if cal.working:
        return int(days) * MINUTES_PER_WORKDAY * 10, 7
    return int(days) * 24 * 60 * 10, 8


def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.strip()[:19])
    except ValueError:
        d = as_date(v)
        return datetime(d.year, d.month, d.day) if d else None


def _parse_hours(v: Optional[str]) -> float:
    """PT24H0M0S (also P1DT2H...) to hours."""
    if not v:
        return 0.0
    m = re.fullmatch(r"-?P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?"
                     r"(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?", v.strip())
    if not m:
        return 0.0
    d, h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    sign = -1 if v.strip().startswith("-") else 1
    return sign * (d * 24 + h + mi / 60 + s / 3600)


def build_mspdi(*, name: str, title: str, cal: Calendar, tasks: list[dict],
                links: list[dict]) -> bytes:
    """tasks: outline-ordered dicts {key, name, start, duration, end, kind,
    idea, milestone, level, outline, summary, progress, actual_start,
    actual_finish, constraint_type, constraint_date, notes, lane,
    baseline_start, baseline_finish}; links: {from, to, type, lag}. UIDs are
    1..n in the given order."""
    ns = MSPDI_NS
    ET.register_namespace("", ns)

    def el(parent, tag, text=None):
        e = ET.SubElement(parent, f"{{{ns}}}{tag}")
        if text is not None:
            e.text = xml_text(text)
        return e

    def ts(d: date, t: str = "08:00:00") -> str:
        return f"{d.isoformat()}T{t}"

    def fin(d: date) -> str:
        """An exclusive end date as MS Project's finish moment."""
        return ts(d - timedelta(days=1), "17:00:00")

    working = cal.working
    fmt = 7 if working else 8

    def dur(days: int) -> str:
        return f"PT{(8 if working else 24) * int(days)}H0M0S"

    root = ET.Element(f"{{{ns}}}Project")
    el(root, "SaveVersion", 14)
    el(root, "Name", name)
    el(root, "Title", title)
    el(root, "ScheduleFromStart", 1)
    start = min((t["start"] for t in tasks), default=date.today())
    finish = max((t["end"] for t in tasks), default=start)
    el(root, "StartDate", ts(start))
    el(root, "FinishDate", fin(finish) if finish > start else ts(start))
    el(root, "CalendarUID", 1)
    el(root, "DefaultStartTime", "08:00:00")
    el(root, "DefaultFinishTime", "17:00:00")
    # Working mode: the calendar's workdays at 8 h. Calendar mode: every day
    # is a working day and durations are elapsed, so MS Project agrees with
    # us whatever it does with the calendar.
    week = list(cal.workdays) if working else [1, 2, 3, 4, 5, 6, 7]
    el(root, "MinutesPerDay", MINUTES_PER_WORKDAY)
    el(root, "MinutesPerWeek", MINUTES_PER_WORKDAY * len(week))
    el(root, "DaysPerMonth", 20 if working else 30)
    el(root, "DurationFormat", fmt)
    el(root, "NewTasksAreManual", 0)
    xas = el(root, "ExtendedAttributes")
    for fid, fname, alias in ((FIELD_TEXT1, "Text1", "Kind"),
                              (FIELD_FLAG1, "Flag1", "Idea")):
        xa = el(xas, "ExtendedAttribute")
        el(xa, "FieldID", fid)
        el(xa, "FieldName", fname)
        el(xa, "Alias", alias)

    cals = el(root, "Calendars")
    c = el(cals, "Calendar")
    el(c, "UID", 1)
    el(c, "Name", "Working days" if working else "Elapsed days")
    el(c, "IsBaseCalendar", 1)
    wds = el(c, "WeekDays")
    for day_type in range(1, 8):                 # 1 = Sunday .. 7 = Saturday
        iso = 7 if day_type == 1 else day_type - 1
        wd = el(wds, "WeekDay")
        el(wd, "DayType", day_type)
        on = iso in week
        el(wd, "DayWorking", 1 if on else 0)
        if on:
            wts = el(wd, "WorkingTimes")
            for a, b in (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")):
                wt = el(wts, "WorkingTime")
                el(wt, "FromTime", a)
                el(wt, "ToTime", b)
    if cal.holidays:
        exs = el(c, "Exceptions")
        for h in cal.holidays:
            ex = el(exs, "Exception")
            el(ex, "EnteredByOccurrences", 0)
            tp = el(ex, "TimePeriod")
            el(tp, "FromDate", ts(h, "00:00:00"))
            el(tp, "ToDate", ts(h, "23:59:00"))
            el(ex, "Occurrences", 1)
            el(ex, "Name", "Holiday")
            el(ex, "Type", 1)
            el(ex, "DayWorking", 0)

    uid = {t["key"]: i for i, t in enumerate(tasks, start=1)}
    preds_of: dict = defaultdict(list)
    for lk in links:
        if lk["from"] in uid and lk["to"] in uid:
            preds_of[lk["to"]].append(lk)
    tasks_el = el(root, "Tasks")
    for t in tasks:
        n = uid[t["key"]]
        d = int(t["duration"] or 0)
        te = el(tasks_el, "Task")
        el(te, "UID", n)
        el(te, "ID", n)
        el(te, "Name", t["name"])
        el(te, "Type", 1)
        el(te, "IsNull", 0)
        el(te, "WBS", t["outline"])
        el(te, "OutlineNumber", t["outline"])
        el(te, "OutlineLevel", t["level"])
        el(te, "Start", ts(t["start"]))
        el(te, "Finish", fin(t["end"]) if d > 0 else ts(t["start"]))
        el(te, "Duration", dur(d))
        el(te, "DurationFormat", fmt)
        el(te, "Milestone", 1 if t.get("milestone") else 0)
        el(te, "Summary", 1 if t.get("summary") else 0)
        el(te, "PercentComplete", int(t.get("progress") or 0))
        if t.get("actual_start"):
            el(te, "ActualStart", ts(t["actual_start"]))
        if t.get("actual_finish"):
            el(te, "ActualFinish", ts(t["actual_finish"], "17:00:00"))
        if not t.get("summary"):
            ct, cd = t.get("constraint_type"), t.get("constraint_date")
            if ct in MSPDI_CONSTRAINT and ct != "asap" and cd:
                el(te, "ConstraintType", MSPDI_CONSTRAINT[ct])
                el(te, "ConstraintDate",
                   ts(cd) if ct in START_CONSTRAINTS else fin(cd))
            else:
                # Keep MS Project from pulling the block to the project
                # start: our plan never schedules earlier than drawn.
                el(te, "ConstraintType", 4)
                el(te, "ConstraintDate", ts(t["start"]))
        if t.get("notes"):
            el(te, "Notes", t["notes"])
        for lk in preds_of.get(t["key"], []):
            link = el(te, "PredecessorLink")
            el(link, "PredecessorUID", uid[lk["from"]])
            el(link, "Type", MSPDI_LINK_TYPE.get(lk["type"], 1))
            el(link, "CrossProject", 0)
            lag, lag_fmt = lag_tenths(int(lk.get("lag") or 0), cal)
            el(link, "LinkLag", lag)
            el(link, "LagFormat", lag_fmt)
        if t.get("kind"):
            xa = el(te, "ExtendedAttribute")
            el(xa, "FieldID", FIELD_TEXT1)
            el(xa, "Value", t["kind"])
        if t.get("idea"):
            xa = el(te, "ExtendedAttribute")
            el(xa, "FieldID", FIELD_FLAG1)
            el(xa, "Value", 1)
        if t.get("baseline_start") and t.get("baseline_finish"):
            bl = el(te, "Baseline")
            el(bl, "Number", 0)
            el(bl, "Start", ts(t["baseline_start"]))
            el(bl, "Finish", fin(t["baseline_finish"])
               if t["baseline_finish"] > t["baseline_start"]
               else ts(t["baseline_start"]))
            el(bl, "Duration", dur(cal.span(t["baseline_start"],
                                            t["baseline_finish"])))
            el(bl, "DurationFormat", fmt)

    lanes = sorted({t["lane"] for t in tasks if t.get("lane")})
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
    for t in tasks:
        if t.get("lane") in rid and not t.get("summary"):
            n += 1
            a = el(asg_el, "Assignment")
            el(a, "UID", n)
            el(a, "TaskUID", uid[t["key"]])
            el(a, "ResourceUID", rid[t["lane"]])
            el(a, "Units", 1)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class MspdiError(ValueError):
    pass


def parse_mspdi(content: bytes) -> dict:
    """An MSPDI file as {calendar: Calendar, tasks: [...], links: [...]}.

    tasks: {uid, name, start, duration, milestone, parent_uid, level,
    summary, constraint_type, constraint_date, notes, lane, kind, idea}, in
    file order.
    links: {from_uid, to_uid, type, lag}. Durations and lags are converted
    to the detected calendar's units; SNET on the task's own start (what our
    export writes for unconstrained blocks) reads back as no constraint,
    which our "never earlier" scheduling makes equivalent."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        # MSPDI never needs a DTD; entities are how XML bombs get in.
        raise MspdiError(
            "The file declares a DTD or entities, which MS Project XML never does")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise MspdiError(f"The file is not valid XML ({e})")
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag[1:].split("}")[0]
    if root.tag.split("}")[-1] != "Project":
        raise MspdiError("The file is not an MS Project XML file (no Project element)")

    def q(tag):
        return f"{{{ns}}}{tag}" if ns else tag

    def txt(e, tag, default=None):
        x = e.find(q(tag)) if e is not None else None
        return x.text.strip() if x is not None and x.text is not None else default

    def num(e, tag, default=0):
        v = txt(e, tag)
        try:
            return int(float(v)) if v is not None else default
        except ValueError:
            return default

    minutes_per_day = num(root, "MinutesPerDay", MINUTES_PER_WORKDAY) or MINUTES_PER_WORKDAY
    project_fmt = num(root, "DurationFormat", 7)

    # calendar: the project's calendar, else the first base calendar
    cal_uid = txt(root, "CalendarUID")
    cal_el = None
    cals = root.find(q("Calendars"))
    if cals is not None:
        for c in cals.findall(q("Calendar")):
            if cal_el is None or txt(c, "UID") == cal_uid:
                cal_el = c
                if txt(c, "UID") == cal_uid:
                    break
    workdays = list(DEFAULT_WORKDAYS)
    holidays: list[date] = []
    if cal_el is not None:
        wds = cal_el.find(q("WeekDays"))
        if wds is not None:
            found = {}
            for wd in wds.findall(q("WeekDay")):
                dt = num(wd, "DayType", -1)
                if 1 <= dt <= 7:
                    found[7 if dt == 1 else dt - 1] = num(wd, "DayWorking", 1) == 1
                elif dt == 0 and num(wd, "DayWorking", 1) == 0:
                    tp = wd.find(q("TimePeriod"))
                    a, b = _parse_dt(txt(tp, "FromDate")), _parse_dt(txt(tp, "ToDate"))
                    if a and b:
                        d = a.date()
                        while d <= b.date():
                            holidays.append(d)
                            d += timedelta(days=1)
            if found:
                workdays = sorted(k for k, on in found.items() if on) or workdays
        exs = cal_el.find(q("Exceptions"))
        if exs is not None:
            for ex in exs.findall(q("Exception")):
                if num(ex, "DayWorking", 0) == 1:
                    continue
                tp = ex.find(q("TimePeriod"))
                a, b = _parse_dt(txt(tp, "FromDate")), _parse_dt(txt(tp, "ToDate"))
                if a and b:
                    d = a.date()
                    while d <= b.date() and len(holidays) < 5000:
                        holidays.append(d)
                        d += timedelta(days=1)

    raw = []
    tasks_el = root.find(q("Tasks"))
    for te in (tasks_el.findall(q("Task")) if tasks_el is not None else []):
        if num(te, "IsNull", 0) == 1 or num(te, "UID", -1) == 0:
            continue                             # project summary / blank row
        start = _parse_dt(txt(te, "Start"))
        if start is None or not (txt(te, "Name") or "").strip():
            continue
        raw.append(te)
    leaf_fmts = [num(te, "DurationFormat", project_fmt) for te in raw
                 if num(te, "Summary", 0) == 0]
    elapsed = (project_fmt in _ELAPSED_FORMATS if not leaf_fmts
               else all(f in _ELAPSED_FORMATS for f in leaf_fmts))
    if elapsed and len(workdays) == 7:
        # our calendar-mode export marks every day working; the weekdays only
        # shade the chart then, so keep the usual Mon-Fri shading
        workdays = list(DEFAULT_WORKDAYS)
    cal = Calendar("calendar" if elapsed else "working", workdays, holidays)

    def to_days(hours: float, fmt: int) -> int:
        if cal.working and fmt not in _ELAPSED_FORMATS:
            return int(round(hours * 60 / minutes_per_day))
        return int(round(hours / 24 if fmt in _ELAPSED_FORMATS
                         else hours * 60 / minutes_per_day))

    lane_by_uid = {}
    res_names = {}
    res_el = root.find(q("Resources"))
    for r in (res_el.findall(q("Resource")) if res_el is not None else []):
        res_names[txt(r, "UID")] = txt(r, "Name")
    asg_el = root.find(q("Assignments"))
    for a in (asg_el.findall(q("Assignment")) if asg_el is not None else []):
        name = res_names.get(txt(a, "ResourceUID"))
        if name and txt(a, "TaskUID") not in lane_by_uid:
            lane_by_uid[txt(a, "TaskUID")] = name

    tasks, links = [], []
    stack: list[tuple[int, str]] = []            # (level, uid)
    for te in raw:
        uid = txt(te, "UID")
        level = max(1, num(te, "OutlineLevel", 1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        stack.append((level, uid))
        start = _parse_dt(txt(te, "Start")).date()
        fmt = num(te, "DurationFormat", project_fmt)
        days = max(0, to_days(_parse_hours(txt(te, "Duration")), fmt))
        milestone = num(te, "Milestone", 0) == 1
        if milestone:
            days = 0
        ct = MSPDI_CONSTRAINT_BACK.get(num(te, "ConstraintType", 0))
        cdt = _parse_dt(txt(te, "ConstraintDate"))
        cd = None
        if ct in START_CONSTRAINTS and cdt:
            cd = cdt.date()
        elif ct in FINISH_CONSTRAINTS and cdt:
            # a finish moment late in the day is the end of that day
            cd = cdt.date() + timedelta(days=1) if cdt.hour >= 12 else cdt.date()
        if ct == "snet" and cd == start:
            ct, cd = None, None
        if ct == "asap" or cd is None:
            ct, cd = None, None
        notes = txt(te, "Notes") or ""
        lane, kind, idea = lane_by_uid.get(uid), None, False
        xattr = {}
        for xa in te.findall(q("ExtendedAttribute")):
            xattr[txt(xa, "FieldID")] = txt(xa, "Value")
        rest = []
        for part in [p.strip() for p in notes.split(" | ")] if notes else []:
            if part.startswith("Lane: "):
                lane = part[6:].strip() or lane
            elif part.startswith("Kind: "):
                kind = part[6:].strip()
            elif part:
                rest.append(part)
        if xattr.get(FIELD_TEXT1):
            kind = xattr[FIELD_TEXT1]
        idea = str(xattr.get(FIELD_FLAG1) or "0").strip().lower() in ("1", "true", "yes")
        tasks.append({
            "uid": uid, "name": (txt(te, "Name") or "").strip(),
            "start": start, "duration": days, "milestone": milestone,
            "parent_uid": parent, "level": level,
            "summary": num(te, "Summary", 0) == 1,
            "constraint_type": ct, "constraint_date": cd,
            "notes": " | ".join(rest) or None, "lane": lane, "kind": kind,
            "idea": idea,
        })
        for pl in te.findall(q("PredecessorLink")):
            lag_fmt = num(pl, "LagFormat", 7)
            tenths = num(pl, "LinkLag", 0)
            minutes = tenths / 10
            if lag_fmt in _ELAPSED_FORMATS:
                lag = minutes / 1440
            else:
                lag = minutes / minutes_per_day
            links.append({
                "from_uid": txt(pl, "PredecessorUID"), "to_uid": uid,
                "type": MSPDI_LINK_TYPE_BACK.get(num(pl, "Type", 1), "FS"),
                "lag": int(round(lag)),
            })
    return {"calendar": cal, "tasks": tasks, "links": links}
