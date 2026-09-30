"""One-time: resin status for 1994 / 2277 (Brose) after Procurement's mails of
2026-09-23..30, written into the worksheet's part.material notes. Dry run by default.

    docker cp update_brose_resin_status.py compose-plm2-backend-1:/tmp/
    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python /tmp/update_brose_resin_status.py --user <id> [--apply]

Per article (by customer part number): one comment on part.material, the flag, and
- the material as "new" text from the drawing where PLM has no material yet,
- 206.881.793 linked to MaterialDB 40-0221 (Bayblend T85 XF, Covestro confirmed).
Comments already on the note are not written again, so a second run does nothing.
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
KEY = "part.material"
PREFIX = "Resin status 2026-09-30: "
BAYBLEND_40_0221 = 17  # MaterialDB id

PP_1994 = ("REZYcom PP RT10020E VTUV rejected (recycled, drawing requires virgin VW 50026-GK1).{extra} "
           "Only path: virgin Hostacom, e.g. TRC 352N (40-0223, VW 316). Open: NM0 grade (we run "
           "Titan Schwarz), TL 52388-F and PV 3952 (dL* < 1.5) confirmation from LyondellBasell, "
           "Hostacom price (Procurement). Not nominated.")
PP_2277 = ("Same resin as the 1994 PP-TD20 parts: REZYcom rejected (recycled, VW 50026-GK1 virgin "
           "required); virgin Hostacom path (e.g. TRC 352N, 40-0223). Open: grade, TL 52388-F and "
           "PV 3952 confirmation, price; colour open with Brose (no colour code on the drawing, "
           "1 or more colours?). Not nominated.")
PA6 = ("REZYcom PA6 RB122 F15 rejected (recycled). Virgin candidates: EPLAMID 6 H G15 BK005 (Epsan, "
       "best of the offers: Charpy 8 kJ/m², HDT/A 200 °C), Chemlon 215 GHU (weaker: HDT/A 185 °C, "
       "GF % not printed, GM release only), fallback Ultramid B3ZG3 (40-0130, Charpy 12 kJ/m²). "
       "Open for all: VW 50125 release, virgin (GK1), PV 3952, NM0 colour. Not nominated.")

# customer part number -> (comment, flag, material text if PLM has none, MaterialDB id to link)
PLAN = {
    "206.881.479": (PP_1994.format(extra=" It also fails this drawing's table: Charpy notched 18 vs "
                                          "min 35 kJ/m² @23 °C, 3 (@-20 °C) vs 4.5 @-30 °C."), "open", None, None),
    "206.881.799": (PP_1994.format(extra=""), "open", None, None),
    "206.881.800": (PP_1994.format(extra=""), "open", None, None),
    "206.885.219": (PP_1994.format(extra=""), "open", None, None),
    "206.885.967": (PP_1994.format(extra=""), "open", None, None),
    "206.885.968": (PP_1994.format(extra=""), "open", None, None),
    "206.886.197": (PP_1994.format(extra=""), "open", None, None),
    "206.882.251": (PA6, "open", None, None),
    "206.882.252": (PA6, "open", None, None),
    "206.887.233": (PA6, "open", None, None),
    "206.883.607": ("ROMILOY 3020/11 datasheet received 2026-09-24: meets the drawing table (tensile modulus "
                    "1850 MPa, flexural strength 60 MPa, Charpy notched 78 vs min 75 kJ/m² dry, unnotched no "
                    "break). Open: TL 52673 release and virgin (GK1) from Romira, NM0 colour, budget (Karl). "
                    "Not nominated.", "open", None, None),
    "206.881.793": ("Pulse dropped. Bayblend T85 XF black, existing 40-0221 (black is fine, the part is "
                    "painted). Covestro confirmed 2026-09-28: VW 50026-GK1 (virgin) and TL 52231 sections "
                    "A and B. Linked to MaterialDB 40-0221.", "confirmed", None, BAYBLEND_40_0221),
    "206.881.971": (PP_2277, "open", "PP-TD20 acc. TL 52388-F", None),
    "206.881.971.B": (PP_2277, "open", "PP-TD20 acc. TL 52388-F", None),
    "206.881.972.A": (PP_2277, "open", "PP-TD20 acc. TL 52388-F", None),
    "206.881.971_G02": (PP_2277, "open", "PP-TD20 acc. TL 52388-F", None),
    "206.881.971_G05": ("PA66 per B-release drawing Y444264-1/A (VW 50127, unfilled, virgin); the RFQ BOM had "
                        "PA6-GF15, mismatch still open with Brose. Offered 2026-09-30: RADILON A HSK 333 BK "
                        "(Radici): unfilled PA66, black, heat stabilized, lubricated, North America supply; "
                        "technically fits. Open: VW 50127 release and virgin (GK1) from Radici, colour "
                        "requirement. Series alternative Heramid A NER MP/1K (40-0274), virgin not confirmed. "
                        "Not nominated.", "open", None, None),
    "206.881.971_G07": ("Offered: Pearlthane 11T95P (Lubrizol, via Danquinsa), Shore A 95 meets. Natural "
                        "only, black via Pearlthane MB-9005 masterbatch (RAL 9005): NM0 match and batching "
                        "open (LOP item). Open: TL 52622 release; second TPU offer pending (Procurement). "
                        "Not nominated.", "open", "TPU acc. TL 52622, Shore 95A", None),
}


async def main(user_id: int, apply: bool) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        parts = (await session.execute(select(Part).where(
            Part.project_id.in_(PROJECTS), Part.item_category == "article"))).scalars().all()
        by_cpn = {p.customer_part_number: p for p in parts}
        missing = sorted(set(PLAN) - set(by_cpn))
        if missing:
            raise SystemExit(f"articles not found: {missing}")
        for cpn, (text, flag, new_text, link_id) in PLAN.items():
            part = by_cpn[cpn]
            note = await FieldNoteService.get(session, part.id, KEY)
            body = PREFIX + text
            todo = []
            if note is None or all(c.body != body for c in note.comments):
                todo.append("comment")
            if (note.flag_status if note else None) != flag:
                todo.append(f"flag {note.flag_status if note else None} -> {flag}")
            if new_text and part.material_source is None:
                todo.append(f"material new '{new_text}'")
            if link_id and part.materialdb_id != link_id:
                todo.append(f"link MaterialDB #{link_id}")
            print(f"{cpn:18} {part.part_number}: {', '.join(todo) or 'nothing to do'}")
            if not apply:
                continue
            if "comment" in todo:
                await FieldNoteService.add_comment(session, part, KEY, body, user_id)
            await FieldNoteService.set_flag(session, part, KEY, flag, user_id)
            if new_text and part.material_source is None:
                await PartMaterialService.set_new(session, part, new_text, user_id)
            if link_id and part.materialdb_id != link_id:
                await PartMaterialService.link(session, part, link_id, user_id)
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
