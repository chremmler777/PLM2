# ECR training content: how it is wired in

Written 2026-09-25, wired into the app 2026-09-26. Chapters 01 to 08 of the
in-app manual ("Training", "Manual") and the printable handout pages are
rendered from this directory. The training is documentation only: recorded,
never blocking a change action. Screenshots and a final label check come after
the UI polish.

## What is here

| File | Holds |
|---|---|
| `types.ts` | The data shapes: `Block`, `ContentSection`, `ContentChapter`, `PracticeTaskSpec`, `ScreenSpec`, `ShotSlot` |
| `shared.ts` | Chapter 01 (basics) and 02 (flow, with the three side tracks) |
| `projectManagement.ts`, `sales.ts`, `engineering.ts`, `scheduling.ts`, `quality.ts`, `finance.ts` | Chapters 03 to 08, each with its practice task specs |
| `index.ts` | `CONTENT_CHAPTERS`, `PRACTICE_TASKS_BY_ROLE`, `PRACTICE_TASKS`, `SHOT_SLOTS`, `contentFor(id)` |
| `render.tsx` | `renderBlocks(blocks, available?)`: blocks onto `../kit.tsx`; a shot renders as a named "Screenshot follows" frame (`ShotPlaceholder`) until its file exists |
| `handouts.ts` | The one-page handout per role (`HANDOUTS`), `practiceOf(role)` (tasks this build runs, and the ones coming), `handoutMarkdown(h)` |
| `content.test.ts` | House rules: no dashes or placeholder words, unique ids and shots, 2 to 4 tasks per role, every chapter wired, every shot slot listed in section 2 below |
| `handouts.test.ts` | The handouts follow the house rules and `docs/training/handouts/*.md` equal `handoutMarkdown` |

Outside the code: `docs/training/handouts/*.md` (one page per role, generated
from `handouts.ts`), `docs/training/rollout-announcement.md`,
`docs/training/roster-template.md` (both parked, see section 8).

Run the tests: from `frontend/`,
`npx vitest run src/training/manual/content --maxWorkers=2 --minWorkers=1`
(`--minWorkers=1` is needed: `--maxWorkers=2` alone collides with the default
minimum thread count on a many-core machine).

## 1. How the chapters are wired

`../chapters.tsx` builds chapters 01 to 08 with `written(id, number, roles)`:
title, summary and sections come from `contentFor(id)`, each section body is
`renderBlocks(section.blocks, SHOTS_AVAILABLE)`. Chapter 09 (`record`) is
written in `../chapters.tsx` itself. Section ids are the anchors of the
Manual tab (prefixed with the chapter id, unique across the manual).

The printable handout (`/training/handout/<role>`, `pages/TrainingHandoutPage.tsx`)
prints the role's one-page handout from `handouts.ts`, the practical check
(the tasks the server's curriculum asks, then the ones coming, see section 3)
and the record block. "With the full chapters" (`?full=1`) appends the role's
chapters on a new page.

To change a handout, edit `handouts.ts`, then rewrite the markdown files:
`WRITE_HANDOUTS=1 npx vitest run src/training/manual/content/handouts.test.ts --maxWorkers=2 --minWorkers=1`.
Without the variable the test fails when a file differs.

When the material changes what a role has to know, bump `code_version` for
that role in `backend/app/services/training.py` and publish from "Training",
"Records", "Publish a new version" when the plant is ready. Not done for this
wiring: no role has been trained on version 1 yet (the training record
arrives with the costing-to-close rollout), so version 1 is this material.

## 2. Screenshots

49 slots, in manual order (`SHOT_SLOTS` holds the same list with the
chapter, the section and in `alt` what the picture must show; the frame in the
manual shows the slot name and that text until the picture exists).
`content.test.ts` checks this table names every slot once and nothing else.
After the polish:

1. Take each shot on a seeded demo change in the state below, save it as
   `frontend/public/manual/<slot>.png`.
2. Add the slot name to `SHOTS_AVAILABLE` in `../chapters.tsx`. The frame
   becomes a `Figure`.

| Slot | Section | Screen | State it needs |
|---|---|---|---|
| `basics-sidebar` | `basics-access` | Any page, sidebar expanded | A user who sees "Changes", "Process Flow", "P&L", "My Tasks" and "Training" |
| `basics-project-team` | `basics-team` | Project page, "Project team" card | A project with a responsible for every department but one ("Unassigned") |
| `basics-backup-row` | `basics-team` | "My Tasks" | Viewer is a backup (not the responsible) of a department with an open task |
| `basics-my-tasks` | `basics-finding` | "My Tasks" | Viewer with own open tasks and backup tasks ("+N as backup"), cropped to the "Open tasks" header, the first rows and the first muted backup row; one image per slot, so the "New indexes" section (a Development member) is named in the alt text only |
| `basics-cockpit` | `basics-finding` | Change page, cockpit | A change in assessment where the viewer owes an action and one department blocks |
| `flow-stepper` | `flow-overview` | Change page, lifecycle stepper | A change in "Quoted" (offer v1 sent) |
| `flow-gantt-baseline` | `flow-implementation` | "Timing" tab, detailed plan in tracking mode | In implementation, baseline set, one block slipped past its ghost |
| `flow-issue-card` | `flow-issues` | "Release" tab, validation issue card | In validation, VI-1 at level L2 with a severity chip |
| `pm-next-step-capture` | `pm-takeover` | Change cockpit, "Next step" card | A captured change without a lead or without an attachment |
| `pm-status-card` | `pm-priority` | Change cockpit, "Status" card | Priority set, a lead, a quote deadline 6 days out |
| `pm-impact-tree` | `pm-scoping` | "Impacted" tab, impact tree | Scoping, lead item picked, two suggested parent assemblies, not yet confirmed |
| `pm-scoping-meeting` | `pm-scoping` | "Scoping" tab, "+ Record a meeting" form | Scoping, impacted set confirmed, letters set per department (one "Informed"), cost carrier chosen |
| `pm-routing-pending` | `pm-assessment` | "Assessments" tab, routing banner | In assessment, the lead asked to take one department off routing ("Take off routing"), not yet decided |
| `pm-cost-summary` | `pm-costing` | "Costing" tab, "Cost summary" | Costing, at least two departments priced, viewer PM |
| `pm-signoff` | `pm-signoff` | "Offer" tab, customer response | Quoted, customer accepted, PM signed, Quality still open |
| `pm-validate-timing` | `pm-plan` | "Timing" tab, the three steps | Approved, detailed plan created, every team confirmed, no idea block |
| `pm-deviations` | `pm-plan` | "Timing" tab, "Deviations from the baseline" | In implementation, one open group: a block moved +3 d and one successor it pushed |
| `pm-route-dialog` | `pm-issues` | "Release" tab, validation issue, "Decide the route" dialog | VI-1 raised by another user, contained, root cause recorded; "Internal rework" with one fix action typed |
| `sales-start-form` | `sales-start` | "Changes", "New Change Request" form | Sales viewer; a project with two parts from one tool, both picked, a short description and a quote deadline |
| `sales-question-card` | `sales-documents` | "Scoping" tab, open question | Scoping, one open question asked by an engineer, not answered |
| `sales-offer-price` | `sales-quote` | "Offer" tab, "Price" step | Quote creation, costing closed, draft offer v1 with one factor switched on |
| `sales-offer-pdf` | `sales-quote` | Offer PDF, page 1 | A sent version with a receipt date (dates read like "26 Sep 2026", signed by the Sales sender) |
| `sales-offer-versions` | `sales-versions` | "Offer" tab, "Negotiation" timeline | Quoted, v1 superseded, one logged round, v2 sent with a change note |
| `sales-customer-response` | `sales-answer` | "Offer" tab, "Customer response" | Quoted, v2 sent, no customer response yet |
| `sales-issue-decision` | `sales-after` | "Release" tab, validation issue, "Record customer decision" | VI-1 routed as "Customer concession", customer to be informed, a mail filed |
| `eng-bucket` | `eng-assessment` | "Assessments" tab, Tool Engineer bucket | In assessment, viewer a Tool Engineer member, a mold on the impacted set |
| `eng-checklist` | `eng-checklist` | "Assessments" tab, "Impacted areas" | 8 of 13 rows answered, one Yes with its remark |
| `eng-risk-on-row` | `eng-risks` | "Assessments" tab, "⚑ Flag risk" on a Yes row | The flag form open with a risk type and a rating chosen |
| `eng-cost-positions` | `eng-costing` | "Costing" tab, own department's "Cost positions" | Costing, the standing rows, one "External · vendor quote" line with two offers, one starred |
| `eng-team-confirmation` | `eng-plan` | "Timing" tab, "Team confirmation" | Approved, detailed plan, the viewer's department not yet confirmed |
| `eng-tracker` | `eng-implementation` | "Timing" tab, "Reports and time booking" | In implementation, a report due, some hours booked |
| `eng-failed-check` | `eng-validation` | "Release" tab, "Validation checks" | In validation, one check failed with its reason, no issue raised yet |
| `eng-release-checklist` | `eng-release` | "Release" tab, "Release checklist" | In validation, the 16 rows, some "Done", one "N.a." with a note |
| `eng-intake-route` | `eng-development` | "My Tasks", "New indexes", triage dialog | A pending index C of part 20-9001-001-0, viewer a Development member |
| `sch-assessment-checklist` | `sch-assessment` | "Assessments" tab, Scheduling bucket | Scoping routed Scheduling (R); "Finished-part stock affected" and "Bank build needed" answered Yes with a remark, the rest No |
| `sch-bank-build-card` | `sch-bankbuild` | "Timing" tab, "Bank build plan" card | Approved; "Planned scrap" with a scrap quote price and a plan note |
| `sch-bank-build-idea` | `sch-bankbuild` | "Timing" tab, Gantt | A plan with a "Tool downtime" block and the dashed "Bank build (idea)" ending at its start |
| `sch-team-confirmation` | `sch-plan` | "Timing" tab, "Team confirmation" | Scheduling confirmed before the last plan edit (the stale chip shows) |
| `sch-deviation-dialog` | `sch-plan` | "Timing" tab, "Record a deviation" dialog | In implementation, baseline set, a block dragged, reason typed |
| `sch-release-checklist` | `sch-release` | "Release" tab, "Release checklist" | In validation, the two Scheduling rows "Done" |
| `qa-signoff` | `qa-signoff` | "Offer" tab, customer response | Quoted, customer accepted, PM signed, viewer a Quality member |
| `qa-audit-tab` | `qa-governance` | Governance, "Audit" tab | A change with a sign-off in its history, viewer a Quality member |
| `qa-lessons` | `qa-release` | "Release" tab, "Lessons learned" | In validation, one lesson recorded, the "+ Add lesson" form open |
| `qa-records-tab` | `qa-training` | "Training", "Records" tab | Viewer with manage rights (Quality or PM), several people on the roster in every state |
| `fin-cost-sheet` | `fin-costsheet` | "Cost sheet", "Rates" tab | A current published version, viewer Sales or Finance |
| `fin-machines` | `fin-costsheet` | "Cost sheet", "Machines" tab | MachineDB synced (or seeded), one press with its own rate in the version |
| `fin-publish-dialog` | `fin-costsheet` | "Cost sheet", "Publish version" dialog | A draft (version 3) with two rows that differ from version 2 |
| `fin-no-rate-line` | `fin-in-costing` | Change "Costing" tab | A costing line of a department without a rate at the change's plant |
| `fin-review-banner` | `fin-review` | "Cost sheet" page | The current version older than the review period; one plant currency unconfirmed |

## 3. Practice tasks: active today, the rest coming

Active means the backend curriculum asks for the key
(`backend/app/services/training.py` `CURRICULA`) and `../../tasks.ts` can run
and score it in the sandbox. Only those are in the practical check. Every
other written task (`PracticeTaskSpec` in the chapter files) is shown as
"Coming later" on the role card of the Training page and on the printable
handout, as plain text: no button, not in the record (`practiceOf(role)` in
`handouts.ts`). Training stays recorded, not blocking.

| Role | Active today (key) | Coming (written spec, needs the sandbox) |
|---|---|---|
| project_management | `pm_set_priority` | `pm_scoping_proceed`, `pm_decide_deviation`, `pm_route_issue` |
| sales | `sales_start_change` | `sales_send_offer`, `sales_new_version`, `sales_issue_customer_decision` |
| engineering | `eng_answer_checklist_row`, `eng_submit_assessment` | `eng_costing_vendor_quotes`, `eng_contain_issue` |
| scheduling | `sch_answer_checklist_row` | `sch_bank_build_plan`, `sch_resolve_bank_idea`, `sch_timing_concern`, `sch_release_stock` |
| quality | `qa_answer_checklist_row` | `qa_quality_signoff`, `qa_flag_row_risk`, `qa_add_lesson` |
| finance | `fin_answer_checklist_row` | `fin_publish_rate`, `fin_add_missing_rate`, `fin_confirm_currency` |

`qa_flag_row_risk` is the nearest: same screen as `qa_answer_checklist_row`,
the sandbox already answers `/concerns`; it needs a check in `tasks.ts` and the
key swap below. The three checklist tasks of Scheduling, Quality and Finance
stay active until their replacements run (open question 1).

Each `PracticeTaskSpec` carries the fields of `TrainingTask` in
`../../tasks.ts` (`key`, `title`, `brief`, `why`, `screen`) plus `fixture`
(what the sandbox must hold) and `pass` (one assertion per line on the
outcome, with the hint shown on a fail). A check function is written from
`pass` in order: the first failing assertion returns its hint. When a coming
task is activated it leaves the "Coming later" list on its own.

Every role stays within `MAX_TASKS_PER_ROLE = 5`.

Changing the keys is a contract change, in one go:
`backend/app/services/training.py` `CURRICULA[role].tasks` and `code_version`,
`backend/tests/test_training.py`, `frontend/src/training/tasks.test.ts`
`EXPECTED`, and `TASKS_BY_ROLE` in `tasks.ts`. The browser refuses a
curriculum it cannot score (`assertCurriculumCovered`), so ship the sandbox
screens before the keys.

### New sandbox screens and handlers

Each `needs-sandbox` task needs a `Screen` kind in `tasks.ts`, a branch in
`TaskScreen.tsx` mounting the real component, fixture rows in
`sandbox/state.ts`, and handlers in `sandbox/adapter.ts` for every request
that screen makes (a miss throws, by design).

**Fixtures are per task.** Each task's `fixture` describes the sandbox state
that task starts from, and nothing else. Two tasks never share a change or an
issue number, so a builder can seed each one without reconciling states (one
change cannot be in implementation for one task and in validation for
another). The numbers in use, one per task:

| Change | Task | State |
|---|---|---|
| CR-TRAIN-0001, 0002 | existing tasks | exist today in `sandbox/state.ts` |
| CR-TRAIN-0003 | `sch_bank_build_plan` | approved, no bank build mode |
| CR-TRAIN-0004 | `pm_decide_deviation` | in implementation, baseline, two open deviations |
| CR-TRAIN-0005 | `pm_scoping_proceed` | scoping, lead, quote deadline, impact confirmed |
| CR-TRAIN-0006 | `eng_costing_vendor_quotes` | costing |
| CR-TRAIN-0007 | `sales_new_version` | quoted, v1 sent |
| CR-TRAIN-0008 | `pm_route_issue` | validation, VI-1 contained with root cause |
| CR-TRAIN-0009 | `eng_contain_issue` | validation, VI-1 not contained |
| CR-TRAIN-0010 | `sales_issue_customer_decision` | validation, VI-1 routed as concession |
| CR-TRAIN-0011 | `sch_release_stock` | validation, release checks open |
| CR-TRAIN-0012 | `qa_add_lesson` | validation, no lessons |
| CR-TRAIN-0013 | `sales_send_offer` | quoting, one severity-3 risk (hidden) |
| CR-TRAIN-0014 | `fin_add_missing_rate` | costing, one line without a rate |
| CR-TRAIN-0015 | `qa_quality_signoff` | quoted, v2 accepted, PM signed |
| CR-TRAIN-0016 | `sch_resolve_bank_idea` | approved, idea block past the downtime |
| CR-TRAIN-0017 | `sch_timing_concern` | approved, detailed plan revision 2 |

"Trainee acts as a ... member" in a fixture names the department the sandbox
user must belong to. The sandbox has no role emulation beyond that, so a pass
criterion never asserts that another role was refused (the refusals are
covered by the handler and backend tests).

| Screen kind | Real component | Requests to answer (from `src/api`) |
|---|---|---|
| `scoping` | `ScopingPanel` | `/v1/changes/{id}/meetings`, `.../meetings/{mid}`, `.../meetings/{mid}/decide`, concerns, departments, recommended departments |
| `costing` | `CostingBuckets` / `CostPositions` | costing positions, `.../costing/positions/{pid}/offers`, `.../costing/offers/{oid}`, attachments, suppliers, costing context |
| `offer` | `OfferTab` (+ `CustomerDecision`) | `/v1/changes/{id}/offers` (+ `/{oid}`, `/send`, `/refresh`, `/received`, `/pdf`), `.../negotiations`, `.../customer-response`, `.../sign-off`, the plan (quote) |
| `timing` | `TimingTab` | `/v1/changes/{id}/plan` family (tasks, feedback, validate-timing, deviations lock and escalate), `.../bank-build` |
| `release` | `ReleaseTab` | `/v1/changes/{id}/release`, `.../release/checks/{key}`, `.../lessons`, validation checks |
| `validation-issue` | `IssuesPanel` | `/v1/changes/{id}/validation/issues` family (contain, root-cause, route, customer, actions), attachments with `validation_issue_id` |
| `cost-sheet` | `CostSheetPage` body | `/v1/cost-sheet` family (drafts, versions, rates, publish, plants currency) |

The exact request list per screen is found the same way as for today's
screens: mount it in `TrainingSandbox.test.tsx` and read `state.misses`.

## 4. Labels to re-check after the polish

Every label in double quotes was checked against `frontend/src` on
2026-09-25. These are the ones most likely to move, or that were cited with
care. Grep each one again before publishing.

| Label as cited | Source today | Why re-check |
|---|---|---|
| "Change from" + plant | `StartChangeModal.tsx` (template `Change from {p}`) | Template; plant name form may change |
| "Index {rev} pending triage", "Triage index {rev} of {part}" | `intake/IntakePanel.tsx`, `intake/IntakeSection.tsx` | Templates, cited with placeholders |
| "Send information to" + departments | `motherPlant/MotherPlantTab.tsx` (`Send information to {n} department{s}`) | Template |
| "Inform" + plant | `motherPlant/InformMotherPlant.tsx` (`Inform {p}`) | Template |
| "{n} of {m} confirmed", "{n} × No ({b} set via Rest to No)" | `TeamFeedbackPanel.tsx`, `AssessmentBuckets.tsx` | Templates |
| "Rest to No" | `cmLabels.ts` `check.restNo` shows "Rest → No" | The copy writes "Rest to No", as `tasks.ts` does; make the screen and the copy agree in the polish |
| "Lower to L1" | `validation/EscalationHistory.tsx` (template `Lower to L{n}`, PM or admin only) | Template, cited for an L2 issue |
| "Cost sheet v{v} is older than {m} months (review due {due})" | `cmLabels.ts` `costing.stale` | Template; the cost sheet page itself shows "Cost sheet review due" (`StaleBanner.tsx`) |
| "Priced from cost sheet v{v} ({plant}, {cur})", "Review every {n} months" | `CostingSheetBar.tsx` via `cmLabels.ts`, `CostSheetPage.tsx` | Templates |
| "Quote in 6 d" (shot alt only) | `DeadlineChip.tsx` template | Template |
| "Publish plan to customer" | `TimingTab.tsx:246` | The Bank build card has "Publish plan to the customer" (hidden on Timing); the polish may unify them |
| "Validate timing" / "Timing validated" | `TimingTab.tsx` | Button vs step title; easy to swap |
| "Record customer decision", "Decide the route", "Record containment", "Record root cause", "Tick my fix action" | `validation/issueModel.ts` `ACT_LABEL` | Primary button texts, likely polish targets |
| "Accepts the deviation", "Requires a fix", "New timing", "Pending" | `validation/issueModel.ts` | Choice labels |
| "L1 Department", "L2 Project", "L3 Management and customer" | `validation/issueModel.ts` | Level names |
| "Import MS Project" | `GanttPlanner.tsx` (empty plan); toolbar has "Import MS Project (.xml)" | Two spellings |
| "+ Risk not on the checklist" | `ConcernStrip.tsx` renders `+ {text}` | Composed |
| "External · estimate", "External · vendor quote", "+ offer", "Own time" | `cmLabels.ts` | Lower case "+ offer"; the source mixes "Favourite" and "pick a favorite" |
| "Final assessment", "Feasibility", "Budget", "Release" (D1) | `D1MasterPanel.tsx`, `cmLabels.ts` | Who may decide a gate: the cockpit says the change lead; the Quality chapter only claims Quality may edit D1 master data |
| "Cost sheet review due", "Plant currencies", "Publish backdated anyway" | `costSheet/*` | New module |
| Validation check names ("Tool sampled", "Part measured", ...) | fallback names in `cmLabels.ts`; real names come from the backend | Backend may name them differently |
| Plan warning texts (bank build ends after downtime, idea blocks) | `backend/app/services/change_plan_service.py` | Paraphrased in the copy, not quoted |
| Offer warning "costing used an older version" | backend `offer_service.py` warning `cost_sheet_outdated` | Paraphrased, not quoted |
| "Lock all {n}", "Lock", "Escalate to customer" | `timing/DeviationsPanel.tsx` | Group decision labels (2026-09-26); "Lock all {n}" is a template |
| "Take off routing", "Removal requested, awaiting decision", "Routing change awaiting approval" | `cmLabels.ts` `lateAssess.*`, `routingDev.*` | Routing removal waits for approval (2026-09-26) |
| "Departments to inform", "Send information to the team" | `cmLabels.ts` `mp.informDepartments`, `mp.sendInfo` | Mother-plant scoping (final walk) |
| "Signed by (preview)" | backend `offer_pdf.py` | PDF text, not a screen label |
| "Any machine (class rate)", "Sync from MachineDB", "Machines from MachineDB", "Class rate / h" | `cmLabels.ts` `costpos.machineAny`, `costSheet/MachinesPanel.tsx` | New module, cost sheet work in progress |
| Silao USD/MXN exchange rate | backend `cost_sheet_service.py` (106), no screen label yet | The chapters describe the behaviour and quote only the backend refusal "Enter the USD/MXN exchange rate of this version first"; quote the screen labels once the cost sheet shows the exchange rate |

Descriptions that are not labels but are claims about behaviour, to confirm
on the polished build:

- The "My Tasks" header counts only main (responsible) rows; backup rows are
  listed after them (`MyTasksPage.tsx`, spec section 18a).
- After the baseline only plan editors (PM, Sales, Scheduling, the lead,
  admin) move dates; members of the owner department set progress and actual
  dates on their own blocks.
- Every risk starts hidden on the offer and Sales opts it in; the page warns
  while a severity-3 risk is hidden (`offer_service.py` risk rows with
  `"show": False`, final walk P2-7, written against the working tree before
  it was committed). The Engineers, Quality and Sales chapters and the
  `sales_send_offer` fixture teach it. If that change does not ship, severity
  3 is shown by default again and those sentences change back.
- `components/costSheet/PublishDialog.tsx` now says "Changes created from the
  valid-from date on are priced with it; changes created before keep their
  rates", which is what the Finance chapter says. Re-read it after the cost
  sheet work lands.
- The PDF letterhead defaults (KTX Group US Corp., Toccoa) come from
  `backend/app/services/company_profile.py` and can be overridden by
  `KTX_COMPANY_*` environment variables. If production overrides them, the
  Sales chapter's sentence about the letterhead changes.

## 5. Placeholders still to fill

No TBD or TODO is left in the content (the test checks it). Values that are
open by nature:

| Where | Placeholder | Filled by |
|---|---|---|
| `docs/training/rollout-announcement.md` | `[go-live date]`, `[session dates]`, `[access contact]`, recipient list | Project Management and the PLM2 administrator, before sending |
| `docs/training/roster-template.md` | the blank tables | the trainer, per session |
| New fixture people and changes (J. Planner, CR-TRAIN-0003 to 0017, Toolmaker A and B) | names in the task briefs | whoever builds the sandbox fixtures; rename freely, keep briefs and fixtures in step |

## 6. Open questions

1. **Scheduling, Quality and Finance sample tasks answer checklist rows**
   (`sch_answer_checklist_row`, `qa_answer_checklist_row`,
   `fin_answer_checklist_row` in `tasks.ts`), but on a part change those
   departments are not routed (CHANGE_MANAGEMENT_FLOW.md, "Physical-part
   changes route exactly five departments"). The content replaces the
   Scheduling and Finance ones with role-true tasks and keeps a Quality one
   framed as "when the scoping meeting routes Quality". Until the
   replacements run in the sandbox the old tasks stay active and the new ones
   are listed as coming (section 3). Agree?
2. **Internal changes can be started since 2026-10-01** ("Internal change"
   on the start form, F-04). The manual still teaches the customer path only
   and does not cover "Approve internal costs" (PM, with the release
   deadline). Add that section; the practice sandbox keeps to customer changes.
3. **Recording attendance as a practice task** was drafted and dropped:
   `/v1/training/*` passes through the sandbox containment
   (`sandbox/containment.ts`), so an attendance recorded in practice would
   reach the live record. Keep it as a live, supervised step instead?
4. **Progress report cadence.** The backend expects a report about every 84
   hours; the UI only shows "report due". The copy avoids "twice a week".
   Say it in the manual?
5. **Two handouts.** Answered 2026-09-26: the printable handout page prints
   the one-pager (from `handouts.ts`, the same text as
   `docs/training/handouts/`), and appends the full chapters on request
   ("With the full chapters").
6. **Release rows next to APQP.** Answered 2026-09-26, see section 7.

## 7. Answered (decisions of 2026-09-25)

The app and the content follow these; the chapters and handouts say them.

- **Finance and Quality do not see prices: intended.** The price viewer
  stays admin, lead, Sales and any Project Management member. The Finance
  chapter ("you own the rates, not the offers") and the Quality chapter
  ("your sign-off is on the process record, not the price") state it as
  the rule. (Was question 2.)
- **Release checklist rows reworked (decision 2026-09-26, corrected the
  same day; replaces the 2026-09-25 Quality / Process Engineer rows; was
  questions 4, 5 and 6).** APQP confirms "Process stable: SPC Cm > 1.67"
  alone (`process_stable_apqp`, Cm optional, above 1.67) and owns "Surface
  quality confirmed", "Technical quality confirmed", "Measurements
  confirmed, measurement report on file", "PPAP / initial sample
  documentation complete, customer approval received (ISIR / PSW)" (PPAP
  asked once) and "Control plan / inspection plan updated". The Tool
  Engineer answers "Cycle time: changed (new value entered) or confirmed
  unchanged" (`cycle_time_tool`, merged from the Manufacturing Engineer's
  "Cycle time confirmed in series production"), next to its tool data and
  part weight rows, and alone measures the cycle time in validation. The
  Process Engineer confirms the process in the process database (PDB) and
  owns no release row. Quality owns no release row; its escalation
  audience is unchanged. Retired rows (`process_parameters`,
  `process_fmea`, `quality_samples`, `quality_control_plan`,
  `documents_updated`, `cycle_time_confirmed`, and the first version's
  `cycle_time` and `process_stable_pe` of the Process Engineer) keep their
  answers readable ("No longer asked"), as do cycle times Manufacturing or
  Process Engineer measured in validation. The new rows reach every change
  not yet finished; a change that ended (released, rejected or cancelled)
  before the cutoff (`PLM_RELEASE_ROWS_SINCE`) keeps its old checklist and
  wording. The Process Engineer still assesses only when the scoping
  meeting gives it a letter.
- **Future, not built:** process engineering tasks will later be forwarded
  from the PDB to PLM.
- **Project Management starts mother-plant changes.** Only PM members (and
  admins) hold `can_start_mother_plant`; Sales and the other starters no
  longer do. The start form shows everybody else "Changes from KTX
  Weissenburg / Solingen are started by Project Management (PM)." (Was
  question 9.)
- **Sales signs the offer.** The PDF's signature is the Sales person who
  sent the version, frozen with it; a draft shows the project's Sales
  responsible, else the Sales viewer, else the "Sales" line alone.
  `KTX_COMPANY_SIGNATURE_NAME` is no longer needed (an optional override).

## 7b. Folded in on 2026-09-26

The chapters and handouts now also say (checked against the code that day):

- Release checklist: 16 rows (Development 3, Tool Engineer 3, APQP 6,
  Packaging Engineer 1, Scheduling 2, Sales 1); Quality, Process Engineer
  and Manufacturing Engineer own no row.
- Offer PDF: dates read like "26 Sep 2026" for every customer; Sales signs
  (the sender, frozen; a PM lead or admin sending: the project's Sales
  responsible, else the "Sales" line); a draft shows "Signed by (preview)".
- KTX Weissenburg / Solingen: only PM starts them; PM writes the
  description; scoping records the departments to inform (no assessment, no
  cost carrier), then "Send information to the team"; approval waits for it.
- RASIC "I": "Informed (notified only)", a notification and no task.
- Routing changes after scoping: an add or a removal is a routing deviation
  with four eyes; a removal waits for approval, the department stays on the
  hook and the change cannot move to costing until it is decided.
- Plan deviations: the moved block and the blocks it pushed are one group,
  one decision ("Lock all {n}" or "Escalate to customer"), by PM, Sales, the
  lead or an admin.
- Cost sheet: kept by Sales, Finance and admins may edit; one rate per
  department per plant ("Rates"); a change is priced with the rates valid on
  the day it was created; machines synced from MachineDB with an optional
  rate per press; Silao quotes in USD and pays in MXN, converted with the
  version's exchange rate.

## 8. Rollout: parked

The training is documentation only for now. The rollout announcement
(`docs/training/rollout-announcement.md`) and the roster
(`docs/training/roster-template.md`) are parked: nothing is sent and no
session is scheduled until the owner says go. Their placeholders (section 5)
stay open until then.
