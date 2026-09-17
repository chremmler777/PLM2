"""Equipment keyed by tool number — for machine clients (the gauge/equipment
import) that know tool numbers, not part ids."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.services.process_flow_service import ProcessFlowService

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get("", response_model=list[dict])
async def equipment_for_tool(
    tool_number: str = Query(..., min_length=1,
                             description="Tool part number, e.g. 3454 or 0674-2"),
    include_gauges: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stations serving the tool: [{id, part_number, name, op_code, kind,
    serves: [tool numbers]}], ordered by op code. Gauges only on request.
    404 when there is no such tool; [] when the tool has no equipment."""
    tool = await ProcessFlowService.find_tool(db, tool_number.strip())
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No tool with number {tool_number!r}")
    return await ProcessFlowService.stations_for(db, tool, include_gauges=include_gauges)
