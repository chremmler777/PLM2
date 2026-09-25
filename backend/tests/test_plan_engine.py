"""Gantt 2.0 engine: the shared vectors (the frontend TS engine asserts the
same file), calendar math, validation issues, MSPDI read/write and the 088
predecessor migration.
"""
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.services.plan_engine import (
    Calendar, ELink, ETask, MspdiError, analyse, build_mspdi, engine_issues,
    parse_mspdi, schedule, topo,
)

DATA = Path(__file__).parent / "data" / "gantt_vectors.json"
CASES = json.loads(DATA.read_text())["cases"]


def _load(case):
    cal = Calendar.from_json(case["calendar"])
    tasks = [ETask(id=t["id"], start=date.fromisoformat(t["start"]),
                   duration=t["duration"],
                   constraint_type=(t["constraint"] or {}).get("type"),
                   constraint_date=(date.fromisoformat(t["constraint"]["date"])
                                    if t["constraint"] else None),
                   parent_id=t["parentId"], name=t["id"],
                   idea=bool(t.get("isIdea")))
             for t in case["tasks"]]
    links = [ELink(from_id=lk["from"], to_id=lk["to"], type=lk["type"],
                   lag=lk["lag"]) for lk in case["links"]]
    return cal, tasks, links


def test_vector_file_shape():
    assert len(CASES) >= 25
    names = [c["name"] for c in CASES]
    assert len(set(names)) == len(names)
    for c in CASES:
        assert {"name", "calendar", "tasks", "links", "expected"} <= set(c)
        assert set(c) <= {"name", "calendar", "options", "tasks", "links", "expected"}
        assert set(c["calendar"]) == {"mode", "workdays", "holidays"}
        for t in c["tasks"]:
            assert {"id", "start", "duration", "constraint", "parentId"} <= set(t)
            assert set(t) <= {"id", "start", "duration", "constraint", "parentId",
                              "isIdea"}
        for lk in c["links"]:
            assert set(lk) == {"from", "to", "type", "lag"}
        assert set(c["expected"]) == {t["id"] for t in c["tasks"]}
        for e in c["expected"].values():
            assert {"start", "end", "total_slack", "critical"} <= set(e)
            assert set(e) <= {"start", "end", "total_slack", "critical", "free_slack"}
    covered = {lk["type"] for c in CASES for lk in c["links"]}
    assert covered == {"FS", "SS", "FF", "SF"}
    ctypes = {t["constraint"]["type"] for c in CASES for t in c["tasks"]
              if t["constraint"]}
    assert ctypes == {"snet", "fnlt", "mso", "mfo"}
    for c in CASES:
        assert set(c.get("options") or {}) <= {"pull", "cycle", "refused"}
    names = set(names)
    # spec §11 "Summary task rule": the cases both engines must cover
    for must in ("summary: FS into a summary bounds every leaf below it",
                 "summary: SS into a summary bounds every leaf below it",
                 "summary: FS from a summary binds to its rolled-up finish",
                 "summary: SS from a summary binds to its earliest start",
                 "summary: SF from a summary binds to its earliest start",
                 "summary refused: FF into a summary is not scheduled",
                 "summary refused: mso on a summary is not scheduled",
                 "summary: snet on a summary bounds every leaf below it",
                 "cycle: blocks keep their dates and have no slack",
                 "working: holiday on the start day",
                 "working: negative lag across a weekend",
                 "summary: SS from a summary binds a block only when no other "
                 "block holds its start",
                 "summary: SS from a summary to a block feeding a later child "
                 "is not a cycle"):
        assert must in names


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vectors(case):
    cal, tasks, links = _load(case)
    opts = case.get("options") or {}
    res = schedule(tasks, links, cal, pull=bool(opts.get("pull")))
    # a cycle stops the pass (blocks keep their dates); a refused link or
    # constraint is an error and is left out of the math
    assert res.cycle is bool(opts.get("cycle"))
    codes = {e["code"] for e in engine_issues(tasks, links, cal)["errors"]}
    if opts.get("cycle"):
        assert "cycle" in codes
    if opts.get("refused"):
        assert opts["refused"] in codes
    full = {tid: {"start": r.start.isoformat(), "end": r.end.isoformat(),
                  "total_slack": r.total_slack, "critical": r.critical,
                  "free_slack": r.free_slack}
            for tid, r in res.tasks.items()}
    # only the keys a case lists are compared (spec §11 Vectors)
    got = {tid: {k: full[tid][k] for k in exp} for tid, exp in case["expected"].items()}
    assert got == case["expected"]


def test_calendar_index_round_trip_with_holidays():
    cal = Calendar("working", [1, 2, 3, 4, 5], ["2026-12-24", "2026-12-25",
                                                "2026-12-26"])
    d = date(2026, 12, 1)
    prev = None
    for _ in range(60):
        i = cal.idx(d)
        if cal.is_work(d):
            assert cal.date_at(i) == d
            if prev is not None:
                assert i == prev + 1
            prev = i
        else:
            assert cal.date_at(i) > d            # snaps to the next working day
        d += timedelta(days=1)
    # Wed 23 Dec + 2 working days: Wed, (24/25 holidays), Mon 28 -> ends Tue 29
    assert cal.end_date(date(2026, 12, 23), 2) == date(2026, 12, 29)
    assert cal.span(date(2026, 12, 23), date(2026, 12, 29)) == 2
    # calendar mode ignores weekends and holidays
    assert Calendar().end_date(date(2026, 12, 23), 2) == date(2026, 12, 25)
    # a working calendar without workdays degrades to elapsed days
    assert Calendar("working", [], []).working is False


def test_cycle_and_issues():
    cal = Calendar()
    d = date(2026, 10, 5)
    tasks = [ETask("A", d, 5, name="A"), ETask("B", d, 2, name="B"),
             ETask("C", d, 2, name="C"),
             ETask("S", d, 0, name="S"), ETask("K", d, 1, parent_id="S", name="K"),
             ETask("F", d, 10, constraint_type="fnlt",
                   constraint_date=date(2026, 10, 8), name="F")]
    links = [ELink("A", "B", "FS"), ELink("A", "C", "SF", 3), ELink("S", "B")]
    found = engine_issues(tasks, links, cal)
    errors = [(e["code"], e["task_id"]) for e in found["errors"]]
    assert ("dependency_violation", "B") in errors
    assert ("dependency_violation", "C") in errors
    msg = next(e["message"] for e in found["errors"] if e["task_id"] == "C")
    assert msg == "'C' ends before 'A' starts (lag +3d)"
    warnings = {(w["code"], w["task_id"]) for w in found["warnings"]}
    assert ("summary_link", "B") in warnings
    assert ("constraint_conflict", "F") in warnings
    # a loop
    loop = [ELink("A", "B"), ELink("B", "A")]
    assert topo(["A", "B"], loop) is None
    assert "cycle" in {e["code"] for e in engine_issues(tasks, loop, cal)["errors"]}
    assert schedule(tasks, loop, cal).cycle is True
    # an unknown end
    bad = engine_issues(tasks, [ELink(99, "A")], cal)
    assert bad["errors"][0]["code"] == "unknown_predecessor"


def test_analyse_keeps_dates_and_reports_free_slack():
    cal = Calendar()
    d = date(2026, 10, 5)
    # A(5) -> B(2) starting 3 days after A ends; B -> C(1) right after
    tasks = [ETask("A", d, 5), ETask("B", d + timedelta(days=8), 2),
             ETask("C", d + timedelta(days=10), 1)]
    links = [ELink("A", "B"), ELink("B", "C")]
    res = analyse(tasks, links, cal)
    assert res.moved == []
    assert res.tasks["A"].start == d
    assert res.tasks["A"].free_slack == 3 and res.tasks["A"].total_slack == 3
    assert res.tasks["B"].free_slack == 0 and res.tasks["C"].critical


def test_summary_progress_weighted_by_duration():
    cal = Calendar()
    d = date(2026, 10, 5)
    tasks = [ETask("S", d, 0), ETask("A", d, 8, parent_id="S", progress=100),
             ETask("B", d, 2, parent_id="S", progress=0)]
    res = analyse(tasks, [], cal)
    assert res.tasks["S"].progress == 80 and res.tasks["S"].is_summary
    assert [res.tasks[t].wbs for t in ("S", "A", "B")] == ["1", "1.1", "1.2"]


def _sample_rows(cal):
    d = date(2026, 10, 5)
    return [
        {"key": 1, "name": "Phase", "start": d, "duration": 7,
         "end": cal.end_date(d, 7), "level": 1, "outline": "1", "summary": True},
        {"key": 2, "name": "Design \x07bell", "start": d, "duration": 3,
         "end": cal.end_date(d, 3), "level": 2, "outline": "1.1",
         "constraint_type": "snet", "constraint_date": date(2026, 10, 1),
         "notes": "Lane: Development | Kind: work | first", "lane": "Development"},
        {"key": 3, "name": "Build", "start": date(2026, 10, 8), "duration": 4,
         "end": cal.end_date(date(2026, 10, 8), 4), "level": 2, "outline": "1.2",
         "constraint_type": "fnlt", "constraint_date": date(2026, 10, 20)},
        {"key": 4, "name": "Done", "start": date(2026, 10, 14), "duration": 0,
         "end": date(2026, 10, 14), "level": 1, "outline": "2",
         "milestone": True, "constraint_type": "mso",
         "constraint_date": date(2026, 10, 14)},
    ]


@pytest.mark.parametrize("mode", ["calendar", "working"])
def test_mspdi_round_trip(mode):
    cal = Calendar(mode, [1, 2, 3, 4, 5], ["2026-10-12"])
    rows = _sample_rows(cal)
    links = [{"from": 2, "to": 3, "type": "SS", "lag": 2},
             {"from": 3, "to": 4, "type": "FF", "lag": -1}]
    xml = build_mspdi(name="x.xml", title="x", cal=cal, tasks=rows, links=links)
    assert b"\x07" not in xml                   # control characters stripped
    back = parse_mspdi(xml)
    assert back["calendar"].to_json() == cal.to_json()
    t = {r["name"]: r for r in back["tasks"]}
    assert set(t) == {"Phase", "Design bell", "Build", "Done"}
    assert t["Design bell"]["parent_uid"] == t["Phase"]["uid"]
    assert t["Phase"]["summary"] is True and t["Done"]["parent_uid"] is None
    assert t["Design bell"]["duration"] == 3 and t["Build"]["duration"] == 4
    assert t["Done"]["milestone"] is True and t["Done"]["duration"] == 0
    assert (t["Design bell"]["constraint_type"],
            t["Design bell"]["constraint_date"]) == ("snet", date(2026, 10, 1))
    assert (t["Build"]["constraint_type"],
            t["Build"]["constraint_date"]) == ("fnlt", date(2026, 10, 20))
    assert (t["Done"]["constraint_type"],
            t["Done"]["constraint_date"]) == ("mso", date(2026, 10, 14))
    assert t["Design bell"]["lane"] == "Development"
    assert t["Design bell"]["kind"] == "work" and t["Design bell"]["notes"] == "first"
    uid = {r["uid"]: r["name"] for r in back["tasks"]}
    got = {(uid[lk["from_uid"]], uid[lk["to_uid"]], lk["type"], lk["lag"])
           for lk in back["links"]}
    assert got == {("Design bell", "Build", "SS", 2), ("Build", "Done", "FF", -1)}


def test_mspdi_link_lag_units():
    from xml.etree import ElementTree as ET
    ns = "{http://schemas.microsoft.com/project}"
    for mode, tenths, fmt in (("working", 2 * 4800, "7"),
                              ("calendar", 2 * 14400, "8")):
        cal = Calendar(mode)
        xml = build_mspdi(name="x", title="x", cal=cal, tasks=_sample_rows(cal),
                          links=[{"from": 2, "to": 3, "type": "FS", "lag": 2}])
        root = ET.fromstring(xml)
        link = root.find(f".//{ns}PredecessorLink")
        assert link.find(f"{ns}LinkLag").text == str(tenths)
        assert link.find(f"{ns}LagFormat").text == fmt
        assert link.find(f"{ns}Type").text == "1"
        per_day = int(root.find(f"{ns}MinutesPerDay").text)
        per_week = int(root.find(f"{ns}MinutesPerWeek").text)
        working = [wd for wd in root.iter(f"{ns}WeekDay")
                   if wd.find(f"{ns}DayWorking").text == "1"]
        assert per_week == per_day * len(working)   # a consistent calendar


def test_mspdi_rejects_junk_and_entities():
    with pytest.raises(MspdiError):
        parse_mspdi(b"not xml")
    with pytest.raises(MspdiError):
        parse_mspdi(b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'b'>]>"
                    b"<Project/>")
    with pytest.raises(MspdiError):
        parse_mspdi(b"<Other/>")


def test_migration_converts_predecessors():
    path = (Path(__file__).parent.parent / "alembic" / "versions"
            / "088_plan_links_calendar.py")
    # backend/alembic (the scripts folder) shadows the alembic package on
    # this PYTHONPATH; the pure function needs neither, so stub `op`.
    import sys
    import types
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = types.SimpleNamespace(op=None)
    try:
        spec = importlib.util.spec_from_file_location("m088", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = saved
    rows = [
        (1, 10, "quote", [], 7),
        (2, 10, "quote", [1, 1, "1"], 7),         # duplicates collapse
        (3, 10, "quote", [2, 3, 99, None, "x"], 7),  # self, unknown, junk dropped
        (4, 10, "detailed", [1], 8),              # other plan: dropped
        (5, 11, "quote", [1], 9),                 # other change: dropped
        (6, 10, "detailed", None, 8),
        (7, 10, "detailed", [6], 8),
    ]
    out = mod.predecessor_links(rows)
    assert [(o["from_task_id"], o["to_task_id"], o["plan"]) for o in out] == [
        (1, 2, "quote"), (2, 3, "quote"), (6, 7, "detailed")]
    assert all(o["type"] == "FS" and o["lag_days"] == 0 for o in out)
    assert out[0]["created_by"] == 7 and out[0]["change_id"] == 10


# --- review round: summaries, performance, cascade --------------------------

def test_summary_links_do_not_explode():
    """300 blocks in 10 groups of nested summaries (group > sub > leaves),
    100 links between summaries of different groups: one edge per link, not
    one per pair of leaves (the old expansion made ~1.7M)."""
    import time
    from app.services.plan_engine import graph
    d = date(2026, 10, 5)
    tasks, groups = [], []
    for gi in range(10):
        gid = f"G{gi}"
        tasks.append(ETask(gid, d, 0, name=gid))
        subs = []
        for si in range(3):
            sid = f"{gid}.S{si}"
            tasks.append(ETask(sid, d, 0, parent_id=gid, name=sid))
            subs.append(sid)
            for li in range(8):
                tasks.append(ETask(f"{sid}.{li}", d, 1 + li % 3, parent_id=sid,
                                   name=f"{sid}.{li}"))
        groups.append([gid] + subs)
    assert len(tasks) == 280
    while len(tasks) < 300:
        tasks.append(ETask(f"X{len(tasks)}", d, 1, name="x"))
    links, k = [], 0
    for gi in range(10):
        for gj in range(gi + 1, 10):
            for a in groups[gi]:
                if k < 100:
                    links.append(ELink(a, groups[gj][k % 4], ("FS", "SS")[k % 2], k % 3))
                    k += 1
    assert len(links) == 100
    cal = Calendar("working", [1, 2, 3, 4, 5], ["2026-10-12"])
    t0 = time.perf_counter()
    res = schedule(tasks, links, cal)
    found = engine_issues(tasks, links, cal)
    took = time.perf_counter() - t0
    assert took < 0.2, took
    assert res.cycle is False and "cycle" not in {e["code"] for e in found["errors"]}
    assert len(graph(tasks, links).links) == 100
    # G0 -> G1 is FS: every block of group 1 starts after group 0 ends
    assert res.tasks["G1"].start >= res.tasks["G0"].end


def test_summary_rules_in_issues_and_math():
    cal = Calendar()
    d = date(2026, 10, 5)
    tasks = [ETask("A", d, 5, name="A"),
             ETask("S", d, 0, name="S", constraint_type="fnlt",
                   constraint_date=date(2026, 10, 6)),
             ETask("B", d, 2, parent_id="S", name="B"),
             ETask("C", date(2026, 10, 9), 2, parent_id="S", name="C")]
    # FF into a summary: an error and not scheduled
    found = engine_issues(tasks, [ELink("A", "S", "FF")], cal)
    assert [e["code"] for e in found["errors"]] == ["summary_finish_link"]
    assert schedule(tasks, [ELink("A", "S", "FF")], cal).tasks["B"].start == d
    # fnlt on a summary: checked once, against the rolled-up finish
    conflicts = [w for w in found["warnings"] if w["code"] == "constraint_conflict"]
    assert [(w["task_id"], w["message"]) for w in conflicts] == [
        ("S", "'S' ends after its finish-no-later-than date 2026-10-06")]
    # FS into a summary that one block breaks: reported once, on the summary
    found = engine_issues(tasks, [ELink("A", "S")], cal)
    viol = [e for e in found["errors"] if e["code"] == "dependency_violation"]
    assert [(e["task_id"], e["message"]) for e in viol] == [
        ("S", "'S' starts before 'A' ends")]
    # mso on a summary: an error, its blocks are not pinned
    pinned = [ETask("S", d, 0, name="S", constraint_type="mso",
                    constraint_date=date(2026, 10, 1)),
              ETask("B", d, 2, parent_id="S", name="B")]
    assert "summary_pin" in {e["code"] for e in engine_issues(pinned, [], cal)["errors"]}
    assert schedule(pinned, [], cal).tasks["B"].start == d


def test_cascade_moves_only_what_the_moved_block_drives():
    from app.services.plan_engine import cascade, downstream
    cal = Calendar()
    d = date(2026, 10, 5)
    # A -> B -> C, X -> Y (unrelated and already violating), P pinned after B
    tasks = [ETask("A", d, 8, name="A"), ETask("B", date(2026, 10, 10), 2, name="B"),
             ETask("C", date(2026, 10, 12), 1, name="C"),
             ETask("P", date(2026, 10, 12), 1, name="P", constraint_type="mso",
                   constraint_date=date(2026, 10, 12)),
             ETask("X", d, 5, name="X"), ETask("Y", d, 1, name="Y")]
    links = [ELink("A", "B"), ELink("B", "C"), ELink("B", "P"), ELink("X", "Y")]
    assert downstream(tasks, links, ["A"]) == {"B": "A", "C": "A", "P": "A"}
    res, cause = cascade(tasks, links, cal, ["A"])
    assert res.tasks["B"].start == date(2026, 10, 13)
    assert res.tasks["C"].start == date(2026, 10, 15)
    assert res.tasks["P"].start == date(2026, 10, 12)      # pinned: stays
    assert res.tasks["Y"].start == d                       # not driven by A
    assert cause == {"B": "A", "C": "A"}
    # a block whose work has started stays put; the walk goes on through it
    started = [ETask(t.id, t.start, t.duration, t.constraint_type,
                     t.constraint_date, name=t.name, started=(t.id == "B"))
               for t in tasks]
    res, cause = cascade(started, links, cal, ["A"])
    assert res.tasks["B"].start == date(2026, 10, 10)
    assert res.tasks["C"].start == date(2026, 10, 12)       # B did not move
    assert cause == {}
    started[2] = ETask("C", date(2026, 10, 11), 1, name="C")  # C now violates B
    res, cause = cascade(started, links, cal, ["A"])
    assert cause == {"C": "A"} and res.tasks["C"].start == date(2026, 10, 12)
    # through a summary: a link out of the summary drives what follows it
    tasks2 = [ETask("S", d, 0, name="S"), ETask("A", d, 3, parent_id="S", name="A"),
              ETask("Z", date(2026, 10, 8), 1, name="Z")]
    assert downstream(tasks2, [ELink("S", "Z")], ["A"]) == {"Z": "A"}


# --- review round: MSPDI robustness -------------------------------------------

def _mspdi(tasks_xml="", calendar_xml="", extra="", weekdays_extra=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Project xmlns="http://schemas.microsoft.com/project">'
        f'<MinutesPerDay>480</MinutesPerDay><DurationFormat>7</DurationFormat>{extra}'
        f'<CalendarUID>1</CalendarUID><Calendars><Calendar><UID>1</UID>'
        '<WeekDays>' + "".join(
            f'<WeekDay><DayType>{k}</DayType><DayWorking>{0 if k in (1, 7) else 1}'
            '</DayWorking></WeekDay>' for k in range(1, 8)) + weekdays_extra
        + '</WeekDays>'
        f'{calendar_xml}</Calendar></Calendars><Tasks>{tasks_xml}</Tasks></Project>'
    ).encode()


def _task_xml(uid, name, start="2026-10-05T08:00:00", dur="PT16H0M0S", level=1,
              extra=""):
    return (f"<Task><UID>{uid}</UID><Name>{name}</Name><Start>{start}</Start>"
            f"<Duration>{dur}</Duration><DurationFormat>7</DurationFormat>"
            f"<OutlineLevel>{level}</OutlineLevel>{extra}</Task>")


def test_mspdi_guard_uses_a_parser():
    doc = ('<?xml version="1.0" encoding="UTF-16"?>'
           '<!DOCTYPE Project [<!ENTITY x "boom">]><Project>&x;</Project>')
    # UTF-16 hides "<!DOCTYPE" from a byte search; whitespace splits it
    for raw in (doc.encode("utf-16"),
                b'<?xml version="1.0"?>\n<!DOCTYPE\n  Project SYSTEM "x.dtd"><Project/>'):
        with pytest.raises(MspdiError, match="DTD"):
            parse_mspdi(raw)
    # a clean UTF-16 file parses
    ok = _mspdi(_task_xml(1, "A")).decode().replace('encoding="UTF-8"', 'encoding="UTF-16"')
    assert parse_mspdi(ok.encode("utf-16"))["tasks"][0]["name"] == "A"


def test_mspdi_recurring_exceptions():
    def ex(typ, a, b, name="X", **kw):
        more = "".join(f"<{k}>{v}</{k}>" for k, v in kw.items())
        return (f"<Exception><Name>{name}</Name><Type>{typ}</Type><DayWorking>0"
                f"</DayWorking><TimePeriod><FromDate>{a}T00:00:00</FromDate>"
                f"<ToDate>{b}T23:59:00</ToDate></TimePeriod>{more}</Exception>")
    cal_xml = "<Exceptions>" + "".join((
        ex(1, "2026-12-24", "2026-12-26", "Christmas"),               # a range
        ex(2, "2026-01-01", "2028-12-31", "New year", Month=0, MonthDay=1),
        # first Monday of May every year
        ex(3, "2026-01-01", "2027-12-31", "May", Month=4, MonthPosition=0,
           MonthItem=4),
        # last Friday of every 6th month from Jan 2026
        ex(5, "2026-01-01", "2026-12-31", "Inventory", Period=6, MonthPosition=4,
           MonthItem=8),
        # 15th of every month, 3 occurrences
        ex(4, "2026-01-01", "2026-12-31", "Mid", MonthDay=15, Occurrences=3,
           EnteredByOccurrences=1),
        # Wednesdays every second week, 2 weeks
        ex(6, "2026-03-01", "2026-03-14", "Wed", DaysOfWeek=8, Period=2),
        ex(99, "2026-01-01", "2026-12-31", "Odd"),
    )) + "</Exceptions>"
    out = parse_mspdi(_mspdi(_task_xml(1, "A"), cal_xml))
    hol = {h.isoformat() for h in out["calendar"].holidays}
    assert {"2026-12-24", "2026-12-25", "2026-12-26"} <= hol
    assert {"2026-01-01", "2027-01-01", "2028-01-01"} <= hol
    assert "2027-06-01" not in hol
    assert {"2026-05-04", "2027-05-03"} <= hol                       # first Mondays
    assert {"2026-01-30", "2026-07-31"} <= hol and "2026-04-24" not in hol
    assert {"2026-01-15", "2026-02-15", "2026-03-15"} <= hol and "2026-04-15" not in hol
    assert "2026-03-04" in hol and "2026-03-11" not in hol
    assert len(hol) == 3 + 3 + 2 + 2 + 3 + 1
    assert out["warnings"] == [
        "Calendar exception 'Odd' has an unknown recurrence type 99 and was skipped"]


def test_mspdi_bounds_and_malformed_numbers():
    big = "9" * 400
    cases = [
        _mspdi(_task_xml(1, "A", dur=f"PT{big}H0M0S")),              # inf hours
        _mspdi(_task_xml(1, "A", dur="PT99999999H0M0S")),            # absurd
        _mspdi(_task_xml(1, "A", start="1066-10-14T08:00:00")),
        _mspdi(_task_xml(1, "A") + _task_xml(2, "B", extra=(
            "<PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type>"
            "<LinkLag>999999999999</LinkLag><LagFormat>7</LagFormat>"
            "</PredecessorLink>"))),
        _mspdi(_task_xml(1, "A", start="2026-13-45T08:00:00")),
    ]
    for raw in cases:
        with pytest.raises(MspdiError):
            parse_mspdi(raw)
    # a DayType 0 exception spanning centuries is capped and clipped
    cal = ("<WeekDay><DayType>0</DayType><DayWorking>0</DayWorking>"
           "<TimePeriod><FromDate>0001-01-01T00:00:00</FromDate>"
           "<ToDate>9999-12-31T00:00:00</ToDate></TimePeriod></WeekDay>")
    out = parse_mspdi(_mspdi(_task_xml(1, "A"), weekdays_extra=cal))
    assert len(out["calendar"].holidays) == 5000
    assert min(out["calendar"].holidays) == date(1900, 1, 1)


def test_mspdi_outline_and_summary_rules():
    deep = "".join(_task_xml(i, f"L{i}", level=i) for i in range(1, 53))
    with pytest.raises(MspdiError, match="outline levels"):
        parse_mspdi(_mspdi(deep))
    pin = (_task_xml(1, "Phase", extra="<ConstraintType>2</ConstraintType>"
                     "<ConstraintDate>2026-10-05T08:00:00</ConstraintDate>")
           + _task_xml(2, "A", level=2))
    with pytest.raises(MspdiError, match="summary"):
        parse_mspdi(_mspdi(pin))
    ff = (_task_xml(1, "X") + _task_xml(2, "Phase", extra=(
        "<PredecessorLink><PredecessorUID>1</PredecessorUID><Type>0</Type>"
        "</PredecessorLink>")) + _task_xml(3, "A", level=2))
    with pytest.raises(MspdiError, match="summary"):
        parse_mspdi(_mspdi(ff))
    # snet / fnlt on a summary are MS Project's and survive a round trip
    cal = Calendar("working")
    d = date(2026, 10, 5)
    rows = [{"key": 1, "name": "Phase", "start": d, "duration": 3,
             "end": cal.end_date(d, 3), "level": 1, "outline": "1", "summary": True,
             "constraint_type": "fnlt", "constraint_date": date(2026, 10, 20)},
            {"key": 2, "name": "A", "start": d, "duration": 3,
             "end": cal.end_date(d, 3), "level": 2, "outline": "1.1"}]
    back = parse_mspdi(build_mspdi(name="x", title="x", cal=cal, tasks=rows, links=[]))
    t = {r["name"]: r for r in back["tasks"]}
    assert (t["Phase"]["constraint_type"], t["Phase"]["constraint_date"]) == \
        ("fnlt", date(2026, 10, 20))


def test_mspdi_import_details():
    today = date.today()
    past = (today - timedelta(days=10)).isoformat()
    future = (today + timedelta(days=30)).isoformat()
    tasks = (
        _task_xml(1, "Go", start="2026-10-09T17:00:00", dur="PT0H0M0S",
                  extra="<Milestone>1</Milestone>")
        + _task_xml(2, "Work", extra=(
            "<PercentComplete>40</PercentComplete>"
            f"<ActualStart>{past}T08:00:00</ActualStart>"
            f"<ActualFinish>{future}T17:00:00</ActualFinish>"
            "<Baseline><Number>1</Number><Start>2026-01-01T08:00:00</Start>"
            "<Finish>2026-01-02T17:00:00</Finish></Baseline>"
            "<Baseline><Number>0</Number><Start>2026-10-05T08:00:00</Start>"
            "<Finish>2026-10-06T17:00:00</Finish></Baseline>"
            # an elapsed lag of 7 days in a working-day file is 5 working days
            "<PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type>"
            "<LinkLag>100800</LinkLag><LagFormat>8</LagFormat></PredecessorLink>"
            "<PredecessorLink><PredecessorUID>7</PredecessorUID><Type>1</Type>"
            "<CrossProject>1</CrossProject><CrossProjectName>other.mpp"
            "</CrossProjectName></PredecessorLink>")))
    out = parse_mspdi(_mspdi(tasks))
    t = {r["name"]: r for r in out["tasks"]}
    # a milestone at 17:00 on Friday is the end of that day: the next day
    assert t["Go"]["start"] == date(2026, 10, 10)
    w = t["Work"]
    assert w["progress"] == 40 and w["actual_start"] == date.fromisoformat(past)
    assert w["actual_finish"] is None
    assert (w["baseline_start"], w["baseline_finish"]) == (date(2026, 10, 5),
                                                            date(2026, 10, 7))
    assert [(lk["type"], lk["lag"]) for lk in out["links"]] == [("FS", 5)]
    assert any("another project" in x for x in out["warnings"])
    assert any("ActualFinish" in x and "future" in x for x in out["warnings"])


def test_mspdi_calendar_mode_holidays_do_not_block_ms_project():
    from xml.etree import ElementTree as ET
    ns = "{http://schemas.microsoft.com/project}"
    cal = Calendar("calendar", [1, 2, 3, 4, 5], ["2026-10-12"])
    root = ET.fromstring(build_mspdi(name="x", title="x", cal=cal,
                                     tasks=_sample_rows(cal), links=[]))
    ex = root.find(f".//{ns}Exception")
    assert ex.find(f"{ns}DayWorking").text == "1"           # MS Project works through it
    assert parse_mspdi(ET.tostring(root))["calendar"].holidays == [date(2026, 10, 12)]
    work = Calendar("working", [1, 2, 3, 4, 5], ["2026-10-12"])
    root = ET.fromstring(build_mspdi(name="x", title="x", cal=work,
                                     tasks=_sample_rows(work), links=[]))
    assert root.find(f".//{ns}Exception/{ns}DayWorking").text == "0"


def _real_alembic():
    """The alembic package, not backend/alembic (the scripts folder that
    shadows it on this PYTHONPATH)."""
    import sys
    backend = str(Path(__file__).parent.parent.resolve())
    saved_path = list(sys.path)
    saved_mods = {k: v for k, v in sys.modules.items()
                  if k == "alembic" or k.startswith("alembic.")}
    for k in saved_mods:
        del sys.modules[k]
    sys.path[:] = [p for p in sys.path
                   if p not in ("", ".") and Path(p or ".").resolve() != Path(backend)]
    try:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        return MigrationContext, Operations
    finally:
        sys.path[:] = saved_path


def _load_088():
    import sys
    import types
    path = (Path(__file__).parent.parent / "alembic" / "versions"
            / "088_plan_links_calendar.py")
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = types.SimpleNamespace(op=None)
    try:
        spec = importlib.util.spec_from_file_location("m088", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = saved
    return mod


def test_migration_088_up_and_down_on_sqlite():
    import sqlalchemy as sa
    MigrationContext, Operations = _real_alembic()
    mod = _load_088()
    eng_ = sa.create_engine("sqlite://")
    md = sa.MetaData()
    sa.Table("users", md, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("change_requests", md, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("plan_calendar", sa.JSON))
    sa.Table("change_plan_tasks", md, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("change_id", sa.Integer), sa.Column("plan", sa.String(10)),
             sa.Column("predecessors", sa.JSON), sa.Column("created_by", sa.Integer),
             # create_all: an UNNAMED self foreign key
             sa.Column("parent_id", sa.Integer, sa.ForeignKey("change_plan_tasks.id")),
             sa.Column("constraint_type", sa.String(4)),
             sa.Column("constraint_date", sa.Date),
             sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime))
    sa.Table("change_plan_deviations", md,
             sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("created_at", sa.DateTime))
    sa.Table("change_plan_links", md, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("change_id", sa.Integer), sa.Column("plan", sa.String(10)),
             sa.Column("from_task_id", sa.Integer), sa.Column("to_task_id", sa.Integer),
             sa.Column("type", sa.String(2)), sa.Column("lag_days", sa.Integer),
             sa.Column("created_by", sa.Integer), sa.Column("created_at", sa.DateTime),
             sa.Index("ix_change_plan_links_change_id", "change_id"))
    md.create_all(eng_)
    with eng_.begin() as c:
        c.execute(sa.text(
            "insert into change_plan_tasks(id, change_id, plan, predecessors, "
            "created_by) values (1, 1, 'quote', '[]', 1), (2, 1, 'quote', '[1]', 1),"
            " (3, 1, 'quote', '[2, 1]', 1)"))
        c.execute(sa.text(
            "insert into change_plan_links(change_id, plan, from_task_id, to_task_id,"
            " type, lag_days, created_at) values (1, 'quote', 1, 2, 'FS', 0, "
            "'2026-01-01'), (1, 'quote', 3, 1, 'SS', 2, '2026-01-01')"))
        mod.op = Operations(MigrationContext.configure(c))
        mod.upgrade()           # the table existed: still converts
        pairs = c.execute(sa.text(
            "select from_task_id, to_task_id, type from change_plan_links "
            "order by id")).all()
        # 1->2 existed, 1->3 is linked the other way already: only 2->3 is new
        assert [tuple(p) for p in pairs] == [(1, 2, "FS"), (3, 1, "SS"), (2, 3, "FS")]
        preds = c.execute(sa.text(
            "select predecessors from change_plan_tasks order by id")).scalars().all()
        assert preds == ["[]", "[]", "[]"]
        cols = {x["name"] for x in sa.inspect(c).get_columns("change_plan_deviations")}
        assert "caused_by_task_id" in cols
        mod.upgrade()           # a second run changes nothing
        assert c.execute(sa.text("select count(*) from change_plan_links")).scalar() == 3
        mod.downgrade()         # the unnamed FK does not stop it
        preds = c.execute(sa.text(
            "select id, predecessors from change_plan_tasks order by id")).all()
        assert [tuple(p) for p in preds] == [(1, "[]"), (2, "[1]"), (3, "[2]")]
        cols = {x["name"] for x in sa.inspect(c).get_columns("change_plan_tasks")}
        assert "parent_id" not in cols
        assert "change_plan_links" not in sa.inspect(c).get_table_names()
        mod.upgrade()           # and back, now with a named FK
        mod.downgrade()


def test_mspdi_calendar_choice_and_base_chain():
    wd = lambda k, on: (f"<WeekDay><DayType>{k}</DayType><DayWorking>{on}"
                        "</DayWorking></WeekDay>")
    hol = lambda d: ("<Exceptions><Exception><Name>H</Name><Type>1</Type>"
                     "<DayWorking>0</DayWorking><TimePeriod>"
                     f"<FromDate>{d}T00:00:00</FromDate><ToDate>{d}T23:59:00"
                     "</ToDate></TimePeriod></Exception></Exceptions>")
    cals = (
        # 1: a resource calendar (the project wrongly points at it): never used
        "<Calendar><UID>1</UID><IsBaseCalendar>0</IsBaseCalendar>"
        "<BaseCalendarUID>3</BaseCalendarUID><WeekDays>"
        + "".join(wd(k, 1) for k in range(1, 8)) + "</WeekDays></Calendar>"
        # 2: derived: Saturday works, Friday off, one holiday
        "<Calendar><UID>2</UID><IsBaseCalendar>1</IsBaseCalendar>"
        "<BaseCalendarUID>3</BaseCalendarUID><WeekDays>" + wd(7, 1) + wd(6, 0)
        + "</WeekDays>" + hol("2026-10-07") + "</Calendar>"
        # 3: its base: Mon-Fri, Sunday off, one holiday
        "<Calendar><UID>3</UID><IsBaseCalendar>1</IsBaseCalendar><WeekDays>"
        + "".join(wd(k, 0 if k in (1, 7) else 1) for k in range(1, 8))
        + "</WeekDays>" + hol("2026-12-25") + "</Calendar>")
    xml = ('<?xml version="1.0"?><Project xmlns="http://schemas.microsoft.com/'
           'project"><DurationFormat>7</DurationFormat><CalendarUID>1'
           f'</CalendarUID><Calendars>{cals}</Calendars>'
           f'<Resources><Resource><UID>1</UID><Name>R</Name><CalendarUID>1'
           '</CalendarUID></Resource></Resources><Tasks>'
           + _task_xml(1, "A") + '</Tasks></Project>').encode()
    cal = parse_mspdi(xml)["calendar"]
    # UID 1 is a resource calendar: the first base calendar (2) is taken,
    # Mon-Thu from its base, Friday off and Saturday on from itself
    assert cal.workdays == [1, 2, 3, 4, 6]
    assert cal.holidays == [date(2026, 10, 7), date(2026, 12, 25)]
    # a calendar listing no weekdays at all: Mon-Fri
    bare = xml.replace(b"<CalendarUID>1</CalendarUID></Resource>",
                       b"</Resource>").replace(
        cals.encode(), b"<Calendar><UID>9</UID><IsBaseCalendar>1</IsBaseCalendar>"
                       b"</Calendar>").replace(b"<CalendarUID>1</CalendarUID>",
                                               b"<CalendarUID>9</CalendarUID>")
    assert parse_mspdi(bare)["calendar"].workdays == [1, 2, 3, 4, 5]


def test_migration_089_dedupes_and_indexes():
    import sys
    import types
    import sqlalchemy as sa
    MigrationContext, Operations = _real_alembic()
    path = (Path(__file__).parent.parent / "alembic" / "versions"
            / "089_plan_link_pair_unique.py")
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = types.SimpleNamespace(op=None)
    try:
        spec = importlib.util.spec_from_file_location("m089", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = saved
    assert mod.duplicate_ids([(5, 1, "q", 1, 2), (3, 1, "q", 1, 2), (4, 1, "q", 2, 1),
                              (7, 1, "d", 1, 2), (9, 1, "q", 1, 2)]) == [5, 9]
    eng_ = sa.create_engine("sqlite://")
    md = sa.MetaData()
    sa.Table("change_plan_links", md, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("change_id", sa.Integer), sa.Column("plan", sa.String(10)),
             sa.Column("from_task_id", sa.Integer), sa.Column("to_task_id", sa.Integer))
    md.create_all(eng_)
    with eng_.begin() as c:
        c.execute(sa.text("insert into change_plan_links values (1, 1, 'q', 1, 2), "
                          "(2, 1, 'q', 1, 2), (3, 1, 'q', 2, 3)"))
        mod.op = Operations(MigrationContext.configure(c))
        mod.upgrade()
        mod.upgrade()                       # idempotent
        assert c.execute(sa.text("select id from change_plan_links order by id")
                         ).scalars().all() == [1, 3]
        with pytest.raises(sa.exc.IntegrityError):
            c.execute(sa.text("insert into change_plan_links values (4, 1, 'q', 1, 2)"))
    with eng_.begin() as c:
        mod.op = Operations(MigrationContext.configure(c))
        mod.downgrade()
        c.execute(sa.text("insert into change_plan_links values (4, 1, 'q', 1, 2)"))


def test_summary_progress_rounds_half_up_and_weights_nested_spans():
    cal = Calendar()
    d = date(2026, 10, 5)
    # 1 day at 25% + 1 day at 100% = 62.5 -> 63 (round() would give 62)
    two = [ETask("S", d, 0), ETask("A", d, 1, parent_id="S", progress=25),
           ETask("B", d, 1, parent_id="S", progress=100)]
    assert analyse(two, [], cal).tasks["S"].progress == 63
    # 0.5 -> 1, not 0
    half = [ETask("S", d, 0), ETask("A", d, 1, parent_id="S", progress=1),
            ETask("B", d, 1, parent_id="S", progress=0)]
    assert analyse(half, [], cal).tasks["S"].progress == 1
    # a nested summary weighs its rolled-up span (6 days: 2 + gap + 2), not
    # the sum of its blocks' durations (4)
    nested = [ETask("T", d, 0), ETask("S", d, 0, parent_id="T"),
              ETask("A", d, 2, parent_id="S", progress=100),
              ETask("B", d + timedelta(days=4), 2, parent_id="S", progress=100),
              ETask("C", d, 2, parent_id="T", progress=0)]
    assert analyse(nested, [], cal).tasks["T"].progress == 75    # 6*100/(6+2)
