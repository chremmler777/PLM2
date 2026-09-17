---
name: ecr-assessment-routing-2026-09-16
description: "Sep 16 ECR session: add-department mid-assessment (4-eyes), per-department risk types + templates, RASIC picker at scoping + 'not our responsibility'; where it sits, what is open"
metadata:
  type: project
---

# ECR session 2026-09-16 — routing and risks (branch `feature/sep-forms-engine`, NOT pushed)

Commits: `215ca64f` cancel teardown, `64033f4c` add department mid-assessment,
`c487f777` risk types + templates; RASIC picker + not-responsible committed after
(see git log). Migrations 066 (department_risk_templates), 067
(change_meetings.department_rasic) 068 (department_risk_types), 069 (department_cost_categories) and 070 (costing_positions.vendor_name) applied on the local dev DB; **prod still at
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
- **Department-defined risk types** (`DepartmentRiskType`, mig 068): "+ Add own
  risk type…" in the dropdown, namespaced keys `d<dept>_<slug>`, soft delete
  keeps raised rows valid. Christoph's original ask ("define one on my own").
- **RASIC at scoping**: meeting stores `{dept: R|A|S|C}` ("I" → C); routing
  stage 1 follows the room's letters; proceed needs one R/A. Attendance ≠
  responsibility (UI says so).
- **Not our responsibility**: R/A department declines in its bucket → reletter
  to C (+ optional add of who instead), same 4-eyes panel; reject restores the
  snapshot letter.

- **Costing table** (commit after 2c64a66b): one table per department, standing
  rows + category-driven lines (own time | estimate | vendor quote), categories
  coded per department with entry_type + department-defined
  (`department_cost_categories`, mig 069). New position kind `own_time`.
  Plant grid collapsible under the table. Matrix of what each department can
  enter lives in `costing_tags.py`.

- **Vendors = Suppliers master data**: vendor fields (offers + estimated
  lines) are datalists over `/v1/suppliers`; a new name is POSTed on save.
- **Costing close/reopen**: PM may close costing (costing → quoting) besides
  Sales/lead/admin; reopen (quoting → costing) needs a reason, logged
  `costing_reopened`, button on the commercial tab. Send stays Sales-only.

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
