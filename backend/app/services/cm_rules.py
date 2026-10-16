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

import re

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
# §7 [R4] price diff: why the accepted total is below the last version sent.
PRICE_DROP_REASONS = ("volume", "competitor", "goodwill", "error")
#: The rule a lower accepted total is held by (SOFT, PM / Management OK).
PRICE_DROP_RULE = "price_drop"

# --- who gives the OK (never the proposer) ---------------------------------
RUN = "run"            # the lead, a Project Management member or an admin
PM_MGMT = "pm_mgmt"    # a Project Management or Management member
QUALITY = "quality"    # a Quality member
APPROVER = "approver"  # the internal approver (engineering approvers, P9)

#: Who gives the OK, in words (messages; the UI owns its own wording).
DECIDER_WORDS = {
    RUN: "the lead, a Project Management member or an admin",
    PM_MGMT: "a Project Management or Management member",
    QUALITY: "a Quality member",
    APPROVER: "the internal approver (never the raiser)",
}

#: The rule Absorb is bound to: it clears `price_open` (HARD #9's exit).
ABSORB_RULE = "price_open"

#: Rules whose override is a commercial call (spec §0 Override).
PM_MGMT_RULES = frozenset({"scope_change_uncovered", "price_drop", ABSORB_RULE})
#: Validation rules are Quality's call wherever they hold.
QUALITY_RULES = frozenset({"validation_open", "validation_failed",
                           "validation_issues_open"})
#: Soft rules that are decided, never overridden: they have their own
#: decision (the routing change: Project Management approves or refuses the
#: added department), so an override would be a second road to it.
DECIDE_ONLY_RULES = {
    "routing_deviation_pending": ("Decide the routing change (the added "
                                  "department) in the Assessments tab: it is "
                                  "decided, not overridden"),
}

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
    "assessments_open": "Assessments open",
    "not_feasible": "Assessment 'not feasible'",
    "routing_deviation_pending": "Routing change waits for its decision",
    "costing_not_finalized": "Costing not finalized",
    "no_quoted_price": "No quoted price",
    "resulting_revisions_missing": "Items without a resulting revision",
    "impact_not_confirmed": "Impacted set not confirmed",
    "check_mapping_missing": "No check workflow for an item category",
    "timing_not_validated": "Timing not validated",
    "validation_open": "Validation checks open",
    "validation_failed": "Validation check failed",
    "validation_issues_open": "Validation issues open",
    "check_workflows_open": "Check workflows not finished",
    "tool_change_open": "Tool change not done",
    "release_checklist_open": "Release checklist open",
    "lessons_missing": "Lessons learned missing",
    "plan_deviations_open": "Plan deviations open",
    "scope_change_uncovered": "Scope change not covered by an offer",
    "price_drop": "Accepted total below the last offer",
    "achieved_missing": "Achieved value not entered",
    "index_pending": "Newer index pending",
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


#: An override or Absorb note says what covers the skipped rule (R4): a
#: sentence, not a word. "Customer date" names the date or the mail.
NOTE_MIN_CHARS = 15


def override_note_refusal(reason_code: Optional[str], note: Optional[str],
                          *, codes: tuple = OVERRIDE_REASONS) -> Optional[str]:
    """None when the reason pick and note of an override (or an Absorb,
    codes=ABSORB_REASONS) are usable, else why not (spec §0: always a
    reason pick; evidence, not 'ok')."""
    if not reason_code:
        return f"Pick a reason: one of {', '.join(codes)}"
    if reason_code not in codes:
        return f"Unknown reason '{reason_code}': one of {', '.join(codes)}"
    value = (note or "").strip()
    if len(value) < NOTE_MIN_CHARS or value.lower() in EMPTY_EVIDENCE:
        return (f"Say what covers it in a sentence (at least {NOTE_MIN_CHARS} "
                f"characters): '{value}' says too little")
    if reason_code == "customer_date" and not any(c.isdigit() for c in value):
        return ("Customer date: name the date or the customer's mail reference "
                "(e.g. 'SOP 24 Oct per mail 2026-10-12')")
    return None


def reference_refusal(text: Optional[str], what: str = "A reference",
                      example: str = "a document number, a mail or a file name"
                      ) -> Optional[str]:
    """None when `text` is a usable reference id (>= 5 characters and not an
    empty word like 'ok' or 'tbd'), else why not, in one plain sentence
    with an example that fits the basis (`example`)."""
    value = (text or "").strip()
    if not value:
        return f"{what} is required, e.g. {example}"
    words = re.findall(r"[A-Za-z0-9ÄÖÜäöüß]+", value)
    # 'n/a n/a', 'ok ok': only empty words or letters; 'asdfg': one word with
    # no number (R4: a document number, a date, or words that name it)
    empty = all(w.lower() in EMPTY_EVIDENCE or len(w) <= 2 for w in words)
    named = any(c.isdigit() for c in value) or len(words) >= 2
    if value.lower() in EMPTY_EVIDENCE or len(value) < 5 or empty or not named:
        return (f"{what}: '{value}' says nothing. Name the evidence (at least "
                f"5 characters: a number, a date or a few words), e.g. {example}")
    return None


def says_what(text: Optional[str]) -> bool:
    """Evidence in words (spec §0, §4): a reference that names something
    (reference_refusal passes) or a number with its unit ("+0.4 s").
    "ok", "checked" and the like say nothing."""
    v = (text or "").strip()
    if not v or v.lower() in EMPTY_EVIDENCE:
        return False
    return reference_refusal(v) is None or (
        any(c.isdigit() for c in v) and any(c.isalpha() for c in v))
