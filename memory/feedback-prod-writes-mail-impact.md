---
name: feedback-prod-writes-mail-impact
description: Before a PLM2 prod data write, state whether it triggers the part-data mail; an interrupted ssh apply may still have run
metadata:
  type: feedback
---
Before applying a PLM2 prod data script (new iterations, files, status), say up front whether it sends a part-data mail and to whom: created / file_uploaded / promoted / activated / rejected / intake_* and new-iteration metadata_updated are mail events (part_data_mail.MAIL_EVENTS) and go to the project's list about 5 minutes later.

**Why:** 2026-10-19 Christoph stopped the apply ("check if the team will get a new data mail") right before the 1994 Handle LH E1.1 / Belt exit cover E2 · 005 filing. The interrupted ssh call had in fact already run on the server (writes 12:39-12:41 UTC), and the rerun overwrote the pre-change backup file with a post-change one.

**How to apply:** put the mail impact into the dry-run confirmation. After an interrupted/rejected ssh write, check prod state before anything else, and give each backup a unique timestamped name so a rerun can't overwrite it. Related: [[part-data-mail-2026-10-15]].
