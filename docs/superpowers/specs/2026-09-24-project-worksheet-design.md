# Project worksheet, field comments and flags, linked material

Date: 2026-09-24. Status: design from chat, for review.

## Problem

Engineering keeps a per-project Excel "BOM" (example: Brose 1994 RFQ 26 BOM
clean with open points 2026-09-23.xlsx): one row per article with tool,
cavities, OEM and Tier 1 numbers, designation, drawing, material and resin,
paint, colour, MIC, weights, volume, grain, gloss, plus an open question and
answer per row, colour coded (yellow open, green confirmed, red not
acceptable). It is the place where discrepancies between drawing, RFQ and
PLM are found, and it is outside PLM.

PLM's "BOM" today is a structural bill of materials per assembly revision
(`part_bom_items`), not this overview.

## Rulings (user, 2026-09-24)

- The Excel is only an example. The worksheet is an overview of database
  data; values are changed where they live (article, tool, paint), not in
  the worksheet.
- Right click on a field: edit (jump to the place where the value is
  changed) or flag it.
- Things that are not defined yet during engineering (resin to be
  nominated, grain question, volume basis) are comments, not separate
  fields.
- Material is a real field. If the material exists it comes from the
  material database (MaterialDB) and is linked. A material that is not
  there yet must be clearly marked as new.
- Flag and comment on all fields: the easy way to find discrepancies.

## Design

### 1. Field notes: comments and flags on any field

A field is addressed by `(part_id, field_key)`; `field_key` is a stable
string from the column registry (e.g. `tool.cavities`, `part.tier1_part_number`,
`part.material`, `paint.colour`).

`field_notes` (one thread per part and field):
- `id`, `part_id` (the article or tool the value belongs to), `field_key`,
  `flag_status`: null | `open` | `confirmed` | `rejected`,
  `flag_set_by`, `flag_set_at`, `created_at`
- unique (`part_id`, `field_key`)

`field_note_comments`: `id`, `note_id`, `body` (text), `author_id`,
`created_at`; append only (no edit or delete; a correction is a new
comment).

Every flag change and comment writes a changelog entry on the part
(`field_flag_set`, `field_comment_added`) so the part history shows it.

API under `/api/v1/parts/{part_id}/field-notes`: list (optionally by
field_key), get one thread, add comment, set flag (open / confirmed /
rejected / cleared), and `/api/v1/projects/{project_id}/field-notes` for
all notes of a project (the worksheet reads this once).

UI: a small reusable `FieldNoteMarker` next to any value (dot coloured by
flag, speech-bubble count for comments) opening a popover with the thread,
"Add comment", and flag buttons. Used in the worksheet cells and on the
article/tool/paint pages next to the fields the registry lists, so a flag
set in the worksheet shows on the article and vice versa.

### 2. Material on the article, linked to MaterialDB

MaterialDB (separate suite app) holds series materials (with a 40- KTX
number) and research materials, and exposes a read-only service API
(`/materialdb/api/v1/materials`, bearer `MATERIALDB_SERVICE_TOKEN`) meant for
PLM2.

New fields on `parts` (articles only, 400 on other categories):
- `material_source`: null | `materialdb` | `new`
- `materialdb_id` (int, MaterialDB id), `material_ktx_number` (40-xxxx or
  null for research), `material_label` (cached display: number, trade
  name, grade), `material_synced_at`
- `material_new_text` (free text) when `material_source = new`

Backend proxies MaterialDB for search and pick (`GET
/api/v1/materials/search?q=`), so the browser never sees the service
token; picking stores id, number and label. A refresh endpoint re-reads the
label. If MaterialDB is unreachable, search returns a clear 503 and existing
links keep their cached label.

UI on the article: "Material" field with a search picker ("from MaterialDB")
and an explicit alternative "New material, not in MaterialDB" (free text).
Display: linked material as `40-1234 Trade name grade` with a MaterialDB
link; new material as the text with an amber `NEW, not in MaterialDB`
badge. The worksheet shows the same.

### 3. The worksheet

A "Worksheet" view on the project page next to the item list (toggle in
the items header; full width while active, the detail pane hidden).

Rows: one per article (the project's items with category article), sorted
like the list; the producing tool's values are shown on the article row.
Optional rows for tools without articles and for purchased parts via a row
filter.

Columns come from a column registry (`worksheetColumns.ts`), each entry:
`key` (= field_key), label, group, value getter, display renderer, edit
target (route + focus key), `editable_on` (article / tool / paint),
default visible. Starting set, only data PLM holds:
- Identity: thumbnail, KTX no., OEM no., Tier 1 no., name, type (article,
  purchased ...), mirror of
- Revision: E level (bold) and customer index, phase
- Material: material (linked or new)
- Paint: painted, colour / paint system (from the paint catalog link)
- Tool: tool no., cavities, toolmaker, cycle time, tonnage
- DFM: DFM status of the tool (waiting on ..., all answered, no topic)
- Notes: open flags count and last comment excerpt for the row

Behaviour: column filter (text contains, select for enums), sort per column,
show/hide columns (remembered per browser via safeStorage), first three
identity columns frozen, "only rows with open flags" filter, export to
Excel (xlsx, visible columns and rows, flag colours kept) through a backend
endpoint so numbers and dates are typed correctly.

Right click on a cell (and a "⋯" on hover for touch/keyboard):
- Edit: navigates to the edit target: the article or tool page (or the
  project page detail with the right tab) with the field highlighted and
  focused; for tool fields the tool page Tool card; for material the
  article's material field; for paint the paint section.
- Comment: opens the field note popover on that cell.
- Flag: open / confirmed / rejected / clear.
Cells with a flag are tinted yellow (open), green (confirmed), red
(rejected); a comment count shows as a small marker.

### 4. One-time data for 1994 (optional script)

`backend/scripts/import_1994_worksheet_notes.py` (dry run by default): from
the example Excel, create field comments for the open questions and answers
(on the matching part and field), set flags per the Excel colours, and set
material as `new` with the Excel text where no MaterialDB match is known;
set the four Tier 1 numbers the Excel resolves (206.882.251 S00H4X-110,
206.882.252 S00H4W-110, 206.885.967 S00G0E-110, 206.885.968 S00G0D-110).
Discrepancies found while importing (Excel cavities 4/4/2 vs PLM 2/2/4 for
199401/199402/199403) become open flags with a comment, not overwrites.

## Testing

Backend: field notes CRUD rules (append-only comments, flag transitions,
unique per field, changelog, cross-project isolation); material fields
(tools rejected, materialdb vs new states, proxy search with MaterialDB
mocked, 503 when unreachable); worksheet export xlsx content.
Frontend: column registry values, filter/sort/hide/freeze, flag tint and
filter, context menu actions (edit navigation with focus, comment popover,
flag), FieldNoteMarker on article/tool pages reflects worksheet flags,
material picker and new-material badge, export link.
Browser check on the local test stack with project 1994.

## Out of scope

Editing values inside the worksheet, custom per-project columns, writing to
MaterialDB from PLM (creating materials happens in MaterialDB), the
structural assembly BOM (unchanged).
