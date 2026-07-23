"""Response schemas for the unified audit timeline API."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    timestamp: datetime
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    correlation_id: Optional[str] = None
    log_level: str

    class Config:
        from_attributes = True


class AuditVerifyResponse(BaseModel):
    valid: bool
    checked: int
    first_broken_id: Optional[int] = None
    # Populated only when GET /audit/verify is called with ?correlation_id=.
    correlation_entries: Optional[int] = None
    correlation_ok: Optional[bool] = None
