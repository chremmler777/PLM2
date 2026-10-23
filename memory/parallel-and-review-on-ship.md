---
name: parallel-and-review-on-ship
description: User wants maximum parallel subagents and an immediate review of every chunk the moment it is shipped/committed
metadata:
  type: feedback
---

Run as much in parallel as possible (builders, reviewers, docs, test walks on disjoint files) and start a review of each chunk right when it is committed, not batched at the end. Also show progress bars in chat while builders run.

**Why:** said 2026-09-24 during the ECR costing-to-close build ("Parallelism as much as possible and review straight when shipped", "show me status bars ... in this chat").

**How to apply:** on every builder completion: commit, then immediately dispatch a reviewer for that commit while other work continues; keep disjoint file ownership so parallel agents don't collide. Related: [[working-agreements]].
