---
name: assessment-impact-lock-2026-07-24
description: Assessment is hard-gated behind a locked impacted set; recall path added; CR-2026-0002 pulled back to scoping
metadata:
  type: project
---

# Assessment impact-lock gate (2026-07-24)

**Why:** Christoph wanted CR-2026-0002 back in scoping so the impacted set —
articles, assembly stations, gauges — is fully defined before assessment fans out.

**What changed** (commit `22562c73` on `main`):

- `-> in_assessment` is a **hard gate** on `impact_confirmed_at`. It lives in
  `ChangeService.transition()`, not `_guard`, so an approved
  `ChangeTransitionDeviation` cannot bypass it. It is evaluated **after** the soft
  guards — so "no deadline" / "no proceed meeting" still surface their own
  reasons — and **before** a deviation is consumed, so a refused attempt does not
  burn one. Ordering matters; moving it earlier breaks ~8 tests.
- New `in_assessment -> scoping` recall, refused once any assessment is submitted
  or carries a non-pending verdict. `ChangeRoutingService.teardown_routing` clears
  assessments, wf instances and routing so a corrected set rebuilds cleanly.
- `impact_confirm` in `my_actions` moved from `approved` to `scoping`; the cockpit
  blocker fires in both.

**Consequence to remember:** a change that reaches `approved` is now always
locked, so the old kickoff guard (`impact_not_confirmed`) only fires when a later
edit to the impacted set clears the lock via `_reset_impact_confirmation`.

**Test helper:** `tests/conftest.lock_impact(session_factory, change_id)` stamps
the lock directly. Any test driving `scoping -> in_assessment` needs it.

**Live:** CR-2026-0002 recalled to `scoping` — 9 assessments, 1 routing, 1 wf
instance torn down, recorded in changelog + audit log.

See [[change-flow-rework-2026-07-23]] and [[equipment-numbering-2026-07-24]].
