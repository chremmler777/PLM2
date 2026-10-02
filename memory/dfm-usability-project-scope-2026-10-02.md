---
name: dfm-usability-project-scope-2026-10-02
description: Why prod DFM topics were empty and closed (Dale, 09-29/30) and the fix - guards, rename/delete, PPT-first form, project-wide "General tooling DFM" (migration 111)
metadata:
  type: project
---

**Prod finding 2026-10-02:** prod had 7 DFM topics (ids 2-8, tools 199401/02/03/04/06/10, two on 199410), all titled "DFM", zero entries, all closed by dale.perry (user 24) seconds to minutes after opening; nginx logs show no entry POST at all. Cause: "+ topic" had no explanation (Dale treated it as "start the DFM of this tool"), no step form opened after create, and the green one-click "Finish confirmed" sat next to "+ New DFM" with no guard, so empty topics got closed.

**User's working model:** the toolmaker sends a DFM PPT, the answers are written INSIDE the PPT, revisions go back and forth. Routes (who sent which file to whom) must stay visible; notes/comments are optional.

**Fix (uncommitted as of writing, then see git log):** close needs >=1 message (409) + confirm dialog naming waiting messages; entry needs file or note (400); PATCH rename, DELETE soft-delete of empty topics (opener or admin, audit topic_renamed/topic_deleted, deleted_at/by); finished strip shows who/when + Reopen; new topic opens the first-step form; form leads with the file dropzone, note behind "+ Add note". Project scope: migration 111 (dfm_topics.project_id, tool_part_id nullable, check ck_dfm_topics_one_scope; dfm_audit_events.project_id), routes /projects/{id}/dfm/... mirror the tool routes, files under uploads/dfm/project-<id>/, project page status bar "Tooling DFM" button + pop-out /projects/:id/dfm; tool archive links to it. No part changelog for project topics (audit events only).

**Open:** what to do with the 7 empty prod topics (delete via new endpoint or reopen/rename) - ask the user. Deploy needs migration 111.
