# Gate Assessment Behind a Locked Impacted Set — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make locking the impacted set a hard precondition of entering assessment, add a recall path out of assessment, surface the lock as the prominent scoping step, and fix the live CR-2026-0002.

**Architecture:** Backend is FastAPI + async SQLAlchemy; the change lifecycle is a state machine in `ChangeService.transition()` with a soft/overridable `_guard` layer and a set of unbypassable hard gates. We add a hard gate (unbypassable by deviation) for `-> in_assessment`, a new `in_assessment -> scoping` recall transition with an assessment-scaffolding teardown, and move the `impact_confirm` next-action from `approved` to `scoping`. Frontend surfaces the blocker in `CockpitSummary`.

**Tech Stack:** Python 3.11/3.12, FastAPI, SQLAlchemy async, pytest + pytest-asyncio (backend); React + TypeScript + vitest (frontend); PostgreSQL (live), SQLite (tests).

## Global Constraints

- Backend tests run from `backend/` with `pytest`. Async tests use `pytestmark = pytest.mark.asyncio`.
- Frontend tests run from `frontend/` with `npm test` (vitest).
- The lock action authz is unchanged: R&D-member-or-admin (`ChangeService.user_can_confirm_impact`). Do not touch it.
- The hard gate must NOT be placed in `_guard` — `_guard` failures are waivable by an approved `ChangeTransitionDeviation`. Hard gates live directly in `transition()`.
- Commit after each task. Commit messages end with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- The live data fix (Task 5) targets the Postgres container `claude-plm2-db-1`, NOT the stale SQLite files in the repo.

---

### Task 1: Hard gate — no assessment until the impacted set is locked

Adds the unbypassable precondition and fixes the shared test helper in lockstep (the helper currently drives `scoping -> in_assessment` without locking, so every test using it would break otherwise).

**Files:**
- Modify: `backend/app/services/change_service.py` (in `transition()`, near the `approved`/`quoted` hard gates around lines 571-586)
- Modify: `backend/tests/conftest.py` (add `lock_impact` helper; call it inside `advance_to_assessment`, lines 129-142)
- Test: `backend/tests/test_assessment_impact_gate.py` (new)

**Interfaces:**
- Consumes: `ChangeService.transition(session, change, to_status, user_id)`, existing `advance_to_assessment(client, auth, session_factory, change_id, dept_ids=None)`, `record_proceed_meeting`.
- Produces: `lock_impact(session_factory, change_id, actor_id=1)` async helper in conftest; hard-gate behavior on `-> in_assessment`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_assessment_impact_gate.py`:

```python
"""The impacted set must be LOCKED (R&D-confirmed) before a change may enter
assessment. Hard gate: no approved transition deviation can bypass it."""
import pytest

from tests.conftest import record_proceed_meeting
from tests.test_changes import departments  # noqa: F401 (reused fixture)

pytestmark = pytest.mark.asyncio


async def _scoping_ready(client, auth, seed, session_factory, part):
    """Create a change with one impacted item, in 'scoping' with a deadline and
    a recorded 'proceed' meeting — everything ready for assessment EXCEPT the
    impact lock."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "gate test",
        "change_type": "physical_part", "lead_id": seed["engineer_id"],
    }, headers=auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True}, headers=auth)
    await client.post(f"/api/v1/changes/{cid}/transition",
                      json={"to_status": "scoping"}, headers=auth)
    await client.patch(f"/api/v1/changes/{cid}",
                       json={"required_by_date": "2026-12-31T12:00:00Z"}, headers=auth)
    await record_proceed_meeting(session_factory, cid)
    return cid


async def test_assessment_blocked_until_impact_locked(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _scoping_ready(client, admin_auth, seed, session_factory, part)
    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=admin_auth)
    assert blocked.status_code == 400, blocked.text
    assert "lock" in blocked.json()["detail"].lower()

    await client.post(f"/api/v1/changes/{cid}/impact/confirm", headers=admin_auth)
    ok = await client.post(f"/api/v1/changes/{cid}/transition",
                           json={"to_status": "in_assessment"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "in_assessment"


async def test_deviation_cannot_bypass_lock_gate(
        client, admin_auth, eng_auth, seed, departments, session_factory, part):
    cid = await _scoping_ready(client, eng_auth, seed, session_factory, part)
    dev = (await client.post(f"/api/v1/changes/{cid}/deviations", json={
        "to_status": "in_assessment", "reason": "skip lock"}, headers=eng_auth)).json()
    ok = await client.post(f"/api/v1/changes/{cid}/deviations/{dev['id']}/decide",
                           json={"decision": "approved"}, headers=admin_auth)
    assert ok.status_code == 200, ok.text

    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "in_assessment"}, headers=eng_auth)
    assert blocked.status_code == 400, blocked.text
    assert "lock" in blocked.json()["detail"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_assessment_impact_gate.py -v`
Expected: both tests FAIL — the transition to `in_assessment` currently returns 200 without a lock.

- [ ] **Step 3: Add the hard gate in `transition()`**

In `backend/app/services/change_service.py`, immediately after the `quoted` hard-check block (the `if to_status == "quoted" and not change.customer_relevant:` raise, ~line 584-586) and before `if to_status == "cancelled":`, insert:

```python
        # HARD gate: assessment cannot start on an unlocked impacted set. Placed
        # here (not in _guard) so no approved transition deviation can bypass it —
        # defining and locking the impacted set is always doable and cheap.
        if to_status == "in_assessment" and change.impact_confirmed_at is None:
            raise ChangeError(
                "Impacted set is not locked — confirm impacted items before "
                "starting assessment")
```

- [ ] **Step 4: Add `lock_impact` helper and wire it into `advance_to_assessment`**

In `backend/tests/conftest.py`, add this helper (near `record_proceed_meeting`, ~line 127):

```python
async def lock_impact(session_factory, change_id: int, actor_id: int = 1):
    """Stamp the impacted-set lock directly (bypasses confirm authz) so
    state-machine tests can cross the -> in_assessment hard gate."""
    from datetime import datetime
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        change = await s.get(ChangeRequest, change_id)
        change.impact_confirmed_by = actor_id
        change.impact_confirmed_at = datetime.utcnow()
        await s.commit()
```

Then in `advance_to_assessment` (lines 129-142), add the lock call after the proceed meeting and before the `in_assessment` transition:

```python
    await record_proceed_meeting(session_factory, change_id, dept_ids)
    await lock_impact(session_factory, change_id)  # cross the -> in_assessment hard gate
    res = await client.post(f"/api/v1/changes/{change_id}/transition",
                            json={"to_status": "in_assessment"}, headers=auth)
    assert res.status_code == 200, res.text
```

- [ ] **Step 5: Run the new tests and the full change suite**

Run: `cd backend && pytest tests/test_assessment_impact_gate.py -v`
Expected: PASS.

Run: `cd backend && pytest tests/test_changes.py tests/test_change_scoping.py tests/test_change_routing.py tests/test_change_cost.py tests/test_change_gates.py tests/test_change_deviations.py tests/test_impact_confirmation.py tests/test_my_actions.py -q`
Expected: PASS (the `advance_to_assessment` fix keeps them green).

- [ ] **Step 6: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/services/change_service.py backend/tests/conftest.py backend/tests/test_assessment_impact_gate.py
git commit -m "feat(changes): hard-gate assessment behind a locked impacted set

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Recall path — `in_assessment -> scoping` with teardown

Adds the transition, a hard precondition (recall only while no assessment work has started), and a teardown that removes the spawned assessments + routing + workflow instance so a corrected set rebuilds cleanly.

**Files:**
- Modify: `backend/app/services/change_service.py` (`ALLOWED_TRANSITIONS` line 48; hard precondition + teardown side-effect in `transition()`)
- Modify: `backend/app/services/change_routing_service.py` (add `teardown_routing`)
- Test: `backend/tests/test_assessment_recall.py` (new)

**Interfaces:**
- Consumes: `ChangeRoutingService.build_routing` (idempotent on `ChangeRouting` existence — `change_routing_service.py:122`), `WfInstance.change_id`, `ChangeAssessment.wf_instance_task_id`, `ChangeAssessment.verdict`, `ChangeAssessment.effective_status`.
- Produces: `ChangeRoutingService.teardown_routing(session, change, user_id)`; `in_assessment -> scoping` transition.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_assessment_recall.py`:

```python
"""A change in in_assessment can be recalled to scoping to fix a flawed
impacted set — but only while no assessment work has started. Recall tears
down the spawned assessments + routing so a corrected set rebuilds cleanly."""
import pytest

from tests.conftest import advance_to_assessment
from tests.test_changes import departments  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _in_assessment(client, auth, seed, session_factory, part):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "recall test",
        "change_type": "physical_part", "lead_id": seed["engineer_id"],
    }, headers=auth)
    cid = res.json()["id"]
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part["part_id"], "is_lead": True}, headers=auth)
    await advance_to_assessment(client, auth, session_factory, cid)
    return cid


async def test_recall_tears_down_assessments(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _in_assessment(client, admin_auth, seed, session_factory, part)
    before = await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
    assert len(before.json()["assessments"]) > 0

    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "scoping"

    after = await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
    assert after.json()["assessments"] == []


async def test_recall_refused_after_assessment_submitted(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _in_assessment(client, admin_auth, seed, session_factory, part)
    a = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
         ).json()["assessments"][0]
    await client.post(f"/api/v1/changes/{cid}/assessments",
                      json={"department_id": a["department_id"], "verdict": "feasible"},
                      headers=admin_auth)

    blocked = await client.post(f"/api/v1/changes/{cid}/transition",
                                json={"to_status": "scoping"}, headers=admin_auth)
    assert blocked.status_code == 400, blocked.text
    assert "started" in blocked.json()["detail"].lower()


async def test_recall_then_resubmit_rebuilds_routing(
        client, admin_auth, seed, departments, session_factory, part):
    cid = await _in_assessment(client, admin_auth, seed, session_factory, part)
    await client.post(f"/api/v1/changes/{cid}/transition",
                      json={"to_status": "scoping"}, headers=admin_auth)
    # impact lock, deadline, and proceed meeting persist across recall — re-submit
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "in_assessment"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    after = await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)
    assert len(after.json()["assessments"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_assessment_recall.py -v`
Expected: FAIL — `in_assessment -> scoping` is not an allowed transition (`Cannot move from 'in_assessment' to 'scoping'`).

- [ ] **Step 3: Allow the transition**

In `backend/app/services/change_service.py`, line 48, add `"scoping"` to the `in_assessment` target set:

```python
    "in_assessment":     {"scoping", "costing", "rejected", "cancelled", "on_hold"},
```

- [ ] **Step 4: Add the `teardown_routing` method**

In `backend/app/services/change_routing_service.py`, add this static method to `ChangeRoutingService` (place it after `build_routing`):

```python
    @staticmethod
    async def teardown_routing(session: AsyncSession, change: ChangeRequest,
                               user_id: int) -> None:
        """Remove all assessment scaffolding built on entry to assessment, so a
        corrected impacted set rebuilds cleanly on re-submit. Caller must ensure
        no assessment work has started."""
        from app.models.workflow import WfInstance
        assessments = (await session.execute(
            select(ChangeAssessment).where(ChangeAssessment.change_id == change.id)
        )).scalars().all()
        for a in assessments:
            a.wf_instance_task_id = None      # break FK before task rows go
        await session.flush()
        for a in assessments:
            await session.delete(a)
        instances = (await session.execute(
            select(WfInstance).where(WfInstance.change_id == change.id)
        )).scalars().all()
        for inst in instances:
            await session.delete(inst)        # cascade deletes its WfInstanceTasks
        routing = (await session.execute(
            select(ChangeRouting).where(ChangeRouting.change_id == change.id)
        )).scalar_one_or_none()
        if routing is not None:
            await session.delete(routing)
        await session.flush()
```

- [ ] **Step 5: Add the recall precondition + teardown side-effect in `transition()`**

In `backend/app/services/change_service.py`, add the hard precondition alongside the other hard gates (right after the Task-1 `in_assessment` hard gate you added):

```python
        # HARD precondition: recall (in_assessment -> scoping) is a correction for
        # a premature submit, not a silent undo of real work. Allowed only while no
        # assessment has been submitted or carries a non-pending verdict.
        if change.status == "in_assessment" and to_status == "scoping":
            started = [a for a in change.assessments
                       if a.verdict != "pending" or a.effective_status == "submitted"]
            if started:
                raise ChangeError(
                    "Cannot recall: assessment work has already started")
```

Then in the "Side effects on entry" block (~lines 605-613, BEFORE `old = change.status`), add the teardown — at this point `change.status` still holds the from-status:

```python
        # Side effects on entry
        if to_status == "scoping" and change.status == "in_assessment":
            from app.services.change_routing_service import ChangeRoutingService
            await ChangeRoutingService.teardown_routing(session, change, user_id)
        if to_status == "in_assessment":
            await ChangeService.ensure_assessments(session, change, user_id)
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_assessment_recall.py -v`
Expected: PASS.

Run: `cd backend && pytest tests/test_change_routing.py tests/test_change_scoped_instances.py -q`
Expected: PASS (no regression in routing/instance behavior).

- [ ] **Step 7: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/services/change_service.py backend/app/services/change_routing_service.py backend/tests/test_assessment_recall.py
git commit -m "feat(changes): recall from assessment to scoping with routing teardown

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Surface the lock as the scoping next-action

Moves the `impact_confirm` next-action from `approved` to `scoping`, so locking is the prominent step standing between the change and assessment.

**Files:**
- Modify: `backend/app/services/change_service.py` (`my_actions`, the `impact_confirm` block at lines 1057-1066)
- Test: `backend/tests/test_assessment_impact_gate.py` (append)

**Interfaces:**
- Consumes: `GET /api/v1/changes/{id}/my-actions` (returns the action list from `ChangeService.my_actions`), `ChangeService.user_can_confirm_impact`.
- Produces: an `impact_confirm` action (`target_tab: "impacted"`) offered during `scoping`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_assessment_impact_gate.py`:

```python
from tests.test_impact_confirmation import rd_member_auth  # noqa: F401,E402


async def test_scoping_surfaces_lock_action_for_rd(
        client, admin_auth, rd_member_auth, seed, session_factory, part):
    cid = await _scoping_ready(client, admin_auth, seed, session_factory, part)
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                             headers=rd_member_auth["auth"])).json()
    assert any(a["kind"] == "impact_confirm" for a in acts), acts

    # once locked, the action is gone
    await client.post(f"/api/v1/changes/{cid}/impact/confirm",
                      headers=rd_member_auth["auth"])
    acts2 = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                              headers=rd_member_auth["auth"])).json()
    assert not any(a["kind"] == "impact_confirm" for a in acts2), acts2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_assessment_impact_gate.py::test_scoping_surfaces_lock_action_for_rd -v`
Expected: FAIL — the action is currently only offered at status `approved`, so the first assertion fails (empty of `impact_confirm`).

- [ ] **Step 3: Move the action to `scoping`**

In `backend/app/services/change_service.py`, replace the `impact_confirm` block (lines 1057-1066) with:

```python
        # kind "impact_confirm": scoping & impacted items exist & not yet locked,
        # and this user may confirm it. Locking is the step that unblocks
        # assessment (see the -> in_assessment hard gate in transition()).
        if (change.status == "scoping" and change.impact_confirmed_at is None
                and change.impacted_items
                and await ChangeService.user_can_confirm_impact(session, user)):
            actions.append({
                "kind": "impact_confirm",
                "label": "Confirm impacted items",
                "target_tab": "impacted",
            })
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/test_assessment_impact_gate.py tests/test_my_actions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add backend/app/services/change_service.py backend/tests/test_assessment_impact_gate.py
git commit -m "feat(changes): surface impact-lock as the scoping next-action

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Frontend — show the impact-lock blocker during scoping

`CockpitSummary` currently flags the unlocked impacted set as a blocker only at status `approved`. Fire it during `scoping` so it reads as the thing blocking assessment. The `impact_confirm` action button already flows automatically from Task 3 via the `actions` prop.

**Files:**
- Modify: `frontend/src/components/changes/CockpitSummary.tsx:48`
- Test: `frontend/src/components/changes/CockpitSummary.test.tsx` (append)

**Interfaces:**
- Consumes: `ChangeDetail.status`, `ChangeDetail.impact_confirmed_at`, `ChangeDetail.impacted_items`.
- Produces: the `impactUnconfirmed` blocker rendering during `scoping`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/changes/CockpitSummary.test.tsx` (inside the `describe('CockpitSummary', ...)` block):

```typescript
  it('flags an unlocked impacted set as a blocker during scoping', () => {
    render(wrap(<CockpitSummary
      change={change({
        status: 'scoping',
        impact_confirmed_at: null,
        impacted_items: [{ id: 1, part_id: 9 }] as ChangeDetail['impacted_items'],
      })}
      gates={[]} pendingDeviations={0}
      onAdvance={vi.fn()} advancing={false} />))
    expect(screen.getByText(/impact/i)).toBeDefined()
    expect(screen.queryByText(/nothing/i)).toBeNull()
  })

  it('does not flag impact lock during scoping when no impacted items exist', () => {
    render(wrap(<CockpitSummary
      change={change({ status: 'scoping', impact_confirmed_at: null, impacted_items: [] })}
      gates={[]} pendingDeviations={0}
      onAdvance={vi.fn()} advancing={false} />))
    expect(screen.queryByText(/nothing/i)).not.toBeNull()
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- CockpitSummary`
Expected: the first new test FAILS — at `scoping` the current condition (`status === 'approved'`) is false, so no impact blocker renders and "nothing blocking" shows.

- [ ] **Step 3: Update the blocker condition**

In `frontend/src/components/changes/CockpitSummary.tsx`, replace line 48:

```typescript
  const impactUnconfirmed = change.status === 'approved' && !change.impact_confirmed_at
```

with:

```typescript
  // Blocks two transitions on the same signal: entering assessment (from scoping,
  // hard-gated) and kickoff (from approved, soft-guarded). Only meaningful once
  // there is an impacted set to lock.
  const impactUnconfirmed = !change.impact_confirmed_at
    && (change.impacted_items?.length ?? 0) > 0
    && (change.status === 'scoping' || change.status === 'approved')
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test -- CockpitSummary`
Expected: PASS (new tests + existing ones).

- [ ] **Step 5: Commit**

```bash
cd /home/nitrolinux/claude/plm2
git add frontend/src/components/changes/CockpitSummary.tsx frontend/src/components/changes/CockpitSummary.test.tsx
git commit -m "feat(changes): flag unlocked impacted set as a scoping blocker

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Data fix — recall the live CR-2026-0002

CR-2026-0002 "Add Support pads" sits in `in_assessment` with an unlocked impacted set (9 pending assessments + routing 116) in the live Postgres. Recall it through the new endpoint so the user can fix + lock + re-submit.

**Files:** none (operational).

**Interfaces:** Consumes the `POST /api/v1/changes/{id}/transition` recall added in Task 2, applied to the running backend.

- [ ] **Step 1: Confirm current live state**

Run:
```bash
docker exec claude-plm2-db-1 psql -U plm -d plm -c \
"select id, change_number, status, impact_confirmed_at is not null as locked from change_requests where id=2;" \
-c "select count(*) as assessments from change_assessments where change_id=2;"
```
Expected: `status = in_assessment`, `locked = f`, assessments = 9. (If any assessment has a non-pending verdict, STOP — recall will be refused by design; report back to the user instead of forcing it.)

- [ ] **Step 2: Recall via the API (through the running backend)**

The recall must run through `transition()` so teardown fires — do NOT hand-edit the DB. Use the backend container with an authenticated admin call. Confirm the exact invocation with the user (auth cookie / admin user), then run the transition `POST /api/v1/changes/2/transition {"to_status": "scoping"}` against the live backend (`claude-plm2-backend-1`, port 8000).

- [ ] **Step 3: Verify the recall**

Run:
```bash
docker exec claude-plm2-db-1 psql -U plm -d plm -c \
"select id, status from change_requests where id=2;" \
-c "select count(*) as assessments from change_assessments where change_id=2;" \
-c "select count(*) as routings from change_routings where change_id=2;"
```
Expected: `status = scoping`, assessments = 0, routings = 0.

- [ ] **Step 4: Hand back to the user**

Report: CR-2026-0002 is back in `scoping` with assessment scaffolding cleared. Next steps are theirs — fix the impacted set (editing it auto-clears any lock), have R&D lock it, then re-submit to assessment through the new hard gate.

---

## Self-Review

**Spec coverage:**
- Hard gate before assessment (spec §1) → Task 1. ✓ Placed in `transition()`, not `_guard`; deviation-bypass test included.
- Recall `in_assessment -> scoping` with pending-only precondition + teardown (spec §2) → Task 2. ✓
- Surface lock as scoping next-action (spec §3) → Task 3 (backend) + Task 4 (frontend prominence). ✓
- CR-2026-0002 data fix (spec §4) → Task 5. ✓
- Non-goal: actor for locking unchanged → no task touches `user_can_confirm_impact`. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code. ✓

**Type consistency:** `teardown_routing(session, change, user_id)` defined in Task 2 and called in Task 2's `transition()` edit with the same signature. `lock_impact(session_factory, change_id, actor_id=1)` defined and called in Task 1. `impact_confirm` action shape (`kind`/`label`/`target_tab`) matches the existing `NextAction` type (`frontend/src/types/change.ts:211`). `impactUnconfirmed` remains a boolean used unchanged at lines 49-50 and 128. ✓
