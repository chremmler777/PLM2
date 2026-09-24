"""Material on articles: search MaterialDB through PLM (the service token
stays on the server), link a MaterialDB material, or mark it new."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.models import User
from app.services import materialdb_client
from app.services.materialdb_client import MaterialDbUnavailable

router = APIRouter(tags=["materials"])


def _unavailable(e: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.get("/materials/search", response_model=List[dict])
async def search_materials(q: str = Query("", max_length=100), current_user: User = Depends(get_current_user)):
    try:
        return await materialdb_client.search(q)
    except MaterialDbUnavailable as e:
        raise _unavailable(e)
