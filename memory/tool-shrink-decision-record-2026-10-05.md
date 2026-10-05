---
name: tool-shrink-decision-record-2026-10-05
description: Tool shrinkage provenance - PLM2 decision record per tool (source + reason, verify after trial) reported back to MaterialDB shrink_experiences; DEPLOYED 2026-10-05 (plm2 5c9e93d5 / 112, MaterialDB 5ece7f5)
metadata:
  type: project
---

2026-10-05 user: shrinkage values (e.g. Hostacom: supplier opinion is main, M. Rautzenberg adds tooling info) must say
where they came from so we can choose; build the tools, then revisit whether the decision was right and what to
correct for the future. User approved the design.

Deployed 2026-10-05 13:51 (user: "commit and push to prod, same for material db"): MaterialDB 5ece7f5,
alembic c3e4f5a6b7d8 (backup db-backups/materialdb-before-shrink-experiences-20261005-125926.sql.gz); plm2 5c9e93d5,
alembic 112 (backup plm2-before-112-20261005-135133.sql.gz). Tests: plm2 backend 2094 passed, frontend 2936; MaterialDB 46.
Prod MaterialDB pull: server ssh config forces the github_deploy key, so pull with
`ssh -A` + `GIT_SSH_COMMAND="ssh -F /dev/null -o UserKnownHostsFile=~/.ssh/known_hosts"`.
Smoke: tool 227702 (2277) shows the LyondellBasell supplier value 0.8/1.1 for 40-0223.

Built:
- PLM2: table tool_shrink_decisions (migration 112, revises 111), service app/services/tool_shrink_service.py,
  API /v1/parts/{id}/shrinkage (+ /decisions, /verify, /report), card components/tools/ToolShrinkCard.tsx on the
  tool page and project Tool tab. Shrinkage no longer edited in ToolFieldsCard; values change only via a decision
  (tool fields follow, logged as field_updated + shrink_decided/shrink_verified). Worksheet "Edit" jumps to the card.
- MaterialDB: table shrink_experiences (alembic c3e4f5a6b7d8), service GET /v1/materials/by-id/{id} and
  PUT /v1/shrink-experiences/plm/{plm_record_id} (upsert), material page tab "Tool shrinkage".
- Candidates: property with a TDS source = datasheet, other source document (mail) = supplier, shrink_experiences =
  KTX tool experience.

**Why:** decisions get checked against the measured parts (L09 in [[project-timing-blocks-2026-10-02]]) and
the next tool with the same material learns from it.

**How to apply:** local plm2 has no MATERIALDB_BASE_URL, so candidates only show on prod. Open: seed the
3127/3128 Rautzenberg note as a shrink_experience; MaterialDB test_materials list-shape test was stale (fixed).
Related: [[tool-shrinkage-rule]].

Later 2026-10-05: worksheet "Chosen shrink combined / parallel / normal" sit next to the datasheet shrink (title = decision
source); tool card shows the chosen value next to cycle time plus "MaterialDB" reference. Combined is its own field
(parts.tool_shrink_combined_pct, migration 113, deployed 16:58, backup plm2-before-113-20261005-165752.sql.gz):
EITHER combined OR parallel + normal, chosen per tool on the Shrinkage card. User: "combined is a choice, need to be
able to either force normal and parallel or combined" - never derive combined from equal values (113 moves no data;
199407/199409/227704 still 0.9/0.65/1.25 as parallel = normal until someone chooses).

2026-10-05 20:38: all ten 1994 tools got a shrinkage decision on prod from the user's filled "1994 BOM - material and
shrinkage.xlsx" (Desktop): Hostacom 199402/04/05/06/08/10 0.8/1.1 split (supplier), EPLAMID 199401/03 0.7/1.0 (datasheet),
Bayblend 199409 0.65 combined (ktx_experience), Romiloy 199407 0.9 combined (datasheet). Script
backend/scripts/record_1994_shrinkage_decisions.py (673c2765), backup plm2-before-1994-shrink-decisions-20261005-203815.sql.gz.
Not yet done: the tool rights (Tool Engineer or admin) + DFM delete with reason work is uncommitted in the tree
(backend full suite not finished; tests outside DFM may need the tool_engineer fixture).

2026-10-05 21:27 DEPLOYED 5a804043 (no migration, backup plm2-before-5a804043-*.sql.gz): tool rights (Tool Engineer or
admin via app/services/tool_rights.py; all editors are plm2_Admin today, user: "Dale will be tooling eng in the future
but now he keeps admin"), DFM delete with reason (soft), and shrinkage decisions reported to MaterialDB at decision time
(one entry per tool, keyed by PLM tool id). Backfill: the 10 1994 decisions are on MaterialDB as "decided, not verified yet".
