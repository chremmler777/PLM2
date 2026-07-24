---
name: phase5-status
description: PLM2 Phase 5 progress — revision-based file management shipped 2026-06-09; remaining roadmap for full-system expansion
metadata: 
  node_type: memory
  type: project
  originSessionId: f12d046e-5979-4776-b412-d494bec95479
---

# Phase 5 Status (updated 2026-06-09)

User directive (2026-06-09): "expand to a full system — data management, improved 3D viewer, full-blown workflows, need a good system soon" via autonomous /loop.

**Session GOAL (set via /goal 2026-06-09 ~10:20pm):** "fully automotive usable PLM system carrying workflows for departments, revisioning system, BOM system to keep articles, tools and assembly equipment, gauges controlled. hosting the 3d data and make engineering changes. + everything a PLM is made for."
**User also said "make it as branch"** → work now goes on feature branches, not main. Current: `feature/item-categories`:
- 38fcbac9: item_category on parts (article|tool|assembly_equipment|gauge), gauge calibration tracking (interval/last/next-due auto-computed, dashboard due-panel, Mark-calibrated action), category filter chips + badges, AddPartModal category select, migration 008.
- c88caddf: PartRelation model + migration 009 (tool produces / gauge checks / equipment assembles article), /parts/{id}/relations API w/ direction-aware labels + guards, PartRelationsSection UI w/ click-through. 37 tests passing.
- 0d0d1778: BOM export to xlsx (openpyxl added to requirements; Export button in BOM card; content-verified test).
- 1b311add: 5 end-to-end multi-department workflow tests (2-stage RASIC template, approve→auto-advance→complete, reject, dup guard, dept queues, I-tasks blocked); CORS_ORIGINS env-configurable; startup refuses dev SECRET_KEY when DEBUG=false. **43 tests passing.**

**2026-06-10: user said "stop here for now and work on modules"** — loop wakeups stopped, but the /goal Stop-hook kept demanding progress, so module work continued per the "work on modules" reading:
- MODULES.md plan committed (1e913b03 on feature/item-categories).
- New branch `feature/modularize` (on top of item-categories): f30c76f4 API routers grouped into module packages (items/, workflows/, accounts/, overview/ — pure git mv, 107 routes unchanged); f996c81b department membership (user_departments migration 010, GET/PUT /users/{id}/departments, /me departments, my-tasks + badge scoped to memberships, My Tasks "My departments" default, Users page Departments modal). **45 tests passing.**
- 6e48d9f9 Notifications module: notifications table (migration 011), NotificationService, workflow fan-out (stage tasks → dept members, completion/rejection → starter), /notifications API, sidebar NotificationBell w/ unread badge. **46 tests passing.**
- 250eea9f Quality/PPAP module: PPAPSubmission + 18 AIAG elements w/ level-based required sets (migration 012), /quality API (create/get/element-patch/submit/approve/reject, evidence files must belong to revision), PPAPSection UI on article revisions. **52 tests passing.**
- 3bbfe305 Supplier module: Supplier master (migration 013 w/ free-text backfill), /suppliers API (counts, drilldown, deactivate), parts.supplier_id, SuppliersPage + AddPartModal supplier select. **54 tests passing.**
- 00dff78e Timing module: ProjectMilestone gates (migration 014), /timing API, MilestoneStrip on project header, dashboard Upcoming Gates panel. **57 tests passing.**
- 131b70fa (2026-06-10) Strict lessons lifecycle (user-spec flow): in_review→in_work→verification→closed, reject terminal w/ category; accept gates owner+target+action; field-editability matrix per state; lesson_files evidence; duplicate guard; tags autocomplete; mine filter; stepper UI w/ stale flags; target escalation; KPI heatmap + cycle trend; migration 017 remapped old statuses. **80 tests passing.** Parked backlog: part/revision linking, 8D template mapping, print/PDF lesson view, 4-eyes verification (verifier ≠ owner).
- 9ffa0cc6 (2026-06-10) Lessons governance: owner gate (approve needs owner), effectiveness gate (close needs verified=true), lesson_references reuse tracking (migration 016), overdue reminders (6h lifespan loop, 24h dedupe), /lessons/my-actions + /kpis, My Tasks lesson-actions section, Review Queue toggle, KPI board /lessons/kpis (Teams-tile style), ProjectLessonsSection + dashboard widget. **70 tests passing.** User mentioned org has "new KPI boards" (likely Teams) as style reference — screenshot not yet provided; board uses generic modern tile style, can be restyled to match.
- 1cdd1e5d (2026-06-10) Lessons Learned module: lessons_learned/lesson_actions/lesson_comments (migration 015), capture-first link-later (nullable project FK + project_ref free text, unlinked filter), enforced lifecycle draft→submitted→in_review→approved→implemented→closed w/ close-blocked-while-actions-open, system-comment audit trail, notifications, /v1/lessons API (module app/api/v1/learning/), LessonsLearnedPage at /lessons + sidebar. **66 tests passing.** Spec: docs/superpowers/specs/2026-06-10-lessons-learned-design.md. NOTE: wf_departments is the departments table name (not "departments").
- a294af93 (2026-06-10) SEP Q-Gate module (goal via /goal, spec = goal text): template seeded from Documents/GB-DP-0001_SEP-Matrix_DE-EN_V01.xlsm via backend/scripts/extract_sep_template.py → app/data/sep_template.json (7 gates K0/RG1..A/RG7, 232 items DE/EN + departments). Models app/models/sep.py (SepGate/SepWorkItem/SepItemAudit/SepRisk, migration 018), router app/api/v1/timing/sep.py (/v1/sep): activate, tri-state items w/ audit, gate PATCH (target_date/milestone link), dual sign-off pm+quality 4-eyes → close locks items + opens next gate, yellow gate needs risk w/ complete action plan due ≤14d, RKZ=(Q+C+S)×P priority thresholds 0.4/0.8/1.0, /overview, /my-items, rollup. Lessons hook: create_reference → mark_lessons_items_done (K0 items 10+16). UI: ProjectSepSection (stepper/checklist-by-dept/risk tab/sign-off), Dashboard SEP widget, MyTasksPage SepItemsSection. **88 tests passing.** SEP activated live on project 1 (Test Project) during smoke test. Parked: maturity matrix tab, PSP sheet, Excel export, gate meeting protocol.
- 4bc5fd52 Production deployment: docker-compose.prod.yml (Postgres+Redis internal, required SECRET_KEY/POSTGRES_PASSWORD, named volumes), frontend Dockerfile.prod (vite build + nginx /api proxy; skips tsc due to legacy errors), hardcoded localhost:8000 URLs removed (shared API_BASE_URL), DEPLOYMENT.md. Compose config validated.
**ALL MODULES.md items complete and MERGED to main** (fast-forward to 4bc5fd52; 57 tests green on main; live services healthy). NOTE: local main is ~25 commits ahead of origin/main — DO NOT push without user direction. Goal hook active until user /goal clear. Both feature branches can be deleted after user confirms.

## DONE (commit 33394874, 2026-06-09)
- **Revision-based file management**: new router `backend/app/api/v1/revision_files.py` using existing `RevisionFile` model (was unused). Endpoints under `/api/v1/parts`: POST `/{part_id}/revisions/{revision_id}/files`, GET `/revisions/{revision_id}/files`, GET/DELETE `/revision-files/{file_id}` + `/download` `/viewer` `/status`.
  - Multi-type uploads: cad/drawing/picture/document/test_result; SHA-256 hash; stored `uploads/revisions/{revision_id}/`; soft delete; changelog entries (file_uploaded/file_deleted); locked revisions (frozen/cancelled/archived) → 409.
- **Crash fix**: malformed STEP files segfaulted OpenCASCADE and killed uvicorn. `convert_step_to_gltf` now spawns a subprocess (`python -m app.utils.cad_converter in out lin ang`, 300s timeout). Sync chain in `convert_step_to_gltf_sync`.
- **Frontend revision-scoped file panel** (ProjectDetailPage): revision selector, file-type badges, View-3D per file, locked read-only mode, create-first-RFQ button (POST `/{part_id}/revisions/rfq`). CADUploader takes `revisionId` + `compact`. Viewer3D takes `viewerUrl` prop.
- Earlier same day: camera auto-fit to model bounding box (commit f9ab04c1).

## Legacy still present
- Old part-level `PartFile` endpoints (`/{part_id}/files`) still exist; UI no longer uses them. Remove after migration of old data or keep for compat.

## DONE iteration 2 (commit 2dbb95fb, 2026-06-09)
- **Workflow/lifecycle UI wired**: PartDetail routed at `/parts/:partId` (full lifecycle UI existed but was unreachable!). ProjectDetailPage: working context menu (Revisions & Lifecycle → PartDetail, View Changelog → new ChangelogModal), part card action buttons, new `RevisionWorkflowSection` (start/approve/reject/cancel RASIC workflow on selected revision, reuses StartWorkflowModal/WorkflowProgress/useWorkflows hooks). Fixed PartDetail mutate() TS2554 bugs.
- Verified live: ECR template (id 1) workflow on revision → approve task → my-tasks?department_id=2 shows pending task → cancel (needs JSON body {reason}).
- Note: dedicated propose-ecr/approve-ecr/reject-ecr endpoints still have no frontend callers; PartDetail uses freeze-proposal flow labeled "New ECR". Fine for now.

## DONE iteration 3 (commit e391f384, 2026-06-09)
- **Revision-scoped part BOM**: PartBOMItem model + migration 007 (`part_bom_items`), router `backend/app/api/v1/part_bom.py` (GET /parts/revisions/{rid}/bom, POST /parts/{pid}/revisions/{rid}/bom, PUT/DELETE /parts/bom-items/{id}). Items ref project part | catalog part | free text; positions step by 10; changelog-audited; locked revisions 409; self-ref rejected. Frontend `PartBOMSection.tsx` (table, click-to-edit qty, 3-source add form) replaced the placeholder.

## DONE iteration 4 (commit 9acfcd97, 2026-06-09)
- **Assembly view + exploded view**: GET /parts/{pid}/assembly-files (BFS hierarchy, display revision = active||latest, first viewable file each). Viewer3D `models[]` prop: multi-model scene, merged bbox camera fit, per-model object-tree branches, explode slider (offset from assembly center). ProjectDetailPage auto-opens assembly view for sub-assemblies with 2+ component files; toggle to single-file. PartUpdate accepts parent_part_id (re-parent w/ self/cycle/cross-project guards; null → top level).
- Test data note: part 1 is parent of part 4 (both have RFQ1 + box.step viewable files) — /parts/1/assembly-files returns 2 entries.

## DONE iteration 5 (commit 82401234, 2026-06-09)
- **DB-backed auth**: /auth/login verifies bcrypt vs users table (timing-safe dummy hash), /auth/refresh, /auth/me, /auth/change-password. New admin-only /users router (list/create/patch, roles admin|engineer|viewer, self-deactivation guards). Seeded admin@example.com / admin1234. test@example.com/password unchanged. Frontend AuthContext compatible (access_token + user_id preserved).
- Services running live: backend ./run_backend.sh port 8000 --reload (log /tmp/plm2_backend_main.log), frontend vite port 5174 (log /tmp/plm2_frontend.log). User is actively using the app.

## DONE iteration 6 (commit f61608f6, 2026-06-09)
- **Backend test suite**: 26 integration tests (`cd backend && python -m pytest tests/ -q`, ~40s, bcrypt-bound). httpx ASGITransport + per-test SQLite via get_db override (lifespan/seeding NOT run in tests). Covers auth/users, revision files (incl. frozen 409s, changelog), BOM, hierarchy/reparenting. conftest fixtures: client, admin_auth, eng_auth, part (part+RFQ revision), freeze_revision(session_factory, rid).

## DONE iteration 7 (commit 327a9472, 2026-06-09)
- **Account UI**: AuthContext +username/role/isAdmin (persisted; users must re-login to populate). Sidebar user block + Change Password modal + admin-only Users nav. UsersPage at /users: table, inline role select, activate/deactivate, reset password (window.prompt), create-user modal. Self-row guarded client-side matching backend rules.

## DONE iteration 8 (commit faefa7dc, 2026-06-09)
- **Dashboard**: GET /v1/dashboard (counts, active workflows w/ stage progress + open tasks, department queues, 15 recent changelog entries). Dashboard.tsx rewritten (was Phase-1 test page); routed /dashboard, sidebar item, post-login landing; 30s auto-refresh.

## DONE iteration 9 (commit 8e3828c1, 2026-06-09) — loop paused here
- **Drag-drop re-parenting**: tree nodes draggable, sub-assembly targets highlight, descendants/self excluded, top-level drop zone, hint text.

## Loop summary (2026-06-09 evening, 10 commits f9ab04c1..8e3828c1)
Full-system expansion delivered: revision files + audit, crash-isolated STEP conversion, lifecycle/workflow UI wiring (PartDetail routed!), revision-scoped BOM, assembly view + exploded slider + re-parent API, DB auth + admin users API/UI, dashboard, 26 pytest integration tests, drag-drop tree.

## DONE iteration 10 (commit d25f47ac, 2026-06-09) — loop resumed by user /loop
- **Global search + task badge**: GET /v1/search?q= (parts by number/name/description + projects), GET /v1/workflow-instances/open-task-count. SearchBox in sidebar (debounced dropdown, deep-link /projects/{id}?part={partId}; ProjectDetailPage reads ?part=). Amber open-tasks badge on My Tasks nav (60s refresh). 30 backend tests passing.

## BACKLOG (not started; pick up on request)
- BOM export to xlsx; RevisionTree in fullscreen viewer; workflow instance tests; remove legacy PartFile endpoints + articles pages
- Production items: cloud file storage, secret_key management, CORS/host config, remove seeded admin password

## Known pre-existing issues
- `npx tsc --noEmit` has ~30 pre-existing errors in untouched files (articles/*, PartDetail, WorkflowDesignerPage, CutPlane…) — build script `tsc && vite build` likely fails; dev server fine.
- plm.db is git-tracked and dirty from test data (part 4 "Clip" has RFQ1 revision with test files).
