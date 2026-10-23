---
name: machine-ram-limit-parallel-agents
description: Dev box has 15 GB RAM / 24 cores; 5 parallel agents running pytest -n and vitest exhausted RAM (load 68) and likely caused a reboot on 2026-09-24
metadata:
  type: project
---

On 2026-09-24 evening the WSL box (15 GB RAM, 24 cores) rebooted mid-session while ~5 subagents ran tests in parallel; after restart, load hit 68 with RAM fully used (vitest ~11 cores, pytest xdist workers). The user saw connection issues.

**Why:** parallel builders each spawning multi-worker test runs multiply memory use on top of the docker stacks.

**How to apply:** when running many agents in parallel (see [[parallel-and-review-on-ship]]), tell each one up front: vitest `--maxWorkers=2` on touched files only, pytest without `-n` (or `-n 2`) on touched files only, one Playwright browser at a time; the supervisor alone runs the full suites, on a separate clean worktree, when agents are idle.

Root cause found later that night: `backend/pytest.ini` sets `-n auto` (24 xdist workers), so every agent that ran pytest without an explicit `-n` spawned 24 workers. Always pass `-n 2` (or `-n 0`) explicitly.

Correction 2026-09-25: the 00:43 shutdown was an orderly WSL poweroff initiated from Windows (systemd stopped services in order), not an out-of-memory crash; the user suspects a Windows auto-update. The 2-worker cap stays useful for load, but a reboot is not proof of RAM exhaustion. Before long unattended runs, remind the user to set Windows active hours / pause updates.

2026-09-26 ~08:00 local: the WSL box rebooted again during a backend suite at -n 6 plus a Playwright walk (journald had crashed earlier that night). /tmp (incl. the session scratchpad) was wiped by the reboot. Lessons: keep evidence/plans that matter outside /tmp (e.g. repo docs or memory), run the full backend suite at -n 4 max, fully detached (setsid nohup) with output to a log, because harness background tasks get cut off mid-run.

2026-09-26 08:45: ROOT CAUSE of the repeated reboots: kernel OOM killer, a python3 (pytest worker) at ~6 GB RSS, around 45% of the full backend suite, each time. So one test (or code path it hits) blows up memory. Always run pytest under `ulimit -v 3000000` (per-process address space cap) so a runaway test fails with MemoryError instead of taking the machine down.
FIXED 2026-09-26 (commit after e50ff50c, backend/tests/conftest.py): the backend test workers grew ~138 MB per 100 tests because (1) app/main.py basicConfig(DEBUG) made aiosqlite log every op and pytest kept the captured text per test, (2) SQLAlchemy per-mapper compiled cache pinned one dialect per per-test engine. Now ~8 MB/100 tests. Keep the ulimit cap anyway.
