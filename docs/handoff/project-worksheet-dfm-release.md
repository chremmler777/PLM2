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

1. `scripts/set_1994_tool_fields.py`: cavities and cycle times from RFQ 26
   loop 37 (ISOFIX 199403 = 4 cavities). Tonnage stays empty; toolmaker with
   `--toolmaker "<supplier>"` once known.
2. Thumbnails: `scripts/export_rfq_thumbnails.sql` against the RFQ2 prod DB
   (RFQ 26), copy the jsonl into the PLM container, then
   `scripts/import_1994_thumbnails.py --file <jsonl>`.
3. `scripts/import_1994_worksheet_notes.py --xlsx <Excel> --user <id>`: the
   engineering Excel (Brose 1994 RFQ26 BOM clean with open points
   2026-09-23.xlsx) as comments and flags, material as new, colour codes,
   grains and the four Tier 1 numbers the Excel resolves. Never overwrites
   PLM values; differences become open flags. A second run finds nothing to do.

Never copy the local RFQ2 or plm databases to prod; prod data is the truth.

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
