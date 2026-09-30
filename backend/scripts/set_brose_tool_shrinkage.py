"""One-time (2026-09-30): tool shrinkage decided by engineering (C. Demmler) for the 1994 / 2277
tools with a resin value, and NM0 on the two articles whose colour was agreed but not in PLM.
Dry run by default.

    docker exec -i -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python /tmp/set_brose_tool_shrinkage.py --user <id> [--apply]

Rule: one value for unfilled resins (parallel = normal), a split only for fibre-filled.
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.part import Part
from app.services.field_note_service import FieldNoteService
from app.services.part_service import PartService

PREFIX = "Set 2026-09-30 by engineering (C. Demmler): "
SHRINK = {  # tool: (parallel %, normal %, basis)
    "199401": (0.7, 1.0, "EPLAMID 6 H G15 BK005 datasheet 0.7 parallel / 1.0 normal (ISO 294-4, 2 mm). "
                         "Glass fibre: apply along / across the simulated flow; PA6 grows with moisture, keep fits steel-safe."),
    "199403": (0.7, 1.0, "EPLAMID 6 H G15 BK005 datasheet 0.7 parallel / 1.0 normal (ISO 294-4, 2 mm). "
                         "Glass fibre: apply along / across the simulated flow; PA6 grows with moisture, keep fits steel-safe."),
    "199407": (0.9, 0.9, "ROMILOY 3020/11 datasheet 0.8-1.0 (ISO 294-4), unfilled: one value, middle of the range."),
    "199409": (0.65, 0.65, "Bayblend T85 XF datasheet 0.5-0.7 (ISO 2577), unfilled: 0.6, +0.05 for post-shrink in the "
                           "paint oven (part painted)."),
    "227704": (1.25, 1.25, "RADILON A HSK 333 BK datasheet 1.2 parallel / 1.3 normal (ISO 294-4), unfilled: one value. "
                           "PA66 grows with moisture: axis diameter steel-safe, cut after sampling."),
}
COLOUR = {"206.883.607": "NM0 confirmed by Brose 2026-09-24 (no paint, no MIC change).",
          "206.881.971_G07": "NM0 per RFQ notes; natural Pearlthane coloured by KTX NM0 batch."}


async def _note(s, part, key, text, flag, uid, apply):
    note = await FieldNoteService.get(s, part.id, key)
    body = PREFIX + text
    todo = [] if note and any(c.body == body for c in note.comments) else ["comment"]
    if (note.flag_status if note else None) != flag:
        todo.append(f"flag -> {flag}")
    if apply:
        if "comment" in todo:
            await FieldNoteService.add_comment(s, part, key, body, uid)
        await FieldNoteService.set_flag(s, part, key, flag, uid)
    return todo


async def main(uid: int, apply: bool) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        parts = (await s.execute(select(Part).where(Part.project_id.in_((34, 35))))).scalars().all()
        tools = {p.part_number: p for p in parts if p.item_category == "tool"}
        arts = {p.customer_part_number: p for p in parts if p.item_category == "article"}
        for number, (par, nor, basis) in SHRINK.items():
            t = tools[number]
            todo = [] if (t.tool_shrink_parallel_pct, t.tool_shrink_normal_pct) == (par, nor) else [f"shrink {par}/{nor}"]
            if apply and todo:
                await PartService.update_part(s, t.id, updated_by=uid, tool_shrink_parallel_pct=par,
                                              update_tool_shrink_parallel_pct=True,
                                              tool_shrink_normal_pct=nor, update_tool_shrink_normal_pct=True)
            for key in ("tool.shrink_parallel", "tool.shrink_normal"):
                todo += [f"{key} {x}" for x in await _note(s, t, key, basis, "confirmed", uid, apply)]
            print(f"{number}: {', '.join(todo) or 'nothing to do'}")
        for cpn, text in COLOUR.items():
            a = arts[cpn]
            todo = [] if a.colour_code == "NM0" else ["colour_code NM0"]
            if apply and todo:
                await PartService.update_part(s, a.id, updated_by=uid, colour_code="NM0", update_colour_code=True)
            todo += [f"part.colour_code {x}" for x in await _note(s, a, "part.colour_code", text, "confirmed", uid, apply)]
            print(f"{cpn}: {', '.join(todo) or 'nothing to do'}")
        if apply:
            await s.commit()
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
