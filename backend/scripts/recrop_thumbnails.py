"""Re-crop existing part thumbnails so the part fills the picture.

The automatic 3D snapshot used to copy the whole wide viewer, leaving the part
small in the middle of the thumbnail. The viewer now crops to the part
(frontend/src/lib/canvasCapture.ts) and set_thumbnail frames every new
thumbnail (thumbnail_service.frame_to_part); this applies the same framing to
the thumbnails already stored. Ones whose part already fills the frame are
left alone. Every
original is copied to --backup before anything is replaced. Writes go through
thumbnail_service.set_thumbnail (one changelog row each; not a mail event).
Dry run unless --apply.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/recrop_thumbnails.py --backup /app/uploads/_thumb-backup-YYYYMMDD [--project 1994] [--apply]
"""
import argparse
import asyncio
import os
import shutil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.thumbnail_service import frame_to_part, set_thumbnail

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", required=True)
    ap.add_argument("--project", help="only this project code")
    ap.add_argument("--part", type=int, action="append", help="only these part ids")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        q = select(Part, Project.code).join(Project, Project.id == Part.project_id).where(
            Part.thumbnail_path.is_not(None)).order_by(Project.code, Part.part_number)
        if args.project:
            q = q.where(Project.code == args.project)
        if args.part:
            q = q.where(Part.id.in_(args.part))
        changed = 0
        for part, code in (await s.execute(q)).all():
            if not os.path.exists(part.thumbnail_path):
                print(f"{code} {part.part_number}: file missing, skip")
                continue
            with open(part.thumbnail_path, "rb") as fh:
                raw = fh.read()
            new, ratio = frame_to_part(raw)
            verdict = "re-crop" if new else "keep"
            print(f"{code} {part.part_number:<20} part fills {ratio:4.0%} of the frame -> {verdict}")
            if not new or not args.apply:
                continue
            os.makedirs(args.backup, exist_ok=True)
            shutil.copy2(part.thumbnail_path, os.path.join(
                args.backup, f"{part.id}-{os.path.basename(part.thumbnail_path)}"))
            await set_thumbnail(s, part, raw, args.user, source_note="re-cropped to the part")
            await s.commit()
            changed += 1
        print(f"APPLIED - {changed} re-cropped." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
