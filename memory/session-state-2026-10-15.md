---
name: session-state-2026-10-15
description: End-of-day state 2026-10-15 (plm chat) - done/deployed, open branches, migration 115 clash with feature/ecr-solid, open decisions, next steps
metadata:
  type: project
---
**Done + deployed on prod today** (prod main = 0536924c, alembic 115):
- 1994 E1.1 drafts on 4 parts, FZ toolmaker data sent to Brose (Paluch), awaiting confirmation (rev ids 2248-2251). See [[1994-e11-fz-toolmaker-2026-10-15]].
- Part-data mail (KTX Apps via Graph, 5-min digest, 1994 list of 8), LIVE after a trial. See [[part-data-mail-2026-10-15]].
- Drawings/PDFs always open in a popup window (087d165c); Back from the project worksheet stays in the project (0536924c).

**WARNING: migration clash.** Prod alembic 115 = 115_part_data_mail. Branch feature/ecr-solid (worktree ~/claude/plm2-ecr-solid, ECR lead = other session) still has 115_change_scope_definition + 116..129 chained on it. It must be rebased on main and renumbered to 116..130 (first down_revision "115") before merging/deploying, or prod skips scope_definition. Its 120_notification_mailed_at may overlap part_data_mail. Owner "addi plm" session confirmed 2026-10-15: it renumbers 115..129 -> 116..130 at its rebase after its workflow ends and routes its notification mails through mail_outbox. Agreed: no new migrations on main without telling that session first. feature/ecr-live-test-1 already renumbered to 116 (ba6e1ec4); it is superseded by ecr-solid.

**Leftover worktrees** (merged, safe to remove): .claude/worktrees/agent-a15f592886bf6cac5 (drawing-popup), agent-afb59c9075b7b63c6 (part-data-mail, locked).

**Open decisions for Christoph:**
- Brose answer on the 4 E1.1: confirm -> "Customer adopted" (E2), reject -> close. The files sent to Brose carry outdated RFQ2 Scout numbers; he decides whether to send Brose a correction.
- Re-send the 4 E1.1 mail to the whole list? (The trial went to him only.)
- Backlog to design: DFM "Data exchange" log per part/topic; separate Moldflow tree (first case 1994 FZ V1 10/13: 206.885.219/199405, 206.881.479/199408, 206.881.799/199410; review files in C:\Users\christoph.demmler\Downloads\1994_Moldflow_FZ_V1_2026-10-15\).
- Role-based mail recipients (later); FZ mold no. field on tools (mail lines show the KTX tool no. only).
- DFM PDFs in a popup no longer show their source line ("Answer #8 · KTX to Toolmaker").

**Gotchas:** prod revision-uploads is not writable over ssh, so stage via /tmp + docker cp and clean up with -u root. The SSH tripwire locks on any "Permission denied" in command output.
