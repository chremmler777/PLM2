"""Switches for change-management steps that are parked, not deleted.

Kept dependency-free so the model, the services and the API can all read
them without import cycles. Read the attribute at call time (never copy it
into a local constant at import), so a test can flip it with monkeypatch.
"""
from __future__ import annotations

# Development's "confirm the impacted parts" step inside scoping (Task 18).
# Off since the first live ECR test (2026-10-14): parts are still picked in
# scoping (lead, PM, Development), and the impacted set locks automatically
# when the scoping meeting decides 'proceed' (a mother-plant change: when it
# goes scoping -> approved). The confirm code, task and button stay in place
# for a later reuse; flip this to True to bring the manual step back.
IMPACT_CONFIRM_STEP_ENABLED = False


def impact_confirm_step(change) -> bool:
    """Whether this change locks its impacted set by Development's manual
    confirm. An engineering review always does: there the lock is the act
    that opens the review, and no meeting ever decides 'proceed'."""
    if getattr(change, "origin", None) == "engineering_review":
        return True
    return bool(IMPACT_CONFIRM_STEP_ENABLED)


# Scoping is a team task led by the PM (Christoph 2026-10-27): questions and
# check items are raised in the meeting by Project Management or the change
# lead; a cancel vote stays open to everyone. Off = anyone may ask again.
SCOPING_QUESTIONS_PM_ONLY = True

# Scoping takes blocking questions only (Christoph 2026-10-27: "check items I
# would not even put in there, otherwise it becomes a whole debate"): no new
# check items; technical checks belong in the departments' assessments. Old
# check items keep working. Off = check items again.
SCOPING_QUESTIONS_ONLY = True

# No proceed out of scoping without the PM's written scope (Christoph
# 2026-10-27: "scope needs to be defined, otherwise I don't let it go").
SCOPE_REQUIRED = True

# A Confirmed answer without a filed mail / document / reference is allowed
# (Christoph 2026-10-28: forcing the customer's mail is overboard; warn
# instead). It then needs the answer in words and is logged "no proof
# attached". True brings back the hard evidence rule.
CONFIRM_EVIDENCE_REQUIRED = False

# ---------------------------------------------------------------------------
# ECR-solid switch groups (spec flow-spec rev 6, "Switches"). Every new HARD
# gate and every new notification of the branch reads one of these at call
# time, so a group can be switched off without a deploy of the code behind
# it. All default ON; each group is tested ON and OFF.
# ---------------------------------------------------------------------------
# C33 quick add, C13, intake (C9, live-change check, supersede, rechecks).
SCOPING_V2 = True
# C8, C20 due rules, C5, supplier wait, no-cost button, costing basis,
# quote-vs-estimate.
ASSESSMENT_V2 = True
# C1 run-team hops, C6, C12, C14, acceptance binding, scope change card,
# supplement, price diff, Absorb.
COMMERCIAL_V2 = True
# C7, computed checks, Fix task, concession, newer-index guard, sign-offs at
# release, C27 digest.
RELEASE_V2 = True
# §7a start at risk (P8 decided: yes, urgent only).
START_AT_RISK = True

SWITCH_GROUPS = ("SCOPING_V2", "ASSESSMENT_V2", "COMMERCIAL_V2", "RELEASE_V2",
                 "START_AT_RISK")


def on(name: str) -> bool:
    """Is this switch group on? Read at call time (monkeypatch-friendly)."""
    if name not in SWITCH_GROUPS:
        raise KeyError(f"Unknown switch group '{name}'")
    return bool(globals()[name])

# Who the scoping room starts from (Christoph 2026-10-28: "standard I say
# Tool Engineer, APQP, Development, Manufacturing Engineering; the rest is not
# needed until implementation in most cases; sometimes Packaging, already
# rare"). Per change type: the standard's other assessors stay offered as
# "sometimes" but are not pre-marked; the raiser's own department stays
# auto-R. A type not listed here pre-marks its standard as before.
SCOPING_PRESELECT = {
    "physical_part": ("Tool Engineer", "APQP", "Development", "Manufacturing Engineer"),
}
