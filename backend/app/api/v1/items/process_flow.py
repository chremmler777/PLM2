"""Read-only process route for a tool, derived from serves/feeds relations."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.process_flow_service import ProcessFlowService

router = APIRouter(prefix="/parts", tags=["process-flow"])


@router.get("/{part_id}/process-flow", response_model=dict)
async def get_process_flow(
    part_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mold -> in-cell -> secondary -> gauge for this part's tool, plus the
    tools feeding into it. Asking from a gauge or station resolves to its tool.
    """
    flow = await ProcessFlowService.build(db, part_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Part not found")
    return flow
