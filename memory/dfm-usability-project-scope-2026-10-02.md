---
name: dfm-usability-project-scope-2026-10-02
description: 2026-10-02 DFM day - why prod DFM topics were empty+closed, lost PPTs, guards/rename/delete, PPT-first steps, General tooling DFM per project (migration 111), prod wipe + restart, deployed 36f7b74f
metadata:
  type: project
---

**Finding.** Prod had 7 DFM topics (09-29/30, all titled "DFM", tools 199401/02/03/04/06/10, two on 199410), zero entries, all closed by dale.perry (user 24) about a minute after opening. nginx showed no entry POST and no file anywhere (all PLM2 file tables, RFQ2 encrypted_files, uploads/dfm). Cause: the PPT was dropped into the step form, then the green one-click "Finish confirmed" (right next to "+ New DFM") was clicked instead of "Record step", which discarded the form. Nothing explained what a topic is and no form opened after create.

**User's working model.** Toolmaker sends a DFM PPT; the answers are written INSIDE the PPT; revisions go back and forth (KTX forwards to Tier 1 "with KTX additions"). Routes (who sent which file to whom, when) must stay visible as the swimlane graphic; notes are not needed.

**Built (39a9fd34, 4868e0c0):**
- Finish needs >=1 message (backend 409) and is disabled while a step form is open; ConfirmDialog names waiting messages.
- Entry needs file or note (400). Form leads with the "DFM file" dropzone, note behind "+ Add note".
- PATCH rename, DELETE soft delete (deleted_at/by) of empty topics by opener or admin (effective_role); audit topic_renamed / topic_deleted.
- Finished strip: "Finished confirmed on <date> by <name>" + Reopen. New topic auto-opens the first-step form.
- Project scope, migration 111: dfm_topics.project_id + check ck_dfm_topics_one_scope, tool_part_id nullable; dfm_audit_events.project_id. Routes /projects/{id}/dfm/... mirror the tool routes (one route factory). Files under uploads/dfm/project-<id>/. No part changelog for project topics. UI: "Tooling DFM" button in ProjectStatusNav, pop-out /projects/:id/dfm, link from each tool's DFM tab.
- Tests at deploy: backend 2082 passed (full suite takes ~44 min with -n 2; -n 0 exceeds 15 min), frontend 2931. Guide updated: docs/guides/project-worksheet-and-dfm.md (screens pw-dfm-v3-*).

**Prod data ops 2026-10-02 (backups in /data/compose/db-backups, NOT ~):**
- 16:22 reopened the 7 empty topics as user 14 (plm2-before-dfm-reopen-20261002-162204.sql.gz).
- 16:43 user after retraining Dale: "clean all dfms out, we restart". Wiped 8 topics, 4 entries, 4 PPTX, 37 audit events, 32 revision_changelogs dfm_* rows, uploads/dfm (plm2-before-dfm-wipe-20261002-164343.sql.gz + plm2-dfm-files-before-wipe-20261002-164343.tar.gz).
- Dale re-entered: 6 topics; 199401/04/06/10 original + KTX forward to Tier 1 with PPTs, 199402 original only, 199403 empty. No mail dates set (cards show 10-02; files dated 09-29/30).
- 17:29 DEPLOYED 36f7b74f, alembic 111 (plm2-before-111-20261002-172828.sql.gz). Smoke OK.

**Offered, not decided:** server-side PPT to PDF preview; per-file "checked" tick.
