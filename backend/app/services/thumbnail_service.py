"""One code path for "a part gets a thumbnail image": sniff the bytes,
write/replace/clear the file, log the change. Used by the
PUT/GET/DELETE /parts/{id}/thumbnail endpoints and by the RFQ2 import
script (scripts/import_1994_thumbnails.py), so there is exactly one place
that decides what counts as an acceptable image."""
from __future__ import annotations

import os
import uuid
from datetime import datetime

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


def thumbnails_dir(part_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "thumbnails", str(part_id))


def media_type_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    return MEDIA_TYPES.get(ext, "application/octet-stream")


async def set_thumbnail(session: AsyncSession, part: Part, contents: bytes, user_id: int,
                        source_note: str | None = None) -> Part:
    """Validate `contents`, write it as the part's new thumbnail, remove the
    old file (if any) once the new one is committed, and log one changelog
    entry. Raises InvalidThumbnail without touching disk or the part."""
    ext, _media_type = sniff_image(contents)
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
