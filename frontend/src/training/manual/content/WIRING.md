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
`docs/training/rollout-announcement.md`, `docs/training/roster-template.md`.

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
that screen makes (a miss throws, by design). New fixture changes:
CR-TRAIN-0003 (approved, detailed plan, downtime and bank build idea),
CR-TRAIN-0004 (in validation, baseline, deviations, VI-1 and VI-2, release
checks), CR-TRAIN-0005 (scoping, impact confirmed), CR-TRAIN-0006 (costing
then quoting, one severity-3 risk), CR-TRAIN-0007 (quoted, v1 sent, later v2
accepted).

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
| "{n} of {m} confirmed", "{n} × No ({b} set via Rest → No)" | `TeamFeedbackPanel.tsx`, `AssessmentBuckets.tsx` | Templates |
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
| New fixture people and changes (J. Planner, CR-TRAIN-0003 to 0007, Toolmaker A and B) | names in the task briefs | whoever builds the sandbox fixtures; rename freely, keep briefs and fixtures in step |

## 6. Open questions

1. **Scheduling, Quality and Finance sample tasks answer checklist rows**
   (`sch_answer_checklist_row`, `qa_answer_checklist_row`,
   `fin_answer_checklist_row` in `tasks.ts`), but on a part change those
   departments are not routed (CHANGE_MANAGEMENT_FLOW.md, "Physical-part
   changes route exactly five departments"). This draft replaces the
   Scheduling and Finance ones with role-true tasks and keeps a Quality one
   framed as "when the scoping meeting routes Quality". Agree?
2. **Finance cannot see prices on a change.** The price viewer is admin,
   lead, Sales and PM (`ChangeDetailPage.tsx` `canSeeCosts`,
   `validation_issue_service.cost_role`, `pnl.py` via
   `NegotiationService.may_read`). Finance owns the rates but cannot read an
   offer or a change's P&L. Intended? The Finance chapter states the rule as
   it is.
3. **Internal changes cannot be started** ("Internal change" is disabled on
   the start form: "Internal changes come later"). The manual teaches the
   customer path only and does not cover "Approve internal costs". Add a
   section when internal changes open.
4. **Quality in validation.** Quality owns no release checklist row, is not
   in the escalation audience (L1 owner and PM, L2 PM, lead, Sales, L3
   management) and can raise an issue only when routed. The chapter gives
   Quality a watching role. Should Quality be notified at L2 or own a
   checklist row?
5. **Process Engineer** owns no release checklist row and is not in the
   default part-change routing. The engineering chapter says it assesses when
   given a letter. Confirm that is the intended role.
6. **Recording attendance as a practice task** was drafted and dropped:
   `/v1/training/*` passes through the sandbox containment
   (`sandbox/containment.ts`), so an attendance recorded in practice would
   reach the live record. Keep it as a live, supervised step instead?
7. **Progress report cadence.** The backend expects a report about every 84
   hours; the UI only shows "report due". The copy avoids "twice a week".
   Say it in the manual?
8. **Two handouts.** The in-app "Printable handout" prints the full chapters
   for a role. The files in `docs/training/handouts/` are one-page cheat
   sheets. Keep both, or add the one-pager as a "Quick reference" section of
   each role chapter?
9. **Who may start a mother-plant change.** The option shows only with
   `can_start_mother_plant`; the manual says Sales or PM starts changes.
   Confirm who holds that permission.
