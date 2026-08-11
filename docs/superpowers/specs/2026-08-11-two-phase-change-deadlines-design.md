# Two-phase change deadlines (quote-by + release-by)

**Date:** 2026-08-11
**Status:** Approved

## Problem

A change request today carries a single Sales-set deadline
(`required_by_date`) with a computed on_track/at_risk/overdue state. The
real flow has two commitments: first the change must be *quoted* by a
date, then — once the customer accepts — it must be *released* by a
(new, later) date. One field cannot express both.

## Decision summary

- The existing `required_by_*` field group is reinterpreted as the
  **quote deadline** ("quoted by"). Existing data keeps its meaning; no
  data migration needed.
- A new **release deadline** field group is added:
  `release_due_date`, `release_due_reason`, `release_due_set_by`,
  `release_due_set_at` on `change_requests`, plus a `quoted_at`
  timestamp (one Alembic migration).
- **Sales sets the release deadline when recording customer acceptance**
  — the field is mandatory in that dialog/API call; acceptance without a
  release date is rejected (422).
- **Internal path** (non-customer-relevant, costing → approved via PM
  internal approval): no quote deadline at all. The PM sets the release
  deadline in the internal-approval dialog (also mandatory there).
- Both deadlines remain editable afterwards by the roles that set them,
  with the existing audit-log pattern (`field_name="required_by_date"` /
  `"release_due_date"`).

## Phase logic (`deadline_state`)

`ChangeService.deadline_state` becomes phase-aware and computes against
whichever deadline is *active* for the change's current status:

| Phase | Customer-relevant | Internal |
|---|---|---|
| captured…costing | quote deadline drives on_track/at_risk/overdue | no active deadline |
| quoted (waiting on customer) | quote deadline fulfilled; frozen fact "quoted on time / quoted late" | n/a |
| approved…in_validation | release deadline drives the state | release deadline drives the state |
| terminal (released/closed/rejected/cancelled) | None (unchanged) | None |

- The at-risk heuristic is unchanged: remaining workflow stages ×
  `DEFAULT_TASK_DUE_DAYS` vs. days left to the active deadline.
- "Quoted on time / quoted late" is determined by comparing a new
  `quoted_at` timestamp column (stamped on transition to `quoted`, same
  pattern as `released_at`/`closed_at`) against `required_by_date`, and
  is frozen from then on — an overdue quote deadline stops nagging once
  the change is quoted.
- A change with no active deadline (e.g. internal change before
  approval) returns `None` as today.

## Surfaces

- **Cockpit banner** (`CockpitSummary`): shows the active deadline and
  its state; in `quoted` it shows the frozen "quoted on time/late" fact;
  after approval it switches to the release deadline.
- **My Actions / lead escalations**: computed from the active deadline
  only.
- **Changes list**: shows whichever deadline is live for each row.
- **Customer-response dialog**: gains a required release-date field
  (+ optional reason) shown only when the response being recorded is
  "accepted".
- **Internal-approval dialog**: gains the same required release-date
  field.

## API changes

- `record_customer_response(..., response="accepted")` requires
  `release_due_date` (optional `release_due_reason`); rejects otherwise.
- Internal approval endpoint requires the same.
- Change read schema adds `release_due_date`, `release_due_reason`,
  `release_due_set_by/at`, and keeps the single computed
  `deadline_state` (now phase-aware) plus a small indicator of which
  deadline is active (e.g. `active_deadline: "quote" | "release" |
  null`) and the frozen `quoted_on_time: bool | null`.
- Change update keeps accepting `required_by_date` edits (quote
  deadline) and additionally accepts `release_due_date` edits once the
  change is accepted/approved, both audit-logged.

## Testing

Backend:
- `deadline_state` per phase for both paths (customer-relevant and
  internal), including frozen quoted-on-time/late and terminal → None.
- Acceptance without `release_due_date` → 422; with it → stored with
  set_by/set_at and audit entry.
- Internal approval without release date → 422.
- Release-deadline edits audit-logged.

Frontend:
- Banner rendering per phase (quote active, frozen quoted fact, release
  active).
- Customer-response dialog: release-date field appears only for
  "accepted" and blocks submit when empty.
- Internal-approval dialog: same validation.

## Out of scope

- No generic `change_deadlines` table — two field groups on the change
  are enough for the two kinds that exist (YAGNI).
- No changes to workflow templates or task due-date derivation.
- No notification/email machinery beyond the existing surfaces.
