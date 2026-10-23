---
name: cavity-layout-2026-10-10
description: Tool cavities are a layout string ("2+2"), never summed; migration 114 deployed to prod 2026-10-10 (56d621b6)
metadata:
  type: feedback
---
User rule: a family tool's cavities show as written ("2+2"), never counted together as 4, anywhere (UI, worksheet, export, importers, notes fallback).

**Why:** the user saw 2+2 tools shown as 4 in the workbook; the split per article matters, a total loses it.

**How to apply:** `parts.tool_cavities` is varchar since migration 114; normalize via `app/services/cavity_layout.py` (backend) and `components/tools/toolCavities.ts` (frontend). Never `sum()` cavity numbers in new code or scripts. Deployed to prod 2026-10-10 20:39 (56d621b6). Prod now: BR167 0821-0824/0841/0841-2 = 1+1, 0851 = 2+2, 1994 199401/199402 = 2+2. SIM tools 9901/9902/9904 left at 2 (notes suggest 2+2, test data). Related: [[1994-brose-volume-sheet-2026-09-23]], [[rfq2-stale-cavity-tags-2026-09-24]].
