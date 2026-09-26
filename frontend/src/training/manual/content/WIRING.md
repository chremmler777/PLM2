# ECR training content: how to wire it in

Draft of 2026-09-25. Nothing in the app imports this directory yet. The
content was written before the UI polish; screenshots and a final label check
come after it. This file says how to plug it in, what is still open, and
which labels must be re-checked.

## What is here

| File | Holds |
|---|---|
| `types.ts` | The data shapes: `Block`, `ContentSection`, `ContentChapter`, `PracticeTaskSpec`, `ScreenSpec`, `ShotSlot` |
| `shared.ts` | Chapter 01 (basics) and 02 (flow, with the three side tracks) |
| `projectManagement.ts`, `sales.ts`, `engineering.ts`, `scheduling.ts`, `quality.ts`, `finance.ts` | Chapters 03 to 08, each with its practice task specs |
| `index.ts` | `CONTENT_CHAPTERS`, `PRACTICE_TASKS_BY_ROLE`, `PRACTICE_TASKS`, `SHOT_SLOTS`, `contentFor(id)` |
| `render.tsx` | `renderBlocks(blocks, available?)`: blocks onto `../kit.tsx`; a shot renders as a placeholder until its file exists |
| `content.test.ts` | House rules: no dashes or placeholder words, unique ids and shots, 2 to 4 tasks per role, every stub in `../chapters.tsx` written |

Outside the code: `docs/training/handouts/*.md` (one page per role),
`docs/training/rollout-announcement.md`, `docs/training/roster-template.md` (both parked, see section 8).

Run the test: from `frontend/`,
`npx vitest run src/training/manual/content/content.test.ts --maxWorkers=2 --minWorkers=1`
(`--minWorkers=1` is needed: `--maxWorkers=2` alone collides with the default
minimum thread count on a many-core machine).

## 1. Plugging the chapters in

Chapter ids, numbers and roles are the same as in `../chapters.tsx`, and every
stub section id there has a written section here (the test checks it). Chapter
09 (`record`) is already written in `../chapters.tsx` and is not repeated.

In `../chapters.tsx`, replace each chapter's `sections` with the content's:

```tsx
import { contentFor } from './content'
import { renderBlocks } from './content/render'

/** Shot stems that have a file in public/manual/. Grows as screenshots land. */
const SHOTS_AVAILABLE = new Set<string>([])

function sectionsOf(chapterId: string): ManualSection[] {
  const c = contentFor(chapterId)
  if (!c) return []
  return c.sections.map((s) => ({
    id: s.id,
    title: s.title,
    body: renderBlocks(s.blocks, SHOTS_AVAILABLE),
  }))
}

// in CHAPTERS, e.g.:
{ id: 'pm', number: '03', title: 'Project Management', summary: ..., roles: ['project_management'],
  sections: sectionsOf('pm') },
```

Take `title` and `summary` from the content too (`contentFor(id)!.title`) if
the wording here is preferred; some summaries were sharpened.

The content adds sections the stubs did not have (for example `pm-role`,
`pm-issues`, `sales-versions`, `eng-validation`, `eng-development`,
`fin-review`, `flow-issues`, `flow-mother-plant`, `flow-intake`). Their ids are
prefixed like the rest, so the Manual tab's anchors keep working.

Then bump `code_version` for every role in `backend/app/services/training.py`
(the material changed) and publish from "Training", "Records", "Publish a new
version" when the plant is ready.

## 2. Screenshots

47 slots, listed in manual order by `SHOT_SLOTS` (each with chapter, section,
what the picture must show in `alt`). After the polish:

1. Take each shot on a seeded demo change, save it as
   `frontend/public/manual/<shot>.png` (the stem is the slot name).
2. Add the stem to `SHOTS_AVAILABLE`. The placeholder becomes a `Figure`.

Slots: basics-sidebar, basics-project-team, basics-backup-row, basics-my-tasks,
basics-cockpit, flow-stepper, flow-gantt-baseline, flow-issue-card,
pm-next-step-capture, pm-status-card, pm-impact-tree, pm-scoping-meeting,
pm-cost-summary, pm-signoff, pm-validate-timing, pm-deviations,
pm-route-dialog, sales-start-form, sales-question-card, sales-offer-price,
sales-offer-pdf, sales-offer-versions, sales-customer-response,
sales-issue-decision, eng-bucket, eng-checklist, eng-risk-on-row,
eng-cost-positions, eng-team-confirmation, eng-tracker, eng-failed-check,
eng-release-checklist, eng-intake-route, sch-assessment-checklist,
sch-bank-build-card, sch-bank-build-idea, sch-team-confirmation,
sch-deviation-dialog, sch-release-checklist, qa-signoff, qa-audit-tab,
qa-lessons, qa-records-tab, fin-cost-sheet, fin-publish-dialog,
fin-no-rate-line, fin-review-banner.

## 3. Plugging the practice tasks in

Each `PracticeTaskSpec` carries the fields of `TrainingTask` in
`../../tasks.ts` (`key`, `title`, `brief`, `why`, `screen`) plus `fixture`
(what the sandbox must hold) and `pass` (one assertion per line on the
outcome, with the hint shown on a fail). A check function is written from
`pass` in order: the first failing assertion returns its hint.

| Role | Task keys (order) | Status |
|---|---|---|
| project_management | `pm_set_priority`, `pm_scoping_proceed`, `pm_decide_deviation`, `pm_route_issue` | 1 ready (exists), 3 need sandbox |
| sales | `sales_start_change`, `sales_send_offer`, `sales_new_version`, `sales_issue_customer_decision` | 1 ready (exists), 3 need sandbox |
| engineering | `eng_answer_checklist_row`, `eng_submit_assessment`, `eng_costing_vendor_quotes`, `eng_contain_issue` | 2 ready (exist), 2 need sandbox |
| scheduling | `sch_bank_build_plan`, `sch_resolve_bank_idea`, `sch_timing_concern`, `sch_release_stock` | 4 need sandbox; replaces `sch_answer_checklist_row` |
| quality | `qa_quality_signoff`, `qa_flag_row_risk`, `qa_add_lesson` | `qa_flag_row_risk` ready (replaces `qa_answer_checklist_row`, same screen, concerns handler exists), 2 need sandbox |
| finance | `fin_publish_rate`, `fin_add_missing_rate`, `fin_confirm_currency` | 3 need sandbox; replaces `fin_answer_checklist_row` |

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
- `components/costSheet/PublishDialog.tsx` makes the same wrong backdating
  claim the first draft of the Finance chapter made: "Costing lines and
  bookings dated since then will be priced with this version." Lines already
  priced keep their snapshot (`costing_rates.snapshot_position`,
  `stored_price`); only time booked since then and lines without a rate take
  the new version. The chapter now says so. The dialog text is fixed in the UI
  polish, not here.
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
   changes route exactly five departments"). This draft replaces the
   Scheduling and Finance ones with role-true tasks and keeps a Quality one
   framed as "when the scoping meeting routes Quality". Agree?
2. **Internal changes cannot be started** ("Internal change" is disabled on
   the start form: "Internal changes come later"). The manual teaches the
   customer path only and does not cover "Approve internal costs". Add a
   section when internal changes open.
3. **Recording attendance as a practice task** was drafted and dropped:
   `/v1/training/*` passes through the sandbox containment
   (`sandbox/containment.ts`), so an attendance recorded in practice would
   reach the live record. Keep it as a live, supervised step instead?
4. **Progress report cadence.** The backend expects a report about every 84
   hours; the UI only shows "report due". The copy avoids "twice a week".
   Say it in the manual?
5. **Two handouts.** The in-app "Printable handout" prints the full chapters
   for a role. The files in `docs/training/handouts/` are one-page cheat
   sheets. Keep both, or add the one-pager as a "Quick reference" section of
   each role chapter?
6. **Release rows next to APQP.** Answered 2026-09-26, see section 7.

## 7. Answered (decisions of 2026-09-25)

The app and the content follow these; the chapters and handouts say them.

- **Finance and Quality do not see prices: intended.** The price viewer
  stays admin, lead, Sales and any Project Management member. The Finance
  chapter ("you own the rates, not the offers") and the Quality chapter
  ("your sign-off is on the process record, not the price") state it as
  the rule. (Was question 2.)
- **Release checklist rows reworked (decision 2026-09-26, replaces the
  2026-09-25 Quality / Process Engineer rows; was questions 4, 5 and 6).**
  The Process Engineer confirms the process in the process database (PDB)
  and owes the release two rows: "Cycle time: changed (new value entered)
  or confirmed unchanged" (`cycle_time`, merged from the Manufacturing
  Engineer's "Cycle time confirmed in series production") and "Process
  stable: SPC Cm > 1.67 (Process Engineer)". APQP owns "Process stable:
  SPC Cm > 1.67 (APQP)" (the stability counts only when both halves are
  done), "Surface quality confirmed", "Technical quality confirmed",
  "Measurements confirmed, measurement report on file", "PPAP / initial
  sample documentation complete, customer approval received (ISIR / PSW)"
  (PPAP asked once) and "Control plan / inspection plan updated". Quality
  owns no release row; its escalation audience is unchanged. Retired rows
  (`process_parameters`, `process_fmea`, `quality_samples`,
  `quality_control_plan`, `documents_updated`, `cycle_time_confirmed`)
  keep their answers readable ("No longer asked"). The new rows reach every
  change not yet finished; a change released before the cutoff
  (`PLM_RELEASE_ROWS_SINCE`), or ended without a release, keeps its old
  checklist. The Process Engineer still assesses only when the scoping
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

## 8. Rollout: parked

The training is documentation only for now. The rollout announcement
(`docs/training/rollout-announcement.md`) and the roster
(`docs/training/roster-template.md`) are parked: nothing is sent and no
session is scheduled until the owner says go. Their placeholders (section 5)
stay open until then.
