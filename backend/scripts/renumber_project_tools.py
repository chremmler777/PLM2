"""Renumber project-coded tools from '<code>-<n>' to '<code><nn>'.

1994-1 -> 199401, 1994-10 -> 199410. Only parts in item_category 'tool'
whose prefix is their own project's code are touched, so legacy tools
('3450') and gauges ('0745-40') stay. Equipment numbered under a renamed
tool ('1994-1-41') follows it ('199401-41'). Dry run unless --apply.

Usage (inside the backend container):
    python scripts/renumber_project_tools.py [--apply] [--project 1994]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import AsyncSessionLocal  # noqa: E402
from app.models.entities import Project  # noqa: E402
from app.models.part import Part  # noqa: E402
from app.services.part_service import ChangelogService  # noqa: E402

TOOL_RE = re.compile(r"^(?P<code>.+)-(?P<n>\d{1,2})$")


async def plan(session, project_code: str | None) -> list[tuple[Part, str]]:
    projects = {p.id: p.code for p in (await session.execute(select(Project))).scalars().all()}
    parts = (await session.execute(select(Part).order_by(Part.part_number))).scalars().all()
    existing = {p.part_number for p in parts}
    renames: dict[str, str] = {}
    out: list[tuple[Part, str]] = []
    for p in parts:
        if p.item_category != "tool":
            continue
        m = TOOL_RE.match(p.part_number)
        if not m or m.group("code") != projects.get(p.project_id):
            continue
        if project_code and m.group("code") != project_code:
            continue
        new = f"{m.group('code')}{int(m.group('n')):02d}"
        if new in existing or new in renames.values():
            raise SystemExit(f"Collision: {p.part_number} -> {new} already exists")
        renames[p.part_number] = new
        out.append((p, new))
    # equipment under a renamed tool: '<old>-<op>' -> '<new>-<op>'
    for p in parts:
        head, sep, tail = p.part_number.rpartition("-")
        if sep and head in renames and re.fullmatch(r"\d{2}", tail):
            out.append((p, f"{renames[head]}-{tail}"))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--project", help="only this project code")
    args = ap.parse_args()
    async with AsyncSessionLocal() as session:
        todo = await plan(session, args.project)
        for p, new in todo:
            print(f"{p.part_number:>12} -> {new:<10} {p.item_category:<10} {p.name}")
        print(f"{len(todo)} part(s) {'renamed' if args.apply else 'would be renamed (dry run, pass --apply)'}")
        if not args.apply:
            return 0
        for p, new in todo:
            old = p.part_number
            p.part_number = new
            await ChangelogService.log_action(
                session, part_id=p.id, action="renumbered",
                action_description=f"Part number {old} -> {new} (project-coded tool numbering)",
                performed_by=1, field_name="part_number", old_value=old, new_value=new)
        await session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
