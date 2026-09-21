# Paint catalog

How PLM records paint on articles: the paint catalog, an article's paint
setup, and the project paint overview. Written for the people who set up
painted articles and the people who maintain the paint catalog. Design
background: `docs/superpowers/specs/2026-09-21-paint-catalog-design.md`.

## What a paint is

A paint is org-scoped master data, edited once and reused across articles:
name, type (`primer`, `basecoat`, `clearcoat`, `one_coat`, `other`), colour
code (e.g. `RAL 9005`), colour name, an optional colour swatch (hex),
supplier (free text — a supplier link exists in the API), a spec reference
(datasheet or spec number), and notes. Paint names are unique per organization.

Paints are never deleted, only deactivated. An article's layers can still
reference an inactive paint; it keeps rendering, tagged as inactive.

## Setting up an article's paint

On the part page, the **Paint** card sits under Part Information:

1. Turn on **Paint required**.
2. Enter the process (free text, e.g. spray, electrocoat) and any notes.
3. Add layers in order (e.g. primer, then basecoat, then clearcoat) by
   picking from the active paints. Each layer can carry an area note (e.g.
   "A-side only"). Reorder or remove layers as needed.
4. **Save** writes the whole setup at once and logs one `paint_updated` line
   on the part's changelog describing the change.

Saving with the toggle off clears any stored layers, process, and notes for
that part. A part marked as paint required with no layers shows "paint spec
missing" on the card.

Paint hangs off the part, not the revision: it is engineering data, not
tied to a specific revision's history. Every change is still visible in the
part changelog.

## Where the overview is

- **Paints page** (`/paints`, sidebar "🎨 Paints"): the full catalog as a
  searchable table, with a toggle to show inactive paints. New and edit
  forms live here. Expanding a row shows every article across projects that
  uses that paint (its used-in list).
- **Project page**: the category chips gain a 🎨 **Painted** chip with a
  count of articles that require paint; painted rows show a small swatch of
  their top layer. A collapsible **Paint** section lists painted articles
  grouped by paint, each group headed by the paint's swatch, name, type, and
  colour code.

## API

| Call | Purpose |
|---|---|
| `GET /api/v1/paints?active_only=true&q=` | List paints of the org |
| `POST /api/v1/paints` | Create a paint; 201, 409 on duplicate name, 400 on invalid input |
| `GET /api/v1/paints/{id}` | One paint; 404 if not found |
| `PUT /api/v1/paints/{id}` | Update a paint, including `is_active`; 409 on duplicate name, 404 if not found |
| `GET /api/v1/paints/{id}/used-in` | Articles across projects using this paint; 404 if the paint does not exist |
| `GET /api/v1/parts/{id}/paint` | A part's paint setup with layers; 200 with `paint_required=false, layers=[]` when none is stored yet; 404 if the part is not in the org |
| `PUT /api/v1/parts/{id}/paint` | Replace a part's whole paint setup; layers are renumbered from the list order and the change is logged; 400 on invalid input; 404 if the part is not in the org |
| `GET /api/v1/parts/project/{id}/paint-overview` | Every part in the project with its paint setup, for grouping client-side; 404 if the project is not in the org |

There is no delete on paints, only deactivation. Deleting a part cascades
its paint setup and layers.

## Out of scope

Cost per part (stays in RFQ2 and change costing); revision-bound paint
history; paint on tools or equipment; colour variants as separate part
numbers; import from RFQ2.
