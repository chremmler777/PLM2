# WinCarat Import + DB Reset Implementation Plan (SP-A + SP-B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wipe the test transactional data from the live PLM Postgres, then import all active WinCarat projects (parts, tools, purchased parts, assembly BOM trees with quantities, tool→article relations) into PLM as the authoritative master.

**Architecture:** Two idempotent, re-runnable async Python scripts under `backend/scripts/`, run with the backend's venv against the live Postgres. A read-only WinCarat extraction module queries Oracle (`KWA` schema) through the same `oracledb` pattern the TWOS `wincarat.py` uses. The importer creates all parts first (so cross-project BOM/relation lookups resolve), then baseline revisions, then BOM items, then relations, committing per project.

**Tech Stack:** Python 3.11, SQLAlchemy async (asyncpg), `oracledb`, existing PLM models (`Part`, `PartRevision`, `PartBOMItem`, `PartRelation`, `Project`, `Plant`).

## Global Constraints

- Live PLM DB: `postgresql+asyncpg://plm:plm@plm2-db:5432/plm` (container `claude-plm2-db-1`). Scripts run inside `claude-plm2-backend-1` (has models + asyncpg + env `DATABASE_URL`).
- WinCarat: Oracle, host `10.105.205.18:1521`, SID `BU`, user `admin`, schema `KWA`. Only reachable from `claude-twos-backend-1` (has `oracledb` + WINCARAT_* env). **The extraction step runs there and writes JSON to a shared file; the load step runs in the PLM container.** SELECT-only against WinCarat, always.
- `ORG_ID = 1`, `CREATED_BY = 3` (chris), default plant = USA Toccoa (existing id 2). Follow `backend/import_atlas.py` conventions (idempotent match on `(project_id, part_number)`; skip/update existing).
- Active project filter: `PROJEKTSTATUS in ('SERIES','PRE-SERI')`, skip zero-article projects, exclude Silao-Mexico projects (final list confirmed with Christoph before load).
- Destructive SP-A is gated behind a `pg_dump` backup + explicit `--yes` flag.
- `data_classification = "confidential"` on all imported parts.

---

## SP-A — DB Reset

### Task A1: Reset script with dry-run report

**Files:**
- Create: `backend/scripts/reset_transactional.py`

**Interfaces:**
- Produces: a CLI script. `python scripts/reset_transactional.py` prints a dry-run report (counts to be deleted); `--yes` performs the deletes inside one transaction.

**What it deletes** (FK-safe order), then commits only with `--yes`:
1. Change dependents by `change_id`: `change_transition_deviations`, `change_changelog`, `change_attachments`, `change_routings`, `change_affected_plants`, `change_impacted_items`, `change_gate`, `change_meetings`, `change_assessments` — and any cost-line tables referencing changes (discover via `information_schema` at runtime, don't hardcode a stale list).
2. `change_requests` (all rows).
3. For projects 1 (Test Project) and 2 (VW426 Atlas): `part_bom_items` (via revisions), `part_relations` (via parts), `part_revisions` (via parts), `part_files`/`revision_changelog` (via parts), `parts`, then the `projects` rows.
- Preserve: `organizations`, `plants`, `users`, `suppliers`, `catalog_parts`.

- [ ] **Step 1: Discover FK-dependent tables at runtime**

Query `information_schema` for all tables with a FK to `change_requests` and to `parts`/`part_revisions`, so deletion order is derived, not hardcoded. Print the discovered dependency set.

```python
# inside the script, before deleting:
async def dependents_of(conn, table):
    rows = await conn.execute(text("""
        SELECT tc.table_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name
        JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name=ccu.constraint_name
        WHERE tc.constraint_type='FOREIGN KEY' AND ccu.table_name=:t
    """), {"t": table})
    return rows.fetchall()
```

- [ ] **Step 2: Build the dry-run report**

For each table to be touched, `SELECT count(*)` of the rows that match the deletion predicate (all change_requests; parts/revisions/bom where project_id in (1,2)). Print a table: `table | rows_to_delete`. No writes.

- [ ] **Step 3: Run dry-run and verify counts**

Run: `docker exec claude-plm2-backend-1 python scripts/reset_transactional.py`
Expected: report shows `change_requests: 11`, Test Project + Atlas parts (project 1: 5 parts; project 2: 20 parts), and 0 rows for preserved tables. No changes to the DB (verify with a follow-up `SELECT count(*) FROM change_requests;` still 11).

- [ ] **Step 4: Backup then real run**

```bash
docker exec claude-plm2-db-1 pg_dump -U plm -d plm -Fc -f /tmp/plm-before-reset.dump
docker cp claude-plm2-db-1:/tmp/plm-before-reset.dump ./backend/plm-before-reset.dump
docker exec claude-plm2-backend-1 python scripts/reset_transactional.py --yes
```
Expected: "Deleted 11 change_requests, N part rows, 2 projects" summary; a re-run of the dry-run now reports 0 across the board.

- [ ] **Step 5: Verify preserved data intact**

Run: `docker exec claude-plm2-db-1 psql -U plm -d plm -c "SELECT count(*) FROM users; SELECT count(*) FROM plants; SELECT id,name FROM projects;"`
Expected: users/plants unchanged; `projects` empty (both removed).

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/reset_transactional.py
git commit -m "feat(seed): idempotent transactional-data reset script (SP-A)"
```

---

## SP-B — WinCarat Importer

### Task B1: WinCarat extraction module (read-only, runs in TWOS container)

**Files:**
- Create: `backend/scripts/wincarat_extract.py`

**Interfaces:**
- Produces: `python wincarat_extract.py --out /tmp/wincarat.json` — connects to Oracle, extracts active projects + their parts + tool enrichment + BOM positions, writes one JSON document. Standalone (imports only `oracledb` + reads WINCARAT_* env directly, since it runs in the TWOS container which lacks PLM models).

**JSON shape:**
```json
{
  "projects": [
    {"projektnr":"1748","name":"G6X UBV","beschreibung":"...","kdnr":21225,
     "customer":"BMW AMERICA","status":"PRE-SERI","werk":"...",
     "parts":[
       {"artnr":"3342","matchcode":"1748 TOOL MAS VO BASIS BMW G6X","kdartnr":null,
        "teileart":"W","stuelinr":null,"zeichnr":"...","gewichtnetto":0.0,"zustand":"F",
        "tool":{"kavitaet":1,"zustandstext":"...","wartungsintervall":50000,"gesamtprod":123,"lieferant":"..."},
        "supplier":null,
        "bom":[{"posnr":"10","child_artnr":"20-3342-001-0","menge":1.0,"einheit":"pcs",
                "benennung":"...","verschleissteil":false,"ersatzteil":false}]}
     ]}
  ]
}
```

- [ ] **Step 1: Connection + active-project query**

Reuse the connect pattern from `claude-twos-backend-1:/app/app/services/wincarat.py` (`oracledb.connect(..., params=ConnectParams(host,port,sid))`). Read creds from `os.environ["WINCARAT_HOST"]` etc. Query `PROJEKTSTAMM` joined to `KUNDE` for `PROJEKTSTATUS in ('SERIES','PRE-SERI')`.

- [ ] **Step 2: Determine the Silao/plant field**

Query the project's production plant. Check `ARTWERK` (article→plant) and `WERKSTAMM` for the projects' articles; determine the code that means Silao/Mexico. Print, for each active project, the distinct plant code(s) of its articles so Christoph can confirm which to exclude. Until confirmed, tag each project `werk=<code>` in the JSON and exclude none automatically.

Run: `docker exec claude-twos-backend-1 python /path/wincarat_extract.py --plants-only`
Expected: a per-project plant-code listing to review.

- [ ] **Step 3: Per-project parts + tool + BOM extraction**

For each project: `SELECT ... FROM KWA.ARTIKEL WHERE PROJEKTNR=:p`. For `TEILEART='W'` rows, left-join `WERKZ` by `ARTNR` for the tool block. For rows with `STUELINR`, query `STULIPO` (join `STULIKO`) for BOM positions. Supplier via `LIEFERANT` when present. Assemble the JSON above.

- [ ] **Step 4: Run extraction and sanity-check project 1748**

Run: `docker exec claude-twos-backend-1 python /path/wincarat_extract.py --out /tmp/wincarat.json` then inspect.
Expected: project 1748 present with ~134 parts, tools `3342/3354/3369` carrying a `tool` block, and at least one part with a non-empty `bom` array whose lines have `menge`. Copy JSON out: `docker cp claude-twos-backend-1:/tmp/wincarat.json ./backend/scripts/wincarat.json`.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/wincarat_extract.py
git commit -m "feat(seed): read-only WinCarat extraction to JSON (SP-B/1)"
```

### Task B2: PLM loader — projects + parts

**Files:**
- Create: `backend/scripts/import_wincarat.py`

**Interfaces:**
- Consumes: `wincarat.json` from B1.
- Produces: `python scripts/import_wincarat.py --in scripts/wincarat.json` — idempotent load into PLM. This task lands projects + parts only (revisions/BOM/relations in B3/B4).

**Mapping (from spec):**
- Project → `Project(code=projektnr, name=name or beschreibung, plant_id=USA_TOCCOA, status="active", description=f"WinCarat {status}; customer {customer}")`. Skip zero-part and excluded-plant projects (`--exclude 1391,...` flag, default from confirmed list).
- Part `TEILEART` → `(item_category, part_type)`: `W`→(`tool`,`purchased`); `T`→(`article`, `sub_assembly` if `stuelinr` else `internal_mfg`); `M` or has supplier → (`article`,`purchased`). `name=matchcode`, `description` composed from matchcode + `KDARTNR` + `zeichnr` + weight (+ tool block for tools), `supplier` set for purchased.

- [ ] **Step 1: Load JSON, ensure plant, upsert projects**

Ensure USA Toccoa plant exists (by code `usa-toccoa`). For each non-excluded, non-empty project, upsert `Project` by `code`. Print created/updated per project.

- [ ] **Step 2: Upsert parts (idempotent on project_id+part_number)**

Iterate every project's parts; map via the TEILEART table; skip if `(project_id, part_number)` exists (update description on re-run). Cache `part_id_by_(projektnr,artnr)` for B3/B4.

- [ ] **Step 3: Run and verify counts**

Run: `docker exec claude-plm2-backend-1 python scripts/import_wincarat.py --in scripts/wincarat.json`
Expected summary: N projects, M parts created. Verify: `psql -c "SELECT count(*) FROM projects; SELECT item_category,count(*) FROM parts GROUP BY 1;"` shows tools + articles present; project 1748 has ~134 parts. Re-run → "0 created" (idempotent).

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/import_wincarat.py backend/scripts/wincarat.json
git commit -m "feat(seed): WinCarat project+part loader (SP-B/2)"
```

### Task B3: Baseline revisions + BOM tree with quantities

**Files:**
- Modify: `backend/scripts/import_wincarat.py`

**Interfaces:**
- Consumes: part cache from B2.
- Produces: one `PartRevision` per part + `PartBOMItem` lines for assemblies.

- [ ] **Step 1: Baseline revision per part**

For each imported part lacking a revision, create `PartRevision(part_id, revision_name="WC-IMP", phase="engineering", status="approved", created_by=CREATED_BY)`; set `part.active_revision_id`. Idempotent (skip if a `WC-IMP` revision exists).

- [ ] **Step 2: BOM items from extracted `bom` arrays**

For each part with `bom` lines, on its baseline revision create `PartBOMItem(revision_id, child_part_id=lookup(projektnr, child_artnr), item_number=posnr, name=benennung, quantity=menge, unit=einheit or "pcs", position=int(posnr or 0), notes=wear/spare flags)`. If a child ARTNR isn't found in any project, log it and create the BOM line as free-text (name only, `child_part_id=None`) rather than dropping it.

- [ ] **Step 3: Run and verify a known assembly tree**

Run the importer again (idempotent). Verify project 1748's `20-3342-001-0` assembly has BOM items with quantities:
`psql -c "SELECT bi.item_number, bi.name, bi.quantity, bi.unit FROM part_bom_items bi JOIN part_revisions r ON r.id=bi.revision_id JOIN parts p ON p.id=r.part_id WHERE p.part_number='20-3342-001-0';"`
Expected: ≥1 line with a numeric quantity. Log count of unresolved (free-text) children.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/import_wincarat.py
git commit -m "feat(seed): baseline revisions + BOM tree with quantities (SP-B/3)"
```

### Task B4: Tool→article `produces` relations

**Files:**
- Modify: `backend/scripts/import_wincarat.py`

- [ ] **Step 1: Derive tool→article links**

For each tool part (`item_category='tool'`), find articles in the same project whose part number's middle segment equals the tool's number (Atlas heuristic: `20-3342-001-0` → tool `3342`). Create `PartRelation(from_part_id=tool, to_part_id=article, relation_type="produces", notes="Imported from WinCarat.", created_by=CREATED_BY)`, idempotent. If an explicit WinCarat workplan link (`ARBPLAKOWKZ`) proves cleaner during B1, prefer it and note the switch here.

- [ ] **Step 2: Run and verify**

Run importer. Verify: `psql -c "SELECT count(*) FROM part_relations WHERE relation_type='produces';"` > 0, and tool `3342` links to `20-3342-001-0`.

- [ ] **Step 3: Full re-run idempotency check**

Run the whole importer once more end-to-end. Expected: "0 created" across projects, parts, revisions, BOM, relations.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/import_wincarat.py
git commit -m "feat(seed): tool->article produces relations + idempotency (SP-B/4)"
```

---

## Self-Review notes

- **Spec coverage:** SP-A (reset) = Task A1. SP-B extraction/parts/BOM/relations = B1–B4. Silao exclusion = B1 Step 2 + B2 Step 1 flag. Purchased parts (clips) = B2 TEILEART `M`/supplier mapping + included as BOM children in B3. Atlas re-import = falls out of "all active projects" (its WinCarat project is in the active set). SP-C/SP-D are separate plans (depend on this output).
- **Cross-project BOM children:** handled by loading all parts (B2) before BOM linking (B3); unresolved children degrade to free-text lines, not dropped.
- **No unit-test fixtures:** these are data-migration scripts; each task's test is a real run against live Oracle/Postgres with explicit expected `psql` output. Idempotency is the core correctness check (re-run → 0 created).
