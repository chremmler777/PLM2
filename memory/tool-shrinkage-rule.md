---
name: tool-shrinkage-rule
description: "Christoph's rule for tool shrinkage: one value for unfilled resins, parallel/normal split only for fibre-filled"
metadata:
  type: feedback
---

Tool shrinkage: unfilled (and non-fibre) resins get ONE shrinkage value; parallel/normal
are only split for fibre-filled resins (GF/CF). Set 2026-09-30 for 1994/2277:
T85 XF 0.6 % unpainted / 0.65 % painted, RADILON 1.25 %, ROMILOY 0.9 %, EPLAMID GF15
keeps 0.7 parallel / 1.0 normal. Hostacom TRC 352N and Pearlthane still without a value.

**Why:** unfilled resins shrink nearly isotropically; only fibre orientation makes the
directional split meaningful. User 2026-09-30: "paralle/normal only with fibers".

**How to apply:** in PLM tool fields (tool_shrink_parallel_pct / _normal_pct, migration 110)
enter the same value in both for unfilled resins; only GF/CF resins get two values.
Related: [[brose-resin-status-2026-09-30]]
