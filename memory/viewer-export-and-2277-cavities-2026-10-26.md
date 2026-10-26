---
name: viewer-export-and-2277-cavities-2026-10-26
description: Viewers can export the worksheet xlsx via @read_only POST marker (61df0a29, local, not deployed); 2277 cavities 227703/04/05 filled on prod
metadata:
  type: project
---

- Viewer export: the worksheet xlsx export was the only export sent as a POST, and the plm2_Viewer read-only check refused it. `read_only` in app/dependencies/auth.py marks a POST that only reads (checked via request.scope["endpoint"]); it is used on worksheet/export. Commit 61df0a29, NOT pushed or deployed as of 2026-10-26. All other exports are GETs. The training roster.csv needs manage rights by design.
- 2277 cavities (prod, applied 2026-10-26): 227703 = 2, 227704 = 8, 227705 = 4, from RFQ2 rfq 25 loop 36 tooling_variant_items, matching the relation notes. Script scripts/set_2277_cavities_20261026.py (32ba1722). Backup db-backups/plm-before-2277-cavities-20261026-1.sql.gz. Action "updated" is not a mail event, so no mail.

**How to apply:** a new export that needs a request body: add @read_only below @router.post. Related: [[prod-changes-2026-10-21]], [[cavity-layout-2026-10-10]].
