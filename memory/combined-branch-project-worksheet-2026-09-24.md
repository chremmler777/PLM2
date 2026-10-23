---
name: combined-branch-project-worksheet-2026-09-24
description: ECR checklist/risk work merged to main and pushed 2026-09-24 (2aea276e); prod does NOT have it yet (needs migrations 085/086)
metadata:
  type: project
---

**2026-09-24: merged and pushed to origin/main as 2aea276e** (merge of `feature/project-worksheet` onto origin/main). The DFM + worksheet release was already on origin/main and deployed to prod earlier that day (handoff commits df308758, ca56abce); the merge added only the change-management work: cockpit "Blocked by" lists the waits (WaitBanner removed), assessment checklist answered No/Yes per row with a submit gate, ⚑ risk flag per row (migration 085 `change_concerns.checklist_key`), "Rest → No" with a `bulk` mark, raiser deletes a risk raised by mistake (POST .../concerns/{id}/retract, migration 086 `retracted_at/by`, changelog `concern_retracted`). Spec/plan: `docs/superpowers/{specs,plans}/2026-09-24-assessment-checklist-answers*`.

**Why:** the user asked "push to main"; local main had been 60+ commits behind while the work lived in worktree `../plm2-integ` on `feature/project-worksheet` (a worksheet session created that branch there at 09:46, so cm commits landed on it, not on `integrate/dfm-redesign`).

**How to apply:** prod still lacks 085/086 and the cm UI; deploying needs the user's explicit "deploy" (backup prod DB, pull, rebuild, `alembic upgrade head`). Local stack (:5173/:8000, db `plm`) is at 086; backups before the merge in `/home/nitrolinux/claude/plm2-backups/`. `feature/change-management-2` (next-step checklist, 0828b8f3) is still unmerged and will conflict in CockpitSummary.tsx. See [[dfm-flow-and-integration-2026-09-23]].
