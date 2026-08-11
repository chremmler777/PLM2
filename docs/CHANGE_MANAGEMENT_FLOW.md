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
- **Concerns** — any team member may flag `reject_proposal` or `needs_info` with
  a note. Only its author may withdraw it (admins are *not* exempt). One open
  concern per person per kind. `meeting_service.py::raise_concern`.
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
4. **Closure**: the decider withdraws their flag once the answers suffice
   (author-only — whoever asked the question judges the answer), then a
   follow-up meeting decides `proceed`. All steps audited.

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

### Inside `in_assessment` — department holds are the risk assessment (2026-08-11)

The department-concern loop at assessment **is the change's risk register**:
a department flags a risk, anyone proposes a mitigation with mandatory
documentation (PPT in the risk's container), and the flagging department (or
PM) accepts or loops — raised → mitigated → accepted, each step stamped.
Risks are not vetoes: they hold only the flagging department's own submit;
the pass decision is the feasible/not-feasible verdict. UI presents these as
"Risks" in the assessment context.

- A department member may raise a **department-scoped concern**: kind
  `reject_proposal` (grounds that would cancel) or `needs_info` (missing
  information), with a note, attributed to their own department
  (`meeting_service.py::raise_concern`, `department_id` required in this phase).
- An open concern is a **soft hold on that department only**: its assessment
  cannot be submitted while points are open
  (`change_service.py::submit_assessment`); the change's status and deadlines
  are untouched, other departments keep working. UI: "On hold" chip per
  department, cockpit counts blocked departments
  (`ChangeResponse.blocked_department_ids`).
- Closing a department concern **requires a resolution note** ("how was it
  addressed") — `POST .../concerns/{id}/withdraw`; author-only, audited with
  the note.

### Assessment shape (2026-08-11, in build)

- **One expandable bucket per routed department**; collapsed = status +
  verdict, expanded = that department's working surface. Members work only
  their own bucket; everyone sees all statuses.
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
  supplier; reported, not gated). **`not_feasible` hard-requires the
  explanation document (PPT) for the customer** as assessment evidence.
  Checked items seed the department's costing grid (cycle time → lifecycle
  line, rest one-time; remark travels as the line note; deliberate deletions
  are remembered).

### Costing & timing shape (2026-08-11, in build)

- **Per-department cost buckets at `costing`** — same accordion philosophy as
  assessment: each participating department files one-time lines (activity
  from its catalog or free label, per plant, hours × rate snapshot + external
  cost) and lifecycle lines as **production-time deltas** (± min/part, per
  plant). Departments see only their own figures; **PM and Sales see all**
  (summation: per-department, one-time vs lifecycle, grand total).
- **Timing**: each department's costing entry carries an implementation
  lead-time estimate; the change-level roll-up is the max.
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
