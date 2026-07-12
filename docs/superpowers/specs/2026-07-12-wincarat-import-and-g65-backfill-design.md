# WinCarat master-data import + G65 change backfill — design

**Date:** 2026-07-12
**Status:** Draft for review
**Author:** Claude Code (with Christoph)

## Goal

Turn the throwaway smoke-test PLM into a real, WinCarat-sourced instance:
wipe the test transactional data, import all active WinCarat projects
(articles + tools + purchased parts + assembly BOM trees with quantities)
into PLM as the authoritative master, then backfill the G65 (BMW G6X,
WinCarat project `1748`) part-history-sheet changes as auto-created,
pre-rollout closed change requests, and produce a per-department
worklist to fill in what the sheets don't carry.

This realizes the standing strategic goal ([[plm-master-datasource]]):
**PLM2 = single source of truth for tooling and projects**, sourcing
read-only from WinCarat (no TWOS carve-out).

## Decisions locked with Christoph (2026-07-12)

1. **Wipe scope:** full reset of transactional data. Delete all 11 test
   change requests + dependents, the "Test Project" (project 1) and its
   parts/gauge, **and** the TWOS-seeded VW426 Atlas (project 2) so it can
   be re-imported cleanly from WinCarat. Keep org, plants, users.
2. **Part master source:** WinCarat (Oracle `KWA` schema). Not TWOS,
   not the history sheets.
3. **Import scope:** **all active** WinCarat projects — `PROJEKTSTATUS`
   in (`SERIES`, `PRE-SERI`), 32 projects (minus zero-article and
   Silao-Mexico ones — see below).
4. **Part depth:** **full BOM depth** — tools, assemblies, components,
   **and purchased parts** (clips/fasteners), with the assembly tree
   built out and **quantities per line**.
5. **Atlas:** re-import from WinCarat (drop the TWOS-seeded copy).
6. **Plant:** everything → **USA Toccoa** for now. Weissenburg
   pre-series (e.g. G67/G69) count as USA. **Exclude Silao Mexico**
   projects (a plant needed later, not yet). Create plant records as
   needed.

## Verified environment facts

**WinCarat** = Oracle 19c, host `10.105.205.18:1521`, SID `BU`, user
`admin`, schema `KWA` (919 tables). Reachable read-only from the
`claude-twos-backend-1` container via the `oracledb` lib (creds already
in that container's env). Query pattern:
`docker exec claude-twos-backend-1 python -c "import oracledb; from app.core.config import settings; ..."`.

**PLM** live DB = Postgres `claude-plm2-db-1` (`postgresql+asyncpg://plm:plm@plm2-db:5432/plm`).
Current state: projects 1 (Test Project) + 2 (VW426 Atlas, TWOS-seeded);
11 test change requests; USA Toccoa plant (id 2).

### Key WinCarat (KWA) tables

| Table | Role | Key columns |
|---|---|---|
| `PROJEKTSTAMM` | project master | `PROJEKTNR`, `PROJEKTNREXT` (name), `BESCHREIBUNG`, `KDNR`, `PROJEKTSTATUS`, `ANZWKZ`, dates |
| `PROJEKTSTATUS` | status lookup | `SERIES`=Series, `PRE-SERI`=Pre-Series, `PROTOTYP`, `SPARE-PA` |
| `KUNDE` | customer | `KDNR`, `MATCHCODE` (name) |
| `ARTIKEL` | parts/articles | `ARTNR`, `MATCHCODE` (name), `KDARTNR` (customer no), `KDNR`, `PROJEKTNR`, `TEILEART` (W/T/M), `STUELINR` (BOM link), `ZEICHNR` (drawing), `GEWICHTNETTO`, `ZUSTAND` |
| `WERKZ` | tools | `ARTNR` (→ARTIKEL), `KAVITAET` (cavities), `ZUSTANDSTEXT`, `WARTUNGSINTERVALL`, `GESAMTPROD`, `LIEFERANTNR` |
| `STULIKO` | BOM header | `STULINR`, `BEZEICHNUNG`, `STATUS` |
| `STULIPO` | BOM position | `STULINR`, `POSNR`, `ARTNR` (child), `MENGE` (qty), `MENGEEINH` (unit), `BENENNUNG` (name), `VERSCHLEISSTEIL` (wear), `ERSATZTEIL` (spare) |
| `LIEFERANT` | supplier | supplier name for purchased parts |

`TEILEART` observed values: `W` = Werkzeug (tool), `T` = produced part
(assembly/component), `M` = misc/purchased (finished bought parts, incl.
customer `50-...` parts). Refined mapping in SP-B.

### Active project list (32; scope for SP-B)

BMW America (1302, 1377, 1383, 1400, 1432, 1451, 1539, 1544*, 1748 [G65],
1918, 100, 2037), VW Chattanooga (1416, 1418, 1433, 1435, 1456, 2141),
Volvo (1583, 1713, 1744, 1856, 1477*), Mercedes (1642, 1681*), Inteva
(1475), Novem Mexiko (1391), Yanfeng CN (1888), VW/other (1717, 1734,
93, 94). `*` = zero articles → skip. Silao-Mexico exclusion resolved at
build time via WinCarat plant field (`WERKSTAMM`/`ARTWERK`); the customer
being in Mexico (Novem Mexiko) does **not** by itself mean KTX-Silao
production. The final import list is shown to Christoph before load.

## PLM target models (already exist)

- `Part` — `project_id`, `part_number`, `name`, `description`,
  `part_type` (purchased | internal_mfg | sub_assembly), `item_category`
  (article | tool | assembly_equipment | gauge), `supplier`,
  `data_classification`, `parent_part_id`, `created_by`.
- `PartRevision` — a part's revision; **BOM lines hang off a revision,
  not the part.** Import creates one baseline revision per part.
- `PartBOMItem` — `revision_id`, `child_part_id`, `item_number`, `name`,
  `quantity`, `unit`, `position`. This carries the tree + amounts.
- `PartRelation` — `from_part_id`, `to_part_id`, `relation_type`
  (produces | checks | assembles | related). Tool→article = `produces`.
- `ChangeRequest` — statuses `captured → in_assessment → costing →
  quoted/approved → in_implementation → in_validation → released →
  closed`; terminal = `closed | rejected | cancelled`. Backfill uses
  `closed` with `closed_at` set.

## Decomposition

Too large for one plan. Four sub-projects, each with its own plan:

### SP-A — DB reset (prerequisite, destructive)

Idempotent async script (`backend/scripts/reset_transactional.py`) run
against the live Postgres. Deletes, in FK-safe order:
change dependents (`change_assessments`, `change_meetings`, `change_gate`,
`change_impacted_items`, `change_affected_plants`, `change_routings`,
`change_attachments`, `change_changelog`, `change_transition_deviations`)
→ `change_requests` → project 1 (Test Project) parts/revisions/BOM/relations
→ project 2 (Atlas) parts/revisions/BOM/relations → projects 1 and 2.
Preserve: org, plants, users, suppliers, catalog. Prints a before/after
row-count report. **Requires an explicit confirm flag** (`--yes`) and a
DB backup first (`pg_dump`). Reversible only via backup.

### SP-B — WinCarat importer (core deliverable)

`backend/scripts/import_wincarat.py`, idempotent, following the
`import_atlas.py` pattern (match on `(project_id, part_number)`; skip or
update existing; re-runnable). One Oracle connection, SELECT-only,
processed per project, committed per project.

**Extraction (per active project `PROJEKTNR`):**
1. Project header from `PROJEKTSTAMM` + customer name from `KUNDE`.
2. All `ARTIKEL where PROJEKTNR = :p`.
3. Tool enrichment: join `WERKZ` by `ARTNR` for `TEILEART='W'`.
4. BOM: for each article with `STUELINR`, read `STULIKO`+`STULIPO`
   positions (child `ARTNR`, `MENGE`, `MENGEEINH`, `POSNR`, `BENENNUNG`,
   wear/spare flags).
5. Supplier name from `LIEFERANT` for purchased parts.

**Mapping WinCarat → PLM:**
- **Project** → `Project` (code=`PROJEKTNR`, name=`PROJEKTNREXT` or
  `BESCHREIBUNG`, plant=USA Toccoa, status=active, description carries
  customer + WinCarat status). Skip if Silao or zero-article.
- **Part** (`ARTIKEL` row) → `Part`:
  - `TEILEART='W'` → `item_category=tool`, `part_type=purchased`;
    enrich description with cavities / condition / maint-interval /
    total-shots from `WERKZ`.
  - `TEILEART='T'` → `item_category=article`; `part_type=sub_assembly`
    if it has a `STUELINR`/BOM, else `internal_mfg`.
  - `TEILEART='M'` (and any part with a supplier / `50-...` customer
    number) → `item_category=article`, `part_type=purchased`,
    `supplier` set. **These are the clips/fasteners** — always imported.
  - `part_number=ARTNR`, `name=MATCHCODE` (fallback `TEXT`),
    `description` composed from MATCHCODE + customer no (`KDARTNR`) +
    drawing (`ZEICHNR`) + net weight, `data_classification=confidential`.
- **Baseline revision**: one `PartRevision` per part (name `WC-IMP`,
  phase engineering, status approved) so BOM items have an owner.
- **BOM tree**: for each assembly, a `PartBOMItem` per `STULIPO` line on
  its baseline revision — `child_part_id`=lookup(child ARTNR),
  `item_number`/`position`=`POSNR`, `name`=`BENENNUNG`, `quantity`=`MENGE`,
  `unit`=`MENGEEINH`, notes flag wear/spare. Multi-level (children that
  are themselves assemblies get their own BOM). Purchased children are
  created as parts and included with their amount.
- **Tool→article `produces` relation**: reuse the Atlas numbering
  heuristic (tool `3342` → articles whose middle segment is `3342`, e.g.
  `20-3342-001-0`), noted as WinCarat-derived. If a cleaner WinCarat
  tool→part link surfaces during build (`ARBPLAKOWKZ` workplan links),
  prefer it and note the switch.

**Ordering within import:** create all parts first (so BOM/relation
lookups resolve), then revisions, then BOM items, then relations —
handling forward references across projects (a child may live in another
project). Unresolved child references are logged, not fatal.

**Scale:** ~32 projects, low thousands of parts/BOM lines. Batch inserts,
per-project commit, lookup caches. Print a per-project summary
(parts created/skipped, BOM lines, relations) and a final total.

### SP-C — G65 history-sheet change backfill (depends on SP-B)

`backend/scripts/backfill_g65_changes.py`. Source: the 5 sheets in
`docs/PartHistorySheets/G65/extracted/` (parts 5A5D970/10-3342,
5A5D994/10-3346, 5A627C0/10-3354, 9634517/10-3369-001, 9634518/10-3369-002,
+ C-Clip 50-0331) → PLM project `1748`. Each populated row (from row 16;
~41 total) → a `ChangeRequest`:
- `project_id` = 1748's PLM id, `status='closed'`, `closed_at` set,
  `raised_at` = sheet row date if present else project start.
- `title` = occasion/process (col C) trimmed; `description` = full row
  (change description, customer level, EC number, internal level,
  drawing index, agreed name/date).
- `change_number` = dedicated backfill series (e.g. `G65-PHS-0001`),
  distinct from the live `CR-2026-****` sequence.
- Marked auto-created/pre-rollout: `issuer='Part History Sheet (backfill)'`,
  description prefixed "Backfilled from part history sheet; implemented
  prior to PLM rollout.", `cm_internal=true`.
- Link the affected assembly via `change_impacted_items` → the WinCarat
  part for that sheet (matched by the sheet's ZSB `20-33xx-001-0`).
- Inserted directly at `status=closed` (bypassing the transition service,
  which would enforce gates these pre-PLM changes never had).

Idempotent on `change_number`. Built generically so VW426's sheets can
run through the same importer when they arrive.

### SP-D — Department backfeed tasklist (depends on SP-C)

A generated report (`docs/PartHistorySheets/G65/backfeed-tasklist.md`,
optionally a worklist doc) enumerating, per backfilled change, the PLM
fields the history sheet did **not** supply — cost lines, feasibility/
assessment verdicts, affected-item detail beyond the top assembly, RASIC
routing, gate decisions, quoted price — grouped by the department that
owns each (Engineering, Quality, PM, Sales, Costing). Output only; no
schema change. This is the "please fill in X for these N backfilled
changes" list per department.

## Sequencing

SP-A (backup + wipe) → SP-B (import, review project list first) →
SP-C (backfill) → SP-D (tasklist). SP-A and SP-B are the priority; each
sub-project is validated before the next. Nothing is pushed to main
without Christoph's go-ahead.

## Risks / open items

- **Silao exclusion mechanism** — confirm the WinCarat field that marks a
  project's KTX production plant; until confirmed, show Christoph the
  full active-project list and exclude by agreement.
- **Tool→article link fidelity** — numbering heuristic is a fallback;
  prefer an explicit WinCarat link if found.
- **Multi-project BOM children** — a child part referenced by one
  project's BOM may belong to another project; import must resolve across
  the whole active set (create all parts before BOM linking).
- **Idempotency vs. WinCarat drift** — re-runs update descriptions but do
  not delete parts removed in WinCarat; a later reconcile pass can handle
  that if needed (out of scope now).
- Destructive SP-A is gated behind a `pg_dump` backup + explicit confirm.
