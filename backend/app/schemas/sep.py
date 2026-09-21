"""SEP payload schemas. Only the file slot on work items lives here so far;
the gate/item payloads are still assembled as dicts inside the SEP router."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SepItemFileOut(BaseModel):
    id: int
    item_id: int
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    uploaded_by: int
    uploaded_by_name: str | None = None
    uploaded_at: datetime


class SepProjectFileItemOut(BaseModel):
    item_id: int
    item_no: int
    title_en: str
    department: str
    files: list[SepItemFileOut]


class SepProjectFileGateOut(BaseModel):
    gate_id: int
    gate_code: str
    phase_en: str
    seq: int
    items: list[SepProjectFileItemOut]
