# Assessment Checklist Answers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every assessment checklist row is answered No/Yes before a department can submit, and any answered row can raise a risk flag in place.

**Architecture:** The keyed checklist JSON in `ChangeAssessment.details.impacts` gains an `answer` field. The backend refuses a submit whose checklist is incomplete and normalises `impacted` from `answer`, so costing is untouched. `change_concerns` gets a nullable `checklist_key`, and a small row-level risk form posts it. The frontend shares the concerns query cache (`['change', id, 'concerns']`) between the ConcernStrip, the checklist rows and the bucket chip.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (Postgres prod, SQLite in tests), React 18 + TanStack Query + Vitest/Testing Library, Tailwind.

**Spec:** `docs/superpowers/specs/2026-09-24-assessment-checklist-answers-design.md`

## Global Constraints

- Work in worktree `/home/nitrolinux/claude/plm2-integ`, branch `integrate/dfm-redesign`. It has unrelated uncommitted worksheet edits; **never stage them**. Always `git add` explicit paths.
- Answers are exactly `"yes"` / `"no"`. There is no third state.
- No "all No" bulk action anywhere.
- `impacted` must always equal `answer == "yes"` in stored JSON.
- A submit whose `details.impacted is False` (questionnaire "not impacted") is exempt from the completeness gate.
- A submit without `details`, or whose `impacts` contain only legacy rows (no `key`), keeps today's behaviour.
- `checklist_key`: `VARCHAR(120)`, nullable, only for `kind='risk'`, value is a checklist key of the concern's department or `free:<label>`.
- Migration number **085** (`down_revision = "084"`).
- Backend tests: `cd backend && uv run --no-sync pytest <path> -q`. Frontend: `cd frontend && npx vitest run <path>`; typecheck `npx tsc --noEmit -p .`.
- UI copy is bilingual via `frontend/src/i18n/cmLabels.ts` (`{ de, en }`).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Packaging flips its questionnaire from "not impacted" back to "impacted".** `PackagingAssessmentFields` replaces details with `{ impacted: false }`, so the checklist comes back empty. The gate must then read "0 of N" and hold the submit, not carry a stale "done". Test in Task 5.
2. **A free line whose label contains a colon or is very long.** The `free:<label>` key must round-trip and stay ≤120 chars. The backend refuses longer keys and the frontend truncates the key, not the label. Tests in Task 1 and Task 4.
3. **Raising a checklist risk, then withdrawing it in the ConcernStrip.** The row must show ⚑ again (open risks only). Test in Task 4.
4. **Resubmitting an old assessment whose details only have legacy activity rows.** It must not be refused as incomplete. Test in Task 2.
5. **An API client sending `answer: "yes"` with `impacted: false`.** The server stores `impacted: true`, and costing seeds from it. Test in Task 2.

---

### Task 1: `checklist_key` on risk concerns (backend)

**Files:**
- Create: `backend/alembic/versions/085_concern_checklist_key.py`
- Modify: `backend/app/models/change.py` (class `ChangeConcern`, after `severity` ~line 768)
- Modify: `backend/app/schemas/change.py:871-882` (`ConcernCreate`), `:936-960` (`ConcernResponse`)
- Modify: `backend/app/services/meeting_service.py:171-275` (`raise_concern`)
- Modify: `backend/app/api/v1/changes/changes.py:2142-2158` (`raise_concern` route)
- Test: `backend/tests/test_concern_checklist_key.py` (new)

**Interfaces:**
- Produces: `ChangeConcern.checklist_key: str | None`; `ConcernCreate.checklist_key: Optional[str]`; `ConcernResponse.checklist_key: Optional[str]`; `MeetingService.raise_concern(..., checklist_key: Optional[str] = None)`.

- [ ] **Step 1: Write the failing tests**

```python
"""A risk raised from a checklist row remembers which row it came from."""
import pytest

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ctx(session_factory, seed):
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        change = ChangeRequest(
            change_number="C-CK-1", title="ck", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=dept.id, stage_order=1))
        await s.commit()
        return {"change_id": change.id, "department_id": dept.id}


async def _risk(client, auth, ctx, **over):
    body = {"kind": "risk", "note": "Cooling line clash", "risk_type": "timing",
            "severity": 2, "department_id": ctx["department_id"]}
    body.update(over)
    return await client.post(f"/api/v1/changes/{ctx['change_id']}/concerns",
                             json=body, headers=auth)


async def test_risk_keeps_its_checklist_key(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="threed_change")
    assert res.status_code == 200, res.text
    assert res.json()["checklist_key"] == "threed_change"
    listed = await client.get(f"/api/v1/changes/{ctx['change_id']}/concerns",
                              headers=admin_auth)
    assert listed.json()[0]["checklist_key"] == "threed_change"


async def test_risk_without_key_still_works(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx)
    assert res.status_code == 200, res.text
    assert res.json()["checklist_key"] is None


async def test_unknown_key_is_refused(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="pfmea_update")  # APQP-only
    assert res.status_code == 400
    assert "checklist" in res.json()["detail"].lower()


async def test_free_line_key_is_accepted(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="free:Hot runner: zone 3")
    assert res.status_code == 200, res.text
    assert res.json()["checklist_key"] == "free:Hot runner: zone 3"


async def test_overlong_key_is_refused(client, admin_auth, ctx):
    res = await _risk(client, admin_auth, ctx, checklist_key="free:" + "x" * 200)
    assert res.status_code in (400, 422)
```

Note: `timing` is one of the shared risk types every department gets (`backend/app/services/risk_types.py`); check the key exists there before running and use another shared key if it was renamed.

A test for "checklist_key on a non-risk kind" cannot be reached through `in_assessment` (only risks are allowed there). Cover it at service level in the same file:

```python
async def test_key_only_for_risks(session_factory, ctx, seed):
    from app.services.meeting_service import MeetingService
    from app.services.change_service import ChangeError
    from app.models.user import User
    async with session_factory() as s:
        change = await s.get(ChangeRequest, ctx["change_id"])
        change.status = "scoping"
        await s.flush()
        await s.refresh(change, ["concerns"])
        user = await s.get(User, seed["admin_id"])
        with pytest.raises(ChangeError, match="checklist"):
            await MeetingService.raise_concern(
                s, change, user, "needs_info", "why?", checklist_key="threed_change")
```

Check the `User` import path with `grep -rn "^class User" backend/app/models` and adjust.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run --no-sync pytest tests/test_concern_checklist_key.py -q`
Expected: FAIL (`checklist_key` missing from the response / unexpected keyword).

- [ ] **Step 3: Implement**

Model (`ChangeConcern`, after `severity`):
```python
    # The checklist row a risk was raised from ("threed_change", or
    # "free:<label>" for a department's own line). Lets the row show that it
    # is already flagged. No FK: the checklist lives in code.
    checklist_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
```

Migration `085_concern_checklist_key.py`, following the style of 084:
```python
"""085: checklist_key on change_concerns — the checklist row a risk came from.

Revision ID: 085
Revises: 084
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("change_concerns")}
    if "checklist_key" not in have:
        with op.batch_alter_table("change_concerns") as batch:
            batch.add_column(sa.Column("checklist_key", sa.String(120), nullable=True))


def downgrade() -> None:
    have = {c["name"] for c in inspect(op.get_bind()).get_columns("change_concerns")}
    if "checklist_key" in have:
        with op.batch_alter_table("change_concerns") as batch:
            batch.drop_column("checklist_key")
```

Schemas:
```python
# ConcernCreate
    # Set when the risk is raised from an assessment checklist row.
    checklist_key: Optional[str] = Field(default=None, max_length=120)
# ConcernResponse (next to severity)
    checklist_key: Optional[str] = None
```

Service `raise_concern`: add `checklist_key: Optional[str] = None` to the signature, and add this validation after the `if kind == "risk":` block:
```python
        if checklist_key is not None:
            if kind != "risk":
                raise ChangeError("Only a risk can point at a checklist row")
            if len(checklist_key) > 120:
                raise ChangeError("checklist_key is too long")
            if not checklist_key.startswith("free:"):
                from app.services import assessment_checklist as checklist
                dept_for_keys = (await session.get(Department, department_id)
                                 if department_id is not None else None)
                if checklist_key not in checklist.keys_for(
                        dept_for_keys.name if dept_for_keys else None):
                    raise ChangeError(
                        f"'{checklist_key}' is not a checklist item for this department")
```
Pass `checklist_key=checklist_key` into the `ChangeConcern(...)` constructor, and add `"checklist_key": checklist_key` to the changelog `new_value` dict.

Route: pass `checklist_key=body.checklist_key` into `MeetingService.raise_concern`. Check that the list endpoint builds rows from `ConcernResponse` via `model_validate`/from_attributes; if it builds them by hand, add the field there too.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run --no-sync pytest tests/test_concern_checklist_key.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/085_concern_checklist_key.py backend/app/models/change.py backend/app/schemas/change.py backend/app/services/meeting_service.py backend/app/api/v1/changes/changes.py backend/tests/test_concern_checklist_key.py
git commit -m "feat(cm): risks remember the checklist row they were raised from"
```

---

### Task 2: Completeness gate and `answer` normalisation (backend)

**Files:**
- Modify: `backend/app/services/change_service.py:1987-2040` (`_validate_impacts`)
- Modify: `backend/tests/test_assessment_checklist.py` (existing `_submit` callers)
- Modify: `backend/tests/test_costing_positions.py` (its one `impacts` submit)
- Create: `backend/tests/checklist_helpers.py`
- Test: `backend/tests/test_checklist_answers.py` (new)

**Interfaces:**
- Consumes: `app.services.assessment_checklist.items_for(dept_name) -> list[dict]` (keys `key`, `label_en`).
- Produces: stored `details.impacts[*]` entries always carry `answer` ∈ {"yes","no"} for keyed rows and `impacted == (answer == "yes")`. Refusal text starts with `"Checklist incomplete — unanswered: "`.

- [ ] **Step 1: Test helper**

`backend/tests/checklist_helpers.py`:
```python
"""Build a fully answered checklist, the way the app now sends it."""
from app.services import assessment_checklist as checklist


def answered(dept_name, yes=(), remarks=None, choices=None):
    """Every checklist key for the department, 'yes' for those in `yes`,
    'no' for the rest."""
    remarks = remarks or {}
    choices = choices or {}
    out = []
    for item in checklist.items_for(dept_name):
        k = item["key"]
        e = {"key": k, "answer": "yes" if k in yes else "no", "impacted": k in yes}
        if k in remarks:
            e["remark"] = remarks[k]
        if k in choices:
            e["choice"] = choices[k]
        out.append(e)
    return out
```

- [ ] **Step 2: Write the failing tests** (`backend/tests/test_checklist_answers.py`; reuse the `tab` fixture shape from `test_assessment_checklist.py`, department "Tool Engineer")

```python
"""Every checklist row is answered before a department can submit."""
import json
import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.workflow import Department
from tests.checklist_helpers import answered

pytestmark = pytest.mark.asyncio
DEPT = "Tool Engineer"


@pytest.fixture
async def tab(session_factory, seed):
    async with session_factory() as s:
        dept = Department(name=DEPT, flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        change = ChangeRequest(
            change_number="C-ANS-1", title="answers", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dept.id, stage_order=1)
        s.add(a)
        await s.commit()
        return {"change_id": change.id, "assessment_id": a.id, "department_id": dept.id}


async def _submit(client, auth, tab, details):
    return await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                             json={"department_id": tab["department_id"],
                                   "verdict": "feasible", "details": details},
                             headers=auth)


async def _stored(session_factory, tab):
    async with session_factory() as s:
        a = await s.get(ChangeAssessment, tab["assessment_id"])
        return json.loads(a.details)


async def test_incomplete_checklist_is_refused_naming_the_rows(client, admin_auth, tab):
    impacts = answered(DEPT)[:-2]           # last two rows unanswered
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail.startswith("Checklist incomplete — unanswered: ")
    assert "Prototyping required" in detail and "Matching/sampling required" in detail


async def test_empty_checklist_is_refused(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab, {"impacts": []})
    assert res.status_code == 400


async def test_keyed_row_without_answer_counts_as_unanswered(client, admin_auth, tab):
    impacts = answered(DEPT)
    del impacts[0]["answer"]
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400
    assert "Cycle time change" in res.json()["detail"]


async def test_invalid_answer_is_refused(client, admin_auth, tab):
    impacts = answered(DEPT)
    impacts[0]["answer"] = "maybe"
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 400


async def test_complete_checklist_is_accepted_and_no_rows_are_kept(
        client, admin_auth, tab, session_factory):
    res = await _submit(client, admin_auth, tab,
                        {"impacts": answered(DEPT, yes={"threed_change"})})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    assert len(stored["impacts"]) == 13
    three = next(e for e in stored["impacts"] if e["key"] == "threed_change")
    assert three == {"key": "threed_change", "answer": "yes", "impacted": True}
    assert sum(1 for e in stored["impacts"] if e["answer"] == "no") == 12


async def test_impacted_is_normalised_from_answer(client, admin_auth, tab, session_factory):
    impacts = answered(DEPT)
    impacts[0].update(answer="yes", impacted=False)      # contradicting client
    impacts[1].update(answer="no", impacted=True)
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    assert stored["impacts"][0]["impacted"] is True
    assert stored["impacts"][1]["impacted"] is False


async def test_not_impacted_questionnaire_is_exempt(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        {"impacted": False, "impacts": [answered(DEPT)[0]]})
    assert res.status_code == 200, res.text


async def test_submit_without_details_is_unchanged(client, admin_auth, tab):
    res = await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                            json={"department_id": tab["department_id"],
                                  "verdict": "feasible"}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_legacy_only_rows_are_not_gated(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        {"impacts": [{"label": "Old free line", "impacted": True}]})
    assert res.status_code == 200, res.text


async def test_free_lines_are_yes(client, admin_auth, tab, session_factory):
    impacts = answered(DEPT) + [{"label": "Hot runner: zone 3", "answer": "yes",
                                 "impacted": True}]
    res = await _submit(client, admin_auth, tab, {"impacts": impacts})
    assert res.status_code == 200, res.text
    stored = await _stored(session_factory, tab)
    free = next(e for e in stored["impacts"] if e.get("label") == "Hot runner: zone 3")
    assert free["impacted"] is True and free["answer"] == "yes"
```

Note on the legacy test: the only-legacy case is `impacts` whose entries all lack `key`. A list mixing keyed and legacy rows is gated on its keyed part.

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run --no-sync pytest tests/test_checklist_answers.py -q`
Expected: the incomplete/empty/unanswered/invalid tests FAIL (currently accepted); the normalisation test FAILS.

- [ ] **Step 4: Implement in `_validate_impacts`**

The keyed-row branch currently ends with `continue`. Change the function so that:

```python
        impacts = details.get("impacts")
        if impacts is None:
            return
        if not isinstance(impacts, list):
            raise ChangeError("details.impacts must be a list")
        dept = await session.get(Department, department_id)
        dept_name = dept.name if dept is not None else None
        allowed_keys = checklist.keys_for(dept_name)
        answered: set[str] = set()
        catalog = None
        for entry in impacts:
            if not isinstance(entry, dict):
                raise ChangeError("Each impacts entry must be an object")
            answer = entry.get("answer")
            if answer is not None and answer not in ("yes", "no"):
                raise ChangeError(f"Invalid checklist answer '{answer}' — yes or no")
            key = entry.get("key")
            if key is not None:
                if key not in allowed_keys:
                    raise ChangeError(
                        f"'{key}' is not a checklist item for this department")
                # ... existing choice validation unchanged ...
                if answer is not None:
                    # The answer is the truth; impacted is derived so costing,
                    # the RFQ hint and the cost-task skip keep reading it.
                    entry["impacted"] = answer == "yes"
                    answered.add(key)
                continue
            if answer is not None:
                entry["impacted"] = answer == "yes"
            # ... existing legacy / free-line branch unchanged ...

        # Every row answered — No is an answer, silence is not. Exempt: the
        # department's questionnaire said "not impacted" (the form hides the
        # checklist then), and old submissions made only of legacy rows.
        has_keyed_or_empty = (not impacts) or any(
            isinstance(e, dict) and e.get("key") is not None for e in impacts)
        if details.get("impacted") is not False and has_keyed_or_empty:
            missing = [i["label_en"] for i in checklist.items_for(dept_name)
                       if i["key"] not in answered]
            if missing:
                raise ChangeError(
                    "Checklist incomplete — unanswered: " + ", ".join(missing))
```

`submit_assessment` already runs `json.dumps(details)` after this call, so the normalised `impacted` values are what gets stored. Update the docstring to say rows must all be answered.

- [ ] **Step 5: Update existing tests to send full checklists**

In `backend/tests/test_assessment_checklist.py`, change every `_submit(client, admin_auth, tab, [ ... ])` whose list is keyed rows to use `answered("Tool Engineer", yes={...}, remarks={...}, choices={...})`, keeping the same `yes` keys and remarks the test asserts on. Tests submitting only legacy rows (`test_legacy_rows_are_still_accepted`) and tests about unknown keys or choices (refused before the gate) stay as they are. `test_nothing_checked_seeds_nothing` becomes `answered("Tool Engineer")` (all No). Apply the same to the one keyed submit in `test_costing_positions.py` (use that test's department name). Import: `from tests.checklist_helpers import answered`. If `tests` isn't importable as a package, check how other tests share helpers (`grep -rn "^from tests\." backend/tests | head`) and follow that; if nobody does it, put `answered` in `backend/tests/conftest.py` as a plain function and import it with `from conftest import answered`.

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run --no-sync pytest tests/test_checklist_answers.py tests/test_assessment_checklist.py tests/test_costing_positions.py -q`
Expected: PASS.
Then the whole suite: `cd backend && uv run --no-sync pytest -q -x -p no:cacheprovider`. Expected: all pass. Fix any other test that submits keyed `impacts` partially, the same way as Step 5.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/change_service.py backend/tests/checklist_helpers.py backend/tests/test_checklist_answers.py backend/tests/test_assessment_checklist.py backend/tests/test_costing_positions.py
git commit -m "feat(cm): assessment submit refused until every checklist row is answered"
```

---

### Task 3: No/Yes rows in the checklist (frontend)

**Files:**
- Modify: `frontend/src/types/change.ts:644-671` (`ChangeConcern`)
- Modify: `frontend/src/api/changes.ts:253-256` (`raiseConcern` body)
- Modify: `frontend/src/components/changes/departmentForms/ActivityChecklist.tsx`
- Modify: `frontend/src/i18n/cmLabels.ts` (near `check.*`, line ~383)
- Test: `frontend/src/components/changes/departmentForms/ActivityChecklist.test.tsx` (new)

**Interfaces:**
- Produces:
  - `ImpactItem.answer?: 'yes' | 'no'`
  - `export function checklistProgress(defs: ChecklistItemDef[], value: Record<string, unknown> | null | undefined): { answered: number; total: number; firstOpen: string | null }`, counting only keyed defs
  - row DOM ids `check-row-${key}`
  - test ids `check-yes-${id}`, `check-no-${id}`
  - prop `highlightOpen?: boolean`
  - `ChangeConcern.checklist_key?: string | null`
  - `raiseConcern` body accepts `checklist_key?: string`

- [ ] **Step 1: Types, API and labels**

`ChangeConcern`: add
```ts
  /** Risk raised from a checklist row: that row's key (or free:<label>). */
  checklist_key?: string | null;
```
`raiseConcern` body type: add `checklist_key?: string;`.

cmLabels (next to `check.title`):
```ts
  'check.yes': { de: 'Ja', en: 'Yes' },
  'check.no': { de: 'Nein', en: 'No' },
  'check.progress': { de: '{n} von {m} beantwortet', en: '{n} of {m} answered' },
  'check.openRows': { de: '{n} Punkte offen', en: '{n} rows unanswered' },
  'check.noCount': { de: '{n} × Nein', en: '{n} × No' },
  'check.summary': { de: '{n} betroffen · {k} Risiken', en: '{n} impacted · {k} risks flagged' },
  'check.flagRisk': { de: '⚑ Risiko melden', en: '⚑ Flag risk' },
  'check.riskFlagged': { de: '⚑ Risiko gemeldet (Sev {s})', en: '⚑ risk flagged (sev {s})' },
```
Change `check.hint` to:
```ts
  'check.hint': {
    de: 'Jede Zeile mit Ja oder Nein beantworten. Ja wird in der Kostenerfassung '
      + 'vorbelegt; wer ein Risiko sieht, meldet es direkt an der Zeile.',
    en: 'Answer every row Yes or No. Yes is pre-seeded into cost input; if you '
      + 'see a risk, flag it right on the row.',
  },
```

- [ ] **Step 2: Write the failing tests**

```tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ActivityChecklist, { checklistProgress } from './ActivityChecklist'

const DEFS = [
  { key: 'cycle_time_change', label_de: 'Zykluszeit', label_en: 'Cycle time change', extra: false },
  { key: 'threed_change', label_de: '3D', label_en: '3D change necessary', extra: false },
]
vi.mock('../../../api/changes', () => ({
  changesApi: {
    assessmentChecklist: vi.fn(() => Promise.resolve(DEFS)),
    listConcerns: vi.fn(() => Promise.resolve([])),
  },
}))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('checklistProgress', () => {
  it('counts answered keyed rows and names the first open one', () => {
    expect(checklistProgress(DEFS, { impacts: [
      { key: 'threed_change', answer: 'no', impacted: false }] }))
      .toEqual({ answered: 1, total: 2, firstOpen: 'cycle_time_change' })
    expect(checklistProgress(DEFS, { impacts: [
      { key: 'cycle_time_change', answer: 'yes', impacted: true },
      { key: 'threed_change', answer: 'no', impacted: false }] }))
      .toEqual({ answered: 2, total: 2, firstOpen: null })
  })
  it('does not count a legacy tick without an answer', () => {
    expect(checklistProgress(DEFS, { impacts: [
      { key: 'threed_change', impacted: true }] }).answered).toBe(0)
  })
})

describe('ActivityChecklist answers', () => {
  afterEach(cleanup)

  it('starts with nothing selected and no bulk No', async () => {
    render(wrap(<ActivityChecklist departmentId={2} value={{}} onChange={() => {}} />))
    const yes = await screen.findByTestId('check-yes-threed_change')
    expect(yes.getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByTestId('check-no-threed_change').getAttribute('aria-pressed')).toBe('false')
    expect(screen.queryByText(/all no/i)).toBeNull()
  })

  it('No is stored as an answer, not dropped', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} value={{}} onChange={onChange} />))
    fireEvent.click(await screen.findByTestId('check-no-threed_change'))
    expect(onChange).toHaveBeenCalledWith({ impacts: [
      { key: 'threed_change', answer: 'no', impacted: false }] })
  })

  it('Yes marks impacted and opens the remark', async () => {
    const onChange = vi.fn()
    const { rerender } = render(wrap(
      <ActivityChecklist departmentId={2} value={{}} onChange={onChange} />))
    fireEvent.click(await screen.findByTestId('check-yes-threed_change'))
    const next = onChange.mock.calls[0][0]
    expect(next.impacts[0]).toMatchObject({ key: 'threed_change', answer: 'yes', impacted: true })
    rerender(wrap(<ActivityChecklist departmentId={2} value={next} onChange={onChange} />))
    expect(screen.getByTestId('check-remark-threed_change')).toBeTruthy()
  })

  it('switching Yes to No clears the choice', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} onChange={onChange}
      value={{ impacts: [{ key: 'threed_change', answer: 'yes', impacted: true, choice: 'internal' }] }} />))
    fireEvent.click(await screen.findByTestId('check-no-threed_change'))
    const row = onChange.mock.calls[0][0].impacts.find((i: { key: string }) => i.key === 'threed_change')
    expect(row).toEqual({ key: 'threed_change', answer: 'no', impacted: false })
  })

  it('highlights unanswered rows when asked', async () => {
    render(wrap(<ActivityChecklist departmentId={2} highlightOpen onChange={() => {}}
      value={{ impacts: [{ key: 'threed_change', answer: 'no', impacted: false }] }} />))
    await waitFor(() => expect(document.getElementById('check-row-cycle_time_change')
      ?.getAttribute('data-open')).toBe('true'))
    expect(document.getElementById('check-row-threed_change')?.getAttribute('data-open')).toBe('false')
  })

  it('a new free line is answered Yes', async () => {
    const onChange = vi.fn()
    render(wrap(<ActivityChecklist departmentId={2} value={{}} onChange={onChange} />))
    fireEvent.click(await screen.findByTestId('check-add-item'))
    const input = screen.getByTestId('check-free-input-0')
    fireEvent.blur(input, { target: { value: 'Hot runner: zone 3' } })
    expect(onChange).toHaveBeenLastCalledWith({ impacts: [
      { label: 'Hot runner: zone 3', answer: 'yes', impacted: true }] })
  })
})
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/changes/departmentForms/ActivityChecklist.test.tsx`
Expected: FAIL (`checklistProgress` not exported, no `check-yes-*`).

- [ ] **Step 4: Implement**

In `ActivityChecklist.tsx`:

1. `ImpactItem`: add `answer?: 'yes' | 'no'`.
2. Export the progress helper:
```ts
/** How far the department has got: keyed rows only (free lines are always Yes). */
export function checklistProgress(
  defs: ChecklistItemDef[], value: Record<string, unknown> | null | undefined,
): { answered: number; total: number; firstOpen: string | null } {
  const byKey = new Map(impactsOf(value).filter((i) => i.key).map((i) => [i.key!, i]))
  const open = defs.filter((d) => !byKey.get(d.key)?.answer)
  return { answered: defs.length - open.length, total: defs.length,
           firstOpen: open[0]?.key ?? null }
}
```
3. `put` keeps answered rows:
```ts
    const kept = [...rest, next].filter(
      (i) => isLegacy(i) || i.answer !== undefined || i.impacted
        || (i.remark ?? '').trim() !== '')
```
4. `answer` setter inside `row`:
```ts
    const setAnswer = (answer: 'yes' | 'no') => put(answer === 'yes'
      ? { ...item, answer, impacted: true }
      : { key: item.key, label: item.label, answer, impacted: false })
```
For keyed rows the No branch must not carry `label: undefined` into the object, because the test compares with `toEqual`. Build it as `{ ...(item.key ? { key: item.key } : { label: item.label }), answer, impacted: false }`.
5. Replace the checkbox `<label>` with:
```tsx
        <div className="flex items-center gap-2 text-sm">
          <span role="group" aria-label={label} className="flex rounded border border-slate-600 overflow-hidden flex-shrink-0">
            {(['no', 'yes'] as const).map((ans) => (
              <button key={ans} type="button" data-testid={`check-${ans}-${id}`}
                aria-pressed={item.answer === ans}
                onClick={() => setAnswer(ans)}
                className={`px-2 py-0.5 text-xs ${item.answer === ans
                  ? (ans === 'yes' ? 'bg-sky-700 text-white' : 'bg-slate-600 text-slate-100')
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
                {t(`check.${ans}`, lang)}
              </button>
            ))}
          </span>
          <span className={item.answer === 'yes' ? 'text-slate-100'
            : item.answer === 'no' ? 'text-slate-500' : 'text-slate-300'}>{label}</span>
        </div>
```
   Answer lookup: `answerFor` stays. The Yes-expanded block keeps its condition `item.impacted`.
6. `<li>` gets `id={`check-row-${id}`}`, `data-open={String(open)}` where `const open = !item.answer && !id.startsWith('free:')`, and when `highlightOpen && open` the class `border-l-2 border-amber-500 pl-2`.
7. Free line creation: `put({ label: v, answer: 'yes', impacted: true })`.
8. Add prop `highlightOpen?: boolean` to the props type.

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/changes/departmentForms/ActivityChecklist.test.tsx src/components/changes/AssessmentBuckets.test.tsx`
Expected: PASS. If an AssessmentBuckets test clicks the old `check-${key}` checkbox, switch it to `check-yes-${key}`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/change.ts frontend/src/api/changes.ts frontend/src/components/changes/departmentForms/ActivityChecklist.tsx frontend/src/components/changes/departmentForms/ActivityChecklist.test.tsx frontend/src/i18n/cmLabels.ts
git commit -m "feat(cm): checklist rows answered No or Yes, No kept as an answer"
```

---

### Task 4: ⚑ Flag risk on a checklist row (frontend)

**Files:**
- Create: `frontend/src/components/changes/departmentForms/ChecklistRiskForm.tsx`
- Modify: `frontend/src/components/changes/departmentForms/ActivityChecklist.tsx`
- Test: `frontend/src/components/changes/departmentForms/ChecklistRiskForm.test.tsx` (new); extend `ActivityChecklist.test.tsx`

**Interfaces:**
- Consumes: `changesApi.riskTypes(departmentId)` → `{ items: { key; label_de?; label_en? }[] }`; `changesApi.raiseConcern(changeId, { kind: 'risk', note, department_id, risk_type, severity, checklist_key })`; `changesApi.listConcerns(changeId)`; `ChangeConcern.checklist_key`.
- Produces: `ChecklistRiskForm({ changeId, departmentId, checklistKey, defaultNote, onDone })`; test ids `check-flag-${id}`, `check-flagged-${id}`, `check-risk-type`, `check-risk-sev-${1|2|3}`, `check-risk-note`, `check-risk-submit`.

- [ ] **Step 1: Write the failing tests**

`ChecklistRiskForm.test.tsx`:
```tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ChecklistRiskForm from './ChecklistRiskForm'

const raiseConcern = vi.fn().mockResolvedValue({ id: 1 })
vi.mock('../../../api/changes', () => ({
  changesApi: {
    riskTypes: vi.fn(() => Promise.resolve({ items: [
      { key: 'timing', label_en: 'Timing' }, { key: 'd4_cooling', label_en: 'Cooling' }] })),
    raiseConcern: (...a: unknown[]) => raiseConcern(...a),
  },
}))
const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
)

describe('ChecklistRiskForm', () => {
  afterEach(cleanup)

  it('is pre-filled from the row and posts its checklist key', async () => {
    const onDone = vi.fn()
    render(wrap(<ChecklistRiskForm changeId={5} departmentId={4}
      checklistKey="threed_change" defaultNote="3D change necessary — gate moves"
      onDone={onDone} />))
    expect((screen.getByTestId('check-risk-note') as HTMLTextAreaElement).value)
      .toBe('3D change necessary — gate moves')
    const submit = screen.getByTestId('check-risk-submit') as HTMLButtonElement
    expect(submit.disabled).toBe(true)                  // type is a deliberate pick
    await screen.findByRole('option', { name: 'Cooling' })
    fireEvent.change(screen.getByTestId('check-risk-type'), { target: { value: 'd4_cooling' } })
    fireEvent.click(screen.getByTestId('check-risk-sev-3'))
    fireEvent.click(submit)
    await waitFor(() => expect(raiseConcern).toHaveBeenCalledWith(5, {
      kind: 'risk', note: '3D change necessary — gate moves', department_id: 4,
      risk_type: 'd4_cooling', severity: 3, checklist_key: 'threed_change' }))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
  })

  it('shows a refusal in place and keeps the note', async () => {
    raiseConcern.mockRejectedValueOnce({ response: { data: { detail: 'nope' } } })
    render(wrap(<ChecklistRiskForm changeId={5} departmentId={4}
      checklistKey="threed_change" defaultNote="x" onDone={() => {}} />))
    await screen.findByRole('option', { name: 'Timing' })
    fireEvent.change(screen.getByTestId('check-risk-type'), { target: { value: 'timing' } })
    fireEvent.click(screen.getByTestId('check-risk-submit'))
    expect((await screen.findByRole('alert')).textContent).toContain('nope')
    expect((screen.getByTestId('check-risk-note') as HTMLTextAreaElement).value).toBe('x')
  })
})
```

Extend `ActivityChecklist.test.tsx`. Change its import to `import ActivityChecklist, { checklistProgress, riskKeyOf } from './ActivityChecklist'`. Make the mocked `listConcerns` controllable with `const listConcerns = vi.fn(() => Promise.resolve([] as unknown[]))` referenced in the mock factory, and add `riskTypes`/`raiseConcern` stubs. Then:
```tsx
describe('ActivityChecklist risk flag', () => {
  afterEach(cleanup)
  const answeredNo = { impacts: [{ key: 'threed_change', answer: 'no', impacted: false }] }

  it('offers ⚑ on an answered row, not on an open one', async () => {
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} value={answeredNo} onChange={() => {}} />))
    expect(await screen.findByTestId('check-flag-threed_change')).toBeTruthy()
    expect(screen.queryByTestId('check-flag-cycle_time_change')).toBeNull()
  })

  it('shows the row as flagged while its risk is open, and ⚑ again once withdrawn', async () => {
    listConcerns.mockResolvedValueOnce([{ id: 9, kind: 'risk', is_open: true, department_id: 4,
      checklist_key: 'threed_change', severity: 3 }])
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} value={answeredNo} onChange={() => {}} />))
    expect((await screen.findByTestId('check-flagged-threed_change')).textContent).toContain('3')
    cleanup()
    listConcerns.mockResolvedValueOnce([{ id: 9, kind: 'risk', is_open: false, department_id: 4,
      checklist_key: 'threed_change', severity: 3 }])
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} value={answeredNo} onChange={() => {}} />))
    expect(await screen.findByTestId('check-flag-threed_change')).toBeTruthy()
  })

  it('ignores another department\'s risk on the same key', async () => {
    listConcerns.mockResolvedValueOnce([{ id: 9, kind: 'risk', is_open: true, department_id: 7,
      checklist_key: 'threed_change', severity: 2 }])
    render(wrap(<ActivityChecklist departmentId={4} changeId={5} value={answeredNo} onChange={() => {}} />))
    expect(await screen.findByTestId('check-flag-threed_change')).toBeTruthy()
  })

  it('a long free line gets a key capped at 120 chars', () => {
    expect(riskKeyOf(`free:${'L'.repeat(200)}`)).toHaveLength(120)
    expect(riskKeyOf('free:Hot runner: zone 3')).toBe('free:Hot runner: zone 3')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/changes/departmentForms/`
Expected: FAIL (module `./ChecklistRiskForm` missing, no `check-flag-*`).

- [ ] **Step 3: Implement `ChecklistRiskForm.tsx`**

```tsx
/**
 * The risk form, opened from a checklist row: the row already says what the
 * risk is about, so the note starts from it. Type and severity stay a
 * deliberate pick, as in the department's risk strip.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import type { RiskSeverity, RiskType } from '../../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const SEVERITIES: RiskSeverity[] = [1, 2, 3]

export default function ChecklistRiskForm({ changeId, departmentId, checklistKey, defaultNote, onDone }: {
  changeId: number; departmentId: number; checklistKey: string; defaultNote: string
  onDone: () => void
}) {
  const qc = useQueryClient()
  const [riskType, setRiskType] = useState('')
  const [severity, setSeverity] = useState<RiskSeverity>(2)
  const [note, setNote] = useState(defaultNote)
  const [failure, setFailure] = useState<string | null>(null)
  const { data } = useQuery({
    queryKey: ['risk-types', departmentId],
    queryFn: () => changesApi.riskTypes(departmentId),
    retry: false,
  })
  const raise = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, {
      kind: 'risk', note: note.trim(), department_id: departmentId,
      risk_type: riskType as RiskType, severity, checklist_key: checklistKey,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      onDone()
    },
    onError: (e: unknown) => setFailure(errDetail(e) ?? 'Could not raise the risk'),
  })
  return (
    <div className="mt-1 ml-6 space-y-1 rounded border border-amber-700/50 bg-amber-950/20 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <select value={riskType} data-testid="check-risk-type" aria-label={t('risk.kind')}
          onChange={(e) => setRiskType(e.target.value)}
          className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
          <option value="">{t('risk.kind')}</option>
          {(data?.items ?? []).map((i) => (
            <option key={i.key} value={i.key}>{i.label_en ?? i.key}</option>
          ))}
        </select>
        <span className="flex items-center gap-1" role="group" aria-label={t('risk.severity')}>
          <span className="text-[11px] text-slate-500 mr-0.5">{t('risk.severity')}</span>
          {SEVERITIES.map((s) => (
            <button key={s} type="button" data-testid={`check-risk-sev-${s}`}
              aria-pressed={severity === s} onClick={() => setSeverity(s)}
              className={`w-7 h-6 rounded border text-xs font-semibold ${severity === s
                ? 'border-amber-500 bg-amber-900 text-amber-100'
                : 'border-slate-600 bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
              {s}
            </button>
          ))}
        </span>
      </div>
      <textarea value={note} rows={2} data-testid="check-risk-note" aria-label={t('risk.note')}
        onChange={(e) => setNote(e.target.value)}
        className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
      {failure && (
        <p role="alert" className="text-xs text-red-300">{failure}</p>
      )}
      <div className="flex gap-2">
        <button type="button" data-testid="check-risk-submit"
          disabled={!riskType || !note.trim() || raise.isPending}
          onClick={() => raise.mutate()}
          className="bg-amber-700 hover:bg-amber-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed">
          {t('check.flagRisk')}
        </button>
        <button type="button" onClick={onDone}
          className="text-xs text-slate-400 hover:text-slate-200 px-1">{t('common.cancel')}</button>
      </div>
    </div>
  )
}
```
Check `RiskSeverity`, `RiskType` and `t('risk.kind' | 'risk.severity' | 'risk.note' | 'common.cancel')` exist (ConcernStrip uses all of them). If the label list for de/en must follow `lang`, pass `lang` through like ActivityChecklist does.

- [ ] **Step 4: Wire into `ActivityChecklist.tsx`**

```tsx
import ChecklistRiskForm from './ChecklistRiskForm'
import type { ChangeConcern } from '../../../types/change'

/** Keys are capped where the backend caps them (change_concerns.checklist_key). */
export const riskKeyOf = (id: string) => id.slice(0, 120)
```
Inside the component:
```tsx
  // Same cache entry as the department's risk strip, so a risk raised or
  // withdrawn in either place shows in both.
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId!),
    enabled: changeId != null,
  })
  const [flagging, setFlagging] = useState<string | null>(null)
  const openRiskFor = (id: string) => (concerns as ChangeConcern[]).find((c) =>
    c.kind === 'risk' && c.is_open && c.department_id === departmentId
    && c.checklist_key === riskKeyOf(id))
```
In `row`, after the Yes/No group on the same line (use `ml-auto`):
```tsx
          {changeId != null && item.answer && (() => {
            const risk = openRiskFor(id)
            return risk ? (
              <span data-testid={`check-flagged-${id}`} className="ml-auto text-[11px] text-amber-300">
                {t('check.riskFlagged', lang).replace('{s}', String(risk.severity ?? '?'))}
              </span>
            ) : (
              <button type="button" data-testid={`check-flag-${id}`}
                onClick={() => setFlagging(id)}
                className="ml-auto text-[11px] text-amber-300/80 hover:text-amber-200">
                {t('check.flagRisk', lang)}
              </button>
            )
          })()}
```
Below the row content:
```tsx
        {flagging === id && changeId != null && (
          <ChecklistRiskForm changeId={changeId} departmentId={departmentId}
            checklistKey={riskKeyOf(id)}
            defaultNote={item.remark?.trim() ? `${label} — ${item.remark.trim()}` : label}
            onDone={() => setFlagging(null)} />
        )}
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/changes/departmentForms/ src/components/changes/AssessmentBuckets.test.tsx src/components/changes/AssessmentSubmitForm.test.tsx`
Expected: PASS. Add `listConcerns: vi.fn().mockResolvedValue([])` to any mock that now lacks it. The AssessmentSubmitForm test doesn't pass `changeId` to the checklist, so the query stays disabled.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/changes/departmentForms/ChecklistRiskForm.tsx frontend/src/components/changes/departmentForms/ChecklistRiskForm.test.tsx frontend/src/components/changes/departmentForms/ActivityChecklist.tsx frontend/src/components/changes/departmentForms/ActivityChecklist.test.tsx
git commit -m "feat(cm): flag a risk straight from a checklist row"
```

---

### Task 5: Progress line and submit gate (frontend)

**Files:**
- Modify: `frontend/src/components/changes/AssessmentSubmitForm.tsx`
- Test: `frontend/src/components/changes/AssessmentSubmitForm.test.tsx`

**Interfaces:**
- Consumes: `checklistProgress` (Task 3), `ActivityChecklist` prop `highlightOpen` (Task 3), row ids `check-row-${key}`, `changesApi.assessmentChecklist(departmentId)` under query key `['assessment-checklist', departmentId]`.
- Produces: test ids `check-progress`, `check-open-jump`.

- [ ] **Step 1: Write the failing tests**

Change the mock at the top of `AssessmentSubmitForm.test.tsx`:
```tsx
const submitAssessment = vi.fn().mockResolvedValue({})
const DEFS = [
  { key: 'cycle_time_change', label_de: 'Z', label_en: 'Cycle time change', extra: false },
  { key: 'threed_change', label_de: '3D', label_en: '3D change necessary', extra: false },
]
const assessmentChecklist = vi.fn(() => Promise.resolve(DEFS))
vi.mock('../../api/changes', () => ({
  changesApi: {
    submitAssessment: (...a: unknown[]) => submitAssessment(...a),
    assessmentChecklist: () => assessmentChecklist(),
    listConcerns: vi.fn().mockResolvedValue([]),
  },
}))
```
Update the existing effort test: before clicking submit, answer both rows with `fireEvent.click(await screen.findByTestId('check-no-cycle_time_change'))` and `fireEvent.click(screen.getByTestId('check-no-threed_change'))`.

New tests:
```tsx
describe('AssessmentSubmitForm checklist gate', () => {
  afterEach(cleanup)
  const form = () => render(wrap(<AssessmentSubmitForm changeId={7} departmentId={2}
    departmentName="Quality" showEffort={false} onDone={() => {}} />))
  const submitBtn = () => screen.getByTestId('assessment-submit') as HTMLButtonElement

  it('counts answers and holds submit until every row is answered', async () => {
    form()
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    expect((await screen.findByTestId('check-progress')).textContent).toContain('0 of 2')
    expect(submitBtn().disabled).toBe(true)
    fireEvent.click(screen.getByTestId('check-no-cycle_time_change'))
    expect(screen.getByTestId('check-progress').textContent).toContain('1 of 2')
    expect(screen.getByTestId('check-open-jump').textContent).toContain('1 rows unanswered')
    fireEvent.click(screen.getByTestId('check-yes-threed_change'))
    expect(submitBtn().disabled).toBe(false)
    fireEvent.click(submitBtn())
    await waitFor(() => expect(submitAssessment).toHaveBeenLastCalledWith(7, expect.objectContaining({
      details: { impacts: expect.arrayContaining([
        { key: 'cycle_time_change', answer: 'no', impacted: false },
        expect.objectContaining({ key: 'threed_change', answer: 'yes', impacted: true }),
      ]) } })))
  })

  it('jumps to the first open row and highlights the open ones', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    form()
    fireEvent.click(await screen.findByTestId('check-no-cycle_time_change'))
    fireEvent.click(screen.getByTestId('check-open-jump'))
    expect(scroll).toHaveBeenCalled()
    expect(document.getElementById('check-row-threed_change')?.className).toContain('border-amber-500')
  })
})
```

Review Focus #1 — Packaging's questionnaire (`pkg-impacted-yes` / `pkg-impacted-no` radios in `PackagingAssessmentFields.tsx`):
```tsx
  it('re-opens an empty checklist gate when Packaging flips back to impacted', async () => {
    render(wrap(<AssessmentSubmitForm changeId={7} departmentId={6}
      departmentName="Packaging Engineer" showEffort={false} onDone={() => {}} />))
    fireEvent.click(await screen.findByTestId('pkg-impacted-yes'))
    fireEvent.click(await screen.findByTestId('check-no-cycle_time_change'))
    fireEvent.click(screen.getByTestId('pkg-impacted-no'))
    expect(submitBtn().disabled).toBe(false)            // not impacted is a full answer
    expect(screen.queryByTestId('check-progress')).toBeNull()
    fireEvent.click(screen.getByTestId('pkg-impacted-yes'))
    expect((await screen.findByTestId('check-progress')).textContent).toContain('0 of 2')
    fireEvent.change(screen.getByLabelText(/verdict/i), { target: { value: 'feasible' } })
    expect(submitBtn().disabled).toBe(true)
  })
```
Put it inside the same `describe` so `submitBtn` is in scope. If the Packaging questionnaire requires further fields before `ready` (see its `pkg-detail` block), the final assertion is still `disabled === true`, which is what matters.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/changes/AssessmentSubmitForm.test.tsx`
Expected: FAIL (no `check-progress`; submit enabled with open rows).

- [ ] **Step 3: Implement**

In `AssessmentSubmitForm.tsx`:
```tsx
import { useQuery } from '@tanstack/react-query'   // merge into the existing import
import ActivityChecklist, { checklistProgress } from './departmentForms/ActivityChecklist'

  // Same query the checklist renders from (shared cache): the form needs the
  // count to hold the submit.
  const { data: defs = [] } = useQuery({
    queryKey: ['assessment-checklist', departmentId],
    queryFn: () => changesApi.assessmentChecklist(departmentId),
  })
  const progress = checklistProgress(defs, details)
  const [showOpen, setShowOpen] = useState(false)
  const checklistDone = notImpacted || progress.answered === progress.total
```
Add `&& checklistDone` to `ready`: `const ready = !needsChangePpt && checklistDone && (notImpacted || (...existing...))`.

Pass `highlightOpen={showOpen}` to `<ActivityChecklist>`. Directly above it (inside the `!notImpacted` guard) render:
```tsx
        {progress.total > 0 && (
          <p data-testid="check-progress"
            className={`text-[11px] ${progress.answered === progress.total ? 'text-emerald-400' : 'text-slate-400'}`}>
            {t('check.progress').replace('{n}', String(progress.answered))
              .replace('{m}', String(progress.total))}
          </p>
        )}
```
Next to the submit button:
```tsx
      {!checklistDone && progress.firstOpen && (
        <button type="button" data-testid="check-open-jump"
          className="ml-2 text-xs text-amber-300 underline decoration-dotted underline-offset-2"
          onClick={() => {
            setShowOpen(true)
            document.getElementById(`check-row-${progress.firstOpen}`)
              ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
          }}>
          {t('check.openRows').replace('{n}', String(progress.total - progress.answered))}
        </button>
      )}
```
`details` state already survives the questionnaire toggle, because `setDetails` merges and the checklist only hides. Keep it that way: don't clear `impacts` when `impacted` flips.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/changes/AssessmentSubmitForm.test.tsx src/components/changes/AssessmentBuckets.test.tsx`
Expected: PASS. If AssessmentBuckets tests submit through the form with `CHECKLIST` defs, answer all rows first.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/AssessmentSubmitForm.tsx frontend/src/components/changes/AssessmentSubmitForm.test.tsx frontend/src/components/changes/AssessmentBuckets.test.tsx
git commit -m "feat(cm): assessment submit waits for every checklist row, with a jump to the open ones"
```

---

### Task 6: Bucket summary chip and No count (frontend)

**Files:**
- Modify: `frontend/src/components/changes/AssessmentBuckets.tsx:257` (areas), `:298-310` (chip), `:461-471` (ticked list)
- Test: `frontend/src/components/changes/AssessmentBuckets.test.tsx`

**Interfaces:**
- Consumes: `impactsOf`, `impactedCount` (existing), `ChangeConcern.checklist_key`, query `['change', changeId, 'concerns']`.
- Produces: test ids `bucket-areas-${deptId}` (existing, new text), `bucket-no-${deptId}`.

- [ ] **Step 1: Write the failing tests**

Add to the `describe('AssessmentBuckets checklist', ...)` block (it has the `buckets`, `change`, `assessment` helpers and `t` imported):
```tsx
  const submittedWithAnswers = () => buckets({ canSeeAll: true, change: change({
    assessments: [assessment({
      status: 'submitted', verdict: 'feasible', submitted_at: '2026-09-24T00:00:00',
      details: { impacts: [
        { key: 'cycle_time_change', answer: 'yes', impacted: true },
        { key: 'sparepart_required', answer: 'no', impacted: false },
        { key: 'visual_risk', answer: 'no', impacted: false },
      ] },
    })] }) })

  it('chip counts impacted rows and open checklist risks of that department', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([
      { id: 1, kind: 'risk', is_open: true, department_id: 2, checklist_key: 'cycle_time_change', severity: 2 },
      { id: 2, kind: 'risk', is_open: true, department_id: 2, checklist_key: null, severity: 1 },
      { id: 3, kind: 'risk', is_open: false, department_id: 2, checklist_key: 'visual_risk', severity: 3 },
      { id: 4, kind: 'risk', is_open: true, department_id: 4, checklist_key: 'visual_risk', severity: 3 },
    ] as never)
    submittedWithAnswers()
    await waitFor(() => expect(screen.getByTestId('bucket-areas-2').textContent)
      .toBe(t('check.summary').replace('{n}', '1').replace('{k}', '1')))
  })

  it('lists No answers collapsed so a reviewer sees they were answered', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([])
    submittedWithAnswers()
    fireEvent.click(await screen.findByTestId('bucket-toggle-2'))
    expect(screen.getByTestId('bucket-no-2').textContent)
      .toBe(t('check.noCount').replace('{n}', '2'))
  })
```

Also update the existing tests in this describe block that Task 3 changes break. `check-${key}` checkbox clicks become `check-yes-${key}`. Tests that submit must answer every `CHECKLIST` row: click `check-no-${key}` for the ones not under test. Their expected `details.impacts` must include `answer` and the No rows; use `expect.arrayContaining([...])` for the rows the test cares about.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/changes/AssessmentBuckets.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `AssessmentBuckets.tsx`, at component level:
```tsx
  // Shared with the risk strip and the checklist rows.
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId),
  })
  const checklistRisks = (deptId: number) => (concerns as ChangeConcern[]).filter((c) =>
    c.kind === 'risk' && c.is_open && c.department_id === deptId && !!c.checklist_key).length
```
Per row: `const risks = checklistRisks(row.id)` next to `areas`. Chip condition becomes `(areas > 0 || risks > 0)`, and the text:
```tsx
                  {risks > 0
                    ? t('check.summary').replace('{n}', String(areas)).replace('{k}', String(risks))
                    : areas === 1 ? t('check.impactedOne')
                      : t('check.impactedCount').replace('{n}', String(areas))}
```
After the ticked `<ul>`:
```tsx
                {(() => {
                  const nos = impactsOf(a?.details).filter((i) => i.answer === 'no').length
                  return nos > 0 ? (
                    <p className="text-xs text-slate-500" data-testid={`bucket-no-${row.id}`}>
                      {t('check.noCount').replace('{n}', String(nos))}
                    </p>
                  ) : null
                })()}
```
Import `ChangeConcern` from the types if it isn't already imported.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/components/changes/AssessmentBuckets.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/AssessmentBuckets.tsx frontend/src/components/changes/AssessmentBuckets.test.tsx
git commit -m "feat(cm): bucket shows impacted rows, checklist risks and answered No count"
```

---

### Task 7: Full verification and live check

**Files:** none new.

- [ ] **Step 1: Full suites**

```bash
cd /home/nitrolinux/claude/plm2-integ/backend && uv run --no-sync pytest -q -p no:cacheprovider
cd /home/nitrolinux/claude/plm2-integ/frontend && npx tsc --noEmit -p . && npx vitest run
```
Expected: all pass, tsc exit 0. Fix anything red before continuing.

- [ ] **Step 2: Migration on the integ database**

The integ backend container `plm2-integ-backend` (port 8010, db `plm_integ`) mounts the worktree. Run:
```bash
docker exec plm2-integ-backend alembic upgrade head
docker exec claude-plm2-db-1 psql -U plm -d plm_integ -c "\d change_concerns" | grep checklist_key
docker exec plm2-integ-backend alembic downgrade -1 && docker exec plm2-integ-backend alembic upgrade head
```
Expected: `checklist_key | character varying(120)` present after the final upgrade. If `alembic` isn't on PATH in the container, use `docker exec -w /app plm2-integ-backend python -m alembic upgrade head` (check the working dir with `docker exec plm2-integ-backend pwd`). Restart the container if the model change isn't picked up: `docker restart plm2-integ-backend`.

- [ ] **Step 3: Live check on :5181**

Open `http://localhost:5181/plm2/changes/5?tab=assessments` while acting as one of the waiting departments (e.g. Tool Engineer). Check:
1. Rows show No/Yes with nothing selected.
2. Submit is disabled and "N rows unanswered" jumps to the first open row.
3. ⚑ on a row opens the pre-filled form. Raise a risk: the row shows "risk flagged", and the department's risk strip lists it.
4. Withdraw it in the strip and ⚑ returns.
5. Answer everything and submit: the bucket chip reads "n impacted · k risks flagged" and "m × No".

Use the playwright-cli skill if driving the browser headless. Report what was seen; don't claim a step you didn't observe.

- [ ] **Step 4: Commit any fixes, then report**

No commit if nothing changed. Report test counts, the migration result and the live observations.
