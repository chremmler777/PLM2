"""Rename the 1994 and 2277 molded articles to the group Infor article scheme
(Karen Braunsdorf 2026-09-22, "Artikelnummerngestaltung Teile"; approved by
Christoph 2026-10-21 via Ass).

    [state 2 = finished][area 1 = injection molding]-[project 4 + tool 2]-
    [color/design 4][fixed variant 2][version 2]

Color/design and version are not known yet (XXXX / XX). The variant is 01/02
where two articles share a tool, 00 otherwise (provisional reading). Bought-in
50- parts and tool numbers stay. The old number is kept findable: it is
prepended to the description ("Formerly 20-1994-005-0.") and logged.

Checks before writing: old number exists, new number is unused, and the tool
segment matches the tool the article is linked to ("produces").
Dry run unless --apply.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/rename_articles_infor_scheme_20261021.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.part import Part, PartRelation
from app.services.part_service import ChangelogService

RENAMES = {
    "20-1994-001-0": "21-199401-XXXX-01XX",
    "20-1994-002-0": "21-199401-XXXX-02XX",
    "20-1994-003-0": "21-199402-XXXX-01XX",
    "20-1994-004-0": "21-199402-XXXX-02XX",
    "20-1994-005-0": "21-199403-XXXX-00XX",
    "20-1994-006-0": "21-199404-XXXX-00XX",
    "20-1994-007-0": "21-199405-XXXX-00XX",
    "20-1994-008-0": "21-199406-XXXX-00XX",
    "20-1994-009-0": "21-199407-XXXX-00XX",
    "20-1994-010-0": "21-199408-XXXX-00XX",
    "20-1994-011-0": "21-199409-XXXX-00XX",
    "20-1994-012-0": "21-199410-XXXX-00XX",
    "20-2277-001-0": "21-227701-XXXX-00XX",
    "20-2277-002-0": "21-227702-XXXX-01XX",
    "20-2277-003-0": "21-227702-XXXX-02XX",
    "20-2277-004-0": "21-227703-XXXX-00XX",
    "20-2277-005-0": "21-227704-XXXX-00XX",
    "20-2277-006-0": "21-227705-XXXX-00XX",
}


async def linked_tools(s, part):
    rels = (await s.execute(select(PartRelation).where(or_(
        PartRelation.from_part_id == part.id, PartRelation.to_part_id == part.id)))).scalars().all()
    out = set()
    for r in rels:
        other = await s.get(Part, r.to_part_id if r.from_part_id == part.id else r.from_part_id)
        if other is not None and other.item_category == "tool":
            out.add(other.part_number)
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        taken = set((await s.execute(select(Part.part_number).where(
            Part.part_number.in_(list(RENAMES.values()))))).scalars())
        todo = []
        for old, new in RENAMES.items():
            part = (await s.execute(select(Part).where(Part.part_number == old))).scalars().all()
            if not part:
                done = (await s.execute(select(Part).where(Part.part_number == new))).scalar_one_or_none()
                if done is not None:
                    print(f"{old} -> {new}: already renamed (id {done.id}); skip")
                    continue
                raise SystemExit(f"{old}: not found, stop")
            if len(part) > 1:
                raise SystemExit(f"{old}: {len(part)} parts carry it, stop")
            part = part[0]
            if new in taken:
                raise SystemExit(f"{new}: already used, stop")
            tool = new.split("-")[1]
            tools = await linked_tools(s, part)
            if tools != {tool}:
                raise SystemExit(f"{old}: linked tools {sorted(tools)} != {tool}, stop")
            print(f"{old} -> {new}  {part.customer_part_number}  tool {tool}  (id {part.id})")
            todo.append((part, old, new))
        if not args.apply:
            print(f"\nDRY RUN - {len(todo)} rename(s), nothing written.")
            return
        for part, old, new in todo:
            note = f"Formerly {old}."
            if not (part.description or "").startswith(note):
                part.description = f"{note} {part.description}" if part.description else note
            part.part_number = new
            await ChangelogService.log_action(
                s, part_id=part.id, action="renumbered",
                action_description=f"Part number {old} -> {new} (group Infor article scheme)",
                performed_by=args.user, field_name="part_number", old_value=old, new_value=new)
        await s.commit()
        print(f"APPLIED - {len(todo)} rename(s).")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
