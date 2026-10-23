---
name: ecr-live-test-1-2026-10-14
description: First live ECR test findings (2026-10-14) and user decisions; build on branch feature/ecr-live-test-1, worktree ../plm2-live1
metadata:
  type: project
---

First live ECR test, findings + decisions (2026-10-14):
1. Scoping question raised by a department (APQP) became Sales-owned. Decision: the question stays the ASKING department's task; asking dept + Sales + PM may answer; closing stays asker or PM.
2. Missing warning popup when assessment is started with open flags: modal listing them.
3. Development's impacted-parts confirmation in scoping: removed but kept behind a switch for reuse; the set locks automatically on the meeting's 'proceed'.
4. Scope free text defined by PM in scoping (change_requests.scope_definition, migration 115).
5. Assessment + costing per-department pipeline: all assessment stages open at once; a department finalizes its own costing right after its assessment, no waiting for the team.

Build: worktree /home/nitrolinux/claude/plm2-live1, branch feature/ecr-live-test-1 off main e595b8d6; two builders (scoping / assessment-costing). Merge + deploy only on the user's word.

**Why:** feedback from the first live test with users.
**How to apply:** these rules supersede the Sales-only answer rule in [[scoping-concerns-2026-08-12]] and the sequential stage/costing-at-costing rules in [[ecr-buildout-2026-08-11]].

STATE 2026-10-14 end: branch commits 4221d4f0 (build), be79fc60 (review fixes), 0c12ea7b (training gate classification). Full suites: frontend 2980/2980 + tsc clean; backend 2130 passed, 1 failed (training route classification, fixed in 0c12ea7b, test_training 42/42). Not merged, not deployed; prod needs migration 115. Worktree frontend/node_modules is a symlink to main's (node_modules is tracked in git: never stage it). vitest here needs --minWorkers=1 with --maxWorkers=2.
Open: recall-to-scoping without supersede keeps positions PM entered before any submit.

2026-10-14 evening: Christoph handed ECR lead to the assistant-51 session (branch feature/ecr-solid, worktree ~/claude/plm2-ecr-solid off 0c12ea7b, migrations from 116). It adds two scoping flag types (blocking "missing info" vs default "for assessment" carried into the department's assessment). This session makes no further ECR changes unless asked; pending: update sections 1-2 of the live-test doc https://claude.ai/code/artifact/931fa723-b6ad-46e6-9305-a665cad7905d when assistant-51 sends commit ids.
