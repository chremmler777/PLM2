"""The release checklist (stage 10): what has to be true before a change is
released, and which department answers for each item.

Config in code, like the validation catalog next door: the list is part of the
process definition, reviewed with it, and changing it is a code change on
purpose. The owner is a department NAME, resolved to an id when a change's
rows are seeded, so a database without one of these departments still gets
the item (owned by nobody, answerable by PM, lead and admin).

Items added to the catalog later (ADDED_LATER) never reach back into
finished changes: a change that was released before the item went live, or
ended without a release (rejected, cancelled), does not show it and is not
counted against it. Every change still open, and every change released at
or after the moment the item went live, has it like any other.

"Went live" is a UTC instant compared with ChangeRequest.released_at (naive
UTC). The default is the planned go-live; the deploy sets
PLM_RELEASE_ROWS_SINCE to the actual deploy moment (see
docs/deploy/ecr-costing-to-close-rollout.md).
"""
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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


# Quality and Process Engineer rows (decision 2026-09-25: both owe their
# own release rows). Default go-live: 2026-09-26 04:00 UTC, i.e. midnight
# New York (EDT) on 26 Sep. Naive, in UTC, like released_at.
RELEASE_ROWS_SINCE_DEFAULT = datetime(2026, 9, 26, 4, 0)
RELEASE_ROWS_SINCE_ENV = "PLM_RELEASE_ROWS_SINCE"


def release_rows_since(env: dict | None = None) -> datetime:
    """The UTC instant the Quality / Process Engineer rows went live, as a
    naive UTC datetime. PLM_RELEASE_ROWS_SINCE (ISO 8601; no offset means
    UTC, an offset is converted to UTC) overrides the default; an
    unparseable value is logged and ignored."""
    env = os.environ if env is None else env
    raw = (env.get(RELEASE_ROWS_SINCE_ENV) or "").strip()
    if not raw:
        return RELEASE_ROWS_SINCE_DEFAULT
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("%s=%r is not an ISO datetime; using %s",
                       RELEASE_ROWS_SINCE_ENV, raw,
                       RELEASE_ROWS_SINCE_DEFAULT.isoformat())
        return RELEASE_ROWS_SINCE_DEFAULT
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# Keys added after the first catalog: they apply per release_rows_since().
ADDED_LATER: frozenset[str] = frozenset({
    "process_parameters", "process_fmea",
    "quality_samples", "quality_control_plan",
})

# Terminal change statuses (mirrors app.models.change.TERMINAL_STATUSES; not
# imported so the catalog stays free of model imports).
_FINISHED = ("released", "closed", "rejected", "cancelled")


def applies(key: str, status: str | None, released_at: datetime | None,
            answered: bool = False) -> bool:
    """Whether this catalog item belongs to a change in this state. An item
    that was answered always belongs; an item added later is left off a
    change that finished before it existed (released earlier, or never
    released at all). `released_at` is naive UTC (an aware value is
    converted)."""
    if key not in ADDED_LATER or answered or status not in _FINISHED:
        return True
    if released_at is None:
        return False
    if released_at.tzinfo is not None:
        released_at = released_at.astimezone(timezone.utc).replace(tzinfo=None)
    return released_at >= release_rows_since()


def keys_for(change, answered_keys=()) -> list[str]:
    """The catalog keys that belong to this change, in catalog order.
    `answered_keys`: keys the change has a persisted row for."""
    done = set(answered_keys)
    status = getattr(change, "status", None)
    released_at = getattr(change, "released_at", None)
    return [k for k in CHECK_KEYS if applies(k, status, released_at, k in done)]
