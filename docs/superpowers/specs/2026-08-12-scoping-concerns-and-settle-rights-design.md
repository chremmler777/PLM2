# Scoping Team Concerns Restored & Settle Rights — Design

**Date:** 2026-08-12
**Branch:** `main` (post-merge of `feature/ecr-target-state`)
**Status:** built, verified (backend + frontend suites green)
**Depends on:** `2026-07-22-acts-as-role-switch-design.md` (D2 — acting-as drops the
real identity's privileges; this spec extends that to personal authorship),
risk-register rework of 2026-08-11 (`4b8955b3` backend, `2b18996f` frontend).

## Problem

The 2026-08-11 risk-register rework narrowed hand-raised concerns to `kind="risk"`
**everywhere** — backend `raise_concern` refused `needs_info`/`reject_proposal`, and
`ConcernStrip`'s form was rewritten to submit only risks. Since `ScopingPanel` shares
that strip, scoping's team-concern flow silently became the risk form. That was wrong
on both ends:

1. **Scoping lost its parallel team voice.** The old module let any team member ask
   for more information (a question) or vote for cancellation without waiting for the
   meeting, with open flags blocking `proceed`. This was working behaviour and was not
   supposed to change.
2. **The risk register leaked into the wrong phase.** Risks belong to assessment,
   where the technical work happens — not to the scoping room.

Two further problems surfaced while restoring it:

3. **Sales could mark a question solved through department attribution.** A question
   attributed to the Sales department ("Sales must ask the customer") made every Sales
   member count as "the raising department" in `withdraw_concern` and in the
   `close_question` my-tasks addressing. In scoping, attribution is a label anyone may
   pick — it must grant nobody the right to declare the point settled.
4. **The acts-as switch kept personal authorship.** An admin who raised a question as
   themselves, then drove the Sales view via `X-Acts-As-Department`, still saw an
   enabled "mark solved" button — the requester right (`raised_by == user.id`)
   survived the hat-switch. That breaks the simulation D2 exists for and is exactly
   how "Sales can still settle" reproduced in the field (dev account `admin-1`/id 7
   raised and answered its own test question).

Plus one UX gap: question cards named the asker by username only. Who asks matters as
much as what is asked — the reader needs the hat next to the name. (And "Answered by"
fell back to `#id` because the backend never served `answered_by_name`.)

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Phase-split raise vocabulary.** Scoping hand-raises `needs_info` / `reject_proposal`; assessment hand-raises `risk` only. Each phase refuses the other's kinds. | Restores the working scoping module without giving up the risk register. A risk holds nothing and is worked with a mitigation proposal — that is assessment's business. A question or cancel vote feeds the scoping decision and blocks `proceed` — that is scoping's. |
| D2 | **Settling a scoping question/vote = its author or a Project Manager member. Nobody else, Sales least of all.** Department attribution grants no settle right in scoping. | Attribution needs no membership, so it cannot confer ownership. An objection cleared by the side it inconveniences is the failure the feature exists to prevent. Sales' part is *answering* (`answer_concern`), which deliberately leaves the flag open. |
| D3 | **The department-member settle path survives only where the department owns the flag:** risks (any phase) and department holds while `in_assessment`. | Colleagues cover for each other and people leave — a department flag is the department's, not one member's. Keyed on kind/status at settle time, mirroring `answer_concern`'s "what is this concern doing now" philosophy. |
| D4 | **Acting-as sets personal authorship aside**, in `withdraw_concern`, in `close_question` task addressing, and in the UI gates. | Acts-as D2 says the admin becomes exactly that department — real memberships and admin bypass step aside. Authorship leaking through shows rights the simulated department does not have, which defeats the simulation and confused live testing. Dropping the switch restores the right. |
| D5 | **`close_question` tasks address the asker and PM** (plus department members only for in-assessment department flags), mirroring D2/D3. | The task list must never invite an action the endpoint will refuse. |
| D6 | **The concerns list serves the asker's departments (`raised_by_departments`) and the answerer's name (`answered_by_name`).** Single-concern responses leave them empty; the UI re-fetches the list after every mutation anyway. | Roles are read from the same membership rows the permission checks use — one source of truth. Enriched in the list endpoint (two grouped queries), not as model properties, because `User` has no departments relationship and lazy loads are a trap under async. |

## Behaviour

### Raising (hand-raise via `POST /changes/{id}/concerns`)

| Phase | Allowed kinds | Department field |
|---|---|---|
| captured / scoping | `needs_info` (question), `reject_proposal` (cancel vote) | Optional attribution — any active department, no membership required, "Team" = none |
| in_assessment | `risk` (type + severity 1–3 required) | Required; must be the raiser's own department (admins/acts-as for the acted one) |

Unchanged: any authenticated user may raise; one open concern per person per kind
(risks exempt); meeting-decided `needs_info` is still written directly by
`decide_meeting`; open non-risk concerns still block `proceed`; risks never block.

### Settling (`withdraw` / "mark solved")

| Flag | Who may settle |
|---|---|
| Scoping question / cancel vote (any attribution) | Author (requester) or PM member |
| Assessment department hold (legacy `reject_proposal`/`needs_info` with department) | Author, that department's members, or PM member |
| Risk | Author, its department's members, or PM member |

- Sales *answers* questions (`answer_concern`) — answering never settles.
- No admin shortcut anywhere (unchanged).
- Under acts-as, the author path is inert (D4); PM rights exist only if acting as
  Project Manager.
- A department-attributed withdrawal still requires a resolution note (unchanged,
  keyed on `department_id`).

### Display

Question cards and concern rows render `Name (Dept, Dept)` for the asker, and the
answerer's real name. Empty memberships → name only.

## Touched surface

- `backend/app/services/meeting_service.py` — `raise_concern` phase split;
  `withdraw_concern` ownership rules + acts-as authorship guard.
- `backend/app/api/v1/changes/changes.py` — `close_question` addressing;
  `list_concerns` enrichment.
- `backend/app/schemas/change.py` — `ConcernCreate` default/comments;
  `ConcernResponse.raised_by_departments` / `answered_by_name`.
- `frontend/src/components/changes/ConcernStrip.tsx` — scoping concern form restored
  (kind picker + attribution + note); risk form now assessment-only (`scoped`);
  `mayClose` honours D2–D4; role suffix on rows.
- `frontend/src/components/changes/ScopingPanel.tsx` — `canSettle` honours acts-as.
- `frontend/src/components/changes/NeedsInfoCard.tsx` — asker role suffix.
- `frontend/src/api/changes.ts`, `frontend/src/types/change.ts` — comments + type.
- `docs/ECR_PROCESS_MAP.md` — stage-2 row records the team-concern loop.

No migrations: `CONCERN_KINDS` and all columns already existed.

## Test pins

- `test_change_concerns.py` — scoping takes questions/votes by hand; risk refused in
  scoping; assessment takes only risks; hand-raised vote blocks `proceed`;
  acts-as sets authorship aside; list serves the asker's role.
- `test_needs_info_loop.py` — Sales answers but cannot settle; **Sales-attributed
  question gives Sales no settle right and no `close_question` task** (the hole that
  reproduced in the field); answerer's name served.
- `test_change_risk_register.py` — assessment raise vocabulary pinned.
- `ConcernStrip.test.tsx` / `NeedsInfoCard.test.tsx` — scoping form kinds; attribution
  grants no settle button; acts-as greys own flag; role rendering.

## Parked

- The dev/test account `admin-1` (id 7) holds no memberships and the seeded `admin`
  (id 2) holds *every* department including Sales + Project Manager — both make
  role-gate testing misleading. A dedicated single-department test user per role
  would remove this class of false bug report.
