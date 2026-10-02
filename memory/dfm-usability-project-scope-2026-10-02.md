---
name: dfm-usability-project-scope-2026-10-02
description: Why prod DFM topics were empty and closed (Dale, 09-29/30) and the fix - guards, rename/delete, PPT-first form, project-wide "General tooling DFM" (migration 111)
metadata:
  type: project
---

**Prod finding 2026-10-02:** prod had 7 DFM topics (ids 2-8, tools 199401/02/03/04/06/10, two on 199410), all titled "DFM", zero entries, all closed by dale.perry (user 24) seconds to minutes after opening; nginx logs show no entry POST at all. Cause: "+ topic" had no explanation (Dale treated it as "start the DFM of this tool"), no step form opened after create, and the green one-click "Finish confirmed" sat next to "+ New DFM" with no guard, so empty topics got closed.

**User's working model:** the toolmaker sends a DFM PPT, the answers are written INSIDE the PPT, revisions go back and forth. Routes (who sent which file to whom) must stay visible; notes/comments are optional.

**Fix (uncommitted as of writing, then see git log):** close needs >=1 message (409) + confirm dialog naming waiting messages; entry needs file or note (400); PATCH rename, DELETE soft-delete of empty topics (opener or admin, audit topic_renamed/topic_deleted, deleted_at/by); finished strip shows who/when + Reopen; new topic opens the first-step form; form leads with the file dropzone, note behind "+ Add note". Project scope: migration 111 (dfm_topics.project_id, tool_part_id nullable, check ck_dfm_topics_one_scope; dfm_audit_events.project_id), routes /projects/{id}/dfm/... mirror the tool routes, files under uploads/dfm/project-<id>/, project page status bar "Tooling DFM" button + pop-out /projects/:id/dfm; tool archive links to it. No part changelog for project topics (audit events only).

**Prod 2026-10-02 16:22:** user said keep them: all 7 topics reopened via DfmService.reopen_topic as user 14 (7 topic_reopened audit events + changelog), backup /data/compose/db-backups/plm2-before-dfm-reopen-20261002-162204.sql.gz (backups live in /data/compose/db-backups, not ~). Committed as 39a9fd34, not pushed; deploy (migration 111) only on the user's "deploy".

**Lost PPTs (user 2026-10-02 "we uploaded ppt documents into it"):** nothing ever reached prod: no upload request in nginx logs, no file rows in any PLM2 file table or RFQ2 encrypted_files, no uploads/dfm dir. Pattern open -> ~1 min -> close with no entry POST means the PPT was dropped into the step form and the old green "Finish confirmed" was clicked instead of "Record step", discarding the form. The files exist only on the users' PCs and must be re-uploaded. Follow-up commit disables Finish while a step form is open.

**Prod DFM wipe 2026-10-02 16:43 (user: "clean all dfms out, we restart on prod"):** after a retraining Dale had uploaded some (topic 9 "dfm" on 199401, 4 PPTX entries). Wiped everything: 8 topics, 4 entries, 4 files, 37 dfm_audit_events, 32 revision_changelogs dfm_* rows, uploads/dfm removed. Backups: /data/compose/db-backups/plm2-before-dfm-wipe-20261002-164343.sql.gz and plm2-dfm-files-before-wipe-20261002-164343.tar.gz (the 4 PPTX). Prod DFM tables empty; restart should happen on the new UI (deploy 39a9fd34 + 4868e0c0, migration 111).

**DEPLOYED 2026-10-02 17:29:** prod at 36f7b74f, alembic 111, backup plm2-before-111-20261002-172828.sql.gz. Smoke: /plm2/ 200, tool + project DFM endpoints 200, new strings in the served bundle. Prod DFM after restart: 6 topics by dale.perry (199401/04/06/10 original + KTX forward to Tier 1 with PPTs; 199402 original only; 199403 empty), no mail dates set.
