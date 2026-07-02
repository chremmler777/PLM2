# Engineering Change Management — Full Lifecycle Design (IATF/VDA-grade)

**Date:** 2026-07-02
**Status:** Approved goal, pending phase-level implementation plans
**Branch context:** builds on `feature/change-assessment-routing` (GB-CM-0001 digitization: D1 panel, RASIC assessments, cost lines, gates)

## Goal

Close the engineering-change loop in PLM2: from impact analysis on the tool/article
tree, through kickoff and check-workflow-driven implementation, to a *computed*
"ready to go" with verified 3D data — all under hard gate control, named
responsibility, and a unified tamper-evident audit trail that satisfies
IATF 16949 / VDA expectations.

PLM2 already captures changes well (state machine, RASIC routing, cost lines,
D1 gates, hash-chained changelog). This design closes the execution half of the
lifecycle and hardens the compliance posture.

## Decisions (agreed 2026-07-02)

| Topic | Decision |
|---|---|
| Execution backbone | Each ECN revision runs a real `WfInstance` from the check-workflow template; "ready to go" is computed from those instances completing. One engine; the parallel assessment-advancement logic in `change_routing_service` is retired over time. |
| Tree → revision propagation | Explicit pick with suggested roll-up: lead picks impacted nodes in an interactive tree; system suggests parent assemblies that structurally must revise (BOM references a new child revision); lead confirms. Nothing revises silently. |
| Gate enforcement | Hard gates + logged deviation. Gates always exist and always block. Only bypass is a formal deviation: proposed with reason, approved by a *different* authorized user (4-eyes), stored as its own auditable object. The `window.prompt` free-text justification override is removed. |
| 3D evidence | Required per impacted revision: an updated CAD/STEP file uploaded to the ECN revision, or an explicit owner-signed "no geometry change" flag, before that revision's check WF can complete. |
| Responsibility | Department routing + named owner (accept or assign) + due dates on every step, overdue flagging, escalation to the change lead. My Tasks reflects ownership, not just department membership. |
| Audit | All change-relevant events also write to the existing (currently unused) hash-chained `AuditLog` with a correlation id per change — one filterable, exportable timeline per change and per part. |
| UI scope | Change-module UX overhaul + interactive impact tree + unified audit timeline + app-wide theme cleanup incl. retiring the legacy Article UI stack. |
| Compliance frame | IATF 16949 / VDA: provable non-bypassable release control, 4-eyes on deviations and sign-offs, who/what/when/on-whose-approval evidence, tamper-evident chains. |

## Scope areas

### 1. Impact tree → revisions
Interactive tree of the affected tool/article (Part hierarchy + revision-owned
BOM). Lead picks impacted nodes; system computes suggested parent roll-ups;
confirmed nodes become `ChangeImpactedItem`s. Kickoff (approved →
in_implementation) spawns ECN `PartRevision`s with bidirectional links
(revision ↔ change): add `originating_change_id` on `PartRevision` alongside the
existing `resulting_revision_id` on the impacted item.

### 2. Check workflow drives execution
On kickoff, each ECN revision gets a `WfInstance` from the mapped check-workflow
template. Ready-to-go = all impacted revisions' instances complete, including a
3D-data step gated on evidence (see decision above). On release, revisions
activate/supersede as today. `ChangeRequest` exposes computed implementation
progress (per-revision WF status roll-up).

### 3. Hard gates + controlled deviation
Gate rows are created for every change (data migration seeds them for in-flight
changes so existing behavior is preserved at their current effective state).
`_guard` treats gates as blocking always. New `GateDeviation` (or generalized
deviation object shared with routing deviations): propose → approve by different
authorized user → gate passable; every step audited.

### 4. Named responsibility & due dates
`owner_id`, `due_date`, `accepted_at` on assessments and WF instance tasks;
overdue computation; escalation surfacing to the change lead (dashboard +
My Tasks). Ownership changes are audited events.

### 5. Unified audit
`AuditService` writing to `AuditLog` (hash-chained, `correlation_id` =
change number) invoked from change transitions, gate decisions, deviations,
sign-offs, WF step completions, file uploads, ownership changes. Per-entity
changelogs (`ChangeChangelog`, `RevisionChangelog`) remain; `AuditLog` becomes
the cross-entity queryable layer. Export endpoint (CSV/PDF) for audits.

### 6. Sleek, guided UI
A change **cockpit**: lifecycle stepper, impact tree with per-node
revision + WF status, gate panel, evidence checklist, audit timeline. Proper
modal dialogs (no `window.prompt`/`alert`), resolved names instead of raw IDs,
one consistent dark-slate theme app-wide, legacy Article UI retired.

**UX principles:** project managers *and* engineers must feel at home and be
visually guided — the UI should always answer "where is this change, what is
blocking it, who is on the hook, what do I do next" at a glance. Progressive
disclosure (summary first, detail on demand), status colors used consistently,
empty states that teach, quality-of-life touches welcome (keyboard-friendly
grids, sensible defaults, inline validation).

**The UI drives the task (hard requirement, 2026-07-02):** never leave the
user asking "where do I define this?". Every blocked state names its reason
and offers the resolving action in place (blocked transition → inline
deviation request; missing evidence → upload affordance on the exact item;
pending approval → approve/reject buttons where the pending thing is shown).
Every screen has one visually primary next action derived from the change's
state. Forms and pickers open in context (modals/inline), never on a
disconnected settings page the user must know about.

## Workflow definitions (seeded templates, RASIC per department module)

Source: `Documents/Changemanagement/ÄnderungsmitteilungChange_Management (*).xlsx`
(D1 approval matrix rows 32–45, gates rows 48–57, department tabs D2–D10). The
existing `ECR` WfTemplate in the DB is a 4-step stub and is replaced by these
two seeded, designer-editable templates. Department names map to seeded
`wf_departments`; D1-matrix roles not present as departments map as noted.

### Template 1: "ECM Bewertung" (change-level assessment routing; captured → approved)

Replaces the ECR stub as the `ChangeRoutingStandard` target for all change types.
Each R-department's module = its D2–D10 tab (producibility verdict + cost lines
per affected plant).

| Stage | Step | R | A | S/C/I |
|---|---|---|---|---|
| 1 Machbarkeit & Bewertung *(opens after gate `feasibility`)* | Fachbereichsbewertung (parallel, one per dept) | Sales, R&D, Tool design, IE, Quality, Logistics, Production, Purchasing, Production control | Project Manager | I: Planner/Scheduler |
| 2 Summierung & Budget *(gate `budget` guards exit)* | Kostenzusammenfassung prüfen, Budget freigeben | Project Manager | Sales | C: R&D, Tool design; I: all assessed depts |
| 3 Kundenaktivitäten | Angebot an Kunde / Kundenantwort erfassen | Sales | Project Manager | I: Quality (customer_relevant), R&D |

D1-matrix mapping: Produktentwicklung→R&D; Prozessentw./Industrial Engineering→IE;
WZ-Management→Tool design; Lieferantenmanagement→Purchasing; QVP + QS (Messraum,
SPC)→Quality; Fertigungssteuerung→Production control. Producibility is asked
**per affected plant** (D1 has one matrix per plant); assessments stay
per-department with per-plant cost lines and per-plant producibility flags.

### Template 2: "ECN Umsetzung" (check workflow per impacted ECN revision; kickoff → ready-to-go)

Instantiated as a `WfInstance` per ECN revision at kickoff (gate `release` = the
D1 "techn. Freigabe / Bestellung → Start Umsetzung"). Steps that don't apply to
an item category are waivable by the owner with reason (audited).

| Stage | Step | R | A | S/C/I |
|---|---|---|---|---|
| 1 Konstruktion | 3D-Daten aktualisieren **(evidence: CAD file on revision or signed no-geometry-change)** | Tool design (tools) / R&D (articles) | R&D | I: Project Manager |
| | Zeichnungen & Doku aktualisieren | Tool design / R&D | R&D | S: Quality |
| 2 Design-Check (4-eyes) | Konstruktionsprüfung (different user than step 1) | R&D | Quality | C: IE |
| 3 Industrialisierung | Werkzeugänderung umsetzen | Production | Tool design | I: Production control |
| | Prozess/Arbeitspläne anpassen | IE | Project Manager | C: Production |
| | Prüfplan / PPAP-Bedarf klären | Quality | Project Manager | C: Sales (if customer_relevant) |
| | Stammdaten & Logistik aktualisieren | Logistics | Project Manager | C: Purchasing; I: Production control |
| 4 Ready to go | Bemusterung / Trial | Quality | Project Manager | S: Production |
| | Finale Freigabe (computed check: all steps done, evidence complete) | Project Manager | Quality | I: Sales, Logistics, Production control |

RASIC semantics as in the existing routing engine: R/A block, S/C never block
(cascade), I notify-only. "Ready to go" on the change = every impacted
revision's instance reached Finale Freigabe.

## Phasing (each phase = own spec/plan → implement cycle)

| Phase | Content | Rationale |
|---|---|---|
| **A** | Hard gates + deviation objects + unified `AuditLog` service & timeline API | Smallest, unblocks compliance; everything later writes into it |
| **B** | Impact tree picking + roll-up suggestion → ECN revision spawning with back-links → check-WF instances → 3D evidence rule → computed ready-to-go | The core loop |
| **C** | Named ownership, due dates, overdue/escalation, My Tasks rework | Layers onto B's task model |
| **D** | Cockpit UI, audit timeline view, app-wide theme cleanup, legacy Article stack retirement | Polish once the data model is stable |

## Execution guidance

- **Model tiering for agent work:** split implementation across agent tiers to
  save cost where it does not cost quality — haiku for mechanical/boilerplate
  tasks (migrations following an established pattern, label maps, simple CRUD
  wiring), sonnet for standard feature implementation, opus/high tier for
  design-sensitive work (state-machine changes, audit hash chains, the impact
  tree algorithm, UX-critical components) and for review/verification passes.
  Never trade correctness for cost; when in doubt, tier up.
- **Test everything:** TDD per task (failing test → minimal implementation →
  pass → commit). Backend pytest, frontend vitest; state-machine and audit-chain
  logic get exhaustive transition/tamper tests; UI flows get component tests.
- **Backward compatibility:** existing tests stay green. Gate hardening ships
  with a migration seeding gate rows for in-flight changes at their current
  effective state.

## Constraints & conventions

- Build on the **Part** stack; legacy Article models are retired, not extended.
- SQLAlchemy 2.0 async (`Mapped`/`mapped_column`), idempotent Alembic migrations
  (inspect-guard pattern, `sa.String` for enum-likes), Pydantic v2
  `from_attributes`, module-constant value tuples.
- Every new model registered in `backend/app/models/__init__.py`.
- Audited actions append to the relevant hash-chained log(s).
- Frontend: TypeScript, TanStack Query, Tailwind dark-slate, DE/EN labels via
  `cmLabels`-style maps.
- Run backend tests from `backend/` with `python3 -m pytest`.

## Error handling & risks

- **WfInstance/assessment duplication during transition period:** Phase B wires
  check-WF instances for ECN revisions; pre-kickoff department assessments keep
  the existing routing engine until a later consolidation. Both write to the
  unified audit, so evidence stays whole.
- **Gate seeding for in-flight changes:** migrate to the state that preserves
  current pass/fail behavior (gates already passed by status are seeded "yes").
- **CAD conversion pipeline is optional at runtime** (pythonocc may be absent):
  the 3D-evidence rule checks file presence + owner sign, not conversion success.
- **No org/plant scoping on change queries** (known gap): note for Phase C/D,
  not a blocker for A/B.
