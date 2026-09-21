# Paint catalog and article paint setup — design

Date: 2026-09-21
Status: approved in chat

## Problem

RFQ2 carries paint per BOM item as free text (paint required, type, grade,
colour, process, cost). PLM has nothing: an article's paint is not recorded,
so nobody can see which articles share a paint or what a painted article
needs. Christoph wants paint in PLM "like in RFQ, with different paints",
plus a paint overview on articles.

## Decisions

1. **Paints are master data**, org-scoped, in their own catalog. Articles
   reference them; a paint's data is edited once.
2. **Paint hangs off the part**, not the revision. Every change is logged in
   the part changelog. Revision-bound paint history is a later extension.
3. **Engineering data only.** No cost per part in PLM; cost stays in RFQ2 and
   change costing.
4. **Layers are ordered.** An article can have several paints in order
   (primer → basecoat → clearcoat) with an optional area note.

## 1. Data model (one migration, 073)

`paints` (org-scoped like `catalog_parts`)
- id, organization_id, name (str 255, required), paint_type (`primer |
  basecoat | clearcoat | one_coat | other`), colour_code (str 50, e.g.
  `RAL 9005` or a customer code), colour_name (str 100), colour_hex (str 7,
  optional swatch), supplier_id (FK suppliers, nullable), supplier_text
  (str 255, free text fallback), spec_reference (str 255, datasheet / spec
  number), notes (text), is_active (bool, default true), created_by,
  created_at, updated_at.
- unique (organization_id, name).

`part_paints` (one per part, created on first edit)
- id, part_id (FK parts, unique), paint_required (bool), process (str 255,
  free text: spray, electrocoat, …), notes (text), updated_by, updated_at.

`part_paint_layers`
- id, part_paint_id (FK part_paints, cascade), paint_id (FK paints),
  layer_order (int, 1-based), area (str 255, e.g. "A-side only"), notes
  (str 500).
- unique (part_paint_id, layer_order).

Changelog: every put on a part's paint setup writes one `paint_updated`
line on the part describing the diff ("Paint required; layers: RAL 9005
basecoat → 2K clear").

## 2. API

| Call | Purpose |
|---|---|
| `GET /api/v1/paints?active_only=true&q=` | List paints of the org |
| `POST /api/v1/paints` | Create; 409 on duplicate name |
| `GET /api/v1/paints/{id}` | One paint |
| `PUT /api/v1/paints/{id}` | Update (incl. is_active) |
| `GET /api/v1/paints/{id}/used-in` | Articles across projects using it: part id, number, name, project code, layer_order |
| `GET /api/v1/parts/{id}/paint` | Part paint setup with layers (paint data embedded); 200 with `paint_required=false, layers=[]` when none stored |
| `PUT /api/v1/parts/{id}/paint` | Replace the whole setup: `{paint_required, process, notes, layers:[{paint_id, area, notes}]}`; layers renumbered from the list order; logs changelog |
| `GET /api/v1/parts/project/{id}/paint-overview` | Every part in the project with paint_required, with layers; grouped client-side |

No delete on paints; deactivate instead. Deleting a part cascades its paint
rows. Layers referencing an inactive paint stay and render with an
"inactive" tag.

## 3. UI

- **Paints page** (`/paints`, sidebar "🎨 Paints" under Purchased Parts):
  table (name, type, colour swatch + code, supplier, spec, active) with
  search and "show inactive"; new/edit form; row expands to its used-in list.
- **Part page**: Paint card under Part Information. Toggle "Paint required";
  when on: process input, notes, ordered layers (paint name · type · colour
  chip · area), add layer via a picker over active paints, remove, move up
  or down; one Save writes the whole setup. Card shows "paint spec missing"
  when required with no layers.
- **Project page**: category chips gain 🎨 **Painted** (articles with
  paint_required) with count; painted rows show a small colour swatch of the
  top layer. New collapsible **Paint** section (like SEP / Changes) listing
  painted articles grouped by paint: paint header (swatch, name, type,
  colour code) → article rows (number, name, layer position). Empty state:
  "No painted articles yet".

## 4. Out of scope

Cost per part; revision-bound paint; paint on tools or equipment; colour
variants as separate part numbers; import from RFQ2.

## 5. Testing

Backend: paints CRUD + org scoping + duplicate name; part paint put/get
round trip, renumbering, changelog line, inactive paint kept; overview and
used-in contents. Frontend: Paints page list/form; Paint card add/remove/
reorder and save payload; Painted chip filter and count; Paint section
grouping.
