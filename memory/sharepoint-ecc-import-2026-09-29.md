---
name: sharepoint-ecc-import-2026-09-29
description: KTW SharePoint "ENGINEERING CHANGE CONTROL" list, BMW G6X items imported to prod 1748 as KTX Weissenburg (mother-plant) changes CR-2026-0001..0003 via backend/scripts/import_sharepoint_ecc.py
metadata:
  type: project
---

Source: ktxgroup.sharepoint.com/sites/KTWProgramManagementProcess, list "ENGINEERING CHANGE CONTROL"
(10 items: 7 BMW, 2 NOVEM, 1 MBUSI). Only ECC-0013/0014/0015-1748 are G6X; ECC-003 (G09) and
ECC-004/005/0012-1918 (G45 transfers) are other BMW programs and were NOT imported.
Export via REST from the logged-in `playwright-cli -s=sharepoint` session; attachments fetched
with page.request (run-code files must sit under the repo's .playwright-cli/).

2026-09-29 on prod (backup db-backups/plm2-before-ecc-import-20260929-175916.sql.gz):
CR-2026-0001 = ECC-0013 (tool 3360), 0002 = ECC-0014 (tool 3351), 0003 = ECC-0015 (tool 3369);
origin mother_plant (KTX Weissenburg (WUG)), SOP = SharePoint target date, lead steven.stocks,
all attachments filed, moved to `scoping`. Impact confirm + team info (-> approved) left to the team.
Data gap: SharePoint text of ECC-0014 says mold 3349 (5A65D45/46), the form + PDF say 3351 (5A65D47/48); imported as 3351.
Prod 1748 parts have no customer_part_number (BMW 5A... numbers), matched by mold number.
Script is idempotent on mother_plant_ref. Local dev has the same three as CR-2026-0006..0008.
