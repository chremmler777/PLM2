---
name: part-number-families-2026-08-06
description: WinCarat article part-number prefix families — 40 is resin/material, 65 is returnables/dunnage (a code comment had these backwards)
metadata:
  type: project
---

WinCarat encodes the article class in the part-number prefix. All such rows are
`item_category = 'article'` in PLM, so the prefix is the only thing that
separates the families:

- `10` / `11` / `20` / `22` — physical parts
- `40` — **resin / material**
- `65` — **returnables / dunnage**

Corrected by the user on 2026-08-06. A comment in
`frontend/src/components/changes/StartChangeModal.tsx` had asserted the
opposite ("40 = packaging, 65 = material") since the change-type filter was
written; the comment is now fixed, but anything else built on that assumption
before 2026-08-06 is suspect and worth re-checking.

The taxonomy now lives in one place, `frontend/src/lib/itemCategory.ts`, which
also derives the equipment classes from the op code rather than from
`item_category` — see [[equipment-numbering-2026-07-24]], because EOAT (`-1x`)
and in-cell stations (`-2x`) are both stored as `assembly_equipment` and only
the number tells them apart. That mirrors `OP_CODE_KINDS` in
`backend/app/services/equipment_numbering.py`; the two copies can drift.
