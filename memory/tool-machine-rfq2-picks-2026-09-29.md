---
name: tool-machine-rfq2-picks-2026-09-29
description: RFQ2 machine picks live in tool_layout_json (not tooling_variant_items.machine_*); PLM parts.tool_machine (mig 109) holds them, set on prod for 1994/2277 on 2026-09-29
metadata:
  type: project
---

RFQ2 stores the chosen press per tool in `tool_size_estimations.tool_layout_json`
(`machine_pick` object, or `machine_picks` list for a tool with two presses) of the
selected variant. `tooling_variant_items.machine_*` is EMPTY for RFQ 25/26, so do not
read machines from there. Name format there: "KM 350-1 — KM KM 350/2000 CX";
PLM stores "KM 350-1 (KM 350/2000 CX)" (no em-dash).

PLM side: `parts.tool_machine` (migration 109, free text, tools only), edited on the
tool card, "Machine" column in the project worksheet. Distinct from
`tool_tonnage_mdb_machine` (MachineDB assigned press, tonnage sync).

2026-09-29: deployed to prod (19fd7fe8, alembic 109) and
`backend/scripts/set_brose_tool_machines.py --apply` set all 15 tools
(1994 from RFQ 26 loop 37 calcs 204-213 -> 199401-199410 in order; 2277 from RFQ 25
loop 36). 199408 Side Shield has two presses (KM 350-3, KM 350-1). No live sync:
re-read RFQ2 and edit the script's MACHINES when the picks change.
See [[1994-brose-volume-sheet-2026-09-23]], [[prod-data-is-truth]].

Same day (daf89014, prod): worksheet export rewritten on XlsxWriter like the RFQ2 BOM Excel; Image column sent as part id, thumbnails placed in-cell (click to zoom), WEBP via Pillow. Keep XlsxWriter out of in_memory mode (breaks the picture rels). User 2026-09-29: machines = only what RFQ2 already picked, just take over (no MachineDB picker).

Correction same day (b9d27b93, applied on prod 20:38): user wants ALL presses RFQ2 picked. RFQ2 rule (ToolCardV2): `machine_picks` list first (candidates, pick order), else `machine_pick`. The single machine_pick is often stale (Map pocket: pick KM 350-1 but list KM 900-1/-2). Stored comma-joined, ' (no fit)' where fit_ok false (Rosette: all three KM 80). Backup db-backups/plm2-before-machine-picks-20260929-203838.sql.gz.

Final same day (458396a2, prod 21:04): user "go back, smallest machine class only": ONE press per tool = smallest clamp force among the RFQ2 picks, tie -> lowest machine number. Backup plm2-before-machine-smallest-20260929-210352.sql.gz.
