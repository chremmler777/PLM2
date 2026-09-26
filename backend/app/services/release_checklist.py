"""The release checklist (stage 10): what has to be true before a change is
released, and which department answers for each item.

Config in code, like the validation catalog next door: the list is part of the
process definition, reviewed with it, and changing it is a code change on
purpose. The owner is a department NAME, resolved to an id when a change's
rows are seeded, so a database without one of these departments still gets
the item (owned by nobody, answerable by PM, lead and admin).

Items added to the catalog later (ADDED_LATER) never reach back into
finished changes: a change that was released before the item existed, or
ended without a release (rejected, cancelled), does not show it and is not
counted against it. Every change still open, and every change released on
or after the day the item was added, has it like any other.
"""
from datetime import datetime

# (key, label, owner department name)
RELEASE_CHECKS: list[tuple[str, str, str]] = [
    ("index_updated",
     "Part index / revision level updated in drawing and PLM", "Development"),
    ("drawing_released",
     "Drawing and 3D data released and distributed", "Development"),
    ("equipment_updated",
     "Tool and equipment data updated (tool card, equipment list)", "Tool Engineer"),
    ("parts_measured",
     "Parts measured, measurement report on file", "APQP"),
    ("weight_measured",
     "Part weight measured and recorded", "Tool Engineer"),
    ("cycle_time_confirmed",
     "Cycle time confirmed in series production", "Manufacturing Engineer"),
    ("documents_updated",
     "PFMEA, control plan and work instructions updated", "APQP"),
    ("process_parameters",
     "Process parameters and work instructions updated", "Process Engineer"),
    ("process_fmea",
     "Process FMEA updated", "Process Engineer"),
    ("quality_samples",
     "Parts measured and PPAP / initial sample documentation complete", "Quality"),
    ("quality_control_plan",
     "Control plan / inspection plan updated", "Quality"),
    ("packaging_updated",
     "Packaging instruction updated", "Packaging Engineer"),
    ("customer_approval",
     "Customer approval received (PPAP / ISIR / PSW)", "APQP"),
    ("erp_updated",
     "ERP, BOM and routing updated", "Scheduling"),
    ("stock_handled",
     "Old stock handled as agreed (bank consumed or scrapped)", "Scheduling"),
    ("customer_informed",
     "Customer informed of the implementation date / first shipment", "Sales"),
    ("spare_parts",
     "Spare and service parts considered", "Development"),
]

CHECK_KEYS = [k for k, _, _ in RELEASE_CHECKS]
_BY_KEY = {k: (label, dept) for k, label, dept in RELEASE_CHECKS}


def label_for(key: str) -> str:
    return _BY_KEY.get(key, (key, None))[0]


def owner_for(key: str) -> str | None:
    return _BY_KEY.get(key, (None, None))[1]


# Quality and Process Engineer rows, added 2026-09-25 (decision: both owe
# their own release rows). Key -> the day the item was added.
ADDED_LATER: dict[str, datetime] = {
    "process_parameters": datetime(2026, 9, 25),
    "process_fmea": datetime(2026, 9, 25),
    "quality_samples": datetime(2026, 9, 25),
    "quality_control_plan": datetime(2026, 9, 25),
}

# Terminal change statuses (mirrors app.models.change.TERMINAL_STATUSES; not
# imported so the catalog stays free of model imports).
_FINISHED = ("released", "closed", "rejected", "cancelled")


def applies(key: str, status: str | None, released_at: datetime | None,
            answered: bool = False) -> bool:
    """Whether this catalog item belongs to a change in this state. An item
    that was answered always belongs; an item added later is left off a
    change that finished before it existed (released earlier, or never
    released at all)."""
    added = ADDED_LATER.get(key)
    if added is None or answered or status not in _FINISHED:
        return True
    return released_at is not None and released_at >= added


def keys_for(change, answered_keys=()) -> list[str]:
    """The catalog keys that belong to this change, in catalog order.
    `answered_keys`: keys the change has a persisted row for."""
    done = set(answered_keys)
    status = getattr(change, "status", None)
    released_at = getattr(change, "released_at", None)
    return [k for k in CHECK_KEYS if applies(k, status, released_at, k in done)]
