"""Comments and a flag on one field of a part: the worksheet's way to find
discrepancies between drawing, RFQ and PLM. One note per (part, field_key);
comments are append only; every comment and flag change is logged on the
part's changelog so the part history shows it."""
import re
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.field_note import FIELD_FLAG_STATUSES, FieldNote, FieldNoteComment
from app.models.part import Part
from app.services.dfm_service import user_names
from app.services.part_service import ChangelogService

FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}\.[a-z][a-z0-9_]{0,30}$")
TOOL_PREFIXES = ("tool", "dfm")
NOT_ON_TOOL_PREFIXES = ("paint", "revision")
MAX_COMMENT_LENGTH = 4000


class FieldNoteError(ValueError):
    """Bad field key, key not valid for the item category, bad flag or empty comment."""


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def check_field_key(part: Part, field_key: str) -> None:
    if not FIELD_KEY_RE.match(field_key or ""):
        raise FieldNoteError(f"Invalid field key '{field_key}': expected <group>.<field> in lower case")
    prefix = field_key.split(".", 1)[0]
    if prefix in TOOL_PREFIXES and part.item_category != "tool":
        raise FieldNoteError(f"'{field_key}' is a tool field and {part.part_number} is not a tool")
    if prefix in NOT_ON_TOOL_PREFIXES and part.item_category == "tool":
        raise FieldNoteError(f"'{field_key}' does not apply to a tool")


def _comment_dict(c: FieldNoteComment, names: dict) -> dict:
    return {"id": c.id, "body": c.body, "author_id": c.author_id,
            "author_name": names.get(c.author_id), "created_at": _iso(c.created_at)}


class FieldNoteService:

    @staticmethod
    async def get(session: AsyncSession, part_id: int, field_key: str) -> Optional[FieldNote]:
        return (await session.execute(select(FieldNote).where(
            FieldNote.part_id == part_id, FieldNote.field_key == field_key))).scalar_one_or_none()

    @staticmethod
    async def _get_or_new(session: AsyncSession, part: Part, field_key: str) -> FieldNote:
        note = await FieldNoteService.get(session, part.id, field_key)
        if note is not None:
            return note
        note = FieldNote(part_id=part.id, field_key=field_key, comments=[])
        try:
            async with session.begin_nested():
                session.add(note)
                await session.flush()
        except IntegrityError:
            # A concurrent request created the note first: use that one.
            note = await FieldNoteService.get(session, part.id, field_key)
            if note is None:
                raise
        return note

    @staticmethod
    async def add_comment(session: AsyncSession, part: Part, field_key: str, body: str,
                          user_id: int) -> FieldNote:
        check_field_key(part, field_key)
        text = (body or "").strip()
        if not text:
            raise FieldNoteError("A comment must not be empty")
        if len(text) > MAX_COMMENT_LENGTH:
            raise FieldNoteError(f"A comment is at most {MAX_COMMENT_LENGTH} characters")
        note = await FieldNoteService._get_or_new(session, part, field_key)
        note.comments.append(FieldNoteComment(body=text, author_id=user_id))
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=part.id, action="field_comment_added",
            action_description=f"Comment on {field_key}: {text[:200]}",
            performed_by=user_id, field_name=field_key, new_value=text[:500])
        return note

    @staticmethod
    async def set_flag(session: AsyncSession, part: Part, field_key: str, status: Optional[str],
                       user_id: int) -> Optional[FieldNote]:
        """status None clears. Setting the current value again changes and logs nothing."""
        check_field_key(part, field_key)
        if status is not None and status not in FIELD_FLAG_STATUSES:
            raise FieldNoteError(f"Unknown flag '{status}'. Valid: {', '.join(FIELD_FLAG_STATUSES)} or none")
        note = await FieldNoteService.get(session, part.id, field_key)
        if note is None:
            if status is None:
                return None
            note = await FieldNoteService._get_or_new(session, part, field_key)
        old = note.flag_status
        if old == status:
            return note
        note.flag_status = status
        note.flag_set_by = user_id if status else None
        note.flag_set_at = datetime.utcnow() if status else None
        await session.flush()
        await ChangelogService.log_action(
            session, part_id=part.id, action="field_flag_set",
            action_description=f"Flag on {field_key}: {old or 'none'} to {status or 'cleared'}",
            performed_by=user_id, field_name=field_key, old_value=old, new_value=status)
        return note

    @staticmethod
    async def list_for_part(session: AsyncSession, part_id: int,
                            field_key: Optional[str] = None) -> list[FieldNote]:
        q = select(FieldNote).where(FieldNote.part_id == part_id)
        if field_key:
            q = q.where(FieldNote.field_key == field_key)
        return list((await session.execute(q.order_by(FieldNote.field_key))).scalars().all())

    @staticmethod
    async def list_for_project(session: AsyncSession, project_id: int) -> list[FieldNote]:
        return list((await session.execute(
            select(FieldNote).join(Part, Part.id == FieldNote.part_id)
            .where(Part.project_id == project_id)
            .order_by(FieldNote.part_id, FieldNote.field_key))).scalars().all())

    @staticmethod
    async def names_for(session: AsyncSession, notes: Iterable[FieldNote]) -> dict:
        ids: set = set()
        for n in notes:
            ids.add(n.flag_set_by)
            ids.update(c.author_id for c in n.comments)
        return await user_names(session, ids)

    @staticmethod
    def summary(note: FieldNote, names: dict) -> dict:
        comments = list(note.comments)
        return {
            "id": note.id, "part_id": note.part_id, "field_key": note.field_key,
            "flag_status": note.flag_status, "flag_set_by": note.flag_set_by,
            "flag_set_by_name": names.get(note.flag_set_by), "flag_set_at": _iso(note.flag_set_at),
            "created_at": _iso(note.created_at), "comment_count": len(comments),
            "last_comment": _comment_dict(comments[-1], names) if comments else None,
        }

    @staticmethod
    def thread(note: FieldNote, names: dict) -> dict:
        return {**FieldNoteService.summary(note, names),
                "comments": [_comment_dict(c, names) for c in note.comments]}

    @staticmethod
    def empty_thread(part_id: int, field_key: str) -> dict:
        return {"id": None, "part_id": part_id, "field_key": field_key, "flag_status": None,
                "flag_set_by": None, "flag_set_by_name": None, "flag_set_at": None,
                "created_at": None, "comment_count": 0, "last_comment": None, "comments": []}
