---
name: prod-ssh-fail2ban
description: Prod SSH (ktx-server 10.105.205.55) sits behind fail2ban; never let ssh fail auth, always source ~/.ssh/agent.env first
metadata:
  type: project
---

Prod box `ktx-server` (10.105.205.55, user christoph.demmler) bans the source
IP after a few failed SSH auths (recidive, hours to a week). The key
`~/.ssh/id_ed25519` is passphrase-protected, so a fresh Bash shell without the
agent socket fails auth and counts toward the ban.

**Why:** 2026-09-22 two BatchMode attempts failed because the agent vars were
not sourced. User: "failtoban, look in adminpanel, remember this."

**How to apply:**
1. `source ~/.ssh/agent.env && ssh-add -l` must list the key BEFORE any ssh.
2. If the agent is gone: passphrase = name of the oddly-named empty folder in
   `H:\Server` (read via `powershell.exe -NoProfile -Command "Get-ChildItem 'H:\Server'"`),
   verify with `ssh-keygen -y -P '<pass>' -f ~/.ssh/id_ed25519`, then
   `eval "$(ssh-agent -s)"; ssh-add ~/.ssh/id_ed25519` and rewrite agent.env with `export` lines.
3. Always `ssh -o BatchMode=yes ktx-server`. On "Permission denied" STOP, do not retry.
   Safe reachability check: `nc -z -w3 10.105.205.55 22`. Unban via DENWERIT
   `sudo fail2ban-client unban <ip>`.
Full procedure: `~/claude/adminpanel/CLAUDE.md` and `adminpanel/docs/plm2-prod-deploy-runbook.md` section 5.
