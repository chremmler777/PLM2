# Acts-As Role Switch & Role-Aware Action Buttons — Design

**Date:** 2026-07-22
**Branch:** `feature/change-flow-rework`
**Status:** approved, ready for planning
**Depends on:** `2026-07-22-change-start-permissions-design.md` (sub-project 1) — its
`wf_departments.can_start_change` column, `ChangeService.can_start_change`,
`GET /changes/permissions` and `StartChangeButton` are the foundation this generalizes.

## Problem

A single person needs to walk one change request through the entire lifecycle —
captured → scoping → in_assessment → costing → quoted → approved → in_implementation →
in_validation → released → closed — to find out which of the implemented behaviours are
wrong. Two things make that impossible today.

1. **The walker cannot become the departments the flow routes to.** The hub-bridged SSO
   identity (`admin-1`, id 7) holds no `user_departments` rows at all. Template 116
   makes ten departments blocking (R/A) on every change. Assessments, sign-offs and gate
   decisions are all addressed to departments nobody at the keyboard belongs to.

2. **Admin bypasses every check, so nothing can be observed failing.** `role == "admin"`
   short-circuits the permission checks. An admin walking the flow sees every gate open
   and learns nothing about whether the gates are correct. Testing a guard requires being
   able to fail it.

Separately, when an action *is* refused, the UI does not say who may perform it. The
user's requirement: every gated action states its required role, the way
`StartChangeButton` states who may start a change.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Acts-as is **backend-enforced**, not a UI preview | A frontend-only switch tests the UI's guess at the rules rather than the rules. A UI bug would read as correct behaviour — the exact failure mode this walkthrough exists to catch. |
| D2 | Acts-as **drops the admin bypass**: effective role becomes `engineer`, effective departments become exactly the selected one | Without this the switch is cosmetic — every check still passes. This is the mechanism that makes gates observable. |
| D3 | Transport is a request header, not server-side session state | Stateless, scoped to one browser tab's requests, and cannot leak into a background job or another session. Clearing it is instant and total. |
| D4 | Only a real admin may act as anyone; the check reads the *real* user | Otherwise acts-as could be chained to escalate. The real identity is always recoverable for audit. |
| D5 | Every mutating request under acts-as is written to the audit log with both identities | An audit trail that records only the assumed identity is a forged record. |
| D6 | Admin department membership is granted to every `role='admin'` user by migration, not to `admin-1` by name | A username in a migration rots as soon as the hub provisions a different one. |
| D7 | One shared `GatedActionButton`, generalized from `StartChangeButton` | Nine gated actions each hand-rolling a permission popup guarantees drift. |

## Effective actor

The core abstraction. A new dependency resolves the *effective* actor for a request:

```
EffectiveActor:
    user: User            # the real, authenticated row — never rewritten
    role: str             # "engineer" while acting-as, else user.role
    department_ids: set   # {selected} while acting-as, else real membership
    acting_as: int | None # the department id being impersonated
```

Resolution:

1. Read `X-Acts-As-Department` from the request. Absent or empty → effective actor is
   the real user, unchanged. This is the path every existing request takes, so behaviour
   for non-admins is bit-for-bit identical to today.
2. Present, but the **real** `user.role != "admin"` → **403**. Not a silent ignore: a
   non-admin sending the header is either a bug or an escalation attempt, and both
   deserve to be loud.
3. Present and valid → look up the department. Unknown id or `is_active = false` → 400.
4. Otherwise return an effective actor with `role = "engineer"`, `department_ids =
   {that id}`, `acting_as = that id`.

`role = "engineer"` rather than `"viewer"` because viewer is blocked from all non-GET
methods at `auth.py:57` — acting as Sales must be able to submit an assessment.

Every permission function in the change module takes the effective actor instead of the
`User`. `ChangeService.can_start_change`, `user_can_sign_off`, the gate-decision
lead/admin check, the deviation second-signature check, and the quoted-price and
internal-approval guards all move onto it. That is the whole point of routing through
one object: no call site needs to know acts-as exists.

**`auth.py:57` is not bypassed.** The read-only viewer rule runs against the real hub
roles before acts-as is resolved. A `plm2_Viewer` cannot acquire write access by sending
the header, because step 2 rejects them for not being a real admin.

## Audit

`AuditService` already hash-chains entries with a `correlation_id` per change. Two
fields are added to `audit_logs`: `acting_as_department_id` (nullable int) and
`real_user_id` (nullable int, populated only when acts-as is active — `user_id` keeps
holding the effective identity so existing queries are unaffected).

Every mutating request resolved under acts-as writes both. An entry that records only
the assumed department is a forged record, so this is not optional and not sampled.

## API

### `GET /api/v1/auth/acts-as/options`

Admin-only. Returns the active departments an admin may act as:

```json
{ "departments": [{ "id": 5, "name": "Sales" }, { "id": 12, "name": "Quality" }] }
```

403 for non-admins — the dropdown must not render for anyone else.

### `GET /api/v1/auth/me` (extended)

Gains `acting_as: { id, name } | null` and `is_real_admin: bool`, so the frontend can
render the banner and decide whether to show the dropdown at all without a second
round-trip.

### Header contract

`X-Acts-As-Department: <department_id>`. Sent on every request by the axios client when
a department is selected. Absent otherwise — never sent as an empty string, because an
empty header is ambiguous between "not acting" and "acting as nothing".

## Frontend

### Selection state

The selected department id lives in `localStorage` under `plm2.actsAsDepartmentId`, read
by the axios request interceptor in `frontend/src/api/client.ts`. localStorage rather
than React state so a page reload does not silently drop you back to admin mid-walk —
losing the role halfway through a lifecycle walk and not noticing is precisely the
confusion this feature exists to remove.

Changing the selection invalidates the entire react-query cache. Every permission
answer, task list and action state in memory was computed for the previous identity.

### The switcher

A dropdown in the app header, rendered only when `is_real_admin` is true. Options come
from `/auth/acts-as/options`, plus a "Yourself (admin)" entry that clears the selection.

### The banner

While acting-as, a persistent bar sits below the header: *"Acting as **Sales**. Admin
powers are suspended."* with a one-click exit. Amber, full-width, not dismissible. You
must never wonder who you are.

### `GatedActionButton`

`StartChangeButton` from sub-project 1, generalized. Props:

```ts
{
  action: ChangeAction;        // discriminated union, below
  changeId?: number;
  onClick: () => void;
  variant?: 'primary' | 'inline';
  label: string;
}
```

It renders the button, disables it when the action is not permitted, and shows the
popup naming who may perform it — in both permitted and denied states, so the rule is
discoverable rather than only punitive. Department names render verbatim from the API;
no frontend prettifying, so the popup can never drift from what is enforced.

The nine change-flow actions it covers: start change, gate decision, assessment submit,
sign-off (PM), sign-off (Quality), quoted price, internal approval, transition, and
deviation approval.

### Permission source

`GET /api/v1/changes/{id}/my-actions` already exists (`changes.py:245`) but returns a
**filtered list of actions the caller can perform** — a denied action is simply absent.
That is exactly the wrong shape here: a button can only say "Quality may do this" if the
server tells it about actions the caller *cannot* perform.

So the endpoint changes from a filtered list to a complete verdict map. Every action
applicable to the change's current status is returned, each as
`{ kind, label, allowed: bool, required: string[], reason: string | null }`. Callers
that want today's behaviour filter on `allowed`.

`ChangeService.my_actions` (`change_service.py:975`) currently mirrors, by hand, the
authorization of each endpoint that performs the action — its own docstring says so.
Widening it to also explain *why* an action is denied doubles down on that duplication:
the mirror is now load-bearing for what the user sees, not just which buttons appear.
Each action's permission test must therefore be extracted into a single named predicate
called by both `my_actions` and the endpoint that performs it, so the two cannot drift.
That extraction is part of this work, not a follow-up.

One request per change detail page answers every button on it. `GatedActionButton` reads
from that shared query; only the start-change action, which has no change id, falls back
to `GET /changes/permissions`.

## Error handling

| Condition | Behaviour |
|---|---|
| Non-admin sends the acts-as header | 403, message names the real role. Loud, never silently ignored. |
| Header names an unknown or retired department | 400. The frontend clears the stored selection and reloads as admin. |
| Action not permitted for the effective actor | Button disabled with a popup naming the required roles; the API independently returns 403 if called directly. |
| `my-actions` query in flight | Buttons disabled, no popup. |
| `my-actions` query fails | Buttons enabled; the server is the authority and returns 403. A dead UI after a transient network blip is worse than a failed request. |

## Testing

**Backend**

- Effective actor: no header → real user unchanged; header as admin → role `engineer`
  and exactly one department; header as non-admin → 403; unknown department id → 400;
  retired department id → 400.
- The admin bypass is genuinely suspended: an admin acting as a non-starter department
  is refused `create_change` with 403.
- A `plm2_Viewer` sending the header is rejected at step 2 and cannot reach a write path.
- Audit rows written under acts-as carry both `real_user_id` and
  `acting_as_department_id`; rows written normally carry neither.
- Migration 033: every `role='admin'` user ends up a member of all active departments;
  re-running is idempotent; retired departments are not granted.
- `my-actions` returns every applicable action with `allowed`, `required` and `reason`,
  for both a permitted and a denied actor — denied actions must be present, not filtered
  out.
- Each extracted permission predicate is asserted to give the same verdict as the
  endpoint that performs the action, for at least one allowed and one denied case. This
  is the test that stops `my_actions` drifting from real authorization.
- `GET /auth/acts-as/options` returns only active departments; 403 for non-admins.

**Frontend**

- The axios interceptor sends the header when a selection exists and omits it entirely
  when cleared.
- Switching selection invalidates the query cache.
- The banner renders while acting-as and not otherwise; the dropdown renders only for a
  real admin.
- `GatedActionButton` enabled/disabled/popup states, including the fail-open path when
  the permission query errors.

The backend and frontend suites must stay green — no regressions against the counts
sub-project 1 finishes at.

## Out of scope

- Reading the hub token's unused `department` claim to auto-sync `user_departments`.
  Acts-as removes the immediate blocker; the drift problem is separate.
- Gated controls outside change management (parts, tooling, projects, quality).
- The parked routing defects that motivated the walkthrough: all five change types
  mapping to `wf_templates` 116, ten blocking departments per change, and Project
  Manager being R/A with zero rates and zero activities. Those are what the walkthrough
  is *for* — this spec only builds the means to observe them.
