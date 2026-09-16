---
name: ecr-assessment-routing-2026-09-16
description: "Sep 16 ECR session: add-department mid-assessment (4-eyes), per-department risk types + templates, RASIC picker at scoping + 'not our responsibility'; where it sits, what is open"
metadata:
  type: project
---

# ECR session 2026-09-16 — routing and risks (branch `feature/sep-forms-engine`, NOT pushed)

Commits: `215ca64f` cancel teardown, `64033f4c` add department mid-assessment,
`c487f777` risk types + templates; RASIC picker + not-responsible committed after
(see git log). Migrations 066 (department_risk_templates) and 067
(change_meetings.department_rasic) applied on the local dev DB; **prod still at
064 — run alembic upgrade head after the deploy**.

## Rules that now exist (all in docs/CHANGE_MANAGEMENT_FLOW.md)
- **Add department in assessment** = routing deviation `add` with mandatory
  reason; lead decides (4-eyes; lead's own proposal → anyone else/PM). Pending
  blocks `in_assessment → costing`. Reject undoes the add (refused once the
  department answered). Approved deviations promote into the standard on
  release (pre-existing `promote_to_standard`).
- **Every routing deviation op needs a reason** (`apply_deviation`).
- **Risk vocabulary per department** in `backend/app/services/risk_types.py`
  (common: timing/cost/other + dept extras; legacy keys valid everywhere).
  Served with labels; validated per raising department.
- **Department risk templates** (`DepartmentRiskTemplate`): members/PM/admin
  write, soft delete, picked in the risk form, "save as template" tick.
- **RASIC at scoping**: meeting stores `{dept: R|A|S|C}` ("I" → C); routing
  stage 1 follows the room's letters; proceed needs one R/A. Attendance ≠
  responsibility (UI says so).
- **Not our responsibility**: R/A department declines in its bucket → reletter
  to C (+ optional add of who instead), same 4-eyes panel; reject restores the
  snapshot letter.

## Open / decided-by-default (flag to Christoph if it bites)
- Templates are per department, not per project.
- Decline is applied immediately (department off the hook until the lead
  rejects) — same semantics as the existing deviation model.
- Stacked deviations share one `deviation_note` (last wins).
- Series handover redesign (three handovers) is a separate, unstarted thread.

## Test approach that worked
Full backend suite must run in two chunks (~12 min each, background); the
600 s tool timeout kills a single run. Frontend `vitest run` full suite ~1 min.
See [[working-agreements]], [[ecr-buildout-2026-08-11]], [[assessment-impact-lock-2026-07-24]].
