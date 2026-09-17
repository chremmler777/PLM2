---
name: sharepoint-lessons-mirror-2026-09-15
description: Toccoa Lessons Learned SharePoint list is mirrored into PLM2 lessons via backend/scripts/import_sharepoint_lessons.py; LL-0001..0019 are in the local dev DB, prod not yet
metadata:
  type: project
---

Source list: "Lessons Learned (Toccoa Project Management)" on the StrategicManagement
SharePoint site (tenant ktxgroup.sharepoint.com, list guid 0e7cc5ef-176a-4cb6-b0ec-6bc84b2ed87a).
Export via REST from a logged-in playwright-cli session (`-s=sharepoint`, persistent
profile) into `backend/scripts/sharepoint_lessons.json`, then run
`import_sharepoint_lessons.py` in the plm2 backend container (idempotent, keyed on the
`ll-00NN` tag with title fallback). Same mapping as the June 2026 import (0e90a065).

**Status 2026-09-15:** LL-0001..0009 (June batch) + LL-0010..0019 (Sep 10/11 batch by
Steven Stocks, all G6x 1748) are in the local dev DB as in_review with open actions where
measures existed. Deployed to prod 2026-09-15 (compose-plm2-backend-1 on ktx-server, ids 19-28). Script + JSON not committed.

**How to apply:** to refresh, re-export the list, drop the JSON in, rerun the script;
existing lessons are skipped, so status changes in SharePoint are not synced back.
