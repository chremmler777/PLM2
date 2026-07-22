# Change Start Permissions & Department Cleanup — Design

**Date:** 2026-07-22
**Branch:** `feature/change-flow-rework`
**Status:** approved, ready for planning

## Problem

Three unrelated defects surfaced while preparing a clean-database walkthrough of the
change flow.

1. **Anyone can start a change.** `POST /api/v1/changes` (`changes.py:54`) has no
   authorization beyond `get_current_user`. Because SSO maps every hub identity to
   either `admin` or `viewer` (`auth.py:26`), and viewers are already blocked from all
   non-GET methods (`auth.py:57`), the effective rule today is "every non-viewer may
   start a change". There is no way to express that starting a change belongs to
   Sales, Project Management and Engineering.

2. **Three inconsistent entry points.** `StartChangeModal` is opened from
   `ChangesPage.tsx:104`, `ProjectDetailPage.tsx:1058` and `PartDetail.tsx:479`, each
   with its own ad-hoc button markup. It is one flow behind three differently-styled
   doors, which reads as three features.

3. **The department table has dead duplicates.** `wf_departments` holds 16 rows, but
   the live routing config (`wf_templates` 116, the only template any
   `change_routing_standards` row points at) uses 11 of them. `Tool Engineer` (2) and
   `Manufacturing Engineer` (3) are seed-era names duplicating `Tool design` (10) and
   `IE` (11), which carry the real rates, activities and RASIC rows. The
   `TYPE_DISCIPLINES` fallback in `change_service.py:63` still names `Tool Engineer`
   plus `Process Engineer` and `Packaging Engineer` — the latter two do not exist in
   `wf_departments` at all, so that fallback can only ever produce a broken routing.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Keep all three entry points; unify them behind one shared button component | The prefills (project on project page, impacted part on part page) are genuinely useful. Consistency of the control, not removal of shortcuts, is what makes it read as one flow. |
| D2 | "Engineering" = Tool design + IE + R&D | User's mapping, confirmed against the live config: these are the departments carrying real RASIC/rate/activity rows. |
| D3 | Permission is stored on the department, not hardcoded | A hardcoded name list is exactly what produced the broken `TYPE_DISCIPLINES`. A column survives renames and is admin-editable. |
| D4 | Enforce in the service layer, not the router | All three entry points, plus any future caller (import scripts, API clients), go through `ChangeService.create_change`. |
| D5 | `role == "admin"` bypasses the department check | Consistent with the rest of the app, and necessary: the hub-bridged SSO identity (`admin-1`, id 7) currently has zero department memberships. |
| D6 | Merge duplicate departments, retire unused ones via `is_active` | `is_active` already exists on `wf_departments`; no schema change needed for retirement. Soft-retire preserves history that hard deletion would break. |

## Data changes

### Department merge and retirement

One Alembic migration, executed in this order:

1. **Repoint references** from the duplicate onto the live department, for every table
   with an FK to `wf_departments`: `wf_step_rasic`, `user_departments`,
   `lessons_learned`, `change_assessments`, `department_rate`,
   `assessment_activity`, `wf_instance_tasks`.

   | Duplicate | Live target |
   |---|---|
   | Tool Engineer (2) | Tool design (10) |
   | Manufacturing Engineer (3) | IE (11) |

   `user_departments` has a composite primary key `(user_id, department_id)`, so a
   repoint can collide when a user belongs to both the duplicate and the target
   (user `admin` belongs to both Tool Engineer and Tool design). Delete the duplicate
   row instead of updating it when the target row already exists.

2. **Retire** by setting `is_active = false` on: Developer (1), Tool Engineer (2),
   Manufacturing Engineer (3), APQP (4), Operations Manager (8).

   All RASIC rows belonging to these departments sit on `wf_templates` id 1 ("ECR"),
   which no `change_routing_standards` row references. Retiring them therefore
   affects no live routing.

3. **Downgrade** restores `is_active = true` and leaves the merged references in
   place. The merge is deliberately not reversed: the duplicate rows carried no
   unique data, so re-splitting them would be guesswork.

### Permission column

`ALTER TABLE wf_departments ADD COLUMN can_start_change BOOLEAN NOT NULL DEFAULT false`

Seeded `true` for: Sales (5), Project Manager (6), Tool design (10), IE (11),
R&D (9).

## Backend

### `ChangeService.can_start_change(session, user) -> bool`

Returns `True` when `user.role == "admin"`, otherwise whether the user belongs to any
department with `can_start_change = true AND is_active = true`.

### `ChangeService.create_change`

Gains a guard at the top: if `can_start_change` is false, raise
`ChangeError("Starting a change is restricted to: <names>")`. The existing
`ChangeError` → HTTP 400 mapping in `changes.py:68` is wrong for an authorization
failure; the router maps this specific case to **403** instead. A dedicated
`ChangePermissionError(ChangeError)` subclass keeps that distinction explicit rather
than matching on message text.

### `GET /api/v1/changes/permissions`

```json
{
  "can_start": false,
  "allowed_departments": ["Sales", "Project Manager", "Tool design", "IE", "R&D"],
  "your_departments": ["Quality"]
}
```

Route ordering matters: it must be declared before `GET /{change_id}` in
`changes.py`, alongside the existing static routes (`/my-tasks`,
`/routing-standards`), or FastAPI will match `permissions` as a `change_id`.

`allowed_departments` is read from the database rather than a frontend constant, so
an admin toggling `can_start_change` changes the enforcement and the popup text
together.

### Dead code removal

Delete `TYPE_DISCIPLINES` (`change_service.py:63`) and its use as a routing fallback.
When no `ChangeRoutingStandard` matches a change type, the correct behaviour is to
fail loudly — a silent fallback onto a list containing two non-existent departments
produces a change whose routing is quietly wrong. Callers get
`ChangeError("No routing standard configured for change type '<type>'")`.

## Frontend

### `<StartChangeButton>`

New component in `frontend/src/components/changes/`. Owns the button, the permission
query, the disabled state, the popup, and the `StartChangeModal` it opens. Props:
`prefill?: { projectId?, partId? }` and a `variant` for the two existing sizes
(page-header primary vs. inline secondary).

Replaces the ad-hoc buttons in `ChangesPage.tsx`, `ProjectDetailPage.tsx` and
`PartDetail.tsx`. Those three files should end up with a single `<StartChangeButton>`
line each and no local `showCreate` state.

Permission is fetched once via react-query with a shared key so all three mounts
share one cached result.

### Popup

Rendered on hover and on focus (keyboard reachable), in both permitted and denied
states:

- **Denied:** "Starting a change is restricted to: Sales · Project Manager · Tool
  design · IE · R&D" followed by "You are in: Quality", or "You are not assigned to
  any department" when the list is empty. Department labels are rendered verbatim
  from `allowed_departments` — no frontend prettifying, so the popup can never drift
  from the names being enforced.
- **Permitted:** the same allowed-departments line only, as discoverable information.

Dark-slate theme tokens, consistent with the app-wide rule. The button is `disabled`
with `aria-describedby` pointing at the popup, so the reason is announced rather than
being a dead control.

## Error handling

| Condition | Behaviour |
|---|---|
| User lacks a starting department | Button disabled, popup explains. API returns 403 if called directly. |
| Permission query in flight | Button disabled with a neutral loading state, no popup. |
| Permission query fails | Button enabled; the server is the authority and will return 403. Failing open in the UI avoids a dead button on a transient network error. |
| No routing standard for a change type | 400 with the explicit message; no silent fallback. |

## Testing

**Backend**

- `can_start_change`: admin bypass; member of a permitted department; member of a
  non-permitted department; member of a permitted-but-retired department (must be
  false); user with no departments.
- `create_change` raises `ChangePermissionError` and the router maps it to 403.
- `GET /permissions` payload for each of the above; route resolves ahead of
  `/{change_id}`.
- Migration: Tool Engineer and Manufacturing Engineer references land on Tool design
  and IE; the `user_departments` collision on user `admin` deletes rather than
  violating the primary key; the five retired departments report `is_active = false`;
  row counts on `wf_step_rasic` are conserved.
- Removing `TYPE_DISCIPLINES` leaves the existing suite green; an unmapped change
  type raises rather than routing.

**Frontend**

- `StartChangeButton` renders enabled/disabled per the permission payload.
- Popup content for permitted, denied-with-departments, and denied-with-none.
- All three host pages render exactly one button and open the shared modal with the
  right prefill.

The existing backend suite (142 tests) and frontend suite (31) must stay green.

## Out of scope

Real defects found during discovery, deliberately parked — they belong to the
lifecycle walkthrough, not to this change:

- All five change types map to `wf_templates` 116, so `change_type` does not
  differentiate routing at all. The spec premise "change_type drives routing" is
  unrealized.
- Template 116 makes ~10 departments blocking (R/A) on every change.
- Project Manager is R and A on template 116 but has 0 `department_rate` and 0
  `assessment_activity` rows, so it is asked for cost lines it cannot produce.
- The hub token carries an unread `department` claim (`auth.py:60`), leaving PLM
  department membership manual and prone to drift from the hub.
- `admin-1` (id 7), the hub-bridged SSO identity, has no department memberships.
