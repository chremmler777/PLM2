"""The release checklist (stage 10): what has to be true before a change is
released, and which department answers for each item.

Config in code, like the validation catalog next door: the list is part of the
process definition, reviewed with it, and changing it is a code change on
purpose. The owner is a department NAME, resolved to an id when a change's
rows are seeded, so a database without one of these departments still gets
the item (owned by nobody, answerable by PM, lead and admin).

Items added to the catalog later (ADDED_LATER) never reach back into
finished changes: a change that was released, rejected or cancelled before
the item went live does not show it and is not counted against it. Every
change still open, and every change that ended at or after the moment the
item went live, has it like any other.

Items taken off the catalog (RETIRED_CHECKS) mirror that: a change that
ended before the cutoff keeps its original checklist, retired items
included (and the relabelled items read with their old words,
OLD_LABELS); everywhere else a retired item is no longer asked, and an
answer somebody gave it stays on the record, shown read-only and not
counted.

"Went live" is a UTC instant compared with the moment the change ended
(ended_at: released_at, else cancelled_at / rejected_at / closed_at; naive
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
    # The cycle time comes from the Tool Engineer (decision 2026-09-26,
    # corrected the same day): changed with the new value, or confirmed
    # unchanged. The key is new so that an answer the Process Engineer gave
    # the first version (cycle_time) stays on the record, not counted.
    ("cycle_time_tool",
     "Cycle time: changed (new value entered) or confirmed unchanged",
     "Tool Engineer"),
    # APQP confirms the process stable, alone. The Process Engineer owes no
    # release row: the process details (parameters, PFMEA, work
    # instructions) live in the process database (PDB).
    ("process_stable_apqp",
     "Process stable: SPC Cm > 1.67", "APQP"),
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
    # merged into cycle_time_tool, owned by the Tool Engineer
    ("cycle_time_confirmed",
     "Cycle time confirmed in series production", "Manufacturing Engineer"),
    # First version of the rework (commit 0c7e5b47): the cycle time asked of
    # the Process Engineer (now cycle_time_tool, Tool Engineer) and the
    # Process Engineer's half of the process-stable confirmation (now APQP
    # alone, process_stable_apqp).
    ("cycle_time",
     "Cycle time: changed (new value entered) or confirmed unchanged",
     "Process Engineer"),
    ("process_stable_pe",
     "Process stable: SPC Cm > 1.67 (Process Engineer)", "Process Engineer"),
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
# Spelled out key by key (not sliced out of CHECK_KEYS), so reordering or
# adding a catalog row cannot silently shift the retired rows elsewhere.
ORDER: list[str] = [
    "index_updated", "drawing_released",
    "equipment_updated", "weight_measured",
    "cycle_time_tool", "cycle_time_confirmed", "cycle_time",
    "process_stable_pe", "process_stable_apqp",
    "surface_quality", "technical_quality", "parts_measured",
    "customer_approval", "control_plan",
    "documents_updated", "process_parameters", "process_fmea",
    "quality_samples", "quality_control_plan",
    "packaging_updated", "erp_updated", "stock_handled", "customer_informed",
    "spare_parts",
]
assert sorted(ORDER) == sorted(_BY_KEY), "ORDER must list every catalog key once"

# Kept keys whose words changed in the rework: a change that ended before
# the cutoff reads them as they were asked then.
OLD_LABELS: dict[str, str] = {
    "parts_measured": "Parts measured, measurement report on file",
    "customer_approval": "Customer approval received (PPAP / ISIR / PSW)",
}

# The answers that carry a value (no column of their own: the value is
# written into the note in these words and into the changelog as data).
CYCLE_TIME_KEY = "cycle_time_tool"
CM_KEYS = frozenset({"process_stable_apqp"})
CM_MIN = 1.67
# The precision a value is kept at: what is checked is what is stored.
CM_DECIMALS = 2
SECONDS_DECIMALS = 1


def value_kind(key: str) -> str | None:
    """'cycle_time' (changed with a new value, or confirmed unchanged), 'cm'
    (optional measured Cm, above CM_MIN) or None."""
    if key == CYCLE_TIME_KEY:
        return "cycle_time"
    if key in CM_KEYS:
        return "cm"
    return None


def rounded_value(key: str, value: float | None) -> float | None:
    """The value as it is checked and stored: Cm to 2 decimals, seconds to
    1. Raises ValueError on a value that is not a finite number."""
    if value is None:
        return None
    if not math.isfinite(value):
        raise ValueError("The value must be a number")
    kind = value_kind(key)
    if kind == "cm":
        return round(value, CM_DECIMALS)
    if kind == "cycle_time":
        return round(value, SECONDS_DECIMALS)
    return value


def _fmt(value: float, decimals: int) -> str:
    """Fixed decimals without trailing zeros: 38.5, 40, 1.85 (never 1e+06)."""
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def answer_note(key: str, outcome: str | None, value: float | None,
                note: str | None) -> str | None:
    """The stored note of a 'done' answer: the value in words first, then
    the free note. The value is rounded first (rounded_value) and the
    rounded value is what is checked and written. Raises ValueError with the
    user-facing reason."""
    kind = value_kind(key)
    value = rounded_value(key, value)
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
            head = f"Changed: new cycle time {_fmt(value, SECONDS_DECIMALS)} s"
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
                f"Cm {_fmt(value, CM_DECIMALS)} is not above {CM_MIN:g}: the "
                "process is not stable yet")
        head = f"Cm {_fmt(value, CM_DECIMALS)}"
    return f"{head}. {note}" if note else head


def label_for(key: str, change=None) -> str:
    """The item's words. With `change`: a change that ended before the
    cutoff reads a relabelled item with its old words (OLD_LABELS)."""
    if change is not None and key in OLD_LABELS and ended_before_cutoff(
            getattr(change, "status", None), ended_at(change)):
        return OLD_LABELS[key]
    return _BY_KEY.get(key, (key, None))[0]


def owner_for(key: str) -> str | None:
    return _BY_KEY.get(key, (None, None))[1]


# The rework of the checklist (Quality and Process Engineer rows, decision
# 2026-09-25; reworked 2026-09-26: APQP confirms the process stable alone,
# the Tool Engineer answers the cycle time, no Process Engineer row) ships
# in one deploy with one go-live instant. Default: 2026-09-26 04:00 UTC,
# i.e. midnight New York (EDT) on 26 Sep. Naive, in UTC, like released_at.
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
    "cycle_time_tool", "process_stable_apqp",
    "surface_quality", "technical_quality", "control_plan",
})
# Retired keys of the first catalog: a change that ended before the cutoff
# still owes (and shows) them like any other item. The other retired keys
# (process_parameters, process_fmea, quality_samples, quality_control_plan,
# and FIRST_VERSION below) were never live before the cutoff, so they belong
# to no change still running; an answer given to them is shown, read-only.
RETIRED_ORIGINAL: frozenset[str] = frozenset({
    "cycle_time_confirmed", "documents_updated",
})
# The Process Engineer rows of the first version of the 2026-09-26 rework
# (commit 0c7e5b47), live wherever that version ran before this
# correction. A change that FINISHED with one of them answered was released
# with that checklist and keeps it: the row stays counted there, and the
# row that replaced it is not added (SUCCESSOR_OF). On a change still
# running the answer is shown read-only, not counted.
FIRST_VERSION: frozenset[str] = frozenset({"cycle_time", "process_stable_pe"})
# New key -> the first-version key it replaces.
SUCCESSOR_OF: dict[str, str] = {"cycle_time_tool": "cycle_time"}

# Terminal change statuses (mirrors app.models.change.TERMINAL_STATUSES; not
# imported so the catalog stays free of model imports).
_FINISHED = ("released", "closed", "rejected", "cancelled")


def ended_at(change) -> datetime | None:
    """When a finished change ended: released (a closed change was released
    first), else cancelled, rejected or closed. None when it is not finished
    or carries no stamp (legacy data)."""
    status = getattr(change, "status", None)
    if status not in _FINISHED:
        return None
    stamps = {
        "released": ("released_at",),
        "closed": ("released_at", "rejected_at", "cancelled_at", "closed_at"),
        "cancelled": ("cancelled_at",),
        "rejected": ("rejected_at",),
    }[status]
    for field in stamps:
        value = getattr(change, field, None)
        if value is not None:
            return value
    return None


def ended_before_cutoff(status: str | None,
                        ended: datetime | None) -> bool:
    """A change that finished before the reworked rows went live. `ended`
    is when it finished (ended_at: released, cancelled, rejected or closed),
    naive UTC (an aware value is converted); a finished change without any
    stamp is legacy data and counts as ended before."""
    if status not in _FINISHED:
        return False
    if ended is None:
        return True
    if ended.tzinfo is not None:
        ended = ended.astimezone(timezone.utc).replace(tzinfo=None)
    return ended < release_rows_since()


def applies(key: str, status: str | None, ended: datetime | None,
            answered: bool = False, answered_keys=()) -> bool:
    """Whether this item is COUNTED on a change in this state (`ended`: see
    ended_at; `answered_keys`: every key the change has a row for). A
    finished change never gains a row it was not released with: an item
    added later is left off a change that finished before it existed, and
    a successor is left off a finished change that answered the row it
    replaced (SUCCESSOR_OF), unless answered there. A retired item of the
    first catalog belongs only to a change that ended before the cutoff; a
    FIRST_VERSION item only to a finished change that answered it;
    elsewhere a retired answer is shown read-only (retired_keys_for)."""
    before = ended_before_cutoff(status, ended)
    finished = status in _FINISHED
    if key in FIRST_VERSION:
        return finished and answered and not before
    if key in RETIRED:
        return before and key in RETIRED_ORIGINAL
    if (key in SUCCESSOR_OF and finished and not answered
            and SUCCESSOR_OF[key] in set(answered_keys)):
        return False
    if key in ADDED_LATER:
        return answered or not before
    return key in _BY_KEY


def keys_for(change, answered_keys=()) -> list[str]:
    """The keys that belong to (are counted on) this change, in display
    order. `answered_keys`: keys the change has a persisted row for."""
    done = set(answered_keys)
    status = getattr(change, "status", None)
    ended = ended_at(change)
    return [k for k in ORDER if applies(k, status, ended, k in done, done)]


def retired_keys_for(change, answered_keys=()) -> list[str]:
    """Retired keys shown read-only on this change: answered (done / n.a.)
    but no longer counted. `answered_keys`: keys with a done/na row."""
    counted = set(keys_for(change, answered_keys))
    done = set(answered_keys)
    return [k for k in ORDER if k in RETIRED and k in done and k not in counted]
