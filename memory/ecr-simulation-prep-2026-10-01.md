---
name: ecr-simulation-prep-2026-10-01
description: ECR KPI board, F-01..F-03 fixes, Process Flow page alignment, SIM test parts on prod and TOC-PLM-06 work instruction for the PM simulations (window 10/05-10/16/2026)
metadata:
  type: project
---

2026-10-01: prepared the Project Management ECR simulations (work instruction TOC-PLM-06 + findings log in docs/audit-plans, built by build/content_wi.py + make_findings_log.py).

- **ECR KPI board** /changes/kpis (commits 9ce766a5, 05947c79): RFQ on time (quoted_at vs required_by_date) and implementation on time (released_at vs release_due_date), by calendar day; per-org targets in org_settings `ecr_kpi_target_rfq` / `ecr_kpi_target_implementation` (default 90 %), admins edit inline.
- **Fixes** 18ac06f2: F-01 costing tab + Close-costing warning read `costing_pending_department_ids`; F-02 moving an existing release deadline needs `release_due_reason` (backend + DeadlineEditor "Move"); F-03 `put_gate` uses `holds_lead`, D1 tab read-only while acting.
- **Process Flow page** aligned with the code in two rounds (5b641999: M1-M18; 428bbe80: 18 more statements a review found, incl. who decides what, Timing validated is a hard gate, no cancel after release). docs/CHANGE_MANAGEMENT_FLOW.md aligned too (f5cf300e).
- **Review follow-ups**: 51a0aba9 (gate prompt holds_lead, costing wait list refresh), e369acc3 (transition deviation decider uses holds_lead, Your actions refresh). 0c5234f2 (NEXT_STATUS as reachability table) was WRONG and reverted (2c149ae3): CockpitSummary reads NEXT_STATUS via nextStatusesFor for next-step buttons and blocking gates; it is a forward next-step table, not a mirror of ALLOWED_TRANSITIONS.
- **Prod data**: `backend/scripts/seed_sim_test_project.py --apply` ran on prod 2026-10-01 (backup `db-backups/plm2-before-sim-seed-20261001-183336.sql.gz`): test-project moved to plant usa-toccoa, 13 SIM items (tools 9901-9904, 20-99xx articles, assemblies 10-9901-001-0/-002-0). No project PM on Test Project on purpose: no real user is a department member on prod, so a responsible cannot be set without adding a membership.
- **Local walk**: a full customer change ran capture -> closed on the SIM parts locally (CR-2026-0009 local). Learned: priority only by the lead (acting drops it); ECN check workflow has 4 stages per item, stage 1 needs 3D evidence (CAD or "No geometry change"), stage 2 Design review four-eyes vs stage 1.
- **F-04 done** (6e0a9170): internal changes can be started from the form (user: "why don't you fix those issues first"); walked an internal change end to end locally first (CR-2026-0010 local).
- **F-06 done** (7396e9b5 + fe7027b1, live on prod): ECN check stage 3 now R Process Engineer / A Tool Engineer for "Implement tool change" and R Scheduling / A PM for "Update master data & logistics", following the role remap in CHANGE_MANAGEMENT_FLOW.md (Production -> Process Engineer, Logistics stock/flow -> Scheduling). `scripts/fix_ecn_retired_departments.py` (target-state, idempotent) applied on prod templates 117/118 (in use) + 120/121 (unused duplicates), v3 with history rows; backups plm2-before-f06*-20261001.
- **Lesson**: when replacing retired roles, check CHANGE_MANAGEMENT_FLOW.md's role remap first (the first F-06 pick ignored it and had to be redone).
- **Deployed 2026-10-02** `8652502c` (pushed to origin/main, prod rebuilt, alembic 110 unchanged, backup plm2-before-8652502c-20261002-120831). KPI board leaves out project code test-project (ECR_KPI_EXCLUDED_PROJECT_CODES).
- **2026-10-02 WI changes**: KPI board leaves out Test Project, so the WI no longer tells PMs to check SIM changes on it (A13/A28/C1/C8 expectations and the KPI screenshot removed). Training manual reference removed from the WI at the user's request ("want document"): the WI is the only reference for the simulations; the in-app Training page stays in the sidebar (user: leave it). WI now 12 pages. Documents (not in git, docs/audit-plans is untracked): pdf/TOC-PLM-06 Work Instruction ECR Simulation.pdf, TOC-PLM-06 ECR Simulation Findings Log.xlsx, .docx; to be copied to SharePoint by the user.

**Why:** user asked PMs to simulate ECRs and report bugs before the 12/21/2026 go-live.
**How to apply:** after the review on 10/20/2026, findings come back in the xlsx (F-01..F-06 already Done). Related: [[audit-implementation-plans-2026-09-30]], [[project-team-responsibles-2026-09-25]], [[prod-data-is-truth]].
