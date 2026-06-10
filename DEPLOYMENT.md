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

### First-run checklist

1. Log in as `admin@example.com / admin1234` → change the password immediately.
2. Users page: create real accounts, assign roles and department memberships.
3. Workflows page: review the workflow templates (departments → stages → RASIC).
4. Suppliers page: vendor master data (free-text supplier names were migrated
   automatically).
