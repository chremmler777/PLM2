---
name: sep-forms-engine
description: SEP forms engine (in-app replacements for F-DVS-CORP templates) — spec and plan written 2026-09-03, implementation not started
metadata:
  type: project
---

State on 2026-09-03: design approved by user, spec at
docs/superpowers/specs/2026-09-03-sep-forms-engine-design.md, 12-task plan at
docs/superpowers/plans/2026-09-03-sep-forms-engine.md (commit 3792f287). No code yet.

Source documents downloaded from Q.wiki (ktx.qwikinow.de, Microsoft login, user logs in
via headed playwright-cli session `ktx`) into Documents/SEP/ (global-forms = corporate
F-DVS-CORP series incl. SEP matrix V03; weissenburg-ep-docs = plant WUG set). Not committed.
Toccoa has no own versions; global set applies.

Decisions: JSON definitions in repo (no form builder); submit marks linked SEP items done,
reopen reverts; risk tab replaced by risk_assessment form; English only; no document
control numbers in UI, `implements` metadata keeps traceability; first batch = risk
assessment, sales-PM handover, legitimization, contact list, LOP, deviation agreement;
remaining ~30 forms later as JSON only. `gate_items` flag off for 1994, on after first run.

**Why:** user wants forms adapted on the fly during first project 1994A/B.
**How to apply:** next session: run the plan with superpowers:subagent-driven-development
(user still to choose subagent vs inline). Related: [[brose-award-import-2026-09-02]].
