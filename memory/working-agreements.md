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
