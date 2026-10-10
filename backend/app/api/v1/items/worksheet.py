"""The project worksheet: rows (one per article with its tool) and the xlsx
export of what the browser shows. Org scoping as in part_paint.py."""
import re
from datetime import date
from typing import Annotated, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.items.part_paint import _project_in_org
from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.entities import Project
from app.models.part import Part
from app.services.worksheet_export import XLSX_MEDIA_TYPE, build_xlsx, embeddable
from app.services.worksheet_audit import (
    DEFAULT_LIMIT, MAX_CSV_ROWS, MAX_LIMIT, audit_entries, build_csv,
)
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
    # image: the cell value is the part id whose thumbnail is placed in the cell
    type: Literal["text", "number", "date", "image"] = "text"


MAX_CELL_TEXT = 5000
MAX_COMMENTS = 10_000


class ExportCell(BaseModel):
    value: Union[int, float, Annotated[str, Field(max_length=MAX_CELL_TEXT)], None] = None
    flag: Optional[Literal["open", "confirmed", "rejected"]] = None
    comments: int = Field(0, ge=0, le=MAX_COMMENTS)
    # Tool group (as on screen): >1 merges this cell over that many rows, 0 = covered by the cell above.
    span: Optional[int] = Field(None, ge=0, le=5000)


class ExportRow(BaseModel):
    cells: List[ExportCell]
    group_start: bool = False  # first row of the next tool's group: a divider line above it


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


async def _thumbnails(db: AsyncSession, project_id: int, body: "ExportIn") -> dict[int, bytes]:
    """Picture bytes for the part ids in image columns, this project's parts
    only; a missing or unreadable file just leaves the cell empty."""
    cols = [j for j, c in enumerate(body.columns) if c.type == "image"]
    ids = {r.cells[j].value for r in body.rows for j in cols if isinstance(r.cells[j].value, int)}
    if not ids:
        return {}
    parts = (await db.execute(select(Part.id, Part.thumbnail_path).where(
        Part.id.in_(ids), Part.project_id == project_id, Part.thumbnail_path.is_not(None)))).all()
    out = {}
    for pid, path in parts:
        try:
            with open(path, "rb") as fh:
                pic = embeddable(fh.read())
        except OSError:
            continue
        if pic:
            out[pid] = pic
    return out


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
                      body.frozen_columns, sheet_title=f"{code} worksheet",
                      group_starts={i for i, r in enumerate(body.rows) if r.group_start},
                      images=await _thumbnails(db, project_id, body))
    filename = f"{code}-worksheet-{date.today().isoformat()}.xlsx"
    return Response(content=data, media_type=XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


AuditGroup = Literal["comments", "flags", "material", "values", "other"]


def _audit_filters(action_group: Optional[AuditGroup] = None, part_id: Optional[int] = None,
                   part: Optional[str] = Query(None, max_length=100),
                   field_key: Optional[str] = Query(None, max_length=64)) -> dict:
    """The filters the list and the CSV share; empty text means no filter."""
    return {"action_group": action_group, "part_id": part_id, "part": part or None, "field_key": field_key or None}


@router.get("/projects/{project_id}/worksheet/audit", response_model=dict)
async def get_worksheet_audit(project_id: int, filters: dict = Depends(_audit_filters),
                              limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
                              before_id: Optional[int] = Query(None, ge=1),
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Worksheet-relevant changelog entries of the project's parts, newest first; page with before_id."""
    await _project_in_org(db, project_id, current_user.organization_id)
    entries, has_more = await audit_entries(db, project_id, **filters, before_id=before_id, limit=limit)
    return {"entries": entries, "has_more": has_more}


@router.get("/projects/{project_id}/worksheet/audit.csv")
async def export_worksheet_audit(project_id: int, filters: dict = Depends(_audit_filters),
                                 current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _project_in_org(db, project_id, current_user.organization_id)
    project = await db.get(Project, project_id)
    entries, truncated = await audit_entries(db, project_id, **filters, limit=MAX_CSV_ROWS)
    filename = f"{_safe(project.code)}-worksheet-audit-{date.today().isoformat()}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if truncated:
        headers["X-Truncated"] = "true"
    return Response(content=build_csv(entries, truncated), media_type="text/csv; charset=utf-8", headers=headers)
