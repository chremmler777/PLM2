"""Change level keyed by tool number — for machine clients (PDB's sampling
board) that know tool numbers, not part ids. A trial runs at the products'
current customer and internal index; PDB snapshots both on the booking."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import get_db, User
from app.models.part import Part, PartRelation, PartRevision
from app.services.process_flow_service import ProcessFlowService

router = APIRouter(prefix="/tool-revisions", tags=["equipment"])

#: Released data: what the customer or we have signed off.
_RELEASED = ("approved", "frozen")
#: Never current: withdrawn, refused or superseded data.
_DEAD = ("cancelled", "rejected", "archived")
#: Legacy imports carry the customer's majors (and their index) from the old system.
_CUSTOMER_SOURCES = ("customer", "import")


def _current(revs: list[PartRevision]) -> PartRevision | None:
    """Latest released revision, else the latest one still alive."""
    alive = sorted((r for r in revs if r.status not in _DEAD), key=lambda r: (r.created_at, r.id))
    released = [r for r in alive if r.status in _RELEASED]
    return (released or alive or [None])[-1]


@router.get("", response_model=list[dict])
async def revisions_for_tool(
    tool_number: str = Query(..., min_length=1, description="Tool part number, e.g. 3457"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Products the tool makes: [{part_number, name, customer_part_number,
    customer_index, internal_index}], ordered by part number. customer_index is
    the current customer revision's own index (its revision name when the
    customer gave none); internal_index is the current internal revision.
    404 when there is no such tool; [] when it makes nothing yet."""
    tool = await ProcessFlowService.find_tool(db, tool_number.strip())
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No tool with number {tool_number!r}")
    products = (await db.execute(
        select(Part).join(PartRelation, PartRelation.to_part_id == Part.id)
        .where(PartRelation.from_part_id == tool.id, PartRelation.relation_type == "produces")
        .order_by(Part.part_number))).scalars().unique().all()
    if not products:
        return []
    revs = (await db.execute(select(PartRevision).where(
        PartRevision.part_id.in_([p.id for p in products])))).scalars().all()
    out = []
    for p in products:
        mine = [r for r in revs if r.part_id == p.id]
        cust = _current([r for r in mine if r.source in _CUSTOMER_SOURCES])
        internal = _current([r for r in mine if r.source == "internal"])
        out.append({
            "part_number": p.part_number, "name": p.name, "customer_part_number": p.customer_part_number,
            "customer_index": (cust.customer_index or cust.revision_name) if cust else None,
            "internal_index": internal.revision_name if internal else None,
        })
    return out
