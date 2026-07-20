"""Backfill VW426 (Atlas, PLM project 1864) OPM part-history rows as changes — SP-C/VW426.

Sibling of backfill_g65_changes.py, but for the OPM "Parts Resume" sheet
template used on the VW426 Atlas program (a different layout from the G65
"Part History Sheet"). Each historical trial/change row becomes a
ChangeRequest in a terminal `closed` state, marked as an auto-created
backfill of a change tracked outside PLM (before rollout). The change is
linked to its affected internal part (from the sheet's "Internal Part No."
cell) via a lead change_impacted_item.

The affected internal part number is read straight off the sheet (cell T8,
e.g. "Internal Part No.: 20-3454-001-0"), so it maps 1:1 to the PLM part
imported from WinCarat project 1864 — no fuzzy customer->internal guessing.

Idempotent: change_number is deterministic (`PHS-<internal>-<row-no>`), so
a re-run skips rows already loaded.

Run in the PLM backend container:
    docker exec claude-plm2-backend-1 sh -c \
        'cd /app && PYTHONPATH=/app python scripts/backfill_vw426_changes.py \
             --sheets-dir /tmp/vw426_sheets'
"""
import argparse
import asyncio
import glob
import os
import re
from datetime import datetime

import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.change import ChangeRequest, ChangeImpactedItem
from app.models.part import Part

RAISED_BY = 3                  # chris
ISSUER = "Part History Sheet (backfill)"
DATA_ROW_START = 18
BACKFILL_NOTE = ("Backfilled from OPM parts-resume sheet; tracked outside PLM "
                 "prior to rollout, so it never ran the live change workflow/gates.")

# OPM "Parts Resume" column layout (1-indexed). B=running No.,
# C=Occasion/Process (dated free text), O=drawing index/level, P=drawing
# date, R=name/dept, V/W/X/Y=Dimensional/Laboratory/Function/Total sample
# status, Z=delivery no., AC=change-description detail.
COL = {"no": 2, "occasion": 3, "drw_index": 15, "drw_date": 16, "responsible": 18,
       "dim": 22, "lab": 23, "func": 24, "total": 25, "deliv": 26, "detail": 29}
# header cells (row, col)
H_NAME = (6, 2)        # B6  "Name: ..."
H_CUSTOMER = (8, 2)    # B8  "Part No.: ..." (customer)
H_INTERNAL = (8, 20)   # T8  "Internal Part No.: ..."
H_ZSB = (10, 20)       # T10 "Internal ZSB-Nr.: ..."


def _cell(ws, r, c):
    v = ws.cell(r, c).value
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _after_colon(text):
    """'Internal Part No.: 20-3454-001-0' -> '20-3454-001-0'; '_'/'-' -> None."""
    if not text or ":" not in text:
        return None
    tail = text.split(":", 1)[1].strip()
    return tail if tail and tail not in ("-", "_") else None


def parse_sheet(ws):
    """Return (internal_part, customer_no, name, [row dicts]) or None to skip."""
    if not ws.title.strip().lower().startswith("parts resume"):
        return None                      # skip 'Pattern' and other tabs
    internal = _after_colon(_cell(ws, *H_INTERNAL))
    if not internal:
        return None
    customer_no = _after_colon(_cell(ws, *H_CUSTOMER))
    name = _after_colon(_cell(ws, *H_NAME)) or customer_no or internal
    rows = []
    seen_no = {}
    for r in range(DATA_ROW_START, 400):
        no = _cell(ws, r, COL["no"])
        if no is None:
            continue
        no = no.split(".")[0]            # openpyxl may hand back '1.0'
        if not no.isdigit():
            continue
        row = {k: _cell(ws, r, c) for k, c in COL.items()}
        row["no"] = no
        # Some sheets repeat a running No. (data-entry typo); disambiguate by
        # in-sheet occurrence so both rows survive with a stable, re-runnable
        # key (2nd occurrence -> '4-2'). Row order is stable across runs.
        seen_no[no] = seen_no.get(no, 0) + 1
        row["occ"] = seen_no[no]
        rows.append(row)
    return internal, customer_no, name, rows


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets-dir", required=True)
    ap.add_argument("--project-code", default="1864")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        from app.models.entities import Project
        proj = (await s.execute(
            select(Project).where(Project.code == args.project_code))).scalar_one()

        existing = set((await s.execute(select(ChangeRequest.change_number))).scalars())
        part_ids = {p.part_number: p.id for p in (await s.execute(select(Part))).scalars()}

        now = datetime.utcnow()
        created = skipped = unlinked = 0
        for f in sorted(glob.glob(os.path.join(args.sheets_dir, "*.xlsx"))):
            wb = openpyxl.load_workbook(f, data_only=True)
            for ws in wb.worksheets:
                parsed = parse_sheet(ws)
                if not parsed:
                    continue
                internal, customer_no, name, rows = parsed
                part_id = part_ids.get(internal)
                if part_id is None:
                    unlinked += 1
                for row in rows:
                    suffix = f"-{row['occ']}" if row.get("occ", 1) > 1 else ""
                    change_number = f"PHS-{internal}-{row['no']}{suffix}"[:30]
                    if change_number in existing:
                        skipped += 1
                        continue
                    occasion = row.get("occasion") or "Historical change"
                    headline = row.get("detail") or occasion
                    title = f"VW426 {name} — {headline}"[:255]
                    status_line = " / ".join(
                        f"{k}:{row.get(k)}" for k in ("dim", "lab", "func", "total")
                        if row.get(k))
                    detail = (
                        f"{BACKFILL_NOTE}\n\n"
                        f"OPM parts-resume sheet: {name}.\n"
                        f"Customer part no: {customer_no}.\n"
                        f"Affected internal part: {internal}.\n"
                        f"Occasion/Process: {occasion}\n"
                        f"Change description: {row.get('detail')}\n"
                        f"Drawing index/level: {row.get('drw_index')} "
                        f"(drawing date {row.get('drw_date')})\n"
                        f"Sample status: {status_line or '-'}\n"
                        f"Delivery no.: {row.get('deliv')}\n"
                        f"Responsible: {row.get('responsible')}"
                    )
                    change = ChangeRequest(
                        change_number=change_number,
                        project_id=proj.id,
                        title=title,
                        description=detail,
                        reason="Backfill of pre-PLM OPM parts-resume change.",
                        change_type="physical_part",
                        priority="medium",
                        data_classification="confidential",
                        status="closed",
                        raised_by=RAISED_BY,
                        raised_at=now,
                        closed_at=now,
                        customer_response="accepted",
                        customer_relevant=True,
                        cm_internal=True,
                        cm_external=False,
                        issuer=ISSUER,
                    )
                    s.add(change)
                    await s.flush()
                    if part_id:
                        s.add(ChangeImpactedItem(
                            change_id=change.id,
                            part_id=part_id,
                            is_lead=True,
                            eng_level_before=None,
                            eng_level_after=row.get("drw_index"),
                            impact_note=(f"{occasion}; sample status {status_line or '-'}"),
                            created_by=RAISED_BY,
                        ))
                    existing.add(change_number)
                    created += 1
            await s.flush()
        await s.commit()
        print(f"VW426 backfill: created={created} skipped={skipped} "
              f"unlinked_sheets={unlinked} (project {proj.code} id {proj.id})")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
