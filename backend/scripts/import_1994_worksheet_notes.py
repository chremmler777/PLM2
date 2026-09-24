"""One-time: turn the 1994 engineering Excel (Brose 1994 RFQ26 BOM clean with
open points 2026-09-23.xlsx, sheet BOM) into PLM field notes. Dry run by default.

    docker cp "<xlsx>" plm2-integ-backend:/tmp/bom-1994.xlsx
    docker exec -i -e PYTHONPATH=/app plm2-integ-backend \
        python scripts/import_1994_worksheet_notes.py --xlsx /tmp/bom-1994.xlsx --user <id> [--apply]

--user is required: the PLM user id the comments and flags are written as.

Per Excel row (article by the OEM number in column D, tool by column B):
- Tier 1 numbers: the four the Excel resolves, only where PLM has none.
- Material: new with the "Material acc. drawing" text where no material is set.
- Designation (column F) marked yellow (open): a comment on part.name.
- Proposed resin and resin status: a comment on part.material, flag from the colour.
- Cavities differing from PLM (or marked yellow): open flag and a comment on the
  tool's tool.cavities; PLM cavities are never overwritten.
- Painted, colour, MIC cells with a colour: comments on paint.painted / paint.colour.
- Open question and answer: comments on the field they are about (QUESTION_FIELD).
- Grain (drawing, frozen RFQ, gloss, question, answer): one comment on revision.level.
Colours: yellow = open, green = confirmed, salmon = rejected.
Every comment starts with COMMENT_PREFIX. The dry run lists only what --apply
would write: comments that already exist (also in the wording of the first
import, without the prefix) and flags already set are left out, so a dry run
after an apply says "nothing to do".
"""
import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Optional

import openpyxl
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.field_note_service import FieldNoteService
from app.services.part_material_service import PartMaterialService
from app.services.part_service import ChangelogService

SHEET = "BOM"
FIRST_DATA_ROW = 4
FILL_FLAG = {"FFFFFF00": "open", "FFC6EFCE": "confirmed", "FFF8CBAD": "rejected"}
FLAG_RANK = {"confirmed": 1, "open": 2, "rejected": 3}  # the stronger flag wins on one field
TIER1 = {"206.882.251": "S00H4X-110", "206.882.252": "S00H4W-110",
         "206.885.967": "S00G0E-110", "206.885.968": "S00G0D-110"}
COMMENT_PREFIX = "From engineering Excel BOM 2026-09-23: "
# Which field each row's open question (R/S) is about, decided by the question text:
#   row | OEM no.     | question                                           | field
#   8   | 206.887.233 | 1 or 3 colors?                                     | paint.colour
#   13  | 206.883.607 | Painted or MIC? What color is RHO? Volume split?   | paint.painted
#   14  | 206.881.479 | 1 or 2 colors?                                     | paint.colour
#   15  | 206.881.793 | Painted VM0 or chrome? What color is VM0?          | paint.painted
# Rows 13 and 15 both ask first whether the part is painted at all, so both go
# on paint.painted; their colour cells (M) carry the colour comment. Default paint.colour.
QUESTION_FIELD = {"206.887.233": "paint.colour", "206.883.607": "paint.painted",
                  "206.881.479": "paint.colour", "206.881.793": "paint.painted"}


@dataclass
class Cell:
    value: object
    flag: Optional[str]


@dataclass
class Action:
    kind: str                 # tier1 | material_new | comment | flag
    part_id: int
    label: str                # part number, for the printout
    field_key: Optional[str] = None
    text: Optional[str] = None
    flag: Optional[str] = None
    legacy_text: Optional[str] = None  # the first import's wording of the same comment


def _flag(cell) -> Optional[str]:
    fill = cell.fill
    if fill is None or fill.fill_type != "solid":
        return None
    rgb = fill.fgColor.rgb if fill.fgColor is not None else None
    return FILL_FLAG.get(rgb) if isinstance(rgb, str) else None


def read_rows(path) -> list[dict]:
    ws = openpyxl.load_workbook(path, data_only=True)[SHEET]
    rows = []
    for r in ws.iter_rows(min_row=FIRST_DATA_ROW):
        cells = {get_column_letter(c.column): Cell(c.value, _flag(c)) for c in r if c.value not in (None, "")}
        if "B" in cells and "D" in cells:
            cells["_row"] = Cell(r[0].row, None)
            rows.append(cells)
    return rows


def _s(cells: dict, col: str) -> str:
    c = cells.get(col)
    return str(c.value).strip() if c is not None and c.value is not None else ""


def _f(cells: dict, col: str) -> Optional[str]:
    c = cells.get(col)
    return c.flag if c is not None else None


async def plan_actions(session: AsyncSession, project_id: int, rows: list[dict]) -> tuple[list, list]:
    parts = (await session.execute(select(Part).where(Part.project_id == project_id))).scalars().all()
    articles = {p.customer_part_number: p for p in parts if p.item_category == "article" and p.customer_part_number}
    tools = {p.part_number: p for p in parts if p.item_category == "tool"}
    comments: list[Action] = []
    seen: set = set()
    flags: dict = {}
    other: list[Action] = []
    warnings: list[str] = []

    def want_flag(part: Part, key: str, flag: Optional[str]):
        current = flags.get((part.id, key), (None, None))[1]
        if flag and FLAG_RANK[flag] > FLAG_RANK.get(current, 0):
            flags[(part.id, key)] = (part, flag)

    def comment(part: Part, key: str, text: str, flag: Optional[str] = None, legacy: Optional[str] = None):
        if (part.id, key, text) not in seen:
            seen.add((part.id, key, text))
            comments.append(Action("comment", part.id, part.part_number, key, COMMENT_PREFIX + text,
                                   legacy_text=legacy or text))
        want_flag(part, key, flag)

    for cells in rows:
        row_no = cells["_row"].value
        oem = _s(cells, "D")
        article = articles.get(oem)
        if article is None:
            warnings.append(f"row {row_no}: no article with OEM number {oem}")
            continue
        tool = tools.get(_s(cells, "B"))
        if tool is None:
            warnings.append(f"row {row_no}: no tool {_s(cells, 'B')}")

        if oem in TIER1 and not article.tier1_part_number:
            other.append(Action("tier1", article.id, article.part_number, text=TIER1[oem]))
        if _s(cells, "I") and article.material_source is None:
            other.append(Action("material_new", article.id, article.part_number, text=_s(cells, "I")))
        if _s(cells, "J") or _s(cells, "K"):
            comment(article, "part.material",
                    f"Proposed resin: {_s(cells, 'J') or 'none'}. Resin status: {_s(cells, 'K') or 'none'}",
                    _f(cells, "K") or _f(cells, "J"))
        excel = _cavities(cells)
        if tool is not None and excel is None and _s(cells, "C"):
            warnings.append(f"row {row_no}: cavities '{_s(cells, 'C')}' is not a number, skipped")
        if tool is not None and excel is not None:
            check = "Check against RFQ 26 loop 37; PLM not changed."
            if tool.tool_cavities is not None and excel != tool.tool_cavities:
                comment(tool, "tool.cavities", f"{excel} cavities, PLM has {tool.tool_cavities}. {check}", "open",
                        legacy=f"Excel BOM 2026-09-23 says {excel} cavities, PLM has {tool.tool_cavities}. {check}")
            elif _f(cells, "C") == "open":
                comment(tool, "tool.cavities", f"cavities ({excel}) marked as open.", "open",
                        legacy=f"Excel BOM 2026-09-23 marks the cavities ({excel}) as open.")
        if _f(cells, "F") == "open":
            comment(article, "part.name", f"Designation on the drawing: {_s(cells, 'F')}", "open")
        if _f(cells, "L"):
            comment(article, "paint.painted", f"Painted: {_s(cells, 'L')}", _f(cells, "L"))
        if _f(cells, "M"):
            comment(article, "paint.colour", f"Colour: {_s(cells, 'M')}", _f(cells, "M"))
        if _f(cells, "N"):
            comment(article, "paint.colour", f"MIC / colour change: {_s(cells, 'N')}", _f(cells, "N"))
        if _s(cells, "R") or _s(cells, "S"):
            key = QUESTION_FIELD.get(oem, "paint.colour")
            if _s(cells, "R"):
                comment(article, key, f"Question: {_s(cells, 'R')}")
            if _s(cells, "S"):
                comment(article, key, f"Answer: {_s(cells, 'S')}")
            want_flag(article, key, _f(cells, "S") or _f(cells, "R"))
        grain = [f"{label} {_s(cells, col)}" for col, label in
                 (("T", "drawing"), ("U", "RFQ 26 frozen"), ("V", "gloss"))
                 if _s(cells, col)]
        if grain or _s(cells, "W") or _s(cells, "X"):
            text = "Grain: " + ", ".join(grain) + "."
            if _s(cells, "W"):
                text += f" Question: {_s(cells, 'W')}"
            if _s(cells, "X"):
                text += f" Answer: {_s(cells, 'X')}"
            grain_flag = "open" if any(_f(cells, c) == "open" for c in "TUVWX") else None
            comment(article, "revision.level", text, grain_flag)

    flag_actions = [Action("flag", part.id, part.part_number, key[1], flag=flag)
                    for key, (part, flag) in flags.items()]
    pending = [a for a in other + comments + flag_actions if await _pending(session, a)]
    return pending, warnings


def _cavities(cells: dict) -> Optional[int]:
    try:
        f = float(_s(cells, "C").replace(",", "."))
    except ValueError:
        return None
    return int(f) if f.is_integer() else None


async def _pending(session: AsyncSession, a: Action) -> bool:
    """True when applying the action would write something. Plan and apply share it."""
    part = await session.get(Part, a.part_id)
    if a.kind == "tier1":
        return not part.tier1_part_number
    if a.kind == "material_new":
        return part.material_source is None
    note = await FieldNoteService.get(session, part.id, a.field_key)
    if a.kind == "comment":
        bodies = {c.body for c in note.comments} if note is not None else set()
        return a.text not in bodies and (a.legacy_text is None or a.legacy_text not in bodies)
    return note is None or note.flag_status != a.flag


async def apply_actions(session: AsyncSession, actions: list, user_id: int) -> int:
    written = 0
    for a in actions:
        if not await _pending(session, a):
            continue
        part = await session.get(Part, a.part_id)
        if a.kind == "tier1":
            old = part.tier1_part_number
            part.tier1_part_number = a.text
            await ChangelogService.log_action(
                session, part_id=part.id, action="metadata_updated",
                action_description=f"Tier 1 part number set to {a.text} from the 1994 Excel BOM 2026-09-23",
                performed_by=user_id, field_name="tier1_part_number", old_value=old, new_value=a.text)
        elif a.kind == "material_new":
            await PartMaterialService.set_new(session, part, a.text, user_id)
        elif a.kind == "comment":
            await FieldNoteService.add_comment(session, part, a.field_key, a.text, user_id)
        elif a.kind == "flag":
            await FieldNoteService.set_flag(session, part, a.field_key, a.flag, user_id)
        written += 1
    await session.flush()
    return written


def _print(actions: list, warnings: list) -> None:
    for w in warnings:
        print(f"   ! {w}")
    for a in actions:
        if a.kind == "comment":
            print(f"   comment  {a.label:<16} {a.field_key:<22} {a.text}")
        elif a.kind == "flag":
            print(f"   flag     {a.label:<16} {a.field_key:<22} {a.flag}")
        else:
            print(f"   {a.kind:<8} {a.label:<16} {'':<22} {a.text}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, required=True, help="PLM user id the notes are written as")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.xlsx)
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as s:
            project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
            actions, warnings = await plan_actions(s, project.id, rows)
            print(f"{len(rows)} Excel rows, {len(actions)} actions for project {project.code} (id {project.id})")
            _print(actions, warnings)
            if not actions:
                print("Nothing to do: everything in the Excel is already in PLM.")
                return
            if not args.apply:
                print("DRY RUN: nothing written. Rerun with --apply after checking the list.")
                return
            written = await apply_actions(s, actions, args.user)
            await s.commit()
            print(f"Applied: {written} changes written.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
