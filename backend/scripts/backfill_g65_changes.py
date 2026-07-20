"""Backfill G65 part-history-sheet rows as auto-created closed changes — SP-C.

Each historical row on a G65 (BMW G6X, PLM project 1748) part history sheet
becomes a ChangeRequest in a terminal `closed` state, marked as an
auto-created backfill of a change implemented before PLM existed. The change
is linked to its affected assembly (the ZSB 20-33xx part) via a lead
change_impacted_item. Inserted directly (NOT through the transition service),
because these pre-rollout changes never ran the live workflow/gates.

Idempotent: change_number is deterministic (`PHS-<affected>-<row-no>`), so a
re-run skips rows already loaded. Written generically so VW426's sheets can
run through the same script when they arrive (point --sheets-dir at them).

Run in the PLM backend container (has models + openpyxl + DATABASE_URL):
    docker exec -e PYTHONPATH=/app claude-plm2-backend-1 \
        python /app/scripts/backfill_g65_changes.py --sheets-dir /tmp/g65_sheets
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

PROJECT_CODE = "1748"          # BMW G6X ("G65")
RAISED_BY = 3                  # chris
ISSUER = "Part History Sheet (backfill)"
DATA_ROW_START = 16
BACKFILL_NOTE = ("Backfilled from part history sheet; implemented prior to PLM "
                 "rollout, so it never ran the live change workflow/gates.")

# Column layout of a part history sheet (1-indexed): B=No, C=Occasion/Process,
# D=Customer Level, E=EC Number, F=Internal Level, G=Drawing Index, H=Agreed by.
COL = {"no": 2, "occasion": 3, "customer_level": 4, "ec_number": 5,
       "internal_level": 6, "drawing_index": 7, "agreed": 8}

_PARTNO = re.compile(r"([0-9A-Za-z]{2}-[0-9A-Za-z\-]+|\b50-\d+\b)")


def _cell(ws, r, c):
    v = ws.cell(r, c).value
    return str(v).strip() if v is not None else None


def _partno_after_colon(text):
    """'Internal ZSB-Nr.: 20-3342-001-0' -> '20-3342-001-0'; '-' -> None."""
    if not text or ":" not in text:
        return None
    tail = text.split(":", 1)[1].strip()
    return tail if tail and tail != "-" else None


def parse_sheet(ws):
    """Return (affected_part_number, description, [row dicts]) or None to skip."""
    b5 = _cell(ws, 5, 2)
    if not b5:                       # PHS_Propsal / empty template
        return None
    zsb = _partno_after_colon(_cell(ws, 7, 10))      # J7 Internal ZSB-Nr.
    intpn = _partno_after_colon(_cell(ws, 5, 10))    # J5 Internal Part No.
    affected = zsb or intpn
    if not affected:
        return None
    description = _cell(ws, 3, 2)     # B3, e.g. 'ZB MAS VO BASIS'
    rows = []
    for r in range(DATA_ROW_START, 400):
        no = _cell(ws, r, COL["no"])
        if no is None or not no.isdigit():
            continue
        rows.append({k: _cell(ws, r, c) for k, c in COL.items()})
    return affected, description, b5, rows


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets-dir", required=True)
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        from app.models.entities import Project
        proj = (await s.execute(select(Project).where(Project.code == PROJECT_CODE))).scalar_one()

        # existing change numbers for idempotency
        existing = set((await s.execute(select(ChangeRequest.change_number))).scalars())
        # part_id by number (for impacted-item linking)
        part_ids = {p.part_number: p.id for p in (await s.execute(select(Part))).scalars()}

        now = datetime.utcnow()
        created = skipped = 0
        for f in sorted(glob.glob(os.path.join(args.sheets_dir, "*.xlsx"))):
            wb = openpyxl.load_workbook(f, data_only=True)
            for ws in wb.worksheets:
                parsed = parse_sheet(ws)
                if not parsed:
                    continue
                affected, description, customer_no, rows = parsed
                part_id = part_ids.get(affected)
                for row in rows:
                    change_number = f"PHS-{affected}-{row['no']}"[:30]
                    if change_number in existing:
                        skipped += 1
                        continue
                    occasion = row.get("occasion") or "Historical change"
                    title = f"G6X {description or affected} — {occasion}"[:255]
                    detail = (
                        f"{BACKFILL_NOTE}\n\n"
                        f"Part history sheet: {customer_no} ({description}).\n"
                        f"Affected internal part: {affected}.\n"
                        f"Occasion/Process: {occasion}\n"
                        f"Customer Level: {row.get('customer_level')}\n"
                        f"EC Number: {row.get('ec_number')}\n"
                        f"Internal Level: {row.get('internal_level')}\n"
                        f"Drawing Index: {row.get('drawing_index')}\n"
                        f"Agreed by: {row.get('agreed')}"
                    )
                    change = ChangeRequest(
                        change_number=change_number,
                        project_id=proj.id,
                        title=title,
                        description=detail,
                        reason="Backfill of pre-PLM part-history-sheet change.",
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
                            eng_level_after=" / ".join(
                                x for x in (row.get("internal_level"), row.get("drawing_index")) if x) or None,
                            impact_note=(f"EC {row.get('ec_number')}; customer level "
                                         f"{row.get('customer_level')}; agreed {row.get('agreed')}"),
                            created_by=RAISED_BY,
                        ))
                    existing.add(change_number)
                    created += 1
            await s.flush()
        await s.commit()
        print(f"G65 backfill: created={created} skipped={skipped} (project {proj.code} id {proj.id})")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
