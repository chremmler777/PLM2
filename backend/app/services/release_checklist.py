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

Items taken off the catalog (RETIRED_CHECKS) mirror that: a change that
ended before the cutoff keeps its original checklist, retired items
included; everywhere else a retired item is no longer asked, and an answer
somebody gave it stays on the record, shown read-only and not counted.

"Went live" is a UTC instant compared with ChangeRequest.released_at (naive
UTC). The default is the planned go-live; the deploy sets
PLM_RELEASE_ROWS_SINCE to the actual deploy moment (see
docs/deploy/ecr-costing-to-close-rollout.md).
"""
import logging
import math
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
    ("weight_measured",
     "Part weight measured and recorded", "Tool Engineer"),
    # Process Engineer (decision 2026-09-26): the process details (parameters,
    # PFMEA, work instructions) live in the process database (PDB), where the
    # Process Engineer confirms them. The release asks only two things of PE.
    ("cycle_time",
     "Cycle time: changed (new value entered) or confirmed unchanged",
     "Process Engineer"),
    # One confirmation owed by two departments: two linked rows, one per
    # owner, and the process counts as stable only when both are done.
    ("process_stable_pe",
     "Process stable: SPC Cm > 1.67 (Process Engineer)", "Process Engineer"),
    ("process_stable_apqp",
     "Process stable: SPC Cm > 1.67 (APQP)", "APQP"),
    ("surface_quality",
     "Surface quality confirmed", "APQP"),
    ("technical_quality",
     "Technical quality confirmed", "APQP"),
    ("parts_measured",
     "Measurements confirmed, measurement report on file", "APQP"),
    # PPAP asked once: the sample documentation and the customer's approval
    # of it are one APQP row (decision 2026-09-26).
    ("customer_approval",
     "PPAP / initial sample documentation complete, customer approval "
     "received (ISIR / PSW)", "APQP"),
    ("control_plan",
     "Control plan / inspection plan updated", "APQP"),
    ("packaging_updated",
     "Packaging instruction updated", "Packaging Engineer"),
    ("erp_updated",
     "ERP, BOM and routing updated", "Scheduling"),
    ("stock_handled",
     "Old stock handled as agreed (bank consumed or scrapped)", "Scheduling"),
    ("customer_informed",
     "Customer informed of the implementation date / first shipment", "Sales"),
    ("spare_parts",
     "Spare and service parts considered", "Development"),
]

# Items no longer asked (decision 2026-09-26). Their stored answers stay on
# the record and read with their own words and owner: shown read-only and
# never counted on a change still running or released after the cutoff; a
# change that ended before the cutoff keeps its original checklist, these
# rows included (see applies()).
RETIRED_CHECKS: list[tuple[str, str, str]] = [
    # merged into cycle_time, now owned by the Process Engineer
    ("cycle_time_confirmed",
     "Cycle time confirmed in series production", "Manufacturing Engineer"),
    # PFMEA and work instructions: in the PDB (Process Engineer); control
    # plan: Quality's quality_control_plan
    ("documents_updated",
     "PFMEA, control plan and work instructions updated", "APQP"),
    # kept in the PDB by the Process Engineer
    ("process_parameters",
     "Process parameters and work instructions updated", "Process Engineer"),
    ("process_fmea",
     "Process FMEA updated", "Process Engineer"),
    # APQP's now: PPAP merged into customer_approval, control plan moved to
    # control_plan. Quality owns no release row.
    ("quality_samples",
     "Parts measured and PPAP / initial sample documentation complete", "Quality"),
    ("quality_control_plan",
     "Control plan / inspection plan updated", "Quality"),
]

CHECK_KEYS = [k for k, _, _ in RELEASE_CHECKS]
RETIRED: frozenset[str] = frozenset(k for k, _, _ in RETIRED_CHECKS)
_BY_KEY = {k: (label, dept) for k, label, dept in RELEASE_CHECKS + RETIRED_CHECKS}

# Display order of every key, retired ones next to what replaced them.
ORDER: list[str] = CHECK_KEYS[:4] + ["cycle_time_confirmed"] + CHECK_KEYS[4:12] \
    + ["documents_updated", "process_parameters", "process_fmea",
       "quality_samples", "quality_control_plan"] + CHECK_KEYS[12:]

# The answers that carry a value (no column of their own: the value is
# written into the note in these words and into the changelog as data).
CYCLE_TIME_KEY = "cycle_time"
CM_KEYS = frozenset({"process_stable_pe", "process_stable_apqp"})
CM_MIN = 1.67


def value_kind(key: str) -> str | None:
    """'cycle_time' (changed with a new value, or confirmed unchanged), 'cm'
    (optional measured Cm, above CM_MIN) or None."""
    if key == CYCLE_TIME_KEY:
        return "cycle_time"
    if key in CM_KEYS:
        return "cm"
    return None


def answer_note(key: str, outcome: str | None, value: float | None,
                note: str | None) -> str | None:
    """The stored note of a 'done' answer: the value in words first, then
    the free note. Raises ValueError with the user-facing reason."""
    kind = value_kind(key)
    if value is not None and not math.isfinite(value):
        raise ValueError("The value must be a number")
    if kind is None:
        if outcome is not None or value is not None:
            raise ValueError("This item takes no value")
        return note
    if kind == "cycle_time":
        if outcome not in ("changed", "unchanged"):
            raise ValueError(
                "Say whether the cycle time changed or is confirmed unchanged")
        if outcome == "changed":
            if value is None or value <= 0:
                raise ValueError("A changed cycle time needs the new value in seconds")
            head = f"Changed: new cycle time {value:g} s"
        else:
            if value is not None:
                raise ValueError("An unchanged cycle time takes no new value")
            head = "Confirmed unchanged"
    else:
        if outcome is not None:
            raise ValueError("This item takes no outcome")
        if value is None:
            return note
        if value <= CM_MIN:
            raise ValueError(
                f"Cm {value:g} is not above {CM_MIN:g}: the process is not "
                "stable yet")
        head = f"Cm {value:g}"
    return f"{head}. {note}" if note else head


def label_for(key: str) -> str:
    return _BY_KEY.get(key, (key, None))[0]


def owner_for(key: str) -> str | None:
    return _BY_KEY.get(key, (None, None))[1]


# The rework of the checklist (Quality and Process Engineer rows, decision
# 2026-09-25; Process Engineer / APQP rows reworked, decision 2026-09-26)
# ships in one deploy with one go-live instant. Default: 2026-09-26 04:00
# UTC, i.e. midnight New York (EDT) on 26 Sep. Naive, in UTC, like
# released_at.
RELEASE_ROWS_SINCE_DEFAULT = datetime(2026, 9, 26, 4, 0)
RELEASE_ROWS_SINCE_ENV = "PLM_RELEASE_ROWS_SINCE"


def release_rows_since(env: dict | None = None) -> datetime:
    """The UTC instant the reworked rows went live, as a
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
    "cycle_time", "process_stable_pe", "process_stable_apqp",
    "surface_quality", "technical_quality", "control_plan",
})
# Retired keys of the first catalog: a change that ended before the cutoff
# still owes (and shows) them like any other item. The other retired keys
# (process_parameters, process_fmea, quality_samples, quality_control_plan)
# were never live before the cutoff, so they belong to no change; an answer
# given to them is still shown, read-only.
RETIRED_ORIGINAL: frozenset[str] = frozenset({
    "cycle_time_confirmed", "documents_updated",
})

# Terminal change statuses (mirrors app.models.change.TERMINAL_STATUSES; not
# imported so the catalog stays free of model imports).
_FINISHED = ("released", "closed", "rejected", "cancelled")


def ended_before_cutoff(status: str | None,
                        released_at: datetime | None) -> bool:
    """A change that finished before the reworked rows went live: released
    earlier, or ended without a release at all. `released_at` is naive UTC
    (an aware value is converted)."""
    if status not in _FINISHED:
        return False
    if released_at is None:
        return True
    if released_at.tzinfo is not None:
        released_at = released_at.astimezone(timezone.utc).replace(tzinfo=None)
    return released_at < release_rows_since()


def applies(key: str, status: str | None, released_at: datetime | None,
            answered: bool = False) -> bool:
    """Whether this item is COUNTED on a change in this state. An item added
    later is left off a change that finished before it existed, unless it
    was answered there; a retired item of the first catalog belongs only to
    such a change (elsewhere its answer is shown read-only, see
    retired_keys_for); any other retired item belongs to no change."""
    before = ended_before_cutoff(status, released_at)
    if key in RETIRED:
        return before and key in RETIRED_ORIGINAL
    if key in ADDED_LATER:
        return answered or not before
    return key in _BY_KEY


def keys_for(change, answered_keys=()) -> list[str]:
    """The keys that belong to (are counted on) this change, in display
    order. `answered_keys`: keys the change has a persisted row for."""
    done = set(answered_keys)
    status = getattr(change, "status", None)
    released_at = getattr(change, "released_at", None)
    return [k for k in ORDER if applies(k, status, released_at, k in done)]


def retired_keys_for(change, answered_keys=()) -> list[str]:
    """Retired keys shown read-only on this change: answered (done / n.a.)
    but no longer counted. `answered_keys`: keys with a done/na row."""
    counted = set(keys_for(change, answered_keys))
    done = set(answered_keys)
    return [k for k in ORDER if k in RETIRED and k in done and k not in counted]
