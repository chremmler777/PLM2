---
name: moldflow-review-structure
description: User rule 2026-10-16 - every Moldflow review entry follows DFM basis (confirmed / open in DFM) -> verdict -> note -> action plan
metadata:
  type: feedback
---
Every Moldflow review result is written in this order: **DFM basis** (what was confirmed in the DFM, or is still open there) → **verdict** → **note** → **action plan**.

**Why:** user 2026-10-16, when the 1994 FZ V01 reports came in: "lets always go following way, what was confirmed in dfm or is open in dfm then verdict and note and actionplan". The Moldflow has to be judged against the DFM agreements, not on its own.

**How to apply:** for each tool, read the PLM2 DFM topics first (confirmed vs open), then give a verdict, a note and an action plan with an owner. Applies to tool_moldflow rows ([[session-state-2026-10-16]]) and to the later Moldflow findings tree.
