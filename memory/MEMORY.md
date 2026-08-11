# PLM2 Project Memory

- [ECR buildout 2026-08-11](ecr-buildout-2026-08-11.md) — READ FIRST for change-flow work: full ECR rework shipped (deadlines, capture→costing, risk register, acts-as); flow truth lives in docs/CHANGE_MANAGEMENT_FLOW.md; open items + operational lessons listed

- [Phase 5 status & expansion roadmap](phase5-status.md) — revision-based files DONE (Jun 2026); next: ECR UI, BOM editing, viewer RevisionTree
- [Architecture map](architecture-map.md) — models, routers, services, frontend pages, startup, DB
- [Working agreements](working-agreements.md) — autonomous /loop build style, commit conventions, test approach; LEAN MODE since Aug 11: no spec/plan ceremony for small features, one batched full-suite run, Opus subagents execute while supervisor designs/commits
- [Change Management roadmap](change-management-roadmap.md) — 7 sub-project decomposition; #1 spine + #2 RASIC routing BUILT; Jul 2: full-lifecycle IATF/VDA goal approved (spec 2026-07-02-ecm-lifecycle-design.md, phases A–D, hard gates supersede soft guards)
- [PLM as master datasource](plm-master-datasource.md) — goal: PLM2 = source of truth for tooling/projects; first import VW426 "Atlas" from TWOS (blocked: data not in workspace, user must provide export)
- [ECM Phase E kickoff](ecm-phase-e-kickoff.md) — Phases A–D DONE (branch at 39bca80f, merge-ready); Phase E scope agreed Jul 2: real workflow model (dept memberships+enforcement, engineering decides affected items, EN seed names, USA plant default) — brainstorm next
- [Model tiering preference](model-tiering-preference.md) — lower-tier models for subagents when no quality concern
- [P&L + usability iteration](pnl-usability-2026-07-07.md) — branch feature/pnl-and-usability DONE Jul 7 (P&L module, governance isolation, escalation fixes, guides); open governance decisions for user
- [Governance policy](governance-policy.md) — who can sign off / quote / approve internal costs (decided Jul 8; pragmatic internal approval, backend+UI enforced)
- [Data seeding post-rollout](data-seeding-post-rollout.md) — NEXT: wipe test changes, import WinCarat (via TWOS FA / KPI board instructions), seed G65 part-history sheets as auto-created changes + department backfeed tasklist
- [Change-flow rework 2026-07-23](change-flow-rework-2026-07-23.md) — on `main`: audit prose, attachments (drop-zone+phase-freeze), deadline gate, scoping channel, Outlook attendee autofill (chips+Enter/Tab), dept rename (Tooling/Manufacturing Engineer), technical-assessment routing. Role matrix to encode from assessment stage on; CR-2026-0002 in scoping
- [Assessment impact-lock gate](assessment-impact-lock-2026-07-24.md) — `-> in_assessment` hard-gated on a locked impacted set (unbypassable by deviation, evaluated after soft guards); `in_assessment -> scoping` recall with routing teardown; CR-2026-0002 recalled to scoping
- [Equipment numbering + gauge inventory](equipment-numbering-2026-07-24.md) — `<tool#>-<op code>` scheme live (153 gauges, 14 equipment, 175 serves); process-flow view shipped; NEXT: impacted-parts picker visualisation + equipment-usage visualisation (skip the 926/3431-3439 tools and the material/process picker)
- [Live DB is Postgres, not plm.db](live-db-is-postgres-2026-08-06.md) — running app = docker `claude-plm2-backend-1` on Postgres; `main.py` auto-runs alembic on every `--reload` restart, so draft migration files get applied within seconds (never leave one on disk)
- [Part-number families](part-number-families-2026-08-06.md) — 40 = resin/material, 65 = returnables/dunnage (a code comment had these backwards); taxonomy now in `frontend/src/lib/itemCategory.ts`
