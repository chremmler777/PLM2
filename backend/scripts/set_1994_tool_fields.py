"""Set the sold-state tool fields on the ten 1994 tools from the nominated
RFQ 26 loop 37 (REV8): cavities, target cycle time, machine tonnage class,
and the toolmaker once known. One changelog entry per changed field. Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/set_1994_tool_fields.py [--toolmaker "<supplier name>"] [--apply]

Cavities and cycle times are final from RFQ 26 loop 37 (REV8, read 2026-09-23).
Tonnage class remains None (untouched). A None in FIELDS leaves that field alone.
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.models.supplier import Supplier
from app.services.part_service import ChangelogService

# tool part_number -> (cavities, cycle_time_s, tonnage_class)
# Cavities: total per tool. RFQ 26 loop 37 REV8 on prod stores cavities per article;
# the handles and latch covers are family tools with 2 per side (2+2 = 4).
FIELDS = {
    "199401": (4, 55.0, None),   # Handle, height adjustment LH/RH, 2+2
    "199402": (4, 50.0, None),   # Latch cover 40/60, 2+2
    "199403": (4, 55.0, None),   # Isofix cover, 4 cavities per nominated RFQ (prod relation note still says 2)
    "199404": (2, 50.0, None),   # A-bracket inner trim
    "199405": (2, 55.0, None),   # Cover trim, center back
    "199406": (2, 50.0, None),   # Center bearing cover
    "199407": (2, 50.0, None),   # Belt exit cover
    "199408": (2, 50.0, None),   # Inner side shield
    "199409": (8, 55.0, None),   # Decor cover
    "199410": (2, 50.0, None),   # A-bracket outer trim
}
REASON = "Sold state from the nominated RFQ 26 loop 37 (REV8), set 2026-09"

LABELS = {"tool_cavities": "Cavities", "tool_cycle_time_s": "Target cycle time (s)",
          "tool_tonnage_class": "Tonnage class (t)", "toolmaker_id": "Toolmaker"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--toolmaker", default=None, help="supplier name to set as toolmaker on all ten tools")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        tools = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.item_category == "tool"))).scalars().all()
        by_number = {p.part_number: p for p in tools}

        toolmaker_id = None
        if args.toolmaker:
            supplier = (await s.execute(select(Supplier).where(Supplier.name == args.toolmaker))).scalar_one_or_none()
            if supplier is None:
                raise SystemExit(f"No supplier named {args.toolmaker!r}; create it on the Suppliers page first")
            toolmaker_id = supplier.id

        changes = []  # (part, field, old, new)
        for number, (cav, cycle, tonnage) in FIELDS.items():
            p = by_number.get(number)
            if p is None:
                print(f"   ! tool {number} not in project {args.project}")
                continue
            wanted = {"tool_cavities": cav, "tool_cycle_time_s": cycle, "tool_tonnage_class": tonnage}
            if toolmaker_id is not None:
                wanted["toolmaker_id"] = toolmaker_id
            for field, new in wanted.items():
                if new is None:
                    continue
                old = getattr(p, field)
                if old != new:
                    changes.append((p, field, old, new))

        print(f"== TOOL FIELDS ({len(changes)} changes)")
        for p, field, old, new in changes:
            print(f"   {p.part_number:<8} {LABELS[field]:<22} {old!r} -> {new!r}")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return

        for p, field, old, new in changes:
            setattr(p, field, new)
            await ChangelogService.log_action(
                s, part_id=p.id, action="metadata_updated",
                action_description=f"{LABELS[field]} {old!r} -> {new!r}. {REASON}",
                performed_by=args.user, field_name=field,
                old_value=None if old is None else str(old), new_value=str(new))
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
