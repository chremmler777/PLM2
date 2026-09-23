---
name: 1994-brose-volume-sheet-2026-09-23
description: Brose finished-part volume sheet for 1994 received 2026-09-23 - mapping to PLM parts, lifetime volume and shot deltas vs the nominated RFQ 26, open points for Brose, PLM ISOFIX cavity note wrong
metadata:
  type: project
---

**Received 2026-09-23 (via the US team, with the "DFM urgency" mail):** a Brose sheet
"Project 1994 / Brose-Sitech / OEM VW Scout / Project BRUV" listing 12 rows with
Brose finished part numbers (suffix -110), Brose material-master names, "Ø Volume
p.a." and "Volume LT". Ø p.a. is simply LT/10, not a peak year. No VW numbers on
the sheet, so the mapping below is by name and volume only (not verified by Brose).

**Numbers/names vs PLM:** the -110 finished part numbers are a different Brose
numbering level than the -000/-001 drawing numbers in PLM/RFQ2; none match, only
S00G0E-110 shares its base with latch cover 60. One cell is corrupted
("S00H4D-110S00HTD-", belt exit cover, probably merged colour variants). Names:
4 exact, 6 loose, 2 conflicts (side shield row says RH, we hold LH only; the two
"Handle Grif" and two "Latch Trim" rows cannot be told apart). Brose's A-bracket
Outer = 799, Inner = 800 agrees with the drawing title blocks (the RFQ naming was
the one off). All 12 rows map onto the 12 nominated parts, nothing extra or missing.

**Lifetime shots, cavities unchanged (cavities = RFQ 26 nominated loop 37 REV8 on prod):**

| Tool | VW number | PLM name | Cav | Nominated LT | New LT | Shots nom. | Shots new |
|---|---|---|---|---|---|---|---|
| 199401 | 206.882.251/252 | Handle, height adjustment LH/RH | 2 (1+1) | 463,612 each | 413,006 each | 463,612 | 413,006 |
| 199402 | 206.885.967/968 | Latch cover 40/60 | 2 (1+1) | 1,019,000 each | 966,000 each | 1,019,000 | 966,000 |
| 199403 | 206.887.233 | Isofix cover | 4 | 4,076,000 | 7,728,000 | 1,019,000 | **1,932,000** |
| 199404 | 206.881.800 | A-bracket inner trim | 2 | 163,017 | 143,475 | 81,509 | 71,738 |
| 199405 | 206.885.219 | Cover trim, center back | 2 | 744,654 | 705,923 | 372,327 | 352,962 |
| 199406 | 206.886.197 | Center bearing cover | 2 | 1,019,000 | 966,000 | 509,500 | 483,000 |
| 199407 | 206.883.607 | Belt exit cover | 2 | 1,182,017 | 1,109,475 | 591,009 | 554,738 |
| 199408 | 206.881.479 | Inner side shield | 2 | 143,000 | 143,475 | 71,500 | 71,738 |
| 199409 | 206.881.793 | Decor cover | 8 | 1,663,000 | 4,181,984 | 207,875 | **522,748** |
| 199410 | 206.881.799 | A-bracket outer trim | 2 | 143,000 | 143,475 | 71,500 | 71,738 |

Most parts drop 5-12%. ISOFIX +90% and the painted decor cover +151% change the
DFM basis (tool life, cavities, tonnage, cycle). Handles at 413,006 exactly equal
the not-awarded Griff 5NA.881.253 volume from the RFQ, so Brose may have mapped
the wrong part.

**Open with Brose before any DFM commitment on 1994:** cross-reference table
finished part number / drawing number / VW number per row; volume basis for ISOFIX
and decor cover (positions per seat? all colours? forecast change?); side shield
LH vs RH; meaning of the header block (OEM "VW Scout", project "BRUV", invest
line 5,000,000 with "no" invest necessary).

**Data findings:** prod PLM tool 199403 relation note says "2 cavities", the
nominated RFQ says 4 (RFQ2 UI shows CAV 4, 1.0M shots; the DB column
tooling_variant_items.total_shots_needed is a cache the UI does not use). Local
PLM and local RFQ2 are older than prod (ISOFIX 2 cav, side shield 1 cav) - see
[[prod-data-is-truth-2026-09-22]]. Our own RFQ 26 BOM has a merged number cell on
the RH side shield row ("S00FX2-001206_881_480"). The user's screenshot still
showed RFQ names, i.e. a pre-rename environment; prod names come from the
B-release drawing title blocks, see [[1994-nominated-e1-reset-2026-09-22]] and
[[brose-award-import-2026-09-02]].

**Reply context (same day):** DFM is engineering + PM, not sales; 1994 DFMs a couple
of days out; 2277 not awarded to the toolshop, no DFMs and a team risk analysis
needed first; Karl to supply sold state per part (series material + datasheets,
tonnage class, target cycle time, official timing: DFM design freeze, FOT, home-line
FOT); Brose contacts needed for a DFM review series and a PM kick-off.

**Shipped 2026-09-23 (prod, commit c59f3fb7, alembic 076, backup
db-backups/plm2-before-076-20260923-155343.sql.gz):** `parts.tier1_part_number`
next to the OEM `customer_part_number`; 8 Brose -110 numbers set on 1994 via
`backend/scripts/set_1994_tier1_numbers.py`. Still empty, pending Brose
cross-reference: handles 206.882.251/252 (S00H4X-110 / S00H4W-110) and latch
covers 206.885.967/968 (S00H56-110 / S00G0E-110). Tool view + DFM archive spec:
docs/superpowers/specs/2026-09-23-tool-dfm-archive-design.md.

**Tool view + DFM archive (plan docs/superpowers/plans/2026-09-23-tool-dfm-archive.md):**
alembic 077 (tool fields on parts) and 078 (dfm_topics / dfm_entries / dfm_entry_files);
`/api/v1/parts/{id}/dfm/...`; tools open in `ToolDetail` (no 3D, produced-article chips,
Tool card, DFM archive with three-column ledger). Prod: back up, `alembic upgrade head`
in the backend container, then `scripts/set_1994_tool_fields.py` dry run and `--apply`
after the cavities / cycle / tonnage are confirmed against RFQ 26 loop 37. Verification
(task 14, 2026-09-23): full backend/frontend suites and tsc already green on this branch;
lint clean on the files this branch touched. Fresh-SQLite `alembic upgrade head` from an
empty DB fails on migration 001 (pre-existing, predates this branch: SQLite can't ALTER
ADD CONSTRAINT outside batch mode). More concerning, 077's own `downgrade()` fails on
SQLite too: `op.drop_column("parts", "toolmaker_id")` hits "unknown column in foreign key
definition" because the column carries an inline FK and SQLite refuses to drop an
FK-referenced column without a table rebuild (`op.batch_alter_table`). Verified by
building the schema with `Base.metadata.create_all` + `alembic stamp head` (same trick
the test suite's own conftest uses), then exercising 077/078 for real: 078's downgrade
(plain drop_table) is clean; 077's downgrade needs batch mode to work on SQLite before
anyone relies on rolling back past 077 on a SQLite deployment. Full end-to-end walkthrough
via curl against this scratch DB passed: tool + article parts, `produces` relation
(`other_active_revision_name` present), tool fields set and surviving reload, 400 on tool
fields for an article, topic opened, 4 ledger entries (ktx to toolmaker+tier1 with a PDF
and an xlsx, toolmaker to ktx, an update superseding the first with 1 earlier version in
`history`, tier1 after reopen), xlsx download and inline PDF both correct, xlsx inline
correctly 415s, close then 409 on a new entry, reopen, changelog lists `dfm_topic_opened`,
`dfm_entry_recorded` x4, `dfm_topic_closed`, `dfm_topic_reopened` in order.

