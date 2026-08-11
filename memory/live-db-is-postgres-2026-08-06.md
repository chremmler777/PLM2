---
name: live-db-is-postgres-2026-08-06
description: The running app uses Postgres in Docker, not backend/plm.db — and main.py auto-runs alembic on every reload, so draft migration files get applied within seconds
metadata:
  type: project
---

**The running app does not use `backend/plm.db`.** That SQLite file is what the
test suite and host-side `alembic` commands touch. The live app is
`claude-plm2-backend-1`, bind-mounting `/home/nitrolinux/claude/plm2/backend`
to `/app`, talking to Postgres in `claude-plm2-db-1`
(`postgresql+asyncpg://plm@plm2-db:5432/plm`).

Consequences, both of which cost time on 2026-08-06:

1. **`alembic upgrade head` from the host migrates SQLite only.** Postgres is
   migrated separately — see below. Verifying a migration against `plm.db`
   proves nothing about what the UI sees.

2. **`app/main.py:~406` runs `alembic upgrade head` on startup when the DB is
   Postgres, and the container runs uvicorn `--reload`.** So *every file save*
   restarts the app and applies whatever migrations exist at that instant. A
   migration file that exists for even a minute gets applied to Postgres. If it
   is then deleted, Postgres keeps the column and the version stamp, the
   defining migration no longer exists, and the next real migration with the
   same revision id never runs — the app then 500s on
   `UndefinedColumnError` for the columns it expects.

   Recovery: drop the orphaned column, roll `alembic_version` back one
   revision, restart the container so startup applies the correct migration.
   Take a `pg_dump -Fc` first.

**Never leave a draft migration file on disk.** Write it only when the design
is settled, because the file *is* the deployment.

3. **Migrations must be dialect-neutral (2026-08-11: 041 took the backend
   down).** Boolean columns are INTEGER on SQLite but real BOOLEAN on Postgres,
   so raw SQL like `SET can_start_change = 0` passes the whole SQLite test
   suite and then fails live with `operator does not exist: boolean <>
   integer`. Use SQLAlchemy Core (`sa.table/sa.column` + `sa.true()/sa.false()`)
   instead of `sa.text()` for data updates. Also: uvicorn's hot reload swaps in
   new ORM code but only a *startup* applies migrations — model and DB can
   drift for minutes, 500ing every query on the touched table. After adding a
   migration, apply it explicitly: `docker exec claude-plm2-backend-1 alembic
   upgrade head`.

Auth note: local login is disabled (`410 "Local login is disabled;
authenticate via the AdminPanel hub"`), so the API cannot be smoke-tested with
curl. Verify through the ORM inside the container instead.
