# ECR: costing to close (plan, offer, timing validation, tracker, release)

Branch `feature/ecr-costing-to-close`, worktree `../plm2-ecr`. Governing map:
`docs/ECR_PROCESS_MAP.md` stages 4-10. This spec is the shared contract for the
backend and both frontend builders. Where it says "must", tests check it.

## 1. The flow after assessment

| Status | Tab | Who | What happens | Leaves when |
|---|---|---|---|---|
| `costing` | Costing | departments, PM runs it | cost lines incl. timing (lead time on every line), internal hours, estimates or vendor quotes | PM/Sales/lead closes costing (existing) |
| `quoting` | Offer | Sales | 1 Plan: rough timeline (Gantt, quote plan) 2 Price: cost basis, optional factors, risk weights, changeover (running change vs customer pays scrap), piece-price effect 3 Document: CBD or rough description, free fields, terms, preview, PDF | offer v1 sent (auto `quoting -> quoted`) |
| `quoted` | Offer | Sales | negotiation: rounds logged, new offer versions with "what changed", each sent version valid 30 days from customer receipt | customer accepts (a sent, unexpired version) + PM + Quality sign-off -> `approved` |
| `approved` | Timing | PM + Scheduling + all teams | detailed plan (seeded from the quote plan), every responsible team confirms or raises a concern, bank build / scrap plan, "Timing validated" sets the baseline, Sales publishes to customer, MS Project export | timing validated -> `in_implementation` (soft guard) |
| `in_implementation` | Timing | departments | tracker: progress %, actual start/finish per block, twice-weekly reports, time booking (existing); date changes only by PM/Sales/lead/admin, each one a deviation with reason; deviation is locked (accepted internally) or escalated to the customer | -> `in_validation` |
| `in_validation` | Release | departments, PM | validation checks (existing), release checklist, lessons learned step | checklist complete + lessons step done -> `released` (soft guard) |
| `released` | Release | PM | summary (plan vs actual, P&L) | PM closes -> `closed` |

Internal changes (not customer relevant): the Offer tab is labelled "Approval"
and holds the existing internal cost approval; the quote plan is still
available so timing exists before approval.

## 2. Data model (migration `087_ecr_plan_offer_release.py`)

Dialect-neutral (sa.true()/sa.false(), no raw SQL updates). Revision id
`087`, down_revision `086`.

### `change_plan_tasks`
| column | type | note |
|---|---|---|
| id | pk | |
| change_id | fk change_requests, index | |
| plan | String(10) | `quote` or `detailed` |
| name | String(200) | |
| lane | String(80) null | swimlane label: department name, `Customer`, `Supplier` |
| department_id | fk wf_departments null | owner department (progress rights) |
| kind | String(20) | `work` `supplier` `downtime` `bank_build` `sampling` `validation` `customer` `buffer` `milestone` |
| is_idea | bool default false | idea block (Sales proposal, e.g. parallel bank build); dashed in UI |
| start_date | Date | |
| duration_days | Integer | calendar days; milestone = 0 |
| predecessors | JSON list[int] | finish-to-start, same plan |
| sort_order | Integer | |
| progress_pct | Integer default 0 | 0..100 |
| actual_start / actual_finish | Date null | |
| baseline_start / baseline_finish | Date null | set by "Timing validated" |
| source_position_id | Integer null | costing position it was seeded from (no FK constraint needed, but allowed) |
| notes | Text null | |
| created_by, created_at, updated_by, updated_at | | |

`end_date = start_date + duration_days` (exclusive). The UI shows the
inclusive last day `end_date - 1` for duration > 0. A successor may start on
the predecessor's `end_date`.

### `change_plan_feedback`
id, change_id (idx), department_id, plan_revision int, verdict
(`confirmed`|`concern`), note Text null (required for concern), created_by,
created_at. The latest row per department counts; a row is stale when its
`plan_revision` < change.plan_revision.

### `change_plan_deviations`
id, change_id (idx), task_id (fk change_plan_tasks, ondelete cascade not
required), old_start, old_end, new_start, new_end (Date), slip_days int (new_end
- baseline end of that task, may be negative), finish_impact_days int (plan
finish after - plan finish before), reason Text, status (`open`|`locked`|
`escalated`), decided_by, decided_at, decision_note, escalation_id (fk
implementation_escalations null), created_by, created_at.

### `change_offers`
id, change_id (idx), version int (unique with change_id), status
(`draft`|`sent`|`superseded`|`accepted`|`declined`), currency String(3)
default `EUR`, data JSON, total_one_time Numeric(14,2) null,
piece_price_delta Numeric(12,4) null, change_note Text null, sent_at DateTime
null, sent_by null, received_at Date null, valid_until Date null, created_by,
created_at, updated_at.

### `change_release_checks`
id, change_id (idx), check_key String(40), status (`open`|`done`|`na`), note
Text null (required for `na`), department_id null (owner, from the catalog),
checked_by, checked_at. Unique (change_id, check_key). Seeded lazily.

### New columns
- `change_requests`: `plan_revision` int default 0 (server_default "0"),
  `timing_validated_at`, `timing_validated_by`, `accepted_offer_id` (int null),
  `lessons_done_at`, `lessons_done_by`, `lessons_none_reason` Text null.
- `change_negotiations.offer_id` int null (the version the round is about).
- `lessons_learned.change_id` fk change_requests null, index.

## 3. Rights (backend enforces, UI mirrors)

- **Plan editors (quote plan)**: admin, change lead, Sales, Project Manager,
  Scheduling. Editable in `costing`, `quoting`, `quoted`; read-only after.
- **Plan editors (detailed plan)**: same set, from `approved` until
  `in_validation`. Before timing is validated every edit bumps
  `plan_revision` (confirmations go stale). After it: only dates change via
  deviation (reason required, see 5). Any member of the task's department may
  write `progress_pct`, `actual_start`, `actual_finish` on its own tasks in
  `in_implementation` (editors may on all).
- **Offer**: Sales, change lead, admin write/send; PM reads. Quality/others no
  access to prices (existing canSeeCosts rule: admin, lead, Sales, PM).
- **Feedback**: a member of the department (or admin) posts for that department.
- **Timing validated / publish**: PM, Scheduling, Sales, lead, admin.
- **Deviation lock / escalate**: PM, Sales, lead, admin. Escalate to customer
  creates an `ImplementationEscalation(direction="customer")`.
- **Release checks**: member of the owner department, PM, lead, admin.
- **Lessons step**: anyone on the change may add lessons; PM/lead/admin
  completes the step.

## 4. Plan API (`/api/v1/changes/{id}/plan...`)

- `GET /plan?plan=quote|detailed` -> `PlanOut`:
  ```
  { plan, tasks: [TaskOut], revision: int, baseline_set: bool,
    can_edit: bool, can_edit_dates: bool, progress_department_ids: [int],
    summary: { start: date|null, finish: date|null, duration_days: int,
               buffer_days: int, critical_ids: [int], ideas: int },
    validation: { errors: [Issue], warnings: [Issue] },
    deadlines: [ { key, label, date } ] }
  TaskOut = all columns + end_date + slack_days + is_critical
            + department_name
  Issue = { code, message, task_id: int|null }
  ```
  `deadlines`: quote deadline (`required_by_date`), release deadline
  (`release_due_date`), offer valid-until of the latest sent offer.
- `POST /plan/seed {plan, replace?: bool}` -> PlanOut. `quote`: generated from
  costing (template below). `detailed`: copy of the quote plan (ids remapped,
  predecessors remapped, ideas stay ideas). Refuses (409) when tasks exist and
  `replace` is not true.
- `POST /plan/tasks {plan, name, kind, lane?, department_id?, start_date,
  duration_days, predecessors?, is_idea?, notes?}` -> PlanOut
- `PATCH /plan/tasks/{tid} {any writable field..., reason?}` -> PlanOut
- `PATCH /plan/tasks {plan, updates: [{id, start_date?, duration_days?}], reason?}`
  bulk (block move / resize of a selection) -> PlanOut. One deviation per
  changed task after baseline, same reason.
- `DELETE /plan/tasks/{tid}` -> PlanOut (removes it from other predecessor
  lists; refused after baseline).
- `POST /plan/schedule {plan}` -> PlanOut. Forward pass: every task whose start
  is before its latest predecessor end moves to that end (successors cascade).
  Never pulls tasks earlier. After the baseline it needs `reason` and every
  moved block becomes a deviation (see §5).
- `GET /plan/export.xml?plan=` -> MSPDI XML (`application/xml`, filename
  `<change_number>-<plan>.xml`) that MS Project opens: Project/Name, StartDate,
  Tasks with UID, ID, Name, Start, Finish, Duration (`PT{24*d}H0M0S`),
  DurationFormat 8 (elapsed days, our durations are calendar days), Milestone, PercentComplete, OutlineLevel 1,
  PredecessorLink (PredecessorUID, Type 1 = FS), Notes, plus baseline
  (Baseline Number 0 Start/Finish) when set. Resources: one per lane, with
  Assignments. Must parse as XML; test checks tasks count and a link.
- `GET /plan/export.csv?plan=` -> CSV (ID, Name, Lane, Kind, Start, Finish,
  Duration days, Predecessors, Progress, Baseline start, Baseline finish).
- `GET /plan/feedback` -> `{ revision, required: [ {department_id,
  department_name, verdict|null, note, by_name, at, stale} ], all_confirmed,
  validated_at, validated_by_name }`. Required departments: every department
  with an R or A assessment row on the change, plus Scheduling and Sales when
  those departments exist.
- `POST /plan/feedback {department_id, verdict, note?}`.
- `POST /plan/validate-timing` -> sets baseline_start/finish on every detailed
  task, `timing_validated_at/by`, changelog `timing_validated`. Refuses when:
  status not `approved`/`in_implementation`, no detailed tasks, validation
  errors, any required department not confirmed at the current revision, any
  idea block left in the detailed plan.
- `GET /plan/deviations` -> list with task name, dates, slip, impact, status,
  names.
- `POST /plan/deviations/{did}/lock {note?}` -> status locked.
- `POST /plan/deviations/{did}/escalate {note}` -> status escalated + escalation.

### Plan validation
Errors: `negative_duration`; `dependency_violation` (starts before a
predecessor ends); `cycle`; `unknown_predecessor`; `empty_name`.
Warnings: `after_release_deadline` (plan finish later than
`release_due_date`, when set), `no_buffer` (no buffer
block), `thin_buffer` (buffer days < 5% of plan duration), `bank_build_late`
(a bank_build block ends after the first downtime block starts),
`idea_blocks` (detailed plan still contains idea blocks), `no_owner` (task
without lane and department), `milestone_duration` (milestone with duration >
0, fixed to 0 on write instead: silently normalise).

### Critical path
Forward/backward pass over FS links over non-idea tasks; slack in days;
`is_critical` when slack == 0 and duration > 0 or milestone on the path.

### Quote plan seed (template)
Anchor = max(today, required_by_date or today) + 7 days ("customer order").
1. Milestone `Customer order / go-ahead` (lane Customer, kind milestone).
2. For each department with costing positions, one `work` task "<Dept>
   engineering" when it has support_effort hours (duration = ceil(hours/8)
   working days converted to calendar via ceil(d*7/5), min 1) after the order.
3. For each external position with a lead time: task named after the
   position label (+ " - <vendor>" when a chosen/favourite vendor exists),
   kind `supplier`, or `downtime` when the department is Tool Engineer, lane =
   department, duration = calendar lead time, after the department's
   engineering task (or the order), `source_position_id` set.
4. If any downtime task: `Bank build (idea)` kind bank_build, is_idea true,
   lane Scheduling, 10 days, ending on the first downtime start (start =
   downtime start - 10, no predecessor).
5. `Sampling / trial` kind sampling, 5 days, lane Tool Engineer, after all
   supplier/downtime tasks.
6. `Measurement and validation` kind validation, 7 days, lane APQP, after 5.
7. `Customer approval (PPAP / ISIR)` kind customer, 14 days, lane Customer,
   after 6.
8. `Safety buffer` kind buffer, max(5, 10% of chain) days, after 7.
9. Milestone `Start of production (change)` after 8.
No costing positions -> steps 1, 5-9 with the Tool Engineer supplier step
replaced by a 20-day `Implementation` work task.

## 5. Deviations (after "Timing validated")
Any start/duration change on a detailed task needs `reason` (400 otherwise)
and a plan editor; it writes one `change_plan_deviations` row per task with
old/new dates, `slip_days` against the task baseline end and
`finish_impact_days` against the plan finish before the edit, and changelog
`plan_deviation`. Open deviations show in the cockpit "Blocked by" list only
as information (they do not gate). `lock` = accepted internally (PM/Sales
decision recorded). `escalate` = Sales tells the customer: creates the
escalation (existing stage-8 table) and marks the deviation escalated.

## 6. Offer API (`/api/v1/changes/{id}/offers...`)

`OfferOut = { id, version, status, currency, data, totals, change_note,
sent_at, sent_by_name, received_at, valid_until, days_left, expired,
created_at, created_by_name, diff: [ {field, before, after} ] | null,
warnings: [Issue] }`.

`data` shape (every key optional on write, server fills defaults):
```
{ recipient: {company, contact, address},
  subject, intro,
  cbd_mode: "detailed" | "rough", rough_description,
  cost_lines: [ {key, label, department, category: internal|external|other,
                 amount, source_amount, include} ],
  factors: [ {key, label, type: pct|amount, value, sign: 1|-1, enabled, note} ],
  risks: [ {concern_id, label, severity, department, show, type: pct|amount,
            value, note} ],
  changeover: {mode: running_change|customer_pays_scrap, scrap_qty,
               scrap_unit_price, note},
  piece_price: {enabled, annual_volume, rows: [{label, driver, delta_per_piece}]},
  timing: {include, weeks_from_order, milestones: [{label, date}], disclaimer},
  free_fields: [ {label, value, amount} ],
  terms: {payment, incoterms, delivery, notes} }
```
Defaults on create (v1): recipient.company = project name; subject = "Offer
for engineering change <change_number>: <title>"; cost_lines seeded from the
summation (one line per department internal, one per external position using
Sales' chosen or the favourite vendor, amounts = source_amount);
factors seeded disabled: `overhead` (pct), `margin` (pct), `engineering_fee`
(amount), `sampling_ppap` (amount), `freight_packaging` (amount),
`expedite` (pct), `discount` (pct, sign -1); risks seeded from open risk
concerns of the change (show = severity 3, value 0 pct); changeover mode
from `bank_build_mode` if set else running_change; timing include true,
disclaimer "Draft timing. Final dates are confirmed after order according to
shop, supplier and equipment availability."; weeks_from_order and milestones
from the quote plan (order milestone to last task, key milestones:
milestones + sampling + customer approval + SOP); terms payment "30 days net",
incoterms empty.

Totals (server, the UI shows these, never recomputes the business rule):
```
base = sum(amount of included cost_lines)
factor_i = value% * base (pct) or value (amount), times sign, if enabled
risk_i = value% * base or value (pct/amount)
scrap = scrap_qty * scrap_unit_price if mode customer_pays_scrap else 0
free = sum(free_fields.amount)
total_one_time = base + sum(factors) + sum(risks) + scrap + free
piece_price_delta = sum(rows.delta_per_piece) if piece_price.enabled
annual_effect = piece_price_delta * annual_volume
internal_cost = summation grand total (for margin display)
```
`totals = {base, factors:[{key,label,amount}], risks_total, scrap, free,
total_one_time, piece_price_delta, annual_effect, internal_cost,
margin_abs, margin_pct}`.

Endpoints:
- `GET /offers` -> [OfferOut] newest first.
- `POST /offers` -> creates the draft: v1 seeded as above; later versions
  clone the latest sent/accepted version's data. 409 with the existing draft id
  when a draft exists. Allowed in `quoting` and `quoted` (and `costing` for a
  preview? no: quoting/quoted only).
- `PATCH /offers/{oid} {data?, currency?}` -> draft only; deep-merge top-level
  keys (a list key replaces the list).
- `POST /offers/{oid}/refresh` -> draft only: re-seeds cost_lines and risks
  from current costing/concerns keeping `include`/amount overrides by key.
- `POST /offers/{oid}/send {received_at?, change_note?}` -> draft -> sent;
  previous sent -> superseded; `sent_at` now; `received_at` default today;
  `valid_until = received_at + 30 days`; `change.quoted_price =
  total_one_time`; status `quoting` -> `quoted` through
  `ChangeService.transition`; changelog `offer_sent` (v, total, note).
  Refused: total <= 0; version >= 2 without change_note; plan (quote) empty
  when timing.include; status not quoting/quoted.
- `POST /offers/{oid}/received {received_at}` -> sent only; recomputes
  valid_until; changelog `offer_received`.
- `GET /offers/{oid}/pdf` -> `application/pdf`, filename
  `<change_number>-offer-v<version>.pdf`. Drafts render with a DRAFT
  watermark.
- Customer response `accepted` (existing endpoint): when offers exist, the
  latest sent offer must not be expired unless `expired_override_reason` is
  given (recorded); it becomes `accepted`, `change.accepted_offer_id` set.
  `declined` marks it declined. Negotiation rounds accept `offer_id`
  (defaults to the latest sent offer).
- `diff` on a version >= 2: changed totals (total_one_time, piece price), cost
  line amounts by key, factors enabled/value, risk values, changeover, timing
  weeks, terms.

### Offer PDF standard (A4 portrait, reportlab)
Letterhead: organisation name + plant name/location of the change's project,
right aligned "OFFER" + number `<change_number>-Q<version>`, date, valid until.
Recipient block (company/contact/address). Subject line bold. Intro text.
Sections: 1 Scope of change (reason, description first 1200 chars, impacted
items table: number, name, index). 2 Price: detailed CBD table (cost lines
included, then factors, risk surcharges, scrap, free fields, total) or, in
rough mode, the rough description and one total line. Piece price effect
block when enabled. 3 Changeover (running change or customer-paid scrap with
qty x price). 4 Timing: draft disclaimer in italics, weeks from order, key
milestones table, and a simple bar chart of the quote plan (reportlab
drawing, one row per non-idea task, lanes coloured). 5 Technical risks and
assumptions: risks with `show` true (severity, department, note). 6 Terms:
payment, incoterms, delivery, validity "This offer is valid for 30 days from
receipt (until <date>)", notes, free fields without amount. Footer with page
x/y and change number. No em-dashes anywhere in the generated text.

## 7. Release checklist (config in code `app/services/release_checklist.py`)
key, label, owner department name:
1. `index_updated` Part index / revision level updated in drawing and PLM (Development)
2. `drawing_released` Drawing and 3D data released and distributed (Development)
3. `equipment_updated` Tool and equipment data updated (tool card, equipment list) (Tool Engineer)
4. `parts_measured` Parts measured, measurement report on file (APQP)
5. `weight_measured` Part weight measured and recorded (Tool Engineer) (auto hint when validated weight exists)
6. `cycle_time_confirmed` Cycle time confirmed in series production (Manufacturing Engineer)
7. `documents_updated` PFMEA, control plan and work instructions updated (APQP)
8. `packaging_updated` Packaging instruction updated (Packaging Engineer)
9. `customer_approval` Customer approval received (PPAP / ISIR / PSW) (APQP)
10. `erp_updated` ERP, BOM and routing updated (Scheduling)
11. `stock_handled` Old stock handled as agreed (bank consumed or scrapped) (Scheduling)
12. `customer_informed` Customer informed of the implementation date / first shipment (Sales)
13. `spare_parts` Spare and service parts considered (Development)

API: `GET /changes/{id}/release` -> `{ checks: [{key, label, department_id,
department_name, status, note, by_name, at, hint}], open_count,
lessons: {done_at, done_by_name, none_reason, items: [LessonOut]},
can_release: bool, blockers: [str] }`;
`POST /changes/{id}/release/checks/{key} {status: done|na|open, note?}`;
`POST /changes/{id}/lessons {title, description, category, lesson_type,
severity, recommendation?}` (creates LessonLearned with project_id and
change_id, status in_review); `POST /changes/{id}/lessons/complete
{none_reason?}` (>= 1 lesson or a none_reason). Guard `in_validation ->
released` (soft, after the existing validation blocker): "Release checklist
incomplete: n open" / "Lessons learned step not done".

## 8. My actions / cockpit
New `my_actions` kinds with `target_tab`: `offer_build` (Sales at quoting:
"Build and send the offer", tab `offer`), `offer_expiring` (Sales at quoted,
latest sent offer <= 7 days left or expired, tab `offer`), `plan_feedback`
(member of a required department at approved, not yet confirmed current
revision, tab `timing`), `timing_validate` (plan editors at approved when all
confirmed, tab `timing`), `plan_deviation` (PM/Sales with open deviations, tab
`timing`), `release_check` (owner department members with open checks at
in_validation, tab `release`), `lessons_step` (PM/lead at in_validation, tab
`release`). Existing `target_tab` values `implementation` become `timing` or
`release` by stage; `commercial` becomes `costing`/`offer`. The frontend
keeps aliases `commercial -> costing|offer by status` and `implementation ->
timing` for old links.

## 9. Frontend structure
Tabs: Overview, Scoping, Impacted, Assessments, Costing, Offer (Approval for
internal), Timing, Release | Governance D1, Audit.
Unlock: costing@costing, offer@costing, timing@approved, release@in_validation.
Active tab: costing->costing, quoting/quoted->offer, approved/in_implementation
->timing, in_validation/released->release.

Shared Gantt component `components/changes/plan/GanttPlanner.tsx`:
```ts
interface GanttPlannerProps {
  changeId: number
  plan: 'quote' | 'detailed'
  mode?: 'plan' | 'track'      // track: baseline ghosts + progress editing
  compact?: boolean            // read-only small view (offer preview)
  onPlanChange?: (p: PlanOut) => void
}
```
It fetches `['change', id, 'plan', plan]` itself and owns every plan mutation.
Timing tab component `components/changes/timing/TimingTab.tsx` with props
`{ change: ChangeRequest, departments, myDepartmentIds: number[], canEditPlan:
boolean, canPublish: boolean, canSeeAll: boolean }`.

## 10. Backend notes

What the backend actually does where the spec was silent or had to be made
concrete. Shapes above still hold; everything here is additive or a
clarification.

### Errors
- 400 business refusal (`detail` is a string), 403 rights, 404 unknown
  task / offer / deviation / release check key on this change.
- 409 `detail` is an object `{message, ...}`: `POST /offers` with a draft
  present gives `{message, draft_id}`; `POST /plan/seed` without `replace`
  gives `{message}`.

### Plan
- `baseline_finish` and deviation `old_end` / `new_end` are EXCLUSIVE, like
  `end_date` (compare them directly). The CSV prints Finish / Baseline finish
  as the inclusive last day.
- After "Timing validated": `can_edit = false`, `can_edit_dates = true`.
  Structural fields (`name, kind, lane, department_id, predecessors, is_idea,
  sort_order`) are refused (400), `notes` stays editable, add / delete /
  A date move pushes the successors it drives
  (later only; pinned blocks and blocks that already started stay put); each
  pushed block gets its own deviation with the same reason and
  `caused_by_task_id` / `caused_by_task_name` naming the block the user moved.
  `finish_impact_days` is the same value on every deviation of one call.
  Schedule after the baseline needs `reason` and creates deviations.
- Progress (`progress_pct, actual_start, actual_finish`): detailed plan only,
  status `in_implementation` only. A PATCH that carries only these fields uses
  the department rule; mixing them with other fields needs an editor.
- Writes refuse `empty_name`, negative durations, unknown or self
  predecessors (400), so those error codes only show for legacy data.
  `dependency_violation` and `cycle` are allowed on write and reported.
- `plan_revision` bumps once per mutating API call on the detailed plan
  before the baseline (seed included). Quote plan edits never bump it.
- Detailed seed with an empty quote plan builds the template directly.
  Template: when positions exist but none yields a block, the 20-day
  `Implementation` fallback is used; `Safety buffer` lane is
  `Project Manager`; lanes that match a department carry its `department_id`.
- `timing_validated` may be re-run while approved / in_implementation (resets
  the baseline). Feedback is accepted in approved and in_implementation and
  needs detailed blocks.
- `deadlines` keys: `quote`, `release`, `offer_valid_until`, present only when
  set.
- Response of `POST /plan/validate-timing`: detailed `PlanOut`.
  `POST /plan/feedback`: the `GET /plan/feedback` shape.
  `POST /plan/deviations/{id}/lock|escalate`: that one deviation row, same
  shape as the list items: `{id, task_id, task_name, old_start, old_end,
  new_start, new_end, slip_days, finish_impact_days, reason, status,
  decided_by, decided_by_name, decided_at, decision_note, escalation_id,
  created_by, created_by_name, created_at}`.
- `TaskOut` also carries `change_id, created_by, created_at, updated_by,
  updated_at`.
- MSPDI: idea blocks are left out, UIDs are 1..n in plan order (not our task
  ids), every task has ConstraintType 4 (start no earlier than) on its own
  start so MS Project keeps our dates.

### Offer
- `POST /offers` answers 201. `OfferOut` also carries `change_id, sent_by,
  created_by, updated_at`. `days_left` is set only for status `sent`.
- `totals.factors` lists only enabled factors. `piece_price_delta` and
  `annual_effect` are null when piece price is disabled; `margin_pct` null
  when the total is 0. `internal_cost` = summation grand total.
- Seeded cost line keys: `dept:<id>` (department's internal money incl. valued
  position hours), `dept_ext:<id>` (the department's cost-line external money
  not covered by positions, only when > 0), `pos:<id>` (external position at
  Sales' chosen, else favourite vendor; label `"<label> (<vendor>)"`). Any
  other key is a manual line and survives `refresh`.
- Seeded changeover mode is `customer_pays_scrap` when `bank_build_mode` is
  `planned_scrap`.
- Warning codes: `no_cost_lines, zero_total, below_internal_cost,
  costing_changed` (draft, summation moved: refresh), `change_note_missing`
  (draft v>=2), `timing_plan_empty, high_risk_unpriced, expired`.
- `diff` compares against the previous non-draft version; `field` is a human
  label (`Total one-time`, `Piece price delta`, `Cost line <label>`,
  `Factor <label>`, `Risk <label>`, `Changeover`, `Scrap quantity`,
  `Scrap unit price`, `Timing weeks from order`, `Terms <key>`).
- Customer response writes changelog `offer_accepted` / `offer_declined`;
  acceptance with no sent offer (legacy quotes) is unchanged.
- `CustomerResponseRequest.expired_override_reason`,
  `NegotiationCreate.offer_id`, `NegotiationResponse.offer_id` added.
- PDF: `Content-Disposition: inline`.

### Release
- Checks are answerable in `in_implementation` and `in_validation`; lessons
  can be added in any status; the lessons step is completed in
  `in_implementation` / `in_validation`. Status `open` resets an answer.
- `department_name` falls back to the catalog owner name when that
  department does not exist (then `department_id` is null and only PM, lead,
  admin answer it). `hint` is set on `weight_measured` when a validated weight
  exists.
- `blockers` lists every reason (validation blocker, ready-to-go, checklist,
  lessons); `can_release` = status `in_validation` and no blockers.
- `POST /release/checks/{key}` and `POST /lessons/complete` return the
  `GET /release` shape; `POST /lessons` returns the `LessonOut` (201):
  `{id, title, description, category, lesson_type, severity, recommendation,
  status, project_id, change_id, created_by, created_by_name, created_at}`.

### Guards, cockpit, my-tasks
- The timing guard applies to the first start of implementation:
  `approved -> in_implementation`, and `on_hold -> in_implementation` when
  the change was approved and never implemented (no bypass through a hold).
  Resuming a hold taken during implementation and looping back from
  validation stay exempt. The release guard
  runs after the validation blocker and the ready-to-go check.
- `ChangeResponse` also carries `plan_revision, timing_validated_at,
  timing_validated_by, accepted_offer_id, lessons_done_at,
  lessons_none_reason`.
- `my_actions` extra keys: `offer_expiring {offer_id, days_left}`,
  `plan_feedback {department_id}`, `plan_deviation {count}`,
  `release_check {department_id, count}`. `wf_task` now says `timing`
  (`release` at in_validation/released). The backend never emitted
  `commercial`.
- `GET /changes/my-tasks`: the existing `create_quote` row IS the "build the
  offer" task and now carries `has_offer_draft, offer_id, target_tab: "offer",
  hint`; new kinds `offer_expiring {offer_id, version, valid_until,
  days_left}`, `plan_feedback {department_id, stale}`, `release_check
  {department_id, check_keys, open_count}`, each with `target_tab`.

## 11. Gantt 2.0: a reusable, MS-Project-grade planner (2026-09-25)

Decision: keep our own planner and lift it into a generic module. Checked
SVAR React Gantt and DHTMLX Gantt (both MIT cores): critical path,
baselines, auto-scheduling, working calendars and MS Project export are paid
PRO features there, and those are exactly the features we need. Ideas are
borrowed (grid + chart split, lightbox editor, link drawing, zoom levels).

### Generic module `frontend/src/components/gantt/`
No change-management imports inside it. Other modules (projects, SEP timing,
tool build plans) use it through an adapter.
```ts
interface GanttTask { id: string|number; parentId?: id|null; name; start: 'YYYY-MM-DD';
  duration: number /* in calendar or working days per calendar mode */;
  kind?: string; lane?: string|null; isIdea?: boolean; progress?: number;
  baselineStart?; baselineEnd?; actualStart?; actualEnd?;
  constraint?: { type: 'asap'|'snet'|'fnlt'|'mso'|'mfo'; date? };
  color?: string; readOnly?: boolean; meta?: Record<string, unknown> }
interface GanttLink { id; from; to; type: 'FS'|'SS'|'FF'|'SF'; lagDays: number }
interface GanttCalendar { mode: 'calendar'|'working'; workdays: number[] /* 1..7, Mon=1 */; holidays: string[] }
interface GanttAdapter { load(); applyChanges(ChangeSet, {reason?}): Promise<void> ; rights: {...} }
```
Engine `gantt/engine/` (pure TS, fully unit tested): calendar date math
(working-day add/diff, holidays), end dates (exclusive), all four link types
with lag/lead, forward pass (auto-schedule, ASAP + constraints), backward
pass, total + free slack, critical path, summary task rollup (start/end/
progress of children), cycle detection, validation issues, WBS numbering,
MSPDI XML export AND import (MS Project .xml), CSV export, undo/redo command
stack (ChangeSet based).

Component features: grid with configurable columns (WBS, name, start, end,
duration, predecessors in MS Project notation e.g. `3FS+2d`, lane, progress,
slack), inline cell editing, indent/outdent (summary tasks, collapse),
row drag reorder, chart with day/week/month/quarter zoom, fit-to-plan,
today + deadline markers, weekend/holiday shading, bars per kind, idea
dashed, buffer hatched, milestone diamond, summary bracket bars, baseline
ghosts, progress fill and drag, slip tails, critical path, link drawing from
either bar end (type from the ends used), link click to edit type/lag,
multi-select block move/resize, keyboard (arrows, shift, Delete, ctrl+z/y,
ctrl+c/v duplicate, Insert new row, Tab indent), context menu, virtualised
rows (200+ tasks smooth), print/PNG export of the chart, light and dark theme
via CSS variables.

### Backend (migration 088, additive)
`change_plan_tasks`: `parent_id` (self fk null), `constraint_type`
String(4) null, `constraint_date` Date null, `wbs` not stored (computed).
New table `change_plan_links` (id, change_id, plan, from_task_id,
to_task_id, type FS|SS|FF|SF, lag_days int). `predecessors` JSON stays
readable for old rows and is migrated into links. Calendar per plan on
`change_requests.plan_calendar` JSON: `{"quote": {...}, "detailed": {...}}`
(the old flat shape reads as the calendar of both plans; default calendar
mode, Mon-Fri, no holidays). `PUT /plan/calendar?plan=` sets one plan's
calendar, refused outside that plan's edit window or after the baseline;
seeding the detailed plan copies the quote plan's calendar.
`POST /plan/import` returns PlanOut plus `import_warnings: string[]`. The service schedules with the same rules as the TS
engine (shared test vectors in `backend/tests/data/gantt_vectors.json`, the
frontend engine tests read the same file). MSPDI export includes link type +
lag (LinkLag in tenths of minutes) and summary tasks (OutlineLevel);
`POST /plan/import` accepts an MSPDI file.

### Vectors
Shared scheduling vectors, `backend/tests/data/gantt_vectors.json`, read by
the backend tests and by `frontend/src/components/gantt/engine/vectors.test.ts`
(which also runs its own sample `engine/__fixtures__/gantt_vectors.sample.json`
in the same format):
```
{"cases": [{
  "name": "fs chain",
  "calendar": {"mode": "calendar"|"working", "workdays": [1..7, Mon=1], "holidays": ["YYYY-MM-DD"]},
  "options": {"pull": false},                     // optional; default push (never earlier than own start)
  "tasks": [{"id": 1|"A", "start": "YYYY-MM-DD", "duration": 5,
             "constraint": {"type": "asap|snet|fnlt|mso|mfo", "date": "YYYY-MM-DD"} | null,   // optional
             "parentId": null, "isIdea": false}],                                        // optional
  "links": [{"from": 1, "to": 2, "type": "FS|SS|FF|SF", "lag": 2}],
  "expected": {"<id>": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD",   // early dates, end exclusive
                         "total_slack": 0 | null, "critical": true,
                         "free_slack": 0}}                           // optional key
}]}
```
Only the keys present in `expected` are compared. Rules (engine
`schedule.ts` header has the full text):
- Units: days in calendar mode, working days in working mode; ends exclusive;
  a working-mode start (milestones too) moves to the next working day.
- Link bounds with `shift(date, lag)`: FS `S.start >= P.end+lag`, SS
  `S.start >= P.start+lag`, FF `S.end >= P.end+lag`, SF `S.end >= P.start+lag`.
- Push mode: ES = max(own start, link bounds, snet); `mso`/`mfo` pin the
  date and win over links (warning `constraint_conflict`); `fnlt` only caps
  the late finish (warning when missed). Pull mode: tasks without
  predecessors start at the project start.
- Finish constraint dates (`fnlt`, `mfo`) are exclusive ends, like `end`.
- Backward pass over non-idea tasks from the project finish (max early end of
  non-idea leaves). Total slack = diff(ES, LS), may be negative; critical =
  not an idea and total slack <= 0. Free slack = min gap to the successors'
  bounds, else diff(EF, project finish), capped at total slack.
- Summary tasks roll up (min start, max end, slack = min of their leaves,
  critical when a leaf is). **A link or constraint on a summary applies to
  every leaf below it** (MS Project behaviour). The backend engine does the
  same (vectors `summary: a link on a summary applies to every leaf below
  it`, `... a link into a summary ...`, `... a constraint on a summary ...`);
  a link between a summary and a block under it is ignored (warning
  `summary_link`).
- A cycle stops the pass: tasks keep their own dates, slack null, error `cycle`.
- MSPDI round trip: link Type 0 FF, 1 FS, 2 SF, 3 SS; LinkLag tenths of
  minutes (14400 per elapsed day with LagFormat 8 in calendar mode, 4800 per
  working day with LagFormat 7); ConstraintType 0 ASAP, 2 MSO, 3 MFO, 4 SNET,
  7 FNLT; kind in ExtendedAttribute Text1 (FieldID 188743731), idea in Flag1
  (188743752); lanes as resources with assignments.

### Summary task rule (decided 2026-09-25, both engines MUST match)
MS Project semantics:
- Link INTO a summary (summary is the successor): FS and SS apply to every
  descendant leaf (no child may start before the predecessor allows). FF and
  SF into a summary are refused (write, batch, import).
- Link FROM a summary (summary is the predecessor): uses the summary's
  rolled-up dates: start = earliest descendant start (SS, SF), finish =
  latest descendant end (FS, FF). Never "every child" for SS/SF.
- Constraints on a summary: snet applies to every descendant start; fnlt is
  checked against the rolled-up finish (warning); mso and mfo are refused.
- A link between a summary and its own descendant is ignored for scheduling
  (warning `summary_link`).
Vectors must cover: FS into summary, SS into summary, FS from summary, SS
from summary, SF from summary, FF into summary (refused), mso on summary
(refused), snet on summary.
