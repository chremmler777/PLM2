"""2277 Brose Backpanel: fill the missing tool cavities (Christoph 2026-10-26).

227703 Map Pocket 2, 227704 Pivot Axis (G05) 8, 227705 Rossette (G07) 4, from
RFQ2 rfq 25 loop 36 (selected variants, tooling_variant_items.cavities) and the
same counts in the tools' "produces" relation notes. One article per tool, so a
plain number, no layout. 227701/227702 were set on 10/21 and are left alone.
Changelog action "updated" is not a part data mail event, so no mail.
Idempotent; dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/set_2277_cavities_20261026.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.part_service import ChangelogService

CAVITIES = {"227703": "2", "227704": "8", "227705": "4"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="2277")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        for number, value in CAVITIES.items():
            tool = (await s.execute(select(Part).where(
                Part.project_id == project.id, Part.part_number == number,
                Part.item_category == "tool"))).scalar_one()
            old = tool.tool_cavities
            print(f"{number} tool_cavities {old!r} -> {value!r}{'  (unchanged)' if old == value else ''}")
            if not args.apply or old == value:
                continue
            tool.tool_cavities = value
            await ChangelogService.log_action(
                s, part_id=tool.id, action="updated",
                action_description=f"Cavities set to {value} (RFQ 25 loop 36, Christoph 2026-10-26)",
                performed_by=args.user, field_name="tool_cavities", old_value=old, new_value=value)
        if args.apply:
            await s.commit()
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
