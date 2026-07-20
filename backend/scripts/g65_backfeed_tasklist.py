"""Generate the department backfeed tasklist for backfilled changes — SP-D.

The G65 part-history sheets carry only a thin slice of what the PLM change
model wants (occasion, customer level, EC number, internal level, drawing
index, agreed-by). Everything else — assessments, cost lines, affected
sub-components, gate decisions, PPAP, quoted price — is missing on the
backfilled `closed` changes. This script queries those changes and emits a
per-department markdown worklist: "for these N backfilled changes, please
fill in X."

Data-driven and re-runnable: it reads whatever changes carry the backfill
issuer, so it also covers VW426 once those sheets are backfilled.

Run in the PLM backend container:
    docker exec -e PYTHONPATH=/app claude-plm2-backend-1 \
        python /app/scripts/g65_backfeed_tasklist.py --out /tmp/backfeed-tasklist.md
"""
import argparse
import asyncio
import os
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.change import ChangeRequest, ChangeImpactedItem
from app.models.entities import Project
from app.models.part import Part

ISSUER = "Part History Sheet (backfill)"

# What each PLM department must backfeed onto the historical changes, and why
# the sheet couldn't supply it. Ordered as it should read.
DEPARTMENT_TASKS = [
    ("R&D / Developer", [
        "Affected sub-components and tools per change — the sheets list only the top ZSB assembly, not which molded parts, clips, or tools actually changed.",
        "Geometry-change flag + 3D evidence (no_geometry_change) for each change.",
        "Resulting part revision per change (link the ECN revision the change produced).",
        "Full change description and root cause — sheets give only a one-line occasion (First Part / VS0 / VS1 / R@R).",
    ]),
    ("Tool Engineer / Tool design", [
        "Tool(s) modified for each change and the nature of the tool work — the tool (33xx) is implied by the assembly number but not linked as an impacted item.",
    ]),
    ("Quality / APQP", [
        "Feasibility verdict per change (the change never ran an assessment).",
        "Dimensional / laboratory / function evaluation results — the sheet's Evaluation-Suppl. columns (Dimensional/Laboratory/Function/Total) are blank.",
        "PPAP submission and level per change.",
        "Quality sign-off.",
    ]),
    ("Project Manager", [
        "Timing milestone / required-by date.",
        "Gate decisions (feasibility, budget, release) — none were recorded pre-PLM.",
        "PM sign-off; whether the change was a series or single change.",
    ]),
    ("Sales", [
        "Actual customer response — backfill defaulted every change to 'accepted'; confirm or correct.",
        "Quoted price to the customer.",
        "Confirm the customer EC number and customer level captured from the sheet.",
    ]),
    ("Manufacturing Engineer / IE / Production", [
        "Process / implementation impact and implementation mode.",
        "Production routing and run-at-rate confirmation (the 'R@R' rows).",
    ]),
    ("Costing (via each assessing department)", [
        "Cost impact per assessing department (estimated cost) and internal cost approval — no cost data exists on the sheets.",
    ]),
    ("Purchasing", [
        "Purchased-component impact (clips / fasteners, 50-series) and supplier PPAP / confirmation.",
    ]),
    ("Logistics", [
        "Packaging impact — returnable packaging appears in the BOM but is not tied to these changes.",
    ]),
]

_FIELD = lambda desc, label: (re.search(rf"{label}:\s*(.*)", desc) or [None, None])[1]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--project-code", help="limit to one project (e.g. 1748=G65, "
                    "1864=VW426); default: all backfilled programs")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        proj_filter = None
        program = "All backfilled programs"
        if args.project_code:
            proj_filter = (await s.execute(
                select(Project).where(Project.code == args.project_code))).scalar_one()
            program = f"{proj_filter.name} (project {proj_filter.code})"
        stmt = select(ChangeRequest).where(ChangeRequest.issuer == ISSUER)
        if proj_filter is not None:
            stmt = stmt.where(ChangeRequest.project_id == proj_filter.id)
        changes = (await s.execute(
            stmt.order_by(ChangeRequest.change_number))).scalars().all()
        # affected part number per change
        impacted = defaultdict(list)
        for ii, pn in (await s.execute(
                select(ChangeImpactedItem, Part.part_number)
                .join(Part, Part.id == ChangeImpactedItem.part_id))).all():
            impacted[ii.change_id].append(pn)
        proj_code = {p.id: p.code for p in (await s.execute(select(Project))).scalars()}
    await engine.dispose()

    # group by affected assembly for the summary
    by_assembly = defaultdict(list)
    for c in changes:
        key = (impacted.get(c.id) or ["(unlinked)"])[0]
        by_assembly[key].append(c)

    lines = []
    w = lines.append
    w(f"# {program} — department backfeed tasklist\n")
    w(f"**{len(changes)} auto-created `closed` changes** were backfilled from the "
      f"{program} part-history sheets. They were implemented before PLM "
      "existed, so they carry only what the sheets recorded. Each department below owns "
      "filling the gaps so these historical changes become complete PLM records.\n")

    w("## Scope\n")
    w("| Affected assembly | Change numbers | Count |")
    w("|---|---|---|")
    for key in sorted(by_assembly):
        cs = by_assembly[key]
        rng = f"{cs[0].change_number} … {cs[-1].change_number}" if len(cs) > 1 else cs[0].change_number
        w(f"| {key} | {rng} | {len(cs)} |")
    w("")

    w("## Per-department worklist\n")
    for dept, tasks in DEPARTMENT_TASKS:
        w(f"### {dept}\n")
        w(f"For all {len(changes)} backfilled changes:\n")
        for t in tasks:
            w(f"- [ ] {t}")
        w("")

    w("## Appendix — what each sheet row already provides\n")
    w("| Change | Affects | Occasion / Process | Drawing idx | EC / sample status |")
    w("|---|---|---|---|---|")
    for c in changes:
        d = c.description or ""
        occ = _FIELD(d, "Occasion/Process") or (
            c.title.split("—", 1)[-1].strip() if "—" in c.title else "—")
        drawing = _FIELD(d, "Drawing Index") or _FIELD(d, "Drawing index/level") or "—"
        extra = (_FIELD(d, "EC Number") or _FIELD(d, "Sample status") or "—")
        row = [c.change_number, (impacted.get(c.id) or ["—"])[0],
               occ, drawing, extra]
        w("| " + " | ".join(str(x).replace("|", "/") for x in row) + " |")
    w("")

    with open(args.out, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {args.out} ({len(changes)} changes, {len(DEPARTMENT_TASKS)} departments)")


if __name__ == "__main__":
    asyncio.run(main())
