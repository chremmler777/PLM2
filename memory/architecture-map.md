---
name: architecture-map
description: "PLM2 system map — backend models/routers/services, frontend pages/components, startup commands, database"
metadata: 
  node_type: memory
  type: project
  originSessionId: f12d046e-5979-4776-b412-d494bec95479
---

# PLM2 Architecture Map (as of 2026-06-09)

## Backend (FastAPI + SQLAlchemy async + aiosqlite, `backend/`)
- DB: `sqlite+aiosqlite:///./plm.db` (backend/plm.db; backend/app.db is stale). Alembic migrations 001–006 auto-run via run_backend.sh.
- Start: `./run_backend.sh` (activates miniconda, exports PYTHONPATH for pythonocc-core, alembic upgrade head, uvicorn :8000 --reload). Frontend: `cd frontend && npm run dev` (port 5174). Login: test@example.com / password (hardcoded in auth.py).
- Models (`app/models/`): entities.py (Organization, Plant, User, Project, CADFile legacy); part.py (Part w/ parent_part_id + active_revision_id, PartRevision w/ phase rfq_phase|engineering|freeze|ecn + status enum, RevisionFile, RevisionChangelog, PartFile legacy); workflow.py (Department, WfTemplate/WfStage/WfStep/WfStepRasic R|A|S|I|C, WfInstance/WfInstanceTask + legacy Workflow* models); article.py (BOM, BOMItem — article-based).
- Routers (`app/api/v1/`): parts.py (~1030 lines: CRUD + full revision lifecycle rfq/engineering/freeze/ecr + legacy part files), revision_files.py (revision-scoped files), bom.py, workflow_templates.py, workflow_instances.py, catalog_parts.py, plants.py, auth.py, articles.py (legacy), health.py.
- Services: part_service.py (PartService, RevisionService w/ create_rfq_revision/proposals/promote/freeze/ECR, ChangelogService.log_action), workflow_service.py, revision_service.py.
- `revision.status` compares as string value (e.g. `RevisionStatus.DRAFT.value`) — enum stored with values_callable, native_enum=False.
- STEP→glTF: `app/utils/cad_converter.py` — async wrapper spawns subprocess (segfault isolation); pythonocc-core → trimesh → placeholder GLB fallback chain.

## Frontend (Vite + React + TS + react-query + tailwind + R3F, `frontend/`)
- Routes (App.tsx): /login, /projects, /projects/:projectId, /workflows (WorkflowDesignerPage), /my-tasks, /catalog.
- ProjectDetailPage: part tree (parent_part_id hierarchy), revision-scoped file panel + Viewer3D, revisions list, AddPartModal w/ catalog selection, context menu (mostly stub actions: Revisions/Changelog/Start ECR/Create Next Revision — NOT wired yet).
- Viewer3D (react-three-fiber): props fileId | viewerUrl; solid/wireframe, grid, object tree, measurement, cut plane, camera auto-fit via bounding box. Model.tsx loads glTF.
- API client: `src/api/client.ts`, base includes /api; calls like `client.get('/v1/parts/...')`.

## Gotchas
- A claude-mem Read hook sometimes withholds file content ("Only line 1 was read") — fall back to Bash sed/cat for those files.
- `pkill -f uvicorn` patterns can kill your own Bash tool shell (exit 144) — run pkill in a separate call after git operations.
- sqlite3 CLI not installed; use `python -c "import sqlite3..."`.
- Several pre-existing tsc errors; don't treat as regressions.
