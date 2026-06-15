# Change Assessment Routing (ECR) — Design Spec

**Sub-project #2 of 7** in the Change Management roadmap. Builds on the lifecycle
spine (#1, branch `feature/change-management`, PR #1). Branch:
`feature/change-assessment-routing`.

## Problem

Today, when a change enters `in_assessment`, `ChangeService.ensure_assessments()`
reads a hard-coded `TYPE_DISCIPLINES` dict (`change_type → [department names]`) and
creates one `ChangeAssessment` per department — all equal-weight, all blocking, all
parallel. There is no notion of *responsible vs. consulted vs. informed*, no
sequencing, no notifications when work becomes due, and routing cannot be changed
without editing code.

## Goal

Drive cross-functional assessment routing from a **configurable, staged RASIC
matrix** authored in the existing flow designer (`WfTemplate`), with governed
deviations that promote into the standard on release. The standard assessment flow
is called **ECR**.

## Decisions (locked during brainstorming)

1. **Routing source:** a configurable RASIC matrix, read from the flow designer's
   `WfTemplate` (stages → steps → per-department `R|A|S|I|C`). Not a separate
   hand-edited table; not full generic `WfInstance` execution.
2. **RASIC semantics for assessments:** **R/A block** (must submit a verdict before
   leaving assessment), **C/S optional** (get a task, non-blocking), **I notify-only**
   (no task, just notified).
3. **Standard + governance:** the flow designer holds *the* standard. A change
   snapshots the standard at routing time. Deviations require **approval**; on
   `released`, an approved deviation is **promoted into the standard** as a new
   template version. The standard evolves only through governed, shipped changes.
4. **Sequencing:** **staged**. A general "change started" info notification goes to
   everyone involved at the start; then stages activate sequentially; each activated
   stage notifies its departments that work is due. R/A block stage advancement; C/S
   do not.
5. **Approach B — change-domain routing.** `ChangeAssessment` stays *the* task +
   verdict record (extended with stage/letter). The change snapshots the standard
   `WfTemplate`; `change_service` drives staged progression + notifications, mirroring
   the proven `workflow_service` pattern without entangling with the revision-bound
   `WfInstance` engine.
6. **ECR template authored by the user** in the flow designer. The system reads
   whatever is mapped; it does **not** hard-code template content.
7. **Project members are out of scope** for #2 — notifications/tasks target
   *departments*. Per-project member resolution is a later sub-project; leave a clean
   seam.

## Data model

### Extend `ChangeAssessment` (`change_assessments`)
New columns (all additive, nullable/defaulted for back-compat):
- `stage_order: int` (default 1) — which stage this assessment belongs to.
- `rasic_letter: str(1)` (default `"R"`) — `R | A | S | C`. `I` never produces a row.
- `status: str(20)` (default `"active"`) — `pending` (stage not yet active) →
  `active` (its stage is live) → `submitted` → `waived`.

Tier is **derived**, not stored: `R`/`A` ⇒ blocking; `C`/`S` ⇒ optional. Existing
`verdict`, `cost_impact`, `lead_time_impact_days`, `conditions`, `notes`,
`responsible_id`, `submitted_*` are unchanged.

### New `ChangeRouting` (`change_routings`) — one per change
Snapshot of the standard at routing time + deviation governance state.
- `id`, `change_id` (unique FK), `template_id` (nullable FK `wf_templates`),
  `template_version: int | None`
- `standard_snapshot: JSON` — the stages → steps → `{department_id, rasic_letter}`
  exactly as authored when the change entered assessment (the immutable baseline).
- `has_deviation: bool` (default false)
- `deviation_status: str(20)` — `none | pending_approval | approved` (default `none`)
- `deviation_note: Text | None`
- `deviation_proposed_by`, `deviation_approved_by` (FK users, nullable),
  `deviation_approved_at: datetime | None`
- timestamps

### New `ChangeRoutingStandard` (`change_routing_standards`) — config
Maps a change type to the ECR template that is its standard.
- `id`, `change_type: str(30)` (unique), `template_id: int` (FK `wf_templates`),
  `template_version: int`
- `updated_by`, `updated_at`

**Fallback:** if a `change_type` has no `ChangeRoutingStandard` row, routing falls
back to the existing `TYPE_DISCIPLINES` dict, materialized as a **single implicit
stage** of all-`R` (blocking) departments. This preserves current behavior and keeps
all 102 spine tests green.

## Staged execution flow

On `captured → in_assessment` (in `ensure_assessments`, rewritten):
1. Resolve the standard template for `change.change_type` via
   `ChangeRoutingStandard`; else build the implicit single-stage fallback from
   `TYPE_DISCIPLINES`.
2. Write the `ChangeRouting` snapshot (template id/version + `standard_snapshot`).
3. Generate `ChangeAssessment` rows for every `R/A/S/C` assignment across **all**
   stages, `status=pending`, carrying `stage_order` + `rasic_letter`. `I`
   assignments produce no row (recorded in the snapshot for notification only).
4. **Broadcast** a "change started" *info* notification to every involved department
   (including `I`) via `NotificationService.notify_departments`.
5. **Activate stage 1:** its assessments → `active`; notify those departments that
   their assessment is due.

During assessment:
6. Departments submit verdicts via the existing `submit_assessment` (sets
   `status=submitted`).
7. **Stage advancement:** when every *blocking* (R/A) assessment in the active stage
   is `submitted`, activate the next stage (its assessments → `active`) and notify.
   C/S assessments never block; if still open when their stage advances, they remain
   submittable but non-blocking.
8. After the final stage, the `in_assessment → costing` guard passes when all
   *blocking* assessments are submitted. A `not_feasible` verdict on any submitted
   assessment still forces an explicit decision (existing guard behavior, refined to
   key on blocking completion rather than "all assessments").

## Deviation & promotion governance

- **Deviate** (lead-only) while in assessment: `add` a department, `remove` one, or
  `reletter` one. Each edit sets `has_deviation=true`,
  `deviation_status=pending_approval`, records `deviation_proposed_by`, and appends a
  hash-chained changelog entry describing the op.
- **Soft guard:** an unapproved deviation (`pending_approval`) blocks leaving
  assessment — overridable by the lead with a logged justification (flexibility
  principle; the only HARD gate remains customer acceptance + PM/Quality dual
  sign-off).
- **Approve deviation:** flips `deviation_status=approved`. **Approver = the change
  lead; if the lead proposed the deviation, the PM must approve (no self-approval).**
- **Promote on release:** in `release()`, if `deviation_status=approved`, build the
  new RASIC structure from the change's final assessments, bump the ECR template to
  v+1, write a `WfTemplateHistory` snapshot whose `change_note` cites the
  `change_number`, and repoint the `ChangeRoutingStandard` row to the new version.
  The standard now reflects what shipped. Because assessments track `stage_order` but
  not `step`, promotion collapses each stage into a **single step** containing that
  stage's department/letter assignments (parallel within the stage).

## API surface (additive)

- `GET /v1/changes/{id}/routing` — staged routing view: stages → departments with
  `{rasic_letter, tier, status, verdict, cost_impact, lead_time_impact_days}`, plus
  `deviation_status` and whether the current user may deviate/approve.
- `POST /v1/changes/{id}/routing/deviation` —
  `{op: "add"|"remove"|"reletter", department_id, rasic_letter?, stage_order?}`.
- `POST /v1/changes/{id}/routing/deviation/approve`.
- `GET /v1/changes/routing-standards` and `PUT /v1/changes/routing-standards` —
  admin maps `change_type → {template_id, template_version}` (the ECR template is
  authored separately in the existing flow designer).

## Frontend surface

- **ChangeDetailPage → assessment tab** becomes a **vertical stage stepper**: each
  stage lists its departments with a RASIC badge (`R/A/S/C/I`), tier
  (blocking/optional/info), status, and submitted verdict. The active stage is
  highlighted; completed stages collapse. Dark-slate theme to match
  `ProjectSepSection` (note: the spine's change pages currently use a light theme —
  this tab follows the dark pattern; full theme reconciliation is a separate spine
  follow-up).
- **Lead-only deviation controls** (add/remove/reletter) + a "deviation pending
  approval" banner with an approve button (shown to the eligible approver).
- **My Tasks:** surface **active-stage** R/A/S/C assessment tasks (refines the
  spine's current flat assessment-task list).

## Testing (TDD)

- Snapshot generation from a mapped template: correct per-letter rows; `I` excluded
  from rows but included in the start notification.
- Stage gating: stage 2 stays `pending` until stage 1's R/A are submitted; C/S do not
  block advancement.
- `not_feasible` on a submitted assessment forces an explicit decision.
- Deviation: an edit flips `pending_approval`; leaving assessment is soft-blocked;
  lead override logs justification; approve flips to `approved`; self-approval by the
  proposing lead is rejected (PM required).
- Promotion on release: creates ECR template v+1, writes a `WfTemplateHistory`
  snapshot citing the change number, repoints `ChangeRoutingStandard`.
- **Back-compat:** with no `ChangeRoutingStandard` mapping, `TYPE_DISCIPLINES`
  fallback reproduces current behavior; all 102 spine tests pass.
- Notifications: assert `NotificationService` is invoked at start (info broadcast)
  and on each stage activation.

## Out of scope (later sub-projects / follow-ups)

- Per-project member resolution (notifications target departments for now).
- Stage *reordering* via deviation (deviations change membership/letters within the
  snapshot's existing stages; adding a department targets a chosen or last stage).
- Commercial costing/quote layer (#3), impact-scope automation (#4), and the light/
  dark theme reconciliation of the spine's change pages.
