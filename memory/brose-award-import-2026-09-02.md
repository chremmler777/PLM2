---
name: brose-award-import-2026-09-02
description: Brose Sitech award (RFQ2 rfq 25 Backpanel, 26 Seat Trim) loaded into live PLM as projects 1994A/1994B on 2026-09-02; open award-vs-RFQ mismatches to confirm with Brose
metadata:
  type: project
---

**Done 2026-09-02:** `backend/scripts/import_brose.py` (idempotent, runs in the
backend container with `PYTHONPATH=/app`) created in the live Postgres:
- Project **1994A Brose Backpanel** (PLM id 34, from RFQ2 rfq 25): 3 awarded articles + Map Pocket, Pivot Axis, Rossette (not awarded, 20- family) + 3 purchased parts (50- family: spring, bumper, strap); tools 1994A-1 (971, 2-cav), 1994A-2 (971.B + 972.A, 1+1), 1994A-3..5 (map pocket, pivot axis, rossette, not awarded). Back panel 206.881.971 carries a 6-line BOM (G02..G07) on its RFQ1 revision.
- Project **1994B Brose Seat Trim** (PLM id 35, from RFQ2 rfq 26): 15 awarded articles + Griff 5NA.881.253 (not awarded), tools 1994B-1..12 in RFQ tooling_calc order (204..217) + 1994B-13 Griff.
- Articles numbered `20-<project>-NNN-0`, customer number in `customer_part_number` (dotted VW form), Brose number/material/color/box/weight/volumes in description, baseline revision `RFQ1` (rfq_phase, approved), `produces` relations with cavity count in notes.
- Source of truth for quote data: RFQ2 Postgres (`rfq2-postgres-1`, user rfq_user, db rfq_db), tables bom_items / tooling_calcs / tooling_variant_items, current loop REV8.

**Codes 1994A (Backpanel) and 1994B (Seat Trim)** were set by the user on 2026-09-02 (first loaded as 8888/9999, renamed in place); WinCarat may assign real numbers later (script keys on project code and part_number, so renumbering means a rename, not a re-import).

**Open with Brose (meeting list given 2026-09-02):** 206.881.480 RH side shield not on the award list but added (shares tool 1994B-8 with 479 LH, flagged in description); 799 named Outer per award (RFQ said Inner); top tether 85H.886.747 per award (RFQ quoted 3G0.886.747); not awarded but loaded on the user's request (2026-09-02, full RFQ scope, descriptions say NOT ON AWARD LIST): Map Pocket, Pivot Axis, Rossette, purchased parts (rfq 25), Griff 5NA.881.253 (rfq 26).

See [[plm-master-datasource]] for the WinCarat/VW426 import pattern this follows.
