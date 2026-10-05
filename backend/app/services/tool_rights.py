"""Who may change tool data: the tool card fields, produces links, shrinkage decisions and DFM.

One rule, used by every tool write path and by the UI flag (/auth/me can_edit_tools):
an admin (the real admin, not while acting as a department) or a member of the
Tool Engineer department (acts-as aware: an admin acting as Tool Engineer may edit,
acting as any other department may only view). Everyone else views.

Today every PLM editor is plm2_Admin, so in practice the rule bites through
"Act as" and for viewers. When admin is narrowed (a PLM admin list or a
plm2_Engineer hub role), only _is_admin changes here."""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Department
from app.services.workflow_service import WorkflowService

TOOL_ENGINEER = "Tool Engineer"
TOOL_EDIT_DENIED = "Only Tool Engineer or an admin can change tool data; you can view it."


def _is_admin(user) -> bool:
    # effective_role is "engineer" while a real admin acts as a department
    return getattr(user, "effective_role", None) == "admin"


async def can_edit_tools(db: AsyncSession, user) -> bool:
    if user is None:
        return False
    if _is_admin(user):
        return True
    dept_id = (await db.execute(select(Department.id).where(Department.name == TOOL_ENGINEER))).scalar_one_or_none()
    return dept_id is not None and await WorkflowService.actor_in_department(db, user, dept_id)


async def require_tool_editor(db: AsyncSession, user) -> None:
    if not await can_edit_tools(db, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, TOOL_EDIT_DENIED)
