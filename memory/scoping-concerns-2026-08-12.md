# Scoping concerns restored & settle rights — 2026-08-12

Session record; full spec in
`docs/superpowers/specs/2026-08-12-scoping-concerns-and-settle-rights-design.md`.

- The 2026-08-11 risk-register rework had replaced scoping's team concerns with
  the risk form everywhere. Restored the phase split: scoping hand-raises
  `needs_info` (question) / `reject_proposal` (cancel vote), blocking `proceed`;
  assessment hand-raises risks only; each phase refuses the other's kinds.
- Settling ("mark solved") a scoping question/vote: **author or PM member only**
  — never Sales. Department attribution grants no settle right (that was the
  hole: a Sales-attributed question unlocked for all Sales members, in
  `withdraw_concern` and the `close_question` task). Department members settle
  only what the department owns: assessment holds and risks.
- Acts-as now sets personal authorship aside too (backend + UI): the field
  report "Sales still has the button" was `admin-1` (id 7) seeing its own
  requester right while acting as Sales.
- Concern lists serve `raised_by_departments` and `answered_by_name`; cards
  show "Name (Dept, …)".
- **Test-data caveat:** id 2 `admin` is in every department (incl. Sales + PM),
  id 7 `admin-1` has none — both make role-gate testing misleading. Parked:
  seed one single-department user per role.
- All uncommitted on `main` as of this session (user hasn't asked for a commit).
