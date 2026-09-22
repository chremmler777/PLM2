# Article view: revision strip, document pane, mirrors, hierarchy

Date: 2026-09-22. Status: design approved by delegation ("do what you think
is right"), plan follows.

## Problem

The project page's part panel shows one flat revision dropdown (E1 and E1.1
look the same), a 3D viewer, and a file list whose only actions are
"View 3D" and "Download". Drawings cannot be opened, mirrored parts have no
representation at all (`mirror_of` is refused by the API), tools never appear
next to their article, and nothing reads like the revision browser of a
standard PLM system. After the 1994 reset, prod has real data for all of
this: 12 articles with `E1 · 003`, PCA/DMU/DRW/STEP files, two mirrors with
no own 3D, and one investigation proposal `E1.1`.

## Rulings (user, 2026-09-22)

- Mirrors are stated, not copied: the mirror part carries a `mirror_of`
  relation; the viewer shows the source part's model with a **red warning**
  that the part is mirrored.
- Drawings must open in the app.
- `E1.1` must be visible on the article as a proposal.
- The overview must read like a standard PLM system: hierarchies, easy to
  understand. Design choices delegated.

## Design

Two-pane shape on the project page, which is where people work today:
**structure on the left, the selected article on the right**. The part
page keeps its timeline and gains the same document pane.

### 1. Left: structure tree with article children

The existing project items list becomes expandable per article. An
expanded article node shows two child groups, indented, read-only:

```
▾ 20-1994-008-0  206.886.197 Center bearing cover        nominated
    Revisions   E1 · 003 (active) · E1.1 proposal
    Tools       199406 Center bearing cover
▸ 20-1994-002-0  206.882.252 Handle, height adjustment RH  ⇄ mirror of 251
```

- Revisions line: majors in order, each followed by its minors; the active
  one bold; a proposal shown with a "proposal" chip. Clicking a revision
  selects the article and that revision on the right.
- Tools line: parts related by `produces` (tools), `checks` (gauges),
  `assembles` (equipment), by part number and name. Clicking opens that
  part.
- Mirror parts show a `⇄ mirror of <number>` chip in the row; the source
  part shows `⇄ mirrored by <number>`.
- Data: the tree uses the existing project parts query plus one new
  endpoint `GET /api/v1/parts/project/{project_id}/structure` returning,
  per article, its revisions (id, name, customer_index, status, parent id,
  is_active) and its related parts (type, id, number, name) and mirror info.
  One call per project page load, no N+1.

### 2. Right: article panel

Top to bottom:

1. **Header**: part number, name, phase chip, and when mirrored a red-bordered
   chip `⇄ Mirror of 206.882.251 · LH data` linking to the source.
2. **Revision strip** replaces the dropdown. Majors as tabs left to right
   (`E1 · 003`, `E2 · 004`, `1`), each tab with its minors nested under it as
   smaller sub-tabs (`E1.1 proposal · draft`). Active revision marked, frozen
   or rejected greyed. The "+ Customer package" and, when the part has no
   revisions, "+ Customer data" buttons stay; a "+ Proposal" button appears
   on the selected major (same endpoint the part page uses).
3. **Document pane**: one area that shows either the 3D viewer or a PDF.
   - 3D: as today. When the selected revision has no viewable 3D and the
     part is a mirror, load the **source part's active revision** viewer and
     draw a red banner across the top: "Mirrored part. Showing 206.882.251
     (LH). Geometry is the mirror image, RPS and references differ." with a
     link to the source.
   - PDF: `<iframe>` on the new inline route. Same mirror rule: a mirror
     with no own drawing shows the source's drawing with the red banner.
   - Pane header shows which file and which revision is displayed.
4. **Files**, grouped: **3D** (PCA, DMU, STEP with kind chips and notes),
   **2D** (drawings), **Documents** (rest). Per row: `Open` for PDFs and
   pictures, `View 3D` for viewable CAD, `Download` always, `Delete` when
   unlocked. The group headers show counts. Upload drop zone stays under the
   list (guided dialog from the previous feature).
5. **Relations** as chips under the files: tools, gauges, equipment, mirror.
   Existing relations section stays for editing.

### 3. Mirror relation

- `mirror_of` joins `VALID_RELATION_TYPES`. Rules in the service: one mirror
  per part, no self-mirror, the source must be an article of the same
  project. Creating a second one → 409. Labels: from the mirror
  "mirror of", from the source "mirrored by".
- Relations UI offers it in the type select for articles.
- The structure endpoint returns `mirror_of: {part_id, part_number,
  customer_part_number}` on the mirror and `mirrored_by: [...]` on the
  source.

### 4. Inline documents

- `GET /api/v1/parts/revision-files/{file_id}/inline`: same auth and
  soft-delete checks as download, `Content-Disposition: inline`, real
  media type from the row (`application/pdf`, `image/png` …). Only for
  `pdf`, `png`, `jpg`, `jpeg`, `gif`, `webp`; other types → 415.
- Download route unchanged.

### 5. Part page

Gets the same document pane and grouped file list under its timeline; the
timeline already nests minors under majors, so it stays.

### 6. Out of scope

- Editing BOM structure from the tree.
- Assembly explode / multi-part views beyond what exists.
- Renaming or renumbering.
- Mirror geometry generation (we never mirror physically).

## Testing

- Backend: structure endpoint shape and no-N+1 (one query per table),
  mirror rules (one per part, self, cross-project, 409), inline route
  (content type, inline disposition, 415, 404, deleted file).
- Frontend: tree node expansion and child click selection, revision strip
  rendering majors/minors and selection, document pane switching 3D/PDF,
  mirror fallback and banner text, file grouping and Open buttons, relation
  chips, part page pane. Existing page tests stay green.
