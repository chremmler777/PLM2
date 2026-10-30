"""One-time: 1994 / 2277 (Brose) resin decisions confirmed by Christoph on 2026-10-28 after the raw
material meeting (Christine Kaufmann, Karl, Cody, Candy). Dry run by default.

    docker cp record_brose_resin_meeting_20261028.py compose-plm2-backend-1:/tmp/
    docker exec -i -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python /tmp/record_brose_resin_meeting_20261028.py --user <id> [--apply]

Per article: one comment on part.material with the decision and its source. The material link
and flag are only checked; a different MaterialDB link is reported as a conflict, never changed.
Per 1994 Moldflow row: material_label / udb_source filled only where empty. Shrinkage and
colour are not touched. Follows update_brose_resin_nominated.py.
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.moldflow import ToolMoldflow
from app.models.part import Part
from app.services import moldflow_service
from app.services.field_note_service import FieldNoteService

PROJECTS = (34, 35)  # 2277 Brose Backpanel, 1994 Brose Seat Trim
SOURCE = " Source: Christoph 2026-10-28, raw material meeting (Christine Kaufmann, Karl, Cody, Candy)."

BAYBLEND, HOSTACOM, EPLAMID, ROMILOY, PEARLTHANE, RADILON = 17, 19, 88, 90, 91, 92

PP = (HOSTACOM, "Resin decision 2026-10-28: Hostacom TRC352N (LyondellBasell, KTX 40-0223) NOMINATED, series starts "
                "with it. Drawing PP-TD20 acc. TL 52388-F. Alternatives (Polykemi etc.) are only sampled to press the "
                "price, and only if they can be validated. UDB: grade-specific (LYB CAE), MaterialDB #19." + SOURCE)
PA6 = (EPLAMID, "Resin decision 2026-10-28: EPSAN EPLAMID 6 H G15. Drawing PA6-GF15 acc. VW 50125. "
                "UDB: EPSAN generic PA6-GF15, MaterialDB #88." + SOURCE)
PLAN = {
    **{cpn: PP for cpn in ("206.881.800", "206.881.799", "206.885.967", "206.885.968", "206.886.197",
                           "206.885.219", "206.881.479", "206.881.971", "206.881.971.B", "206.881.972.A",
                           "206.881.971_G02")},
    "206.882.251": PA6, "206.882.252": PA6, "206.887.233": PA6,
    "206.881.971_G07": (PEARLTHANE, "Resin decision 2026-10-28: Pearlthane 11T95P (Lubrizol, via Danquinsa). "
                                    "Drawing TPU Shore 95A acc. TL 52622. UDB: GP85AB equivalent, MaterialDB #91."
                        + SOURCE),
    "206.881.971_G05": (RADILON, "Resin decision 2026-10-28: Radilon A HSK 333 BK (Radici). Drawing PA66 unfilled acc. "
                                 "VW 50127. UDB: Radilon A HS 164 NT equivalent, MaterialDB #92." + SOURCE),
    "206.883.607": (ROMILOY, "Resin decision 2026-10-28: Romiloy 3020/11 (Romira / Rowa), molded-in colour, not "
                             "painted. Drawing PA+ASA acc. TL 52673. UDB: grade-specific, MaterialDB #90 (FZ has it "
                             "since 2026-10-16)." + SOURCE),
    "206.881.793": (BAYBLEND, "Resin decision 2026-10-28: Bayblend T85 XF (Covestro, KTX 40-0221), painted part. "
                              "Drawing PC/ABS acc. TL 52231. No UDB: FZ uses its own Moldflow database." + SOURCE),
}

PP_MF = ("Hostacom TRC352N (40-0223)", "LYB CAE grade-specific UDB, MaterialDB #19 (decision 2026-10-28)")
MOLDFLOW = {  # 1994 tool -> (material_label, udb_source), each written only where empty
    **{t: PP_MF for t in ("199402", "199404", "199405", "199406", "199408", "199410")},
    "199401": ("EPLAMID 6 H G15 (Epsan)", "EPSAN generic PA6-GF15, MaterialDB #88 (decision 2026-10-28)"),
    "199403": ("EPLAMID 6 H G15 (Epsan)", "EPSAN generic PA6-GF15, MaterialDB #88 (decision 2026-10-28)"),
    "199407": ("Romiloy 3020/11", "Romira grade-specific UDB, MaterialDB #90, FZ has it since 2026-10-16"),
    "199409": ("Bayblend T85 XF (40-0221)", "No UDB: FZ uses its own Moldflow database (decision 2026-10-28)"),
}


async def main(user_id: int, apply: bool) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    conflicts = []
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        parts = (await session.execute(select(Part).where(Part.project_id.in_(PROJECTS)))).scalars().all()
        by_cpn = {p.customer_part_number: p for p in parts if p.item_category == "article"}
        tools = {p.part_number: p for p in parts if p.item_category == "tool"}
        missing = sorted(set(PLAN) - set(by_cpn)) + sorted(set(MOLDFLOW) - set(tools))
        if missing:
            raise SystemExit(f"not found: {missing}")

        for cpn, (mid, text) in PLAN.items():
            part = by_cpn[cpn]
            todo = []
            if part.materialdb_id != mid:
                conflicts.append(f"{cpn}: linked to MaterialDB #{part.materialdb_id}, decision says #{mid}")
            note = await FieldNoteService.get(session, part.id, "part.material")
            if note is None or all(c.body != text for c in note.comments):
                todo.append("part.material comment")
                if apply:
                    await FieldNoteService.add_comment(session, part, "part.material", text, user_id)
            if (note.flag_status if note else None) != "confirmed":
                conflicts.append(f"{cpn}: part.material flag is {note.flag_status if note else None}, not confirmed")
            print(f"{cpn:18} {part.part_number}: {', '.join(todo) or 'nothing to do'}")

        for tool_no, (label, udb) in MOLDFLOW.items():
            rows = (await session.execute(select(ToolMoldflow).where(
                ToolMoldflow.tool_part_id == tools[tool_no].id, ToolMoldflow.deleted_at.is_(None)))).scalars().all()
            for row in rows:
                data = {}
                if not row.material_label:
                    data["material_label"] = label
                if not row.udb_source:
                    data["udb_source"] = udb
                if apply and data:
                    await moldflow_service.update(session, row, data, user_id)
                print(f"moldflow {tool_no} {row.version}: {', '.join(data) or 'nothing to do'}"
                      f" (kept: label={row.material_label!r}, udb_source={row.udb_source!r}, udb_status={row.udb_status})")

        if apply:
            await session.commit()
            print("applied")
        else:
            print("dry run, nothing written (--apply to write)")
    for c in conflicts:
        print("CONFLICT", c)
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.user, a.apply))
