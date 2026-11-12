"""The one place that changes a SEP work item's status (and audits it).

Used by the SEP view (`sep.update_item`) and by the project LOP, so a line
closed in the LOP and an item set done in the SEP view are the same write.
"""
from datetime import datetime

from app.models.sep import SepItemAudit, SepWorkItem


def make_audit(item: SepWorkItem, user_id: int, field: str, old, new) -> SepItemAudit:
    return SepItemAudit(
        item_id=item.id, user_id=user_id, field=field,
        old_value=str(old) if old is not None else None,
        new_value=str(new) if new is not None else None,
    )


def apply_item_status(db, item: SepWorkItem, new_status: str, user_id: int) -> bool:
    """Set the status, audit it, stamp completed_at (done only). Caller commits.
    False when nothing changed."""
    if new_status == item.status:
        return False
    db.add(make_audit(item, user_id, "status", item.status, new_status))
    item.status = new_status
    item.completed_at = datetime.utcnow() if new_status == "done" else None
    return True
