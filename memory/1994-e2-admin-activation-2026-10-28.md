---
name: 1994-e2-admin-activation-2026-10-28
description: 2026-10-28 prod - the three pending 1994 Brose E2 indexes (886.197, 883.607, 887.233) triaged administrative and active; CR-2026-0008 cancelled; mails sent
metadata:
  type: project
---
User 2026-10-28: "all of the pending triage in 1994 is no impact and official". Chosen: administrative (reason
"Official Brose data, no impact (Christoph 2026-10-28)."), cancel CR-2026-0008 (engineering review of 887.233, was in
scoping), let the part-data mails go (7 rows: 3 intake_decided, 3 activated, 1 promoted).

Now active: 206.886.197 E2 rev 2247 (idx 004), 206.883.607 E2 rev 2253 (idx 005), 206.887.233 E2 rev 2255 (idx 002).
887.233 intake 4 was a promotion of FZ E1.1 2249, so 2249 is now approved "Promoted to E2". 1994 has no pending intake left.
Still open: 206.886.197 E1.1 2122 (Brose DRAFT_MOD investigation of 004) is a draft, probably to close. Toolmaker
drafts E2.1 2258 (887.233) and 2261 (886.197) sit on the now-active E2.
Script backend/scripts/activate_1994_e2_admin_20261028.py (dry run = run all + rollback), as user 14 via the service
calls the API uses. Backup /data/compose/db-backups/plm2-before-1994-e2-admin-152219.sql.gz.
Related: [[1994-e11-fz-toolmaker-2026-10-15]], [[feedback-prod-writes-mail-impact]]
