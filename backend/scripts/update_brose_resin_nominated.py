"""One-time: 1994 / 2277 (Brose) resins confirmed by Purchasing on 2026-09-30. Dry run by default.

    docker cp update_brose_resin_nominated.py compose-plm2-backend-1:/tmp/
    docker exec -i -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python /tmp/update_brose_resin_nominated.py --user <id> [--apply]

Per article: a comment on part.material (resin, colour route, supplier statements still to
come), flag "confirmed", and the material linked to its MaterialDB entry. Colour questions
still open with Brose go on part.colour_code with an open flag.
Follows update_brose_resin_status.py; comments already on a note are not written again.
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.part import Part
from app.services.field_note_service import FieldNoteService
from app.services.part_material_service import PartMaterialService

PROJECTS = (34, 35)  # 2277 Brose Backpanel, 1994 Brose Seat Trim
PREFIX = "Resin confirmed by Purchasing 2026-09-30: "
NM0 = " Colour NM0 batched by KTX (no supplier confirmed NM0)."

# MaterialDB ids
BAYBLEND, HOSTACOM, EPLAMID, ROMILOY, PEARLTHANE, RADILON = 17, 19, 88, 90, 91, 92

PA6 = (EPLAMID, "EPLAMID 6 H G15 BK005 (Epsan), new material base. Drawing PA6-GF15 acc. VW 50125." + NM0
       + " Epsan to confirm VW 50125, virgin VW 50026-GK1, PV 3952.")
PP = (HOSTACOM, "Hostacom TRC 352N (LyondellBasell, 40-0223), existing grade. Drawing P/E-TD20 acc. TL 52388-F." + NM0
      + " LyondellBasell to confirm TL 52388-F, PV 3952. Base colour for the batch to settle (40-0223 is Titan Schwarz).")
PP77 = (HOSTACOM, "Hostacom TRC 352N (LyondellBasell, 40-0223), existing grade. Drawing PP-TD20 acc. TL 52388-F."
        " LyondellBasell to confirm TL 52388-F, PV 3952. Colour open with Brose.")
PLAN = {
    "206.881.793": (BAYBLEND, "Bayblend T85 XF black (Covestro, 40-0221), existing grade. Painted VM0, black base OK. "
                              "Covestro confirmed VW 50026-GK1 and TL 52231 A/B on 2026-09-28."),
    "206.882.251": PA6, "206.882.252": PA6, "206.887.233": PA6,
    "206.881.479": PP, "206.881.799": PP, "206.881.800": PP, "206.885.219": PP,
    "206.885.967": PP, "206.885.968": PP, "206.886.197": PP,
    "206.883.607": (ROMILOY, "ROMILOY 3020/11 (Romira), new material base. Drawing PA+ASA acc. TL 52673." + NM0
                    + " Romira to confirm TL 52673, virgin GK1. Watch Charpy margin at sampling (78 dry vs min 75)."),
    "206.881.971": PP77, "206.881.971.B": PP77, "206.881.972.A": PP77, "206.881.971_G02": PP77,
    "206.881.971_G05": (RADILON, "RADILON A HSK 333 BK (Radici), new material base, standard black. Drawing PA66 acc. "
                                 "VW 50127 (RFQ BOM had PA6-GF15). Radici to confirm VW 50127, virgin GK1."),
    "206.881.971_G07": (PEARLTHANE, "Pearlthane 11T95P (Lubrizol), new material base, natural. Drawing TPU acc. TL 52622, "
                                    "Shore 95A." + NM0 + " Lubrizol to confirm TL 52622 (coloured compound), virgin GK1."),
}
COLOUR_OPEN = {
    "206.881.971_G05": "Drawing Y444264-1/A has no colour code. Ask Brose: standard black OK?",
    **{pn: "No colour code on the drawing. Ask Brose: one or more colours (NM0?)."
       for pn in ("206.881.971", "206.881.971.B", "206.881.972.A", "206.881.971_G02")},
}


async def _note(session, part, key, body, flag, user_id, apply) -> list[str]:
    note = await FieldNoteService.get(session, part.id, key)
    todo = []
    if note is None or all(c.body != body for c in note.comments):
        todo.append(f"{key} comment")
    if (note.flag_status if note else None) != flag:
        todo.append(f"{key} flag -> {flag}")
    if apply:
        if f"{key} comment" in todo:
            await FieldNoteService.add_comment(session, part, key, body, user_id)
        await FieldNoteService.set_flag(session, part, key, flag, user_id)
    return todo


async def main(user_id: int, apply: bool) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        parts = (await session.execute(select(Part).where(
            Part.project_id.in_(PROJECTS), Part.item_category == "article"))).scalars().all()
        by_cpn = {p.customer_part_number: p for p in parts}
        missing = sorted(set(PLAN) - set(by_cpn))
        if missing:
            raise SystemExit(f"articles not found: {missing}")
        for cpn, (mid, text) in PLAN.items():
            part = by_cpn[cpn]
            todo = await _note(session, part, "part.material", PREFIX + text, "confirmed", user_id, apply)
            if cpn in COLOUR_OPEN:
                todo += await _note(session, part, "part.colour_code", COLOUR_OPEN[cpn], "open", user_id, apply)
            if part.materialdb_id != mid:
                todo.append(f"link MaterialDB #{mid}")
                if apply:
                    await PartMaterialService.link(session, part, mid, user_id)
            print(f"{cpn:18} {part.part_number}: {', '.join(todo) or 'nothing to do'}")
        if apply:
            await session.commit()
            print("applied")
        else:
            print("dry run, nothing written (--apply to write)")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.user, a.apply))
