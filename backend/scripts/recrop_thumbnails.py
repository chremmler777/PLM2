"""Re-crop existing part thumbnails so the part fills the picture.

The automatic 3D snapshot used to copy the whole wide viewer, leaving the part
small in the middle of the thumbnail. The viewer now crops to the part
(frontend/src/lib/canvasCapture.ts); this does the same to the thumbnails
already stored: background = the top-left pixel, part = every pixel that
differs by more than TOLERANCE, square crop with MARGIN of the long side on
each edge, filled with the background, at most MAX_SIDE px.

Thumbnails whose part already fills most of the frame are left alone. Every
original is copied to --backup before anything is replaced. Writes go through
thumbnail_service.set_thumbnail (one changelog row each; not a mail event).
Dry run unless --apply.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/recrop_thumbnails.py --backup /app/uploads/_thumb-backup-YYYYMMDD [--project 1994] [--apply]
"""
import argparse
import asyncio
import io
import os
import shutil

from PIL import Image, ImageChops
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part
from app.services.thumbnail_service import set_thumbnail

TOLERANCE = 12
MARGIN = 0.08
MAX_SIDE = 400
TIGHT_ENOUGH = 0.7  # part's long side already >= 70% of the frame's: leave it


def recrop(raw: bytes):
    """(new PNG bytes, fill ratio before) or (None, ratio) when no crop helps."""
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = img.size
    bg = img.getpixel((0, 0))
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg)).convert("L")
    box = diff.point(lambda v: 255 if v > TOLERANCE else 0).getbbox()
    if box is None:
        return None, 0.0
    x0, y0, x1, y1 = box  # x1/y1 exclusive
    long_part = max(x1 - x0, y1 - y0)
    ratio = long_part / max(w, h)
    if ratio >= TIGHT_ENOUGH:
        return None, ratio
    side = round(long_part * (1 + 2 * MARGIN))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left, top = round(cx - side / 2), round(cy - side / 2)
    canvas = Image.new("RGB", (side, side), bg)
    canvas.paste(img.crop((max(left, 0), max(top, 0), min(left + side, w), min(top + side, h))),
                 (max(-left, 0), max(-top, 0)))
    if side > MAX_SIDE:
        canvas = canvas.resize((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue(), ratio


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
            new, ratio = recrop(raw)
            verdict = "re-crop" if new else "keep"
            print(f"{code} {part.part_number:<20} part fills {ratio:4.0%} of the frame -> {verdict}")
            if not new or not args.apply:
                continue
            os.makedirs(args.backup, exist_ok=True)
            shutil.copy2(part.thumbnail_path, os.path.join(
                args.backup, f"{part.id}-{os.path.basename(part.thumbnail_path)}"))
            await set_thumbnail(s, part, new, args.user, source_note="re-cropped to the part")
            await s.commit()
            changed += 1
        print(f"APPLIED - {changed} re-cropped." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
