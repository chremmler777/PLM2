---
name: data-route-2026-10-19
description: Data route (Data from / to customer, Confirm / Close) built on feature/data-route, NOT merged or deployed; open items and how to test locally
metadata:
  type: project
---

Status 2026-10-20: built and green, waiting for Christoph to test and decide. He has no time now; parked as a task for later (handed to Asss 2).

**What it is.** Two buttons replace six ways of creating versions:
- "Data from customer" files received data. Official data gets a new folder (E2 · 005) and goes to triage. Feasibility data gets an E x.x.
- "Data to customer" records what we sent and need confirmed (E x.x, or internal only).
- Each E x.x ends with Confirm (becomes the next folder, files carried over, goes to triage) or Close (reason required).
- Spec: docs/superpowers/specs/2026-10-19-data-route-design.md
- Plan: docs/superpowers/plans/2026-10-19-data-route.md (Task 12 tracking is NOT built).

**Where the code is.**
- Branch feature/data-route, worktree /home/nitrolinux/claude/plm2-dataroute, latest 5c931d0a.
- Not merged, not pushed, not on prod. Prod runs 475fbdfb (alembic 116).
- Tests at 5c931d0a: backend 2190 passed, 1 skipped; frontend 3012 passed.
- SDD ledger: plm2-dataroute/.superpowers/sdd/2026-10-19-data-route/progress.md

**How to test locally.**
- Open http://10.105.100.54:5175/plm2/devlogin.html. It sets a 7-day login cookie (expires about 2026-10-27) and opens Handle LH in project 1994.
- If the app keeps jumping between the dashboard and a blank page, the cookie has expired: re-mint the token (see the scratchpad snippet logic: HS256 with get_settings() secret, sub 14) and rewrite frontend/public/devlogin.html. That file is untracked and listed in .git/info/exclude.
- Containers: dataroute-backend (8002) and dataroute-frontend (5175). DB plm_dataroute is a prod copy with the mail lists inactive, migrated to dr1, with the backfill applied.
- CAD originals are missing locally; glb, pdf and image files are there.
- Local test so far: intake 5 (Handle LH E2 · 5) was routed as engineering review, which created CR-2026-0009 in the local DB only.
- 127.0.0.1/plm2 (DB plm) is the OLD code. Its stray E1.1/E1.2 on Latch Cover 40 (rev 2236/2237) can be deleted there.

**Open decisions for Christoph.**
1. Test the route locally and give feedback.
2. Merge: locally into main, push with a PR, or keep. Before merging, re-run the full backend suite if more commits land.
3. Deploy to prod only with an explicit OK: pg_dump backup, then migration dr1.
4. After deploy, dry-run backend/scripts/backfill_1994_direction.py on prod (about 6 rows expected), show the list, and apply only with an OK.
5. Migration ordering with the ECR branch (ecr-solid uses up to 146): dr1 sits on 116, and whichever branch merges second re-points one down_revision. Tell the ECR session.
6. ISOFIX 206.887.233: Brose E2 · 002 changed about 1 mm in two zones beyond the FZ data (X 2662 / Y 546-555 / Z 459.6 and X 2675 / Z 464.5-465). Decide whether to send Dale a follow-up and/or note it on CR-2026-0008.

**Later, not built.**
- Task 12 tracking: input mask (who, channel, when), Share with toolmaker, download log, login on the file endpoints.
- Customer name per project (labels are customer-neutral for now).
- Multi-part filing in Data from customer.
- Parked: a new official index can still supersede a waiting one (the dialog warns); the legacy /promote endpoint has no guards.

**Cleanup after merge.** Remove the worktree, the SDD workspace, the two dataroute containers, the plm_dataroute DB and .local-sim/uploads.

Related: [[part-data-mail-2026-10-15]], [[feedback-prod-writes-mail-impact]], [[1994-e11-fz-toolmaker-2026-10-15]]
