---
name: brose-award-import-2026-09-02
description: Brose Sitech award (RFQ2 rfq 25 Backpanel, 26 Seat Trim) loaded into live PLM as projects 8888/9999 on 2026-09-02; open award-vs-RFQ mismatches to confirm with Brose
metadata:
  type: project
---

**Done 2026-09-02:** `backend/scripts/import_brose.py` (idempotent, runs in the
backend container with `PYTHONPATH=/app`) created in the live Postgres:
- Project **8888 Brose Backpanel** (PLM id 34, from RFQ2 rfq 25): 3 articles, tools 8888-1 (971, 2-cav), 8888-2 (971.B + 972.A, 1+1).
- Project **9999 Brose Seat Trim** (PLM id 35, from RFQ2 rfq 26): 15 articles, tools 9999-1..9999-12 in RFQ tooling_calc order (204..217).
- Articles numbered `20-<project>-NNN-0`, customer number in `customer_part_number` (dotted VW form), Brose number/material/color/box/weight/volumes in description, baseline revision `RFQ1` (rfq_phase, approved), `produces` relations with cavity count in notes.
- Source of truth for quote data: RFQ2 Postgres (`rfq2-postgres-1`, user rfq_user, db rfq_db), tables bom_items / tooling_calcs / tooling_variant_items, current loop REV8.

**8888/9999 are placeholders** the user chose; WinCarat may assign real numbers later (script keys on project code and part_number, so renumbering means a rename, not a re-import).

**Open with Brose (meeting list given 2026-09-02):** 206.881.480 RH side shield not on the award list but added (shares tool 9999-8 with 479 LH, flagged in description); 799 named Outer per award (RFQ said Inner); top tether 85H.886.747 per award (RFQ quoted 3G0.886.747); not awarded: Map Pocket, Pivot Axis, Rossette, purchased parts (rfq 25), Griff 5NA.881.253 (rfq 26).

See [[plm-master-datasource]] for the WinCarat/VW426 import pattern this follows.
