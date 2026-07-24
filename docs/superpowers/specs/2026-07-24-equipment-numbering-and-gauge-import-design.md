# Equipment Numbering, Gauge Import, and Process Flow — Design

**Status:** approved 2026-07-24
**Source of truth for the naming scheme:** email thread "RE: Naming of Equipment",
Russ Addison → Christoph Demmler, 2026-07-24. Adopted as-is except that molds keep
the bare tool number (see §1).

## Problem

There is no standard for naming equipment. Molds live in the PLM as `tool` parts
(251 rows), but EOAT, degaters, assembly stations, and gauges exist only in
spreadsheets — chiefly `FM-QUA-0094-17 Gauge Inventory.xlsx` (171 gauges keyed by
a legacy `P#`). Nothing links a gauge or a station to the tools it serves, so a
change cannot name its impacted equipment, and there is no way to see a part's
process route.

Maintenance tracks the same physical equipment in its own PM software. A shared
number format is a precondition for ever reconciling the two, so the scheme below
is chosen to be one Maintenance can adopt unchanged.

## 1. Numbering

`<tool#>[-<op code>]`

| Suffix | Meaning |
|---|---|
| *(none)* | Mold — the bare tool number, e.g. `3454` |
| `-10` | EOAT |
| `-20`, `-21`, … | Automated in-cell station (degater, tab cutter, clip install) |
| `-30`, `-31`, … | Secondary station (punch & weld, assembly table) |
| `-40`, `-41`, … | Gauge |

The second digit indexes multiples of the same kind in one cell. Molds deliberately
do **not** take `-00`: the existing 251 tool records keep their numbers untouched.
Russ's suggestion of indexing a mold's second character by part rev level is
**deferred** — not in scope, and no field is reserved for it yet.

**Shared equipment takes the lowest tool number it serves.** The punch-and-weld
cell serving 3454, 3455 and the 3457 brackets is `3454-30`; the gauge covering
3454/3455 (legacy `P1289`) is `3454-40`.

### Namespace collision

Existing second-tool numbering already uses a suffix: `0674-2`, `0674-3`. Op codes
are always two digits, so `0674-2` (second tool) and `0674-20` (in-cell station)
are distinguishable. The parser MUST treat a one-digit suffix as a second-tool
marker and only a two-digit suffix as an op code, and MUST reject a three-digit
suffix rather than silently truncating.

## 2. Storage

`parts.item_category` gains two values alongside `article` and `tool`:
`equipment` and `gauge`. Gauges are split out from generic equipment because they
are inventoried, audited, and owned by Quality rather than Tooling.

No new columns. The legacy gauge `P#` and the rack location (storage area / row /
bay / shelf) go into the existing description/notes text.

**Explicitly deferred:** a 1:1 `equipment_detail` side table holding op code,
legacy ID, structured storage location, and a Maintenance reference. The
spreadsheet stays the master for storage location until that exists; the PLM
cannot regenerate FM-QUA-0094-17 in this iteration. This is a known, accepted
limitation, not an oversight.

## 3. Linkage

Reuse the existing `part_relations` table (`from_part_id`, `to_part_id`,
`relation_type`, `notes`) — currently carrying 1319 `produces` rows. Two new
relation types:

- `serves` — equipment → each tool it serves. The equipment's *number* comes from
  the lowest such tool; these rows carry the complete set, so nothing depends on
  parsing the number to know coverage.
- `feeds` — tool → tool, for parts consumed by a downstream station.

For the VW426 cell:

```
3450-20  serves → 3450          (degater; same shape for 3451, 3452, 3453, 3456)
3454-30  serves → 3454, 3455, 3457
3454-40  serves → 3454, 3455
3457     feeds  → 3454, 3455
```

3450–3453 and 3456 are complete after degating. 3457 has no degater, so it gets no
`-20`; its brackets are welded downstream — two to 3454 and two to 3455. That
multiplicity lives in the `feeds` row's `notes`; it is not modelled as a quantity
field in this iteration.

## 4. Gauge import

A dry-run-first importer over `FM-QUA-0094-17 Gauge Inventory.xlsx` (Sheet1,
header on row 2: Customer, Tool #, Description, Gauge P #, Storage Area, Row, Bay,
Shelf; 171 data rows).

Per row:
1. Parse `Tool #`. Seven rows carry multiple IDs — `918/919`, `929/991`,
   `931/990-001`, `931/990-002`, `3454/3455` — split on `/` and take the lowest as
   the number owner.
2. Allocate the next free `-4N` index for that tool. LH/RH pairs on the same tool
   therefore become `-40` and `-41`.
3. Create a `gauge` part; put the legacy `P#` and the rack location in the notes.
4. Write one `serves` relation per tool ID listed on the row.

The run reports, and does not guess: every multi-ID collapse, every tool number
with no matching `tool` part, every customer-name variant it normalised (the sheet
contains `BMW`, `BMW `, `BMW (G09)`, `BMW(G09)`, `OP BMW`, `OP BMW `, `OP VW`,
`OP VW `, `VW`). A dry run prints the full plan and writes nothing. Re-running an
import is idempotent: a gauge already present with the same legacy `P#` is skipped,
not duplicated.

## 5. Process flow

A derived view — no stored flow definition. From a tool, walk `serves` and `feeds`
and order the result by op code: mold → in-cell station → secondary station →
gauge. Upstream tools joined by `feeds` render as merging branches, which is what
makes the 3457 → 3454/3455 case legible.

Deriving rather than storing means the flow cannot drift from the equipment
records. The cost is that any ordering not implied by op code (two secondary
stations in a required sequence) cannot be expressed yet.

## 6. Item picker: material + creation process

Replaces the current filter in the Start Change modal, which admits only part
number prefixes 10, 11, 20, 22. Selection moves to material plus creation process,
so painted parts are selectable where they belong and excluded where they do not —
they are out of scope for the VW426 cell.

This is a separate piece of work with its own spec; it is recorded here only so the
boundary is explicit.

## Sequence

1. §1–§4 — numbering, categories, relation types, gauge import. Gets correct data in.
2. §5 — process-flow view.
3. §6 — picker, as its own spec.

## Testing

- Number parser: bare number → mold; `-10`/`-20`/`-40` → correct kind; `-2`
  → second-tool marker, not an op code; three-digit suffix → rejected.
- Lowest-ID rule: `3454/3455` → `3454-40` with `serves` rows for both tools.
- Index allocation: two gauges on one tool → `-40` and `-41`.
- Importer: dry run writes nothing; a second real run adds no duplicates; an
  unmatched tool number is reported rather than silently created.
- Process flow: the VW426 fixture yields mold → degate → gauge for 3450, and a
  merge at `3454-30` for 3454/3455/3457.
