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
