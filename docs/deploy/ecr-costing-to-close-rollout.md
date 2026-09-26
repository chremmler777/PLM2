# Rollout: ECR costing to close (feature/ecr-costing-to-close)

Status: PREPARED, NOT EXECUTED. Run only on the project owner's explicit
"deploy". Written 2026-09-25 against the branch head in the worktree
`/home/nitrolinux/claude/plm2-ecr` (66 commits on top of main `f4b354e5`).

Prod as of 2026-09-25: `/data/compose/plm2` at `f4b354e5`, alembic `086`
(see the adminpanel runbook `docs/plm2-prod-deploy-runbook.md` §11, row
2026-09-25). This rollout takes prod from `086` to the branch head (`101` or `102`,
see below). Procedure and names follow that runbook §10 and the release note
`docs/handoff/project-worksheet-dfm-release.md` (main repo).

Spec: `docs/superpowers/specs/2026-09-25-ecr-costing-to-close.md`.

## What is in it

Change management from costing to close: quote and detailed plan (Gantt with
links and calendar), customer offer with PDF, release checklist, lessons
step, validation issues (failure branch of stage 9), actual costs and P&L
(offer versus doing), the Finance cost sheet (rates per department and plant,
machine classes by tonnage, sampling, overheads) with costing priced from it,
KTX Weissenburg / Solingen (mother plant) changes, early-stage polish,
revision intake (every new customer index is triaged by Development), the
project team (one responsible per role per project), ECR training record
(recorded, not blocking).

No new Python or npm dependencies (requirements.txt and package.json are
unchanged against main). The image rebuild is still mandatory: code and
migrations are baked into it.

## Migrations 085 to 102

085 and 086 are already on prod (deployed 2026-09-25) and are listed for
completeness. On Postgres the whole `alembic upgrade head` run is ONE
transaction (`alembic/env.py`, no transaction_per_migration): if any step
fails, nothing of 087..head stays.

| Rev | What it does | Data-touching | Downgrade risk |
|---|---|---|---|
| 085 | `change_concerns.checklist_key` (the checklist row a risk came from). Already on prod. | No | Drops the column: row links of risks lost. |
| 086 | `change_concerns.retracted_at/by` (raiser deletes a risk). Already on prod. | No | Drops both: retractions lost (risks reappear). |
| 087 | Five new tables: `change_plan_tasks`, `change_plan_feedback`, `change_plan_deviations`, `change_offers`, `change_release_checks`; on `change_requests`: `plan_revision` (default 0), timing validated at/by, `accepted_offer_id`, lessons done at/by/none reason; plus `offer_id` / `change_id` link columns. | No (schema only; new NOT NULL column has a server default) | Drops the five tables and columns: every plan, offer, release check made after deploy is lost. |
| 088 | Gantt 2.0: `change_plan_tasks.parent_id/constraint_type/constraint_date`, new `change_plan_links` (FS/SS/FF/SF + lag), `change_requests.plan_calendar`, `change_plan_deviations.caused_by_task_id`; converts legacy `predecessors` JSON into FS links; backfills and tightens NOT NULL on 087 columns. | Yes, but only rows of the 087 tables (empty on prod at deploy) | Converts FS links back into predecessor lists; SS/FF/SF links and lags are lost; drops the links table and new columns. |
| 089 | Unique index on `change_plan_links (change_id, plan, from_task_id, to_task_id)`; deletes duplicate links first (oldest kept). | Yes (DELETE of duplicate links; table is new, so none on prod) | Drops the index only; deleted duplicates are not restored (harmless). |
| 090 | Validation issues: `change_validation_issues`, `..._actions`, `..._escalations`; `change_attachments.validation_issue_id`. | No | Drops the three tables and the column: all issues lost, attachments stay but lose the link. |
| 091 | `change_actual_costs` (supplier invoices, scrap, other). No currency column (see 101). | No | Drops the table: all actual costs lost. |
| 092 | Cost sheet tables (`cost_sheet_versions`, `_rates`, `_machine_classes`, `_machine_rates`, `_sampling_rates`, `_overheads`) and `org_settings`. INSERTS the "Finance" department if missing. Migrates `department_rate` into cost sheet version 1 per organisation (latest row per department x plant, currency EUR). `department_rate` itself untouched. | Yes (INSERT department, versions, rates) | Drops all cost sheet tables and `org_settings` (training gate org setting included). The Finance department row stays. |
| 093 | `change_requests.origin` (customer / internal / mother_plant, default customer) + mother plant name, ref, SOP; new `change_info_receipts`. Backfills origin from `customer_relevant` (NULL counts as internal). | Yes (UPDATE every change_requests row) | Drops the columns and receipts: mother-plant changes lose their origin and read-and-understood records. |
| 094 | `plants.currency` (default EUR, set to USD where location/name/code contains `US`, `USA` or `UNITED STATES`; recomputed for EVERY plant); `cost_sheet_versions.draft_lock` + unique one-draft index; `machine_class_id` on machine and sampling rates (backfilled by name, missing classes created); `cost_sheet_overheads.currency`; row currencies follow the plant (values are NOT converted); the single 092 version is rebuilt as a chain, one published version per `effective_from` date. | Yes (UPDATE plants, rates; DELETE + INSERT versions and rates; INSERT machine classes) | Collapses the migrated chain back to one version with currency EUR; currencies Finance set are lost; created machine classes stay. Do not downgrade once Finance has worked on the cost sheet. |
| 095 | `change_assessments.pending_rasic_letter`; `change_requests.title_auto` (default false), `scope_changed_after_quote` (default false), scope change at / reason / department ids; `change_meetings.cost_carrier`; `change_concerns.settled_as`, backfilled for withdrawn risks (author if the raiser withdrew it, else pm). | Yes (UPDATE withdrawn change_concerns) | Drops the columns: settlement attribution and scope-change markers lost. |
| 096 | `revision_intakes` and `change_review_answers`. Existing revisions untouched; only indexes received after deploy create intakes. | No | Drops both tables. Revisions received after deploy stay `in_review` (not active) with no intake to decide them: fix by hand. |
| 097 | `project_responsibles` (project team), unique (project, department). | No | Drops the table: the team is lost (prefill can be rerun). |
| 098 | Rate snapshot on `costing_positions` (rate, currency, source, cost sheet version, match, date, detail, `labour_position`, `trials`, `machine_class_id`); on `assessment_cost_line` (currency, version, source); `change_requests.machine_class_id`; on `implementation_bookings` (`labour_position`, `machine_class_id`, `machine_hours`). Data fix: an org with `department_rate` rows but no cost sheet version gets version 1 (valid from its earliest rate, 2020-01-01 when undated), in the plant currency. | Yes (INSERT version and rates only where an org has none) | Drops the columns: priced snapshots lost (lines go back to live pricing). The version created by the fix stays. |
| 099 | `costing_positions.rate_currency` (backfilled from `currency` where a snapshot exists); clears `rate_on` where `rate` is NULL; `assessment_cost_line.rate_snapshot` becomes nullable. | Yes (UPDATE costing_positions; raw SQL, but no booleans, so dialect-safe) | Sets NULL `rate_snapshot` to 0 and makes it NOT NULL again (rate-less lines then read as priced at 0); drops `rate_currency`. |
| 100 | Training: `training_versions`, `training_signoffs`, `training_attempts`. | No | Drops the three tables: all sign-offs and attempts lost. |
| 101 | ONLY IF PRESENT at deploy time (another agent may add "actual cost currency"): expected to add a currency to `change_actual_costs`. Read it before the deploy: check whether it backfills existing rows (from the plant currency?) and whether its downgrade drops the column. Adjust the expected head below. | Read it | Read it |
| 101 or 102 | Toccoa plant currency set to USD explicitly (094's `US` / `USA` word match may miss `Toccoa, GA`). Takes the next free number after the actual cost currency migration, if that ships. | Yes (UPDATE the Toccoa `plants` row) | Read it: a downgrade may leave the currency as set. |

Summary: nothing drops or rewrites existing business data except 093
(origin backfill), 094 (plant currencies, cost sheet rebuild), 095
(settled_as backfill) and 099 (costing position cleanup). A downgrade is
lossy for everything created after deploy; the real rollback is the backup.

## Environment

The prod backend is defined in the PARENT compose file
`/data/compose/docker-compose.yml`, block `plm2-backend`, NOT in the repo's
`docker/docker-compose.prod.yml`. The repo file now passes these variables
(commit on this branch), but prod only sees them if they are added to the
prod block. All are optional: unset or empty keeps the default.

| Variable | Default (backend/app/services/company_profile.py, app/utils/clock.py) | Recommendation |
|---|---|---|
| `KTX_COMPANY_LEGAL_NAME` | `KTX Group US Corp.` | keep default |
| `KTX_COMPANY_ADDRESS` | `325 Hammerstone Drive|Toccoa, GA 30577|United States of America` | keep default |
| `KTX_COMPANY_PHONE` | `+1 706 963 1110` | keep default |
| `KTX_COMPANY_FAX` | `+1 706 963 1052` | keep default |
| `KTX_COMPANY_EMAIL` | `ktx_info@us.ktx.group` | keep default |
| `KTX_COMPANY_WEBSITE` | `ktx.group` | keep default |
| `KTX_COMPANY_FOOTER` | `IATF 16949:2016 certified site|A company of the KTX Group` | keep default |
| `KTX_COMPANY_SIGNATURE_NAME` | empty | not needed, leave unset: Sales signs. On send the sender is frozen as signer when they are a Sales member; otherwise (PM lead, admin) the project's Sales responsible, else the "Sales" role line with no name. A draft previews exactly that for the viewer, labelled "Signed by (preview)". Set only to force one fixed name on every offer |
| `KTX_COMPANY_SIGNATURE_TITLE` | `Sales` | not needed, leave unset (set only to force one fixed title) |
| `PLM_BUSINESS_TZ` | `America/New_York` (IANA name; drives the business date of deadlines, plan dates, offers) | set explicitly to `America/New_York` |
| `PLM_RELEASE_ROWS_SINCE` | `2026-09-26T04:00:00Z` (midnight New York on 26 Sep; backend/app/services/release_checklist.py) | set to the deploy moment in UTC (ISO 8601, e.g. `2026-09-27T14:30:00Z`; no offset means UTC). Changes released before it do not get the four new Quality / Process Engineer release rows; every change not yet released does |

Lists are separated by `|`. Not needed: `TRAINING_GATE` (training is
recorded, not blocking; the gate stays off, and it is also an org setting).

Add to the prod `plm2-backend` environment (back up the compose file first):

```yaml
      PLM_BUSINESS_TZ: America/New_York
      PLM_RELEASE_ROWS_SINCE: "<deploy moment, UTC, e.g. 2026-09-27T14:30:00Z>"
```

For `PLM_RELEASE_ROWS_SINCE` take the moment the backend is stopped in step
4 (`date -u +%Y-%m-%dT%H:%M:%SZ` on the server, noted in the deploy log) so
nothing released on the old code falls after it.

### New release rows for changes in flight

The release checklist gains four rows, 13 to 17:

- Quality: "Parts measured and PPAP / initial sample documentation
  complete" (samples / PPAP) and "Control plan / inspection plan updated".
- Process Engineer: "Process parameters and work instructions updated" and
  "Process FMEA updated" (PFMEA).

Every change not yet released at the deploy moment (in validation or
earlier) gets them as open rows and cannot be released until Quality and
Process Engineer answer each one done, or mark it n/a with a note (PM, the
change lead or an admin may also answer). Changes released before
`PLM_RELEASE_ROWS_SINCE` are left as they were. Tell Quality and Process
Engineer (step 7) and the leads of changes in validation.

## Preflight (local, before the go)

1. Branch merged to main on the owner's go (no merge is part of this
   document). Check the tree is complete: `alembic heads` shows one head
   (`101` or `102`, see the migration table).
2. Full suites on a clean checkout of the merge commit: backend
   `python -m pytest -q` (xdist), frontend `npx vitest run`, `npx tsc
   --noEmit`. Record the counts in the deploy log.
3. Prefill script test: `python -m pytest tests/test_prefill_project_team.py
   -n 0 -q` (11 tests).
4. Routing sweep test: `python -m pytest tests/test_change_routing.py -n 2 -q
   -k sweep` (dry run writes nothing, `--apply` is idempotent). The sweep
   itself runs on prod in step 5a.

## Prod steps

SSH per the fail2ban procedure: `source ~/.ssh/agent.env && ssh-add -l`
must list the key, then `ssh -o BatchMode=yes ktx-server`. On a password
prompt or "Permission denied": STOP, do not retry.

### 0. Read-only checks on prod (before anything changes)

```bash
cd /data/compose
docker exec compose-plm2-backend-1 alembic current            # expect 086
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select id, name, code, location from plants order by id;"
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select d.name, p.name as plant, r.hourly_rate, r.effective_from from department_rate r join wf_departments d on d.id = r.department_id join plants p on p.id = r.plant_id order by p.name, d.name, r.effective_from;"
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select id, name, is_active from wf_departments order by sort_order;"
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select count(*) filter (where customer_relevant) as customer, count(*) filter (where not customer_relevant or customer_relevant is null) as internal from change_requests;"
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select count(*) from parts; select count(*) from part_revisions; select count(*) from projects; select count(*) from change_requests; select count(*) from lessons_learned;"
```

What to look for:

- Plants: 094 sets USD only when location, name or code contains the word
  `US` / `USA` or `UNITED STATES`, so a Toccoa row that reads e.g.
  `Toccoa, GA` would become EUR. A new migration on this branch (101 or
  102, whichever number is free) sets the Toccoa plant currency to USD
  explicitly, so this no longer depends on the word match. Verify after the
  migration (step 3 on `plm_scratch`, step 4 on prod) with
  `select id, name, code, location, currency from plants order by id;`:
  Toccoa must read `USD`. If it does not, stop and check that migration is
  in the build (rates keep their numbers either way; nothing is converted).
  Silao (Mexico) becomes EUR: Finance decides the currency.
- Department rates: note which departments have a Toccoa rate. There is no
  Project Manager rate today (see the Finance to-do).
- Departments: `Project Manager`, `Manufacturing Engineer`, `Tool Engineer`,
  `APQP`, `Development` must exist and be active for the team prefill.
  `Finance` is created by 092 if missing.
- Keep the counts for the post-deploy comparison.

### 1. Back up the compose file (and optionally an early DB copy)

```bash
set -o pipefail
cp /data/compose/docker-compose.yml /data/compose/docker-compose.yml.bak-$(date +%Y%m%d-%H%M%S)-plm2-ecr
# optional early copy; NOT the rollback backup (users keep working until step 4)
docker exec compose-plm2-db-1 pg_dump -U plm -d plm | gzip \
  > /data/compose/db-backups/plm2-early-ecr-costing-to-close-$(date +%Y%m%d-%H%M%S).sql.gz
```

The authoritative backup is taken in step 4, after the backend is stopped,
so it holds every write up to the outage.

### 2. Pull and build (no recreate yet)

```bash
cd /data/compose/plm2 && git fetch origin && git merge-base --is-ancestor HEAD origin/main && git pull --ff-only origin main
cd /data/compose && docker compose build plm2-backend plm2-frontend
```

### 3. Dry run on a scratch copy (with timing)

```bash
docker exec compose-plm2-db-1 dropdb -U plm --if-exists plm_scratch
docker exec compose-plm2-db-1 createdb -U plm plm_scratch
docker exec compose-plm2-db-1 sh -c "pg_dump -U plm -d plm -Fc | pg_restore -U plm -d plm_scratch --no-owner"
docker images | grep plm2-backend        # the freshly built image name
time docker run --rm --network compose_ktx-net \
  -e DATABASE_URL=postgresql+asyncpg://plm:<password>@plm2-db:5432/plm_scratch \
  <new plm2-backend image> alembic upgrade head
```

Then on `plm_scratch`: `alembic_version` = the head (`101` or `102`), the counts from
step 0 unchanged, `select id, name, currency from plants;` with Toccoa `USD`,
`select organization_id, version, status, valid_from, note from
cost_sheet_versions order by 1, 2;` shows a published chain,
`select count(*) from cost_sheet_rates;` greater than 0. Run the prefill dry
run against the scratch DB too (step 6 with `-e
DATABASE_URL=...plm_scratch` via `docker run`). Drop `plm_scratch` after.

If the upgrade takes longer than about 20 seconds, do NOT rely on the startup
migration (next step explains why).

### 4. Migrate, then recreate

`app/main.py` runs `alembic upgrade head` at startup with a 30 second
timeout, in every uvicorn worker. Fourteen migrations with the 094 data
rebuild must not race two workers or be cut off by the timeout. So migrate
explicitly while the backend is stopped (short outage, announce it):

```bash
cd /data/compose
set -o pipefail
docker compose stop plm2-backend
# authoritative backup: backend stopped, nothing writes any more
docker exec compose-plm2-db-1 pg_dump -U plm -d plm | gzip \
  > /data/compose/db-backups/plm2-before-ecr-costing-to-close-$(date +%Y%m%d-%H%M%S).sql.gz \
  && echo BACKUP OK
ls -l /data/compose/db-backups/ | tail -3; zcat /data/compose/db-backups/plm2-before-ecr-costing-to-close-*.sql.gz | head -5
docker compose run --rm --no-deps plm2-backend alembic upgrade head
docker compose run --rm --no-deps plm2-backend alembic current     # must show the head (100, 101 or 102)
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select id, name, code, location, currency from plants order by id;"   # Toccoa = USD
```

Do not run `alembic upgrade head` unless `BACKUP OK` was printed and the
dump is not empty. Note the backup file name in the deploy log.

Add the environment lines (section Environment) to the `plm2-backend` block
now, then:

```bash
docker compose up -d plm2-backend plm2-frontend
docker exec compose-plm2-backend-1 alembic current                 # again: the head
docker exec compose-plm2-backend-1 printenv PLM_BUSINESS_TZ
docker exec compose-plm2-backend-1 printenv PLM_RELEASE_ROWS_SINCE     # the deploy moment, UTC
docker compose exec nginx nginx -s reload                          # new container IP
docker exec compose-plm2-backend-1 python -c "from OCC.Core.STEPControl import STEPControl_Reader"   # prints nothing
```

### 5. Smoke checks

Base `https://apps.ad.us.ktx.group/plm2/`. HTTP: `curl -sk -o /dev/null -w
'%{http_code}\n' https://localhost/plm2/` = 200; `/plm2/api/v1/auth/me`
without cookie = 401 JSON. API checks with a cookie-minted token only (a
Bearer token is treated as a service token), roles as objects
`[{"name": "plm2_Admin", "system": "plm2"}]`. All 200:

- `/plm2/api/v1/changes`
- `/plm2/api/v1/cost-sheet` and `/plm2/api/v1/cost-sheet/lookup/rate?...` (a Toccoa department)
- `/plm2/api/v1/pnl/summary`, `/plm2/api/v1/pnl/changes`
- `/plm2/api/v1/projects/35/team` (1994), and the same for the 2277 and VW426 project ids
- `/plm2/api/v1/intakes/my`
- `/plm2/api/v1/training/status`, `/plm2/api/v1/training/roster`
- `/plm2/api/v1/changes/<an open change id>/offers`
- Regression: `/plm2/api/v1/parts/project/35`, `/plm2/api/v1/sep/projects/35`, `/plm2/api/v1/lessons`, `/plm2/api/v1/paints`, `/plm2/api/v1/projects/35/worksheet`, `equipment?tool_number=3450` (PDB service path)

In the browser (as the owner, hub login):

- `/plm2/changes` list, then one open change `/plm2/changes/<id>`: cockpit, stages, costing tab shows rates from the cost sheet (or "No rate" where none), process flow Detailed and Overview.
- `/plm2/changes/<id>/plan/quote` and `/plan/detailed`: Gantt renders, links draw.
- Offer PDF from the offer card: letterhead shows KTX Group US Corp., Toccoa address. A sent version is signed by the Sales member who sent it (sent by a PM lead or an admin: the project's Sales responsible, else the "Sales" line with no name). A draft shows "Signed by (preview)" with who would sign if you sent it now: you when you are in Sales, otherwise the project's Sales responsible, else the "Sales" line.
- Release tab of a change in validation: 17 rows, the four new Quality / Process Engineer rows open. A change released before the deploy: 13 rows.
- `/plm2/cost-sheet`: published version chain, Toccoa rows in USD, one draft at most.
- `/plm2/pnl` and `/plm2/reports`: cost report per currency.
- `/plm2/my-tasks`: counts plausible, backup markers after the prefill.
- `/plm2/projects/35` (1994): Project team card.
- `/plm2/training`, `/plm2/training/handout/<role>`: roster loads, gate reads off.
- `/plm2/process-map`, `/plm2/projects`, `/plm2/parts/<id>`, `/plm2/lessons`: unchanged pages still load.

Counts from step 0 identical; `docker logs compose-plm2-backend-1 --since
10m | grep -c " 500 "` = 0; container restarts = 0.

### 5a. Routing task sweep (after the migration and the smoke checks)

Changes in flight may carry assessment rows of a started routing stage
without their workflow task (a department a deviation added to a later
stage, or one the scoping room pulled in before the snapshot-driven task
creation). The write paths repair their own change from now on; this sweep
does it once for every change with an active change-scoped instance. Dry
run first: it performs the repair per change and rolls it back, so it
prints exactly what `--apply` would write.

```bash
docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
  python scripts/repair_routing_tasks.py                        # dry run
docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
  python scripts/repair_routing_tasks.py --apply
docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
  python scripts/repair_routing_tasks.py                        # must report 0 row(s)
```

Read the dry run: one line per change with the repaired assessment ids.
Lines marked `late, flagged for the lead` are R/A departments added to a
stage that had already passed: they are NOT waived, their task is active and
the change lead is notified (cockpit action "Chase ..."). Tell the leads of
those changes. Lines starting `!!` are errors for that change only (the rest
still ran); note them in the deploy log. Idempotent: rerunning changes
nothing.

### 6. Project team prefill (after the smoke checks)

Owner decision 2026-09-25 (memory `project-team-responsibles-2026-09-25`):
1994, 2277 and VW426 (code 1864): PM Cody (cody.hrtyanski), Manufacturing
Engineer Russ, Tool Engineer Dale (dale.perry), APQP George (VW426: Apurva
M., apurvam), Development Christoph (christoph.demmler).

```bash
docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
  python scripts/prefill_project_team.py                         # dry run
```

Read every line. Rows marked `!!` block `--apply`:

- `ambiguous_user` / `ambiguous_project`: pin the right one with
  `--user-id 'George=<id>'` / `--project-id VW426=<id>` (ids are printed).
- `no_user`: that person never logged in through the hub yet (users are
  created on first login). Ask them to log in once, rerun.
- `not_member`: the user is not in that department. Add the membership in
  PLM, or rerun with `--add-membership` (owner's call).
- `taken`: somebody set another responsible in the UI already. Leave it, or
  `--replace` on the owner's word.
- Check the `note:` lines: Christoph has two accounts on some DBs
  (`christoph.demmler` and `christoph.demmler-1`); the hub-bridged one is the
  exact username `christoph.demmler`.

Then, with the owner's user id as `set_by`:

```bash
docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
  python scripts/prefill_project_team.py --apply --actor-id <owner id> [pins]
```

A second dry run must show every row `unchanged`. Check the Project team
card on the three projects.

### 7. Tell the users

- Development: new customer indexes now wait in revision intake until
  triaged (full ECR, attach, engineering review, administrative).
- Finance: the to-do below.
- Everyone: training record is live but not blocking.
- Quality and Process Engineer: changes in validation now carry four more
  release rows (Quality: samples / PPAP, control plan; Process Engineer:
  process parameters / work instructions, PFMEA) to answer done or mark
  n/a with a note before the change can be released.

## Finance to-do (open after deploy)

1. Confirm the Toccoa cost sheet rates are USD. 094 relabels the Toccoa
   rows as USD without converting the numbers, so the numbers must already
   be dollar rates (the old `department_rate` table had no currency).
   Confirm or correct them on `/plm2/cost-sheet` in a new draft, publish.
2. Add a Project Manager rate for Toccoa. There is none today, so PM hours
   on a costing line show "No rate" and stay unpriced in costing, offers and
   the P&L. Add the rate in a new draft version and publish it with the
   right valid-from date (lines priced earlier keep their snapshot; lines
   without a rate price live once the rate exists).
3. Toccoa plant currency: the new migration (101 or 102) sets it to USD
   explicitly, because 094's `US` / `USA` word match may miss `Toccoa, GA`.
   Confirm with the plants query (step 4) that Toccoa reads `USD`.
4. Decide the Silao (Mexico) currency if Silao rates are used.
5. If 101 ships: check the currency of any actual costs already entered.

## Rollback

Decide by what broke.

- Code only, schema fine (UI or API bug): first make the old code's
  assumption true again: at `f4b354e5` `assessment_cost_line.rate_snapshot`
  is required (non-null), migration 099 made it nullable, so rate-less lines
  written since the deploy would break the old code:

  ```bash
  docker exec compose-plm2-db-1 psql -v ON_ERROR_STOP=1 -U plm -d plm \
    -c "UPDATE assessment_cost_line SET rate_snapshot = 0 WHERE rate_snapshot IS NULL;"
  ```

  Those lines then read as priced at 0 (not "No rate"); note the count the
  UPDATE prints. Then `cd /data/compose/plm2 && git checkout f4b354e5`,
  `docker compose up -d --build plm2-backend plm2-frontend`, nginx reload.
  Every other column 087..102 added to an existing table is nullable or has
  a server default, so the old code runs on the new schema; its startup
  `alembic upgrade head` only logs a warning about the unknown revision. New tables sit unused. Revisions received since deploy
  may be `in_review`; set them active by hand if needed. Return to main
  afterwards (`git checkout main`).
- Migration failed during step 4: nothing was applied (one transaction).
  `alembic current` still shows 086. `docker compose up -d plm2-backend`
  with the old image is not possible after the rebuild, so check out
  `f4b354e5` and rebuild as above.
- Data wrong after migration (cost sheet, currencies, origins): restore the
  backup rather than downgrade; the downgrades lose data (table above). Use
  the authoritative backup from step 4
  (`plm2-before-ecr-costing-to-close-<ts>.sql.gz`), not the optional early
  copy from step 1.

  ```bash
  set -o pipefail
  docker compose stop plm2-backend
  docker exec compose-plm2-db-1 psql -v ON_ERROR_STOP=1 -U plm -d postgres -c "drop database plm;" -c "create database plm owner plm;"
  zcat /data/compose/db-backups/plm2-before-ecr-costing-to-close-<ts>.sql.gz | docker exec -i compose-plm2-db-1 psql -v ON_ERROR_STOP=1 -U plm -d plm
  cd /data/compose/plm2 && git checkout f4b354e5 && cd .. && docker compose up -d --build plm2-backend plm2-frontend
  docker exec compose-plm2-backend-1 alembic current                 # 086
  docker compose exec nginx nginx -s reload
  ```

  Anything entered after the deploy is lost with a restore; export it first
  if users worked in the meantime.
- Env: remove the added lines from the compose block (backup from step 1).

## Deploy log

(fill in: commit, alembic before/after, backup file, dry-run timing, test
counts, smoke results, prefill output, Finance confirmation)
