---
name: project-team-responsibles-2026-09-25
description: Per-project team - one responsible per role leads that role's tasks, the rest of the department is backup (sees/acts, not counted); project PM = default change lead
metadata:
  type: project
---

User decision 2026-09-25: every project has a team with one responsible per role (Project Manager, Sales, Development, Tool Engineer, Manufacturing/Process Engineer, APQP, Packaging, Scheduling, Quality, Finance). The responsible "leads each task" of that role on the project's changes: counts on their counter/My Tasks, gets notifications. Others in the department are backup: they see the task and can work it, but it does not count toward their tasks, with a visual marker that they are not the main. No responsible set = department-wide as before. "Project PM is standard PM": the Project Manager responsible is the default change lead.

**Why:** clear ownership per project without locking out colleagues who cover.

**How to apply:** spec §18 in docs/superpowers/specs/2026-09-25-ecr-costing-to-close.md (branch feature/ecr-costing-to-close), table project_responsibles (migration 097). Any new per-department task type must respect main/backup counting. Related: [[ecr-costing-to-close-2026-09-25]].

## Team assignments given by the user (2026-09-25)
Projects 1994 (Brose Seat Trim), 2277 (Brose Backpanel), 1864 (VW426 Atlas):
- Project Manager: Cody (cody.hrtyanski)
- Manufacturing Engineer: Russ
- Tool Engineer: Dale (dale.perry on prod)
- APQP: VW426 (1864) = Apurva M. ("apurvam"); 1994 and 2277 = George
- Development: the user, Christoph Demmler (christoph.demmler; note two local accounts ids 14 and 20 share this name on some DBs, pick the real hub one)
Only cody.hrtyanski exists in the local test DB; users are created on first hub login, so the others must be matched on prod (by name/email) when the team is prefilled at deploy. Prefill only on the user's "deploy" go.

## Rights model decision (2026-09-25)
The hub only has plm2_Admin and plm2_Viewer, so every PLM editor is a full admin; department/project-team rights only apply to non-admins or when acting as a department. User decided: **keep admin for now** at rollout; revisit later (options discussed: a plm2_Engineer hub role mapped to PLM's engineer role, or a PLM-side admin list). Counting (main/backup) and lead defaults still work for admins; rights restrictions do not.
