# PLM2 — Module Plan

Drafted 2026-06-10 after "stop here for now and work on modules". This is a
proposal to react to, not implemented work.

## Modules that exist today (and where they live)

| Module | Backend | Frontend | State |
|---|---|---|---|
| **Items & Revisions** | `api/v1/parts.py`, `part_service.py`, `revision_naming.py` | ProjectDetailPage, PartDetail, RevisionTimeline | Complete: customer data index (`E<n>` review / `<n>` official, minors are ours), part lifecycle phase rfq→nominated→series, categories, calibration, customer package receive, chosen major number, customer index shown next to every revision name. See `docs/CUSTOMER_DATA_INDEX.md` |
| **Files & 3D** | `revision_files.py`, `cad_converter.py` | Viewer3D, CADUploader | Complete: revision-scoped, STEP→glTF (crash-isolated), assembly + exploded view |
| **BOM** | `part_bom.py`, `bom_tree_service.py` | PartBOMSection, BomTree, AssemblyTreeList | Complete: revision-owned, copied forward on new majors/proposals, multi-level tree, where-used, project Assemblies view, xlsx export |
| **Item Relations** | `part_relations.py` | PartRelationsSection | Complete: produces/checks/assembles |
| **Workflows** | `workflow_templates.py`, `workflow_instances.py`, `workflow_service.py` | WorkflowDesignerPage, MyTasksPage, RevisionWorkflowSection | Complete: RASIC multi-dept chains, e2e tested |
| **Auth & Users** | `auth.py`, `users.py` | UsersPage, ChangePasswordModal | Complete: DB login, roles, admin UI |
| **Overview** | `dashboard.py`, `search.py` | Dashboard, SearchBox | Complete: stats, queues, calibration warnings, global search |
| **Paint** | `models/paint.py`, `services/paint_service.py`, `api/v1/paints.py`, `api/v1/items/part_paint.py` | PaintsPage, PartPaintCard, ProjectPaintSection | Complete: engineering data only (no cost), part-level (not revision-bound). Paint catalog is org-scoped master data; a part's paint setup is ordered layers with process and notes. See `docs/PAINT.md` |

## Candidate next modules (automotive PLM)

1. **Quality / PPAP** — inspection plans per revision, PPAP document checklist
   (PSW, control plan, FMEA, MSA), submission levels, customer sign-off
   workflow. Builds directly on revision files + workflows.
2. **Supplier Management** — supplier master data (beyond the free-text
   `supplier` field), supplier ↔ catalog-part links, supplier portal-ready
   API (RFQ packages from revision files).
3. **Project / Timing** — milestones (SOP, design freeze dates) per project,
   gate status derived from revision phases, overdue gates on dashboard.
4. **Notifications** — in-app notification center fed by changelog +
   workflow events (task assigned, revision approved, calibration due);
   later email via the existing SMTP settings.
5. **Production hardening module-cut** — Docker compose (Dockerfile exists),
   PostgreSQL migration path, cloud/object file storage behind a storage
   interface, secrets via env (startup guard already added).

## Code modularization (optional refactor)

Current layout is flat (`api/v1/*.py`, one big `part_service.py`). If the
codebase should mirror modules:

```
backend/app/modules/
  items/        (models, service, router: parts, revisions, categories, relations)
  files3d/      (revision files, converter)
  bom/
  workflows/
  accounts/     (auth, users)
  overview/     (dashboard, search)
```

Mechanical move with import updates; ~1 session of careful refactoring, no
behavior change, tests stay green. Recommended only if new modules (Quality,
Supplier) are coming, so they land in a clean structure.

## Open decisions

- Merge `feature/item-categories` into `main`? (tested: 43 passing)
- Which module first: Quality/PPAP is the most "automotive" gap; Notifications
  is the cheapest win; code modularization should precede big new modules.
