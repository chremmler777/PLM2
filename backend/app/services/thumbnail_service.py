"""One code path for "a part gets a thumbnail image": sniff the bytes,
write/replace/clear the file, log the change. Used by the
PUT/GET/DELETE /parts/{id}/thumbnail endpoints and by the RFQ2 import
script (scripts/import_1994_thumbnails.py), so there is exactly one place
that decides what counts as an acceptable image."""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime

from PIL import Image, ImageChops, UnidentifiedImageError

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part
from app.services.part_service import ChangelogService

MAX_THUMBNAIL_SIZE = 2 * 1024 * 1024  # 2MB

MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


class InvalidThumbnail(ValueError):
    """Not a PNG/JPEG/WEBP by magic bytes, or over the size limit."""


class ThumbnailTooLarge(InvalidThumbnail):
    """Over MAX_THUMBNAIL_SIZE."""


def sniff_image(contents: bytes) -> tuple[str, str]:
    """(ext, media_type) detected from magic bytes only - never from the
    filename or the client's declared content type. Raises InvalidThumbnail
    (ThumbnailTooLarge for the size case) if it is not an accepted image."""
    if len(contents) > MAX_THUMBNAIL_SIZE:
        raise ThumbnailTooLarge("Thumbnail must be 2MB or smaller")
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", MEDIA_TYPES["png"]
    if contents.startswith(b"\xff\xd8\xff"):
        return "jpg", MEDIA_TYPES["jpg"]
    if len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return "webp", MEDIA_TYPES["webp"]
    raise InvalidThumbnail("File must be a PNG, JPEG or WEBP image")


#: Framing: background = the top-left pixel, part = pixels that differ by
#: more than FRAME_TOLERANCE. The part is cut out as a square with
#: FRAME_MARGIN of its long side on each edge (at most FRAME_MAX_SIDE px) and
#: the background becomes white. A picture whose part already spans
#: FRAME_TIGHT_ENOUGH of the frame is not cropped, only whitened.
FRAME_TOLERANCE = 12
FRAME_MARGIN = 0.08
FRAME_MAX_SIDE = 400
FRAME_TIGHT_ENOUGH = 0.7
WHITE = (255, 255, 255)


def frame_to_part(contents: bytes) -> tuple[bytes | None, float]:
    """The image framed on the part over a white background (PNG bytes), or
    None when nothing would change (already tight and white, or nothing
    stands out from the background). Second value: how much of the frame's
    long side the part spanned."""
    try:
        img = Image.open(io.BytesIO(contents)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None, 0.0
    w, h = img.size
    bg = img.getpixel((0, 0))
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg)).convert("L")
    part_mask = diff.point(lambda v: 255 if v > FRAME_TOLERANCE else 0)
    box = part_mask.getbbox()
    if box is None:
        return None, 0.0
    x0, y0, x1, y1 = box  # x1/y1 exclusive
    long_part = max(x1 - x0, y1 - y0)
    ratio = long_part / max(w, h)
    crop = ratio < FRAME_TIGHT_ENOUGH
    if not crop and bg == WHITE:
        return None, ratio
    if bg != WHITE:
        img = Image.composite(img, Image.new("RGB", img.size, WHITE), part_mask)
    if crop:
        side = round(long_part * (1 + 2 * FRAME_MARGIN))
        left = round((x0 + x1) / 2 - side / 2)
        top = round((y0 + y1) / 2 - side / 2)
        canvas = Image.new("RGB", (side, side), WHITE)
        canvas.paste(img.crop((max(left, 0), max(top, 0), min(left + side, w), min(top + side, h))),
                     (max(-left, 0), max(-top, 0)))
        img = canvas
    if max(img.size) > FRAME_MAX_SIDE:
        img.thumbnail((FRAME_MAX_SIDE, FRAME_MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue(), ratio


def thumbnails_dir(part_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "thumbnails", str(part_id))


def media_type_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    return MEDIA_TYPES.get(ext, "application/octet-stream")


async def set_thumbnail(session: AsyncSession, part: Part, contents: bytes, user_id: int,
                        source_note: str | None = None) -> Part:
    """Validate `contents`, write it as the part's new thumbnail, remove the
    old file (if any) once the new one is committed, and log one changelog
    entry. Raises InvalidThumbnail without touching disk or the part. A
    part that sits small in a wide frame is cropped to fill the picture
    (frame_to_part), whatever the source: viewer snapshot, upload, import."""
    ext, _media_type = sniff_image(contents)
    framed, _ratio = frame_to_part(contents)
    if framed is not None:
        contents, ext = framed, "png"
    target_dir = thumbnails_dir(part.id)
    os.makedirs(target_dir, exist_ok=True)
    new_path = os.path.join(target_dir, f"{uuid.uuid4().hex}.{ext}")
    with open(new_path, "wb") as fh:
        fh.write(contents)

    old_path = part.thumbnail_path
    try:
        part.thumbnail_path = new_path
        part.thumbnail_updated_at = datetime.utcnow()
        await ChangelogService.log_action(
            session, part_id=part.id, action="thumbnail_updated",
            action_description=f"Thumbnail updated{f' ({source_note})' if source_note else ''}",
            performed_by=user_id,
        )
        await session.flush()
    except Exception:
        try:
            os.remove(new_path)
        except OSError:
            pass
        raise

    if old_path and old_path != new_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass
    return part


async def clear_thumbnail(session: AsyncSession, part: Part, user_id: int) -> Part:
    """Clear the thumbnail fields and remove the file on disk. No-op (still
    logs) if there was none."""
    old_path = part.thumbnail_path
    part.thumbnail_path = None
    part.thumbnail_updated_at = None
    await ChangelogService.log_action(
        session, part_id=part.id, action="thumbnail_updated",
        action_description="Thumbnail removed", performed_by=user_id,
    )
    await session.flush()
    if old_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass
    return part
