# Release: project page, DFM archive, worksheet (main 7954ef68)

Date: 2026-09-24. Status: on `main` and **deployed to prod** 2026-09-24
(alembic 084), 1994 data scripts applied the same day.

User guide: `docs/guides/project-worksheet-and-dfm.md`.

## What is in it

| Area | What | Migration |
|---|---|---|
| Tool fields | cavities, toolmaker, tonnage class, target cycle time on tools | 077 |
| DFM archive | topics per tool, entries with files, append-only | 078 |
| Thumbnails | article and tool thumbnails on the items list | 079 |
| DFM flow | message kinds (original, forward, answer, question), reply links, waiting / answered | 080 |
| DFM audit | audit log per topic: messages, files, views, downloads, SHA-256 per file | 081 |
| Field notes | comments and flags (open, confirmed, rejected) on any worksheet field | 082 |
| Material | article material linked to MaterialDB, or "new, not in MaterialDB" | 083 |
| Colour, grain | moulded-in colour code (e.g. NM0) and grain (e.g. KF8) on articles | 084 |

Also: the project page redesign (SEP gate bar, grouped items list,
thumbnails, KTX / Tier 1 / OEM numbers, mirror brackets, detail tabs,
pop-out), the worksheet (filter, sort, columns, xlsx export, right-click
Edit / Comment / Flag) and the worksheet audit log (CSV export).

## Tests at release

Backend 1152 passed, frontend 1061 passed, `tsc` and eslint clean
(2026-09-24). Browser checks on the local test stack with project 1994.

## Prod deploy

Only on the go from the project owner. SSH per the fail2ban procedure
(key in ssh-agent, check `ssh -o BatchMode=yes ktx-server`; on a password
prompt or "Permission denied" stop, do not retry).

1. Back up the prod DB (`/data/compose`, `db-backups/plm2-before-084-<ts>.sql.gz`).
2. Set in the prod `.env`: `MATERIALDB_BASE_URL` (MaterialDB API root inside
   the docker network) and `MATERIALDB_SERVICE_TOKEN` (same value as
   MaterialDB's own). Without them the material search answers 503;
   everything else works. Never put the token in the repo or in logs.
3. `git pull`, `docker compose up -d --build plm2-backend plm2-frontend`.
4. `alembic upgrade head` in the backend container; `alembic current` must
   show 084. Reload nginx.
5. Smoke test: project 1994 page, a tool's DFM tab, the worksheet, export.

## 1994 data on prod (after the deploy)

All scripts are dry run by default; read the dry run, then add `--apply`.
Run in the prod backend container with `-e PYTHONPATH=/app`. Check the PLM
user id to record as (`--user`) on prod first; it differs from local.

1. `scripts/set_1994_tool_fields.py`: cavities (total per tool) and cycle
   times from RFQ 26 loop 37. Tonnage stays empty; toolmaker with
   `--toolmaker "<supplier>"` once known. RFQ2 stores cavities per article
   (`tooling_variant_items.cavities`); a tool's total is the sum over its
   articles, which equals the cavity count of the tool layout.
2. Thumbnails: `scripts/export_rfq_thumbnails.sql` against the RFQ2 prod DB
   (RFQ 26), copy the jsonl into the PLM container, then
   `scripts/import_1994_thumbnails.py --file <jsonl>`.
3. `scripts/import_1994_worksheet_notes.py --xlsx <Excel> --user <id>`: the
   engineering Excel (Brose 1994 RFQ26 BOM clean with open points
   2026-09-23.xlsx) as comments and flags, material as new, colour codes,
   grains and the four Tier 1 numbers the Excel resolves. Never overwrites
   PLM values; differences become open flags. A second run finds nothing to do.

Never copy the local RFQ2 or plm databases to prod; prod data is the truth.

## Prod log 2026-09-24

All steps as PLM user 14, dry run first.

- **1994 data:** tool fields (10 tools), worksheet import (112 changes;
  second run: nothing to do), thumbnails (12 articles, 10 tools from RFQ2
  RFQ 26). All 12 articles now carry a Tier 1 number.
- **Cavities checked on all ten tools** against RFQ 26 loop 37 (article sum
  and tool layout agree):

  | Tool | Cavities |
  |---|---|
  | 199401 Handle LH/RH | 4 (2+2) |
  | 199402 Latch cover 40/60 | 4 (2+2) |
  | 199403 ISOFIX | 4 |
  | 199404 A-bracket inner | 2 |
  | 199405 to 199408 | 2 each |
  | 199409 Decor cover | 8 |
  | 199410 A-bracket outer | 2 |

  The first run of the tool script set 199401 and 199402 to 2 (it took the
  per-article value); corrected to 4 with the fixed script. The ISOFIX
  "produces" link note said "2 cavities" (loop 28 value) and now says 4,
  logged on both parts.
- **Cavity flags closed:** the Excel's open cavity questions (199401 to
  199404, 199409, 199410) have a "Checked 2026-09-24" comment and the flag
  confirmed. The Excel's "frozen RFQ" cavity values for 199403, 199404,
  199409 and 199410 were the stale tag in the RFQ2 tool name (next point),
  not the real count.
- **RFQ2 stale cavity tags removed** (RFQ2 prod DB, backup
  `db-backups/rfq_db_before_cavitytag_20260924-200806.sql.gz`): the seed
  scripts had written "— raw (N-cavity)" into tool names and "N-cavity" into
  `injection_concept`, which the tool card shows as a chip. Neither followed
  the real cavities (e.g. Seat back upper trim showed "2-cavity", real 8).
  Stripped from 57 names and cleared on 58 tools (RFQ 22 to 26); the
  estimator treats both the same, so no cost changed. Left as they are:
  RFQ 21 "1/1 single-cavity (incumbent reference)" and RFQ 22
  "(2-cavity min)". The code fix (chip guard, clean export names, seeds) is
  handed to the RFQ2 project.
- **Test DFM deleted:** the only prod DFM topic ("dfm" on 199401, one entry,
  no files, a test) with its audit events and two changelog lines. Backup
  `db-backups/plm2-before-dfm-test-delete-20260924-201208.sql.gz`.

## Known limits and follow-ups

- The part changelog (and the worksheet audit log built on it) is complete
  for changes made in PLM, but not hash-chained: `previous_hash` /
  `entry_hash` stay empty for part entries. Only the change and admin audit
  logs are chained. Do not call it tamper-evident.
- 206.883.607 (Belt exit cover) is painted in PLM; the Excel says not
  painted, colour NM0. Correct the article, then the colour note lands on
  the right field.
- The worksheet import takes Excel column L "yes" as painted even when PLM
  says unpainted; such a colour note shows on the second marker of the
  Colour cell.
- Test gaps (non-blocking): colour-code flag dedupe on a re-import, and
  clearing the shown field's flag while the other colour field is still
  flagged.
- `frontend/node_modules` (about 17,000 files, incomplete) is committed to
  git since c53a69ed (2026-02-21); separate cleanup.
