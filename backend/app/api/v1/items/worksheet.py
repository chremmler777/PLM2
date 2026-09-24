"""The project worksheet: rows (one per article with its tool) and the xlsx
export of what the browser shows. Org scoping as in part_paint.py."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _project_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.worksheet_service import worksheet_rows

router = APIRouter(tags=["worksheet"])


@router.get("/projects/{project_id}/worksheet", response_model=dict)
async def get_worksheet(project_id: int, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    return await worksheet_rows(db, project_id)
