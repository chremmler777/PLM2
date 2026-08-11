---
name: working-agreements
description: "How the user works on PLM2 — autonomous /loop building, commit style, verification expectations"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f12d046e-5979-4776-b412-d494bec95479
---

# Working agreements (PLM2)

User runs autonomous build loops ("/loop be creative", "you know how I work in the other projects") and wants rapid, full-feature expansion toward a production-quality PLM system.

**Why:** They want a working system soon and trust iterative autonomous delivery over up-front questioning.

**How to apply:**
- Each loop iteration: pick the highest-value chunk from [[phase5-status]] roadmap, build it end to end (backend + frontend), verify with a live smoke test (start uvicorn, curl the endpoints), then commit with descriptive `Feat:`/`Fix:` messages (existing repo convention, git user "Claude Code").
- Committing without asking is the established pattern in this repo (frequent small feature commits on main).
- Verify by running the real server, not just imports — the STEP-segfault bug was only found by live upload testing.
- Don't commit plm.db churn or __pycache__; stage only source files.

## Lean mode (2026-08-11, after a canceled 1.5h session)

User canceled a session because a "simple" feature drowned in brainstorm→spec→plan ceremony. Explicit instruction: "we need to run quick, i need to ship, doesn't have to be perfect."

**Why:** The superpowers pipeline's fixed cost (spec + plan docs, TDD fail-first steps, full-suite runs between tasks) dominates small features. The backend suite alone takes ~14 min (447 tests, ~3s each), so running it between steps burns the session.

**How to apply:**
- Small features: no spec/plan docs, no fail-first ceremony. Implement + tests together, commit, move on. Ceremony is opt-in for big cross-cutting work only.
- Tests: targeted files per feature; ONE full-suite run batched at the end before shipping — never between steps.
- Delegation pattern that worked well: Fable supervises + designs, two persistent Opus subagents execute (one backend, one frontend, disjoint file sets, frontend never runs git — supervisor commits its work). Feed them follow-up tasks via SendMessage as the user live-tests and fires findings.
- User live-tests in the running app and sends rapid-fire UX findings mid-turn; treat each as a small dispatch, keep the loop tight.
