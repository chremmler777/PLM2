# Change Flow Realignment — "Path to Quote" (Milestone 1)

**Date:** 2026-07-04
**Status:** Draft for review
**Scope:** ChangeRequest lifecycle from capture to approval. Implementation phase (ECN, validation, release) is untouched and will be addressed in Milestone 2.

## Problem

The implemented flow forces commercial decisions onto the initiator before any technical input exists:

1. All three gates (feasibility / budget / release) are seeded at creation, so the feasibility/budget question lands on the initiator/lead on day one — but cost figures only emerge from the technical departments' assessments.
2. There is no pre-determination step. After `captured`, all nine departments immediately receive assessment tasks, with no scope-clarification in between.
3. Every change runs toward `quoted`, but internal changes have no customer quote — they need internal cost approval instead.
4. Bug cluster: the sales deadline ("final date") appears not to save — the edit control is buried in the overview tab while the read-only chip sits in the cockpit header; same-day dates parse to UTC midnight and instantly render "overdue"; the PATCH response omits `deadline_state`.

## Target flow

```
captured ──► scoping ──► in_assessment ──► costing ──┬─► quoted ──► approved   (customer_relevant)
                │                                    └─────────► approved      (internal, PM cost approval)
                └─► rejected (scoping decision "reject")
```

Side-exits (`on_hold`, `cancelled`, `rejected`) remain available as today.

### 1. Capture (initiator: Sales, PM, or Development)

- Fields as today: title, reason, description, change_type, customer_relevant, priority, attachments (PPT / 3D / sketch already supported), requested deadline (`required_by_date`).
- **No gates are seeded at creation.** The feasibility question is answered by the scoping stage; the budget question by the path split.
- Transition `captured → scoping` replaces `captured → in_assessment`.

### 2. Scoping — pre-determination stage (owner: Project Management)

New status `scoping` between `captured` and `in_assessment`, driven by a **meeting-notes module**:

- A `ChangeMeeting` record on the change: meeting date, participants (free-pick from users + free-text externals), notes (rich text), decision, and **selected impacted departments**.
- Decision values: `proceed` / `reject` / `needs_info`.
  - `proceed` → kicks off assessment directly from the meeting record: assessment tasks are created **only for the departments selected in the meeting**, and the change transitions `scoping → in_assessment`. This replaces the old feasibility gate.
  - `reject` → change transitions to `rejected` with the meeting note as rationale.
  - `needs_info` → change stays in `scoping`; the open questions are captured in the notes and resolved in a follow-up meeting record (a change can hold multiple meeting records).
- Guard: `scoping → in_assessment` requires a meeting record with decision `proceed` and ≥1 selected department. Impacted items (≥1) and lead are still required, as today.
- Multiple meetings per change are allowed (e.g. first meeting `needs_info`, second `proceed`). The kickoff uses the latest `proceed` meeting's department selection.
- PM-or-admin gated: creating/deciding meetings requires the PM role (department "Project Manager" membership) or admin.

### 3. Assessment (technical departments — cost origin)

Mechanically as today, with two changes:

- **Scoped fan-out:** assessment tasks are created only for the departments flagged in the scoping meeting, not all nine.
- **Tracked effort per feasibility check:** each `ChangeAssessment` gets an `effort_hours` field (decimal, entered by the assessor when submitting) recording time spent on the assessment itself. Shown per department and totaled in the summation view, so assessment effort is visible alongside the change cost.
- Cost lines keep **internal and external cost** columns as today (`AssessmentCostLine.internal_cost` / `external_cost`); both must survive into the summation, quote basis, and later P&L.

### 4. Summation & path split (PM)

`in_assessment → costing` guard stays: all routed assessments submitted, none `not_feasible`, no pending routing deviation. The old budget gate at this point is removed; from `costing` the path branches on `customer_relevant`:

- **Customer branch** (`customer_relevant = true`): `costing → quoted → approved` as today. Sales sets `quoted_price` from the rollup (internal + external cost visible side by side); customer response `accepted` + PM/Quality sign-offs still required for `approved`.
- **Internal branch** (`customer_relevant = false`): `costing → approved` directly, gated by a new **internal cost approval**: PM (or admin) approves the summation total. Recorded with approver, timestamp, approved amount snapshot, and optional note. No quote step. (Threshold rules — e.g. above X € needs higher sign-off — are explicitly out of scope for now; the approval record is structured so a threshold check can be added later.)

### Gates model

- `feasibility` gate: **retired** — superseded by the scoping meeting decision.
- `budget` gate: **repurposed/retired** — superseded by quote acceptance (customer branch) or internal cost approval (internal branch).
- `release` gate: **kept** — still guards `→ in_implementation`, untouched in this milestone.
- Existing changes with seeded gates: migration marks feasibility/budget gates of non-started changes as superseded; in-flight changes past `in_assessment` keep their current gate state so history stays truthful.

### P&L hook (forward-looking, no UI in this milestone)

Cost data must stay structured for a later P&L view: per change, `quoted_price` (customer branch) or approved internal amount vs. summation of internal + external cost lines → margin. This milestone only guarantees the data shape (approval amount snapshot, cost line internal/external split, effort hours); the P&L report itself comes later.

## Deadline ("final date") fixes

1. Move the deadline edit control into the cockpit header next to the `DeadlineChip` (inline edit: date + reason), instead of the overview tab.
2. Date-only semantics: the frontend sends the picked day as 23:59:59 UTC of that date, and `deadline_state` only reports `overdue` once the day has fully passed — choosing today never immediately renders "overdue".
3. PATCH `/v1/changes/{id}` response recomputes `deadline_state` before returning (parity with GET/list/confirm).
4. Keep `required_by_reason` untouched when a PATCH sends only `required_by_date` (currently nulled implicitly).

## Data model changes (summary)

- `ChangeRequest.status`: new value `scoping`; transition map updated (`captured → scoping → in_assessment`; `costing → approved` for internal branch).
- New `ChangeMeeting` table: change_id, meeting_date, participants (JSON), notes, decision, selected department ids (JSON), created_by/at, decided_by/at.
- `ChangeAssessment.effort_hours` (nullable decimal).
- New `ChangeInternalApproval` table (or fields on ChangeRequest): approved_by/at, approved_amount_snapshot, note.
- Gate seeding: only `release` gate seeded at creation.
- Alembic migration (SQLite + Postgres compatible, idempotent guards as per house pattern), including status/transition backfill for in-flight changes: `captured` changes stay `captured` (their first transition now targets `scoping`); changes already in `in_assessment`+ are unaffected.

## Frontend changes (summary)

- Cockpit: stage cards reflect new sequence; "Next" actions offer `Start scoping`, meeting module entry point.
- New scoping/meeting panel: create meeting, notes editor, participant picker, department multi-select, decision buttons, "kick off assessment" action on `proceed`.
- Assessment submit form: effort hours input (required on submit).
- Summation view: internal/external cost columns + effort total; internal branch shows "Approve internal costs" (PM); customer branch shows quote step as today.
- Deadline chip becomes editable in cockpit header.
- DE/EN labels per existing i18n pattern.

## Testing

- Backend: transition-map tests for new statuses/branches; scoping guard tests (proceed/reject/needs_info, department fan-out); effort_hours persisted; internal approval gate; deadline PATCH returns fresh `deadline_state`; migration up/down on SQLite and scratch Postgres.
- Frontend: meeting module component tests; deadline same-day not overdue; cockpit next-actions per branch.

## Out of scope (Milestone 2+)

- Implementation phase redesign (ECN, validation, release).
- P&L report/dashboard.
- Approval threshold rules.
- Notification coverage for meeting invitations (bell notifications for assessment tasks follow the existing pattern).
