---
name: change-management-roadmap
description: "Change Management module — 7 sub-project decomposition, design decisions, and current build status"
metadata: 
  node_type: memory
  type: project
  originSessionId: ea770147-f5f3-48d9-b1aa-0dfe0b55c74d
---

Change Management (ECR/ECN/ECO) module for PLM2, started Jun 15 2026 on branch `feature/change-management`. Full design spec: `docs/superpowers/specs/2026-06-15-change-management-core-design.md`.

**Decomposition (7 sub-projects, each its own spec→plan→build):**
1. Change Request core + lifecycle ("the spine") — BUILT (Jun 15 2026) on feature/change-management; backend 102 tests pass, frontend type-clean. Plan: docs/superpowers/plans/2026-06-15-change-management-core.md
2. Cross-functional assessment auto-routing via RASIC workflow engine — BUILT (Jun 16 2026) on branch `feature/change-assessment-routing` (off the spine; 17 commits, full suite 115 passing). Staged RASIC routing read from flow-designer WfTemplate via ChangeRoutingStandard (change_type→template), TYPE_DISCIPLINES fallback; R/A blocking, C/S optional, I notify-only; per-change ChangeRouting snapshot; staged advancement + notifications; governed deviations (no self-approval) that promote to a new ECR WfTemplate version on release. Spec: docs/superpowers/specs/2026-06-15-change-assessment-routing-design.md; plan: docs/superpowers/plans/2026-06-15-change-assessment-routing.md. NOT merged. Known deferrals: deviation add/remove UI (only approve surfaced), admin-authz on /routing-standards, per-project member resolution, dept-name labels in UI.
3. Commercial layer — costs, offers/quotes, P&L-if-implemented (Sales)
4. Impact scope automation + engineering-level marking
5. 3D data storage + diff colormap overlay in viewer (new; viewer exists, no diff yet)
6. Sampling/validation (PPAP) + release automation
7. Timing proposal + tracking (milestones)

**Locked decisions for #1:** one ChangeRequest object, phased (no ECR/ECO split); one lifecycle, `change_type` drives routing; per-discipline structured assessments (verdict + cost/time); decision gate = customer acceptance + dual sign-off (PM+Quality) — the one HARD guard; Change spawns & owns ECN PartRevisions, release activates/supersedes + stamps eng level; hash-chained audit reusing RevisionChangelog pattern.

**Branch/app state (Jun 15 2026):** all work is on branch `feature/change-management` (26 commits). PUSHED to origin; open PR #1 → main (https://github.com/chremmler777/PLM2/pull/1), awaiting review/merge. Branch kept alive for PR iteration. Backend full suite 102 passing; frontend type-clean for change files. App was last run via `run_backend.sh` (uvicorn :8000) + `npm run dev` (vite :5173). Note: standalone ChangesPage/ChangeDetailPage use a light Tailwind theme while the rest of the app is dark-slate — a polish-consistency follow-up. Also known: My Tasks only surfaces assessment tasks (not sign-off tasks); ChangesPage has only a status filter.

**Flexibility principle (key user constraint):** ECRs often start with only a PPT and a sentence. Minimal start allowed (title+reason only), `ChangeAttachment` model for informal docs (PPT/PDF/email), soft guards the lead can override with logged justification — except the approve gate which is hard.

Reuses existing engine: WfDepartments (Tool Eng, APQP, Quality, PM, Sales, ME, Packaging, Process), PartRelation for impact seeding, PPAP, milestones, Notification. Adds `eoat` to parts.item_category. See [[architecture-map]] and [[phase5-status]].

**Full-lifecycle goal (Jul 2 2026, supersedes parts of the above):** spec `docs/superpowers/specs/2026-07-02-ecm-lifecycle-design.md` (committed on feature/change-assessment-routing). IATF 16949/VDA alignment. Key decisions: check-workflow WfInstances drive ECN-revision execution and "ready to go" is COMPUTED (all impacted revisions' WFs complete incl. per-revision 3D evidence: updated CAD file or owner-signed no-geometry-change flag); impact tree = explicit pick + suggested parent roll-ups; **hard gates + 4-eyes deviation objects replace the soft justification-override pattern** (revises the earlier "soft guards" flexibility decision — minimal-start capture stays, but transitions/gates are no longer free-text bypassable); dept routing + named owner + due dates + escalation; unified AuditLog (correlation_id per change) finally gets written; UI = change cockpit + impact tree + audit timeline + app-wide dark-slate cleanup + legacy Article stack retirement. Phasing A (gates/deviation/audit) → B (tree→ECN→WF→ready-to-go) → C (ownership/due dates) → D (cockpit UI/theme). Execution style: model-tiered agents (haiku mechanical / sonnet standard / opus design-critical + reviews), TDD everything, existing tests stay green (migration seeds gate rows for in-flight changes).

**Phase B NEXT (scouted Jul 2 2026):** exploration facts + user directives persisted in `.superpowers/sdd/phase-b-exploration.md` — READ THAT FIRST when planning Phase B (part/revision/WfInstance/RevisionFile field-level facts, 9 named gaps, context-first initiation directive incl. spec section 0, dark-slate theming rule). Next step: write Phase B plan via superpowers:writing-plans, then subagent-driven execution (sonnet default / opus design-critical / haiku fixes).

**Phase A BUILT (Jul 2 2026):** commits 1b60edfd..81a5360d on feature/change-assessment-routing (not pushed). Hash-chained AuditService (correlation_id per change, full-row hash envelope incl. correlation_id/log_level) + /api/v1/audit list/verify/export; ChangeTransitionDeviation 4-eyes objects (second signature must be engineer/admin, never proposer, never viewer) replace justification override entirely; gates seeded na at creation + migration 022 seeds in-flight; gate decide = lead/admin only; frontend DeviationBanner + ReasonDialog replace window.prompt. Backend 142 tests, frontend 31, e2e smoke 10/10 + UI banner verified. Final opus review: ready to merge. Deferred minors in .superpowers/sdd/progress.md (Phase B: unique(change_id,gate_key) constraint, migration test for in-flight seeding; Phase D: proposer sees approve buttons, config-plane audit for routing-standards, project-membership scoping). UX hard requirement added to spec: "the UI drives the task" — blocked states must name reason + offer resolving action in place.
