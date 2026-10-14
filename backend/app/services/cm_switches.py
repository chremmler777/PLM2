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
