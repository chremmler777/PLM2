# Rollout: ECR costing to close (feature/ecr-costing-to-close)

Status: PREPARED, NOT EXECUTED. Run only on the project owner's explicit
"deploy". Written 2026-09-25, refreshed 2026-09-26 against the final branch
state in the worktree `/home/nitrolinux/claude/plm2-ecr`: head `c8af38a2`
(cost sheet: one rate per department and plant, MachineDB presses, Silao in
USD and MXN) plus its review fixes, on top of main `f4b354e5`, alembic head
`107`. If commits land after `c8af38a2`, re-check `git log --oneline
c8af38a2..HEAD` and `backend/alembic/versions` before the deploy.

Prod as of 2026-09-25: `/data/compose/plm2` at `f4b354e5`, alembic `086`
(see the adminpanel runbook `docs/plm2-prod-deploy-runbook.md` §11, row
2026-09-25). This rollout takes prod from `086` to `107`. Procedure and names follow that runbook §10 and the release note
`docs/handoff/project-worksheet-dfm-release.md` (main repo).

Spec: `docs/superpowers/specs/2026-09-25-ecr-costing-to-close.md`.

## What is in it

Change management from costing to close: quote and detailed plan (Gantt with
links and calendar), customer offer with PDF, release checklist, lessons
step, validation issues (failure branch of stage 9), actual costs and P&L
(offer versus doing), the Finance cost sheet (rates per department and plant,
machine classes by tonnage, sampling, overheads) with costing priced from it,
KTX Weissenburg / Solingen (mother plant) changes (started by the Project
Manager only; scoping records who is informed, no cost carrier), early-stage
polish,
revision intake (every new customer index is triaged by Development), the
project team (one responsible per role per project), ECR training record
(recorded, not blocking). Final-walk fixes on top: routing tasks for every
R/A department (sweep script), plan deviation groups, actual costs with a
currency, undecided D1 gates, Sales signs the offer, offer PDF dates in the
form "26 Sep 2026", the reworked 16-row release checklist, Approve on a
3D-evidence step waits for a CAD file or a signed "no geometry change".

No new Python or npm dependencies (requirements.txt and package.json are
unchanged against main). The image rebuild is still mandatory: code and
migrations are baked into it.

## Migrations 085 to 107

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
| 101 | Three steps, in this order. (1) Toccoa plant currency set to `USD`: whole-word, any-case match on `toccoa` in `plants.name` or `plants.location` (094's `US` / `USA` match misses `Toccoa, GA`); relabel only, no rate converted; not scoped by organisation (one Toccoa plant today). (2) `change_actual_costs.currency` (String(3), nullable), backfilled for every row with the change's costing currency: the plant of the change's only affected plant, else the project's plant, `EUR` when that plant has none (NULL or empty). (3) Standing effort rows (`costing_positions` of kind `internal_effort` / `support_effort`): duplicates per change, department and kind are merged, the most recently updated row kept whole (else the highest id), `costing_offers.position_id` and `change_plan_tasks.source_position_id` re-pointed to it, the others DELETED; then partial unique index `uq_costing_positions_standing`. | Yes (UPDATE plants, UPDATE change_actual_costs, UPDATE + DELETE costing_positions duplicates) | Drops the index and the currency column. Toccoa stays `USD`; merged duplicates are not restored (harmless). |
| 102 | Plan deviation groups: new `change_plan_deviation_groups` (root block, reason, status, decision, escalation), `change_plan_deviations.group_id` (nullable, FK on Postgres, index). Backfill: every OPEN deviation is grouped with the own move that pushed it (the grouping the Timing tab already showed); rows that fit nowhere stay ungrouped. | Yes, only rows of the 087 deviation table (none on prod: plans are new) | Drops `group_id` and the groups table: group decisions and their escalation links lost; the deviations stay. |
| 103 | `change_gate.decision` becomes nullable without a server default; seeded gates nobody touched (`decision = 'na'`, no decider, no decision time) set to NULL (undecided). A gate without `yes` still holds its transition. | Yes (UPDATE change_gate, prod rows included) | Sets every NULL back to `na`, NOT NULL again with default `na`. |
| 104 | One rate per department per plant. `cost_sheet_rates`: duplicates of (version, department, plant) are MERGED in every version, published ones included (plant NULL counts as a plant of its own): the department default row (position NULL) is kept, else the highest id; the kept row loses its position (positions are gone; a line naming one is priced from its department's row). `hourly_rate` becomes NULLABLE (an empty rate = "no rate yet", never 0). Unique index `uq_cost_sheet_rate_dept_plant` on (version_id, department_id, coalesce(plant_id, 0)). Seeds: the open draft of each organisation gets an EMPTY-rate row for every active department and active plant without one; published versions are not seeded. | Yes (DELETE duplicate rate rows, UPDATE position, INSERT empty draft rows) | Drops the index, DELETES the rows without a rate and makes `hourly_rate` NOT NULL again. Merged duplicates and dropped positions are not restored. |
| 105 | MachineDB presses: new `cost_sheet_machines` (synced copy, unique per org and MachineDB id), new `cost_sheet_machine_item_rates` (one rate per machine per version), `costing_positions.machine_id` (nullable FK). Guarded (skips what exists). See "MachineDB machines in the cost sheet". | No (schema only; filled by the sync) | Drops both tables and the column: per-machine rates and machine choices on lines lost; lines fall back to class pricing. |
| 106 | Two currencies per plant. `plants.local_currency` (nullable), `cost_sheet_versions.fx_rates` (JSON, e.g. `{"USD/MXN": "17.30"}` = 1 USD is 17.30 MXN, frozen on publish), `entered_rate` / `entered_currency` on `cost_sheet_rates` and `cost_sheet_machine_rates` (a rate typed in the local currency). DATA CHANGE: a plant named, coded or located Silao (code `SIL`) without a local currency gets quote currency `USD` and local currency `MXN`, once; the EMPTY rows of an open draft at Silao follow it to `USD`. Published versions keep their rows and currencies (frozen); rows with a rate are not relabelled. Pending the Silao currency decision (Finance to-do 4). | Yes (UPDATE plants for Silao; UPDATE empty draft rows) | Drops the columns (exchange rates and typed local numbers lost). Silao's quote currency stays `USD`. |
| 107 | `cost_sheet_machine_item_rates.entered_rate` / `entered_currency` (nullable): a per-machine rate typed in the plant's local currency (Silao: MXN), like 106 did for the rate and machine class rows. Guarded. | No (schema only) | Drops the two columns: typed local numbers lost, the rates in the quote currency stay. |

Summary: nothing drops or rewrites existing business data except 093
(origin backfill), 094 (plant currencies, cost sheet rebuild), 095
(settled_as backfill), 099 (costing position cleanup), 101 (Toccoa
currency, duplicate standing effort rows merged), 103 (untouched D1
gates read undecided), 104 (duplicate department rates merged, empty draft
rows) and 106 (Silao quote currency `USD`, local `MXN`). A downgrade is
lossy for everything created after deploy; the real rollback is the backup.

## Environment

The prod backend is defined in the PARENT compose file
`/data/compose/docker-compose.yml`, block `plm2-backend`, NOT in the repo's
`docker/docker-compose.prod.yml`. The repo file passes the `KTX_COMPANY_*`
variables and `PLM_BUSINESS_TZ`, but NOT `PLM_RELEASE_ROWS_SINCE`
(DECISION for the owner: add `PLM_RELEASE_ROWS_SINCE:
${PLM_RELEASE_ROWS_SINCE:-}` to the repo file too, or leave it prod-only).
Prod only sees any of them if they are added to the prod block. All are
optional: unset or empty keeps the default.

| Variable | Default (backend/app/services/company_profile.py, app/utils/clock.py) | Recommendation |
|---|---|---|
| `KTX_COMPANY_LEGAL_NAME` | `KTX Group US Corp.` | keep default |
| `KTX_COMPANY_ADDRESS` | `325 Hammerstone Drive|Toccoa, GA 30577|United States of America` | keep default |
| `KTX_COMPANY_PHONE` | `+1 706 963 1110` | keep default |
| `KTX_COMPANY_FAX` | `+1 706 963 1052` | keep default |
| `KTX_COMPANY_EMAIL` | `ktx_info@us.ktx.group` | keep default |
| `KTX_COMPANY_WEBSITE` | `ktx.group` | keep default |
| `KTX_COMPANY_FOOTER` | `IATF 16949:2016 certified site|A company of the KTX Group` | keep default |
| `KTX_COMPANY_SIGNATURE_NAME` | empty | not needed, leave unset: Sales signs (rule below). Set only to force one fixed name on every offer; it overrides the person |
| `KTX_COMPANY_SIGNATURE_TITLE` | `Sales` | not needed, leave unset (set only to force one fixed title; otherwise the person's own title, else `Sales`) |
| `PLM_BUSINESS_TZ` | `America/New_York` (IANA name; drives the business date of deadlines, plan dates, offers) | set explicitly to `America/New_York` |
| `PLM_RELEASE_ROWS_SINCE` | `2026-09-26T04:00:00Z` (midnight New York on 26 Sep; backend/app/services/release_checklist.py) | set to the deploy moment in UTC (ISO 8601, e.g. `2026-09-27T14:30:00Z`; no offset means UTC). Changes that ended before it (released, or rejected / cancelled) keep their old 13-row checklist and wording; every other change gets the reworked 16-row one |

Offer signature rule (code, not configuration): on send the sender is
frozen into the sent version as signer when they are a member of Sales;
otherwise (PM lead, admin) the project's Sales responsible (project team),
else the "Sales" role line with no name. A draft previews exactly that for
the viewer, labelled "Signed by (preview)". Offer PDF dates read "26 Sep
2026" for every customer; amounts still follow the offer currency.

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

The release checklist is reworked, 13 to 16 rows (decision 2026-09-26,
corrected the same day: APQP confirms SPC, the cycle time comes from the
Tool Engineer):

- Tool Engineer: "Cycle time: changed (new value entered) or confirmed
  unchanged" (replaces the Manufacturing Engineer's "Cycle time confirmed
  in series production"; "changed" needs the new seconds; the row shows
  the Tool Engineer's cycle time measured in validation), next to "Tool
  and equipment data updated" and "Part weight measured and recorded".
- APQP: "Process stable: SPC Cm > 1.67" (one row, APQP alone; Cm optional,
  above 1.67), "Surface quality confirmed", "Technical quality confirmed",
  "Measurements confirmed, measurement report on file" (relabelled),
  "PPAP / initial sample documentation complete, customer approval
  received (ISIR / PSW)" (PPAP asked once) and "Control plan / inspection
  plan updated".
- Unchanged: Development (index / revision level, drawing and 3D data
  released, spare and service parts), Packaging Engineer (packaging
  instruction), Scheduling (ERP / BOM / routing, old stock), Sales
  (customer informed). The 16 rows: Development 3, Tool Engineer 3, APQP 6,
  Packaging Engineer 1, Scheduling 2, Sales 1
  (`backend/app/services/release_checklist.py`, `RELEASE_CHECKS`).
- Process Engineer: no release row (the process details stay in the
  process database, PDB, where the Process Engineer confirms them).
- Quality: no release row.
- Retired: "PFMEA, control plan and work instructions updated" (APQP) and
  "Cycle time confirmed in series production" (Manufacturing Engineer). An
  answer given to a retired row stays on the change, shown read-only as "No
  longer asked" and not counted. Same for answers to the Process Engineer
  rows of the first version of this rework ("Cycle time ..." and "Process
  stable: SPC Cm > 1.67 (Process Engineer)"), should any exist on a test or
  staging database; a change that was released there with them keeps them
  and gains no Tool Engineer cycle-time row.

Validation (stage 9): "Measured cycle time" is now measured by the Tool
Engineer only (before: Tool Engineer, Manufacturing Engineer and Process
Engineer each). A cycle time Manufacturing or Process Engineer already
recorded stays readable, marked "No longer asked", and no longer blocks the
release; an open validation issue linked to such a check can be closed by
PM, the lead or an admin with a note.

Every change not yet ended at the deploy moment (in validation or earlier)
gets the five new rows open and cannot be released until they are answered
done, or n/a with a note (PM, the change lead or an admin may also answer).
Changes that ended before `PLM_RELEASE_ROWS_SINCE` (released, rejected or
cancelled) are left as they were, retired rows and old wording included.
Tell APQP and Tool Engineer (step 7) and the leads of changes in
validation. No migration: the cycle time and the optional Cm are rounded
(seconds to 1 decimal, Cm to 2) and written into the row's note ("Changed:
new cycle time 38.5 s", "Cm 1.85") and into the changelog as data.

Future, not built: process engineering tasks will later be forwarded from
the PDB to PLM.

## MachineDB machines in the cost sheet (migration 105)

**DECISION / INFRA item for the owner.** The cost sheet's Machines tab lists
the presses from MachineDB and each can carry its own hourly rate per
version; a costing line (machine time, sampling) that names a machine is
priced on that rate, else on the class rate of the machine's plant.
plm2 reads MachineDB through a sync (`POST /api/v1/cost-sheet/machines/sync`,
button "Sync from MachineDB" for Sales, Finance, admins) into its own table
`cost_sheet_machines`; costing only reads that copy. Without a MachineDB
connection nothing breaks: the sync button is disabled with "Sync is off",
the tab shows the last synced copy (empty before the first sync), and
costing keeps pricing on class rates.

Environment of `plm2-backend` (all optional; unset = sync off):

| Variable | Value | Note |
|---|---|---|
| `MACHINEDB_API_URL` | `http://<machinedb host>:3001/v1` | the service API (`/v1`), NOT the MachineDB web UI; nginx does not expose `/v1` |
| `MACHINEDB_SERVICE_TOKEN` | MachineDB's service token (the one TWOS and RFQ2 use) | secret: compose `.env`, never in git; never logged |
| `MACHINEDB_TIMEOUT_S` | `10` (default) | request timeout |
| `MACHINEDB_SYNC_ON_STARTUP` | `1` (default) | a background sync at backend start when configured; `0` turns it off. It only syncs organisations with the org setting `machinedb_enabled` = `true`, or, when no organisation has that setting, the single organisation with plants (a multi-org install syncs nothing until one is switched on). It never forces (see the guard below). |

**The token travels in a header on every sync: never send it over plain
http across a network.** Use one of:

- the docker-internal network, when plm2 and MachineDB share a compose
  project or an attached network (`http://machinedb-backend:3001/v1`: the
  traffic never leaves the host); or
- https: a TLS-terminating reverse-proxy route on the MachineDB host that
  forwards `/v1` to port 3001 (`MACHINEDB_API_URL=https://<machinedb host>/v1`).

A published `http://<host>:3001/v1` between two hosts is a fallback only
for a short test, firewalled to the plm2 host, with the token rotated
afterwards.

Network route (the infra part): on prod, plm2 and MachineDB run on
DIFFERENT hosts. MachineDB is on `10.105.205.55` (MIGRATION-PLAN.md). The
plm2 host must reach MachineDB's `/v1` there. Recommended: an https route
on the MachineDB host (reverse proxy with TLS, forwarding `/v1` with the
bearer header to port 3001), `MACHINEDB_API_URL=https://<machinedb host>/v1`.
Plain `http://10.105.205.55:3001/v1` sends the token readable on the LAN:
only as a firewalled stopgap (see above). Check from the plm2 host before
the go:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $MACHINEDB_SERVICE_TOKEN" \
  https://<machinedb host>/v1/machines     # 200 = reachable and token accepted
```

Locally (dev compose) the route is the docker network: `http://machinedb-backend:3001/v1`
with `${MACHINEDB_SERVICE_TOKEN}`, as TWOS uses it. The ecr dev container
(`plm2-ecr-backend`) does not have these variables yet.

First sync, after the recreate (step 4) and the smoke checks:

1. Open Cost sheet > Machines as Sales, Finance or an admin, click "Sync from
   MachineDB" (or wait for the startup sync) and read the report: new,
   changed, retired or scrapped, and machines without a plant.
2. Plant mapping: MachineDB `usa` maps to the plant named Toccoa / USA,
   `mexico` to Silao Mexico, `weissenburg` to Weissenburg (by name, only when
   exactly one plant matches). `solingen` and `serbia` stay unmapped until
   someone maps them on the tab (org setting `machinedb_plant_map`); nothing
   is guessed. The tab's "Plant mapping" lists every MachineDB plant in use
   with its plm2 plant and why (by plant name, mapped by hand, kept
   unmapped by hand). Saving sends only the plants changed and is merged
   into the stored mapping; "Use default" drops one hand mapping.
3. Finance enters per-machine rates in the next draft only where a machine
   differs from its class; the class rates stay the fallback. A rate
   defaults to the currency of the machine's plant; an unmapped machine
   needs its currency chosen. At a two-currency plant (Silao) the rate can
   be typed in the local currency (Local / h, migration 107); the other one
   is calculated at the version's exchange rate, like the rates tab. The
   XLSX export has a "Machine rates" sheet (CSV: `section=MachineRates`).

Currency in costing: a machine's own rate, or the class rate at the
machine's plant, in another currency than the costing plant is converted
at the version's exchange rate and the rate label says so ("converted from
100.00 EUR at ..."); without that exchange rate the line shows "No rate"
(machine rate in other currency) and the P&L flags the change as not fully
priced. Nothing is added across currencies.

Sync guard: a MachineDB answer that looks broken is refused (409) and
recorded as the last sync attempt, the local copy untouched: an empty list
while machines are on record, more than half of the rows unreadable, or
more than half of the machines on record retired at once. The tab then
offers "Sync anyway" to Sales, Finance and admins (a forced sync,
`POST .../sync?force=true`); the startup sync never forces. A manual sync
only ever touches the caller's organisation. Two syncs (or two saves of
the same machine rate) at the same time: the second gets 409 and keeps
nothing.

Local dry run (2026-09-26, rolled back): 53 machines (usa 26, mexico 27),
all mapped, a second sync reports nothing new or changed.

## Preflight (local, before the go)

1. Branch merged to main on the owner's go (no merge is part of this
   document). Check the tree is complete: `alembic heads` shows one head,
   `107`.
2. Full suites on a clean checkout of the merge commit: backend
   `python -m pytest -q` (xdist), frontend `npx vitest run`, `npx tsc
   --noEmit`. Record the counts in the deploy log.
3. Prefill script test: `python -m pytest tests/test_prefill_project_team.py
   -n 0 -q` (11 tests).
4. Routing sweep test: `python -m pytest tests/test_change_routing.py -n 2 -q
   -k "sweep or backfill"` (dry run writes nothing, `--apply` is idempotent,
   snapshot backfill). The sweep itself runs on prod in step 5a.
5. Migration tests on SQLite: `python -m pytest
   tests/test_migration_101_sqlite.py tests/test_migration_102_sqlite.py
   tests/test_migration_103_sqlite.py tests/test_migration_104_sqlite.py
   tests/test_migration_105_sqlite.py tests/test_migration_106_sqlite.py
   tests/test_migration_107_sqlite.py -n 2 -q`.

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
# pricing date: the first cost sheet version starts at the earliest department rate
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select min(effective_from) from department_rate;"
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select count(*) from change_requests where created_at < (select min(effective_from) from department_rate);"
```

What to look for:

- Plants: 094 sets USD only when location, name or code contains the word
  `US` / `USA` or `UNITED STATES`, so a Toccoa row that reads e.g.
  `Toccoa, GA` would become EUR. Migration 101 then sets it to USD when
  `toccoa` is a whole word of the plant's name or location (the code is
  not matched). Check here that the Toccoa row's name or location contains
  `Toccoa`. Verify after the migration (step 3 on `plm_scratch`, step 4 on
  prod) with `select id, name, code, location, currency from plants order
  by id;`: Toccoa must read `USD`. If it does not, stop and check that 101
  is in the build and what the row's name and location read (rates keep
  their numbers either way; nothing is converted).
  Silao (Mexico): 094 sets it by location; 106 then sets quote currency
  `USD` and local currency `MXN`. This is pending the Silao currency
  decision (Finance to-do 4): no rate is relabelled.
- Pricing date: a change is priced with the version valid on its creation
  date. Note `min(effective_from)` (the first version's valid-from, 2020-01-01
  when no rate is dated) and how many changes were created before it: they
  are priced with that first version, and each line says "priced with v1,
  the earliest cost sheet".
- Department rates: note which departments have a Toccoa rate. There is no
  Project Manager rate today (see the Finance to-do).
- Departments: `Project Manager`, `Manufacturing Engineer`, `Tool Engineer`,
  `APQP`, `Development` must exist and be active for the team prefill.
  `Finance` is created by 092 if missing.
- Also note `select count(*) from change_gate where decision = 'na' and
  decided_by is null and decided_at is null;` (the rows 103 turns undecided)
  and `select count(*) from costing_positions where kind in
  ('internal_effort', 'support_effort');` (101 may merge duplicates, so this
  count can drop by the duplicates merged).
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

Then on `plm_scratch`: `alembic_version` = `107`, the counts from
step 0 unchanged (except the two counts 101 and 103 touch, noted above), `select id, name, currency from plants;` with Toccoa `USD`,
`select organization_id, version, status, valid_from, note from
cost_sheet_versions order by 1, 2;` shows a published chain,
`select count(*) from cost_sheet_rates;` greater than 0. Run the prefill dry
run against the scratch DB too (step 6 with `-e
DATABASE_URL=...plm_scratch` via `docker run`). Drop `plm_scratch` after.

If the upgrade takes longer than about 20 seconds, do NOT rely on the startup
migration (next step explains why).

### 4. Migrate, then recreate

`app/main.py` runs `alembic upgrade head` at startup with a 30 second
timeout, in every uvicorn worker. Twenty-one migrations (087..107) with the 094 data
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
docker compose run --rm --no-deps plm2-backend alembic current     # must show 107 (head)
docker exec compose-plm2-db-1 psql -U plm -d plm -c "select id, name, code, location, currency from plants order by id;"   # Toccoa = USD
```

Do not run `alembic upgrade head` unless `BACKUP OK` was printed and the
dump is not empty. Note the backup file name in the deploy log.

Add the environment lines (section Environment) to the `plm2-backend` block
now, then:

```bash
docker compose up -d plm2-backend plm2-frontend
docker exec compose-plm2-backend-1 alembic current                 # again: 107
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
- Offer PDF from the offer card: letterhead shows KTX Group US Corp., Toccoa address. Dates read like "26 Sep 2026" on one line in the header (every customer); amounts in the offer currency. A sent version is signed by the Sales member who sent it (sent by a PM lead or an admin: the project's Sales responsible, else the "Sales" line with no name). A draft shows "Signed by (preview)" with who would sign if you sent it now: you when you are in Sales, otherwise the project's Sales responsible, else the "Sales" line.
- D1 of an open change nobody has decided: the gates read undecided (not "n/a"), and the release still waits for a `yes`.
- Timing tab of a change with a validated plan and open deviations: one decision per group (the moved block with what it pushed).
- Actual costs of a change in implementation: each row shows its currency (the costing plant's; Toccoa `USD`).
- Start change: the KTX Weissenburg / Solingen origin is offered only to a Project Manager (and admin); such a change goes from scoping (who is informed, no cost carrier) straight to informing the team, the PM writes the description.
- Implementation tab, a revision with a check workflow on a 3D-evidence step: Approve is held with "3D evidence" as the reason until a CAD file is uploaded or "no geometry change" is signed, then enabled without a page reload.
- Release tab of a change in validation: 16 rows, Tool Engineer (3) and APQP (6) groups as listed above, no Process Engineer, Quality or Manufacturing Engineer group. A change released before the deploy: 13 rows, with "Cycle time confirmed in series production", "PFMEA, control plan and work instructions updated", "Parts measured, measurement report on file" and "Customer approval received (PPAP / ISIR / PSW)".
- Validation block of a change in validation: "Measured cycle time" only under Tool Engineer.
- `/plm2/cost-sheet`: published version chain, Toccoa rows in USD, one draft at most.
- `/plm2/pnl` and `/plm2/reports`: cost report per currency.
- `/plm2/my-tasks`: counts plausible, backup markers after the prefill.
- `/plm2/projects/35` (1994): Project team card.
- `/plm2/training`, `/plm2/training/handout/<role>`: roster loads, gate reads off.
- `/plm2/process-map`, `/plm2/projects`, `/plm2/parts/<id>`, `/plm2/lessons`: unchanged pages still load.

Counts from step 0 identical; `docker logs compose-plm2-backend-1 --since
10m | grep -c " 500 "` = 0; container restarts = 0.

### 5a. Scripts after the migration, in this order, dry run first

1. `scripts/repair_routing_tasks.py` (below): routing tasks and snapshot
   backfill. Required.
2. `scripts/prefill_project_team.py` (step 6). Required (owner decision
   2026-09-25).
3. `scripts/repair_final_walk.py`: NOT part of the prod run by default. It
   repaired the dev database after the final walk (2026-09-25). It has NO
   dry run (it commits directly) and runs as the first admin user. Its
   three steps against prod: (1) routing tasks, fully covered by
   `repair_routing_tasks.py`; (2) closes the workflows still open on
   released or closed changes (`close_engine_work`: check flows canceled,
   the change flow completed, open tasks waived); (3) title and lead of
   escalated engineering reviews, which prod cannot have (reviews arrive
   with this deploy). DECISION for the owner: step (2) may apply to prod
   changes released on the old code with a workflow still open. Check
   first, read-only: `select cr.change_number, cr.status, wi.id, wi.status
   from change_requests cr join wf_instances wi on wi.change_id = cr.id
   where cr.status in ('released', 'closed') and wi.status = 'active';`.
   Zero rows: skip the script. Otherwise run it once after a fresh backup,
   on the owner's word, and keep its output in the deploy log.

#### Routing task sweep

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

The same run backfills the routing snapshot: a department added by a
routing deviation approved before approvals wrote their adds into the
snapshot gets its entry (`added_by_deviation`), replayed from the changelog
of the current routing. A change whose deviation is still pending is listed
`SKIPPED, deviation pending`: run the sweep again after that decision.

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
- APQP and Tool Engineer: changes in validation now carry the reworked
  release rows (Tool Engineer: cycle time changed or unchanged, next to
  tool data and part weight; APQP: process stable SPC Cm > 1.67, surface
  quality, technical quality, measurements, PPAP with customer approval,
  control plan) to answer done or mark n/a with a note before the change
  can be released. The Tool Engineer alone measures the cycle time in
  validation. Process Engineer, Quality and Manufacturing Engineer no
  longer own release rows.

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
3. Toccoa plant currency: migration 101 sets it to USD explicitly,
   because 094's `US` / `USA` word match may miss `Toccoa, GA`. Confirm
   with the plants query (step 4) that Toccoa reads `USD`.
4. Silao (Mexico) currency: pending the Silao currency decision. 106 set
   Silao to quote `USD` and local `MXN`; published rows keep the currency
   they were typed in and nothing is relabelled. A draft flags every row
   whose currency is not its plant's quote currency (warning in the draft
   and in the publish dialog); typing an MXN rate on such a row asks to
   switch the row to the quote currency first. Old costing lines without a
   recorded currency are read in the costing plant's currency and flagged
   ("no recorded currency"), never silently.
5. Publish version 2 (backdated if needed). The migrated version 1 holds
   only what `department_rate` had. Put the missing department rates (and
   machine class and sampling rates) into a new draft and publish it with
   the valid-from they apply from; a valid-from in the past needs the
   backdated confirmation. How it prices old changes (gap fill): a change
   keeps the rates of its creation date. Where the version valid on that
   date has NO rate (no row, or an empty one) for a department, machine
   class or sampling at the plant, the earliest LATER published version
   that has one prices it, and the line says so ("no rate in v1 on the
   creation date; taken from v2 valid from 26 Sep 2026"). A rate that
   existed on the creation date is never replaced by a later version: a v2
   that changes a v1 rate does not move changes created under v1. Lines
   record the version actually used.
6. Actual costs: 101 gave every existing row the costing plant's currency.
   Prod has none before the deploy (the table arrives with 091), so this
   only matters for rows entered on a staging copy.

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
  UPDATE prints. Also for 103: the old code's gate response requires a
  decision string (`GateResponse.decision: str`), so an undecided gate
  (NULL) would make `/changes/<id>/gates` fail with 500. Set them back
  first (the old code inserts new gates with the ORM default `na`, so the
  nullable column itself is harmless):

  ```bash
  docker exec compose-plm2-db-1 psql -v ON_ERROR_STOP=1 -U plm -d plm \
    -c "UPDATE change_gate SET decision = 'na' WHERE decision IS NULL;"
  ```

  101 and 102 need nothing for a code-only rollback: the old code does not
  know `change_actual_costs` or the plan deviation tables at all, and the
  Toccoa `USD` label is not read by it. One side effect of 101: the partial
  unique index `uq_costing_positions_standing` stays, so a double save of a
  standing effort row on the old code fails with an error instead of
  writing a duplicate (the duplicate was the bug; leave the index).

  Then `cd /data/compose/plm2 && git checkout f4b354e5`, `docker compose
  up -d --build plm2-backend plm2-frontend`, nginx reload.
  Every other column 087..107 added to an existing table is nullable or has
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
