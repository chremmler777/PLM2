"""Material of an article: linked to MaterialDB or explicitly new. Every change
is logged on the part's changelog with the old and new display text."""
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.part import Part
from app.services import materialdb_client
from app.services.part_service import ChangelogService

MATERIAL_ONLY_ON_ARTICLES = "Material applies to articles only"
LABEL_MAX = 300


class MaterialNotInDb(ValueError):
    """The picked MaterialDB id does not exist (a 400)."""


class MaterialGone(Exception):
    """A linked material vanished from MaterialDB; the cached label stays (a 409)."""


def material_text(part: Part) -> Optional[str]:
    if part.material_source == "materialdb":
        return part.material_label or f"MaterialDB #{part.materialdb_id}"
    if part.material_source == "new":
        return f"NEW (not in MaterialDB): {part.material_new_text}"
    return None


def _check(part: Part) -> None:
    if part.item_category != "article":
        raise ValueError(MATERIAL_ONLY_ON_ARTICLES)


def _apply_link(part: Part, m: dict) -> None:
    part.material_source = "materialdb"
    part.materialdb_id = m["id"]
    part.material_ktx_number = m.get("ktx_number")
    part.material_label = materialdb_client.label(m)[:LABEL_MAX]
    part.material_synced_at = datetime.utcnow()
    part.material_new_text = None


async def _finish(session: AsyncSession, part: Part, old: Optional[str], user_id: int,
                   action: str = "material_set") -> Part:
    part.updated_by = user_id
    part.updated_at = datetime.utcnow()
    await session.flush()
    new = material_text(part)
    if old != new:
        await ChangelogService.log_action(
            session, part_id=part.id, action=action,
            action_description=f"Material: {old or 'none'} to {new or 'none'}",
            performed_by=user_id, field_name="part.material", old_value=old, new_value=new)
    return part


class PartMaterialService:

    @staticmethod
    async def link(session: AsyncSession, part: Part, materialdb_id: int, user_id: int) -> Part:
        _check(part)
        m = await materialdb_client.find_by_id(materialdb_id, force=True)
        if m is None:
            raise MaterialNotInDb(f"Material {materialdb_id} is not in MaterialDB")
        old = material_text(part)
        _apply_link(part, m)
        return await _finish(session, part, old, user_id)

    @staticmethod
    async def set_new(session: AsyncSession, part: Part, text: str, user_id: int) -> Part:
        _check(part)
        clean = (text or "").strip()
        if not clean:
            raise ValueError("Describe the new material")
        old = material_text(part)
        part.material_source = "new"
        part.material_new_text = clean[:500]
        part.materialdb_id = None
        part.material_ktx_number = None
        part.material_label = None
        part.material_synced_at = None
        return await _finish(session, part, old, user_id)

    @staticmethod
    async def clear(session: AsyncSession, part: Part, user_id: int) -> Part:
        _check(part)
        old = material_text(part)
        part.material_source = None
        part.material_new_text = None
        part.materialdb_id = None
        part.material_ktx_number = None
        part.material_label = None
        part.material_synced_at = None
        return await _finish(session, part, old, user_id)

    @staticmethod
    async def refresh(session: AsyncSession, part: Part, user_id: int) -> Part:
        _check(part)
        if part.material_source != "materialdb" or part.materialdb_id is None:
            raise ValueError("Only a material linked to MaterialDB can be refreshed")
        m = await materialdb_client.find_by_id(part.materialdb_id, force=True)
        if m is None:
            raise MaterialGone(f"{part.material_label or part.materialdb_id} is no longer in MaterialDB; "
                                "the saved label is kept")
        old = material_text(part)
        _apply_link(part, m)
        return await _finish(session, part, old, user_id, action="material_refreshed")
