"""ECR-solid rules (flow spec rev 6, §0 "HARD" and "Override").

Two kinds of rule hold a change:

- HARD: no override lifts it. They live in ChangeService.transition (and are
  mirrored by EarlyStageService.hard_refusal so no button is offered for a
  hop that is certain to be refused). Each has a fixed exit the rule names.
- SOFT: a guard in ChangeService._guard_reasons. Every soft refusal carries
  its rule key; an Override (a transition deviation) is bound to exactly
  that rule (C6), and a hop held by two soft rules needs two overrides.

Kept dependency-free (no models, no services) so the model layer, the
services and the API can import it without cycles.
"""
from __future__ import annotations

from typing import Optional


class GuardReason(str):
    """A soft guard's refusal text that also carries its rule key.

    A str subclass, so every caller that reads the text (messages, tests,
    the cockpit) keeps working; `.key` is what an override binds to."""

    key: str

    def __new__(cls, key: str, text: str) -> "GuardReason":
        obj = super().__new__(cls, text)
        obj.key = key
        return obj


# --- the reason pick of every override (spec §0 "always a reason pick") ----
OVERRIDE_REASONS = ("customer_date", "in_parallel", "not_applicable", "other")
# Absorb: why the money is not asked from the customer (spec §0 HARD #9).
ABSORB_REASONS = ("goodwill", "small_amount", "our_error", "other")

# --- who gives the OK (never the proposer) ---------------------------------
RUN = "run"            # the lead, a Project Management member or an admin
PM_MGMT = "pm_mgmt"    # a Project Management or Management member
QUALITY = "quality"    # a Quality member
APPROVER = "approver"  # the internal approver (engineering approvers, P9)

#: The rule Absorb is bound to: it clears `price_open` (HARD #9's exit).
ABSORB_RULE = "price_open"

#: Rules whose override is a commercial call (spec §0 Override).
PM_MGMT_RULES = frozenset({"scope_change_uncovered", "price_drop", ABSORB_RULE})
#: Validation rules are Quality's call wherever they hold.
QUALITY_RULES = frozenset({"validation_open", "validation_failed",
                           "validation_issues_open"})
#: Hops whose overrides are Quality's call (implementation start, release).
QUALITY_TARGETS = frozenset({"in_implementation", "released"})

#: English names of the soft rules (the UI owns the wording in both languages
#: under `rule.<key>`; these are for messages, logs and the changelog).
RULE_LABELS = {
    "capture_incomplete": "Capture incomplete",
    "no_impacted_items": "No impacted items",
    "no_lead": "No lead",
    "no_quote_deadline": "No quote deadline",
    "no_proceed_meeting": "No scoping decision 'proceed'",
    "assessments_open": "Assessments not all submitted",
    "not_feasible": "An assessment says 'not feasible'",
    "routing_deviation_pending": "Routing change waits for its decision",
    "costing_not_finalized": "Costing not finalized",
    "no_quoted_price": "No quoted price",
    "resulting_revisions_missing": "Impacted items without resulting revision",
    "impact_not_confirmed": "Impacted set not confirmed",
    "check_mapping_missing": "No check workflow for an item category",
    "timing_not_validated": "Timing not validated",
    "validation_open": "Validation checks still open",
    "validation_failed": "Validation check failed",
    "validation_issues_open": "Validation issues open",
    "check_workflows_open": "Revisions not through their check workflow",
    "release_checklist_open": "Release checklist incomplete",
    "lessons_missing": "Lessons learned not done",
    "plan_deviations_open": "Plan deviations open",
    "scope_change_uncovered": "Scope change not covered by an offer",
    "price_drop": "Accepted total lower than the last offer",
    ABSORB_RULE: "Price open",
}


def rule_label(key: Optional[str]) -> str:
    if not key:
        return "any open rule (before rule binding)"
    if key.startswith("gate:"):
        return f"D1 gate '{key[5:]}'"
    return RULE_LABELS.get(key, key)


def decider_group(rule_key: Optional[str], to_status: str,
                  customer_relevant: bool = True) -> str:
    """Who gives the OK on an override of this rule into this status."""
    if rule_key == ABSORB_RULE:
        return PM_MGMT if customer_relevant else APPROVER
    if rule_key in PM_MGMT_RULES:
        return PM_MGMT
    if rule_key in QUALITY_RULES or to_status in QUALITY_TARGETS:
        return QUALITY
    return RUN


#: The HARD list (spec §0), for the why-blocked panel and the docs: number,
#: rule, and the only exits.
HARD_RULES = {
    1: ("impact_lock", "Impacted set locked at proceed, never empty"),
    2: ("open_questions", "Open questions at proceed"),
    3: ("validation_failed", "Failed check or open validation issue at release; "
        "only exit: a concession (Quality)"),
    4: ("customer_acceptance", "Acceptance of the current offer + PM and "
        "Quality sign-off for approval"),
    5: ("rejection_letter", "Rejection letter before a rejected change closes"),
    6: ("run_team_hop", "Mid-flow hops are the run team's"),
    7: ("ppap_decision", "Internal: ppap_decision before proceed"),
    8: ("internal_approval", "Internal: approval by an engineering approver "
        "who is not the raiser"),
    9: ("signoffs_and_price", "Release: sign-offs bound to the latest offer "
        "sent; close: no open price (exits: acceptance or Absorb)"),
    10: ("own_items", "Own check items and questions at the department's submit"),
}


#: Evidence words that say nothing (spec §0 Evidence).
EMPTY_EVIDENCE = frozenset({"ok", "okay", "tbd", "na", "n/a", "done", "checked",
                            "yes", "-", "--"})


def reference_refusal(text: Optional[str], what: str = "A reference") -> Optional[str]:
    """None when `text` is a usable reference id (>= 5 characters and not an
    empty word like 'ok' or 'tbd'), else why not."""
    value = (text or "").strip()
    if not value:
        return f"{what} is required (document number, mail or file reference)"
    if value.lower() in EMPTY_EVIDENCE or len(value) < 5:
        return (f"{what} must name the evidence (at least 5 characters, e.g. "
                "the PSW or mail reference): '"
                + value + "' says nothing")
    return None
