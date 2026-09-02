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
- Articles numbered `20-<project>-NNN-0` (purchased `50-`), **name = `<customer number> <name>`** (user asked 2026-09-02 that articles reflect the customer number), customer number also in `customer_part_number` (dotted VW form), Brose number/material/color/box/weight/volumes in description, baseline revision `RFQ1` (rfq_phase, approved), `produces` relations with cavity count in notes.
- Source of truth for quote data: RFQ2 Postgres (`rfq2-postgres-1`, user rfq_user, db rfq_db), tables bom_items / tooling_calcs / tooling_variant_items, current loop REV8.

**Codes 1994A (Backpanel) and 1994B (Seat Trim)** were set by the user on 2026-09-02 (first loaded as 8888/9999, renamed in place); WinCarat may assign real numbers later (script keys on project code and part_number, so renumbering means a rename, not a re-import).

**Open with Brose (meeting list given 2026-09-02):** 206.881.480 RH side shield not on the award list but added (shares tool 1994B-8 with 479 LH, flagged in description); 799 named Outer per award (RFQ said Inner); top tether 85H.886.747 per award (RFQ quoted 3G0.886.747); not awarded but loaded on the user's request (2026-09-02, full RFQ scope, descriptions say NOT ON AWARD LIST): Map Pocket, Pivot Axis, Rossette, purchased parts (rfq 25), Griff 5NA.881.253 (rfq 26).

See [[plm-master-datasource]] for the WinCarat/VW426 import pattern this follows.

**3D data (2026-09-02, `backend/scripts/attach_brose_cad.py`):** customer STEP files attached to the
RFQ1 revisions from the RFQ2 working copies on `C:\temp` (rfq26_step, brose_step_export,
probe_971.stp), staged in `backend/scripts/brose_cad_stage/` (git-ignored, 1.3 GB). RFQ2's
`.stp.fine.glb` viewer files are reused. Coverage: all 12 B-release seat-trim parts, top tether
(only the 3G0 ADS-2021 STEP, no 85H data yet), back panel 971 (CP3 2026-02-20 STEP; the
B-release is CATPart-only on U:), G02..G07 B-release. **Still without 3D:** 971.B / 972.A (CP3
STEP on `U:\RFQ\RFQ25\Loop_09\02_CAD\Old Data for Ref`, U: needs `sudo mount -t drvfs 'U:'
/mnt/u`), 206.881.480 RH (mirror, no file), 4M0.881.547 (no CAD received), Griff 5NA.881.253
(CATPart on U: only).

**PROD (2026-09-02 20:05-20:25):** both scripts ran on `ktx-server` (compose-plm2-backend-1): projects 1994A/1994B
+ all 20 STEP files with viewers are live at https://apps.ad.us.ktx.group/plm2/. Prod DB was NOT overwritten
(it holds changes local lacks); backup `db-backups/plm2-before-brose-20260902-200453.sql.gz`. Added the
`/data/appdata/plm2/revision-uploads:/app/uploads` mount (owned by uid 1000) so revision files and change
attachments survive rebuilds. RFQ2 prod already had RFQ 25/26 and is newer than local: never push the local
RFQ2 DB to prod. Runbook §11 in adminpanel/docs/plm2-prod-deploy-runbook.md has the log.
