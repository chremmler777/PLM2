# Master BOM and Tooling Board — Design

Date: 2026-09-08. Status: approved in conversation, pending written review.

## Purpose

PLM2 takes over a project after the RFQ phase. The RFQ tool (RFQ2, a sibling
app in the suite) has two layouts that proved themselves with users: a master
bill of materials grouped by assembly with mirrored left/right parts and
per-row engineering details, and a tooling tab that assigns articles to tools
from a grouped article rail. This design brings those two layouts into PLM2 as
PLM2 features, on PLM2's own part data. There is no runtime link to RFQ2 and
no data import; the benefit is a familiar, repeated layout across the suite.

Out of scope: the RFQ2 sketcher and mold layout, tool sizing and cost
calculation, projected surface, and any RFQ2 to PLM2 data transfer.

## Decisions taken

1. The master BOM replaces the flat parts tree on the project page as the main
   view of a project's parts.
2. A group is a sub-assembly part (`part_type = sub_assembly`); its current
   revision's BOM items are the rows. Articles that belong to no assembly form
   an "Unassigned" group. No separate group record.
3. A mirror pair is a `mirror_of` part relation, shown on both parts.
4. Rows show identity plus engineering basics: name, customer part number,
   category, current revision and status, material, weight, box size, finish.
5. The engineering attributes live on the revision, so a frozen revision keeps
   the values it was approved with.
6. Readiness stays light: empty attribute cells are highlighted and each group
   shows a filled/total count. No banner and no gate coupling.
7. The six attributes are editable inline while the current revision is not
   frozen; identity and revision management stay on the part page.
8. Tool cards carry the tool's identity, its linked articles with cavities per
   article, supplier and revision status. No cost or lead time.
9. One board covers tools, gauges and assembly equipment with a switch, since
   all three are article-to-item relations (`produces`, `checks`, `assembles`).

## Data model

All changes are one Alembic migration (`066_master_bom.py`), additive, with
nullable columns so existing rows need no backfill.

`part_revisions` gains:

| column | type | note |
|---|---|---|
| `material` | String(120), nullable | e.g. "PC/ABS" |
| `weight_g` | Float, nullable | grams |
| `box_x_mm`, `box_y_mm`, `box_z_mm` | Float, nullable | bounding box |
| `finish` | String(255), nullable | surface / paint spec |

`parts` gains, used only for sub-assemblies but allowed on any part:

| column | type |
|---|---|
| `peak_annual_volume` | Integer, nullable |
| `lifetime_volume` | Integer, nullable |

`part_relations`:

- `relation_type` accepts a new value `mirror_of`. A mirror is stored once
  (`from_part_id` < `to_part_id` is not required; the service treats the pair
  as symmetric when reading). Creating a second mirror for a part that already
  has one is refused with 409; a part has at most one mirror.
- New column `cavities` (Integer, nullable), meaningful for `produces` and
  ignored for other types.

No changes to `part_bom_items`.

## API

All routes sit under the existing parts router prefix and use the existing
authentication dependency; no new permission model.

### `GET /v1/projects/{project_id}/master-bom`

One composed read. Response:

```
{
  "groups": [
    {
      "part_id": 12, "name": "Cover assembly LHD", "customer_part_number": "9656732",
      "revision_id": 40, "revision_name": "ENG1", "revision_status": "in_progress",
      "peak_annual_volume": 41000, "lifetime_volume": 159000,
      "filled": 3, "total": 5,
      "rows": [ <row>, ... ]
    },
    ...,
    { "part_id": null, "name": "Unassigned", "rows": [ <row>, ... ], "filled": 0, "total": 0 }
  ],
  "relation_kinds": { "tool": "produces", "gauge": "checks", "assembly_equipment": "assembles" }
}
```

A row:

```
{
  "part_id": 15, "bom_item_id": 77, "item_number": "10", "quantity": 1, "unit": "pcs",
  "name": "Cover SHUD LHD", "customer_part_number": "9656732", "item_category": "article",
  "part_type": "internal_mfg",
  "revision_id": 51, "revision_name": "ENG1", "revision_status": "in_progress", "frozen": false,
  "material": "PC/ABS", "weight_g": 203.6, "box_x_mm": 401.8, "box_y_mm": 338, "box_z_mm": 27.64,
  "finish": "EDM grain Feinnarbe L",
  "mirror_part_id": 16, "mirror_name": "Cover SHUD RHD",
  "linked": { "tool": [{"part_id": 30, "name": "T-0412", "cavities": 1}], "gauge": [], "assembly_equipment": [] }
}
```

Rules:

- Groups are sub-assembly parts of the project, ordered by name. Rows come
  from the group's current revision's `part_bom_items` that reference a
  project part (`child_part_id`); catalog and free-text items are listed as
  rows with `part_id: null` and only `name`, `quantity`, `unit` filled.
- "Current revision" is the part's latest revision by creation, which is how
  the part page picks it today; the row reports whether it is frozen
  (`revision_status == "frozen"`).
- The `Unassigned` group lists articles of the project that appear in no
  sub-assembly BOM. Tools, gauges and assembly equipment are never rows.
- `filled` counts rows whose six attributes are all non-empty; `total` counts
  rows with a `part_id`.
- Thumbnails: PLM2 stores CAD as glTF and has no rendered preview image, so the
  row carries no image URL in this version. The UI shows a category glyph in
  that column; a preview endpoint can be added later without changing the
  shape.

### `PATCH /v1/parts/revisions/{revision_id}/attributes`

Body: any subset of the six attributes. Refused with 409 `"Revision is frozen"`
when the revision's status is `frozen`. Returns the updated revision.

### `PATCH /v1/parts/{part_id}/volumes`

Body: `peak_annual_volume`, `lifetime_volume` (either optional). Any part.

### Relations

- `POST /v1/parts/{part_id}/relations` (existing) accepts `relation_type:
  "mirror_of"` and an optional `cavities` integer. Mirror creation enforces the
  one-mirror rule and refuses a self-mirror.
- New `PATCH /v1/parts/relations/{relation_id}` with body `cavities`.
- `DELETE` unchanged.

### `GET /v1/projects/{project_id}/tooling-board?kind=tool|gauge|assembly_equipment`

```
{
  "kind": "tool", "relation_type": "produces",
  "assemblies": [ { "part_id": 12, "name": "...", "customer_part_number": "...",
                    "peak_annual_volume": 41000, "lifetime_volume": 159000,
                    "articles": [ { "part_id": 15, "name": "...", "customer_part_number": "...",
                                    "weight_g": 203.6, "assigned": true } ] } ],
  "items": [ { "part_id": 30, "name": "T-0412", "part_number": "T-0412", "supplier": "...",
               "revision_name": "ENG1", "revision_status": "in_progress",
               "articles": [ { "part_id": 15, "name": "...", "relation_id": 91, "cavities": 1 } ] } ],
  "articles_total": 13, "articles_assigned": 4
}
```

Unassigned articles appear under their assembly with `assigned: false`; the
"Unassigned" assembly follows the same rule as the master BOM. An article is
assigned when it has at least one relation of the requested type.

## Master BOM view

`frontend/src/components/bom/MasterBomSection.tsx` replaces the parts tree on
the left of the project detail page. The right-hand part detail panel keeps
working: clicking a row name selects the part exactly as the tree did.

- Group header: assembly name, customer number, revision chip, row count,
  volumes (editable inline, two small number inputs), completeness
  `filled/total` as a chip; collapsible.
- Rows in this column order: glyph, name, customer number, category, revision
  and status chip, material, weight (g), box (x × y × z mm), finish, links
  (small icons with counts for tool, gauge, equipment), mirror badge.
- Empty attribute cells render with the amber "missing" treatment used by the
  forms renderer; nothing is blocked.
- Inline editing: material, weight, box, finish are inputs when the row's
  revision is not frozen and the user has edit rights on the part page today.
  Saving is per cell on blur through the attributes endpoint, with the toast
  pattern used elsewhere. Frozen rows are read-only with a lock icon and
  "Frozen revision" title.
- Mirror badge: shows the partner's name on hover; clicking selects the
  partner. Mirrors are created from the part page's relations section by
  choosing type "Mirror of" (existing UI, new option).
- Column picker: a small menu toggling material, weight, box, finish, links;
  stored in local storage per user.
- "Add part" and "Add assembly" buttons keep the existing create flows.
  Assembly membership is edited on the assembly's BOM section, as now.
- Loading: skeleton rows. Empty project: one dashed empty state with the two
  add buttons.

Styling follows the PLM2 system already used by the SEP forms: slate-800
cards with hairline borders, rounded-lg inputs, sky-600 primary actions,
tabular numerals, Geist.

## Tooling board

`frontend/src/components/bom/ToolingBoard.tsx`, shown as a "Tooling" tab next
to the master BOM (a two-tab header: "Master BOM" / "Tooling & equipment").

- Switch: Tools, Gauges, Assembly equipment. Progress bar and counts on the
  right of the switch.
- Left rail: search box, "hide assigned" checkbox, assemblies as headers with
  volumes, article rows with customer number and weight; assigned articles
  show a small check.
- Right area: one card per item of the selected kind: name and number,
  supplier, revision status chip, list of linked articles with an editable
  cavities field (tools only) and a remove control; an "Assign article" picker
  listing articles from the rail (search inside). "New" opens the existing
  create-part dialog with the item category preset. Empty state when no items
  exist.
- Assign creates the relation of the kind's type from the item to the
  article; remove deletes it. Both invalidate the board and the master BOM
  queries.

## Error handling

- 409 from the attributes endpoint on a frozen revision surfaces as a toast
  and the cell reverts.
- Mirror rule violations (second mirror, self-mirror) return 409 with a plain
  message shown in the relations section.
- Board assign on an article already linked to that item returns 409; the
  picker hides already-linked articles so this only happens in a race.

## Testing

Backend (`backend/tests/test_master_bom.py`):

- Master BOM grouping: two assemblies, one article in each, one article in
  none → three groups, unassigned last; catalog item appears with
  `part_id: null`.
- Completeness counts and `frozen` flag.
- Attributes PATCH: updates and 409 on frozen.
- Mirror: creation, symmetry in the master BOM rows, second mirror 409,
  self-mirror 409.
- Cavities on create and PATCH; ignored for `checks`.
- Tooling board for each kind: assigned flags, counts, items with articles.

Frontend (`frontend/src/components/bom/*.test.tsx`):

- MasterBomSection renders groups, rows, missing highlights, completeness
  chip; inline edit calls the attributes endpoint; frozen rows have no inputs.
- ToolingBoard renders the rail and cards, assign and remove call the relation
  endpoints, the progress bar reflects counts.

Run backend tests with `cd backend && python3 -m pytest tests/test_master_bom.py -q`
and frontend tests with `cd frontend && npx vitest run src/components/bom`.

## Migration and rollout

Migration 066 adds columns only. No data migration. The old parts tree code is
removed from the project page in the same change; the part detail panel and
its sections are untouched. Deployment note: run `alembic upgrade head`, no
image rebuild needed.

## Later, not now

Rendered CAD thumbnails for the glyph column; SEP gate rules on attribute
completeness; prefilling the sales handover parts table from the master BOM;
carrying PLM2's design tokens back into RFQ2.
