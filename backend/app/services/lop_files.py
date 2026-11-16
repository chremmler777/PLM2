"""Files attached to LOP lines: storage, listing, soft delete.

One blob per row under uploads/lop/<project_id>/<line_id>/<uuid>_<name>, the
same layout and limits as the SEP item files (sep_file_service). The project
team and the Project Manager attach; everyone who reads the line reads its
files; the PM removes any file, everybody else only their own. Every attach
and remove is a line event, so it shows in the line's history.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import User
from app.models.lop import LopFile, LopLine
from app.services.lop_service import LopError, LopForbidden, LopNotFound, LopService, _iso, _uname
from app.services.sep_file_service import (
    CHUNK_SIZE, MAX_FILE_SIZE, MAX_FILES_PER_REQUEST, EmptyFilename, _safe_name,
)

logger = logging.getLogger(__name__)


class LopFileTooLarge(LopError):
    status_code = 413


def _dir(project_id: int, line_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "lop", str(project_id), str(line_id))


def _discard(paths: list[str]) -> None:
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            logger.warning("Could not remove orphaned LOP upload %s", path)


async def _may_attach(session: AsyncSession, user: User, line: LopLine) -> bool:
    return (await LopService.can_manage(session, user, line.project_id)
            or await LopService.is_team_member(session, user, line.project_id))


async def store(session: AsyncSession, user: User, line_id: int, files: list) -> list[LopFile]:
    """Stream every upload to disk, hash it, insert its row. A rejected batch
    (too many, one too large, an empty name) leaves nothing on disk."""
    line = await LopService.get_line(session, user, line_id)
    if not await _may_attach(session, user, line):
        raise LopForbidden("Only the project team attaches files to a line")
    if not files:
        raise LopError("No file was sent")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise LopFileTooLarge(f"Too many files in one upload (max {MAX_FILES_PER_REQUEST})")
    target = _dir(line.project_id, line.id)
    os.makedirs(target, exist_ok=True)
    written: list[str] = []
    rows: list[LopFile] = []
    try:
        for f in files:
            try:
                name = _safe_name(f.filename)
            except EmptyFilename as e:
                raise LopError(str(e))
            path = os.path.join(target, f"{uuid.uuid4().hex}_{name}")
            digest, size = hashlib.sha256(), 0
            written.append(path)
            with open(path, "wb") as fh:
                while chunk := await f.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > MAX_FILE_SIZE:
                        raise LopFileTooLarge(
                            f"File {name} is too large (max {MAX_FILE_SIZE // (1024 * 1024)} MB)")
                    digest.update(chunk)
                    fh.write(chunk)
            row = LopFile(line_id=line.id, project_id=line.project_id, filename=name,
                          stored_path=path, content_type=(f.content_type or "application/octet-stream")[:100],
                          size_bytes=size, sha256=digest.hexdigest(), uploaded_by=user.id)
            session.add(row)
            rows.append(row)
            LopService._event(session, line, user, "file", None, name)
        LopService._touch(line, user)
        await LopService.mark_in_meeting(session, line)
        await session.commit()
    except Exception:
        await session.rollback()
        _discard(written)
        raise
    for row in rows:
        await session.refresh(row)
    return rows


async def listing(session: AsyncSession, user: User, line_id: int) -> list[dict]:
    """The line's live files, newest first."""
    line = await LopService.get_line(session, user, line_id)
    rows = list((await session.execute(
        select(LopFile).where(LopFile.line_id == line.id, LopFile.is_deleted.is_(False))
        .order_by(LopFile.uploaded_at.desc(), LopFile.id.desc()))).scalars().all())
    return await dicts(session, user, line, rows)


async def dicts(session: AsyncSession, user: User, line: LopLine, rows: list[LopFile]) -> list[dict]:
    manage = await LopService.can_manage(session, user, line.project_id)
    uids = {r.uploaded_by for r in rows if r.uploaded_by}
    users = {u.id: u for u in (await session.execute(
        select(User).where(User.id.in_(uids)))).scalars().all()} if uids else {}
    return [{"id": r.id, "line_id": r.line_id, "filename": r.filename,
             "content_type": r.content_type, "size_bytes": r.size_bytes,
             "uploaded_by": r.uploaded_by, "uploaded_by_name": _uname(users.get(r.uploaded_by)),
             "uploaded_at": _iso(r.uploaded_at),
             "can_delete": manage or r.uploaded_by == user.id} for r in rows]


async def get(session: AsyncSession, user: User, line_id: int, file_id: int) -> tuple[LopLine, LopFile]:
    """One live file, but only if it really sits on that line."""
    line = await LopService.get_line(session, user, line_id)
    row = (await session.execute(select(LopFile).where(
        LopFile.id == file_id, LopFile.line_id == line.id,
        LopFile.is_deleted.is_(False)))).scalar_one_or_none()
    if row is None:
        raise LopNotFound("File not found")
    return line, row


async def remove(session: AsyncSession, user: User, line_id: int, file_id: int) -> None:
    """Soft delete: the row is flagged, the blob stays."""
    line, row = await get(session, user, line_id, file_id)
    if not (await LopService.can_manage(session, user, line.project_id) or row.uploaded_by == user.id):
        raise LopForbidden("Only the Project Manager removes a file somebody else attached")
    row.is_deleted, row.deleted_at, row.deleted_by = True, datetime.utcnow(), user.id
    LopService._event(session, line, user, "file", row.filename, None)
    LopService._touch(line, user)
    await LopService.mark_in_meeting(session, line)
    await session.commit()
