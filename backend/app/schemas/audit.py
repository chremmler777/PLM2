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
    # Spec §16: who acted as which department, and new_values with ids read
    # as names ("template_id": "ECM Assessment", "task_id": "Development:
    # Department assessment"). Set by the list endpoint.
    real_user_id: Optional[int] = None
    real_user_name: Optional[str] = None
    acting_as_department_id: Optional[int] = None
    acting_as_department_name: Optional[str] = None
    display_values: Optional[dict] = None

    class Config:
        from_attributes = True


class AuditVerifyResponse(BaseModel):
    valid: bool
    checked: int
    first_broken_id: Optional[int] = None
    # Populated only when GET /audit/verify is called with ?correlation_id=.
    correlation_entries: Optional[int] = None
    correlation_ok: Optional[bool] = None
    # Populated only with ?change_id= (spec §16 P1-9): the change's own rows
    # by entity. break_scope: "none" | "global" (the chain broke at
    # first_broken_id, outside this change) | "change" (the break, or a row
    # that no longer re-hashes, is one of this change's own entries).
    change_entries: Optional[int] = None
    change_ok: Optional[bool] = None
    change_first_broken_id: Optional[int] = None
    break_scope: Optional[str] = None
