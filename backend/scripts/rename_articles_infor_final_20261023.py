"""Final Infor numbers for the 18 molded 1994 and 2277 articles: the XXXX / XX
placeholders of the 2026-10-21 rename are filled in (Kathleen Hentschel
2026-10-23: Toccoa creates them; colour schwarz 0001 / titanschwarz 0503;
version digits 15-16 = 00 until parts are produced). Requested by Christoph
2026-10-23 via Ass; material may still change, then the colour gets updated.

The placeholder numbers were provisional, so no "Formerly" note is added; the
description keeps its "Formerly 20-...." legacy number and the changelog logs
the step. Renumbering is not a part data mail event, so nothing is mailed.
Same checks as the 10-21 rename: old number exists, new number is unused, the
tool segment matches the linked tool. Dry run unless --apply.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/rename_articles_infor_final_20261023.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.part import Part, PartRelation
from app.services.part_service import ChangelogService

RENAMES = {
    "21-199401-XXXX-01XX": "21-199401-0503-0100",
    "21-199401-XXXX-02XX": "21-199401-0503-0200",
    "21-199402-XXXX-01XX": "21-199402-0503-0100",
    "21-199402-XXXX-02XX": "21-199402-0503-0200",
    "21-199403-XXXX-00XX": "21-199403-0503-0000",
    "21-199404-XXXX-00XX": "21-199404-0503-0000",
    "21-199405-XXXX-00XX": "21-199405-0503-0000",
    "21-199406-XXXX-00XX": "21-199406-0503-0000",
    "21-199407-XXXX-00XX": "21-199407-0503-0000",
    "21-199408-XXXX-00XX": "21-199408-0503-0000",
    "21-199409-XXXX-00XX": "21-199409-0001-0000",
    "21-199410-XXXX-00XX": "21-199410-0503-0000",
    "21-227701-XXXX-00XX": "21-227701-0503-0000",
    "21-227702-XXXX-01XX": "21-227702-0503-0100",
    "21-227702-XXXX-02XX": "21-227702-0503-0200",
    "21-227703-XXXX-00XX": "21-227703-0503-0000",
    "21-227704-XXXX-00XX": "21-227704-0001-0000",
    "21-227705-XXXX-00XX": "21-227705-0503-0000",
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
            part.part_number = new
            await ChangelogService.log_action(
                s, part_id=part.id, action="renumbered",
                action_description=f"Part number {old} -> {new} (final Infor number, colour/version filled in)",
                performed_by=args.user, field_name="part_number", old_value=old, new_value=new)
        await s.commit()
        print(f"APPLIED - {len(todo)} rename(s).")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
