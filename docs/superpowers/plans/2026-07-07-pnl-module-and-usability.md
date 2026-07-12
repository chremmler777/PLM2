# P&L Module + Usability Iteration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Profit & Loss module (computed from existing change-management cost data), simplify the change flow UX (grouped nav, governance-tab isolation, branch-aware stepper), verify escalations, then validate everything with unit suites and a Playwright live walkthrough, and write per-department guides.

**Architecture:** P&L is computed on read — a new `PnlService` reconciles revenue (`quoted_price` for customer changes, `internal_approved_amount` for internal) against `AssessmentCostLine` cost aggregates, org-scoped via the existing `_org_scope` helper. No migration. Frontend adds a `/pnl` page following ReportsPage patterns, plus a P&L card in the cockpit commercial tab. Usability work touches only presentation-layer files (Sidebar, ChangeDetailPage tab bar, LifecycleStepper, ChangesPage).

**Tech Stack:** FastAPI + SQLAlchemy async (backend), pytest asyncio-auto (backend tests), React + TS + react-query + Tailwind dark-slate (frontend), vitest + Testing Library (frontend tests), Playwright (live E2E).

**Spec:** `docs/superpowers/specs/2026-07-07-pnl-module-and-usability-design.md`

## Global Constraints

- Dark-slate theme only: `bg-slate-800` cards, `border-slate-700`, sky-500/600 primary, emerald=positive, amber=warning, red=negative. No `bg-white`/`text-gray-*` in new/touched UI.
- Internal changes have **budget variance**, not profit — UI must label internal-branch margin "vs. approved budget", never "profit".
- Only changes in `costing` or beyond appear in P&L (no cost basis before that).
- All money floats rounded to 2 decimals in responses.
- Backend tests: `cd backend && python -m pytest tests/<file> -q`. Frontend: `cd frontend && npx vitest run <file>`. Full gates at Task 10.
- Commit after every task, message convention `feat:`/`fix:`/`docs:` + scope, trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Model tiering: mechanical tasks (theme conversion, docs scaffolding) → haiku/sonnet; service/guard logic and reviews → default model.

---

### Task 1: PnlService (backend)

**Files:**
- Create: `backend/app/services/pnl_service.py`
- Test: `backend/tests/test_pnl.py`

**Interfaces:**
- Consumes: `CostService.summation(session, change)` (dict with `totals.grand_total`, `total_effort_hours`); `app.services.report_service._org_scope(stmt, viewer)`; `ChangeRequest` fields `quoted_price`, `internal_approved_amount`, `customer_relevant`, `status`, `project_id`.
- Produces:
  - `PnlService.changes_pnl(session, viewer, project_id=None, plant_id=None, branch=None, status_group=None) -> list[dict]` — rows with keys `change_id, change_number, title, project_id, project_name, branch ("customer"|"internal"), status, revenue (float|None), internal_cost, external_cost, total_cost, margin (float|None), margin_pct (float|None), effort_hours, pending_price (bool), realized (bool)`.
  - `PnlService.summary(session, viewer, ...same filters) -> dict` — `{"totals": {revenue, internal_cost, external_cost, total_cost, margin, margin_pct}, "pipeline": {...same keys}, "realized": {...}, "by_project": [{project_id, name, revenue, total_cost, margin}], "by_branch": {"customer": {...}, "internal": {...}}, "count": int}`.

**Definitions:**
- `PNL_STATUSES = ("costing", "quoted", "approved", "in_implementation", "in_validation", "released", "closed")`; `REALIZED_STATUSES = PNL_STATUSES[2:]`.
- Revenue: `quoted_price` if `customer_relevant` else `internal_approved_amount`. `pending_price = revenue is None`.
- Cost per change: sum of `AssessmentCostLine.internal_cost` / `.external_cost` joined via `ChangeAssessment.change_id` (single grouped query for all changes — do NOT call `CostService.summation` per change in a loop).
- `margin = revenue - total_cost` when revenue is not None, else None; `margin_pct = margin / revenue * 100` when revenue not in (None, 0).
- `plant_id` filter: change has ≥1 cost line with that `plant_id`.
- `status_group`: `"pipeline"` → status in `("costing", "quoted")`; `"realized"` → status in `REALIZED_STATUSES`; None → all of `PNL_STATUSES`.
- Summary totals treat `None` revenue as 0 for sums but count them in `count`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_pnl.py`. Use existing conftest helpers (`seed`, `admin_auth`, `record_proceed_meeting`, `advance_to_assessment`). Build two changes via service/session directly (pattern from `test_reports.py`): one customer-relevant in `quoted` with `quoted_price=10000` and cost lines summing internal 4000 / external 2000; one internal in `costing` with `internal_approved_amount=None` then approved snapshot 5000, cost lines internal 3000 / external 0. Tests:

```python
async def test_changes_pnl_rows(...):
    rows = await PnlService.changes_pnl(session, admin_user)
    cust = next(r for r in rows if r["branch"] == "customer")
    assert cust["revenue"] == 10000.0 and cust["total_cost"] == 6000.0
    assert cust["margin"] == 4000.0 and cust["margin_pct"] == 40.0

async def test_internal_branch_uses_approved_amount(...):
    # before approval: pending_price True, margin None
    # after ChangeService.approve_internal_costs: revenue == snapshot, margin == snapshot - cost

async def test_excludes_pre_costing_statuses(...):
    # change in "in_assessment" never appears

async def test_filters(...):
    # branch="internal" returns only internal; status_group="pipeline" excludes approved+

async def test_summary_shape_and_totals(...):
    s = await PnlService.summary(session, admin_user)
    assert s["totals"]["margin"] == s["totals"]["revenue"] - s["totals"]["total_cost"]
    assert set(s["by_branch"]) == {"customer", "internal"}

async def test_org_scoping(...):
    # non-admin viewer from another org sees no rows (mirror test_reports.py org test)
```

- [ ] **Step 2: Run tests, verify FAIL** (`ModuleNotFoundError: app.services.pnl_service`).
- [ ] **Step 3: Implement `PnlService`** — single grouped cost query keyed by change_id; second query for effort; one pass to build rows; `summary` reuses `changes_pnl` rows (pure-python aggregation, fine at this scale).
- [ ] **Step 4: Run `python -m pytest tests/test_pnl.py -q`** → all pass.
- [ ] **Step 5: Commit** `feat(pnl): PnlService — per-change P&L rows and summary aggregation`.

### Task 2: P&L endpoints (backend)

**Files:**
- Create: `backend/app/api/v1/pnl.py`
- Modify: `backend/app/api/v1/__init__.py` (register router — follow how `reports.py` router is included)
- Test: `backend/tests/test_pnl_api.py`

**Interfaces:**
- Produces: `GET /api/v1/pnl/changes?project_id=&plant_id=&branch=&status_group=` → `{"rows": [...]}`; `GET /api/v1/pnl/summary?...` → summary dict. Both `Depends(get_current_user)`, mirror `backend/app/api/v1/reports.py` exactly (router prefix `/pnl`, tags `["pnl"]`).

- [ ] **Step 1: Failing API tests** — auth required (401 anon), 200 shape for admin, filters passed through (branch=internal returns only internal rows), invalid `branch` value → 422 (use `Literal["customer","internal"]` query param).
- [ ] **Step 2: Verify FAIL.**
- [ ] **Step 3: Implement router + registration.**
- [ ] **Step 4: `python -m pytest tests/test_pnl_api.py tests/test_pnl.py -q`** → pass.
- [ ] **Step 5: Commit** `feat(pnl): /api/v1/pnl endpoints (changes, summary)`.

### Task 3: P&L page (frontend)

**Files:**
- Create: `frontend/src/api/pnl.ts`, `frontend/src/types/pnl.ts`, `frontend/src/pages/PnlPage.tsx`, `frontend/src/pages/PnlPage.test.tsx`
- Modify: `frontend/src/App.tsx` (route `/pnl`), `frontend/src/components/layout/Sidebar.tsx` (nav entry `{ path: '/pnl', label: 'P&L', icon: '💰' }` after Changes)

**Interfaces:**
- Consumes: Task 2 endpoints via `client.get('/v1/pnl/changes', { params })` / `'/v1/pnl/summary'`.
- Produces: `pnlApi = { changes(filters): Promise<{rows: PnlRow[]}>, summary(filters): Promise<PnlSummary> }`; types `PnlRow`, `PnlSummary` mirroring Task 1 keys.

**Page layout (ReportsPage card patterns, `bg-slate-800 border border-slate-700 rounded-lg`):**
- 4 summary tiles: Revenue, Cost (int + ext sublines), Margin (emerald ≥0 / red <0), Margin %.
- Pipeline vs. Realized split row (two compact cards).
- Filter bar: project select (reuse projects query pattern), branch toggle (All / Customer / Internal), status-group toggle (All / Pipeline / Realized).
- Table: Change # (link `/changes/:id?tab=commercial`), Title, Branch chip, Status pill (`STATUS_PILL`), Revenue (— + amber "price pending" chip when `pending_price`), Int. cost, Ext. cost, Margin badge. Internal rows label margin column tooltip/header note "vs. approved budget".

- [ ] **Step 1: Failing component test** (pattern `ReportsPage.test.tsx`: QueryClientProvider + MemoryRouter, mock `pnlApi`): renders tiles from summary, renders row with margin badge emerald for positive, shows "price pending" for `pending_price` row, branch filter triggers refetch with param.
- [ ] **Step 2: Verify FAIL** (`npx vitest run src/pages/PnlPage.test.tsx`).
- [ ] **Step 3: Implement api/types/page + route + sidebar entry.**
- [ ] **Step 4: Tests pass; `npx tsc --noEmit` clean for new files.**
- [ ] **Step 5: Commit** `feat(pnl): P&L page, sidebar entry, api client`.

### Task 4: Cockpit P&L card (frontend)

**Files:**
- Create: `frontend/src/components/changes/PnlCard.tsx`, `frontend/src/components/changes/PnlCard.test.tsx`
- Modify: `frontend/src/pages/ChangeDetailPage.tsx` (render `<PnlCard change={change} />` at top of commercial tab)

**Interfaces:**
- Consumes: `change` object (has `customer_relevant`, `quoted_price`, `internal_approved_amount`, `status`) + `changesApi.summation(changeId)` (existing) for cost totals.
- Produces: compact 3-column card — Revenue/Budget · Cost (int/ext) · Margin — same semantics as Task 1; hidden entirely before `costing` (statuses `captured|scoping|in_assessment`).

- [ ] **Step 1: Failing tests** — customer branch shows "Revenue" label + margin; internal shows "Approved budget" + "vs. approved budget"; hidden in `in_assessment`.
- [ ] **Step 2: Verify FAIL. Step 3: Implement. Step 4: Pass + tsc. Step 5: Commit** `feat(pnl): per-change P&L card in commercial tab`.

### Task 5: Sidebar groups — isolate technical nav

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Test: create `frontend/src/components/layout/Sidebar.test.tsx`

Split `navItems` into `dailyItems` (Dashboard, Projects, Purchased Parts, Suppliers, Lessons Learned, Changes, P&L, Reports, My Tasks) and `setupItems` (Workflows, Users[admin]). Render Setup as a separate section under a `SETUP` slate-500 uppercase heading, **only when `role === 'admin' || role === 'engineer'`** (from `useAuth()`), collapsed-sidebar behavior unchanged. Everyday users (viewer + dept members) no longer see the workflow designer.

- [ ] **Step 1: Failing test** — renders Setup heading + Workflows for admin; hides both for viewer role (mock `useAuth`); My Tasks badge still renders.
- [ ] **Step 2–4: FAIL → implement → PASS + tsc.**
- [ ] **Step 5: Commit** `feat(nav): daily/setup sidebar groups; hide designer from everyday users`.

### Task 6: Governance tab isolation in cockpit

**Files:**
- Modify: `frontend/src/pages/ChangeDetailPage.tsx`
- Test: extend `frontend/src/pages/ChangeDetailPage.test.tsx`

Everyday tab bar: `overview | scoping | impacted | assessments | commercial | implementation`. `d1` and `audit` move into a right-aligned "Governance ▾" group in the tab bar, rendered **only** when the viewer is change lead, admin, or Quality/PM department member — reuse the `myActions`/authz data already fetched by the page if it exposes this; otherwise gate on `isAdmin || user.id === change.lead_id` plus keep deep links working (`?tab=d1` still opens for authorized users; unauthorized deep link falls back to overview).

- [ ] **Step 1: Failing tests** — viewer (non-lead) sees no D1/Audit tab buttons; lead sees Governance group; `?tab=audit` as unauthorized falls back to overview.
- [ ] **Step 2–4: FAIL → implement → PASS + tsc.**
- [ ] **Step 5: Commit** `feat(cockpit): governance tabs (D1, audit) isolated behind role-gated group`.

### Task 7: Branch-aware stepper + plain-language sublabels + list progress

**Files:**
- Modify: `frontend/src/components/changes/LifecycleStepper.tsx` (new optional prop `customerRelevant?: boolean`), `frontend/src/lib/changeStatus.ts` (add `STATUS_HINTS: Partial<Record<ChangeStatus, string>>`), `frontend/src/pages/ChangeDetailPage.tsx` (pass prop), `frontend/src/pages/ChangesPage.tsx` (mini progress `n/m` per row)
- Test: extend `frontend/src/components/changes/LifecycleStepper.test.tsx`, `frontend/src/lib/changeStatus.test.ts`

`STATUS_HINTS` (shown as `title` tooltip + small sublabel under current step): captured "Describe what should change", scoping "Meet, decide, pick departments", in_assessment "Departments check feasibility & cost", costing "Sum up costs", quoted "Offer sent to customer", approved "Go decision made", in_implementation "Doing the work", in_validation "Checking results", released "Change is live", closed "Wrapped up".
Stepper: when `customerRelevant === false`, filter `quoted` out of the rendered order (indices recomputed). Current step renders its hint as a second line (`text-[10px] text-slate-400`). ChangesPage: per row `step i/n` chip computed from the same filtered order (helper `stepPosition(status, customerRelevant)` exported from `changeStatus.ts`).

- [ ] **Step 1: Failing tests** — internal change stepper omits "Quoted"; customer stepper keeps it; current step shows hint text; `stepPosition('costing', false)` returns `{index: 3, total: 9}` (captured→closed minus quoted = 9 on-path steps).
- [ ] **Step 2–4: FAIL → implement → PASS + tsc.**
- [ ] **Step 5: Commit** `feat(status): branch-aware stepper with plain-language hints; list progress chip`.

### Task 8: Dark-slate conversion of remaining light components

**Files:**
- Modify: `frontend/src/components/changes/DeviationBanner.tsx`, `frontend/src/components/changes/ReasonDialog.tsx`
- Test: existing tests must stay green (`DeviationBanner.test.tsx`)

Mechanical restyle to slate tokens (`bg-white`→`bg-slate-800`, `text-gray-900`→`text-slate-100`, `border-gray-200`→`border-slate-700`, buttons to sky-600); no behavior change. (PartDetail.tsx light theme is out of scope — not in the change path.)

- [ ] **Step 1: Restyle. Step 2: `npx vitest run src/components/changes` green + tsc. Step 3: Commit** `fix(theme): dark-slate DeviationBanner + ReasonDialog`.

### Task 9: Escalation verification + department-lead gap

**Files:**
- Test first: `backend/tests/test_escalations.py`, `backend/tests/test_notification_sweep.py` (extend)
- Possibly modify: `backend/app/services/notification_sweep.py`, `backend/app/services/change_service.py` (`lead_escalations`)

Verify the chain: overdue `ChangeAssessment.due_date` → sweep emits `overdue` notification to assessment owner **and change lead**; unowned overdue assessment → notify department members (this is the suspected gap — if `run_notification_sweep` only notifies owners, an unclaimed overdue assessment escalates to nobody). Write the test that encodes the desired behavior; if it fails, fix the sweep to notify the change lead for unclaimed overdue assessments (dedup via existing `notify_once`).

- [ ] **Step 1: Read `notification_sweep.py` + existing tests; write failing test** `test_unclaimed_overdue_assessment_notifies_lead`.
- [ ] **Step 2: Run; if it already passes, record that escalations are complete and skip to commit (test kept as regression guard). If FAIL: implement lead notification in sweep.**
- [ ] **Step 3: `python -m pytest tests/test_escalations.py tests/test_notification_sweep.py -q`** → pass.
- [ ] **Step 4: Commit** `fix(escalation): unclaimed overdue assessments escalate to change lead` (or `test(escalation): regression coverage` if no fix needed).

### Task 10: Full verification gates

- [ ] **Step 1:** `cd backend && python -m pytest -q` → all pass (baseline ~312 + new).
- [ ] **Step 2:** `cd frontend && npx vitest run` → all pass; `npx tsc --noEmit` → 0 errors; `npm run lint` → clean.
- [ ] **Step 3: Commit** any stragglers; record counts in `.superpowers/sdd/progress.md`.

### Task 11: Playwright live walkthrough (stability + does-it-make-sense)

**Files:**
- Create: `docs/guides/img/` (screenshots), walkthrough notes in `.superpowers/sdd/walkthrough-2026-07-07.md`

Run the real stack (`./run_backend.sh` on :8000, `cd frontend && npm run dev` on :5173). Use the playwright-cli skill / MCP browser. Logins: admin@example.com/admin1234, test@example.com/password. Walk both branches end to end:

1. **Customer branch:** capture change (customer_relevant) → PM records scoping meeting, decision proceed with 2 departments → each department assesses (effort hours + cost lines) → costing summation → Sales sets quoted price → customer accepted → PM+Quality sign-offs → approved. Screenshot every stage (name `NN-<stage>-<role>.png`).
2. **Internal branch:** capture (not customer-relevant) → scope → assess → costing → PM approves internal costs → approved. Verify stepper omits "Quoted".
3. **P&L:** open `/pnl`, verify both changes appear with correct revenue/cost/margin; open cockpit commercial tab P&L card.
4. **Roles:** login as viewer/dept member — no Setup nav group, no Governance tabs, cannot decide meeting (button absent/403 toast).
5. **Escalation:** set an assessment due_date in the past (API), trigger sweep, verify bell notification + My Tasks EscalationsCard entry + deep link.
6. **Judgement pass:** at each screen note anything confusing, dead-ended, or mislabeled in the walkthrough notes — these feed the next loop iteration.

- [ ] **Step 1: Run walkthrough, capture screenshots + notes.**
- [ ] **Step 2: File every found issue as a fix task; fix-and-re-verify small ones immediately.**
- [ ] **Step 3: Commit** `test(e2e): playwright walkthrough evidence + notes`.

### Task 12: Department guides + manual (only after Task 11 issues are resolved)

**Files:**
- Create: `docs/guides/initiator.md`, `docs/guides/project-management.md`, `docs/guides/technical-departments.md`, `docs/guides/sales.md`, `docs/guides/quality.md`, `docs/guides/management-pnl.md`, `docs/guides/manual.md`

Each guide: (1) mermaid flow diagram of that department's slice, (2) "Your job in one paragraph", (3) step-by-step "what you see / what you do" with the Task 11 screenshots embedded (relative `img/` paths), (4) "when things block" section (deviations, escalations, who to ask). Manual: full lifecycle diagram with customer/internal branch split, glossary of statuses (reuse `STATUS_HINTS` wording), role table, FAQ. Plain language throughout — no internal jargon (RASIC explained where unavoidable).

- [ ] **Step 1: Write guides. Step 2: Verify every screenshot referenced exists and every UI label quoted matches the app (grep the source). Step 3: Commit** `docs(guides): per-department guides + user manual with visuals`.

---

## Self-review notes

- Spec coverage: P&L backend (T1–2), frontend (T3–4), nav isolation (T5), governance tabs (T6), visual status (T7), theme legacy (T8), escalations (T9), tests incl. Playwright (T10–11), guides with visuals (T12). Deadline fixes already shipped in path-to-quote — not re-planned.
- Loop contract: after T11's judgement pass, unresolved UX findings spawn a new iteration (fix tasks) before T12 starts — T12 is gated on "satisfied".
