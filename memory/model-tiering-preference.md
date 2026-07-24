---
name: model-tiering-preference
description: Use lower-tier models (haiku/sonnet) for subagent tasks when quality is not critical
metadata:
  type: feedback
---

Use lower-tier models for subagent work when there is no quality concern (mechanical edits, exploration, boilerplate tasks); reserve high-tier models for design, tricky implementation, and review.

**Why:** User pays for tokens; most SDD implementer/explorer tasks don't need top-tier reasoning.

**How to apply:** In subagent-driven development and Agent/Workflow calls, pass `model: "haiku"` or `"sonnet"` for mechanical/low-risk tasks; keep default (session) model for complex implementation and reviews. See [[working-agreements]].
