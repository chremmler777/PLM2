---
name: feedback-2277-backpanel-press-3200
description: 2277 back panel tools 227701 and 227702 both run on the 3200 t Engel (EN 3200-1), cavities 2 and 1+1; never take the RFQ2 smallest-class press pick for them
metadata:
  type: feedback
---

Both 2277 back panel tools run on the 3200 t press: tool_machine "EN 3200-1 (Engel DUO 17060/3500 TECH US)", tool_tonnage_class 3200. 227701 (MIC) has 2 cavities, 227702 (DS/PS) has 1+1.

**Why:** the user said on 2026-10-26 "that always goes wrong". The RFQ2 Tool Layout Designer picked KM 2300-1 / KM 1300-1 for 227701, and set_brose_tool_machines.py took the smallest-class pick (KM 1300-1), which was wrong. Fixed on prod 2026-10-26 (scripts/set_2277_backpanel_machine_20261026.py, backup plm-before-2277-machine-20261026-1.sql.gz). set_brose_tool_machines.py now carries the Engel for 227701 too.

**How to apply:** whenever machines, tonnage or cavities of 2277 are set, imported or synced from RFQ2 (or any script), check that 227701/227702 end up as above; do not trust RFQ2 press picks or "smallest class" logic for them. Related: [[prod-changes-2026-10-21]], [[viewer-export-and-2277-cavities-2026-10-26]], [[cavity-layout-2026-10-10]].
