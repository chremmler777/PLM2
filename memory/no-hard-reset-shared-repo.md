---
name: no-hard-reset-shared-repo
description: Never git reset --hard / checkout -- . / stash in plm2: several Claude sessions keep uncommitted work in the same tree
metadata:
  type: feedback
---

Never run `git reset --hard`, `git checkout -- .`, `git stash` or `git clean` in /home/nitrolinux/claude/plm2.
Other sessions (PDB, DFM, imports) keep uncommitted edits there, mostly memory/*.md.

**Why:** 2026-10-05 a `git reset --hard origin/main` (to replace an amended commit) wiped three memory files'
uncommitted edits from other sessions; they had to be replayed from the session transcripts
(~/.claude/projects/-home-nitrolinux-claude-plm2/*.jsonl).

**How to apply:** to fix a pushed commit, add a new commit on top; to move a local branch, use
`git reset --soft` or `git rebase` only after `git status` shows no foreign changes. Commit by explicit path.
