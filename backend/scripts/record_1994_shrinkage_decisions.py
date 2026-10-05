"""Record the 1994 tool shrinkage decisions from the BOM review of 10/05/2026
("1994 BOM - material and shrinkage.xlsx", chosen columns) as shrinkage decisions,
so every 1994 tool value says where it came from.

Dry run by default (prints what it would record, writes nothing):

    docker exec -e PYTHONPATH=/app compose-plm2-backend-1 \
        python -m scripts.record_1994_shrinkage_decisions --user christoph.demmler [--apply]

A tool that already has a current decision with the same values is skipped.
"""
import argparse
import asyncio
import logging

from sqlalchemy import select

from app.models import AsyncSessionLocal
from app.models.entities import User
from app.models.part import Part
from app.models.tool_shrink import ToolShrinkDecision
from app.services import tool_shrink_service as svc

REVIEW = "1994 BOM review 10/05/2026 (1994 BOM - material and shrinkage.xlsx)"
HOSTACOM = ("Supplier along / across values (LyondellBasell, measured on a 2.5 mm plaque). "
            "KTX tools 3127/3128 (1416 VW316) were cut 0.9 combined: history only, not a choice for 1994. "
            + REVIEW)
EPLAMID = "Glass fibre PA6-GF15: parallel / normal as on the datasheet (ISO 294-4, 2 mm). " + REVIEW

# tool -> (mode, values, preferred candidate kind, rationale, fallback source label)
DECISIONS = {
    "199402": ("split", (0.8, 1.1), "supplier", HOSTACOM, None),
    "199404": ("split", (0.8, 1.1), "supplier", HOSTACOM, None),
    "199405": ("split", (0.8, 1.1), "supplier", HOSTACOM, None),
    "199406": ("split", (0.8, 1.1), "supplier", HOSTACOM, None),
    "199408": ("split", (0.8, 1.1), "supplier", HOSTACOM, None),
    "199410": ("split", (0.8, 1.1), "supplier", HOSTACOM, None),
    "199401": ("split", (0.7, 1.0), "datasheet", EPLAMID, None),
    "199403": ("split", (0.7, 1.0), "datasheet", EPLAMID, None),
    "199409": ("combined", 0.65, "ktx_experience",
               "Decor cover is painted: KTX tooling value for painted Bayblend T85 XF is 0.65 (unpainted 0.6); "
               "datasheet 0.5-0.7. Unfilled PC/ABS: one combined value. " + REVIEW,
               "KTX tooling note: Bayblend T85 XF painted 0.65 / unpainted 0.6 (MaterialDB 40-0221)"),
    "199407": ("combined", 0.9, "datasheet",
               "Middle of the datasheet range 0.8-1.0 (ISO 294-4, one range, unfilled PA/ASA): one combined value. "
               + REVIEW, None),
}


async def main(username: str, apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one()
        print(f"as {user.full_name} (id {user.id}), {'APPLY' if apply else 'dry run'}")
        for number, (mode, values, kind, rationale, fallback) in DECISIONS.items():
            tool = (await db.execute(select(Part).where(Part.part_number == number,
                                                         Part.item_category == "tool"))).scalar_one()
            par, nor, comb = (values[0], values[1], None) if mode == "split" else (None, None, values)
            cur = (await db.execute(select(ToolShrinkDecision).where(
                ToolShrinkDecision.tool_id == tool.id, ToolShrinkDecision.status == "current"))).scalar_one_or_none()
            if cur and (cur.parallel_pct, cur.normal_pct, cur.combined_pct) == (par, nor, comb):
                print(f"  {number}: already decided {svc.values_text(comb, par, nor)}, skipped")
                continue
            c = await svc.candidates(db, tool)
            pick = next((x for x in c["candidates"] if x["kind"] == kind), None)
            label = fallback or (pick["source_label"] if pick else None)
            mat = c["materials"][0] if c["materials"] else {}
            print(f"  {number}: {tool.tool_shrink_parallel_pct}/{tool.tool_shrink_normal_pct}/"
                  f"{tool.tool_shrink_combined_pct} -> {svc.values_text(comb, par, nor)} | {kind}: {label} "
                  f"| {mat.get('label')}{' | MaterialDB: ' + c['error'] if c['error'] else ''}")
            if not label:
                raise SystemExit(f"{number}: no {kind} source found in MaterialDB; stop")
            if apply:
                await svc.decide(db, tool, user, parallel_pct=par, normal_pct=nor, combined_pct=comb,
                                 source_kind=kind, source_label=label, rationale=rationale,
                                 materialdb_id=mat.get("materialdb_id"), material_label=mat.get("label"),
                                 shown=c["candidates"])
        if apply:
            await db.commit()
            print("committed")
        else:
            await db.rollback()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.user, a.apply))
