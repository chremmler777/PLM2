"""Seed the VW426 (project 1864) cell equipment. Dry run by default; --write commits.

Facts, per Christoph 2026-07-24:
  - All eight tools have an EOAT.
  - 3450, 3451, 3452, 3453, 3456 each have a degater and are finished after degating.
  - 3454 and 3455 share one punch-and-weld station; it is numbered after the
    lowest tool it serves, so 3454-30.
  - 3457 has no degater. Its brackets are welded downstream: two into 3454 and
    two into 3455. They are measured by caliber, so 3457 has no gauge.
"""
import asyncio
import sys

from sqlalchemy import select

from app.models.database import AsyncSessionLocal
from app.models.part import Part, PartRelation
from app.services.equipment_numbering import equipment_number, item_category_for

CREATED_BY = 3  # chris

EOAT_TOOLS = ["3450", "3451", "3452", "3453", "3454", "3455", "3456", "3457"]
DEGATER_TOOLS = ["3450", "3451", "3452", "3453", "3456"]
PW_STATION_SERVES = ["3454", "3455", "3457"]
FEEDS = [("3457", "3454", "2 brackets"), ("3457", "3455", "2 brackets")]


async def main(write: bool) -> None:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(
            select(Part.part_number, Part.id, Part.project_id).where(
                Part.item_category == "tool",
                Part.part_number.in_(
                    EOAT_TOOLS + DEGATER_TOOLS + PW_STATION_SERVES)))).all()
        by_number = {r.part_number: r for r in rows}

        missing = set(EOAT_TOOLS + DEGATER_TOOLS + PW_STATION_SERVES) - set(by_number)
        if missing:
            print(f"ABORT: missing tool parts {sorted(missing)}")
            return

        planned: list[tuple[str, str, list[str]]] = []
        for tool in EOAT_TOOLS:
            planned.append((equipment_number(tool, 1, 0), "EOAT", [tool]))
        for tool in DEGATER_TOOLS:
            planned.append((equipment_number(tool, 2, 0), "Degate station", [tool]))
        planned.append((equipment_number("3454", 3, 0),
                        "Punch & weld station", PW_STATION_SERVES))

        existing = {pn for (pn,) in (await s.execute(
            select(Part.part_number).where(
                Part.part_number.in_([p[0] for p in planned])))).all()}

        for number, name, serves in planned:
            mark = "EXISTS" if number in existing else "CREATE"
            print(f"  {mark} {number:10} {name:22} serves {','.join(serves)}")
        for src, dst, note in FEEDS:
            print(f"  FEEDS  {src} -> {dst} ({note})")

        if not write:
            print("\nDRY RUN — nothing written. Re-run with --write to commit.")
            return

        for number, name, serves in planned:
            if number in existing:
                continue
            owner = by_number[serves[0]]
            eq = Part(project_id=owner.project_id, part_number=number, name=name,
                      part_type="purchased",
                      item_category=item_category_for(number.rpartition("-")[2]),
                      data_classification="confidential", created_by=CREATED_BY)
            s.add(eq)
            await s.flush()
            for tool in serves:
                s.add(PartRelation(from_part_id=eq.id, to_part_id=by_number[tool].id,
                                   relation_type="serves", created_by=CREATED_BY))
        existing_feeds = {
            (r.from_part_id, r.to_part_id) for r in (await s.execute(
                select(PartRelation).where(
                    PartRelation.relation_type == "feeds"))).scalars().all()}
        for src, dst, note in FEEDS:
            key = (by_number[src].id, by_number[dst].id)
            if key in existing_feeds:
                continue
            s.add(PartRelation(from_part_id=key[0], to_part_id=key[1],
                               relation_type="feeds", notes=note,
                               created_by=CREATED_BY))
        await s.commit()
        print("\nSeeded VW426 cell equipment.")


if __name__ == "__main__":
    asyncio.run(main("--write" in sys.argv))
