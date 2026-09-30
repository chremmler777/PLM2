"""One-time (2026-09-30): open flags on tool.shrink_parallel for the 1994 / 2277 tools whose
resin has no shrinkage value yet. Dry run by default.

    docker exec -i -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python /tmp/flag_brose_tool_shrinkage.py --user <id> [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.part import Part
from app.services.field_note_service import FieldNoteService

KEY = "tool.shrink_parallel"
HOSTACOM = ("No shrinkage value yet: the Hostacom TRC 352N datasheet only says 'contact LyondellBasell'. "
            "Purchasing to request parallel AND normal for our wall thickness: TD20 is talc-filled, and the "
            "talc platelets orient with the flow, so the two can differ (less than with glass fibre). "
            "No KTX reference: the Nifco simulations of 3127/3128 (our other TRC 352N tools) were run on PC/ABS.")
PEARLTHANE = ("No shrinkage value yet: the Pearlthane 11T95P datasheet gives none. Purchasing to request it from "
              "Lubrizol (unfilled TPU: one value).")
PLAN = {**{t: HOSTACOM for t in ("199402", "199404", "199405", "199406", "199408", "199410",
                                 "227701", "227702", "227703")},
        "227705": PEARLTHANE}


async def main(user_id: int, apply: bool) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        tools = {t.part_number: t for t in (await session.execute(select(Part).where(
            Part.project_id.in_((34, 35)), Part.item_category == "tool"))).scalars().all()}
        for number, text in PLAN.items():
            tool = tools[number]
            note = await FieldNoteService.get(session, tool.id, KEY)
            has = note is not None and any(c.body == text for c in note.comments)
            print(f"{number}: {'comment there' if has else 'comment'}, flag {note.flag_status if note else None} -> open")
            if apply:
                if not has:
                    await FieldNoteService.add_comment(session, tool, KEY, text, user_id)
                await FieldNoteService.set_flag(session, tool, KEY, "open", user_id)
        if apply:
            await session.commit()
            print("applied")
        else:
            print("dry run (--apply to write)")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.user, a.apply))
