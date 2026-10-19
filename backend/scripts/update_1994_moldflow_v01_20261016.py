"""1994 Moldflow: FZ V01 reports for 7 tools received 2026-10-16 (TransferNow
ZIP, one V01 report + .mfr per tool), 4 reviewed by Christoph the same day.
Updates each tool's V1 row through moldflow_service.update (audited). Notes
are appended, not replaced. Idempotent: a second run changes nothing. Dry run
by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/update_1994_moldflow_v01_20261016.py --user 14 [--apply]
"""
import argparse
import asyncio
import os
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.moldflow import ToolMoldflow
from app.models.part import Part
from app.services import moldflow_service

D = date(2026, 10, 16)
SRC = ("FZ TransferNow ZIP 2026-10-16 07:13/07:24 (V01 report + .mfr), "
       "local copy Downloads\\1994_Scout_Moldflow_Review on Christoph's PC")
REVIEWED = "KTX review OK (CD) 2026-10-16, to send to Brose."

UPDATES = {
    "199401": dict(received_on=D, ktx_review_on=D, status="in_review", geometry_status="ready", gate_status="ready",
                   material_label="BASF Ultramid B3EG3 (substitute for EPLAMID 6 H G15)",
                   blockers="Sink marks critical on front wall (0.095 mm vs 0.05 mm limit): rib reduction + Brose OK needed",
                   note=f"FZ-26361 V01. {REVIEWED}"),
    "199402": dict(received_on=D, ktx_review_on=D, status="in_review", geometry_status="ready", gate_status="ready",
                   blockers="Weld lines need Brose confirmation",
                   note=f"FZ-26364 V01. {REVIEWED}"),
    "199403": dict(received_on=D, status="received", geometry_status="ready", gate_status="ready",
                   blockers="Questions to FZ: clamp 8.4 t for 4 cav implausible; warp 0.8 mm; "
                            "different PA6-GF15 grade than 199401",
                   note="FZ-26365 V01. KTX review open, questions sent to FZ."),
    "199404": dict(received_on=D, status="received", geometry_status="ready", gate_status="ready",
                   blockers="Questions to FZ: summary table looks copied from 199401; FZ says bigger press needed",
                   note="FZ-26362 V01. KTX review open, questions sent to FZ."),
    "199406": dict(received_on=D, ktx_review_on=D, status="in_review",
                   note=f"FZ-26367 V01. Gate matches DFM. {REVIEWED}"),
    "199407": dict(received_on=D, ktx_review_on=D, status="rework", geometry_status="ready", gate_status="ready",
                   blockers="Run with wrong material (Terblend N NM-21EF instead of Romiloy 3020/11): re-run needed. "
                            "Gate deviates from DFM (tunnel gate at slide front instead of cashew, DFM rev 10/11): "
                            "gate vestige needs Brose clarification",
                   note=f"FZ-26363 V01. {REVIEWED}"),
    "199409": dict(received_on=D, status="received",
                   blockers="Run with Bayblend T65 XF instead of T85 XF: re-run or justify",
                   note="FZ-26368 V01. KTX review open."),
}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        for tool_no, upd in UPDATES.items():
            tool = (await s.execute(select(Part).where(
                Part.project_id == project.id, Part.part_number == tool_no,
                Part.item_category == "tool"))).scalar_one()
            row = (await s.execute(select(ToolMoldflow).where(
                ToolMoldflow.tool_part_id == tool.id, ToolMoldflow.version == "V1",
                ToolMoldflow.deleted_at.is_(None)))).scalars().first()
            if row is None:
                print(f"{tool_no}: no V1 row - skipped")
                continue
            data = {k: v for k, v in upd.items() if k != "note"}
            if upd["note"] not in (row.notes or ""):
                data["notes"] = f"{row.notes}\n{upd['note']}" if row.notes else upd["note"]
            if SRC not in (row.source_ref or ""):
                data["source_ref"] = f"{row.source_ref}\n{SRC}" if row.source_ref else SRC
            changed = {k: v for k, v in data.items() if getattr(row, k) != v}
            print(f"{tool_no}: {row.status} -> {upd['status']}; changes: {', '.join(changed) or 'none'}")
            if args.apply and changed:
                await moldflow_service.update(s, row, changed, args.user)
        if args.apply:
            await s.commit()
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
