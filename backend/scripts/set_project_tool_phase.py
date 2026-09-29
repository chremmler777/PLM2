"""Move every tool of a project to its next lifecycle phase (tools run
rfq -> dfm -> preseries -> series), through RevisionService.set_lifecycle_phase
so each move is one changelog entry. Tools already in the target phase are
skipped; a tool that cannot reach it in one step is reported and left alone.
Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/set_project_tool_phase.py --project 1994 --phase dfm [--apply]
"""
import argparse
import asyncio
import os
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import TOOL_NEXT_PHASE, Part
from app.services.part_service import RevisionService


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--phase", required=True, choices=sorted(set(TOOL_NEXT_PHASE.values())))
    ap.add_argument("--effective", default=date.today().isoformat())
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        tools = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.item_category == "tool").order_by(Part.part_number))).scalars().all()
        moves = []
        for t in tools:
            if t.lifecycle_phase == args.phase:
                continue
            if TOOL_NEXT_PHASE.get(t.lifecycle_phase) != args.phase:
                print(f"   ! {t.part_number} is in {t.lifecycle_phase}, not one step from {args.phase}: left alone")
                continue
            moves.append(t)
        print(f"== TOOL PHASE -> {args.phase} ({len(moves)} tools, effective {args.effective})")
        for t in moves:
            print(f"   {t.part_number:<8} {t.lifecycle_phase} -> {args.phase}")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return
        for t in moves:
            await RevisionService.set_lifecycle_phase(s, t.id, args.phase, date.fromisoformat(args.effective),
                                                     created_by=args.user)
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
