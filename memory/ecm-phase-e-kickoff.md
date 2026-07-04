# ECM Phase E — "Make it a real workflow" (kickoff notes, 2026-07-02)

Status: MERGED into Phase E spec + plan on 2026-07-03 (docs/superpowers/specs/2026-07-03-ecm-phase-e-design.md Stream 5; plan Tasks 17-23). This file is historical.
Next step: superpowers brainstorming → spec → writing-plans → SDD execution (same cycle as Phases A–D).

## Where Phases A–D ended
- All complete + final opus review READY TO MERGE. Branch `feature/change-assessment-routing` at `39bca80f` (unpushed). Backend 189 / frontend 55 tests green, tsc baseline 21, migrations head 026.
- Real dev stack = docker-compose `claude-plm2-*` (backend :8000 bind-mount + --reload, frontend :5173, **Postgres** `claude-plm2-db-1` — NOT the local sqlite plm.db). Postgres migrated to 026; physical_part routing standard repointed to ECM Bewertung.
- Full ledger: `.superpowers/sdd/progress.md` (incl. deferred-to-Phase-E triage list from the final review).

## User feedback driving Phase E (2026-07-02 evening)
- "It's one PM page — we wanted a workflow model, so everyone gets tasks." Correct: `submit_assessment` has NO department-membership check (any user can submit any dept's verdict — Phase B deferred item), and there is NO API/UI to assign users to departments (`user_departments` only writable in tests), so My Tasks is structurally empty.
- **DECISION: Engineering (R&D) makes the decision on what is affected** — impact selection/confirmation becomes an engineering responsibility (today the change lead picks impacted items). Lead may propose; engineering judges/confirms. Design the exact mechanism in brainstorm (e.g. impact-assessment task for R&D before/at in_assessment).
- Department assignment UX: user asked "test dropdown?" and said *make it handy/easy, you probably have better ideas*. Recommended: Users-page multi-select departments dropdown (admin assigns) + seeded dev memberships so tasks flow immediately in their stack.
- **Keep UI English for now**: seeded template/stage/step names are German ("ECM Bewertung", "Machbarkeit & Bewertung", "3D-Daten aktualisieren", …) and leak into the EN UI → rename in wf_seed_service + update both DBs (watch: check_workflow_standards/routing standards match templates BY NAME; tests assert names).
- **Plants**: default should be USA *for now* ("we define that later"). No default-plant concept exists; projects have plant_id (Test Project→Main Factory, VW426 Atlas→USA Toccoa). Plant list has duplicates: "USA" and "USA Toccoa", plus "Main Factory" test junk — consolidate. User saw Weissenburg (WUG) appearing as standard somewhere — locate & fix during Phase E.

## Phase E scope (agreed)
1. Department membership admin (Users page dropdown) + dev membership seeds.
2. Enforcement: dept membership required for submit_assessment (and complete_task); role-aware change page — your actionable pieces highlighted, rest read-only.
3. My-Tasks-first experience; "what do I do now" guidance per role on the cockpit.
4. Engineering owns the affected-items decision (see DECISION above).
5. English seed names for templates/stages/steps.
6. Plant defaults (project plant → default, USA for now) + duplicate plant cleanup.

## Also queued (final-review deferrals — bundle where they fit)
Correlation-scoped audit chain verify; audit org/role scoping; AuditTimeline >1000-rows drops newest; audit day headings browser-local TZ (user must consciously accept or fix); migration 025 downgrade guard; ChangeResponse vars()-validator fragility; ready-to-go badge green drift.

## Env crib (binding)
`alembic` console script from backend/ (not python3 -m); SQLite can't ADD COLUMN with FK (plain col + ORM FK) and needs batch_alter_table for ALTER COLUMN; Postgres needs sa.false() boolean defaults + CASCADE for circular-FK drops; fixers stage explicit paths only, never -A; repo tracks .pyc noise — never stage __pycache__/plm.db; frontend tsc baseline 21; dev logins test@example.com/password + admin@example.com/admin1234.
