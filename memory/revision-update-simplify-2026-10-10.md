---
name: revision-update-simplify-2026-10-10
description: Open plan - simplify PLM2 revision update (new customer index) + "old drawing, new data" case; why 206.886.197 got E2/E3 tangled; current-path map
metadata:
  type: project
---
User (2026-10-10): revision update is "way too complex"; plan a simpler way later, plus how to handle old drawings with new data (e.g. Brose sends new CATPart 004 while the PDF drawing is still 001/003).

Incident: 206.886.197 (20-1994-008-0) - "Customer adopted" (promote E1.1) made E2, a minute later the B-Release 004 upload made E3 and silently superseded E2 (pending intakes are skipped by the Documents selection, so the next upload compares against the old active index and creates another major). Fixed on prod 2026-10-10: E1·003 active, E1.1 draft, E2·004 in_review (intake pending). Brose sent CATPart only.

Pain points found (code map 2026-10-10):
- Four ways to make a major (+Customer data x2, UploadDialog "Next customer data", +Customer package, Customer adopted/promote); one creates a revision with no files.
- Upload dialog title says "Upload files to <current>" even when it creates a new major.
- Index "004" only parsed for VW/Scout naming; otherwise defaults to Attach -> files land on the current index silently.
- Customer package refuses CATPart+STEP+PDF of one part ("Part appears twice").
- PDF typed "document" by package, "drawing" by upload.
- Second upload while a major is pending triage silently archives it (intake_superseded) - should ask "add to pending E2?" instead.
- Statuses cancelled/frozen never set by code; archived means two things.
- Answered 2026-10-10: Brose "B-Release" (even when frozen to Scout/VW) is REVIEW data for us = E index, because 1994 is in engineering/DFM and Brose still changes everything. Official numbering (1, 2, ...) starts at tool start / design freeze. Don't let the customer's release wording decide E vs official; the project phase does.

How to apply: when the user returns to this, brainstorm one dialog "customer sent new data": drop files -> detected part/index/date -> one decision (new index or add to existing/pending) -> done; triage stays separate. Related: [[1994-nominated-e1-reset-2026-09-22]], [[cavity-layout-2026-10-10]].
