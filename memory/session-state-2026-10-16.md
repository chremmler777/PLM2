---
name: session-state-2026-10-16
description: 2026-10-16 plm chat - header back fix deployed f27f9b23; Moldflow timing overview in build (migration 116, ECR chat must renumber to 117+)
metadata:
  type: project
---
- Deployed f27f9b23 (frontend): project header ← is "← Items" in the worksheet, "← Projects" on the list; part page back goes to its project (?part=).
- Moldflow timing overview approved by Christoph (via Asss 2 request): per-tool table tool_moldflow (migration **116_tool_moldflow**, down 115), worksheet "Moldflow" group + status-nav panel, seed scripts/seed_1994_moldflow.py from mail facts (dry run to Christoph before prod). Branch feature/moldflow-overview (builder running). Full findings tree later on the same records.
- **ECR branch (feature/ecr-solid, "addi plm" session) must renumber to 117..131**, not 116..130. The heads-up could not be delivered (session unreachable 2026-10-16); tell it when it is back.
Related: [[session-state-2026-10-15]], [[part-data-mail-2026-10-15]].
