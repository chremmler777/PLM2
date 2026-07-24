"""Import the gauge inventory (FM-QUA-0094-17) as 'gauge' parts.

Dry run by default — prints the full plan and writes nothing:
    python import_gauges.py "/path/to/FM-QUA-0094-17 Gauge Inventory.xlsx"

Commit it:
    python import_gauges.py "/path/to/...xlsx" --write

Idempotent: a gauge already recorded for the same (owner tool, legacy no) is
skipped, so re-running adds nothing. Never creates a tool part — rows naming an
unknown tool are reported and skipped.
"""
import asyncio
import sys

import openpyxl
from sqlalchemy import select

from app.models.database import AsyncSessionLocal
from app.models.part import Part, PartRelation
from app.services.gauge_import import GaugeRow, plan_import

CREATED_BY = 3  # chris
HEADER_ROWS = 2  # title row + column headers; data starts on row 3


def read_rows(path: str) -> list[GaugeRow]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Sheet1"]
    rows: list[GaugeRow] = []
    for raw in ws.iter_rows(min_row=HEADER_ROWS + 1, values_only=True):
        customer, tool_ref, desc, legacy, area, row_, bay, shelf = (raw + (None,) * 8)[:8]
        if not tool_ref:
            continue
        storage = " / ".join(str(x).strip() for x in (area, row_, bay, shelf) if x)
        rows.append(GaugeRow(
            customer=str(customer or "").strip(),
            tool_ref=str(tool_ref).strip(),
            description=str(desc or "").strip(),
            legacy_no=str(legacy or "").strip(),
            storage=storage,
        ))
    return rows


async def main(path: str, write: bool) -> None:
    rows = read_rows(path)
    print(f"Read {len(rows)} data rows from {path}")

    async with AsyncSessionLocal() as s:
        tool_rows = (await s.execute(
            select(Part.part_number, Part.id, Part.project_id).where(
                Part.item_category == "tool"))).all()
        known_tools = {r.part_number for r in tool_rows}
        tool_by_number = {r.part_number: r for r in tool_rows}

        # Existing gauges keyed by (owner tool, legacy no), recovered from the
        # notes text this importer writes.
        existing: set[tuple[str, str]] = set()
        for pn, notes in (await s.execute(
                select(Part.part_number, Part.description).where(
                    Part.item_category == "gauge"))).all():
            owner = pn.rpartition("-")[0] or pn
            if notes and "Legacy gauge no: " in notes:
                legacy = notes.split("Legacy gauge no: ", 1)[1].split(".", 1)[0].strip()
                existing.add((owner, legacy))

        plan, report = plan_import(rows, known_tools, existing)

        print(f"\n--- report ({len(report)} lines) ---")
        for line in report:
            print(" ", line)
        print(f"\n--- plan ({len(plan)} gauges) ---")
        for p in plan:
            print(f"  {p.part_number:12} serves {','.join(p.serves):12} {p.name}")

        if not write:
            print("\nDRY RUN — nothing written. Re-run with --write to commit.")
            return

        for p in plan:
            owner = tool_by_number[p.owner_tool]
            gauge = Part(project_id=owner.project_id, part_number=p.part_number,
                         name=p.name or p.part_number, description=p.notes,
                         part_type="purchased", item_category="gauge",
                         data_classification="confidential", created_by=CREATED_BY)
            s.add(gauge)
            await s.flush()
            for tool_number in p.serves:
                s.add(PartRelation(
                    from_part_id=gauge.id, to_part_id=tool_by_number[tool_number].id,
                    relation_type="serves", created_by=CREATED_BY))
        await s.commit()
        print(f"\nWrote {len(plan)} gauges.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--write"]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    asyncio.run(main(args[0], "--write" in sys.argv))
