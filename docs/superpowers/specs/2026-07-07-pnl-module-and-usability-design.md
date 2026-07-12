# Profit & Loss Module + Change-Flow Usability Iteration

**Date:** 2026-07-07
**Status:** Approved for implementation (autonomous /goal loop)
**Branch:** `feature/pnl-and-usability`
**Goal (user):** Add P&L as a general module fed by change management; test change management, role management, and workflows; simplify the flow so it is easy and understandable for humans (isolate technical views, visual trackable status, working escalations); then write per-department guides and a user manual. Loop until satisfied.

## Part 1 — Profit & Loss module

### Concept

P&L is a **general reporting module** with pluggable sources. The first (and for now only) source is change management. Every P&L row is a normalized record:

```
source_type ("change") · source_id · label · project · plant(s) · branch (customer|internal)
revenue · internal_cost · external_cost · total_cost · margin · margin_pct · effort_hours · status · dates
```

**Computed on read — no new tables, no migration.** All inputs already persist:

- Revenue, customer branch: `ChangeRequest.quoted_price`
- Budget, internal branch: `ChangeRequest.internal_approved_amount` (internal changes have no revenue; their "P&L" is approved budget vs. actual assessed cost)
- Cost: `CostService.summation` over `AssessmentCostLine.internal_cost / external_cost` (one_time + lifecycle shown separately)
- Effort: `ChangeAssessment.effort_hours` rollup (informational, not costed)

Margin: customer branch = `quoted_price − total_cost`; internal branch = `internal_approved_amount − total_cost` (i.e. budget variance, labeled as such in the UI — not "profit").

### Backend

- New `PnlService` (`app/services/pnl_service.py`), sibling of `ReportService`, reusing `change_service._org_scope` for authorization scoping.
- Endpoints (`app/api/v1/pnl.py`):
  - `GET /api/v1/pnl/changes` — per-change P&L rows; filters: `project_id`, `plant_id`, `branch` (customer|internal), `status_group` (pipeline|approved|done), date range.
  - `GET /api/v1/pnl/summary` — totals + breakdowns by project and by branch; pipeline vs. realized split (realized = status approved and beyond).
- Only changes that have reached `costing` or beyond appear (before that there is no cost basis). Changes without a revenue figure yet (in costing, quote pending) show revenue `null` and are flagged `pending_price`.
- Auth: any authenticated user, org-scoped like changes. A finance-role gate is a deliberate later option; the service takes the user so a gate can be added in one place.

### Frontend

- New route `/pnl`, sidebar entry **P&L 💰** next to Reports. Dark-slate, ReportsPage card patterns.
- Page: summary tiles (Revenue, Cost int/ext, Margin, Margin %), filter bar, per-change table with margin badge (emerald positive / red negative / slate pending), row click → change cockpit commercial tab.
- Cockpit integration: the commercial tab gets a compact **P&L card** for that change (revenue vs. cost vs. margin) so the change's financial picture lives where the money decisions are made.

## Part 2 — Usability iteration ("easy, understandable, human")

### 2.1 Isolate technical views

- Sidebar gains two groups: **Daily work** (Dashboard, Projects, Purchased Parts, Suppliers, Lessons, Changes, P&L, Reports, My Tasks) and a collapsed **Setup** group (Workflows designer, Users) shown only to admins/engineers. Everyday users never see template authoring.
- Cockpit tabs: **D1 and Audit move behind a single "Governance" tab-group toggle** (or role-gate: visible to lead/Quality/admin only). Default everyday view: Overview · Scoping · Impacted · Assessments · Commercial · Implementation.
- Remaining light-theme legacy in the change path (`DeviationBanner`, `ReasonDialog`) converted to dark-slate.

### 2.2 Visual, trackable status

- `LifecycleStepper` becomes **branch-aware**: internal changes hide the `quoted` step; the stepper shows only the path this change will actually take.
- Stepper steps get plain-language sublabels (e.g. scoping = "Scope & decide participants", costing = "Sum up costs") from `cmLabels`.
- ChangesPage list: add a mini progress indicator (n/m steps) per row so the pipeline is scannable without opening each change.
- `CockpitSummary` stays the "what now" engine; audit that every blocked state names its reason and offers the resolving action in place (existing UX hard requirement).

### 2.3 Escalations must work

- Verify end-to-end: overdue assessment / at-risk deadline → notification sweep emits → bell + My Tasks EscalationsCard show it → deep link resolves.
- Gap to close if found: escalation visibility for the *department lead* of an overdue assessment (currently lead-of-change only), and a clear "escalated" marker in the cockpit.

## Part 3 — Testing (repeat after Part 2)

1. Backend `pytest` (312+) and frontend `vitest` suites green; new P&L service/endpoint tests + component tests.
2. **Playwright live walkthrough** (user requirement): drive the real app (uvicorn + vite) through the full lifecycle per role — initiator captures, PM scopes with meeting, departments assess with effort + cost lines, PM sums, internal branch → PM approves costs, customer branch → Sales quotes → accept → sign-offs → approved; check P&L page reflects it; check escalation appears when a due date passes. Screenshot each stage; judge stability *and* whether each screen makes sense.
3. Role-management checks: viewer sees no admin surfaces; non-PM cannot decide meetings/approve costs; deviation 4-eyes holds.

## Part 4 — Documentation (only when flow is satisfying)

`docs/guides/`: one guide per department — Initiator (Sales/anyone), Project Management, Technical departments (assessors), Sales/Commercial, Quality, Management (P&L reading) — plus `docs/guides/manual.md`, the end-to-end user manual. Plain language, per-step "what you see / what you do", mirrors the real UI after the usability pass.

**Visual guides (user request):** each guide opens with a flow diagram of that department's slice of the lifecycle (mermaid in the markdown), and steps embed the annotated screenshots captured during the Playwright walkthrough (`docs/guides/img/`). The manual gets the full lifecycle diagram with the customer/internal branch split.

## Out of scope

- Approval threshold rules, finance role, quote line items, non-change P&L sources (design leaves the seam), implementation-phase redesign.
