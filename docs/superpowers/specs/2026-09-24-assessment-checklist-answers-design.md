# Assessment checklist: every row answered, risk flagged in place

Date: 2026-09-24 · Branch: `integrate/dfm-redesign`

## Problem

The assessment checklist ("Betroffene Bereiche", `assessment_checklist.py`) is a
list of checkboxes that are off by default. An unticked box means either "checked,
not impacted" or "never looked at", and nobody can tell which. The risk flag
(`ChangeConcern kind='risk'`) is liked, but it lives in a separate strip above
the form, so thinking through the list and flagging a risk are two unrelated acts.

Goal: the checklist becomes a guide that makes each department think through every
row, and that turns a worry into a flagged risk on the spot.

## Decisions

1. **Two answers per row: No / Yes.** No third "unsure" state. If a department is
   unsure, that is a risk, and it gets flagged.
2. **Nothing is pre-selected, and there is no "all No" shortcut.** A bulk No
   brings back the blind spot this feature removes.
3. **Every row must be answered before submit.** Frontend and backend enforce the
   same rule.
4. **Impact and risk stay separate.** Yes means "impacted": it seeds costing
   exactly as a tick does today. A risk is flagged on purpose via a ⚑ button on
   the row, because many impacts only cost money and are not a risk.
5. **Exemption stays.** A department questionnaire that answers "not impacted"
   (`details.impacted === false`, e.g. Packaging) still skips the checklist
   completely.

## Behaviour

### Checklist row (`ActivityChecklist.tsx`)
- A segmented control `No | Yes` replaces the checkbox. Unanswered rows show both
  options unselected, with the label in the normal colour.
- **Yes** reveals what a tick reveals today: the choice radios (if any), the
  remark and the RFQ slot for `modification_external`.
- **No** collapses the row. A remark is optional and not shown by default.
- Free lines a department adds are answered Yes. You only add a line because
  something is impacted.
- **⚑ Flag risk** is shown on every answered row (Yes or No). A department can
  answer "No, not impacted" and still see a risk, e.g. "no 3D change, but the
  tolerance stack is tight". Clicking it opens the risk form inline under the
  row, pre-filled:
  - department = this bucket's department
  - note = row label, plus " — " + remark if one exists
  - risk type and severity are left for the user (a deliberate choice, same as today)
  - `checklist_key` = row key (free lines: `free:<label>`)
- Once a risk is raised from a row, the row shows `⚑ risk flagged (sev N)` and
  the button is replaced. The risk also appears in the department's ConcernStrip
  as usual. Withdrawing it there brings the button back.

### Progress and submit gate (`AssessmentSubmitForm.tsx`)
- A progress line above the list: `11 of 14 answered`. It turns green at 14/14.
- Submit is disabled while any row is unanswered. The button's helper text says
  `3 rows unanswered` and clicking that text scrolls to and highlights the first
  unanswered row.
- The backend enforces the same rule (below); a refusal is shown in place like
  other submit errors.

### Bucket summary (`AssessmentBuckets.tsx`)
- The existing "{n} areas impacted" becomes `n impacted · k risks flagged`, where
  k counts open risks of that department with a `checklist_key`.
- The submitted-answer list shows Yes rows as today. Rows answered No are listed
  collapsed ("12 × No") so a reviewer can see they were answered, not skipped.

## Data

### `details.impacts` entry (JSON in `ChangeAssessment.details`)
```
{ key | label, answer: "yes" | "no", impacted: bool, remark?, choice? }
```
- `answer` is new. `impacted` is kept equal to `answer == "yes"` so
  `CostService.seed_from_checklist`, `impactedCount`, the RFQ expectation and the
  cost-task skip rule keep working unchanged.
- The frontend no longer drops "untouched" rows. No answers are stored, since
  they are the evidence the row was considered.
- Legacy rows (no `answer`) are read as `answer = impacted ? "yes" : <unanswered>`.
  Assessments submitted before this change are never re-validated.

### `change_concerns.checklist_key` (migration 085)
- `VARCHAR(120) NULL`, no FK: checklist keys live in code.
- Set only when a risk is raised from a checklist row. `POST /changes/{id}/concerns`
  accepts optional `checklist_key`, allowed only for `kind='risk'`. It is
  validated against `checklist.keys_for(department)`, or the `free:` prefix.
- Returned on the concern schema, so the row can find its flag.

## Backend rules (`ChangeService._validate_impacts`, called from `submit_assessment`)
- When the submit carries `details.impacts`, every key in
  `checklist.keys_for(dept_name)` must appear exactly once with `answer` in
  `{"yes","no"}`. Otherwise the submit is refused with
  `ChangeError("Checklist incomplete — unanswered: <labels>")`.
- `answer` and `impacted` must agree; the server normalises `impacted` from
  `answer` rather than trusting both.
- A submit whose `details.impacted is False` (questionnaire "not impacted") is
  exempt, matching the frontend.
- A submit without `details` (API callers, older tests) keeps its current
  behaviour. The gate lives where the checklist is sent, and the app always
  sends it.

## Testing
- Backend: incomplete checklist refused, with its labels named; complete one
  accepted; `impacted` normalised from `answer`; "not impacted" questionnaire
  exempt; a submit without `details` unchanged; `checklist_key` accepted for risk, refused for other kinds and for
  unknown keys; migration up/down.
- Frontend: No/Yes control writes `answer`+`impacted`; No rows kept in details;
  progress counter; submit disabled until complete and jump-to-first-unanswered;
  ⚑ opens a pre-filled form and posts `checklist_key`; row shows "risk flagged"
  from an open concern; bucket summary counts.

## Out of scope (open points)
- **Per-department prompt lists editable in the app.** Today each department
  gets the 13 common rows plus a few extras from code. Each department should get
  its own 8–12 question-style prompts, e.g. Tool Engineer: "Steel safe or needs
  welding?", "Cooling affected?"; Packaging: "Dunnage still fits?"; Quality:
  "PPAP level change?". This would likely move the list from
  `assessment_checklist.py` into a table next to `department_risk_types`.
- **Prompts that adapt to the change.** Show only rows relevant to what the impact
  tree touches (resin change → material/drying prompts; dunnage-only change →
  no tooling prompts).
- **Memory from earlier changes.** On a row, show risks flagged from the same
  prompt on earlier changes to the same part or tool ("flagged on CR-2026-0002:
  cooling line clash").
- **Mapping a checklist row to a default risk type** so ⚑ can pre-select the type
  too. Needs the per-department lists first.
