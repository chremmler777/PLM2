---
name: equipment-numbering-2026-07-24
description: Equipment/gauge numbering scheme adopted 2026-07-24, what shipped, and what Christoph wants next (visualisation, not more importing)
metadata:
  type: project
---

# Equipment numbering + gauge inventory (2026-07-24)

## The scheme (decided, in production)

`<tool#>[-<2-digit op code>]`, adopted from Russ Addison's email "RE: Naming of
Equipment" (2026-07-24), with one change Christoph made: **molds keep the bare
tool number**, no `-00`. Rev-level indexing of molds is deferred.

| Suffix | Meaning |
|---|---|
| *(none)* | Mold |
| `-10` | EOAT |
| `-20`, `-21` … | Automated in-cell station (degater, tab cutter, clip install) |
| `-30`, `-31` … | Secondary station (punch & weld, assembly table) |
| `-40`, `-41` … | Gauge |

**Shared equipment takes the lowest tool number it serves.** Coverage lives in
`serves` relations, never in the number — tool 3455 owns no equipment, its station
is `3454-30`. Any code that finds equipment by number prefix is wrong.

Maintenance tracks the same physical equipment in its PM software; the format was
chosen so they can adopt it unchanged. Not yet reconciled with them.

Hyphen rules (the namespace is shared three ways): split on the **last** hyphen; a
tail is an op code only if exactly two digits in family 1–4. `0674` is tool 1,
`0674-2` is tool 2, `91-0001` is a tool. A second tool owns equipment nestedly:
`0674-2-40`.

## What shipped

Spec `docs/superpowers/specs/2026-07-24-equipment-numbering-and-gauge-import-design.md`,
plans `2026-07-24-equipment-numbering-and-gauge-import.md` and
`2026-07-24-process-flow-view.md`. All on `main`, backend 410 / frontend 168 green.

- `app/services/equipment_numbering.py` — parse/classify/allocate, pure functions.
- `app/services/gauge_import.py` + `import_gauges.py` — dry-run-first importer.
- `seed_vw426_equipment.py` — VW426 cell.
- `app/services/process_flow_service.py` + `GET /parts/{id}/process-flow`.
- `frontend/src/components/ProcessFlowSection.tsx` — shown on the item panel for
  tools/equipment (not articles).

Live data written: **153 gauges, 14 equipment, 175 serves, 2 feeds.**

No migration was needed — `parts.item_category` already documented
`assembly_equipment` and `gauge`, and there is no CHECK constraint.

## VW426 cell facts (from Christoph)

- All 8 tools 3450–3457 have an EOAT.
- 3450, 3451, 3452, 3453, 3456 have a degater and are finished after degating.
- 3454 + 3455 share one punch-and-weld → `3454-30`, which also serves 3457.
- 3457 has no degater; its brackets are welded downstream, 2 into 3454 and 2 into
  3455. **3457 has no gauge** — measured by caliber. Sheet row P1403 is therefore
  an explicit exclusion in `gauge_import.EXCLUSIONS`.

## Deliberately parked (Christoph said skip, 2026-07-24)

- 18 gauges whose tools (`926`, `3431`–`3439`) don't exist in the PLM. The
  importer reports and skips them; re-running picks them up once tools exist.
- Spec §6, the item picker on material + creation process.
- The `equipment_detail` side table (structured storage location, maintenance ref).
  Legacy `P#` and rack location currently live in the part's description text, so
  the spreadsheet remains master for storage.

## What he wants next

Visualisation, not more data plumbing:

1. **Better picker visualisation for impacted parts** — in the change flow, when
   choosing what a change hits.
2. **Better visualisation of equipment usage** — which tools a piece of equipment
   serves, where it is used. The `serves`/`feeds` data now exists to drive it.

Both need brainstorming before building. See [[change-flow-rework-2026-07-23]].
