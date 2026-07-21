# Änderungsmitteilung Digitization — Design

**Date:** 2026-06-24
**Branch context:** builds on `feature/change-assessment-routing`
**Status:** approved design, pre-implementation

## Context

The customer's change-management process is encoded in an Excel workbook,
`ÄnderungsmitteilungChange_Management.xlsx` (document `GB-CM-0001`). It is the
authoritative spec for the change-management feature already started in PLM2
(`change_requests`, `change_assessments`, `change_routings`).

The workbook contains:

- **`Änderungsinformation_D1`** — master header (issuer, project/car line,
  customer, affected plants, lead part / *Leit-Teil*, change description), an
  11-department approval matrix (*Zustimmung erforderlich von* with contact
  person + producibility yes/no + comment), and **3 gates**:
  1. `realisierbar?` → *Start Bewertung* (feasibility → start assessment)
  2. `Budget geprüft?` → *Start Kundenaktivitäten* (budget → customer activities)
  3. `techn. Freigabe / Bestellung?` → *Start Umsetzung* (release → implementation)
- **`D2`–`D10`** — one cost-assessment tab per department (Sales, R&D, Tool
  design, IE, Quality, Logistics, Production, Purchasing, Production control).
  Each tab is a list of **cost lines**, split across **two plants**
  (NKTW Weissenburg / NKTW USA); each plant has *internal* cost (demand hours ×
  hourly rate) and *external* cost (material / devices / other). Each department
  has a predefined **activity catalog** plus free-input rows.
- **`Std.-Sätze+Fzg`** — hourly-rate table by department × plant (Sales 50,
  R&D 65 / 21.5, …), min-factors (DEU 0.6 / USA 0.36), and vehicle quantities
  for lifecycle costs.
- **`Summierung`** — a pure roll-up of all department lines: one-time vs
  lifecycle, internal vs external, per plant, plus grand totals.

This is **sub-project A** of three:

- **A — Änderungsmitteilung digitization** (this doc): extend the data model to
  hold the full per-department cost detail + D1 master + gates, and build the
  in-app forms. The primary path: departments fill info directly in the system.
- **B — Excel backup round-trip** (separate spec): export/import the exact
  `GB-CM-0001` workbook as an offline fallback. Depends on A's data model.
- **C — Localization (ES/EN/DE)** (separate spec): per-user system language for
  all labels/UI/export headers. Cross-cutting, greenfield. A's forms are built
  localization-ready (labels keyed) so C slots in without touching components.

## Goals

- PLM2 becomes the source of truth for change assessments, able to regenerate
  the `Summierung` itself.
- Every department can enter its full cost assessment directly in the app.
- Capture the D1 master fields, approval matrix, and 3 gates, wiring the gates
  into the existing change state-machine.

## Non-goals (explicitly out of scope for A)

- Excel export/import (sub-project B).
- Localization runtime + Spanish; A only *keys* labels (sub-project C).
- Email distribution; machine translation of free text.

## Approach

Chosen: **normalized data model** (new tables for cost lines, department×plant
rates, and a seeded activity catalog). Rejected alternatives: a JSON blob on the
assessment (not queryable, weak roll-ups) and a hybrid keeping rates/catalog as
JSON config (rates are shared reference data that want a real table).

## Data model

### New tables

**`assessment_cost_line`** — one row per cost line.

| field | type | notes |
|---|---|---|
| `id` | PK | |
| `assessment_id` | FK → `change_assessments` | |
| `plant_id` | FK → plants | Weissenburg / USA |
| `activity_id` | FK → `assessment_activity`, nullable | null for free-input |
| `activity_label` | string, nullable | required when `activity_id` is null |
| `cost_kind` | enum `one_time` \| `lifecycle` | |
| `demand_hours` | float | *Bedarf / Stunden* (internal) |
| `rate_snapshot` | float | hourly rate captured at entry time |
| `internal_cost` | float | computed = `demand_hours × rate_snapshot` |
| `external_cost` | float | material / devices / other |
| `note` | string, nullable | |

**`department_rate`**

| field | type | notes |
|---|---|---|
| `id` | PK | |
| `department_id` | FK → `wf_departments` | |
| `plant_id` | FK → plants | |
| `hourly_rate` | float | from `Std.-Sätze` |
| `min_factor` | float | DEU 0.6 / USA 0.36; used only by lifecycle math |
| `effective_from` | date | |

**`assessment_activity`** — seeded per-department catalog.

| field | type | notes |
|---|---|---|
| `id` | PK | |
| `department_id` | FK → `wf_departments` | |
| `label` | string | e.g. R&D "3D-Konstruktion Produkt" |
| `sort_order` | int | |
| `is_active` | bool | |

**`change_gate`** — the 3 D1 gates.

| field | type | notes |
|---|---|---|
| `id` | PK | |
| `change_id` | FK → `change_requests` | |
| `gate_key` | enum `feasibility` \| `budget` \| `release` | |
| `decision` | enum `yes` \| `no` \| `na` | |
| `decided_by` | FK → users, nullable | |
| `decided_at` | datetime, nullable | |
| `remark` | string, nullable | |

### Extended tables

**`change_assessments`** — add `producibility` (`yes`|`no`|`na`),
`contact_person` (string), `approval_comment` (string) for the D1 approval
matrix. Keep `verdict` / `status` / routing fields. `cost_impact` becomes the
*computed* sum of its one-time lines (recalculated on line change, kept for
back-compat); add computed `lifecycle_cost`.

**`change_requests`** — add D1 master fields not already present: `issuer`,
`is_series` (bool), `cm_internal` (bool), `cm_external` (bool),
`implementation_mode` (`integrated`|`separational`), `customer_relevant` (bool),
`car_line` (string), and `affected_plants` (M2M → plants). The **Leit-Teil** is
modeled by adding `is_lead` (bool) to the existing `change_impacted_items`.

### Computed, never stored

The `Summierung` roll-up.

## Cost computation & rates

Confirmed from the workbook's live formulas:

- **Internal cost per line:** `internal_cost = demand_hours × rate` where `rate`
  is `department_rate.hourly_rate` for that department × plant.
  (Workbook: `K11 = J11 * 'Std.-Sätze+Fzg'!C$6`.)
- **External cost:** entered directly; no formula.
- **Per-department total:** sum of that department's line internal/external
  costs per plant. (Workbook: `K28 = SUM(K11:K27)`.)
- **`Summierung`:** sum of per-department totals, grouped by plant × `cost_kind`
  × {internal, external}, with grand totals. (Workbook: `D34 = D4+D7+D10+…`
  one-time; `D35 = D5+D8+…` lifecycle.) A pure function exposed via one endpoint.
- `rate_snapshot` is stored on each line so later rate edits do not silently
  rewrite historical costs; recompute only on an explicit "refresh rates" action.
- **Lifecycle math** uses `min_factor` and vehicle quantity; the exact
  per-department lifecycle formula is transcribed from the workbook cells during
  implementation of the lifecycle line rows (one-time cost, the common case, is
  fully specified above and does not use `min_factor`).

## Backend services & API

Extend `ChangeService` / `ChangeRoutingService`; add a small `cost_service` for
cost-line CRUD, recompute, and roll-up. New/changed endpoints under the existing
`/api/v1/changes` prefix:

- `GET /{id}/assessments/{aid}/cost-lines` — list a department's cost lines.
- `PUT /{id}/assessments/{aid}/cost-lines` — replace a department's cost lines
  (whole-collection replace; recompute `cost_impact`/`lifecycle_cost`).
- `GET /{id}/summation` — computed `Summierung`.
- `GET /{id}/gates`, `PUT /{id}/gates/{gate_key}` — read/decide gates; a gate
  decision wires into existing state-machine guards (feasibility→`in_assessment`,
  budget→`costing`/customer activities, release→`in_implementation`).
- `GET /reference/rates`, `GET /reference/activities?department_id=` — form data.

Gate decisions and cost-line edits append to the existing hash-chained
`change_changelog`.

## Frontend (in-app — the primary path)

- **Department assessment form** — an editable cost-line grid: rows = catalog
  activities + free-input; columns = per plant {demand hours, external cost};
  internal cost auto-calculated; live per-plant and total footer. Plus
  producibility yes/no, contact person, verdict, lead-time, conditions/notes.
- **D1 master panel** — header fields, affected plants, Leit-Teil picker,
  approval-matrix overview, and the 3 gates (decide + date + current-user
  signature).
- **Summierung view** — read-only computed table mirroring the workbook roll-up.
- **Localization-ready** — every label pulled from a string-key map (ship DE/EN
  now, matching the workbook); sub-project C swaps in the ES/EN/DE runtime
  without touching components.

## Error handling & edge cases

- Missing `department_rate` for a department × plant → block internal-cost
  compute with a clear message; allow external-only entry.
- Single-plant change → a plant can be toggled off; its columns hide and it
  drops from the roll-up.
- Free-input line → `activity_label` required.
- Concurrent edits to one assessment → optimistic concurrency (reject stale
  writes); all edits logged to the changelog.

## Testing

- Unit: cost math (`hours × rate`) and `Summierung` roll-up checked against a
  known filled-workbook example.
- Service/API: cost-line replace, recompute, snapshot-on-edit, and
  gate → state-machine wiring.
- Migration test for the new/extended tables.
- Reuse existing `test_change_routing` fixtures (`departments`, `ecr_template`,
  `_seeded_change`).

## Seed data

- `department_rate` seeded from `Std.-Sätze` (Sales 50; R&D/Tool/IE 65 DEU /
  21.5 USA; Quality 45 / 21.5; Logistics 50 / 21.5; Production 55 / 21.5;
  Purchasing 50 / 21.5; Production control 50 / 21.5; min-factor DEU 0.6 /
  USA 0.36).
- `assessment_activity` seeded per department from each tab's selection list.
- Plants Weissenburg and USA ensured present.
