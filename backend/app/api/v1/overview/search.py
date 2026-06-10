"""Global search endpoint - parts and projects by number, name, description."""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.entities import Project
from app.models.part import Part

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query(..., min_length=2, max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search parts (number, name, description) and projects (name, code)."""
    pattern = f"%{q.lower()}%"

    part_result = await db.execute(
        select(Part, Project.name)
        .join(Project, Project.id == Part.project_id)
        .where(
            or_(
                func.lower(Part.part_number).like(pattern),
                func.lower(Part.name).like(pattern),
                func.lower(Part.description).like(pattern),
            )
        )
        .order_by(Part.part_number)
        .limit(15)
    )
    parts = [
        {
            "type": "part",
            "id": part.id,
            "part_number": part.part_number,
            "name": part.name,
            "part_type": part.part_type,
            "item_category": part.item_category,
            "project_id": part.project_id,
            "project_name": project_name,
        }
        for part, project_name in part_result.all()
    ]

    project_result = await db.execute(
        select(Project)
        .where(
            or_(
                func.lower(Project.name).like(pattern),
                func.lower(Project.code).like(pattern),
            )
        )
        .order_by(Project.name)
        .limit(5)
    )
    projects = [
        {"type": "project", "id": p.id, "name": p.name, "code": p.code}
        for p in project_result.scalars().all()
    ]

    return {"parts": parts, "projects": projects}
