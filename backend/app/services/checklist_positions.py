"""Christoph 2026-11-08: what a department said Yes to in its assessment is
carried into its costing, so nobody types it twice.

An Internal or External modification row can hold several cases ("re-cut
insert LH", "new ejector plate"); each case becomes its own costing line when
the assessment is submitted: an external case a supplier money line (estimate,
1 job, price still to fill in), an internal case an own-time line (hours still
to fill in). Re-submitting adds only new cases; a line the department deleted
or reworded is not brought back under the same wording, and nothing is ever
removed here.
"""
from sqlalchemy import select

from app.models.change_cost import CostingPosition
from app.services import assessment_checklist as checklist

# checklist key -> costing position kind
CASE_KEYS = {"modification_external": "external", "modification_internal": "own_time"}
# Christoph 2026-11-08: every other Yes row is a costing line too (spare
# part = bought from a supplier; the rest is own work). Not a cost line: the
# timing risk (a risk), the cycle time (the per-plant grid, min per part).
ROW_EXTERNAL = {"sparepart_required"}
ROW_SKIP = {"timing_risk", "cycle_time_change"} | set(CASE_KEYS)
NOTE_PREFIX = "From the assessment: "


def cases_of(entry: dict) -> list[str]:
    """The case texts of a Yes row: its case list, else its remark."""
    out = [c["text"] for c in checklist.case_list(entry)]
    if out:
        return out
    remark = (entry.get("remark") or "").strip()
    return [remark] if remark else []


async def carry_cases(session, change, assessment, dept_name, user_id: int) -> int:
    details = assessment.details_dict
    yes = [e for e in (details.get("impacts") or [])
           if isinstance(e, dict) and e.get("key")
           and (e.get("answer") == "yes" if e.get("answer") is not None
                else bool(e.get("impacted")))]
    rows = [e for e in yes if e["key"] in CASE_KEYS]
    others = [e for e in yes if e["key"] not in ROW_SKIP]
    if not rows and not others:
        return 0
    have = {(k, (lbl or "").strip().lower()) for k, lbl in (await session.execute(
        select(CostingPosition.kind, CostingPosition.label).where(
            CostingPosition.change_id == change.id,
            CostingPosition.department_id == assessment.department_id))).all()}
    carried = set(details.get("carried_cases") or [])
    from app.services import costing_rates
    added = 0
    for e in rows:
        kind = CASE_KEYS[e["key"]]
        row_label = checklist.label_for(e["key"], dept_name) or e["key"]
        for case in cases_of(e):
            label = case[:200]
            mark = f"{e['key']}|{label.lower()}"
            # once carried, never again (a deleted line stays deleted)
            if mark in carried or (kind, label.lower()) in have:
                carried.add(mark)
                continue
            p = CostingPosition(
                change_id=change.id, department_id=assessment.department_id,
                label=label, kind=kind, pricing="estimate",
                notes=f"{NOTE_PREFIX}{row_label}", created_by=user_id,
                **({"quantity": 1.0, "quantity_unit": "job"} if kind == "external" else {}),
                lead_time_unit="calendar_days")
            session.add(p)
            await session.flush()
            await costing_rates.snapshot_position(session, change, p)
            carried.add(mark)
            added += 1
    for e in others:
        kind = "external" if e["key"] in ROW_EXTERNAL else "own_time"
        label = (checklist.label_for(e["key"], dept_name) or e["key"])[:200]
        mark = f"{e['key']}|row"
        if mark in carried or (kind, label.lower()) in have:
            carried.add(mark)
            continue
        remark = (e.get("remark") or "").strip()
        p = CostingPosition(
            change_id=change.id, department_id=assessment.department_id,
            label=label, kind=kind, pricing="estimate",
            notes=f"{NOTE_PREFIX}{remark or label}"[:1000], created_by=user_id,
            **({"quantity": 1.0, "quantity_unit": "job"} if kind == "external" else {}),
            lead_time_unit="calendar_days")
        session.add(p)
        await session.flush()
        await costing_rates.snapshot_position(session, change, p)
        carried.add(mark)
        added += 1
    details["carried_cases"] = sorted(carried)
    import json
    assessment.details = json.dumps(details)
    await session.flush()
    return added
