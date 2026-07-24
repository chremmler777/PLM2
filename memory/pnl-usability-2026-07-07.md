---
name: pnl-usability-2026-07-07
description: "P&L module + usability iteration — branch feature/pnl-and-usability, built+tested+documented Jul 7 2026; open governance decisions"
metadata:
  type: project
---

# P&L module + usability iteration (Jul 7 2026)

Branch `feature/pnl-and-usability` (off feature/change-assessment-routing at 9d511ad0), ~20 commits, UNMERGED/UNPUSHED. Spec `docs/superpowers/specs/2026-07-07-pnl-module-and-usability-design.md`, plan `docs/superpowers/plans/2026-07-07-pnl-module-and-usability.md`.

**Built:** P&L module (PnlService computed-on-read, `/api/v1/pnl/{changes,summary}`, `/pnl` page 💰, PnlCard in cockpit commercial tab; revenue = quoted_price customer / internal_approved_amount internal — internal margin labeled "vs. approved budget", never "profit"). Usability: sidebar Daily/SETUP groups (Setup admin+engineer only), governance tabs (D1/Audit) role-gated group in cockpit, branch-aware LifecycleStepper + STATUS_HINTS + n/m progress chips in list, dark-slate conversions. Escalations: notification sweep now covers unclaimed overdue assessments AND unclaimed overdue change-scoped WfInstanceTasks → change lead (dedup `...:overdue:lead`). Datetime: `NaiveUtcDatetime` (app/schemas/common.py) normalizes tz-aware input datetimes — fixed asyncpg 500 on meeting creation in the docker Postgres stack. Walkthrough UX wave: customer_relevant asked at capture + editable in overview (captured/scoping only, also guarded server-side), quoted-price inline editor, commercial empty-state explainers, 4-eyes sign-off hint, scoping→assessment mapping hint, capture-modal missing-fields hint.

**Docs:** `docs/guides/` — manual + 6 department guides (initiator, project-management, technical-departments, sales, quality, management-pnl) with mermaid diagrams + 17 real screenshots (img/), labels verified against source.

**Verified:** backend 340+ pytest, frontend 132 vitest, tsc 0, eslint clean on touched files (75 pre-existing repo-wide lint errors in untouched files). Live Playwright walkthrough both branches e2e on the docker Postgres stack (localhost:8000/5173 = claude-plm2-* containers, repo bind-mounted, NOT a host uvicorn). Final whole-branch review READY WITH FIXES → fix wave applied.

**OPEN FOR USER (governance policy, not code defaults):** (1) sign-off authz breadth — any engineer can quality-sign without Quality membership; (2) quoted-price entry has no role gate; (3) lead alone can scope+proceed+approve internal costs (no 4-eyes on internal branch). Backlog: P&L date-range/plant UI filters, branchStepOrder null-flag semantics for legacy rows, i18n STATUS_HINTS, remaining gray→slate in overview tab, sweep owner-query instance-status filter.
