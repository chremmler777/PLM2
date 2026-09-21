"""Files attached to SEP work items: storage, listing, soft delete, counts.

One blob per row under uploads/sep/<project_id>/<item_id>/<uuid>_<name>, the
same layout the change attachments use. Deletes are soft (the row keeps the
audit trail honest) and never touch the blob.

Everything the router needs comes from here, including the project-wide
grouped listing and the per-item file counts the SEP project payload folds in
— both as a single grouped query, never one query per item.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sep import SepGate, SepItemFile, SepWorkItem

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB per file
MAX_FILES_PER_REQUEST = 20
CHUNK_SIZE = 1024 * 1024  # stream in 1 MiB bites; never hold a whole upload
MAX_FILENAME_LEN = 200    # filename column is 255, and the path gets a uuid prefix


class SepFileError(Exception):
    """Upload rejected; nothing of this batch survives on disk."""


class FileTooLarge(SepFileError):
    pass


class TooManyFiles(SepFileError):
    pass


class EmptyFilename(SepFileError):
    pass


def _safe_name(raw: str | None) -> str:
    """Basename, trimmed, and short enough for the column - extension kept."""
    name = os.path.basename(raw or "").strip()
    if not name:
        raise EmptyFilename("Every file needs a filename")
    if len(name) > MAX_FILENAME_LEN:
        stem, ext = os.path.splitext(name)
        ext = ext[:MAX_FILENAME_LEN]          # a pathological "extension" cannot win
        name = stem[:MAX_FILENAME_LEN - len(ext)] + ext
    return name


class SepFileService:

    @staticmethod
    def _dir(project_id: int, item_id: int) -> str:
        return os.path.join(os.getcwd(), "uploads", "sep", str(project_id), str(item_id))

    @staticmethod
    def _discard(paths: list[str]) -> None:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                logger.warning("Could not remove orphaned SEP upload %s", path)

    @staticmethod
    async def store_files(db: AsyncSession, *, item: SepWorkItem, files: list,
                          user_id: int) -> list[SepItemFile]:
        """Stream every upload to disk and insert its row.

        Each file is copied a chunk at a time and hashed as it goes, so a
        request never holds an upload in memory, and it is abandoned the moment
        it grows past the cap. Whatever the failure - too many files, one file
        too large, an empty name, a failing insert - every blob written for the
        batch is removed again, so a rejected batch leaves nothing behind.
        """
        if len(files) > MAX_FILES_PER_REQUEST:
            raise TooManyFiles(
                f"Too many files in one upload (max {MAX_FILES_PER_REQUEST})")

        target_dir = SepFileService._dir(item.project_id, item.id)
        os.makedirs(target_dir, exist_ok=True)

        written: list[str] = []
        rows: list[SepItemFile] = []
        try:
            for f in files:
                safe_name = _safe_name(f.filename)
                stored_path = os.path.join(target_dir, f"{uuid.uuid4().hex}_{safe_name}")
                digest = hashlib.sha256()
                size = 0
                written.append(stored_path)
                with open(stored_path, "wb") as fh:
                    while chunk := await f.read(CHUNK_SIZE):
                        size += len(chunk)
                        if size > MAX_FILE_SIZE:
                            raise FileTooLarge(f"File {safe_name} exceeds 100MB")
                        digest.update(chunk)
                        fh.write(chunk)
                row = SepItemFile(
                    item_id=item.id,
                    project_id=item.project_id,
                    filename=safe_name,
                    stored_path=stored_path,
                    content_type=f.content_type or "application/octet-stream",
                    size_bytes=size,
                    sha256=digest.hexdigest(),
                    uploaded_by=user_id,
                )
                db.add(row)
                rows.append(row)
            await db.flush()
        except Exception:
            SepFileService._discard(written)
            raise
        return rows

    @staticmethod
    async def list_item_files(db: AsyncSession, *, item_id: int) -> list[SepItemFile]:
        """Non-deleted files on one item, newest first."""
        result = await db.execute(
            select(SepItemFile)
            .where(SepItemFile.item_id == item_id, SepItemFile.is_deleted.is_(False))
            .order_by(SepItemFile.uploaded_at.desc(), SepItemFile.id.desc())
        )
        return list(result.scalars())

    @staticmethod
    async def get_file(db: AsyncSession, *, item_id: int, file_id: int) -> SepItemFile | None:
        """One live file, but only if it really sits on that item."""
        result = await db.execute(
            select(SepItemFile).where(
                SepItemFile.id == file_id,
                SepItemFile.item_id == item_id,
                SepItemFile.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def soft_delete(db: AsyncSession, *, file: SepItemFile, user_id: int) -> SepItemFile:
        """Mark the row deleted; the blob stays on disk."""
        from datetime import datetime
        file.is_deleted = True
        file.deleted_at = datetime.utcnow()
        file.deleted_by = user_id
        await db.flush()
        return file

    @staticmethod
    async def project_files(db: AsyncSession, *, project_id: int) -> list[dict]:
        """Every live file in a project, grouped gate -> item, in one query.

        Only gates and items that actually carry files show up; gates come in
        `seq` order, items in `item_no` order, files newest first.
        """
        result = await db.execute(
            select(SepGate, SepWorkItem, SepItemFile)
            .join(SepWorkItem, SepWorkItem.gate_id == SepGate.id)
            .join(SepItemFile, SepItemFile.item_id == SepWorkItem.id)
            .where(SepGate.project_id == project_id, SepItemFile.is_deleted.is_(False))
            .order_by(SepGate.seq, SepWorkItem.item_no,
                      SepItemFile.uploaded_at.desc(), SepItemFile.id.desc())
        )
        gates: dict[int, dict] = {}
        items: dict[int, dict] = {}
        for gate, item, file in result.all():
            group = gates.get(gate.id)
            if group is None:
                group = gates[gate.id] = {
                    "gate_id": gate.id, "gate_code": gate.code,
                    "phase_en": gate.phase_en, "seq": gate.seq, "items": [],
                }
            entry = items.get(item.id)
            if entry is None:
                entry = items[item.id] = {
                    "item_id": item.id, "item_no": item.item_no,
                    "title_en": item.title_en, "department": item.department, "files": [],
                }
                group["items"].append(entry)
            entry["files"].append(file)
        return list(gates.values())

    @staticmethod
    async def file_counts(db: AsyncSession, project_id: int) -> dict[int, int]:
        """item_id -> number of live files, for a whole project in one query."""
        result = await db.execute(
            select(SepItemFile.item_id, func.count(SepItemFile.id))
            .where(SepItemFile.project_id == project_id, SepItemFile.is_deleted.is_(False))
            .group_by(SepItemFile.item_id)
        )
        return {item_id: count for item_id, count in result.all()}
