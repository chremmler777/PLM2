"""2277 Brose Backpanel: both back panel tools run on the 3200 t press (Christoph 2026-10-26).

227701 had 'KM 1300-1', the RFQ2 Tool Layout Designer's smallest-class pick
copied on 2026-09-29; that pick is wrong for 2277 and must not be copied again.
227702 already has the Engel. Cavities stay 2 (227701) and 1+1 (227702).
Changelog action "updated" is not a part data mail event, so no mail.
Idempotent; dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/set_2277_backpanel_machine_20261026.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.part_service import ChangelogService

PRESS = "EN 3200-1 (Engel DUO 17060/3500 TECH US)"
MACHINES = {"227701": PRESS, "227702": PRESS}


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
        for number, value in MACHINES.items():
            tool = (await s.execute(select(Part).where(
                Part.project_id == project.id, Part.part_number == number,
                Part.item_category == "tool"))).scalar_one()
            old = tool.tool_machine
            print(f"{number} tool_machine {old!r} -> {value!r}{'  (unchanged)' if old == value else ''}"
                  f"  [cavities {tool.tool_cavities}, class {tool.tool_tonnage_class}]")
            if not args.apply or old == value:
                continue
            tool.tool_machine = value
            await ChangelogService.log_action(
                s, part_id=tool.id, action="updated",
                action_description=f"Machine set to {value}: both back panels run on 3200 t (Christoph 2026-10-26)",
                performed_by=args.user, field_name="tool_machine", old_value=old, new_value=value)
        if args.apply:
            await s.commit()
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
