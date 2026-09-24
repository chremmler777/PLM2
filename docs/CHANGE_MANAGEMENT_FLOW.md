# Change Management — process flow (living document)

**Purpose.** One place holding what the change process actually *is*, so the
formal process flow + description can be written from it, and so an auditor can
be shown how each rule is enforced rather than asserted. Updated as decisions
land; every rule here names the code that enforces it.

**Status:** in progress. Sections marked ⚠ are open questions, not decisions.

---

## 1. Where the flow came from

Two different origins, worth keeping straight:

| Part | Origin |
|---|---|
| Assessment routing, D1 approval matrix, per-department modules | `Documents/Changemanagement/ÄnderungsmitteilungChange_Management*.xlsx` — the real workbook |
| The `captured → scoping → in_assessment → …` state machine | Our design, `docs/superpowers/specs/2026-07-04-change-flow-path-to-quote-design.md` |

The original core design (2026-06-15) went `captured → in_assessment` directly.
`scoping` was introduced on 2026-07-04. **No customer-supplied process flow
defines these stages** — we are free to reshape them.

### The workbook's own structure (to reconcile against)

Tabs: `Änderungsinformation_D1` (master), then one per department —
`Vertrieb (Sales)_D2`, `Entwicklung (R&D)_D3`, `Wkzg. Entw. (tool design)_D4`,
`IE_D5`, `Qualität (QVP)_D6`, `Logistik_D7` (+`_D7_2`), `Produktion_D8`,
`Einkauf (purchasing)_D9`, `Fertigungsst. (production c)_D10` — plus
`Summierung`, `Std.-Sätze+Fzg`, `Änderungshistorie`, `Bauteilauswahl`.

⚠ **To review:** the workbook is the template the business already fills in.
Each D-tab should map 1:1 onto a department assessment module, `Summierung`
onto the cost summation, `Änderungshistorie` onto the audit trail, and
`Bauteilauswahl` onto the impacted-item picker. That mapping has not been
checked field-by-field. Do this before writing the formal description.

---

## 2. Stages

| Stage | What happens | Who |
|---|---|---|
| `captured` | Originator enters the request: project, description, documents, one-line reason, cost carrier, required-by date. **No meetings here** | Sales; **Project Management may act alternatively** (both departments carry `can_start_change`; the flag, not a hardcoded role, is what the API enforces) |
| `scoping` | Team decides: proceed / needs info / reject. Impacted set worked out and locked (first PM action), documents gathered. Description is frozen (Sales' capture text); discussion happens by email, thread attached | PM convenes; decision recorded by any member |
| `in_assessment` | Routed departments answer feasibility + cost per the D1 matrix | Departments (RASIC) |
| `costing` | Costs summed | — |
| `quoted` | Offer to customer (customer-carried changes only) | Sales |
| `approved` | Go decision | PM + Quality sign-off, or internal cost approval |
| `in_implementation` | ECN revisions spawned, work done | — |
| `in_validation` | Results checked | — |
| `released` → `closed` | Change is live, then wrapped up | — |

Off-path: `on_hold`, `rejected` (reversible), `cancelled` (terminal).

### Sanity checks per stage

Run these when discussing any stage's implementation:

1. **Can it be entered by accident?** Every entry should require the thing the
   stage is *for* to already exist.
2. **Does leaving it require a named person?** If not, the audit trail records a
   state change with nobody behind it.
3. **Is the negative path as well-served as the happy path?** Reject and
   needs-info deserve the same care as proceed.
4. **What does it cost to undo?** If irreversible, say so in the UI *before* the
   click, not after.
5. **Does the workbook have a tab for this?** If yes, the fields should line up.

---

## 3. Gates and rules, with enforcement

### Entering `scoping`
- **Soft:** the capture must be complete — a `description`, **at least one
  attachment**, and (customer-relevant changes only) the **required-by date**.
  Missing pieces are listed in the message: *"Incomplete capture — missing
  description, at least one attachment before scoping"*. Overridable by
  approved deviation. `change_service.py::_guard`.
  Rationale: Sales captures, the project team scopes — kickoff means handing
  over a request someone can actually work on. The impacted set is **no longer**
  required here: it is defined during scoping (first PM action there) and stays
  hard-locked before assessment, as before.

### Inside `scoping`
- The onward move is **the meeting's call, not a button**. The cockpit offers no
  advance button at `scoping`; it points at the scoping tab.
  `changeStatus.ts::DECIDED_BY_MEETING`.
- **Concerns** — any team member may flag `reject_proposal` (cancel vote) or
  `needs_info` (question) with a note; naming a department is attribution only.
  Risks are **not** raisable here — the register belongs to assessment. Settling
  ("mark solved") belongs to the author or a Project Manager member — attribution
  hands the named department (Sales, typically) nothing, admins are *not* exempt,
  and the acts-as switch sets personal authorship aside. One open concern per
  person per kind. `meeting_service.py::raise_concern` / `withdraw_concern`; see
  `superpowers/specs/2026-08-12-scoping-concerns-and-settle-rights-design.md`.
- **Open concerns block `proceed`** — the decision must either be answered by
  the author withdrawing, or by a negative decision that consumes it.
- Meeting decision `reject` requires a reason; `needs_info` requires stating
  what is missing. `proceed` needs no justification.
- A negative decision **resolves** the open concerns and its reason becomes the
  change's `rejection_reason` — one decision, one justification.
- `needs_info` keeps the change in `scoping` and raises a **Sales-accountable
  action** ("obtain missing information"). Sales owns the customer relationship.
- After a negative decision, an **attachment slot** appears for Sales/PM to file
  what they send the customer — rejection letter, open questions, or a
  counter-proposal.

### The needs-info loop (2026-08-11)

A `needs_info` decision opens a tracked request/response cycle instead of a
note nobody owns:

1. The decision **auto-raises a Team flag** (`needs_info` concern, author =
   the decider) carrying the decision reason. Net effect per follow-up round:
   the prior flag is resolved by the decision, a fresh one is raised — the
   change always visibly owes exactly one answer
   (`meeting_service.py::decide_meeting`).
2. **Sales gets the task** — my-tasks kind `obtain_info` with the reason, for
   Sales members, while `ChangeService.pending_info_request` holds.
3. **Documents are classified**: attachments carry `kind`
   (`general | info_request | info_response`) and a response links to its
   request (`responds_to_id`, migration 046). The needs-info slot uploads as
   `info_request`; the UI pairs responses under their requests.
4. **Answer vs. closure are two acts** (2026-08-12): Sales *answers* the
   question (`answer_concern` — a comment; the flag stays open, and the
   `close_question` task goes to the asker and PM). **Closure** is the asker's
   or a PM member's call — whoever asked the question judges the answer;
   Sales never marks solved. Question cards name the asker with their
   department role(s), not just the username. All steps audited.

### The two deadlines (2026-08-11)

One quote-by, one release-by; at any moment at most one is *active*
(`ChangeRequest.active_deadline`, `ChangeService.deadline_state`).

- **Quote deadline** (`required_by_*`) — customer-relevant changes only. Set by
  Sales at capture (part of the kickoff gate). Active until the change is
  quoted; `quoted_at` freezes a permanent quoted-on-time/late fact
  (`quoted_on_time`). Internal changes never have one.
- **Locked after capture, moved only by pushback.** From `scoping` on, changing
  the quote date requires a reason in the same PATCH; audited as
  `quote_deadline_pushback` (`change_service.py::update`, UI: cockpit "Push
  back"). The date has **one owner** (lead/Sales/PM); discovery has many
  mouths — a meeting outcome, or a department flagging timing in its
  assessment answer, feeds the owner, who records the pushback.
- **Release deadline** (`release_due_*`) — born mandatorily at the moment of
  commitment: customer acceptance (Sales) or internal cost approval (PM); the
  API refuses the acceptance/approval without it. Editable afterwards via
  audited PATCH (`release_deadline_set`), never clearable. Drives
  `deadline_state` from then on; escalations and the workload report follow
  whichever deadline is active.

### Inside `in_assessment` — the risk register (reworked 2026-08-11)

Risks at assessment are a **register, not a hold** — and assessment is the only
phase that hand-raises them (a scoping raise of kind `risk` is refused, and
assessment refuses the scoping kinds; 2026-08-12). A department records a
risk with a **standard type** — fill issue, dimensional issue, visual/surface,
process capability, other (free text) — a **severity rating 1–3** (3 =
highest) and a note, then submits its verdict regardless. No mitigation
proposal loop, no submit block: the pass decision is the
feasible / with-conditions / not-feasible verdict, and the register is what
travels.

- **Severity-3 risks surface to Sales on the commercial view** — they belong
  on the offer as technical judgment. Sales owns carrying them to the
  customer; the assessing department owns raising them.
- **"Reject" is not a raiseable option.** A department that cannot do it sets
  verdict `not_feasible` (which hard-requires the Change PPT, below).
- **"Needs info" is not a department concern anymore** — by assessment time
  it is too late, and everyone communicates with the customer directly. The
  mail lands in the change-level customer-mail log (below). The
  scoping-*meeting* decision `needs_info` (a meeting outcome) stays.
- Legacy concerns (`reject_proposal` / `needs_info`) on old changes stay
  readable and closable with their old rules; only raising them is gone.

### Assessment documents & customer communication (2026-08-11)

Three typed containers, three responsibilities:

| Artifact | Container | Responsible | Rule |
|---|---|---|---|
| **Change PPT** (internal explanation of the change) | per assessing department's bucket (`kind=change_ppt`) | assessing department | required for a `not_feasible` verdict (replaces the generic evidence gate) |
| **RFQ** (external — supplier pricing & timing) | per assessing department's bucket (`kind=rfq`) | assessing department | expected when "external modification" is ticked; reported, not gated |
| **Customer mails** (.msg/.eml/pdf) | change level (`kind=customer_email`) | everyone uploads, Sales owns the customer relationship | chronological tracked list, visible to all — the customer-communication record of the change |

### Assessment shape (2026-08-11, in build)

- **Process owners see their task, not the board (2026-08-11).** An ordinary
  member's assessment tab is their own department's bucket, auto-expanded,
  plus one slim progress line ("4/6 submitted — waiting on …"). The full
  per-department board belongs to PM, Sales, the change lead and admins.
  Who is still owed ("Assessment: waiting on Development, APQP (4/6)") is a
  ⏳ row in the cockpit's **Blocked by** card for every viewer (2026-09-24:
  the separate wait banner above the cockpit is gone; `resolveWaitStates`
  feeds `CockpitSummary`'s `waits` prop).
- **A bucket binds to the row that matters now**: the active one, else the
  latest answer, else the earliest dormant one — a submitted verdict never
  disappears behind a not-yet-started later stage, which shows as "Later
  stage" (queued), not as unclaimed work.
- **Buckets auto-populate with the department's domain objects**, derived
  from the impacted parts via the serves links: Tool Engineer → tools/molds,
  Manufacturing Engineer → equipment, APQP → gauges + documents,
  Development → the part design itself.
- **Physical-part changes route exactly five departments**: Development,
  Tool Engineer, Manufacturing Engineer, APQP, Packaging Engineer. Packaging's
  bucket opens with "packaging impacted?" — if yes: layout change / packaging
  type / modification; "not impacted" is a complete assessment. Sales, PM,
  Scheduling and Quality carry no assessment tasks for physical part changes.
- **No cost fields at assessment.** Cost (the workbook's per-department
  activity grids — hours × rates per plant, one-time vs lifecycle) belongs to
  `costing`.
- **The impact checklist (2026-08-11, replaces the workbook activity lists as
  assessment questions).** Config, not data
  (`GET /changes/reference/assessment-checklist`). **13 common items**: cycle
  time change, increased scrap, increased maintenance, 3D change necessary,
  dimensional risk, visual risk, work instruction update, new process, spare
  part required, internal modification, external modification, prototyping,
  matching/sampling. **Extras**: APQP → PFMEA update, control plan update;
  Development → article design update (internal vs customer-given). External
  modification expects an **RFQ document** (costs & timing request to the
  supplier; reported, not gated). **`not_feasible` hard-requires the Change
  PPT** in the department's bucket (see the document table above).
  Checked items seed the department's costing grid (cycle time → lifecycle
  line, rest one-time; remark travels as the line note; deliberate deletions
  are remembered).
- **Every checklist row is answered (2026-09-24,
  spec `docs/superpowers/specs/2026-09-24-assessment-checklist-answers-design.md`).**
  Each `details.impacts` entry carries `answer: "yes" | "no"`; `impacted`
  is derived from it server-side (`answer == "yes"`), so costing, the RFQ
  hint and the cost-task skip read what they always read. No rows are
  stored. `_validate_impacts` refuses a submit whose checklist is
  incomplete and names the unanswered rows. Exempt: a
  questionnaire "not impacted" (`details.impacted is False`), a submit
  without `details.impacts` (API callers), and old submissions made only
  of legacy rows (activity id, or a bare line with no answer). The form
  holds the submit until the checklist has loaded and every row is
  answered. **Rest → No** fills only unanswered rows and marks them
  `bulk: true`; a row changed by hand drops the mark; the bucket shows
  "n × No (b set via Rest → No)".
- **Risks flagged from a row (2026-09-24).** `change_concerns.checklist_key`
  (migration 085; a checklist key or `free:<label>`, ≤120 chars, risks
  only, validated against the department's checklist) links a risk to the
  row it was raised from. The row lists its open risks compactly and jumps
  to the card; the card in the department's risk panel says "from: <row>"
  and is the only place for proposal / resolve / delete. The panel's own
  button is "+ Risk not on the checklist". Submitted answers name the Yes
  rows and mark those with open risks (⚑).
- **Delete a risk raised by mistake (2026-09-24).** `POST
  /changes/{id}/concerns/{cid}/retract`: its raiser only, open risks only,
  refused once a mitigation proposal (`answered_at`) or a document
  (`concern_id` attachment) exists. Sets `retracted_at/by` (migration 086);
  `is_open` is false, the concerns list omits it, the changelog records
  `concern_retracted`. Nothing is erased; the changelog is hash-chained.
  Resolving a risk ("Risk resolved") asks "How was it addressed?".

### Costing & timing shape (2026-08-11, in build; positions added 2026-08-12)

- **Per-department cost buckets at `costing`** — same accordion philosophy as
  assessment: each participating department files one-time lines (activity
  from its catalog or free label, per plant, hours × rate snapshot + external
  cost) and lifecycle lines as **production-time deltas** (± min/part, per
  plant). Departments see only their own figures; **PM and Sales see all**
  (summation: per-department, one-time vs lifecycle, grand total).
- **Cost positions (2026-08-12)** — each department states, as tagged
  positions (standard tags like moldflow, external design, tool change, gauge
  change, testing … or free text): its **internal effort** (time spent on the
  assessment), its **estimated support during implementation**, and
  **external positions** priced either as an estimate or by **vendor quotes**
  — one table row per vendor: uploaded quote document, cost, lead time,
  shipping stated separately or declared included in the offer. The
  department **votes a favorite vendor**; Sales chooses later. **Sales has no
  input at costing** — they receive the full picture and build the quote from
  it. A department whose assessment marked nothing impacted (e.g. Packaging's
  "no change") owes no costing input and carries no costing task.
- **Timing**: each department's costing entry carries an implementation
  lead-time estimate; the change-level roll-up is the max.
- **Scoping like assessment**: at costing a department sees **only its own
  block**; PM and Sales see all blocks.
- **`quoting` — the create-quote stage (2026-08-12)**: costing closes the
  quote inputs, then the change moves `costing → quoting → quoted`. The
  quoting stage is **Sales-only**: they see all costs wrapped up per
  department (lines, lifecycle, positions with the favorite vendor) and build
  the quote from it. The implementation-timeline builder (MS-Project-like,
  Sales decides what runs in parallel) is a **future tool** — the stage
  carries a placeholder statement for now.
- **Quote**: Sales sets the quoted price manually with the summation (incl.
  the lifecycle time roll-up) as the internal basis — departments give time,
  Sales prices (the D2 "recalculation" job).
- **Activity catalogs remapped to our roles**: Production → Process Engineer,
  Logistics → Packaging Engineer (packaging) + Scheduling (stock/flow),
  Production control → Scheduling, Purchasing → deactivated (out of ECR
  scope for now).
- **Bank build is explicitly post-acceptance**: sizing needs a tooling
  downtime start date and confirmed lead times, which exist only once the
  customer accepts (release deadline born there). Costing may carry an
  estimate line; the plan itself belongs to implementation planning.

### Entering `in_assessment`
- **Hard, unbypassable:** impacted set must be Development-locked.
  *"Impacted set is not locked — confirm impacted items before starting
  assessment"*. Not even an approved deviation clears it.
- **Soft:** ≥1 impacted item, lead assigned, deadline set, meeting with decision
  `proceed`.
- The **lead item pins here** — departments are routed against it. Editable in
  `captured`/`scoping` only.

### Who is on the hook: the room's RASIC call at scoping
Attendance at the scoping meeting makes nobody responsible, and absence takes
nothing away. The PM sets responsibility WITH the team, per department, on the
meeting record (`ChangeMeeting.department_rasic`, `{department_id: letter}`):
- **Letters:** R (Responsible, assesses), A (Accountable, assesses), S
  (Supports), C (Consulted/informed — no answer owed). "I" is accepted and
  stored as C. The picker starts from the change type's standard routing
  (every stage-1 department with its standard letter, served by
  `recommended-departments`); the room overrules it.
- **Routing follows the room:** on `proceed`, stage 1 is built from the map —
  the room's letter wins over the template's; a department the room added
  gets the letter it chose. Older meetings without letters keep the old rule
  (template letter, extras are R). Proceeding needs at least one R/A.
- **The department may still say no.** In assessment, a routed R/A department
  clicks "Not our responsibility" in its own bucket: reason required,
  optionally naming who should own it. That is the routing deviation
  `reletter → C` (plus `add` for the named department), decided by the change
  lead through the same 4-eyes panel. Rejecting restores the letter the routing
  gave; approving leaves the department consulted. Refused once the department
  has answered.
Every routing deviation now carries a reason (`apply_deviation`).

### The costing table (2026-09-16)
One table per department at `costing`, line by line. Rows 1–2 are standing
(assessment effort, implementation support, both own time); Tool Engineer has
a third (part weight, an estimate). Every further line is a **category from
the department's list**, and the category says what the line is:
- **own time** — hours (`kind=own_time`), valued at the department rate in the
  summation like the standing rows;
- **money, estimate** — a house number (`kind=external, pricing=estimate`);
- **money, vendor quote** — read from the favourite of the offers under the
  line (`pricing=quote`); one offer prices the line without a vote, several
  need the star. Sales' later choice is shown on the line, never edited here.
Categories: coded per department in `app/services/costing_tags.py` (each with
`entry_type` money|time, "other" in both types for everyone) plus the
department's own (`department_cost_categories`, migration 069, added from the
table's category dropdown with its type; soft delete). The free-text tag is
gone from the UI; the API still accepts any tag string.
The per-plant workbook grid (cycle-time delta, hours × rate) stays under the
table, collapsible. A department routed on several stages has one table.

**Full and partial quotes.** On a quoted line each offer is a **full quote**
(an alternative: one is bought, the star recommends which; several without a
star leave the line unpriced) or a **partial quote** (`is_partial`, migration
071: a part of the line, always counted). Line amount = sum of the parts +
the counted alternative; lead time = the slowest of those (calendar-day
compared). A part carries no star and cannot be Sales' choice; Sales decides
among the alternatives only.

**Vendors.** External lines are labelled "External · estimate" / "External ·
vendor quote". An estimated line may name who gave the number
(`CostingPosition.vendor_name`, migration 070); a quoted line names its
vendors on the offers. Every vendor field offers the **Suppliers master
data** and a new name typed there is stored as a supplier on save (best
effort), so the list grows the way the department categories do. Suppliers
are managed (renamed, deactivated) on the Suppliers page.

**Closing and reopening costing.** Departments enter lines while the change
is in `costing`. Costing closes when it moves to `quoting` — **Project
Management, Sales, the change lead or admin** may close it (PM runs costing
and says when the numbers are complete). Sending the quote (`quoting →
quoted`) stays Sales/lead/admin. While in `quoting` the commercial tab says
costing is closed and offers **Reopen costing** to the same people who may
close it; the reason is mandatory and recorded as `costing_reopened`. PM and
admin may still fix any department's lines at any time (`may_write`).

### Risk vocabulary: coded baseline + the department's own additions
- Coded per department in `app/services/risk_types.py` (own types, then the
  common timing/cost/other). Legacy moulding keys stay valid for everyone.
- A department **adds its own types** from the risk form ("+ Add own risk
  type…", `department_risk_types`, keys namespaced `d<dept>_<slug>`); members,
  PM and admin may add or remove. Removal is soft: off the dropdown, rows raised
  under it keep their key and stay valid; adding the same name revives it.
- **Risk templates** (`department_risk_templates`): pre-written type + severity
  + wording, picked in the form to prefill, saved from it with a tick, soft
  deleted. Same writers.

### Adding a department during `in_assessment`
Somebody was forgotten, or something turns out to be impacted after all. This
is NOT a recall to scoping (that tears down everyone's work and is refused once
anything is submitted). It is a **routing deviation** (`op: add`):
- **Who proposes:** change lead, PM or admin, from the assessment tab
  ("Add department"). Department, RASIC letter (R default) and a **mandatory
  reason** (the audit record of why they were missed).
- **Effect at once:** the department gets its assessment row and engine task on
  the assessment stage, with the standard due date. It is on the hook
  immediately; a blocking letter (R/A) gates costing like any first-stage row.
- **4-eyes decision:** the proposer never decides. A non-lead's proposal is the
  lead's call; the lead's proposal is anyone else's (the PM's). While pending,
  `in_assessment → costing` is refused ("Routing deviation is pending
  approval") and no further add is offered. The lead sees it under my-actions
  (`routing_deviation_decision`) and is notified.
- **Reject** needs a reason and undoes the add: row and task removed, the
  department off the hook. If the added department already answered, the
  rejection is refused — the answer is a fact of the record.
- **Approve** keeps it; on release the deviation is **promoted into the
  standard routing** for that change type (`promote_to_standard`), so the next
  change routes the department without anyone remembering.
Code: `change_routing_service.py::apply_deviation / reject_deviation /
approve_deviation`; UI `RoutingDeviationPanel.tsx`.

### Rejecting at capture
A request can go straight `captured → rejected` without passing through
scoping, via the **direct transition endpoint** with a `rejection_reason` —
forcing the scoping hop would demand a full capture for a change that is dying
anyway. Meetings cannot be recorded at `captured` at all: the scoping decision
is the project team's, so `meeting_service.py::create_meeting` requires status
`scoping`.

### Rejection and reopening
- Rejecting requires a memo and warns that the flow stops.
- `rejected → scoping` reopen requires its own memo.
- Both write their own changelog entry, separate from the status hop.
- **Cancellation stays terminal** — that is the irreversible one.

---

## 4. Naming and identity

- **Change title is composed, never typed:**
  `<our number>[ +n] - <customer number> - <item name>`, from the lead item.
  `StartChangeModal.tsx::composeTitle`.
- **Reason** is a one-line short description, hard-capped at 100 chars both
  sides. Detail belongs in attachments and assessments.
- **Cost carrier** replaces "customer-relevant": *Customer change* vs *Internal
  change*. Deliberately not "internal/external" — the D1 master already uses
  those words for its own independent `cm_internal` / `cm_external` flags.

---

## 5. Roles (ECR set, 2026-08-11)

The nine ECR roles, in picker order: **Sales, Project Manager, APQP, Tool
Engineer, Manufacturing Engineer, Process Engineer, Development, Scheduling,
Packaging Engineer** — plus **Quality**, kept active for the PM+Quality
approval sign-off. All other departments are deactivated for ECR
(migration 043; renames: R&D → Development, Tooling Engineer → Tool Engineer,
Planner/Scheduler → Scheduling).

Stage responsibilities so far: `captured` = Sales (`can_start_change`, Sales
only), `scoping` = Project Manager, impact lock = **Development only — no
admin shortcut**; an admin who needs to lock a set does it through acts-as
(`X-Acts-As-Department: <Development>`), so the department is on the record
rather than the admin bypass (`ChangeService.user_can_confirm_impact`),
`in_assessment` = routed departments per D1. UI shows the responsible role as
a badge on the stage (`StageResponsibleBadge.tsx`).

**Acts-as (admin testing):** an admin can pick any role from a header dropdown
and the *backend* treats them as an engineer in exactly that department —
admin bypass dropped while acting, every gate observable, mutations audited
with both identities (`X-Acts-As-Department`, spec
`2026-07-22-acts-as-role-switch-design.md`). Default "Myself" = full admin
view.

---

## 6. Open questions

- ⚠ **Cost carrier is never re-confirmed.** Sales picks it at capture and it
  selects the whole commercial branch; the scoping meeting should confirm or
  flip it before assessment, same pattern as the impact lock. A
  misclassification currently surfaces at `quoted`.
- ⚠ **Post-quote impact edits.** Editing the impacted set clears the Development lock —
  correct pre-quote, but after `quoted` it means the quote no longer covers the
  scope, and nothing forces reconciliation.
- ⚠ **Title staleness.** Composed once at creation; swapping the lead item later
  leaves the old name. See
  `docs/superpowers/plans/2026-08-06-title-backfill-dms-link.md`.
- ⚠ **One meeting or two.** Current position (and Fable's, consulted 2026-08-06):
  one. `captured` is originator data entry with no cross-functional obligation;
  `scoping` is the single CCB-style review. A `needs_info` outcome produces a
  *follow-up meeting row*, not a second meeting type.
- ⚠ **Workbook field mapping** — see §1.
- ⚠ **External flow only, for now (2026-08-11).** The current shape — Sales/PM
  as the only capturers, quote deadline, customer letters, Sales-owned
  loops — deliberately serves the *external* (customer-driven) change flow
  with safeguarding. When internal changes become a real volume, expect the
  starter set to widen (more `can_start_change` departments) and the internal
  branch to grow its own conventions. Revisit then; don't generalize early.
- ⚠ **Process responsibles per project (planned, not built — 2026-08-11).**
  Today department pickers preselect nothing (except Development, the master
  engineering role, when the user holds it). The intended end state: each
  project carries named *process responsibles* per role, auto-pulled into
  changes on that project — pickers then default to the project's responsible
  person/department instead of asking. Decided to note, deliberately not
  implemented yet.

---

## 7. Audit trail

Every rule above writes to the hash-chained `change_changelog`. Actions that
carry a human decision get their own entry rather than being folded into the
status change: `rejected`, `reopened`, `concern_raised`, `concern_withdrawn`
(with resolution note for department concerns), `scoping_meeting_decided`,
`impacted_lead_changed`, `title_backfilled`, `release_deadline_set`,
`quote_deadline_pushback`, `customer_response_recorded`.

An auditor asking "who objected, and what was done about it" is answered by the
concern rows plus the meeting decision that resolved them — not by inference
from who pressed a button.
