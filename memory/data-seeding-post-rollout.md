---
name: data-seeding-post-rollout
description: "Next chapter (Jul 12 2026): wipe test data, import WinCarat, seed part-history-sheet changes as auto-created, department backfeed tasklist"
metadata:
  type: project
---

# Post-rollout data seeding plan (stated Jul 12 2026)

Sequence the user wants AFTER pushing the P&L/usability branch to main (main now at merge commit of PR #3) and clearing the chat. Do these in order:

1. **Wipe all test changes.** The change-management sandbox data from the build walkthrough (CR-2026-0001 .. CR-2026-0011 in the live docker Postgres db, `claude-plm2-db-1`) is throwaway. Clean it out so the system starts from real data. Preserve real master data (plants, the VW426 Atlas project/tools/articles imported earlier — see [[plm-master-datasource]]) unless the user says otherwise; only the *changes* (+ their meetings/assessments/cost lines/gates/audit) are test cruft. Confirm scope with the user before a destructive wipe.

2. **Import all project data from WinCarat** — articles and tools (+ gauges/other assets). See [[plm-master-datasource]] for the re-activated import: TWOS **FA** module uses WinCarat and has instructions; **KPI board** also uses it — research both to find the extract/DB route. Idempotent `import_atlas.py`-style script.

3. **Part history sheets → auto-created changes.** User has a **part history sheet in "G65"** (location/share — confirm exact path; "History sheets are here" was said but no path captured). Each historical change on the sheet becomes a ChangeRequest in PLM, flagged/noted as **auto-created / pre-PLM-rollout** (they were implemented before PLM existed, so they skip the live workflow — seed them in a terminal/closed-ish state with a note like "Backfilled from part history sheet; implemented prior to PLM rollout"). 
   - **VW426 will also get history sheets** but the user does NOT have them yet — so build the importer generically and run VW426 when its sheets arrive.

4. **Department backfeed tasklist.** Produce a task list for each department to *backfeed* the missing detail into these auto-created historical changes (the sheets won't have everything the PLM model wants — cost lines, assessments, affected items, etc.). This is a per-department "please fill in X for these N backfilled changes" worklist.

**Status:** ✅ ALL DONE Jul 12 2026 on branch `feature/wincarat-import-g65-backfill` (NOT yet merged to main). Decisions taken: full transactional reset; WinCarat = master (see [[plm-master-datasource]] for the Oracle access route + MATERIAL/EIGENKZ schema facts); import ALL active projects, full BOM depth incl. purchased clips + assembly tree with quantities; all → USA Toccoa (single-plant WinCarat, no Silao data present); Atlas re-imported from WinCarat.
- **SP-A** `backend/scripts/reset_transactional.py` — wiped 736 rows / 34-table FK closure of the 2 seed projects; guarded so it can't nuke post-import data. Backup: `backend/plm-before-reset.dump`.
- **SP-B** `wincarat_extract.py` (twos container) + `import_wincarat.py` (plm2 container, `PYTHONPATH=/app`) — 29 projects, 1934+110 parts, 2044 WC-IMP revisions, 7477 BOM items, 1307 produces relations. Idempotent.
- **SP-C** `backfill_g65_changes.py` — 41 G65 history-sheet rows → closed ChangeRequests under project 1748 (id 12), `PHS-<part>-<row>` numbers, issuer 'Part History Sheet (backfill)'. Sheets copied to container /tmp/g65_sheets.
- **SP-D** `g65_backfeed_tasklist.py` → `docs/PartHistorySheets/G65/backfeed-tasklist.md` — per-department worklist of missing PLM fields.
- Spec `docs/superpowers/specs/2026-07-12-wincarat-import-and-g65-backfill-design.md`; plan `docs/superpowers/plans/2026-07-12-wincarat-import-and-reset.md`.
- **NEXT:** user wanted (from 12:20) push to main + /clear. Confirm merge. VW426 sheets still pending — `backfill_g65_changes.py` is generic, point `--sheets-dir` at them when they arrive.
