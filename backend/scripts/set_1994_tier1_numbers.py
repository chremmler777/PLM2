"""Set the Brose (Tier 1) part numbers on the 1994 articles from the Brose
finished-part volume sheet received 2026-09-23. customer_part_number stays the
VW number. Rows that cannot be told apart on the sheet (the two "Handle Grif"
and the two "Latch Trim" rows) are left empty until Brose confirms the
cross-reference. One changelog entry per part. Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/set_1994_tier1_numbers.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.part_service import ChangelogService

# VW number -> Brose finished part number (sheet column "Finished Part Number")
TIER1 = {
    "206.881.799": "S00HP8-110",  # A-Bracket Outer COVER
    "206.881.479": "S00H43-110",  # Cover - Side shield, inner (sheet says r..., we hold LH)
    "206.881.793": "S00H4R-110",  # Blende Backrest - Painted
    "206.881.800": "S00H48-110",  # A-Bracket Inner Cover
    "206.883.607": "S00H4D-110",  # Belt Exit Cvr (sheet cell corrupted "S00H4D-110S00HTD-", first number taken)
    "206.885.219": "S00HT7-110",  # COVER TRIM
    "206.887.233": "S00H54-110",  # ISOFIX Cover
    "206.886.197": "S00HQJ-110",  # Cover - Center Bearing
}
# Left empty on purpose: 206.882.251/252 (S00H4X-110 / S00H4W-110, "Handle Grif" x2)
# and 206.885.967/968 (S00H56-110 / S00G0E-110, "Bracket, Seat Bk Latch Trim" x2).
REASON = "Tier 1 (Brose) finished part number from the Brose volume sheet received 2026-09-23, mapped by part name"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        parts = (await s.execute(select(Part).where(Part.project_id == project.id))).scalars().all()
        by_cpn = {p.customer_part_number: p for p in parts if p.item_category == "article"}
        changes = []
        for cpn, t1 in TIER1.items():
            p = by_cpn.get(cpn)
            if p is None:
                print(f"   ! article {cpn} not in project")
                continue
            if p.tier1_part_number != t1:
                changes.append((p, p.tier1_part_number, t1))

        print(f"== TIER 1 NUMBERS ({len(changes)} parts)")
        for p, old, new in changes:
            print(f"   {p.part_number:<14} {p.customer_part_number}  {old!r} -> {new!r}")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return

        for p, old, new in changes:
            p.tier1_part_number = new
            await ChangelogService.log_action(
                s, part_id=p.id, action="metadata_updated",
                action_description=f"Tier 1 part number {old!r} -> {new!r}. {REASON}",
                performed_by=args.user, field_name="tier1_part_number", old_value=old, new_value=new)
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
