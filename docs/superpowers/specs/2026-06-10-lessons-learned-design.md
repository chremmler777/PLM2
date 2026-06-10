# Lessons Learned Module — Design (2026-06-10)

## Goal
A reliable, trackable, accountable lessons-learned system inside PLM2, modeled on the
classic SharePoint "Lessons Learned (Project Management)" list but upgraded to a modern
interactive workflow: status lifecycle, action items with owners and due dates, comment
thread, notifications, and dashboard-style stats.

## The project-link problem (user question)
Real-world projects may not exist in the PLM yet, so a hard FK would block capture.
**Decision: capture-first, link-later.**
- `project_id` is a **nullable** FK to `projects.id`.
- `project_ref` is a free-text fallback ("Toccoa Ramp-up") so the lesson still says
  which project it belongs to even when that project is not in the PLM.
- Lessons can be re-linked at any time via PATCH (`project_id`); the UI shows an
  amber "not linked" chip and offers a project picker to link afterwards.
- A `unlinked=true` list filter makes the backlog of unlinked lessons visible so the
  workaround stays accountable rather than becoming permanent data rot.

## Data model (migration 015, `app/models/lesson.py`)

### lessons_learned
| field | type | notes |
|---|---|---|
| id | int PK | |
| title | str(200) | required |
| project_id | FK projects, nullable, idx | link-later |
| project_ref | str(200), nullable | free-text project name fallback |
| category | str(30) | design, manufacturing, quality, supplier, logistics, project_management, tooling, other |
| lesson_type | str(20) | success / problem / improvement |
| severity | str(10) | low / medium / high / critical |
| description | Text | what happened (required) |
| root_cause | Text, nullable | why it happened |
| recommendation | Text, nullable | what to do differently next time |
| tags | str(300), nullable | comma-separated, searchable |
| status | str(20), idx | lifecycle below, default `draft` |
| owner_id | FK users, nullable | accountable person |
| department_id | FK departments, nullable | owning department |
| created_by / created_at / updated_at | audit | |
| submitted_at / closed_at | nullable timestamps | cycle-time tracking |

### lesson_actions (accountability)
id, lesson_id FK idx, description Text, assignee_id FK users nullable,
due_date nullable, status open/done, completed_at, created_by, created_at.

### lesson_comments (interactivity + audit trail)
id, lesson_id FK idx, user_id FK, body Text, is_system bool, created_at.
Status transitions write a system comment ("status draft → submitted by …"), giving a
full who-did-what history without a separate audit table.

## Status lifecycle (server-enforced transition map)
```
draft → submitted → in_review → approved → implemented → closed
          ↓ (withdraw)   ↓ rejected → draft (rework)
        draft
```
Guard: a lesson cannot be **closed** while it has open actions (409) — closing means
the learning was actually acted on, not just filed.

## API (`/v1/lessons`, module package `app/api/v1/learning/`)
- `GET /lessons` — filters: status, category, lesson_type, severity, project_id,
  unlinked, q (title/description/tags/project_ref); returns action counts.
- `POST /lessons` — create (draft); validates optional project_id exists.
- `GET /lessons/stats` — totals by status/category/type, open + overdue actions, unlinked count.
- `GET /lessons/{id}` — full detail incl. actions + comments (resolved usernames).
- `PATCH /lessons/{id}` — fields incl. owner_id, department_id, project_id (link-later).
- `POST /lessons/{id}/transition {status}` — enforced map + close guard + system comment.
- `POST /lessons/{id}/actions`, `PATCH /lessons/actions/{id}` (done/reopen, reassign), `DELETE`.
- `POST /lessons/{id}/comments`.

Notifications (existing NotificationService): submit → department members;
owner assigned → owner; action assigned → assignee; approved/rejected → creator + owner.

## Frontend
- `LessonsLearnedPage.tsx` at `/lessons`, sidebar entry "Lessons" (📘), same dark-slate
  style as SuppliersPage.
- Stats strip (total / in review / approved-not-implemented / overdue actions / unlinked).
- Filter bar: status chips, category + type selects, text search.
- Table: title, project (or amber unlinked chip), category, type, severity, owner,
  actions progress (2/3), status badge, age.
- Detail modal: edit fields, status workflow buttons (only legal transitions shown),
  project link picker, actions checklist (add/assign/due/complete), comment thread with
  system entries styled differently.
- New Lesson modal: title, description, category, type, severity, project select
  (optional) **or** free-text project ref, recommendation.

## Testing
`backend/tests/test_lessons.py` (existing conftest fixtures): create with/without
project + link-later PATCH; invalid transition 400; full happy-path lifecycle;
close blocked by open action (409) then allowed; action complete; comment + system
comment from transition; filters (status, unlinked, q); stats endpoint.

## Out of scope (YAGNI)
Approval role restrictions (app-wide permissions are flat today), file attachments on
lessons, knowledge-base search integration. All can layer on later without schema changes.

---

# v2 — Operational governance (2026-06-10, same day)

Goal: make the system self-managing — trackable, accountable, reused.

## Schema additions (migration 016)
- `lessons_learned`: `approved_at` (cycle-time KPI), `effectiveness_note`,
  `effectiveness_verified_by/at` (close gate).
- `lesson_actions`: `last_reminded_at` (reminder dedupe).
- New `lesson_references`: lesson reviewed/applied for a project
  (lesson_id, project_id, milestone_id?, note, created_by) — feeds reuse-rate KPI;
  duplicate (lesson, project) rejected.

## Rules added (server-enforced)
1. **Owner gate:** in_review → approved requires `owner_id` (409 otherwise).
2. **Effectiveness gate:** implemented → closed requires `effectiveness_verified=true`
   (+ optional note); recorded with verifier and timestamp. Open-actions guard unchanged.

## New API
- `GET /lessons/my-actions` — open actions assigned to current user (My Tasks).
- `GET /lessons/kpis` — time-to-review, implementation rate, action completion,
  overdue by assignee/department, by category/severity/status/month, reuse rate,
  unlinked backlog, review-queue depth. Aggregated in Python (DB-agnostic, small scale).
- `GET /lessons/projects/{id}/references`, `POST /lessons/{id}/references`.

## Reminders
`lesson_reminder_service.send_overdue_action_reminders`: notifies assignees of overdue
open actions, ≤1 per action per 24h (`last_reminded_at`). Background loop in app
lifespan runs every 6h.

## Frontend
- **My Tasks**: Lesson Actions section (deep-links to `/lessons?lesson=ID`, mark-done).
- **Lessons page**: Review Queue toggle (submitted/in_review oldest-first), effectiveness
  dialog on close, owner-missing hint, KPI Board button, `?lesson=`/`?project=` params.
- **KPI board** at `/lessons/kpis`: tile style (big numbers + accent colors), CSS bar
  breakdowns, overdue-by-assignee/department tables.
- **Project page**: ProjectLessonsSection strip — project lesson count, reuse-review
  count, "Gate prep" amber prompt when no review recorded, Review Applicable Lessons
  modal (search all non-draft lessons from other projects → mark reviewed).
- **Dashboard**: condensed lessons widget (queue, overdue, implementation %, unlinked).

---

# v3 — Strict lifecycle rework (2026-06-10, user-specified flow)

User flow: capture → automatically in review → triage defines owner + timing + actions,
then accept or reject → in work (evidence) → verification review → closed.
"Clean workflow, no double entries or in-between states — it follows its spec."

## New state machine (replaces v1 lifecycle)
```
in_review ──accept──▶ in_work ──all actions done, owner sends──▶ verification ──verified──▶ closed
    │                    ▲                                            │
    └──reject──▶ rejected└────────────── send back with feedback ─────┘
```
- **Creation lands in `in_review`** — no draft, no manual submit. created_at = submission time.
- **Accept gates (server):** owner_id set, target_date set, ≥1 action. Sets accepted_at.
- **Reject gates:** category ∈ {duplicate, not_actionable, out_of_scope, insufficient_info}
  + free-text reason; submitter notified. Terminal.
- **in_work → verification:** all actions done; only the owner (or admin) sends;
  sets verification_requested_at.
- **verification → closed:** effectiveness_verified=true (+ note), verifier recorded.
- **verification → in_work:** send back with mandatory feedback note (system comment +
  owner notified).
- No other edges exist; tests assert every illegal edge from every state returns 400.

## Field editability by state (PATCH-enforced)
- `in_review`: everything (content, owner, target_date, department, project link, tags).
- `in_work`: root_cause, recommendation, tags, project link; owner/target_date may be
  *changed* (never cleared) and the change writes a system comment. Reviewed content
  (title, description, category, type, severity) is locked after acceptance.
- `verification`: project link only.
- `closed` / `rejected`: read-only.
- Actions: create/edit/delete in in_review + in_work only. Files: upload/delete in
  in_review + in_work only.

## Schema (migration 017)
- lessons_learned += target_date, accepted_at, verification_requested_at,
  reject_category, reject_reason, last_escalated_at.
- New `lesson_files`: filename, stored uploads/lessons/{lesson_id}/, sha256,
  content_type, size, uploaded_by, created_at.
- **Data migration:** draft/submitted → in_review; approved → in_work
  (accepted_at = approved_at, target_date default +30d); implemented → verification
  (verification_requested_at = now); closed/rejected unchanged.

## Duplicate guard
GET /lessons/check-duplicates?title= → word-overlap matches (warn, never block);
capture modal shows similar lessons live.

## QoL / visuals
Stepper with time-in-state + stale flags (in_review >14d, verification >7d, in_work
past target_date); target-date escalation notifies owner + department (daily dedupe via
last_escalated_at, same 6h loop); GET /lessons/tags for autocomplete; mine=true filter;
capture autofocus + Ctrl+Enter; KPI board gains severity×category heatmap, monthly
capture-to-close cycle-time trend, on-time close rate, time-to-accept.

