"""The project worksheet: rows (one per article with its tool) and the xlsx
export of what the browser shows. Org scoping as in part_paint.py."""
import re
from datetime import date
from typing import List, Literal, Optional, Union

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _project_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.entities import Project
from app.services.worksheet_export import XLSX_MEDIA_TYPE, build_xlsx
from app.services.worksheet_service import worksheet_rows

router = APIRouter(tags=["worksheet"])


@router.get("/projects/{project_id}/worksheet", response_model=dict)
async def get_worksheet(project_id: int, current_user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    return await worksheet_rows(db, project_id)


class ExportColumn(BaseModel):
    key: str = Field(..., max_length=64)
    label: str = Field(..., max_length=100)
    type: Literal["text", "number", "date"] = "text"


class ExportCell(BaseModel):
    value: Union[int, float, str, None] = None
    flag: Optional[Literal["open", "confirmed", "rejected"]] = None
    comments: int = Field(0, ge=0)


class ExportRow(BaseModel):
    cells: List[ExportCell]


class ExportIn(BaseModel):
    columns: List[ExportColumn] = Field(..., min_length=1, max_length=60)
    rows: List[ExportRow] = Field(default_factory=list, max_length=5000)
    frozen_columns: int = Field(0, ge=0, le=10)

    @model_validator(mode="after")
    def _rectangular(self):
        n = len(self.columns)
        if any(len(r.cells) != n for r in self.rows):
            raise ValueError(f"every row needs exactly {n} cells, one per column")
        return self


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "project"


@router.post("/projects/{project_id}/worksheet/export")
async def export_worksheet(project_id: int, body: ExportIn, current_user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    project = await db.get(Project, project_id)
    code = _safe(project.code)
    data = build_xlsx([c.model_dump() for c in body.columns],
                      [[cell.model_dump() for cell in r.cells] for r in body.rows],
                      body.frozen_columns, sheet_title=f"{code} worksheet")
    filename = f"{code}-worksheet-{date.today().isoformat()}.xlsx"
    return Response(content=data, media_type=XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
