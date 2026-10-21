---
name: prod-changes-2026-10-21
description: 2026-10-21 prod changes on 1994/2277 (Infor rename, worksheet width, thumbnails, 2277 tool data and cycle times) and the held 2277 CAD filing
metadata:
  type: project
---

All live on prod, code at 8307150f (local main = origin/main = prod), alembic still 116. No mail sent by any of it.

**Infor article rename (applied, via Ass, approved by Christoph).**
- 18 molded articles of 1994 and 2277 renamed, e.g. 20-1994-005-0 -> 21-199403-XXXX-00XX. 50- bought-in parts and tool numbers unchanged.
- Old number kept as "Formerly <old>." in the description plus a changelog row (action "renumbered").
- Script backend/scripts/rename_articles_infor_scheme_20261021.py. Backup db-backups/plm-before-infor-rename-20261021-122740.sql.gz.

**Worksheet KTX no. column (deployed 28293b9a).** frozenWidth 170 -> 210 so the 19-char numbers show in full; StartChangeModal number span w-36 -> w-44.

**Thumbnails (deployed 868f4ce7 + 8307150f).**
- Every thumbnail is cropped square to the part with 8% margin on white, at two points: the viewer snapshot (frontend/src/lib/canvasCapture.ts) and the server (thumbnail_service.frame_to_part, called in set_thumbnail for every source: snapshot, upload, scripts).
- 28 existing thumbnails re-cropped via backend/scripts/recrop_thumbnails.py; originals in /app/uploads/_thumb-backup-20261021 (backend container). 3 already tight were kept.
- The 9 2277 parts were re-snapshotted from the 3D viewer at 3x (they were about 200x45 px). 1994 keeps the re-cropped RFQ2 images; re-shoot from 3D is offered, not done.

**2277 tool data (via Ass, Christoph 10/21).**
- 227701: cavities 2; 227702: cavities 1+1; both tool_tonnage_class 3200. Descriptions end with "Press class 3200 t; 2300 t possible as alternative (Christoph 10/21)."
- tool_machine left as the RFQ2 pick. Open conflict: 227701 says KM 1300-1 (1300 t) against 3200 t; asked Christoph via Ass whether to change or clear it.
- Backup db-backups/plm-before-2277-tooldata-20261021-1.sql.gz.

**Cycle times (user ask "worksheet needs calculated cycletimes").**
- 2277 set from RFQ2 rfq 25 process_calcs (loops 29 and 36 agree): 227701 65 s, 227702 65 s, 227703 55 s, 227704 35 s, 227705 35 s. Backup db-backups/plm-before-2277-cycletime-20261021-1.sql.gz.
- 1994 already had them from RFQ 26 (50/55 s, set via scripts/set_1994_tool_fields.py); verified on the prod worksheet API.
- These are quote values (mostly "transfer_given"), not computed from the part. Offered: a "s per part" column (cycle / cavities) or a geometry-based cooling estimate. Not built.
- RFQ2 source: container rfq2-rfq-postgres-1, user rfq_user, db rfq_db, table process_calcs (cycle_time_s, cycle_time_source, internal_estimate_s) joined to bom_items.

**Held: 2277 Brose B-RELEASE 08-28 CAD.**
- Script backend/scripts/add_2277_brose_release_20261021.py, NOT run. Its CAVITIES part is now already done (it skips unchanged values).
- Blockers: 3 PCA CATParts 197-257 MB exceed the 100 MB limit (needs an override); 971.B/972.A keep the same TM index. Recommended E2 for all 9. Waiting on Christoph.
- Staged files: ~/stage-2277-20261021 (host) and /app/uploads/_stage-2277-20261021 (container). Remove once filed or dropped.

**How to apply.** Prod API writes from inside the backend container need a JWT with sub, username and email (user 14 = christoph.demmler), else 401 "Token missing email/username". The ssh guard rejects `rm -f` and `$(...)` inside ssh commands; use plain rm and fixed backup names.

Related: [[data-route-2026-10-19]], [[feedback-prod-writes-mail-impact]], [[cavity-layout-2026-10-10]], [[brose-award-import-2026-09-02]]
