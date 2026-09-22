---
name: prod-data-is-truth
description: Prod PLM2 database is the source of truth for data; data operations (wipes, attaches, renames, migrations) run on prod, never pushed from local
metadata:
  type: feedback
---

For data actions (file wipes, customer data attach, renumbering, imports,
nominations), prod (`ktx-server`, compose-plm2-*) is always the truth. Local
Postgres is a dev copy and must never be pushed to prod, and local state is
never the basis for deciding what prod should look like.

**Why:** user 2026-09-22: "prod is always truth, never pull local for those
actions". Prod already holds changes local lacks (see [[brose-award-import-2026-09-02]]).

**How to apply:** read prod first (`source ~/.ssh/agent.env`, ssh, `docker exec
compose-plm2-db-1 psql`), dry-run scripts on prod against prod data, take a
`db-backups/` dump before any write, and only then `--apply` on prod. Local
runs are for testing the script's code path, not for deciding prod data.
See [[prod-ssh-fail2ban]] for the SSH procedure.
