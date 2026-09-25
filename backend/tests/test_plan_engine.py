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


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vectors(case):
    cal, tasks, links = _load(case)
    res = schedule(tasks, links, cal,
                   pull=bool((case.get("options") or {}).get("pull")))
    assert not res.cycle
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
