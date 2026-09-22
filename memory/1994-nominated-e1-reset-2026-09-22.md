---
name: 1994-nominated-e1-reset
description: Prod state of project 1994 Brose Seat Trim after the 2026-09-22 reset - 12 nominated articles (001-012), drawing names, E1 with customer index, PCA/DMU/DRW/STEP, mirrors as relations, E1.1 investigation on 206.886.197
metadata:
  type: project
---

**Prod 1994 after 2026-09-22 (scripts in backend/scripts/reset_1994_e1.py,
rename_1994_from_drawings.py, add_1994_e11_investigation.py; backup
db-backups/plm2-before-1994-e1-reset-20260922-160050.sql.gz):**
- RFQ 26 (rfq2 id 26, status won) = exactly 12 articles, renumbered
  20-1994-001-0 … 012-0, names from the Brose B-RELEASE drawing title
  blocks (LH/RH and 40/60 from the CATIA filenames). Tools 199401-199410.
- Every article `nominated` (2026-09-21), E1 carries the customer index from
  the 3D filename: 003, latch covers 004, ISOFIX 001, received 2026-05-28.
- Files on E1: PCA + DMU CATPart, DRW_TZ PDF, STEP exported from the PCA
  with viewer. Mirrors: 206.882.252 mirror_of 251 (no files), 206.885.968
  mirror_of 967 (own CATParts + STEP, no drawing copy).
- Deleted (not nominated): 206.881.480, 4M0.881.547, 85H.886.747,
  5NA.881.253. Tool 199408 is LH only, 2 cavities.
- First proposal: 206.886.197 E1.1 "investigation data, not official",
  Brose DRAFT_MOD STEP 2026-05-29 (draft index 004).
- 206.881.799 drawing header shows a Brose typo (206_881_779); title block
  is right.

**Why:** user rulings 2026-09-22 (nominated list = the won RFQ, mirrors are
relations, delete the rest, names from drawings). Prod is truth, see
[[prod-data-is-truth]]; mirror UI follow-up in [[mirror-parts-relation]].

**Next time:** viewer conversion runs one STEP per core-second, ~8 min for a
120 MB file; parallelise the attach loop before the next bulk load.
