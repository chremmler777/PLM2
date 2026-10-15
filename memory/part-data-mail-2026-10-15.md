---
name: part-data-mail-2026-10-15
description: PLM2 part-data email notifications - KTX Apps via Graph like TWOS, per-project list (1994 = EC kickoff 7 + Karl), 5-min digest, trial first; role-based later
metadata:
  type: project
---
User 2026-10-15: mail on new part data + revision status (incl. the 4 E1.1 of [[1994-e11-fz-toolmaker-2026-10-15]] as backfill), sent "from ktx apps, like tool transports in TWOS" (Graph sendMail as apps-noreply@us.ktx.group, ENTRA_* from /data/compose/secrets/shared.env, NOTIFY_TRIAL_RECIPIENT).
Decisions: 1994 list = Brose 1994 EC Kickoff/Review 2026-10-14 attendees (Cody Hrtyanski, Christoph Demmler, Christopher Holmes, Dale Perry, Russ Addison, Apurva Mhetre, George Richardson) + Karl Limburg, all firstname.lastname@us.ktx.group; 5-min digest per project; trial to Christoph first, go live on his OK. Role-based recipients later ("will take a while").
DEPLOYED 2026-10-15 17:43 (main 286ceecb, alembic 115; backup plm2-before-115-mail-20261015-174234.sql.gz; compose backup docker-compose.yml.bak-before-plm2-mail-20261015-174224). 1994 list seeded (8); trial digest of the 4 E1.1 sent 17:49 to Christoph only. LIVE since 2026-10-15 (~18:00, user OK after trial): NOTIFY_TRIAL_RECIPIENT removed from the prod plm2-backend block; re-add it there for a trial. Live-test migration moved to 116 (branch feature/ecr-live-test-1, ba6e1ec4).

Same day, frontend deployed 2026-10-15 ~20:30 (main 0536924c, no migration): drawings/PDFs always open in their own popup window (087d165c, helper components/parts/openDocumentWindow.tsx); opening the project worksheet is a history step so Back stays in the project (0536924c). A mistaken PDB detour (user meant PLM) was deleted; PDB untouched at fd39cb5.
