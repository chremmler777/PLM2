"""Rename the 1994 articles and tools to the names on the Brose B-release
drawings (title block Designation, 2026-05-28), LH/RH and 40/60 from the
CATIA filenames. One changelog entry per renamed part. Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/rename_1994_from_drawings.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part, PartRelation
from app.services.part_service import ChangelogService

# customer part number -> name (the app shows "<customer number> <name>")
ARTICLES = {
    "206.881.479": "Inner side shield",
    "206.881.793": "Decor cover",
    "206.881.799": "A-bracket outer trim",
    "206.881.800": "A-bracket inner trim",
    "206.882.251": "Handle, height adjustment LH",
    "206.882.252": "Handle, height adjustment RH",
    "206.883.607": "Belt exit cover",
    "206.885.219": "Cover trim, center back",
    "206.885.967": "Latch cover 40",
    "206.885.968": "Latch cover 60",
    "206.886.197": "Center bearing cover",
    "206.887.233": "Isofix cover",
}
# tool number -> name (prefix "1994 TOOL " as today)
TOOLS = {
    "199401": "Handle, height adjustment LH/RH",
    "199402": "Latch cover 40/60",
    "199403": "Isofix cover",
    "199404": "A-bracket inner trim",
    "199405": "Cover trim, center back",
    "199406": "Center bearing cover",
    "199407": "Belt exit cover",
    "199408": "Inner side shield",
    "199409": "Decor cover",
    "199410": "A-bracket outer trim",
}
REASON = "Name taken from the Brose B-RELEASE 2026-05-28 drawing title block (side/variant from the CATIA filename)"


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
        by_num = {p.part_number: p for p in parts}
        changes = []
        for cpn, name in ARTICLES.items():
            p = by_cpn.get(cpn)
            if p is None:
                print(f"   ! article {cpn} not in project")
                continue
            new = f"{cpn} {name}"
            if p.name != new:
                changes.append((p, p.name, new))
        for num, name in TOOLS.items():
            p = by_num.get(num)
            if p is None:
                print(f"   ! tool {num} not in project")
                continue
            new = f"{project.code} TOOL {name}"
            if p.name != new:
                changes.append((p, p.name, new))
        # tool 199408 lost its RH article: description and cavity note follow
        t408 = by_num.get("199408")
        lh = by_cpn.get("206.881.479")
        desc_change = None
        if t408 and "206.881.480" in (t408.description or ""):
            desc_change = (t408, t408.description,
                           "Injection mold, 2-plate, 2 cavities: 206.881.479 x2. Customer Brose Sitech. "
                           "Awarded 2026-09-02 (RFQ 26 REV8, tooling_calc 211). RH 206.881.480 removed 2026-09-22 (not nominated).")
        rel408 = None
        if t408 and lh:
            rel408 = (await s.execute(select(PartRelation).where(
                PartRelation.from_part_id == t408.id, PartRelation.to_part_id == lh.id,
                PartRelation.relation_type == "produces"))).scalar_one_or_none()

        print(f"== RENAME ({len(changes)} parts)")
        for p, old, new in changes:
            print(f"   {p.part_number:<14} {old!r} -> {new!r}")
        if desc_change:
            print(f"   199408 description -> {desc_change[2]!r}")
        if rel408 and rel408.notes != "2 cavities":
            print(f"   199408 -> 206.881.479 relation notes {rel408.notes!r} -> '2 cavities'")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return

        for p, old, new in changes:
            p.name = new
            await ChangelogService.log_action(
                s, part_id=p.id, action="metadata_updated",
                action_description=f"Renamed {old!r} -> {new!r}. {REASON}",
                performed_by=args.user, field_name="name", old_value=old, new_value=new)
        if desc_change:
            t, old, new = desc_change
            t.description = new
            await ChangelogService.log_action(
                s, part_id=t.id, action="metadata_updated",
                action_description="Description: RH 206.881.480 removed, 2 cavities 206.881.479 x2",
                performed_by=args.user, field_name="description", old_value=old, new_value=new)
        if rel408 and rel408.notes != "2 cavities":
            old = rel408.notes
            rel408.notes = "2 cavities"
            await ChangelogService.log_action(
                s, part_id=lh.id, action="metadata_updated",
                action_description=f"Tool 199408 produces relation notes {old!r} -> '2 cavities' (LH-only tool)",
                performed_by=args.user, field_name="relation_notes", old_value=old, new_value="2 cavities")
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
