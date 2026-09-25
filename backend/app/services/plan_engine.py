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
min/max of the children with committed work below them (idea blocks do not
stretch a summary; a summary of ideas only rolls up its ideas), slack = min of the children, critical when any
child is, progress weighted by child duration. Links on summaries follow MS
Project, modelled as three points per summary instead of one link per pair
of leaves (so nested summaries never multiply links):
- a link FROM a summary binds to the summary's own start (the earliest child
  start: SS, SF) or finish (the latest child end: FS, FF);
- a link INTO a summary (FS, SS only) is a start bound on every leaf below
  it; FF/SF into a summary are refused (error `summary_finish_link`) and not
  used for scheduling;
- a start or finish bound (snet, fnlt) on a summary applies to every leaf
  below it; mso/mfo on a summary are refused (error `summary_pin`) and not
  used;
- a link between a block and its own summary is not used (warning
  `summary_link`, as is any link on a summary).
In the backward pass a finish-type link out of a summary bounds every leaf
below it, a start-type link only the leaves that start the summary.
Idea blocks are scheduled forward but left out of the backward pass (slack
null, never critical). The project end is the max ef of non-idea leaves. A
cycle stops the pass: blocks keep their dates, slack null.
"""
from __future__ import annotations

import heapq
import math
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
PIN_CONSTRAINTS = ("mso", "mfo")
# Link types that bound the successor's END: not allowed into a summary.
FINISH_TARGET_LINKS = ("FF", "SF")
# Link types that read the predecessor's START (out of a summary: its start point).
START_SOURCE_LINKS = ("SS", "SF")
CALENDAR_MODES = ("calendar", "working")
# Sanity bounds shared by the API, the service and the MSPDI import.
MAX_OUTLINE_DEPTH = 50
MAX_DURATION_DAYS = 36500
MAX_LAG_DAYS = 3650
MIN_YEAR, MAX_YEAR = 1900, 2200
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
    started: bool = False               # has an actual start: work is under way


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
    order) with the WBS number of each. Iterative: a deep outline must not
    hit the recursion limit."""
    children, roots = tree(tasks)
    out = []
    stack = [(tid, str(n)) for n, tid in reversed(list(enumerate(roots, start=1)))]
    while stack:
        tid, wbs = stack.pop()
        out.append((tid, wbs))
        kids = children.get(tid, [])
        for n in range(len(kids), 0, -1):
            stack.append((kids[n - 1], f"{wbs}.{n}"))
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


def _leaves_under(tasks: list[ETask], ids=None) -> dict:
    """id -> the leaf ids at or below it (for `ids`, default every task)."""
    children, _ = tree(tasks)
    memo: dict = {}
    for tid, _w in reversed(dfs_order(tasks)):     # children before parents
        kids = children.get(tid, [])
        memo[tid] = [tid] if not kids else [x for k in kids for x in memo[k]]
    wanted = [t.id for t in tasks] if ids is None else ids
    return {i: memo[i] for i in wanted if i in memo}


def _constraints(tasks: list[ETask]) -> dict:
    """leaf id -> [(type, date)]: its own constraint first, then the start /
    finish bounds (snet, fnlt) of its summaries, nearest first. mso/mfo on
    a summary are not used (MS Project refuses them)."""
    by_id = {t.id: t for t in tasks}
    anc = _ancestors(tasks)
    out = {}
    for t in tasks:
        cs = []
        for n, x in enumerate([t.id] + anc[t.id]):
            y = by_id[x]
            ct = y.constraint_type
            if not ct or ct == "asap" or not y.constraint_date:
                continue
            if n > 0 and ct in PIN_CONSTRAINTS:
                continue
            cs.append((ct, y.constraint_date))
        out[t.id] = cs
    return out


def topo(ids: list, links: list[ELink]) -> Optional[list]:
    """Ids ordered so every predecessor comes first (stable on input order);
    None on a cycle."""
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


# ----------------------------------------------------------------------
# The scheduling graph
# ----------------------------------------------------------------------
@dataclass
class Graph:
    """Tasks and links as the math uses them.

    Nodes: ("L", id) a leaf; for a summary ("G", id) its start gate (the
    start bound every leaf below it gets), ("PS", id) its start point (the
    earliest child start, what SS/SF out of it read) and ("PF", id) its
    finish point (the latest child end, what FS/FF out of it read). Edges: a
    link from its source (L, PS or PF) to its target (L or G);
    G(parent) -> G/L(child); L/PF(child) -> PF(parent); L/PS(child) ->
    PS(parent), except from a child the start point itself drives (a block
    fed through a successor of the summary's start starts after it, so it
    cannot be the earliest: leaving it out avoids a false cycle).
    `order` is a topological order of the nodes, None on a cycle."""
    by_id: dict
    children: dict
    parent: dict
    anc: dict
    summaries: set
    leaves: list
    links: list
    succ: dict
    order: Optional[list]
    # summary id -> the children its start point rolls up
    start_kids: dict = field(default_factory=dict)
    # summary id -> the children its dates roll up: those with committed
    # (non-idea) work below them; all children when there is none
    real_kids: dict = field(default_factory=dict)

    def src(self, tid, typ="FS"):
        if tid not in self.summaries:
            return ("L", tid)
        return ("PS", tid) if typ in START_SOURCE_LINKS else ("PF", tid)

    def dst(self, tid):
        return ("G", tid) if tid in self.summaries else ("L", tid)

    def node(self, tid, point):
        """A task's start ("S") or finish ("F") node."""
        if tid not in self.summaries:
            return ("L", tid)
        return ("PS", tid) if point == "S" else ("PF", tid)


def usable_link(lk: ELink, by_id: dict, anc: dict, summaries: set) -> bool:
    """A link the math uses: both ends known, not a self link, not between a
    block and its own summary, not FF/SF into a summary."""
    f, t = lk.from_id, lk.to_id
    if f not in by_id or t not in by_id or f == t:
        return False
    if f in anc[t] or t in anc[f]:
        return False
    if t in summaries and lk.type in FINISH_TARGET_LINKS:
        return False
    return True


def graph(tasks: list[ETask], links: list[ELink]) -> Graph:
    by_id = {t.id: t for t in tasks}
    children, _ = tree(tasks)
    parent = {c: p for p, cs in children.items() for c in cs}
    summaries = {p for p, cs in children.items() if cs}
    anc = {}
    for t in tasks:
        chain, p = [], parent.get(t.id)
        while p is not None:
            chain.append(p)
            p = parent.get(p)
        anc[t.id] = chain
    leaves = [t.id for t in tasks if t.id not in summaries]
    # One link per (from, to, type); a duplicate keeps the larger lag.
    use: dict = {}
    for lk in links:
        typ = lk.type if lk.type in LINK_TYPES else "FS"
        e = ELink(from_id=lk.from_id, to_id=lk.to_id, type=typ,
                  lag=int(lk.lag or 0), id=lk.id)
        if not usable_link(e, by_id, anc, summaries):
            continue
        k = (e.from_id, e.to_id, typ)
        if k not in use or e.lag > use[k].lag:
            use[k] = e
    ulinks = list(use.values())
    g = Graph(by_id=by_id, children=children, parent=parent, anc=anc,
              summaries=summaries, leaves=leaves, links=ulinks,
              succ=defaultdict(list), order=None)
    pos = {t.id: n for n, t in enumerate(tasks)}
    rank = {"G": 0, "L": 1, "PS": 2, "PF": 3}
    nodes = []
    for t in tasks:
        if t.id in summaries:
            nodes += [("G", t.id), ("PS", t.id), ("PF", t.id)]
        else:
            nodes.append(("L", t.id))
    succ = g.succ
    for p, cs in children.items():
        for c in cs:
            if c in summaries:
                succ[("G", p)].append(("G", c))
                succ[("PF", c)].append(("PF", p))
            else:
                succ[("G", p)].append(("L", c))
                succ[("L", c)].append(("PF", p))
    for lk in ulinks:
        succ[g.src(lk.from_id, lk.type)].append(g.dst(lk.to_id))

    def reach(start) -> set:
        seen, stack = {start}, [start]
        while stack:
            for m in succ.get(stack.pop(), []):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        return seen
    # Summary dates roll up the children with committed work (an idea is a
    # proposal: it does not stretch a summary). Start points, deepest
    # summary first, also leave out a child the start point itself drives.
    has_real: dict = {}
    for tid, _w in reversed(dfs_order(tasks)):
        if tid not in summaries:
            has_real[tid] = not by_id[tid].idea
            continue
        kids = children[tid]
        real = [c for c in kids if has_real[c]]
        has_real[tid] = bool(real)
        g.real_kids[tid] = real or kids
    for sid, _w in reversed(dfs_order(tasks)):
        if sid not in summaries:
            continue
        kids = g.real_kids[sid]
        driven = reach(("PS", sid)) if succ.get(("PS", sid)) else set()
        keep = [c for c in kids if g.node(c, "S") not in driven] or kids
        g.start_kids[sid] = keep
        for c in keep:
            succ[g.node(c, "S")].append(("PS", sid))

    indeg = {n: 0 for n in nodes}
    for n, ms in succ.items():
        for m in ms:
            indeg[m] += 1
    ready = [(pos[n[1]], rank[n[0]], n) for n in nodes if indeg[n] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        *_, n = heapq.heappop(ready)
        order.append(n)
        for m in succ[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(ready, (pos[m[1]], rank[m[0]], m))
    g.order = order if len(order) == len(nodes) else None
    return g


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


def _min(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def compute(tasks: list[ETask], links: list[ELink], cal: Calendar,
            *, move: bool = True, pull: bool = False,
            only: Optional[set] = None) -> PlanResult:
    """Forward pass (move=True: the schedule; move=False: the dates as they
    stand), backward pass over non-idea blocks, slack, critical path and
    summary rollup. pull=True: blocks without a predecessor start at the
    project start instead of keeping their own start. only: the leaves the
    forward pass may move; every other block keeps its dates."""
    res = PlanResult()
    g = graph(tasks, links)
    by_id = g.by_id
    leaves = g.leaves
    cons = _constraints(tasks)
    in_links: dict = defaultdict(list)
    out_links: dict = defaultdict(list)
    for lk in g.links:
        in_links[g.dst(lk.to_id)].append(lk)
        out_links[lk.from_id].append(lk)

    es: dict = {}
    ef: dict = {}
    gate: dict = {}
    project_start = min((cal.idx(by_id[t].start) for t in leaves), default=0)
    if g.order is None:
        res.cycle = True
        for tid in leaves:
            t = by_id[tid]
            es[tid] = cal.idx(t.start)
            ef[tid] = es[tid] + max(int(t.duration or 0), 0)
    else:
        for kind, tid in g.order:
            if kind == "G":
                b = gate.get(g.parent.get(tid))
                for lk in in_links[("G", tid)]:
                    f = lk.from_id
                    r = (es[f] if lk.type == "SS" else ef[f]) + lk.lag
                    b = r if b is None else max(b, r)
                gate[tid] = b
            elif kind == "L":
                t = by_id[tid]
                dur = max(int(t.duration or 0), 0)
                own = cal.idx(t.start)
                fixed = not move or (only is not None and tid not in only)
                pin = None if fixed else _pin(cons[tid], cal, dur)
                if fixed:
                    s = own
                elif pin is not None:
                    s = pin
                else:
                    s = project_start if pull else own
                    for ct, cd in cons[tid]:
                        if ct == "snet":
                            s = max(s, cal.idx(cd))
                    pg = gate.get(g.parent.get(tid))
                    if pg is not None:
                        s = max(s, pg)
                    for lk in in_links[("L", tid)]:
                        # a summary source has only the point this link reads yet
                        s = max(s, _req_start(lk, es.get(lk.from_id),
                                              ef.get(lk.from_id), dur))
                es[tid], ef[tid] = s, s + dur
            elif kind == "PS":
                es[tid] = min(es[k] for k in g.start_kids[tid])
            else:
                ef[tid] = max(ef[k] for k in g.real_kids[tid])

    for tid in leaves:
        t = by_id[tid]
        start = cal.date_at(es[tid])
        res.tasks[tid] = TaskResult(
            start=start, end=cal.end_from_idx(es[tid], ef[tid]),
            start_idx=es[tid], end_idx=ef[tid],
            progress=int(t.progress or 0))
        if move and start != t.start and (only is None or tid in only):
            res.moved.append(tid)

    real = [tid for tid in leaves if not by_id[tid].idea]
    if g.order is not None and real:
        project_end = max(ef[tid] for tid in real)
        # the two earliest non-idea starts under each summary: a start
        # bound out of a summary binds a block only when every OTHER block
        # under it starts after the bound (one of them keeps it otherwise)
        first2: dict = {}
        for tid in real:
            for a in g.anc[tid]:
                first2[a] = sorted(first2.get(a, []) + [(es[tid], str(tid), tid)])[:2]

        def others_start(a, tid):
            rest = [x for x in first2.get(a, []) if x[2] != tid]
            return rest[0][0] if rest else None

        lf: dict = {}
        lg: dict = {}
        lpf: dict = {}
        lps: dict = {}

        def late(node, which):
            kind, x = node
            if kind == "L":
                if x not in lf:
                    return None                    # an idea successor
                return lf[x] - (ef[x] - es[x]) if which == "start" else lf[x]
            return lg.get(x) if which == "start" else None

        def bounds(src):
            """(finish bound, start bound) the links out of src put on it."""
            fb = sb = None
            for lk in out_links[src]:
                v = late(g.dst(lk.to_id), "start" if lk.type in ("FS", "SS")
                         else "finish")
                if v is None:
                    continue
                if lk.type in ("FS", "FF"):
                    fb = _min(fb, v - lk.lag)
                else:
                    sb = _min(sb, v - lk.lag)
            return fb, sb

        for kind, tid in reversed(g.order):
            if kind == "G":
                v = None
                for c in g.children[tid]:
                    v = _min(v, lg.get(c) if c in g.summaries else late(("L", c), "start"))
                lg[tid] = v
            elif kind == "PF":
                fb, _sb = bounds(tid)
                p = g.parent.get(tid)
                lpf[tid] = _min(fb, lpf.get(p)) if p is not None else fb
            elif kind == "PS":
                lps[tid] = bounds(tid)[1]
            elif not by_id[tid].idea:
                dur = ef[tid] - es[tid]
                f = project_end
                fb, sb = bounds(tid)
                p = g.parent.get(tid)
                if p is not None:
                    fb = _min(fb, lpf.get(p))
                for a in g.anc[tid]:
                    b = lps.get(a)
                    o = others_start(a, tid)
                    if b is not None and (o is None or o > b):
                        sb = _min(sb, b)
                if fb is not None:
                    f = min(f, fb)
                if sb is not None:
                    f = min(f, sb + dur)
                for ct, cd in cons[tid]:
                    if ct == "fnlt":
                        f = min(f, cal.idx(cd))
                if _pin(cons[tid], cal, dur) is not None:
                    f = min(f, ef[tid])
                lf[tid] = f

        def early(node, which):
            kind, x = node
            if kind == "L":
                if by_id[x].idea:
                    return None
                return es[x] if which == "start" else ef[x]
            return es[x] if which == "start" else None

        for tid in real:
            total = lf[tid] - ef[tid]
            rooms = []
            for src in [tid] + g.anc[tid]:
                o = None if src == tid else others_start(src, tid)
                for lk in out_links[src]:
                    v = early(g.dst(lk.to_id), "start" if lk.type in ("FS", "SS")
                              else "finish")
                    if v is None:
                        continue
                    if lk.type in ("FS", "FF"):
                        rooms.append(v - lk.lag - ef[tid])
                    elif o is None or o > v - lk.lag:
                        rooms.append(v - lk.lag - es[tid])
            free = min(rooms) if rooms else project_end - ef[tid]
            r = res.tasks[tid]
            r.total_slack = total
            r.free_slack = min(free, total)
            r.critical = total <= 0

    # summary rollup, children first
    for tid, _w in reversed(dfs_order(tasks)):
        kids = g.children.get(tid, [])
        if not kids:
            continue
        rs = [res.tasks[k] for k in g.real_kids[tid]]
        weight = sum(max(r.end_idx - r.start_idx, 0) for r in rs)
        # weights: each child's span (a nested summary's rolled-up span);
        # half-up rounding, the same in the browser (not banker's round())
        if weight > 0:
            prog = math.floor(sum(r.progress * max(r.end_idx - r.start_idx, 0)
                                  for r in rs) / weight + 0.5)
        else:
            prog = math.floor(sum(r.progress for r in rs) / len(rs) + 0.5)
        slacks = [r.total_slack for r in rs if r.total_slack is not None]
        frees = [r.free_slack for r in rs if r.free_slack is not None]
        res.tasks[tid] = TaskResult(
            start=min(x.start for x in rs), end=max(x.end for x in rs),
            start_idx=min(x.start_idx for x in rs),
            end_idx=max(x.end_idx for x in rs),
            total_slack=min(slacks) if slacks else None,
            free_slack=min(frees) if frees else None,
            critical=any(x.critical for x in rs), is_summary=True,
            progress=prog)
    for tid, wbs in dfs_order(tasks):
        res.tasks[tid].wbs = wbs
    return res


def schedule(tasks: list[ETask], links: list[ELink], cal: Calendar,
             *, pull: bool = False) -> PlanResult:
    return compute(tasks, links, cal, move=True, pull=pull)


def analyse(tasks: list[ETask], links: list[ELink], cal: Calendar) -> PlanResult:
    return compute(tasks, links, cal, move=False)


def downstream(tasks: list[ETask], links: list[ELink], sources: list) -> dict:
    """leaf id -> the nearest source whose move can push it along the
    links: successors, successors of every summary above it, every leaf
    under a summary it links into. The walk stops at another source (that
    one answers for what lies behind it); between two sources the first in
    the given order wins. The sources themselves are not in the result."""
    g = graph(tasks, links)
    srcs = set(sources)
    cause: dict = {}
    for src in sources:
        if src not in g.by_id:
            continue
        starts = ([("PS", src), ("PF", src)] if src in g.summaries
                  else [("L", src)])
        seen, stack = set(starts), list(starts)
        while stack:
            n = stack.pop()
            for m in g.succ.get(n, []):
                if m in seen or (m[0] == "L" and m[1] in srcs):
                    continue                     # another source answers for it
                seen.add(m)
                stack.append(m)
                if m[0] == "L" and m[1] not in cause:
                    cause[m[1]] = src
    return cause


def cascade(tasks: list[ETask], links: list[ELink], cal: Calendar,
            sources: list) -> tuple[PlanResult, dict]:
    """The forward pass restricted to what moving `sources` pushes: only
    their downstream leaves move (later, never earlier; a pinned block keeps
    its date, and so does a block whose work has started: the walk goes on
    through it, it stays put). Returns the result and {moved leaf: source
    that caused it}."""
    return push(tasks, links, cal, sources)


def push(tasks: list[ETask], links: list[ELink], cal: Calendar, sources: list,
         also: Iterable = ()) -> tuple[PlanResult, dict]:
    """cascade(), plus `also`: blocks that may move themselves (a new link
    or lag into them, a changed constraint on them), each its own cause.
    Automatic scheduling before the baseline and the deviation cascade
    after it are this one forward pass."""
    cause = downstream(tasks, links, list(sources) + [a for a in also
                                                      if a not in sources])
    for a in also:
        cause.setdefault(a, a)
    cons = _constraints(tasks)
    started = {t.id for t in tasks if t.started}
    summaries = summary_ids(tasks)
    movable = {tid for tid in cause
               if tid not in summaries and tid not in started
               and (tid in also or _pin(cons.get(tid, []), cal, 0) is None)}
    res = compute(tasks, links, cal, move=True, only=movable)
    return res, {tid: cause[tid] for tid in res.moved}


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
def issue(code: str, message: str, task_id=None) -> dict:
    return {"code": code, "message": message, "task_id": task_id}


def _lag_txt(lag: int) -> str:
    return f" (lag {lag:+d}d)" if lag else ""


_VERBS = {"FS": ("starts", "ends"), "SS": ("starts", "starts"),
          "FF": ("ends", "ends"), "SF": ("ends", "starts")}


def engine_issues(tasks: list[ETask], links: list[ELink], cal: Calendar) -> dict:
    """The scheduling issues on the dates as they stand. Errors:
    negative_duration, empty_name, unknown_predecessor, dependency_violation,
    cycle, summary_finish_link (FF/SF into a summary), summary_pin (mso/mfo
    on a summary). Warnings: constraint_conflict (also a link a pinned block
    breaks), summary_link (a link on a summary, applied to the blocks under
    it, or between a block and its own summary)."""
    errors, warnings = [], []
    g = graph(tasks, links)
    by_id, summaries, anc = g.by_id, g.summaries, g.anc
    for t in tasks:
        if not (t.name or "").strip():
            errors.append(issue("empty_name", "A block has no name", t.id))
        if int(t.duration or 0) < 0:
            errors.append(issue(
                "negative_duration", f"'{t.name}' has a negative duration", t.id))
        if t.id in summaries and t.constraint_type in PIN_CONSTRAINTS \
                and t.constraint_date:
            errors.append(issue(
                "summary_pin",
                f"'{t.name}' is a summary: a must-start-on or must-finish-on "
                "constraint on it is not allowed (put it on a block under it)",
                t.id))
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
        elif lk.to_id in summaries and lk.type in FINISH_TARGET_LINKS:
            errors.append(issue(
                "summary_finish_link",
                f"The {lk.type} link from '{f.name}' into the summary '{t.name}' "
                "is not allowed (link to a block under it)", lk.to_id))
        elif lk.from_id in summaries or lk.to_id in summaries:
            warnings.append(issue(
                "summary_link",
                f"The link from '{f.name}' to '{t.name}' is on a summary block: "
                "it applies to the blocks under it", lk.to_id))
    if g.order is None or any(lk.from_id == lk.to_id for lk in links):
        errors.append(issue("cycle", "The dependencies form a loop"))

    cons = _constraints(tasks)
    es: dict = {}
    ef: dict = {}
    for tid in g.leaves:
        t = by_id[tid]
        es[tid] = cal.idx(t.start)
        ef[tid] = es[tid] + max(int(t.duration or 0), 0)
    for tid, _w in reversed(dfs_order(tasks)):
        kids = g.real_kids.get(tid, [])
        if kids:
            es[tid] = min(es[k] for k in kids)
            ef[tid] = max(ef[k] for k in kids)
    under = _leaves_under(tasks, [lk.to_id for lk in g.links
                                  if lk.to_id in summaries])

    seen = set()
    for lk in g.links:
        p, s = by_id[lk.from_id], by_id[lk.to_id]
        key = (p.id, s.id, lk.type, lk.lag)
        if key in seen:
            continue
        verb = _VERBS[lk.type]
        text = f"'{s.name}' {verb[0]} before '{p.name}' {verb[1]}{_lag_txt(lk.lag)}"
        if s.id in summaries:
            need = (es[p.id] if lk.type == "SS" else ef[p.id]) + lk.lag
            bad = [x for x in under[s.id] if es[x] < need]
            if not bad:
                continue
            seen.add(key)
            pinned = all(_pin(cons[x], cal, ef[x] - es[x]) is not None for x in bad)
        else:
            need = _req_start(lk, es[p.id], ef[p.id], ef[s.id] - es[s.id])
            if es[s.id] >= need:
                continue
            seen.add(key)
            pinned = _pin(cons[s.id], cal, ef[s.id] - es[s.id]) is not None
        if pinned:
            warnings.append(issue(
                "constraint_conflict", text + ", pinned by its constraint", s.id))
        else:
            errors.append(issue("dependency_violation", text, s.id))

    # A leaf: its own constraint and the snet of every summary above it. A
    # summary: its fnlt against its rolled-up finish (spec §11).
    checks = []
    for tid in g.leaves:
        t = by_id[tid]
        own = [(t.constraint_type, t.constraint_date)] if (
            t.constraint_type and t.constraint_type != "asap"
            and t.constraint_date) else []
        checks.append((t, own + [c for c in cons[tid][len(own):] if c[0] == "snet"]))
    for sid in summaries:
        t = by_id[sid]
        if t.constraint_type == "fnlt" and t.constraint_date:
            checks.append((t, [("fnlt", t.constraint_date)]))
    for t, tcons in checks:
        s, e = es[t.id], ef[t.id]
        for ct, cdate in tcons:
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
        # Working mode: holidays are non-working days. Calendar mode: they
        # only shade the chart, so they go out as WORKING exceptions (MS
        # Project schedules through them, like we do) under a name the
        # import reads back as shading.
        exs = el(c, "Exceptions")
        for h in cal.holidays:
            ex = el(exs, "Exception")
            el(ex, "EnteredByOccurrences", 0)
            tp = el(ex, "TimePeriod")
            el(tp, "FromDate", ts(h, "00:00:00"))
            el(tp, "ToDate", ts(h, "23:59:00"))
            el(ex, "Occurrences", 1)
            el(ex, "Name", "Holiday" if working else SHADING_HOLIDAY)
            el(ex, "Type", 1)
            el(ex, "DayWorking", 0 if working else 1)
            if not working:
                wts = el(ex, "WorkingTimes")
                for a, b in (("08:00:00", "12:00:00"), ("13:00:00", "17:00:00")):
                    wt = el(wts, "WorkingTime")
                    el(wt, "FromTime", a)
                    el(wt, "ToTime", b)

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
        ct, cd = t.get("constraint_type"), t.get("constraint_date")
        if ct in MSPDI_CONSTRAINT and ct != "asap" and cd and not (
                t.get("summary") and ct in PIN_CONSTRAINTS):
            # a summary carries its own snet / fnlt (MS Project allows those)
            el(te, "ConstraintType", MSPDI_CONSTRAINT[ct])
            el(te, "ConstraintDate",
               ts(cd) if ct in START_CONSTRAINTS else fin(cd))
        elif not t.get("summary"):
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


# Calendar exception Type (MSPDI): 1 daily, 2 yearly by month day, 3 yearly
# by position, 4 monthly by month day, 5 monthly by position, 6 weekly.
# MonthItem: 0 day, 1 weekday, 2 weekend day, 3..9 Sunday..Saturday.
# MonthPosition: 0..3 first..fourth, 4 last. Month: 0..11. DaysOfWeek: bit
# mask, 1 = Sunday .. 64 = Saturday.
MAX_HOLIDAYS = 5000
SHADING_HOLIDAY = "Holiday (shading only)"


def _month_len(y: int, m: int) -> int:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - date(y, m, 1)).days


def _month_day(y: int, m: int, day: int) -> Optional[date]:
    if not 1 <= m <= 12 or day < 1:
        return None
    return date(y, m, min(day, _month_len(y, m)))


def _month_pos(y: int, m: int, pos: int, item: int) -> Optional[date]:
    if not 1 <= m <= 12 or not 0 <= pos <= 4 or not 0 <= item <= 9:
        return None

    def match(d: date) -> bool:
        wd = d.isoweekday()
        if item == 0:
            return True
        if item == 1:
            return wd <= 5
        if item == 2:
            return wd >= 6
        return wd == (7 if item == 3 else item - 3)
    days = [d for d in (date(y, m, k) for k in range(1, _month_len(y, m) + 1))
            if match(d)]
    if not days:
        return None
    if pos == 4:
        return days[-1]
    return days[pos] if pos < len(days) else None


def recurring_days(typ: int, a: date, b: date, *, period: int = 1,
                   month: int = 0, month_day: int = 1, month_item: int = 0,
                   month_pos: int = 0, days_of_week: int = 0,
                   occurrences: int = 0, cap: int = MAX_HOLIDAYS) -> Optional[list]:
    """The days of one calendar exception between a and b (inclusive), at
    most `cap` (and `occurrences` when given). None for an unknown type."""
    out: list = []
    step = max(1, int(period or 1))
    if typ == 1:
        d = a
        while d <= b and len(out) < cap:
            out.append(d)
            d += timedelta(days=step)
    elif typ == 6:
        mask = days_of_week or (1 << (a.isoweekday() % 7))
        w = a - timedelta(days=a.isoweekday() % 7)          # the Sunday before
        while w <= b and len(out) < cap:
            for k in range(7):                                # 0 = Sunday
                d = w + timedelta(days=k)
                if mask & (1 << k) and a <= d <= b and len(out) < cap:
                    out.append(d)
            w += timedelta(days=7 * step)
    elif typ in (2, 3):
        for y in range(a.year, b.year + 1):
            d = (_month_day(y, month + 1, month_day) if typ == 2
                 else _month_pos(y, month + 1, month_pos, month_item))
            if d is not None and a <= d <= b:
                out.append(d)
            if len(out) >= cap:
                break
    elif typ in (4, 5):
        y, m = a.year, a.month
        while (y, m) <= (b.year, b.month) and len(out) < cap:
            d = (_month_day(y, m, month_day) if typ == 4
                 else _month_pos(y, m, month_pos, month_item))
            if d is not None and a <= d <= b:
                out.append(d)
            m += step
            y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    else:
        return None
    if occurrences and occurrences > 0:
        out = out[:occurrences]
    return out


def _guard_xml(content: bytes) -> None:
    """Refuse a DTD, entity or notation declaration before ElementTree sees
    the file. A real parser (expat) instead of a byte search, so a UTF-16
    file or a declaration split by whitespace cannot slip past."""
    from xml.parsers import expat

    def refuse(*_args):
        raise MspdiError(
            "The file declares a DTD or entities, which MS Project XML never does")
    p = expat.ParserCreate()
    p.StartDoctypeDeclHandler = refuse
    p.EntityDeclHandler = refuse
    p.UnparsedEntityDeclHandler = refuse
    p.NotationDeclHandler = refuse
    p.ExternalEntityRefHandler = refuse
    try:
        p.Parse(content, True)
    except expat.ExpatError as e:
        raise MspdiError(f"The file is not valid XML ({e})")


def _bounded(d: date, what: str) -> date:
    if not MIN_YEAR <= d.year <= MAX_YEAR:
        raise MspdiError(f"{what}: the date {d.isoformat()} is outside the years "
                         f"{MIN_YEAR}-{MAX_YEAR}")
    return d


def parse_mspdi(content: bytes) -> dict:
    """An MSPDI file as {calendar: Calendar, tasks: [...], links: [...],
    warnings: [str]}.

    tasks: {uid, name, start, duration, milestone, parent_uid, level,
    summary, constraint_type, constraint_date, notes, lane, kind, idea,
    progress, actual_start, actual_finish, baseline_start, baseline_finish},
    in file order.
    links: {from_uid, to_uid, type, lag}. Durations and lags are converted
    to the detected calendar's units (an elapsed lag in a working-day file
    is scaled by the working days per week, and back); SNET on the task's
    own start (what our export writes for unconstrained blocks) reads back as
    no constraint, which our "never earlier" scheduling makes equivalent.
    A start moment at or after the end of the working day (a milestone MS
    Project puts at 17:00) is the next day. Refused (MspdiError): not XML, a
    DTD or entities, dates outside 1900-2200, absurd durations or lags,
    an outline deeper than MAX_OUTLINE_DEPTH, mso/mfo on a summary, FF/SF
    into a summary. Skipped with a warning: cross-project links, calendar
    exceptions of an unknown recurrence type, actual dates in the future."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    try:
        return _parse_mspdi(content)
    except MspdiError:
        raise
    except (ValueError, OverflowError, RecursionError, TypeError,
            AttributeError) as e:
        raise MspdiError(f"The file could not be read as MS Project XML ({e})")


def _parse_mspdi(content: bytes) -> dict:
    _guard_xml(content)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise MspdiError(f"The file is not valid XML ({e})")
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag[1:].split("}")[0]
    if root.tag.split("}")[-1] != "Project":
        raise MspdiError("The file is not an MS Project XML file (no Project element)")
    warnings: list[str] = []

    def q(tag):
        return f"{{{ns}}}{tag}" if ns else tag

    def txt(e, tag, default=None):
        x = e.find(q(tag)) if e is not None else None
        return x.text.strip() if x is not None and x.text is not None else default

    def num(e, tag, default=0):
        v = txt(e, tag)
        try:
            return int(float(v)) if v is not None else default
        except (ValueError, OverflowError):
            return default

    minutes_per_day = num(root, "MinutesPerDay", MINUTES_PER_WORKDAY) or MINUTES_PER_WORKDAY
    if not 1 <= minutes_per_day <= 1440:
        minutes_per_day = MINUTES_PER_WORKDAY
    project_fmt = num(root, "DurationFormat", 7)
    day_end = (17, 0)
    dft = txt(root, "DefaultFinishTime")
    if dft:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", dft)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            day_end = (int(m.group(1)), int(m.group(2)))

    def start_day(dt: datetime) -> date:
        """A start moment as a day: at or after the end of the working day
        it is the next day (a milestone MS Project puts at 17:00)."""
        if (dt.hour, dt.minute) >= day_end:
            return dt.date() + timedelta(days=1)
        return dt.date()

    def finish_day(dt: datetime) -> date:
        """A finish moment as an exclusive end date: late in the day is the
        end of that day."""
        return dt.date() + timedelta(days=1) if dt.hour >= 12 else dt.date()

    lo_d, hi_d = date(MIN_YEAR, 1, 1), date(MAX_YEAR, 12, 31)

    # The calendar: the project's (CalendarUID), else the first base
    # calendar; never a resource calendar. Weekdays it does not list come
    # from its base calendar (BaseCalendarUID, followed up the chain), else
    # Mon-Fri; exceptions of the whole chain are merged.
    cal_uid = txt(root, "CalendarUID")
    all_cals: dict = {}
    base_flag: dict = {}
    cals = root.find(q("Calendars"))
    for c in (cals.findall(q("Calendar")) if cals is not None else []):
        uid = txt(c, "UID")
        if uid is not None and uid not in all_cals:
            all_cals[uid] = c
            base_flag[uid] = txt(c, "IsBaseCalendar")
    res_root = root.find(q("Resources"))
    resource_cals = {txt(r, "CalendarUID") for r in (
        res_root.findall(q("Resource")) if res_root is not None else [])}
    resource_cals |= {u for u, f in base_flag.items() if f == "0"}
    resource_cals.discard(None)
    cal_el = None
    if cal_uid in all_cals and cal_uid not in resource_cals:
        cal_el = all_cals[cal_uid]
    else:
        cal_el = next((c for u, c in all_cals.items() if base_flag[u] == "1"), None) \
            or next((c for u, c in all_cals.items() if u not in resource_cals), None)
    chain = []
    c, seen_uids = cal_el, set()
    while c is not None and len(chain) < 10:
        chain.append(c)
        seen_uids.add(txt(c, "UID"))
        nxt = txt(c, "BaseCalendarUID")
        c = all_cals.get(nxt) if nxt not in seen_uids else None
    workdays = list(DEFAULT_WORKDAYS)
    holidays: list[date] = []
    shading: list[date] = []

    def period_of(el):
        tp = el.find(q("TimePeriod"))
        a, b = _parse_dt(txt(tp, "FromDate")), _parse_dt(txt(tp, "ToDate"))
        if not a or not b:
            return None
        a, b = max(a.date(), lo_d), min(b.date(), hi_d)
        return (a, b) if a <= b else None

    found: dict = {}
    for cal_el in chain:
        wds = cal_el.find(q("WeekDays"))
        if wds is not None:
            for wd in wds.findall(q("WeekDay")):
                dt = num(wd, "DayType", -1)
                if 1 <= dt <= 7:
                    iso = 7 if dt == 1 else dt - 1
                    if iso not in found:          # the derived calendar wins
                        found[iso] = num(wd, "DayWorking", 1) == 1
                elif dt == 0 and num(wd, "DayWorking", 1) == 0:
                    ab = period_of(wd)
                    if ab:
                        holidays += recurring_days(
                            1, ab[0], ab[1], cap=MAX_HOLIDAYS - len(holidays))
        exs = cal_el.find(q("Exceptions"))
        if exs is not None:
            for ex in exs.findall(q("Exception")):
                name = txt(ex, "Name") or ""
                working = num(ex, "DayWorking", 0) == 1
                if working and not name.startswith(SHADING_HOLIDAY):
                    continue
                ab = period_of(ex)
                if not ab:
                    continue
                typ = num(ex, "Type", 1)
                days = recurring_days(
                    typ, ab[0], ab[1], period=num(ex, "Period", 1),
                    month=num(ex, "Month", 0), month_day=num(ex, "MonthDay", 1),
                    month_item=num(ex, "MonthItem", 0),
                    month_pos=num(ex, "MonthPosition", 0),
                    days_of_week=num(ex, "DaysOfWeek", 0),
                    occurrences=(num(ex, "Occurrences", 0)
                                 if num(ex, "EnteredByOccurrences", 0) == 1 else 0),
                    cap=MAX_HOLIDAYS - len(holidays) - len(shading))
                if days is None:
                    warnings.append(
                        f"Calendar exception '{name or '?'}' has an unknown "
                        f"recurrence type {typ} and was skipped")
                    continue
                (shading if working else holidays).extend(days)
    if found:
        week = {d: found.get(d, d in DEFAULT_WORKDAYS) for d in range(1, 8)}
        workdays = sorted(d for d, on in week.items() if on) or workdays
    holidays = sorted(set(holidays))
    shading = sorted(set(shading))
    file_per_week = len(workdays) or 5

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
    if elapsed:
        holidays = holidays + shading
        if len(workdays) == 7:
            # our calendar-mode export marks every day working; the weekdays
            # only shade the chart then, so keep the usual Mon-Fri shading
            workdays = list(DEFAULT_WORKDAYS)
    cal = Calendar("calendar" if elapsed else "working", workdays, holidays)

    def to_days(hours: float, fmt: int) -> int:
        """Hours in a duration / lag format as days of the plan calendar."""
        if fmt in _ELAPSED_FORMATS:
            days = hours / 24
            return int(round(days * file_per_week / 7 if cal.working else days))
        days = hours * 60 / minutes_per_day
        return int(round(days if cal.working else days * 7 / file_per_week))

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

    latest_actual = date.today() + timedelta(days=1)
    tasks, links = [], []
    stack: list[tuple[int, str]] = []            # (level, uid)
    for te in raw:
        uid = txt(te, "UID")
        name = (txt(te, "Name") or "").strip()
        level = max(1, num(te, "OutlineLevel", 1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        if len(stack) + 1 > MAX_OUTLINE_DEPTH:
            raise MspdiError(
                f"'{name}' sits deeper than {MAX_OUTLINE_DEPTH} outline levels")
        parent = stack[-1][1] if stack else None
        stack.append((level, uid))
        start = _bounded(start_day(_parse_dt(txt(te, "Start"))), f"'{name}'")
        fmt = num(te, "DurationFormat", project_fmt)
        days = max(0, to_days(_parse_hours(txt(te, "Duration")), fmt))
        if days > MAX_DURATION_DAYS:
            raise MspdiError(f"'{name}' lasts {days} days, more than "
                             f"{MAX_DURATION_DAYS}")
        milestone = num(te, "Milestone", 0) == 1
        if milestone:
            days = 0
        ct = MSPDI_CONSTRAINT_BACK.get(num(te, "ConstraintType", 0))
        cdt = _parse_dt(txt(te, "ConstraintDate"))
        cd = None
        if ct in START_CONSTRAINTS and cdt:
            cd = start_day(cdt)
        elif ct in FINISH_CONSTRAINTS and cdt:
            cd = finish_day(cdt)
        if ct == "snet" and cd == start:
            ct, cd = None, None
        if ct == "asap" or cd is None:
            ct, cd = None, None
        if cd is not None:
            _bounded(cd, f"'{name}' constraint")
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
        progress = min(100, max(0, num(te, "PercentComplete", 0)))
        actual = {}
        for key, tag in (("actual_start", "ActualStart"),
                         ("actual_finish", "ActualFinish")):
            v = _parse_dt(txt(te, tag))
            if v is None:
                actual[key] = None
            elif v.date() > latest_actual:
                warnings.append(f"'{name}': the {tag} {v.date().isoformat()} is "
                                "in the future and was not imported")
                actual[key] = None
            else:
                actual[key] = _bounded(v.date(), f"'{name}' {tag}")
        bl_start = bl_finish = None
        for bl in te.findall(q("Baseline")):
            if num(bl, "Number", -1) != 0:
                continue
            bs, bf = _parse_dt(txt(bl, "Start")), _parse_dt(txt(bl, "Finish"))
            if bs is None or bf is None:
                continue
            bl_start = _bounded(start_day(bs), f"'{name}' baseline")
            bl_finish = bl_start if bf <= bs else max(
                bl_start, _bounded(finish_day(bf), f"'{name}' baseline"))
        tasks.append({
            "uid": uid, "name": name,
            "start": start, "duration": days, "milestone": milestone,
            "parent_uid": parent, "level": level,
            "summary": num(te, "Summary", 0) == 1,
            "constraint_type": ct, "constraint_date": cd,
            "notes": " | ".join(rest) or None, "lane": lane, "kind": kind,
            "idea": idea, "progress": progress, **actual,
            "baseline_start": bl_start, "baseline_finish": bl_finish,
        })
        for pl in te.findall(q("PredecessorLink")):
            if num(pl, "CrossProject", 0) == 1:
                warnings.append(f"'{name}': a link to another project "
                                f"({txt(pl, 'CrossProjectName') or '?'}) was skipped")
                continue
            lag_fmt = num(pl, "LagFormat", 7)
            minutes = num(pl, "LinkLag", 0) / 10
            lag = to_days(minutes / 60, lag_fmt)
            if abs(lag) > MAX_LAG_DAYS:
                raise MspdiError(f"'{name}': a lag of {lag} days is more than "
                                 f"{MAX_LAG_DAYS}")
            links.append({
                "from_uid": txt(pl, "PredecessorUID"), "to_uid": uid,
                "type": MSPDI_LINK_TYPE_BACK.get(num(pl, "Type", 1), "FS"),
                "lag": lag,
            })

    # MS Project's own rules for summaries, which our math relies on
    parents = {t["parent_uid"] for t in tasks if t["parent_uid"] is not None}
    names = {t["uid"]: t["name"] for t in tasks}
    for t in tasks:
        if t["uid"] in parents and t["constraint_type"] in PIN_CONSTRAINTS:
            raise MspdiError(
                f"'{t['name']}' is a summary task with a must-start-on or "
                "must-finish-on constraint, which MS Project does not allow")
    for lk in links:
        if lk["to_uid"] in parents and lk["type"] in FINISH_TARGET_LINKS:
            raise MspdiError(
                f"The {lk['type']} link into the summary task "
                f"'{names.get(lk['to_uid'])}' is not allowed (MS Project "
                "refuses finish links into a summary)")
    return {"calendar": cal, "tasks": tasks, "links": links, "warnings": warnings}
