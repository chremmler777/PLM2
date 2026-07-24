---
name: governance-policy
description: "PLM2 change-management authorization policy decisions (who can sign off / quote / approve)"
metadata:
  type: feedback
---

# Change-management authorization policy (decided 2026-07-08)

User-chosen rules for the change cockpit, enforced backend (403) + UI-hidden:

- **Quality sign-off:** admin OR member of "Quality" department.
- **PM sign-off:** admin OR member of "Project Manager" department. 4-eyes kept (PM and Quality must be different users).
- **Quoted price** (set via PATCH /changes/{id}): admin, the change lead, OR member of "Sales".
- **Internal cost approval:** admin OR member of "Project Manager" — **PRAGMATIC, not strict 4-eyes**. The approver MAY be the same person who decided scoping. User deliberately chose this over strict 4-eyes so single-PM orgs aren't deadlocked.

**Why:** small teams (possibly one PM) must not be locked out of approving internal changes; but casual over-broad access (any engineer signing Quality) was unwanted.

**How to apply:** enforce in both the API and the UI (hide controls); department names are exact literals "Quality"/"Project Manager"/"Sales". If asked to add strict 4-eyes on internal approval later, that's the deferred stricter variant — confirm it won't deadlock the org first. See [[pnl-usability-2026-07-07]].
