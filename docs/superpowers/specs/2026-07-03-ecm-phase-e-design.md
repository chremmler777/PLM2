# ECM Phase E — Engine Unification, Sales Deadline, Notifications, Reporting

**Date:** 2026-07-03
**Status:** Approved design, pending implementation plan
**Parent spec:** `2026-07-02-ecm-lifecycle-design.md` (phases A–D delivered on
`feature/change-assessment-routing`)

## Goal

Finish the ECM lifecycle work: collapse the two parallel execution engines into
one (the parent spec's "retired over time" decision), give Sales a change-level
deadline with at-risk tracking, deliver the in-app notification inbox the
Notification model was built for, and put a KPI dashboard on top of the
now-stable data model. Close the remaining debt (org/plant scoping, tsc
baseline) and merge the branch to main.

## Decisions (agreed 2026-07-03)

| Topic | Decision |
|---|---|
| Consolidation depth | **Full engine unification** (user chose over shared-logic convergence): the workflow engine becomes the execution spine for the assessment phase; `change_routing_service`'s advancement machinery is deleted. |
| `ChangeAssessment` fate | Demoted to **task payload**, not deleted: D1 substance (verdict, cost impact, cost lines, producibility, conditions, lifecycle cost) stays on the record, linked 1:1 to its `WfInstanceTask`. Execution fields (`status`, `stage_order`, `rasic_letter`, owner/due-date columns) become read-through from the task. |
| Deadline behavior | Target date + at-risk tracking. Non-blocking: no gate, no deviation needed to finish late. |
| Notification channels | In-app only; email is a possible later add-on. |
| Reporting architecture | Live SQL aggregates, no snapshot/materialized tables at current data volume. |
| Compliance KPIs view | Not selected — out of scope for the dashboard (audit timeline from Phase D remains the audit surface). |

## Stream 1 — Engine unification

### Change-scoped workflow instances

- `WfInstance` gains nullable `change_id` FK; `part_revision_id` becomes
  nullable; CHECK constraint: exactly one of (`change_id`,
  `part_revision_id`) is set.
- On change **submit** (where `ChangeRoutingService.build_routing` runs today)
  the system spawns one instance from the "ECM Bewertung" template (resolved
  via `ChangeRoutingStandard`, per-change snapshot preserved in
  `ChangeRouting.standard_snapshot` as today).
- `workflow_service` owns stage activation, RASIC semantics (R/A block, S/C
  cascade, I notify), due dates, ownership/accept, escalation — for assessment
  instances exactly as for ECN check instances. One engine, one semantics.

### Assessment as payload

- `ChangeAssessment.task_id` FK (unique) to `WfInstanceTask`.
- Submitting an assessment = completing its R-task with payload
  (verdict/costs/etc.) written in the same transaction; waiving = the existing
  task-waive path. Cost lines (`AssessmentCostLine`) untouched — they keep
  hanging off the assessment, so **no cost data migrates**.
- Execution columns on `ChangeAssessment` are kept in the schema during Phase E
  (dropped in a later cleanup once the UI no longer reads them) but are no
  longer written by new code paths; API responses read execution state from the
  task.

### Deletions / survivors in `change_routing_service`

| Piece | Fate |
|---|---|
| `maybe_advance`, stage math, blocking logic, private due-date/escalation code | Deleted — replaced by `workflow_service` |
| `blocking_complete` (submit→approve guard) | Becomes an instance-stage query on the change-scoped instance |
| `build_routing` | Becomes "spawn assessment instance + payload rows" |
| `resolve_standard`, `promote_to_standard` (template promotion on release) | Stay |
| `ChangeRouting` model | Survives as standard snapshot + routing-deviation governance record only |
| Routing deviations (`apply_deviation`) | Mechanism unchanged; its effect re-targets the instance's tasks |

### Migration (highest-risk item)

One idempotent, inspect-guarded Alembic migration:

1. For every change with a `ChangeRouting` but no change-scoped instance:
   synthesize a `WfInstance` (+ tasks) from `standard_snapshot`, mirroring
   current stage/status so behavior is identical before/after.
2. Link each existing `ChangeAssessment` to its synthesized task (match on
   department + stage_order + rasic_letter); mirror owner/due-date/accepted
   onto the task.
3. Released/closed changes get `completed` instances for audit consistency.
4. Unmatchable assessments (deviated routings that added rows) get tasks
   synthesized from the assessment itself — nothing is dropped.

Exhaustive before/after tests on seeded in-flight states (each lifecycle
status × deviation present/absent × waived rows).

### Frontend

- D1 panel, stage cards, routing view re-point to a unified endpoint (task +
  payload joined). My Tasks collapses to one source (all work is
  `WfInstanceTask`s now).
- **No visible behavior change** — this stream is architectural; existing
  component tests keep passing with adjusted fixtures.

### Audit

Instance spawn, task completion-with-payload, waives, and the migration itself
write to the unified `AuditLog` (correlation id = change number), as all
engines already do.

## Stream 2 — Sales deadline & at-risk tracking

- `ChangeRequest` new columns: `required_by_date` (DateTime, nullable),
  `required_by_reason` (Text), `required_by_set_by` (FK users),
  `required_by_set_at`. Settable/editable from the cockpit by Sales or the
  lead; every set/change is an audited event (old → new date in payload).
- Computed status (service-level, not stored): **on_track / at_risk /
  overdue**. `at_risk` = sum of default due-days of remaining open stages (from
  the template) no longer fits before `required_by_date`; `overdue` = date
  passed and change not closed/released.
- Surfaces: countdown chip on cockpit header + changes list; escalation entry
  for the lead when a change flips to at_risk/overdue; feeds the on-time-rate
  KPI (Stream 4) and notifications (Stream 3).

## Stream 3 — In-app notifications

- **Coverage matrix** (emitted at service sites via existing
  `NotificationService`): task assigned / ownership accepted, RASIC 'I' events
  (uniform now — one engine), due-soon (T-2 days) and overdue flips,
  escalations, transition deviations awaiting 4-eyes decision, deadline
  at_risk/overdue flips.
- Dedup per (user, event type, subject id) so recomputes don't spam; due-soon /
  overdue computed in the same pass that already computes escalations.
- **API:** list (paged, unread filter), unread count, mark-read, mark-all-read.
- **UI:** bell + unread badge in the top bar; dropdown inbox grouped by change,
  newest first; click navigates to the exact tab/item (reuse the Phase D
  act-in-place jump targets). Dark-slate, DE/EN labels.

## Stream 4 — Reporting & KPIs

`ReportService` + `/api/v1/reports/*`, live SQL aggregates, one dashboard page
with three views (each number click-through to the filtered list behind it):

1. **Pipeline & cycle times** — funnel per lifecycle status, throughput/month,
   avg days per stage (from audit timeline timestamps), on-time vs. deadline
   rate.
2. **Overdue & workload** — open tasks per department and per owner, overdue
   counts, active escalations, at-risk changes.
3. **Cost roll-up** — budget vs. actual from cost lines, grouped by project and
   plant.

Org/plant scoping (below) applies to all report queries from day one.

## Debt items (in scope)

- **Org/plant scoping on change queries** — the known gap from the parent
  spec: change list/report queries filter by the user's organization; plant
  filter where `affected_plant_ids` applies.
- **tsc baseline** — burn down the 21 pre-existing frontend type errors to 0;
  CI-able `tsc --noEmit` from then on. Repo-wide lint: fix what the touched
  files surface; a full lint-zero campaign stays out of scope.
- **Merge to main** — after final verification: push branch, merge to main
  (user confirmation required before push; outward-facing action).

## Stream order & dependencies

1 (unification) → 2 (deadline) → 3 (notifications) → 4 (reporting).
Rationale: notifications want one engine to hook uniformly; reporting reads
what 1–2 stabilize. Debt items ride along where they touch (org-scoping lands
with Stream 4's queries at the latest; tsc burn-down last, before merge).

## Testing

- TDD per task. Stream 1 gets the heaviest battery: engine-equivalence tests
  (same scenario through old fixtures vs. new engine → same outward behavior),
  exhaustive migration tests, RASIC semantics regression suite.
- Deadline: boundary tests around at_risk computation (fits exactly / off by
  one day / no template due-days).
- Notifications: dedup, coverage matrix (one test per event type), mark-read
  idempotence.
- Reports: fixture-seeded aggregate correctness incl. org/plant scoping and
  empty-data shapes.
- Frontend: component tests for bell/inbox, deadline chip, dashboard cards;
  existing suites stay green throughout.

## Execution guidance (per parent spec)

Model tiering: opus/high tier for Stream 1 (engine semantics, migration) and
review passes; sonnet for Streams 2–4 feature work; haiku for mechanical work
(label maps, simple CRUD wiring, tsc burn-down mechanics). Never trade
correctness for cost.

## Stream 5 — "Make it a real workflow" (merged 2026-07-03 from the agreed
## kickoff scope in memory/ecm-phase-e-kickoff.md)

User decision 2026-07-03: merge the previously agreed Phase E scope into this
phase rather than deferring it.

1. **Department membership admin:** Users-page multi-select departments
   dropdown (admin assigns), backed by GET/PUT user-departments endpoints;
   dev membership seeds so tasks flow immediately on both dev DBs.
2. **Enforcement:** department membership required to act (falls out of
   Stream 1 — submissions run through `complete_task`); the change page is
   role-aware: your actionable pieces highlighted, the rest read-only.
3. **My-Tasks-first:** cockpit answers "what do I do now" for the current
   user — a panel listing *their* open actions on this change.
4. **Engineering owns the affected-items decision** (user decision
   2026-07-02): the lead proposes impacted items; an R&D department member
   confirms. Mechanism: `impact_confirmed_by/at` on `ChangeRequest`, a
   confirm endpoint restricted to R&D members, and the
   `approved -> in_implementation` guard requires confirmation. Cockpit
   shows the pending-confirmation state and offers the action in place to
   R&D users.
5. **English seed names:** rename seeded template/stage/step names
   (ECM Bewertung → ECM Assessment, ECN Umsetzung → ECN Implementation, …).
   Standards match templates BY NAME — existing rows in both dev DBs are
   renamed by a startup repair; tests updated.
6. **Plant defaults + cleanup:** consolidate duplicate plants ("USA" vs
   "USA Toccoa", "Main Factory" test junk), default plant = project plant
   else USA (interim decision); locate and fix the stray Weissenburg (WUG)
   default.
7. **Audit deferral bundle** (from the Phase D final review): audit list/
   export org/role scoping, correlation-scoped chain-verify reporting,
   AuditTimeline >1000-row truncation notice, fixed-TZ (UTC) day headings,
   migration 025 downgrade guard, `ChangeResponse` vars()-validator
   property fragility, ready-to-go badge color drift.

## Environment facts (binding, from kickoff crib)

- The real dev stack is docker-compose `claude-plm2-*` (backend :8000
  bind-mount + --reload, frontend :5173, **Postgres**) — final smoke runs
  there, not only on SQLite.
- `alembic` runs as a console script from `backend/` (not `python3 -m`).
- Postgres migrations need `sa.false()` server defaults and CASCADE for
  circular-FK drops; SQLite needs plain-Integer FK adds + batch_alter_table.
- Never stage `__pycache__`/`plm.db`; fixers stage explicit paths only.
- Dev logins: test@example.com/password, admin@example.com/admin1234.

## Risks

- **Migration fidelity** is the dominant risk: an in-flight change whose
  synthesized instance mismatches its real state would block or falsely unblock
  transitions. Mitigation: equivalence tests per lifecycle status, plus the
  Phase B startup-repair pattern re-checked against change-scoped instances.
- **Hidden readers of assessment execution columns** (status/stage/owner on
  `ChangeAssessment`): columns stay in place during Phase E; API keeps the
  response shape while sourcing from tasks, so stale readers degrade to
  consistent-but-derived data, not breakage.
- **At-risk heuristic quality:** template due-days are defaults, not promises;
  the flag is advisory (explicitly non-blocking), so false positives cost
  attention, not throughput.
