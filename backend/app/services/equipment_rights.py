"""Who may create or change gauges and assembly equipment (EOATs included), and their links.

PLM is the one source for tools, gauges, assembly equipment and EOATs (Christoph,
2026-11-16). One rule per item category, used by every write path (create, update,
checks / assembles / serves links) and by the UI flags (/auth/me can_edit_gauges,
can_edit_assembly_equipment):

  tool                 admin or Tool Engineer (unchanged, app/services/tool_rights.py)
  gauge                admin, APQP or the Project Manager
  assembly_equipment   admin, Manufacturing Engineer or the Project Manager
                       (an EOAT is assembly equipment numbered <tool>-1x)
  article              no rule here

Acts-as aware exactly like tool_rights: the real admin may do all of it, an admin
acting as a department counts as that department only. Everyone else views."""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Department
from app.services.tool_rights import _is_admin, require_tool_editor
from app.services.workflow_service import WorkflowService

APQP = "APQP"
PROJECT_MANAGER = "Project Manager"
MANUFACTURING_ENGINEER = "Manufacturing Engineer"

GAUGE_DEPARTMENTS = (APQP, PROJECT_MANAGER)
ASSEMBLY_EQUIPMENT_DEPARTMENTS = (MANUFACTURING_ENGINEER, PROJECT_MANAGER)

GAUGE_EDIT_DENIED = "Only APQP, the Project Manager or an admin can change gauges; you can view them."
ASSEMBLY_EQUIPMENT_EDIT_DENIED = ("Only Manufacturing Engineer, the Project Manager or an admin can change "
                                  "assembly equipment and EOATs; you can view them.")


async def _in_any_department(db: AsyncSession, user, names: tuple[str, ...]) -> bool:
    if user is None:
        return False
    if _is_admin(user):
        return True
    dept_ids = (await db.execute(select(Department.id).where(Department.name.in_(names)))).scalars().all()
    for dept_id in dept_ids:
        if await WorkflowService.actor_in_department(db, user, dept_id):
            return True
    return False


async def can_edit_gauges(db: AsyncSession, user) -> bool:
    return await _in_any_department(db, user, GAUGE_DEPARTMENTS)


async def can_edit_assembly_equipment(db: AsyncSession, user) -> bool:
    return await _in_any_department(db, user, ASSEMBLY_EQUIPMENT_DEPARTMENTS)


async def require_gauge_editor(db: AsyncSession, user) -> None:
    if not await can_edit_gauges(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, GAUGE_EDIT_DENIED)


async def require_assembly_equipment_editor(db: AsyncSession, user) -> None:
    if not await can_edit_assembly_equipment(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, ASSEMBLY_EQUIPMENT_EDIT_DENIED)


async def require_category_editor(db: AsyncSession, user, item_category: str | None) -> None:
    """The right to create or change an item of this category (articles have no rule)."""
    if item_category == "tool":
        await require_tool_editor(db, user)
    elif item_category == "gauge":
        await require_gauge_editor(db, user)
    elif item_category == "assembly_equipment":
        await require_assembly_equipment_editor(db, user)


async def require_relation_editor(db: AsyncSession, user, relation_type: str,
                                  from_category: str | None) -> None:
    """The right to add or remove a link: which articles a tool produces is tool data,
    what a gauge checks is gauge data, what a station assembles is equipment data, and
    which tools an item serves belongs to that item. Other link types have no rule."""
    if relation_type == "produces":
        await require_tool_editor(db, user)
    elif relation_type == "checks":
        await require_gauge_editor(db, user)
    elif relation_type == "assembles":
        await require_assembly_equipment_editor(db, user)
    elif relation_type == "serves":
        await require_category_editor(db, user, from_category)
