# Change Management — Core + Lifecycle (Sub-project #1)

**Date:** 2026-06-15
**Status:** Implemented (sub-project #1) on branch `feature/change-management` — backend 102 tests pass, frontend type-clean. See plan `docs/superpowers/plans/2026-06-15-change-management-core.md`.
**Scope:** The spine of the Change Management module. First of seven planned sub-projects.

---

## 1. Context & goal

PLM2 already has projects, parts/articles, revisions (with an `ecn` phase), a generic
RASIC stage-gate workflow engine, an SEP Q-Gate module, PPAP quality, milestones, a
3D viewer, and hash-chained audit logging. What is missing is a **Change Management**
process to coordinate engineering changes — most often a physical part change that must
trigger feasibility analysis, costing/offers, a go/no-go decision, implementation across
multiple affected items, validation, and release.

This sub-project builds the **spine**: a single Change object with a strict-but-flexible
lifecycle, change-type-driven routing, impacted-item linking, discipline assessments, and
a tamper-evident audit trail — with defined attachment points for the later sub-projects.

### Decomposition (full roadmap, for context)

1. **Change Request core + lifecycle (this spec)**
2. Cross-functional assessment auto-routing via the RASIC workflow engine
3. Commercial layer — costs, offers/quotes, P&L-if-implemented (Sales-led)
4. Impact scope automation & engineering-level marking
5. 3D data storage + diff colormap overlay in the viewer
6. Sampling/validation (PPAP) + release automation
7. Timing proposal + tracking (milestones)

Each later sub-project gets its own spec → plan → implementation cycle.

---

## 2. Design decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Core structure | **One object, phased.** Single `ChangeRequest` flowing through one state machine. No ECR/ECO record split. |
| 2 | Change types | **One lifecycle; `change_type` drives routing** (which disciplines/items are suggested, which steps are skippable). |
| 3 | Assessment gate | **Structured verdict + cost/time inputs per discipline.** Lead closes the phase when required disciplines respond. |
| 4 | Decision gate | **Customer acceptance + internal dual sign-off** (PM + Quality, two different users). |
| 5 | Change ↔ revisions | **Change creates & owns ECN revisions.** On approval it spawns a `PartRevision` (ecn) per impacted part; on release those become active/official and supersede the prior revision. |
| 6 | First-build scope | **Spine + working UI + impacted-items.** |
| 7 | Flexibility | **Minimal start + soft guards.** A change can start with just a title/reason + a PPT. The lead can advance phases with a logged justification when data is incomplete. |

---

## 3. Flexibility principle (load-bearing)

Real ECRs frequently start with nothing but a PowerPoint and a sentence. The model must
capture structure **when available** and stay out of the way when it is not.

- **Minimal start:** create with only `title` + `reason` + optional attachments. No
  impacted items, CAD, or structured data required at `captured`.
- **General attachments:** a `ChangeAttachment` model holds informal documents (PPT, PDF,
  email, images, sketches) at any phase — distinct from structured `RevisionFile` CAD data.
- **Soft guards:** the state machine defines ideal preconditions, but the **lead (PM) may
  force a transition with a logged justification** even when data is incomplete. Each
  override is recorded (`action: forced_transition`, with reason + actor).
- **Hard guard (no override):** `quoted → approved` always requires customer acceptance
  **and** dual sign-off. This is the one governance-critical gate.
- **Progressive structure:** impacted items and assessments are added/refined as the change
  matures; `change_type` *suggests* disciplines and item slots but does not force them.

Flexibility never costs traceability: every override is in the audit trail with who and why.

---

## 4. Data model

All models follow existing conventions: SQLAlchemy 2.0 `Mapped`/`mapped_column`, string
enums declared with `Enum(..., values_callable=lambda x: [e.value for e in x], native_enum=False)`,
relationships with `back_populates` + `selectin` where useful.

### 4.1 `ChangeRequest` (`change_requests`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | PK | |
| `change_number` | str, unique, indexed | `CR-{year}-{NNNN}`, per-year sequence |
| `title` | str | required |
| `description` | text | nullable |
| `reason` | text | justification / "why"; nullable but encouraged |
| `project_id` | FK → projects | |
| `change_type` | Enum `ChangeType` | physical_part \| tooling \| document_spec \| process_im \| packaging |
| `priority` | Enum | low \| medium \| high \| critical |
| `data_classification` | str | default "confidential" |
| `status` | Enum `ChangeStatus` | see §5 |
| `lead_id` | FK → users | Project Manager = Accountable |
| `raised_by` | FK → users | |
| `raised_at` | datetime | |
| `customer_response` | Enum | pending \| accepted \| declined \| negotiating |
| `customer_response_at` / `_by` | datetime / FK | recorded by Sales |
| `pm_signed_by` / `_at` | FK / datetime | internal sign-off |
| `quality_signed_by` / `_at` | FK / datetime | internal sign-off (different user) |
| `estimated_cost` | numeric, nullable | **stub** — commercial sub-project (#3) |
| `quoted_price` | numeric, nullable | **stub** (#3) |
| `pnl_note` | text, nullable | **stub** (#3) |
| `timing_milestone_id` | FK → project_milestones, nullable | **stub** (#7) |
| `released_at` / `released_by` | datetime / FK | |
| `closed_at` | datetime | |
| `cancelled_at` / `cancellation_reason` | datetime / text | |
| `created_at` / `updated_at` | datetime | |

Relationships: `project`, `lead`, `raised_by_user`, `impacted_items`, `assessments`,
`attachments`, `changelog_entries`.

### 4.2 `ChangeImpactedItem` (`change_impacted_items`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | PK | |
| `change_id` | FK → change_requests | |
| `part_id` | FK → parts | item being changed (article/tool/assembly_equipment/eoat/gauge) |
| `impact_note` | text | nullable |
| `eng_level_before` | str, nullable | engineering-level / identifier status before |
| `eng_level_after` | str, nullable | stamped at release |
| `resulting_revision_id` | FK → part_revisions, nullable | the ECN revision spawned for this item |
| `created_at` / `created_by` | datetime / FK | |

Items may be seeded from `PartRelation` (e.g. tool *produces* article, gauge *checks*
article) to assist impact discovery; final list is curated by the lead.

### 4.3 `ChangeAssessment` (`change_assessments`)

One row per impacted discipline.

| Field | Type | Notes |
|-------|------|-------|
| `id` | PK | |
| `change_id` | FK → change_requests | |
| `department_id` | FK → wf_departments | discipline (Tool Eng/Dev, APQP/Quality, ME, Packaging, Process, Sales) |
| `verdict` | Enum | pending \| feasible \| feasible_with_conditions \| not_feasible |
| `cost_impact` | numeric, nullable | feeds commercial layer (#3) |
| `lead_time_impact_days` | int, nullable | |
| `conditions` | text, nullable | for feasible_with_conditions |
| `notes` | text, nullable | |
| `responsible_id` | FK → users, nullable | |
| `submitted_at` / `submitted_by` | datetime / FK | |
| `created_at` / `updated_at` | datetime | |

Created from the `change_type`'s suggested department list; surface in My Tasks. Full
RASIC auto-routing is sub-project #2.

### 4.4 `ChangeAttachment` (`change_attachments`)

General documents (the PPT-only start). Mirrors `LessonFile`.

| Field | Type | Notes |
|-------|------|-------|
| `id` | PK | |
| `change_id` | FK → change_requests | |
| `filename` / `stored_path` | str | |
| `content_type` | str | |
| `size_bytes` | int | |
| `sha256` | str | |
| `uploaded_by` | FK → users | |
| `created_at` | datetime | |

### 4.5 `ChangeChangelog` (`change_changelog`)

Hash-chained audit, mirroring `RevisionChangelog` (reuse the existing SHA-256 chaining helper).

| Field | Type | Notes |
|-------|------|-------|
| `id` | PK | |
| `change_id` | FK → change_requests | |
| `action` | str | created, status_changed, forced_transition, assessment_submitted, impacted_item_added/removed, attachment_added, customer_response_recorded, signed_off, revision_spawned, released, closed, cancelled |
| `action_description` | text | human-readable |
| `field_name` | str, nullable | |
| `old_value` / `new_value` | text (JSON), nullable | |
| `performed_by` | FK → users | |
| `performed_at` | datetime, indexed | |
| `previous_hash` / `entry_hash` | str(64), nullable | SHA-256 chaining |
| `notes` | text, nullable | holds override justification for forced_transition |

### 4.6 Enum extension

Add `eoat` to the existing `parts.item_category` enum (article, tool, assembly_equipment,
**eoat**, gauge) so injection-mold grippers are first-class impacted items.

---

## 5. Lifecycle state machine

```
captured → in_assessment → costing → quoted →[GATE]→ approved
  → in_implementation → in_validation → released → closed

parking / exits:
  on_hold      (↔ from any active state, back to prior)
  rejected     (terminal; from in_assessment or quoted)
  cancelled    (terminal; from any non-terminal state)
```

All transitions go through `ChangeService.transition(change, to_status, user, justification=None)`:
validates the guard, writes a `ChangeChangelog` entry, fires notifications. Status is never
set directly anywhere else.

### Guards

| Transition | Guard | Override? |
|------------|-------|-----------|
| `captured → in_assessment` | Recommended: ≥1 impacted item + lead assigned; creates assessment rows for the change_type's disciplines | **Yes** (lead, logged) |
| `in_assessment → costing` | Recommended: every required discipline submitted a verdict; any `not_feasible` forces explicit decision | **Yes** (lead, logged) |
| `costing → quoted` | Recommended: offer/price recorded | **Yes** (lead, logged) |
| `quoted → approved` | **customer_response = accepted AND pm_signed AND quality_signed** | **No (hard)** |
| `approved → in_implementation` | Spawns ECN `PartRevision` per impacted item (§6) | — |
| `in_implementation → in_validation` | Recommended: all impacted items have a resulting revision with data | **Yes** (lead, logged) |
| `in_validation → released` | Recommended: validation passed (PPAP/sampling hook — stub) | **Yes** (lead, logged) |
| `released → closed` | wrap-up complete | **Yes** (lead, logged) |
| `* → on_hold` / `on_hold → *` | reversible parking | — |
| `* → cancelled` | requires `cancellation_reason` | — |

Forced (overridden) transitions are logged as `action: forced_transition` with the
justification stored in `notes`.

---

## 6. Change ↔ revisions (implementation & release)

- **`approved → in_implementation`:** for each `ChangeImpactedItem` whose `part_id` warrants
  it, `ChangeService` creates a `PartRevision` in `ecn` phase, sets `change_reason` from the
  change, and links it via `resulting_revision_id`. Records `revision_spawned` in the changelog.
- **Implementation:** engineers populate those ECN revisions with new CAD/3D data
  (`RevisionFile`) through the existing revision flow. The 3D diff colormap (#5) and sampling
  (#6) attach to these revisions later.
- **`released`:** each ECN revision becomes active/official, `supersedes_revision_id` is set
  on the prior revision, the part's `active_revision_id` is updated, and `eng_level_after` is
  stamped on the impacted item. Records `released`.

The Change is the umbrella coordinating a consistent set of revisions across all affected items.

---

## 7. Services

`ChangeService` (new, `backend/app/services/change_service.py`):

- `create_change(...)`, `list_changes(filters)`, `get_change(id)`, `update_change(...)`
- `transition(change, to_status, user, justification=None)` — central guarded state machine
- `add_impacted_item(...)`, `remove_impacted_item(...)`, `seed_impacted_items_from_relations(...)`
- `submit_assessment(change, department, verdict, cost_impact, lead_time, conditions, notes, user)`
- `record_customer_response(change, response, user)`
- `sign_off(change, role, user)` — pm | quality, enforces two-different-users
- `spawn_ecn_revisions(change, user)` — invoked on approve→implementation
- `release(change, user)` — activate revisions, supersede, stamp eng level
- `_append_changelog(...)` — reuses the existing SHA-256 hash-chaining helper

Notifications via the existing `NotificationService`.

---

## 8. API (`/v1/changes`)

Router folder `backend/app/api/v1/changes/changes.py`, registered in `api/v1/__init__.py`.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/changes` | create (minimal start allowed) |
| GET | `/changes` | list; filters: project_id, status, change_type, lead_id, mine |
| GET | `/changes/{id}` | detail (nested items/assessments/attachments/audit) |
| PATCH | `/changes/{id}` | update metadata |
| POST | `/changes/{id}/transition` | `{to_status, justification?}` |
| POST | `/changes/{id}/impacted-items` | add |
| DELETE | `/changes/{id}/impacted-items/{itemId}` | remove |
| POST | `/changes/{id}/impacted-items/seed` | seed from PartRelations |
| GET / POST | `/changes/{id}/assessments` | list / submit verdict |
| POST | `/changes/{id}/attachments` | upload general doc (PPT etc.) |
| POST | `/changes/{id}/customer-response` | Sales records customer outcome |
| POST | `/changes/{id}/sign-off` | `{role: pm|quality}` |
| POST | `/changes/{id}/release` | release shortcut (also reachable via transition) |

Pydantic schemas (`backend/app/schemas/change.py`) follow the Base/Create/Update/Response/
DetailResponse convention plus action requests: `ChangeTransitionRequest`,
`CustomerResponseRequest`, `SignOffRequest`, `ChangeAssessmentCreate`,
`ChangeImpactedItemCreate`.

---

## 9. Frontend

- **`ChangesPage.tsx`** — filterable list (status / type / project / mine) + create modal
  (title + reason + optional attachment is enough to create).
- **`ChangeDetailPage.tsx`** — visual lifecycle stepper across the state machine; tabs:
  Overview, Impacted Items, Assessments, Commercial (stub), Implementation (linked
  revisions), Audit timeline. Transition action buttons gated by current status + user role;
  forced transitions prompt for a justification.
- **`ProjectChangesSection.tsx`** — embedded in `ProjectDetailPage` alongside the SEP and
  Lessons sections.
- **My Tasks** — assessment tasks (per assigned department) and sign-off tasks surface in
  `MyTasksPage`.
- API client functions + TS types in `frontend/src/types/change.ts` and
  `frontend/src/api/` per existing structure.

---

## 10. Migration & testing

- **Alembic `018_add_change_management.py`:** create `change_requests`,
  `change_impacted_items`, `change_assessments`, `change_attachments`, `change_changelog`;
  add `eoat` to `parts.item_category`.
- **Backend tests** (`pytest`, existing conftest auth/client fixtures): valid transition
  paths; each guard (assessment completeness, the hard dual-sign-off + customer-acceptance
  gate, cancellation reason required); forced-transition logging; ECN revision spawning on
  approval; release activating/superseding revisions + eng-level stamping; changelog
  hash-chain integrity.
- **Frontend:** `tsc` type-check passes; manual smoke of create → advance → sign-off →
  implement → release.

---

## 11. Out of scope (later sub-projects)

RASIC auto-routing of assessments (#2); full cost/offer/P&L module (#3); automatic impact
discovery beyond relation seeding (#4); 3D diff colormap overlay (#5); sampling automation
(#6); timing tracking (#7). This spec defines the stub fields/links those will populate.
