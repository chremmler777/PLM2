---
name: rfq2-stale-cavity-tags-2026-09-24
description: RFQ2 tool header chip "N-cavity" was the seeded injection_concept text, not a count; cleaned on RFQ2 prod 2026-09-24
metadata:
  type: project
---
RFQ2 tool card chip (ToolCardV2.tsx:367) prints tooling_calcs.injection_concept; seed scripts (seed_brose.py:70-71 etc.) wrote "N-cavity" there and "— raw (N-cavity)" into the name. Real cavities = tooling_variant_items.cavities per article (tool total = sum = layout cavity count); all exports use those.
2026-09-24 on RFQ2 prod (backup db-backups/rfq_db_before_cavitytag_20260924-200806.sql.gz): stripped "— raw (N-cavity)" from 57 names, set injection_concept NULL on 58 rows (RFQ 22-26). Estimator treats NULL and "N-cavity" identically (cold_runner), so no cost change. Left alone: RFQ 21 "1/1 single-cavity (incumbent reference)", RFQ 22 "(2-cavity min)" x11, name "Display — raw".
Code fix handed to the RFQ2 chat as text (chip guard, export names cleaned, seeds stop writing the tag, pdf_builder cavity_count bug). See [[1994-brose-volume-sheet-2026-09-23]].

Follow-up same day: all 10 1994 tools on PLM prod checked against RFQ 26 nominated loop 37 (items sum = layout count): 199401 4 (2+2), 199402 4 (2+2), 199403 4, 199404 2, 199405-199408 2, 199409 8, 199410 2 - all match. The engineering Excel's 4 yellow cavity questions (199403/404/409/410) quoted the stale name tags as "frozen loop 9"; answered with a comment and flag confirmed. ISOFIX produces-link note fixed "2 cavities" -> "4 cavities" (changelog on both parts). Loop 28 (older) had ISOFIX 2, A-brackets 1.
