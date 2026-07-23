# Gate assessment behind a locked impacted set

**Date:** 2026-07-23
**Status:** Approved for planning
**Area:** Change management workflow (`backend/app/services/change_service.py`, `.../change_routing_service.py`, frontend change detail)

## Problem

A change can be submitted into assessment (`scoping -> in_assessment`) while its
impacted-item set has never been **locked** (`impact_confirmed_at is None`).
Entering assessment immediately fans out staged assessments and routing, so
cross-functional evaluation begins against an impacted set that R&D never
confirmed. If a flaw is then found, there is no way back: `in_assessment` has no
transition to `scoping`.

Concrete instance (live local Postgres, `claude-plm2-db-1`): **CR-2026-0002
"Add Support pads"** is `in_assessment` with `impact_locked = false`; entering
assessment already spawned **9 assessments** (all `pending`) plus routing
template 116. This is the exact failure this design closes.

Two contributing gaps:

1. The impacted set is not required to be locked before assessment. The
   `in_assessment` guard (`_guard`, `change_service.py:488`) only soft-requires
   impacted items *exist*, plus a lead, a deadline, and a proceed meeting.
2. The lock action ("confirm impacted items") is only surfaced as a next-action
   at status `approved` (`change_service.py:1060`) — far downstream of where it
   is now needed — so it is easy to miss during scoping.

## Goals

- Assessment cannot begin unless the impacted set is **defined and locked**.
- The gate is **hard**: no 4-eyes transition deviation can bypass it. Locking
  the impacted set is always doable and cheap, so there is no legitimate reason
  to skip it.
- A change in `in_assessment` can be **recalled to `scoping`** to fix a flawed
  impacted set, provided no assessment work has started.
- Locking the impacted set is the **prominent next step** after scoping, not a
  buried action.

## Non-goals

- Changing **who** may lock the impacted set. It stays R&D-member-or-admin
  (`user_can_confirm_impact`): the lead proposes the set, R&D confirms it. That
  separation is intentional and unchanged.
- Reworking the soft-block + 4-eyes deviation model for any other transition.
- Recall after real assessment work exists (see "no-silent-undo" below) — out of
  scope; those changes stay in assessment and follow the normal path.

## Design

### 1. Hard gate: no assessment until the impacted set is locked

Add an **unconditional** precondition in `ChangeService.transition()`, in the
same block as the existing hard gates (the `approved` checks at
`change_service.py:571`) — deliberately **not** in `_guard`, because `_guard` is
the soft/overridable layer whose failures can be waived by an approved
`ChangeTransitionDeviation`.

- When `to_status == "in_assessment"` and `change.impact_confirmed_at is None`,
  raise `ChangeError` (e.g. "Impacted set is not locked — confirm impacted items
  before starting assessment"). No deviation path.
- The existing soft checks in `_guard` for `in_assessment` (items exist, lead,
  deadline, proceed meeting) remain as-is. The hard lock check is additive.

Because editing the impacted set already clears the lock
(`_reset_impact_confirmation`, called from `add_impacted_item`,
`remove_impacted_item`, `apply_impact_selection`), any change to the set after
locking forces a re-lock before assessment can (re)start. That invariant is what
makes the gate meaningful.

### 2. Recall path: `in_assessment -> scoping`

- Add `scoping` to `ALLOWED_TRANSITIONS["in_assessment"]`
  (`change_service.py:48`).
- **Precondition (hard):** recall is only permitted while **every** assessment
  on the change is still `pending` (nothing submitted, no verdict). If any
  assessment has progressed, recall is refused — recall is a correction for a
  premature submit, not a silent undo of real work.
- **Teardown side effect on entry to `scoping` from `in_assessment`:** remove the
  assessment scaffolding that entering assessment created, so a corrected
  impacted set rebuilds cleanly on re-submit. That means: the staged
  `ChangeAssessment` rows, their linked `WfInstanceTask`s / stage-1 `WfInstance`,
  the `ChangeRouting` snapshot, and any "entered assessment" notifications
  produced by `build_routing`. `build_routing` is idempotent (returns the
  existing routing rather than rebuilding — `change_routing_service.py:122`), so
  without teardown a re-entry would silently reuse stale routing built from the
  old set. Reuse the existing task+assessment delete logic in
  `change_routing_service` (the remove path around lines 306-315) rather than
  duplicating it.
- Record the recall in the changelog (the standard `status_changed` entry
  covers it; add an explicit note that assessment scaffolding was torn down).

### 3. Surface the lock as the next step during scoping

In `next_actions` (`change_service.py:1057`), change the `impact_confirm`
action's condition so it is offered when:

- `change.status == "scoping"` (moved from `"approved"`; once the gate exists,
  impact is always locked before assessment, so the `approved` case is dead —
  drop it),
- impacted items exist,
- `change.impact_confirmed_at is None`,
- and the user passes `user_can_confirm_impact`.

Keep `target_tab: "impacted"`. The endpoint
(`POST /changes/{id}/impact/confirm`) already works at any status, so no authz
change is needed. Frontend change-detail should render this next-action
prominently during scoping (it is the thing standing between the change and
assessment).

### 4. Data fix for CR-2026-0002

Once the recall path exists, apply it to CR-2026-0002: recall to `scoping`,
which tears down its 9 pending assessments + routing 116. The user then fixes the
impacted set, locks it (R&D confirm), and re-submits through the new hard gate.
Performed against the live local Postgres (`claude-plm2-db-1`), not the stale
SQLite seed files in the repo.

## Data flow (after change)

```
captured -> scoping --[lock impacted set]--> (hard gate passes) --> in_assessment
                ^                                                        |
                |------------------ recall (all assessments pending) ----|
                                    (tears down assessments + routing)
```

## Testing

- **Gate:** `scoping -> in_assessment` with `impact_confirmed_at is None` raises,
  and **is not** waivable by an approved deviation. With the set locked, it
  succeeds and spawns assessments.
- **Lock invalidation:** locking, then editing the impacted set, clears the lock
  and re-blocks assessment.
- **Recall happy path:** `in_assessment -> scoping` with all assessments
  `pending` succeeds and removes assessments + routing + linked tasks; a
  subsequent re-lock + `in_assessment` rebuilds fresh routing.
- **Recall refusal:** with any assessment submitted / non-pending, recall raises.
- **next_actions:** during `scoping` with unlocked impacted items, an
  R&D/admin user sees the `impact_confirm` action; a non-authorized user does
  not; the action disappears once locked.
- **Regression:** existing `approved -> in_implementation` impact-confirm
  enforcement and the on_hold/resume routing-reuse behavior are unaffected.

## Open questions

None blocking. Actor for locking confirmed unchanged (R&D-or-admin).
