"""Set the planned press (tool_machine) on the Brose tools from the RFQ2 Tool
Layout Designer picks: project 1994 from RFQ 26 loop 37, project 2277 from
RFQ 25 loop 36 (selected variant, tool_size_estimations.tool_layout_json
machine_pick / machine_picks). One changelog entry per changed tool. Dry run
by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/set_brose_tool_machines.py [--apply]

Picks read from RFQ2 prod on 2026-09-29: of the presses RFQ2 picked
(machine_picks, else the single machine_pick, as ToolCardV2 reads them) the
one of the smallest machine class (clamping force), on a tie the lowest
machine number. One press per tool. RFQ2 names a press
"KM 350-1", a dash, "KM KM 350/2000 CX" (machine, manufacturer, model); stored here as
"KM 350-1 (KM 350/2000 CX)", with " (no fit)" where the layout says the tool
does not fit that press.
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.part_service import ChangelogService

# (project code, tool part_number) -> smallest-class press RFQ2 picked; RFQ2 tooling_calc id and the picks in the comment
MACHINES = {
    ("1994", "199401"): "KM 550-1 (KM 550/2000/750 GX)",  # 204 Handle, height adjustment LH/RH; of KM 550-1
    ("1994", "199402"): "KM 200-1 (KM 200/750 CX)",  # 205 Latch cover 40/60; single pick
    ("1994", "199403"): "KM 200-1 (KM 200/750 CX)",  # 206 Isofix cover; of KM 550-1, KM 200-1
    ("1994", "199404"): "KM 80-1 (KM 80/380 CX)",  # 207 A-bracket inner trim; of KM 80-1, KM 350-1
    ("1994", "199405"): "KM 200-1 (KM 200/750 CX)",  # 208 Cover trim, center back; of KM 200-1
    ("1994", "199406"): "KM 200-1 (KM 200/750 CX)",  # 209 Center bearing cover; of KM 200-1
    ("1994", "199407"): "KM 80-1 (KM 80/380 CX)",  # 210 Belt exit cover; of KM 80-1, KM 200-1
    ("1994", "199408"): "KM 350-1 (KM 350/2000 CX)",  # 211 Inner side shield; of KM 350-3, KM 350-1
    ("1994", "199409"): "KM 550-2 (KM 550/2000/750 GX)",  # 212 Decor cover; of KM 550-2
    ("1994", "199410"): "KM 200-1 (KM 200/750 CX)",  # 213 A-bracket outer trim; of KM 200-1, KM 200-2
    ("2277", "227701"): "KM 1300-1 (KM 1300/8100/750 MXL)",  # 202 Seat back panel MIC; of KM 2300-1, KM 1300-1
    ("2277", "227702"): "EN 3200-1 (Engel DUO 17060/3500 TECH US)",  # 203 Seat back panel DS/PS; of EN 3200-1
    ("2277", "227703"): "KM 900-1 (KM 900/4300 GX)",  # 200 Map pocket; of KM 900-1, KM 900-2
    ("2277", "227704"): "KM 80-1 (KM 80/380 CX)",  # 201 Pivot axis (G05); of KM 80-3, KM 80-2, KM 80-1
    ("2277", "227705"): "KM 80-1 (KM 80/380 CX) (no fit)",  # 199 Rossette (G07); of KM 80-1/-2/-3, none fit
}
REASON = "Smallest-class press picked in the RFQ2 Tool Layout Designer (RFQ 26 loop 37 / RFQ 25 loop 36), set 2026-09-29"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        codes = sorted({code for code, _ in MACHINES})
        projects = {p.code: p.id for p in (await s.execute(
            select(Project).where(Project.code.in_(codes)))).scalars().all()}
        tools = (await s.execute(select(Part).where(
            Part.project_id.in_(list(projects.values())), Part.item_category == "tool"))).scalars().all()
        code_of = {pid: code for code, pid in projects.items()}
        by_key = {(code_of[t.project_id], t.part_number): t for t in tools}

        changes = []
        for key, machine in MACHINES.items():
            tool = by_key.get(key)
            if tool is None:
                print(f"   ! tool {key[1]} not in project {key[0]}")
                continue
            if tool.tool_machine != machine:
                changes.append((tool, tool.tool_machine, machine))

        print(f"== TOOL MACHINES ({len(changes)} changes)")
        for tool, old, new in changes:
            print(f"   {tool.part_number:<8} {old!r} -> {new!r}")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return

        for tool, old, new in changes:
            tool.tool_machine = new
            await ChangelogService.log_action(
                s, part_id=tool.id, action="metadata_updated",
                action_description=f"Machine {old!r} -> {new!r}. {REASON}",
                performed_by=args.user, field_name="tool_machine",
                old_value=old, new_value=new)
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
