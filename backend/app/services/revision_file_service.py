"""One code path for a file landing on a revision: validate, write, hash,
convert STEP to glTF, record, log. Used by the single-file upload endpoint
and by the customer package receive."""
from __future__ import annotations

import hashlib
import logging
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import PartRevision, RevisionFile
from app.services.part_service import ChangelogService
from app.utils.cad_converter import convert_step_to_gltf

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Extension -> (file_type, cad_format) mapping. PDFs default to "document";
# callers can override with the file_type form field (e.g. "drawing").
EXTENSION_MAP = {
    ".step": ("cad", "step"),
    ".stp": ("cad", "step"),
    ".iges": ("cad", "iges"),
    ".igs": ("cad", "iges"),
    ".stl": ("cad", "stl"),
    ".jt": ("cad", "jt"),
    ".catpart": ("cad", "catia"),
    ".catproduct": ("cad", "catia"),
    ".dxf": ("drawing", None),
    ".dwg": ("drawing", None),
    ".pdf": ("document", None),
    ".png": ("picture", None),
    ".jpg": ("picture", None),
    ".jpeg": ("picture", None),
    ".gif": ("picture", None),
    ".webp": ("picture", None),
    ".docx": ("document", None),
    ".xlsx": ("document", None),
    ".pptx": ("document", None),
    ".txt": ("document", None),
    ".md": ("document", None),
    ".csv": ("document", None),
}

VALID_FILE_TYPES = {"cad", "drawing", "picture", "document", "test_result"}

MIME_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


class UnsupportedFile(ValueError):
    """Extension, file type or size not accepted."""


def uploads_dir(revision_id: int) -> str:
    return os.path.join(os.getcwd(), "uploads", "revisions", str(revision_id))


def remove_files(paths: list[str]) -> None:
    """Best-effort delete of files written for a revision file that did not
    make it into the database."""
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def classify(filename: str, file_type: str | None = None) -> tuple[str, str, str | None]:
    """(ext, resolved file_type, cad_format) or raise UnsupportedFile."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in EXTENSION_MAP:
        raise UnsupportedFile(f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(EXTENSION_MAP))}")
    inferred_type, cad_format = EXTENSION_MAP[ext]
    resolved = file_type or inferred_type
    if resolved not in VALID_FILE_TYPES:
        raise UnsupportedFile(f"Invalid file_type '{resolved}'. Valid: {', '.join(sorted(VALID_FILE_TYPES))}")
    return ext, resolved, cad_format


async def store_revision_file(session: AsyncSession, revision: PartRevision, filename: str, contents: bytes,
                              uploaded_by: int, content_type: str | None = None,
                              file_type: str | None = None, kind: str | None = None,
                              note: str | None = None) -> RevisionFile:
    ext, resolved_type, cad_format = classify(filename, file_type)
    if len(contents) > MAX_FILE_SIZE:
        raise UnsupportedFile("File size must be under 100MB")
    target_dir = uploads_dir(revision.id)
    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, f"{uuid.uuid4().hex}{ext}")
    with open(file_path, "wb") as fh:
        fh.write(contents)
    # everything past the disk write is undone on failure: a file without its
    # row is invisible to the application and would leak on every retry
    written = [file_path]
    try:
        viewer_file_path = None
        if cad_format == "step":
            gltf_path = os.path.join(target_dir, f"{uuid.uuid4().hex}.glb")
            written.append(gltf_path)
            try:
                if await convert_step_to_gltf(file_path, gltf_path):
                    viewer_file_path = gltf_path
                else:
                    logger.warning(f"glTF conversion failed for {filename}")
            except Exception as e:  # conversion is best effort
                logger.error(f"glTF conversion error for {filename}: {e}", exc_info=True)
        rev_file = RevisionFile(
            revision_id=revision.id, filename=filename, file_type=resolved_type,
            mime_type=content_type or MIME_MAP.get(ext, "application/octet-stream"),
            file_size=len(contents), file_path=file_path, cad_format=cad_format,
            kind=(kind or "").strip().upper() or None, note=(note or "").strip() or None,
            file_hash=hashlib.sha256(contents).hexdigest(),
            viewer_file_path=viewer_file_path, has_viewer=viewer_file_path is not None,
            uploaded_by=uploaded_by,
        )
        session.add(rev_file)
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=revision.part_id, revision_id=revision.id, action="file_uploaded",
            action_description=f"Uploaded {resolved_type} file '{filename}' to {revision.revision_name}",
            performed_by=uploaded_by, file_id=rev_file.id)
    except Exception:
        remove_files(written)
        raise
    return rev_file
