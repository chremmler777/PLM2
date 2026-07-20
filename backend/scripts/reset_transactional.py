"""Reset transactional test data on the live PLM Postgres (SP-A).

Wipes the throwaway seed data — project 1 "Test Project" and project 2
"VW426 Atlas" (the TWOS-seeded copy, re-imported from WinCarat later) —
together with EVERYTHING that references those projects: change requests
and their whole dependent closure, parts/revisions/BOM/relations, SEP
work items, lessons learned, PPAP, workflow instances, etc. Preserves
org, plants, users, suppliers, catalog, and all workflow *configuration*
(wf_steps, wf_departments).

Approach: this is a pre-import, one-time reset. Rather than hand-order a
33-table foreign-key closure, the script

  1. GUARDS that the only projects present are a subset of {1, 2}. If any
     other project exists (e.g. after the WinCarat import has run) it
     refuses to run — so it can never nuke real imported data.
  2. Computes the full FK descendant closure of `projects` from
     information_schema (so schema growth is covered automatically).
  3. Inside one transaction, disables FK triggers
     (session_replication_role = replica), deletes every row from each
     closure table, and restores the role. Because the guard proves the
     DB contains nothing but projects 1 & 2, "all rows" is exactly the
     seed data.

Dry-run by default (row-count report, no writes). Pass --yes to delete.
Idempotent: after a successful wipe a re-run reports zeros.

Run inside the PLM backend container (has DATABASE_URL + asyncpg):
    docker exec claude-plm2-backend-1 python scripts/reset_transactional.py
    docker exec claude-plm2-backend-1 python scripts/reset_transactional.py --yes
"""
import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

SEED_PROJECT_IDS = (1, 2)
PRESERVED = ("organizations", "plants", "users", "suppliers", "wf_steps", "wf_departments")

_CLOSURE_SQL = text("""
WITH RECURSIVE fk AS (
  SELECT tc.table_name::text AS child, ccu.table_name::text AS parent
  FROM information_schema.table_constraints tc
  JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name=ccu.constraint_name
  WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_name <> ccu.table_name
),
closure AS (
  SELECT 'projects'::text COLLATE "C" AS tbl
  UNION
  SELECT (fk.child COLLATE "C") FROM fk JOIN closure c ON fk.parent=c.tbl
)
SELECT tbl FROM closure ORDER BY tbl
""")


async def guard(conn) -> None:
    others = (await conn.execute(text(
        "SELECT count(*) FROM projects WHERE id <> ALL(:ids)"),
        {"ids": list(SEED_PROJECT_IDS)})).scalar_one()
    if others:
        sys.exit(f"ABORT: {others} project(s) exist outside {SEED_PROJECT_IDS}. "
                 "This reset only runs against the pre-import seed DB (projects 1 & 2 only).")


async def closure_tables(conn) -> list[str]:
    rows = (await conn.execute(_CLOSURE_SQL)).scalars().all()
    # 'projects' is the root; delete it last conceptually, but with FK
    # triggers disabled order is irrelevant, so a flat set is fine.
    return list(rows)


async def report(conn, tables: list[str]) -> int:
    total = 0
    for t in tables:
        n = (await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
        if n:
            print(f"  {t:32} {n}")
        total += n
    print(f"  {'TOTAL':32} {total}")
    return total


async def main() -> None:
    do_it = "--yes" in sys.argv
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not set — run inside the PLM backend container.")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await guard(conn)
        tables = await closure_tables(conn)
        print(f"{'DELETE' if do_it else 'DRY-RUN'} — closure of projects ({len(tables)} tables), rows targeted:")
        await report(conn, tables)
        if do_it:
            await conn.execute(text("SET session_replication_role = replica"))
            for t in tables:
                await conn.execute(text(f"DELETE FROM {t}"))
            await conn.execute(text("SET session_replication_role = DEFAULT"))
            print("Committed deletes.")
        else:
            print("No changes written. Re-run with --yes to delete.")
    async with engine.connect() as conn:
        print("Preserved tables (post-run counts):")
        for t in PRESERVED:
            n = (await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
            print(f"  {t:16} {n}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
