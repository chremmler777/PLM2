---
name: paint-catalog-2026-09-21
description: Paint catalog + per-article paint setup + project paint overview shipped 2026-09-21; decisions, rulings, follow-ups
metadata:
  type: project
---

Built 2026-09-21 on `main` (migration 073, three tables, ten feature commits plus a fix wave).

**What it is.** Paints are org-scoped master data on a Paints page (`/paints`): name, type (primer/basecoat/clearcoat/one_coat/other), colour code, colour name, hex swatch, supplier text (API also takes a validated `supplier_id`), spec reference, notes, active flag; no delete, deactivate only. An article's paint setup hangs off the part (not the revision): paint required, process, notes, ordered layers from the catalog; one Save writes the whole setup and logs a `paint_updated` changelog line; saving with the toggle off clears layers/process/notes on the server but keeps the draft on screen. Project page: `🎨 Painted (n)` chip, top-layer swatch on rows, collapsible Paint section grouped by paint. Spec `docs/superpowers/specs/2026-09-21-paint-catalog-design.md`, guide `docs/PAINT.md`.

**Why:** Christoph wanted paint in PLM "like in RFQ, with different paints" and a paint overview on articles; RFQ2 only has free-text paint fields per BOM item.

**How to apply:** New paints go in the catalog first, then articles reference them. Engineering data only: no cost per part (stays in RFQ2 and change costing). Part-level, not revision-bound, by decision; revision-bound paint is a possible later extension. Import from RFQ2 was out of scope.

**Follow-ups not done:** per-layer notes have no input on the card (field exists in API); no supplier picker in the UI; search on the Paints page is not debounced; the part card does not invalidate the project overview query (fine while the pages are separate routes and staleTime is 0). Backend tests: `uv run --no-sync pytest`. Related: [[customer-package-receive-2026-09-18]].
