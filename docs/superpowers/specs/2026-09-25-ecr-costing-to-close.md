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

Idea blocks (decided 2026-09-25, both engines MUST match):
- A link whose predecessor is an idea never drives its successor: it is
  ignored by the forward and backward pass, automatic scheduling (push),
  the post-baseline cascade and the critical path. It stays stored and
  shown. A leaf is an idea when is_idea is set; a summary is an idea when it
  has no committed (non-idea) work below it, whatever its own flag (a
  summary with real work below it always drives).
- is_idea is refused on a block that has blocks under it (400, code
  `summary_idea`), and an idea cannot gain blocks under it (create, move,
  batch). The import clears the flag on summaries with a warning.
- A link INTO an idea drives the idea: ideas follow committed work.
- Validation warns `bank_build_late` when an idea ends after the start of a
  block it links to (once per idea and successor).
- Summary dates roll up only children with committed work (a summary of
  ideas only rolls up its ideas).
Vectors: idea -> real FS (the idea, even lengthened, moves nothing real);
real -> idea (the idea moves); a summary of ideas only does not drive; a
summary flagged idea with real work below it drives.

## 12. Validation issues: the failure branch (2026-09-25)

When validation fails technically (tool cannot run, assembly does not fit,
out of tolerance, weight or cycle time off, cosmetic, packaging), the change
does not just bounce back. Each failure becomes a **validation issue** with
a light 8D shape and a decided route to the fix. Customer discussion is part
of it. Release is refused while any issue is open.

### Model (migration `090_validation_issues.py`, down_revision 089)
`change_validation_issues`:
| column | type | note |
|---|---|---|
| id | pk | |
| change_id | fk, index | |
| number | int | per change, 1..n (shown "VI-3") |
| title | String(200) | |
| category | String(30) | `tool` `equipment_assembly` `dimensional` `material_weight` `cycle_time` `cosmetic` `packaging` `documentation` `other` |
| severity | int | 1 low, 2 medium, 3 blocks production |
| department_id | fk null | owner department (who must fix) |
| check_id | fk validation_checks null | the failed check it came from |
| affected_part_id / affected_tool_ref | int null / String(120) null | what failed (part id; tool/equipment number free text) |
| description | Text | what happened |
| containment | Text null | immediate action (hold parts, protect bank, run old state) |
| contained_at / contained_by | | |
| root_cause | Text null | |
| root_cause_at / root_cause_by | | |
| route | String(30) null | `internal_rework` `supplier_rework` `design_change` `customer_concession` `follow_up_change` |
| route_reason | Text null | |
| route_decided_at / route_decided_by | | |
| supplier_name | String(120) null | for supplier_rework |
| chargeback | bool default false | supplier pays (supplier_rework) |
| customer_inform | bool default false | customer must be told |
| customer_decision | String(20) null | `accept_deviation` `require_fix` `new_timing` `pending` |
| customer_decision_note | Text null | |
| customer_decided_at / customer_decided_by | | Sales records |
| concession_until | Date null | temporary concession end (null = permanent) |
| extra_cost | Numeric(12,2) null | money (redacted for non-cost roles) |
| cost_bearer | String(12) null | `internal` `supplier` `customer` |
| follow_up_change_id | fk change_requests null | spawned follow-up ECR |
| status | String(20) | `open` -> `contained` -> `route_decided` -> `fixing` -> `revalidation` -> `closed` / `accepted` (concession) / `transferred` (follow-up change) |
| closed_at / closed_by / closure_note | | |
| created_by / created_at / updated_at | | |

`change_validation_issue_actions`: id, issue_id fk, description, owner_id fk
users null, department_id null, due_date Date null, status open|done,
done_at/by, created_by/at. (Fix actions.)

Attachments: `change_attachments.validation_issue_id` fk null (evidence and
customer mails filed into the issue; kinds `general`, `customer_email`).

### Rules
- **Raise**: any member of a routed department, PM, lead, admin, while
  `in_validation` (or `in_implementation` after a loop back). A `failed`
  validation check offers "Raise issue" prefilled (category from check key:
  cycle_time -> cycle_time, weight -> material_weight, measured ->
  dimensional, sampled -> tool, packaging_validated -> packaging,
  revision_bump -> documentation); one open issue per failed check.
- **Containment** (owner dept, PM, lead): required before a route can be
  decided when severity is 3.
- **Root cause** (owner dept, PM, lead): required before a route (all
  severities), except `customer_concession` may be decided with the cause
  still open when the customer accepts as-is.
- **Route** decided by PM or lead (not the raiser alone; 4-eyes: the decider
  must not be the raiser unless admin), with a reason:
  - `internal_rework` / `supplier_rework` / `design_change`: status
    `fixing`; if the change is `in_validation` it moves to
    `in_implementation` automatically (the existing loop back, reason =
    "VI-n: <title>: <route_reason>", changelog `validation_escalated`);
    fix actions are required (>= 1); a plan block "Fix VI-n" (kind `work`,
    lane owner dept) is added to the detailed plan after the last
    validation block via the plan service (after the baseline: as a
    deviation with the route reason). `design_change` sets
    `customer_inform = true` by default.
  - `customer_concession`: requires `customer_inform`; closes as
    `accepted` only when Sales records `customer_decision =
    accept_deviation` with a customer mail attached to the issue
    (hard rule); `concession_until` optional.
  - `follow_up_change`: creates a new ChangeRequest (captured, same
    project, reason "Follow-up of <change_number> VI-n", description from
    the issue, lead = this change's lead) and links it; issue status
    `transferred`; this change may then be released once the rest is
    closed (the follow-up carries the work).
- **Customer**: Sales records the customer decision and notes, mails filed
  into the issue. `require_fix` on a concession route reopens the route
  decision. `new_timing` means the plan deviation must be escalated to the
  customer (links the deviation escalation). A Sales task appears while
  `customer_inform` is true and no decision is recorded.
- **Cost**: `extra_cost` + `cost_bearer`; `customer` bearer creates a
  Sales task "Quote the fix" and, when the change is still commercially open
  (offer workflow), allows a supplement offer version (existing offer
  versions, note "Supplement for VI-n"). Actuals P&L includes issue extra
  costs by bearer (internal = our cost; supplier = recoverable; customer =
  revenue once quoted).
- **Fix actions**: owners mark done; all done -> status `revalidation`.
- **Re-validation**: the linked validation check is answered again
  (`passed`) by its department -> issue auto-closes (`closed`), or PM closes
  with a closure note (no linked check). A new `failed` answer keeps it open
  and reopens `fixing` (loop).
- **Guards**: `in_validation -> released` soft guard adds "n validation
  issues open"; `in_implementation -> in_validation` shows open issues in
  `fixing` as info. Changelog actions: `validation_issue_raised`,
  `_contained`, `_root_cause`, `_route_decided`, `_customer_decision`,
  `_action_done`, `_revalidated`, `_closed`, `_transferred`.
- **My actions / my tasks**: owner department: contain / root cause / fix
  actions; PM/lead: decide route; Sales: customer decision, quote the fix.
- **Rights for money**: `extra_cost` redacted for non-cost roles (price
  redactor).

### API (`/api/v1/changes/{id}/validation/issues...`)
`GET` list (IssueOut incl. actions, attachments, names, allowed next acts
for the viewer), `POST` create, `PATCH /{iid}` (title, description,
severity, category, department_id, affected fields), `POST /{iid}/contain
{containment}`, `POST /{iid}/root-cause {root_cause}`, `POST /{iid}/route
{route, reason, supplier_name?, chargeback?, customer_inform?, actions?:
[{description, owner_id?, department_id?, due_date?}]}`, `POST
/{iid}/customer {decision, note, concession_until?}`, `POST /{iid}/cost
{extra_cost, cost_bearer}`, `POST /{iid}/actions`, `POST
/{iid}/actions/{aid}/done`, `POST /{iid}/close {note}` (PM/lead, no linked
check), attachments via the existing upload with `validation_issue_id`.

### UI (Release tab, Validation step)
Validation panel: a failed check shows "Raise issue". Issues list above the
checklist: VI-n cards with a stepper (Raised, Contained, Root cause, Route,
Fixing, Re-validation, Closed), severity chip, owner, route badge, customer
decision chip, extra cost (cost roles), actions checklist, evidence and
customer mail drop zone, and one primary button for the viewer's next act.
Route decision dialog explains each route in one line and what happens
(loop back to implementation, plan block, customer mail requirement,
follow-up change). Cockpit "Blocked by" lists open issues; the release
blockers list includes them.

### 12a. Recovery timing (Gantt) and escalation plan
**Recovery plan in the Gantt.** Deciding a fix route (`internal_rework`,
`supplier_rework`, `design_change`) creates a **recovery group** in the
detailed plan: a summary block "Recovery VI-n: <title>" (lane = owner
department) placed after the failed validation block, with one child block
per fix action (duration from the action's due date or 5 working days
default, owner department lane), then "Re-validation VI-n" (kind
`validation`, 3 days) and FS links chaining them; the recovery group is
linked FS into the blocks that depended on the failed validation (SOP,
customer approval), so automatic scheduling pushes them. After the baseline
all of it is recorded as deviations with `reason = "VI-n: <route_reason>"`
and `caused_by` the recovery group (the user edits the recovery blocks in
the Gantt like any other). The issue card shows the recovery group's
finish, the new plan finish and the slip against the baseline finish and
the release deadline ("Recovery ends 14.11, SOP moves +9 wd, 4 wd after the
release deadline"). A button "Open recovery in the plan" focuses the group
in the Gantt (Timing tab, `?tab=timing&task=<id>`).

**New timing for the customer.** When the recovery pushes the plan finish
past the release deadline, the issue requires a customer timing decision:
Sales records `customer_decision = new_timing` with the new date (updates
`release_due_date` with reason "VI-n", audited as
`release_deadline_set`) or `require_fix` (keep the date: PM must shorten
the recovery). The deviations created by the recovery are escalated to the
customer together (one escalation record referencing the issue).

**Escalation plan.** Each issue has an escalation level, computed and
stored with history (`change_validation_issue_escalations`: id, issue_id,
level 1..3, reason, notified (text: who), created_by/at, acknowledged_by/at):
- Level 1, department: raised issue; owner department + PM informed.
- Level 2, project: automatic when severity 3, or a fix action is overdue,
  or the recovery slips the plan finish past the baseline finish, or no
  route decided after 2 working days; PM + change lead + Sales; Sales
  decides whether the customer must be informed.
- Level 3, management and customer: automatic when the recovery finish is
  after the release deadline, or a level-2 escalation is not acknowledged
  within 2 working days, or the customer requires a fix on a concession;
  Sales informs the customer (customer mail filed into the issue),
  management notified (users of the "Management" department if it exists,
  else admins).
- Every level change writes an escalation row, a changelog entry
  `validation_issue_escalated`, a notification to the named roles and a
  my-actions item "Acknowledge escalation VI-n (level x)"; acknowledging
  records who/when. Manual escalation (PM/lead/Sales) with a reason is
  allowed; de-escalation only by closing or by PM with a reason.
- Level is re-evaluated on every issue or plan change and by the existing
  notification sweep (notification_sweep.py) for overdue triggers.
- The cockpit shows the highest open level ("Escalation L3: VI-2 tool
  cannot run, customer informed 25.09").

### 12b. Backend notes (as built)

Errors: 400 business refusal (string `detail`), 403 rights, 404 unknown
issue / action / escalation / check on this change. Every write answers the
issue's `IssueOut`; `POST` create and `POST /{iid}/actions` answer 201.

**Model additions** (migration 090, beyond the table above): issues carry
`new_timing_date`, `customer_escalation_id` (fk implementation_escalations),
`fix_quoted_at/by` (customer bearer: Sales quoted the fix; P&L revenue
"once quoted"), `recovery_task_id`, `revalidation_task_id` (plain ints, no
FK), `escalation_level` (current, default 1). Actions carry `plan_task_id`
(their recovery block). `change_validation_issue_escalations` has a
`trigger` code: `raised severity action_overdue plan_slip no_route
release_deadline unacknowledged require_fix manual deescalate`, and
`created_by` null when the sweep raised it.

**Extra endpoints** (all under `/validation/issues`): `GET /summary`
(`{open_count, fixing_count, highest_level, top: {id, ref, title, level,
status, customer_inform, customer_decided_at}, blocker, open: [...]}`),
`GET /prefill?check_id=` (`{check_id, check_key, check_status, title,
category, severity, department_id, department_name, description,
existing_issue_id, can_raise}`), `GET /{iid}`, `POST /{iid}/fix-quoted
{note?}` (Sales), `POST /{iid}/escalate {reason, level?}` (PM, lead, Sales;
default one up), `POST /{iid}/deescalate {reason, level?}` (PM member or
admin; default one down), `POST /{iid}/escalations/{eid}/acknowledge`.

**Bodies**: create `{title, description, category?, severity?,
department_id?, check_id? | check_key + check_department_id?,
affected_part_id?, affected_tool_ref?}` (from a check: category and owner
default from it; the check must be `failed`; one open issue per check).
PATCH also takes `customer_inform` (Sales, PM, lead, admin; cannot be
switched off on a concession). contain `{containment}` (or `{text}`),
root-cause `{root_cause}` (or `{text}`). customer `{decision, note,
concession_until?, new_release_due_date?}` (`new_date` accepted as alias).
cost `{extra_cost, cost_bearer}` (bearer required when a cost is set).

**IssueOut**: every column plus `ref` ("VI-n"), `department_name`,
`check_key`, `check_department_id`, `check {id, check_key, label,
department_id, department_name, status}`, `affected_part_number`, `*_name`
for every user column, `cost_visible`, `extra_cost` (null when redacted),
`cost_set`, `currency` ("EUR"), `can_supplement_offer`,
`follow_up_change_number`, `step` (`raised contained root_cause route
fixing revalidation closed`), `is_open`, `actions [{id, issue_id,
description, owner_id, owner_name, department_id, department_name,
due_date, status, overdue, done_at, done_by, done_by_name, plan_task_id,
can_done, created_by, created_at}]`, `attachments [{id, filename, kind,
content_type, size_bytes, phase, validation_issue_id, uploaded_by,
uploaded_by_name, created_at}]`, `has_customer_mail`, `escalation_level`,
`escalations [{id, level, trigger, reason, notified, created_by,
created_by_name, created_at, acknowledged_by, acknowledged_by_name,
acknowledged_at, needs_ack, can_acknowledge}]` (oldest first), `escalation
{level, level_name, unacknowledged, latest, history}` (same rows),
`recovery` (below), `next_acts`, `primary_act`, `extra_acts`.

**next_acts** is ORDERED; the first entry outside `edit attach escalate
add_action` is the primary button (`primary_act`). Names and when:
`acknowledge` (an unacknowledged level 2/3 row the viewer was notified of),
`contain` / `root_cause` (no route yet, not recorded, owner department / PM
/ lead / admin), `route` (no route, PM / lead / admin and not the raiser
unless admin, change in approved / in_implementation / in_validation,
containment present at severity 3), `customer` (Sales / admin while
`customer_inform` and no decision or `pending`), `action_done`, `close`
(PM / lead / admin, no linked check, status `revalidation`), `cost` (cost
roles, no cost recorded yet), `add_action` (owner side, fix route),
`escalate` (PM / lead / Sales, level < 3), `edit`, `attach` (owner side or
Sales). `extra_acts`: `quote_fix` (Sales, customer bearer, not quoted),
`deescalate` (PM member or admin, level > 1).

**recovery** (null without a recovery group): `{summary_task_id, task_id
(same), revalidation_task_id, start, finish, plan_finish, baseline_finish,
release_due_date, release_deadline (same), slip_days, slip_workdays,
slip_baseline_wd, slip_deadline_wd, past_deadline_days,
past_deadline_workdays, plan_past_deadline_days, needs_timing_decision}`.
Every finish is the INCLUSIVE last day. `slip_*` compare the plan finish
with the baseline finish / release deadline; `past_deadline_*` compare the
recovery finish with the deadline; working days are Mon-Fri.
`needs_timing_decision`: the plan finish is past the release deadline and
no `new_timing` is recorded.

**Rules as built**:
- Raise window: `in_validation`, or `in_implementation` when the status
  changelog shows the change was in validation before. "Routed department"
  = any department with an assessment row or with priced implementation
  work.
- Route: 4-eyes refuses the raiser (403) unless admin. Fix routes need an
  open action (existing or in the body). The loop back runs
  `ChangeService.transition(..., reason="VI-n: <title>: <route reason>")`
  (its guards apply: a refusal fails the route decision). Supplier rework
  needs `supplier_name`. A `require_fix` on a concession clears the route
  (status back to contained / open) and the next route decision clears
  the `require_fix` decision.
- Recovery group: anchored after the latest-ending `validation` block of
  the detailed plan (no validation block: no incoming link, starts today);
  it never starts before today. Fix blocks run in parallel from the start
  (duration to the action's due date, else 5 working days, 7 calendar days
  in calendar mode), "Re-validation VI-n" (kind `validation`, 3 days, lane
  of the failed check's department) after all of them; the anchor links FS
  into the summary, the re-validation links FS into every block the anchor
  linked to. Before the baseline it is one `ChangePlanService.apply_changes`
  ChangeSet (auto-push moves the successors, revision bump). After the
  baseline `apply_changes` refuses structural edits, so the service writes
  the blocks and links itself (using the plan service's helpers, unchanged)
  and records deviations with reason "VI-n: <route reason>": one for the
  summary (old = zero-length at its start) and one per pushed block with
  `caused_by_task_id` = the summary. No detailed plan: no recovery group
  (`recovery` null). Actions added after the route are not added to the
  plan.
- Customer: `accept_deviation` closes (status `accepted`) only on a
  concession route and only with a `customer_email` attachment filed into
  the issue. `new_timing` needs `new_release_due_date`, moves
  `release_due_date` through the audited `release_deadline_set`
  (reason "VI-n") and escalates every OPEN deviation whose reason starts
  with "VI-n:" under ONE `ImplementationEscalation(direction="customer")`
  (`customer_escalation_id`). Any decision sets `customer_inform`.
- Re-validation: `ValidationService.record_check` calls
  `ValidationIssueService.on_check_answered`: a `passed` answer closes every
  open issue linked to that check (whatever its step), a `failed` answer
  sends a linked issue in `revalidation` back to `fixing`. Close by hand:
  PM / lead / admin with a note, only without a linked check, from
  `revalidation` (or `open` / `contained` for an issue raised in error).
- Attachments: `POST /changes/{id}/attachments` takes form field
  `validation_issue_id` (kinds `general`, `customer_email`; open issue;
  owner department, PM, lead, Sales, raiser, admin; exclusive with the
  other containers). Delete follows the default rule (uploader, lead, PM,
  admin). `AttachmentResponse.validation_issue_id` added.
- Escalation: a level only rises automatically; a trigger already recorded
  at a level does not fire again (so a PM de-escalation sticks until a new
  trigger). Level 3 sets `customer_inform`. Audience: L1 owner department +
  PM; L2 PM + lead + Sales; L3 adds Management (or active admins when that
  department has no members). Notifications `kind
  validation_issue_escalated`, link `/changes/{id}?tab=release&issue={iid}`.
  Re-evaluated after every issue write and by the sweep
  (`counts["validation_issue_escalated"]`); plan edits outside the issue
  endpoints are picked up by the sweep.
- Guards: `in_validation -> released` adds "n validation issue(s) open"
  after the validation-check blocker (transferred / accepted / closed do
  not count); the release tab `blockers` list carries the same text.
  `ValidationIssueService.fixing_info` gives the "still fixing" info for
  `in_implementation -> in_validation` (not a guard).
- my_actions / my-tasks kinds (`target_tab: "release"`, `issue_id`):
  `validation_issue_contain` (owner dept, severity 3), `_root_cause` (owner
  dept), `_route`, `_action` (action owner / department), `_customer`,
  `_quote`, `_close`, `_escalation` (+ `escalation_id`, `level`; label
  "Acknowledge escalation VI-n (level x)"). Admins get none of the role
  rows (they act on the card). my-tasks rows carry `hint` = label.
- Money: `extra_cost` is in `PRICE_KEYS` (changelog / audit redaction) and
  null in `IssueOut` outside the cost roles; `cost_set` still tells.
  `can_supplement_offer` is only a flag (customer bearer while the change is
  quoting / quoted); no offer is created by the issue.

## 13. P&L rough cut: offer vs doing (2026-09-25)
Not deep, but every change always compares the offer with what happened.

Per change (`GET /api/v1/pnl/changes/{id}/offer-vs-actual`, cost roles only):
```
{ currency, basis: "accepted_offer" | "sent_offer" | "internal_approval" | "costing",
  offer_version, lines: [
   {key: "revenue", label, planned, actual},          # accepted offer total (+ supplements) ; actual = same + quoted issue supplements
   {key: "internal", label, planned, actual},         # planned: costing internal (hours x rate) snapshot at acceptance; actual: booked hours x department rate
   {key: "external", label, planned, actual},         # planned: costing external (chosen/favourite vendor); actual: actual cost entries
   {key: "issues_internal", label, planned: 0, actual},   # validation issues borne by us
   {key: "issues_supplier", label, planned: 0, actual},   # recoverable from supplier (shown, not in margin)
   {key: "issues_customer", label, planned: 0, actual},   # billed to customer (adds to revenue actual when quoted)
   {key: "scrap", label, planned, actual} ],
  planned_margin, actual_margin, planned_margin_pct, actual_margin_pct, variance,
  timing: {baseline_finish, forecast_finish, actual_finish, slip_days, unit},
  piece_price: {delta_per_piece, annual_volume, annual_effect} | null,
  warnings: [ "no accepted offer", "hours booked without department rate", ... ] }
```
Planned figures are frozen at customer acceptance (or internal approval) in
the accepted offer's `_snapshot.pnl` (add to the snapshot on acceptance;
older changes fall back to current costing with basis "costing").

New table (migration `091_actual_costs.py`, down_revision "090"):
`change_actual_costs` (id, change_id idx, department_id null, category
`external` | `scrap` | `other`, vendor_name String(120) null, amount
Numeric(12,2), cost_date Date, note Text null, attachment_id null,
created_by/at). Write: cost roles, and members of the named department
for their own department; read: cost roles.
`GET/POST/DELETE /api/v1/changes/{id}/actual-costs`.

P&L page (`/pnl`) list gains columns Offer revenue, Planned cost, Actual
cost, Planned margin, Actual margin, Variance, Slip; summary tiles aggregate
the same. UI: PnlCard shows plan only before implementation, then the
offer-vs-actual table with variance chips, the timing line and an "Add
actual cost" form (supplier invoice lines); the release summary uses the
same card.

## 14. Mother-plant changes (side track, 2026-09-25)
Some changes are engineered and commercially handled by the mother plant.
We have no feasibility and no quoting phase: the goal is to inform the team
what is done, take the mother plant's timing, and start directly with bank
build planning and implementation.

- **Origin**: `change_requests.origin` String(20) `customer` | `internal` |
  `mother_plant` (migration after the ones in flight; backfill from
  customer_relevant), plus `mother_plant_name` String(120),
  `mother_plant_ref` String(120), `mother_plant_sop` Date.
  Mother plants are a dropdown, default **KTX Weissenburg (WUG)**, second
  option **KTX Solingen** (rare); stored as the name string, list in config
  (`app/services/mother_plants.py`) so more can be added. `customer_relevant`
  stays false for mother-plant changes (no quote deadline, no offer).
- **Start**: StartChangeModal option "Change from mother plant": name,
  reference, SOP date (required), documents, optional MS Project file for
  their timing. Who may start: `can_start_change` departments and PM.
- **Flow**: `captured -> scoping -> approved -> in_implementation ->
  in_validation -> released -> closed`. New allowed transition
  `scoping -> approved` only for origin mother_plant, hard-gated on the
  impact lock (Development) and the inform list being sent; no
  assessment/costing/quoting/quoted statuses ever. On entering `approved`:
  `release_due_date = mother_plant_sop` (reason "Mother plant timing"),
  detailed plan seeded from the imported file if given, else empty with
  the SOP milestone.
- **Team informed**: at scoping the PM selects departments to inform
  (default: the physical-part routing departments). "Send information"
  creates one `change_info_receipts` row per department (id, change_id,
  department_id, sent_by/at, acknowledged_by/at, note) and a My Tasks item
  "Read and understood" for its members; acknowledging may carry a note
  back. Open receipts show in Blocked by (info, not a gate).
- **Timing**: Timing tab as for other changes (detailed plan, bank build,
  team confirmation, baseline, publish is not needed: no customer publish;
  "Inform mother plant" stamp instead), deviations and validation issues as
  usual; escalation level 3 informs the mother plant contact (text) instead
  of the customer, via PM.
- **Tabs**: Assessments, Costing, Offer replaced by one "Mother plant"
  tab (reference, documents, SOP, their timing file, inform list with
  receipts). LifecycleStepper shows only the used stages.
- **P&L**: actual local costs only (no offer basis; basis "none").

## 15. Cost sheet, Finance controlled (side track, 2026-09-25)
Hourly costs come from a per-position cost sheet that Finance maintains and
updates regularly. Separate module, feeds costing and the P&L.
- **Model**: `cost_sheet_versions` (id, organization_id, version int,
  valid_from Date, published_at/by, note, status draft|published) and
  `cost_sheet_rates` (id, version_id, department_id, position String(80)
  null (e.g. Engineer, Technician, Toolmaker; null = department default),
  plant_id null (null = all plants), hourly_rate Numeric(10,2), currency
  String(3), note). Existing `department_rate` rows migrate into version 1
  (valid_from = earliest, published).
- **Rights**: edit drafts and publish: members of the "Finance" department
  (create it if missing) or admin; read: everyone (rates are public by
  design). Publishing a draft freezes it; the previous version stays
  readable with its validity end = new valid_from - 1.
- **Stale warning**: org setting `cost_sheet_review_months` (default 12);
  banner on the cost sheet page and in costing when the latest published
  version is older; My Tasks item for Finance.
- **Rate lookup**: `rate_for(department, position, plant, on_date)` =
  most specific match (dept+position+plant > dept+position > dept+plant >
  dept) in the version valid on that date. Costing lines store the rate
  snapshot and the version id; P&L actuals use the rate valid on the
  booking date; offers warn "costing used cost sheet v3, current is v4".
  Bookings may name a position (optional) to pick the position rate.
- **UI**: sidebar Setup > "Cost sheet": version selector with validity,
  table department x position x plant, inline edit in drafts, "Publish
  version" with valid-from and note, diff to previous version, CSV/XLSX
  export.

### 15a. Machine cost, sampling per tonnage, personnel overhead
Same versioned sheet (one publish covers all parts):
- `cost_sheet_machine_rates` (version_id, plant_id null, machine_class
  String(40) e.g. tonnage class "<=200 t", "200-450 t", "450-800 t",
  ">800 t" (classes defined per org, editable), optional machine_ref
  String(80) for a specific press, tonnage_min/max int null,
  hourly_rate Numeric(10,2), currency, note).
- `cost_sheet_sampling_rates` (version_id, plant_id null, machine_class,
  mode `flat` | `components`; flat_price per trial; or setup_hours,
  run_hours_default, handling_cost, and the machine rate of that class ×
  hours + labour hours × effective labour rate; computed price shown).
- Personnel overhead: `cost_sheet_overheads` (version_id, plant_id null,
  department_id null (null = all), kind `percent` | `per_hour`, value).
  Effective labour rate = base position rate x (1 + percent) or + per_hour;
  most specific overhead wins (dept+plant > dept > plant > org).
- Use: costing lines of kind own_time use the effective labour rate;
  new costing line kinds `machine_time` (hours x machine class rate) and
  `sampling` (trials x sampling price of the class); implementation
  bookings may carry machine class hours; P&L actuals use the rates valid
  on the booking date; the Gantt's sampling / re-validation blocks show the
  sampling cost estimate when a machine class is set on the change
  (change-level `machine_class`, default from the impacted tool's
  tonnage if known).
- UI: cost sheet page tabs "Positions", "Machines", "Sampling",
  "Overheads", each with the version's validity; effective rate column
  on Positions.
