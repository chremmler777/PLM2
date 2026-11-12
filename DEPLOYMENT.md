# PLM2 — Deployment

## Development (current workflow)

```bash
./run_backend.sh                 # API on :8000 (SQLite, hot reload)
cd frontend && npm run dev       # UI on :5174
```

Logins: `admin@example.com / admin1234` (admin), `test@example.com / password` (engineer).
Change both passwords after first login (sidebar → Change Password / Users page).

## Production (Docker)

```bash
cd docker
cp .env.example .env
openssl rand -hex 32             # → paste as SECRET_KEY in .env
# set POSTGRES_PASSWORD in .env; set CORS_ORIGINS to your public URL
docker compose -f docker-compose.prod.yml up -d --build
```

Then open `http://<host>` (port configurable via `HTTP_PORT`).

What the production stack does differently from dev:

| Concern | Dev | Production |
|---|---|---|
| Database | SQLite file | PostgreSQL 16 (named volume, internal network) |
| Migrations | run_backend.sh | backend runs `alembic upgrade head` on startup (non-SQLite) |
| Frontend | Vite dev server | static build served by nginx, `/api` proxied to backend |
| API base | `http://localhost:8000/api` | same-origin `/api` (baked via `VITE_API_URL`) |
| Backend | `--reload`, DEBUG=true | 2 uvicorn workers, DEBUG=false |
| Secrets | dev defaults | startup **refuses** the dev SECRET_KEY when DEBUG=false |
| Files | `backend/uploads/` | named volumes (`upload_data`, `gltf_data`, `upload_workdir`) |

### Operational notes

- **Backups:** volumes `postgres_data` (database) and `upload_data`/`upload_workdir`
  (CAD + documents) hold all state.
- **Uploads up to 100 MB** are allowed; nginx is configured with
  `client_max_body_size 120m` and a 300 s proxy timeout for STEP conversion.
- **STEP→glTF conversion** runs in an isolated subprocess inside the backend
  container (pythonocc-core comes from the conda base image); a malformed CAD
  file cannot crash the API.
- **Tests:** `cd backend && python -m pytest tests/ -q` (57 tests, isolated
  SQLite per test — safe to run anywhere).
- **SEP forms engine:** migration `065_sep_forms` creates the `form_definitions`,
  `form_instances` and `form_events` tables and seeds the definition rows
  itself. The legacy `sep_risks` → `risk_assessment` copy is not part of that
  migration (a second connection can't see its uncommitted DDL); it runs
  idempotently in the backend's `lifespan` at every startup, and also via
  `python backend/scripts/migrate_sep_risks.py` as a manual fallback if a
  stack is never restarted after the migration. New or updated form
  definitions are picked up the same way, at startup or via
  `python scripts/load_form_definitions.py`. `reportlab==4.2.5` (PDF export)
  is a new backend dependency, so the backend image must be rebuilt, not just
  restarted, when deploying this change.

- **Customer data index (migration 072):** revision names change from
  RFQ/ENG/IND/ECR to `E<n>` (customer review data) and `<n>` (customer
  official data); minors `.<m>` are internal proposals. The migration renames
  existing rows in place per part in creation order; ids are unchanged. After
  deploy, set the lifecycle phase of nominated parts by hand on the part page
  (admin: "Mark nominated"). No image rebuild needed; a restart applies the
  migration.

### Project LOP

The Project LOP is the open-points list of a project (tasks, SEP items the PM
picks, risk rows, PDB topics), with a daily digest, a weekly escalation summary
and meeting minutes. Migration `161_project_lop` adds the tables and the
`projects.lop_enabled` flag; a restart applies it.

Settings (env, defaults in `backend/app/core/config.py`):

| Env | Default | Meaning |
|---|---|---|
| `PDB_API_URL` | `http://pdb-backend:8000` | PDB backend, read only (live status and open topics) |
| `PDB_SERVICE_TOKEN` | empty | same secret as PDB's `PDB_PLM_READ_TOKEN`; empty = the PDB box says "not configured" |
| `LOP_MAIL_ENABLED` | `false` | while false, LOP digest, escalation summary and minutes are in-app badges only; PLM2's ECR mail is already live in production and is not affected |
| `LOP_ESCALATION_RECIPIENTS` | empty | usernames or e-mails, comma separated; intended: Cody and Christoph |
| `LOP_TIMEZONE` | `America/New_York` | time zone of the digest |
| `LOP_DIGEST_HOUR` | `7` | digest hour, Monday to Friday; digests (and Monday's escalation summary) are only created from this hour to two hours later, never during the rest of the day |
| `LOP_STALE_DAYS` | `14` | a line with no update for this long is stale |
| `LOP_DUE_SOON_DAYS` | `3` | "due soon" looks this many days ahead |
| `LOP_MEETING_GAP_DAYS` | `10` | open lines and no closed LOP meeting for longer escalate the PM |

- **Rollout:** the migration enables the LOP for project codes 1748, 1864, 1994
  and 2277; every project created afterwards through the API gets it too.
  Other existing projects need `projects.lop_enabled` set by hand. Seed scripts
  and imports that create projects directly do not set it.
- **PDB first:** deploy PDB first (or at the same time) so the PDB box works
  (PDB needs `PDB_PLM_READ_TOKEN`). If PDB is not deployed or not reachable,
  nothing breaks: the box says it is unavailable and the rest of the LOP works.
- **Mail needs BOTH switches:** LOP mail goes out only when `ECR_MAIL_ENABLED`
  is true (PLM2's notification mail loop, which sends every mail, ECR and LOP,
  runs only then and needs Microsoft Graph configured; it is already on in
  production) AND `LOP_MAIL_ENABLED` is true. With either one off, the LOP
  digest, escalation summary and minutes stay in-app badges.
- **Recommended first week:** leave `LOP_MAIL_ENABLED` off, let Christoph look
  at the badges, then turn it on. Optionally set `NOTIFY_TRIAL_RECIPIENT` to
  him first, but note that this existing switch diverts ALL PLM2 mail (ECR
  included), not only LOP mail.
- **Limit:** "one digest per person per day" is guaranteed for a single backend
  worker. With several workers, add a unique index on notifications
  (`user_id`, `kind`, `subject_key`) for the LOP kinds first.

### First-run checklist

1. Log in as `admin@example.com / admin1234` → change the password immediately.
2. Users page: create real accounts, assign roles and department memberships.
3. Workflows page: review the workflow templates (departments → stages → RASIC).
4. Suppliers page: vendor master data (free-text supplier names were migrated
   automatically).
