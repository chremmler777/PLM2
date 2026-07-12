---
name: plm-master-datasource
description: "Strategic goal — make PLM2 the single source of truth for tooling & projects; first import is VW426 \"Atlas\" from TWOS"
metadata: 
  node_type: memory
  type: project
  originSessionId: ea770147-f5f3-48d9-b1aa-0dfe0b55c74d
---

**Strategic goal (stated Jun 15 2026):** PLM2 should become the MAIN datasource for tooling and projects across the org, eventually carved out of TWOS. TWOS is a satellite system ("Kleinsystem") listed in `IT_SPEC_UEBERSICHT.md` alongside PDB and Kapazitätsanalyse. **For now: do NOT carve out of TWOS — just use/import the data read-only.**

**DONE Jun 15 2026 (in `backend/plm.db`, org 1, created_by chris=user 3):**
- Plant "USA Toccoa" (code `usa-toccoa`, id=2).
- Project "VW426 Atlas" (id=2) under that plant. **Code corrected `1846` → `1864`** Jun 15 2026 — the article data (project no. + every description) consistently says 1864; 1846 was a transposition typo. Code is now `1864`.
- 8 tools imported as `item_category="tool"` parts (parts.id 6–13; part_number = TWOS tool ID 3450–3457), each linked to project 2 via `project_id` (that IS the tool↔project connection). Supplier toolcodes (4666–4673) and customer/part codes preserved in each tool's `description`.
- **12 articles imported** (`item_category="article"`, `part_type="internal_mfg"`) Jun 15 2026: part numbers `10-3457-001-0/-1`, `10-3457-002-0/-1` (PDC brackets, IM-WIP) + `20-3450..3456-*` (carrier/cladding/undertray, IM-FG). Customer/program (OPmobility VW426), stage, std qty 100 pcs stored in each article's `description`.
- **12 `produces` PartRelations** (tool → article), derived from the 4-digit middle segment of each article part number (e.g. `20-3451-002-0` → tool 3451). Tool 3457 produces all 4 PDC brackets.
- Idempotent import script: `backend/import_atlas.py` (re-runnable; skips existing, corrects code). Confirmed idempotent (2nd run = 0 created).

Tools: 3450 Grille Carrier | 3451 Lateral Trim MIC | 3452 Upper cladding basis MIC | 3453 Under cladding basis MIC | 3454 Rear Cladding | 3455 Rear Cladding | 3456 REAR Upr Tray (Cross) | 3457 PDC Brackets.

**NEXT:** Atlas tool+article+relation import is COMPLETE. Note: the older "Customer ID" codes on tools (e.g. C_3CR_807_531_A) are the OEM/customer article references — distinct from KTX internal article numbers (10-/20- series now imported). Possible follow-up: store those OEM refs as a field/alias on the article parts (currently only in tool descriptions). Also still open: merge PR #1 (change-management spine) then start sub-project #2.

Relevant building blocks already in PLM2: `Part` model with `item_category` (article|tool|assembly_equipment|eoat|gauge), `PartRelation` (produces/checks/assembles), `PartService.create_part`. See [[architecture-map]] and [[change-management-roadmap]].

**WinCarat import — RE-ACTIVATED Jul 12 2026 (was deferred Jul 4).** User wants ALL project data pulled from WinCarat: articles + tools (and gauges/other assets if present), read-only. New leads to chase this time:
- **TWOS "FA" uses WinCarat and has instructions** — the FA module/area of TWOS reads WinCarat; find its documented import/access instructions (start in `IT_SPEC_UEBERSICHT.md`, the TWOS docs, and `Documents/`). That's the likely path to a repeatable extract.
- **KPI board** also uses WinCarat — research how it connects/what it documents.
- As of Jul 4, no WinCarat data was reachable from WSL (nothing in workspace/Documents, no install under /mnt/c, /mnt/h + /mnt/u empty). Re-scan; if still no direct access, the FA/KPI instructions should reveal the export or DB route.
- Follow the `import_atlas.py` pattern (idempotent, re-runnable) once a data source is found. Import into a CLEAN db (see [[data-seeding-post-rollout]] — user wants test changes CR-2026-0001..0011 wiped first).

**WinCarat ACCESS ROUTE FOUND & VERIFIED Jul 12 2026 — this was the long-standing blocker, now cleared.** WinCarat is a live **Oracle 19c** ERP: host `10.105.205.18:1521`, SID `BU`, user `admin`, schema **`KWA`** (919 tables, 2533 articles, 504 tools). Both the **TWOS "FA"** stack (`claude-twos-backend-1`) and **KPI** stack connect to it read-only via the python `oracledb` lib. Reuse the pattern in `claude-twos-backend-1:/app/app/services/wincarat.py` (SELECT-only, cached). Easiest query path from here: `docker exec claude-twos-backend-1 python -c "import oracledb; from app.core.config import settings; ..."` (creds already in that container's env: WINCARAT_HOST/PORT/SID/USER/PASSWORD). Reference doc referenced in-code: adminpanel `docs/wincarat-tool-pm.md`.
- **Key KWA tables:** `ARTIKEL` (articles/parts; cols incl. `ARTNR`, `MATCHCODE`=name, `KDARTNR`=customer art no, `KDNR`=customer, `PROJEKTNR`=project link, `TEILEART` W=tool/T=assembly/M=misc, `ZEICHNR`=drawing, `ZUSTAND`); `WERKZ` (tools; joins to ARTIKEL by ARTNR; cols KAVITAET, WARTUNGSINTERVALL, ZUSTAND, GESAMTPROD); `WKZLEBENSLAUF` (tool lifecycle/history); `PROJEKTSTAMM` (project master: PROJEKTNR, BESCHREIBUNG, KDNR, PROJEKTSTATUS, dates); `AFORUECK` (production feedback/scrap).
- **G65 = BMW "G6X" program = WinCarat PROJEKTNR `1748`.** All G65 part-history-sheet parts live under project 1748: tools `3342`/`3354`/`3369` (TEILEART=W, "1748 TOOL … BMW G6X"), assemblies `20-33xx-001-0` (TEILEART=T "1748 ZB …"), customer parts `50-xxxx` (MATCHCODE embeds customer no e.g. `50-1117` = '1748 HEAD SHIELD 5A627C0'). The history-sheet "internal PN" `10-33xx` numbers are mostly CANCELLED/superseded in WinCarat — trust `PROJEKTNR=1748` as the authoritative scope, not the `10-` numbers. VW426 Atlas is a *separate* WinCarat project (its own PROJEKTNR — find it before importing).
