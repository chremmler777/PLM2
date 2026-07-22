# Change Start Permissions & Department Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict starting a change request to members of departments flagged as change-starters (Sales, Project Manager, Tool design, IE, R&D), surface that rule in one shared button component used by all three entry points, and clean the duplicate/dead departments out of `wf_departments`.

**Architecture:** A new `wf_departments.can_start_change` boolean is the single source of truth. `ChangeService.can_start_change()` reads it and is called from `ChangeService.create_change()`, so every caller — all three UI entry points, the REST API, import scripts — is covered by one guard. The frontend reads the same truth from `GET /api/v1/changes/permissions` and renders one `<StartChangeButton>` everywhere, so the popup text can never drift from what is enforced.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + pytest-asyncio (backend); React 18 + TypeScript + react-query v5 + Tailwind + Vitest + Testing Library (frontend).

## Global Constraints

- Branch: `feature/change-flow-rework`. Do not merge to main.
- Spec: `docs/superpowers/specs/2026-07-22-change-start-permissions-design.md`.
- Backend tests run **on the host from `backend/`**: `python3 -m pytest`. They do **not** run in `claude-plm2-backend-1` — that container has no `aiosqlite`.
- Backend baseline is **351 passing** (~7m43s). Never finish a task with fewer.
- Frontend tests: `npm test -- --run` from `frontend/`.
- Departments permitted to start a change: **Sales, Project Manager, Tool design, IE, R&D**. Exact `wf_departments.name` strings.
- Departments to retire: **Developer, Tool Engineer, Manufacturing Engineer, APQP, Operations Manager**.
- Merges: **Tool Engineer → Tool design**, **Manufacturing Engineer → IE**.
- All new UI uses dark-slate theme tokens (`bg-slate-800`, `border-slate-700`, `text-slate-300`), matching the app-wide rule.
- Department labels in the UI are rendered verbatim from the API. Never hardcode a department name in frontend code.
- Commit after every task.

---

### Task 1: Migration — merge duplicates, retire dead departments, add `can_start_change`

**Files:**
- Create: `backend/alembic/versions/032_change_starter_departments.py`
- Modify: `backend/app/models/workflow.py:16-25` (add the column to `Department`)
- Test: `backend/tests/test_change_starter_departments.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Department.can_start_change: Mapped[bool]`; DB column `wf_departments.can_start_change BOOLEAN NOT NULL DEFAULT false`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_change_starter_departments.py`:

```python
"""Department merge/retire migration and the can_start_change column."""
import pytest
from sqlalchemy import select

from app.models.workflow import Department, UserDepartment

pytestmark = pytest.mark.asyncio


async def test_department_has_can_start_change_defaulting_false(session_factory):
    async with session_factory() as s:
        d = Department(name="Fresh Dept", flow_type="action", is_active=True, sort_order=1)
        s.add(d)
        await s.commit()
        assert d.can_start_change is False


async def test_can_start_change_is_settable(session_factory):
    async with session_factory() as s:
        d = Department(name="Starter Dept", flow_type="action", is_active=True,
                       sort_order=1, can_start_change=True)
        s.add(d)
        await s.commit()
        row = (await s.execute(
            select(Department).where(Department.name == "Starter Dept")
        )).scalar_one()
        assert row.can_start_change is True
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `python3 -m pytest tests/test_change_starter_departments.py -v`
Expected: FAIL — `TypeError: 'can_start_change' is an invalid keyword argument for Department`.

- [ ] **Step 3: Add the column to the model**

In `backend/app/models/workflow.py`, inside `class Department`, add after the `is_active` line:

```python
    can_start_change: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
```

At the top of the file, ensure the import exists:

```python
from sqlalchemy import false as sa_false
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_change_starter_departments.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/032_change_starter_departments.py`:

```python
"""032: Change-starter departments — merge duplicates, retire dead seeds,
add wf_departments.can_start_change.

- Tool Engineer -> Tool design, Manufacturing Engineer -> IE. Both duplicates
  are seed-era names; the targets carry the real RASIC/rate/activity rows.
- Retires Developer, Tool Engineer, Manufacturing Engineer, APQP and
  Operations Manager (is_active=false). Their only RASIC rows sit on
  wf_templates id 1 ("ECR"), which no change_routing_standards row points at,
  so no live routing is affected.
- can_start_change seeded true for Sales, Project Manager, Tool design, IE, R&D.

The merge is deliberately NOT reversed on downgrade: the duplicate rows held
no unique data, so re-splitting them would be guesswork.

Revision ID: 032
Revises: 031
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

MERGES = [("Tool Engineer", "Tool design"), ("Manufacturing Engineer", "IE")]
RETIRE = ["Developer", "Tool Engineer", "Manufacturing Engineer",
          "APQP", "Operations Manager"]
STARTERS = ["Sales", "Project Manager", "Tool design", "IE", "R&D"]

# Every table with an FK to wf_departments.
REPOINT_TABLES = [
    "wf_step_rasic", "lessons_learned", "change_assessments",
    "department_rate", "assessment_activity", "wf_instance_tasks",
]


def _dept_id(bind, name):
    return bind.execute(
        sa.text("SELECT id FROM wf_departments WHERE name = :n"), {"n": name}
    ).scalar()


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    cols = {c["name"] for c in insp.get_columns("wf_departments")}
    if "can_start_change" not in cols:
        op.add_column(
            "wf_departments",
            sa.Column("can_start_change", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
        )

    tables = set(insp.get_table_names())

    for dup_name, target_name in MERGES:
        dup = _dept_id(bind, dup_name)
        target = _dept_id(bind, target_name)
        if dup is None or target is None or dup == target:
            continue

        for table in REPOINT_TABLES:
            if table not in tables:
                continue
            bind.execute(
                sa.text(f"UPDATE {table} SET department_id = :t "
                        f"WHERE department_id = :d"),
                {"t": target, "d": dup},
            )

        # user_departments has PK (user_id, department_id): a user in BOTH the
        # duplicate and the target would collide on UPDATE. Drop the duplicate
        # row for those users, repoint the rest.
        if "user_departments" in tables:
            bind.execute(
                sa.text(
                    "DELETE FROM user_departments WHERE department_id = :d "
                    "AND user_id IN (SELECT user_id FROM user_departments "
                    "WHERE department_id = :t)"
                ),
                {"d": dup, "t": target},
            )
            bind.execute(
                sa.text("UPDATE user_departments SET department_id = :t "
                        "WHERE department_id = :d"),
                {"t": target, "d": dup},
            )

    for name in RETIRE:
        bind.execute(
            sa.text("UPDATE wf_departments SET is_active = false WHERE name = :n"),
            {"n": name},
        )

    for name in STARTERS:
        bind.execute(
            sa.text("UPDATE wf_departments SET can_start_change = true WHERE name = :n"),
            {"n": name},
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    for name in RETIRE:
        bind.execute(
            sa.text("UPDATE wf_departments SET is_active = true WHERE name = :n"),
            {"n": name},
        )

    cols = {c["name"] for c in insp.get_columns("wf_departments")}
    if "can_start_change" in cols:
        op.drop_column("wf_departments", "can_start_change")
```

- [ ] **Step 6: Apply the migration to the dev database**

Run: `docker exec claude-plm2-backend-1 sh -c "cd /app && alembic upgrade head"`
Expected: `Running upgrade 031 -> 032`.

- [ ] **Step 7: Verify the dev database state**

Run:

```bash
docker exec claude-plm2-backend-1 sh -c "PGPASSWORD=plm psql -h plm2-db -U plm -d plm -c \"
SELECT name, is_active, can_start_change FROM wf_departments ORDER BY id;\""
```

Expected: 16 rows. `is_active = f` for exactly Developer, Tool Engineer, Manufacturing Engineer, APQP, Operations Manager. `can_start_change = t` for exactly Sales, Project Manager, Tool design, IE, R&D.

Then verify the merge landed:

```bash
docker exec claude-plm2-backend-1 sh -c "PGPASSWORD=plm psql -h plm2-db -U plm -d plm -c \"
SELECT d.name, count(r.id) AS rasic FROM wf_departments d
LEFT JOIN wf_step_rasic r ON r.department_id = d.id
WHERE d.name IN ('Tool Engineer','Tool design','Manufacturing Engineer','IE')
GROUP BY d.name ORDER BY d.name;\""
```

Expected: `Tool Engineer` 0, `Tool design` 14 (12 + the 2 moved), `Manufacturing Engineer` 0, `IE` 12.

- [ ] **Step 8: Run the full backend suite**

Run: `python3 -m pytest -q`
Expected: 353 passed (351 baseline + the 2 new).

- [ ] **Step 9: Commit**

```bash
git add backend/alembic/versions/032_change_starter_departments.py \
        backend/app/models/workflow.py \
        backend/tests/test_change_starter_departments.py
git commit -m "feat(departments): merge duplicate seed departments, retire dead ones, add can_start_change"
```

---

### Task 2: Enforce the permission in `ChangeService.create_change`

Folds in the conftest fixture and existing-suite repair, because the guard turns every non-admin change-creating test red the moment it lands. The suite must be green at this task's commit.

**Files:**
- Modify: `backend/app/services/change_service.py:76` (add `ChangePermissionError`), and `create_change`
- Modify: `backend/app/api/v1/changes/changes.py:54-72` (403 mapping)
- Modify: `backend/tests/conftest.py` (add the `can_start_changes` fixture)
- Test: `backend/tests/test_change_starter_departments.py` (extend)

**Interfaces:**
- Consumes: `Department.can_start_change` from Task 1.
- Produces:
  - `class ChangePermissionError(ChangeError)` in `change_service.py`
  - `async ChangeService.can_start_change(session: AsyncSession, user: User) -> bool`
  - `async ChangeService.starter_department_names(session: AsyncSession) -> list[str]`
  - `async ChangeService.user_department_names(session: AsyncSession, user_id: int) -> list[str]`
  - pytest fixture `can_start_changes` in `conftest.py`, returning the created department's `id`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_change_starter_departments.py`:

```python
from app.models.entities import User
from app.services.change_service import ChangeService


async def _dept(session_factory, name, *, starter, active=True):
    async with session_factory() as s:
        d = Department(name=name, flow_type="action", is_active=active,
                       sort_order=1, can_start_change=starter)
        s.add(d)
        await s.commit()
        return d.id


async def _join(session_factory, user_id, dept_id):
    async with session_factory() as s:
        s.add(UserDepartment(user_id=user_id, department_id=dept_id))
        await s.commit()


async def test_admin_may_start_without_any_department(session_factory, seed):
    async with session_factory() as s:
        admin = await s.get(User, seed["admin_id"])
        assert await ChangeService.can_start_change(s, admin) is True


async def test_member_of_starter_department_may_start(session_factory, seed):
    did = await _dept(session_factory, "Sales", starter=True)
    await _join(session_factory, seed["engineer_id"], did)
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        assert await ChangeService.can_start_change(s, eng) is True


async def test_member_of_non_starter_department_may_not_start(session_factory, seed):
    did = await _dept(session_factory, "Quality", starter=False)
    await _join(session_factory, seed["engineer_id"], did)
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        assert await ChangeService.can_start_change(s, eng) is False


async def test_retired_starter_department_does_not_grant_permission(session_factory, seed):
    did = await _dept(session_factory, "Retired Starter", starter=True, active=False)
    await _join(session_factory, seed["engineer_id"], did)
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        assert await ChangeService.can_start_change(s, eng) is False


async def test_user_with_no_departments_may_not_start(session_factory, seed):
    async with session_factory() as s:
        eng = await s.get(User, seed["engineer_id"])
        assert await ChangeService.can_start_change(s, eng) is False


async def test_create_change_returns_403_when_not_permitted(client, eng_auth, seed):
    res = await client.post(
        "/api/v1/changes",
        json={"project_id": seed["project_id"], "title": "Nope",
              "change_type": "physical_part"},
        headers=eng_auth,
    )
    assert res.status_code == 403, res.text
    assert "restricted" in res.json()["detail"].lower()


async def test_create_change_succeeds_for_starter_member(
    client, eng_auth, seed, can_start_changes
):
    res = await client.post(
        "/api/v1/changes",
        json={"project_id": seed["project_id"], "title": "Yes",
              "change_type": "physical_part"},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
```

- [ ] **Step 2: Add the conftest fixture**

In `backend/tests/conftest.py`, add near the other auth fixtures (after `eng_auth`):

```python
@pytest_asyncio.fixture
async def can_start_changes(session_factory, seed):
    """Grant the seeded engineer membership in a change-starter department.

    Any test where a NON-ADMIN creates a change must request this fixture —
    ChangeService.create_change refuses otherwise. Admins bypass the check.
    """
    from app.models.workflow import Department, UserDepartment
    async with session_factory() as s:
        d = Department(name="Change Starters", flow_type="action",
                       is_active=True, sort_order=99, can_start_change=True)
        s.add(d)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=d.id))
        await s.commit()
        return d.id
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_change_starter_departments.py -v`
Expected: FAIL — `AttributeError: type object 'ChangeService' has no attribute 'can_start_change'`, and the 403 test gets 200.

- [ ] **Step 4: Implement the permission logic**

In `backend/app/services/change_service.py`, after `class ChangeError(ValueError):` (line 76), add:

```python
class ChangePermissionError(ChangeError):
    """Caller is not allowed to perform this change action (maps to HTTP 403)."""
```

Add these static methods to `ChangeService`:

```python
    @staticmethod
    async def starter_department_names(session: AsyncSession) -> list[str]:
        """Names of active departments permitted to start a change."""
        from app.models.workflow import Department
        rows = await session.execute(
            select(Department.name)
            .where(Department.can_start_change.is_(True),
                   Department.is_active.is_(True))
            .order_by(Department.sort_order, Department.name)
        )
        return [n for (n,) in rows]

    @staticmethod
    async def user_department_names(session: AsyncSession, user_id: int) -> list[str]:
        """Names of the active departments a user belongs to."""
        from app.models.workflow import Department, UserDepartment
        rows = await session.execute(
            select(Department.name)
            .join(UserDepartment, UserDepartment.department_id == Department.id)
            .where(UserDepartment.user_id == user_id,
                   Department.is_active.is_(True))
            .order_by(Department.sort_order, Department.name)
        )
        return [n for (n,) in rows]

    @staticmethod
    async def can_start_change(session: AsyncSession, user) -> bool:
        """Admins always may; everyone else needs a starter-department membership."""
        if user.role == "admin":
            return True
        from app.models.workflow import Department, UserDepartment
        hit = (await session.execute(
            select(UserDepartment.department_id)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id == user.id,
                   Department.can_start_change.is_(True),
                   Department.is_active.is_(True))
            .limit(1)
        )).scalar_one_or_none()
        return hit is not None
```

- [ ] **Step 5: Guard `create_change`**

`create_change` (`change_service.py:231`) currently receives `raised_by` (a user id),
not a `User`. Add one keyword-only parameter `actor` and a guard, changing nothing
else about the signature or body:

```python
    @staticmethod
    async def create_change(
        session: AsyncSession, *, project_id: int, title: str, change_type: str,
        raised_by: int, reason: Optional[str] = None, description: Optional[str] = None,
        priority: str = "medium", lead_id: Optional[int] = None,
        data_classification: str = "confidential",
        customer_relevant: Optional[bool] = None,
        actor: Optional["User"] = None,
    ) -> ChangeRequest:
        if actor is not None and not await ChangeService.can_start_change(session, actor):
            names = await ChangeService.starter_department_names(session)
            raise ChangePermissionError(
                "Starting a change is restricted to: " + ", ".join(names)
            )
        if change_type not in CHANGE_TYPES:
            raise ChangeError(f"Invalid change_type '{change_type}'")
        # ... rest of the existing body unchanged, from generate_change_number onward
```

`actor=None` means "no caller identity supplied, skip the check". That keeps the
backfill scripts in `backend/scripts/` working unchanged — they call `create_change`
directly with no request user.

- [ ] **Step 6: Map the error to 403 in the router**

In `backend/app/api/v1/changes/changes.py`, update the import and the `create_change` handler:

```python
from app.services.change_service import ChangeService, ChangeError, ChangePermissionError
```

```python
    try:
        change = await ChangeService.create_change(
            session=db, project_id=body.project_id, title=body.title,
            change_type=body.change_type, raised_by=current_user.id,
            actor=current_user,
            reason=body.reason, description=body.description, priority=body.priority,
            lead_id=body.lead_id, data_classification=body.data_classification,
            customer_relevant=body.customer_relevant,
        )
    except ChangePermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ChangeError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

`ChangePermissionError` must be caught **before** `ChangeError` — it is a subclass, so
the reverse order silently returns 400.

- [ ] **Step 7: Run the new tests**

Run: `python3 -m pytest tests/test_change_starter_departments.py -v`
Expected: PASS (9 passed).

- [ ] **Step 8: Find and repair the existing tests the guard broke**

Run: `python3 -m pytest -q 2>&1 | tail -40`

Every failure will be a `403` where a `200`/`201` was expected. For each failing test,
find whether it creates the change with `eng_auth` (non-admin) or `admin_auth` (admin,
unaffected). For the `eng_auth` ones, add `can_start_changes` to the test function's
parameter list — the fixture only adds a membership, so no other assertion changes:

```python
# before
async def test_something(client, eng_auth, seed):
# after
async def test_something(client, eng_auth, seed, can_start_changes):
```

Candidate files (those that POST to `/api/v1/changes`): `test_changes.py`,
`test_change_routing.py`, `test_change_scoping.py`, `test_change_gates.py`,
`test_change_cost.py`, `test_change_deviations.py`, `test_change_deadline.py`,
`test_change_scoped_instances.py`, `test_change_org_scoping.py`, `test_impact_tree.py`,
`test_impact_confirmation.py`, `test_assessment_ownership.py`, `test_my_actions.py`,
`test_audit.py`, `test_audit_scoping.py`, `test_user_departments.py`.

Do **not** modify the `seed` fixture to grant departments globally.
`test_user_departments.py::test_get_returns_current_memberships` asserts the engineer
starts with `[]` departments, and `test_put_replaces_set` asserts exact membership
sets — a global grant breaks both.

- [ ] **Step 9: Run the full backend suite**

Run: `python3 -m pytest -q`
Expected: 360 passed (353 after Task 1 + 7 new in this task). Zero failures.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/change_service.py \
        backend/app/api/v1/changes/changes.py \
        backend/tests/
git commit -m "feat(changes): restrict starting a change to change-starter departments"
```

---

### Task 3: `GET /api/v1/changes/permissions`

**Files:**
- Modify: `backend/app/api/v1/changes/changes.py` (new route, declared before `GET /{change_id}` at line 232)
- Modify: `backend/app/schemas/change.py` (add `ChangePermissionsResponse`)
- Test: `backend/tests/test_change_starter_departments.py` (extend)

**Interfaces:**
- Consumes: `ChangeService.can_start_change`, `starter_department_names`, `user_department_names` from Task 2.
- Produces: `GET /api/v1/changes/permissions` → `{can_start: bool, allowed_departments: string[], your_departments: string[]}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_change_starter_departments.py`:

```python
async def test_permissions_endpoint_denies_non_member(client, eng_auth, seed):
    res = await client.get("/api/v1/changes/permissions", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["can_start"] is False
    assert body["your_departments"] == []


async def test_permissions_endpoint_allows_starter_member(
    client, eng_auth, seed, can_start_changes
):
    res = await client.get("/api/v1/changes/permissions", headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["can_start"] is True
    assert body["allowed_departments"] == ["Change Starters"]
    assert body["your_departments"] == ["Change Starters"]


async def test_permissions_route_is_not_shadowed_by_change_id(client, admin_auth):
    """`permissions` must not be parsed as a {change_id} path parameter."""
    res = await client.get("/api/v1/changes/permissions", headers=admin_auth)
    assert res.status_code == 200
    assert "can_start" in res.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_change_starter_departments.py -k permissions -v`
Expected: FAIL with 422 — FastAPI matches `/{change_id}` and rejects `permissions` as a non-integer.

- [ ] **Step 3: Add the response schema**

In `backend/app/schemas/change.py`:

```python
class ChangePermissionsResponse(BaseModel):
    can_start: bool
    allowed_departments: List[str]
    your_departments: List[str]
```

- [ ] **Step 4: Add the route**

In `backend/app/api/v1/changes/changes.py`, place this **immediately after the
`/reference/activities` route (line 218) and before `GET /{change_id}` (line 232)**,
with the other static-path routes:

```python
@router.get("/permissions", response_model=ChangePermissionsResponse)
async def get_change_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Who may start a change, and whether the caller is one of them."""
    return ChangePermissionsResponse(
        can_start=await ChangeService.can_start_change(db, current_user),
        allowed_departments=await ChangeService.starter_department_names(db),
        your_departments=await ChangeService.user_department_names(db, current_user.id),
    )
```

Add `ChangePermissionsResponse` to the existing schema import block at the top of the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_change_starter_departments.py -v`
Expected: PASS (12 passed).

- [ ] **Step 6: Run the full backend suite**

Run: `python3 -m pytest -q`
Expected: 363 passed (360 + 3 new).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/changes/changes.py backend/app/schemas/change.py backend/tests/
git commit -m "feat(changes): add GET /changes/permissions"
```

---

### Task 4: Remove the broken `TYPE_DISCIPLINES` routing fallback

**Files:**
- Modify: `backend/app/services/change_service.py:63-69` (delete `TYPE_DISCIPLINES`)
- Modify: `backend/app/services/change_routing_service.py:4` (docstring), `:105-112`
  (the fallback branch in `resolve_standard`), `:197-205` (the now-dead
  `template_id is None` branch in `build_routing`)
- Modify: `backend/tests/test_assessment_effort.py:10` (depends on the fallback)
- Test: `backend/tests/test_change_routing.py` (extend)

**Interfaces:**
- Consumes: `can_start_changes` fixture from Task 2.
- Produces: `ChangeRoutingService.resolve_standard` raises
  `ChangeError("No routing standard configured for change type '<type>'")` when no
  `ChangeRoutingStandard` row matches.

`TYPE_DISCIPLINES` names `Process Engineer` and `Packaging Engineer`, neither of which
exists in `wf_departments`. A fallback onto non-existent departments produces a change
whose routing is silently wrong, which is worse than a loud failure.

Note: `GET /{change_id}/routing` only *reads* an existing snapshot — it returns empty
stages when no routing was built. The fallback lives in `resolve_standard`, so the test
must exercise that directly rather than going through the read endpoint.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_change_routing.py`:

```python
async def test_unmapped_change_type_raises_instead_of_falling_back(session_factory):
    """With no ChangeRoutingStandard for the type, resolve_standard must raise,
    not silently fall back onto a hardcoded discipline-name list."""
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeError

    async with session_factory() as s:
        with pytest.raises(ChangeError, match="routing standard"):
            await ChangeRoutingService.resolve_standard(s, "packaging")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_change_routing.py::test_unmapped_change_type_raises_instead_of_falling_back -v`
Expected: FAIL — `resolve_standard` returns `(None, None, [{"stage_order": 1, "departments": []}])` instead of raising.

- [ ] **Step 3: Delete the fallback**

Remove the `TYPE_DISCIPLINES` dict from `change_service.py:63-69`. In
`change_routing_service.py`, replace the fallback branch at the end of
`resolve_standard` (lines 105-112) with:

```python
        raise ChangeError(
            f"No routing standard configured for change type '{change_type}'"
        )
```

Add `ChangeError` to the imports. Then remove the now-unreachable `else:` branch in
`build_routing` (lines 197-205) that looked up the `"ECM Assessment"` template by name
to compensate for a fallback with no `template_id` — `resolve_standard` can no longer
return `template_id is None`, so `if routing.template_id is not None:` becomes
unconditional. Also update the module docstring (line 4), which still describes the
fallback.

- [ ] **Step 4: Repair `test_assessment_effort.py`**

Its fixture (line 10) creates departments matching `TYPE_DISCIPLINES["physical_part"]`
so routing resolves without a `ChangeRoutingStandard`. Give it an explicit template plus
a `ChangeRoutingStandard` row for `physical_part` instead — follow the `ecr_template`
fixture in `tests/test_change_routing.py:55` for how to build a `WfTemplate` with
stages, steps and RASIC rows. Do not restore the dict.

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_change_routing.py tests/test_assessment_effort.py -v`
Expected: PASS, both files green.

- [ ] **Step 6: Run the full backend suite**

Run: `python3 -m pytest -q`
Expected: 364 passed (363 + 1 new). Any other test that relied on the fallback gets an
explicit `ChangeRoutingStandard` row, never a restored dict.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ backend/tests/test_change_routing.py
git commit -m "refactor(routing): drop TYPE_DISCIPLINES fallback naming non-existent departments"
```

---

### Task 5: Frontend API client and types

**Files:**
- Modify: `frontend/src/types/change.ts` (add `ChangePermissions`)
- Modify: `frontend/src/api/changes.ts` (add `permissions`)

**Interfaces:**
- Consumes: `GET /api/v1/changes/permissions` from Task 3.
- Produces: `ChangePermissions` type; `changesApi.permissions(): Promise<ChangePermissions>`.

- [ ] **Step 1: Add the type**

In `frontend/src/types/change.ts`:

```ts
export interface ChangePermissions {
  can_start: boolean;
  allowed_departments: string[];
  your_departments: string[];
}
```

- [ ] **Step 2: Add the API method**

In `frontend/src/api/changes.ts`, add `ChangePermissions` to the existing
`import type { ... } from '../types/change'` block, then add to `changesApi`:

```ts
  permissions: () =>
    client.get<ChangePermissions>('/v1/changes/permissions').then((r) => r.data),
```

- [ ] **Step 3: Verify it type-checks**

Run from `frontend/`: `npx tsc --noEmit`
Expected: no errors introduced by these files.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/change.ts frontend/src/api/changes.ts
git commit -m "feat(frontend): changesApi.permissions + ChangePermissions type"
```

---

### Task 6: `<StartChangeButton>` component

**Files:**
- Create: `frontend/src/components/changes/StartChangeButton.tsx`
- Create: `frontend/src/components/changes/StartChangeButton.test.tsx`

**Interfaces:**
- Consumes: `changesApi.permissions` and `ChangePermissions` from Task 5;
  `StartChangeModal` and its exported `StartChangePrefill` from
  `frontend/src/components/changes/StartChangeModal.tsx`.
- Produces: default-exported `StartChangeButton` with props
  `{ prefill?: StartChangePrefill; variant?: 'primary' | 'inline'; label?: string }`.

Note the existing prefill shape is `{ projectId?: number; part?: PickedPart }` —
a full part object, not a part id.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/changes/StartChangeButton.test.tsx`:

```tsx
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import StartChangeButton from './StartChangeButton'

const mockPermissions = vi.fn()
vi.mock('../../api/changes', () => ({
  changesApi: { permissions: () => mockPermissions() },
}))

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('StartChangeButton', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('enables the button when the user may start a change', async () => {
    mockPermissions.mockResolvedValue({
      can_start: true,
      allowed_departments: ['Sales', 'R&D'],
      your_departments: ['Sales'],
    })
    wrap(<StartChangeButton />)
    await waitFor(() =>
      expect(screen.getByTestId('start-change-button').hasAttribute('disabled')).toBe(false))
  })

  it('disables the button and names the allowed departments when denied', async () => {
    mockPermissions.mockResolvedValue({
      can_start: false,
      allowed_departments: ['Sales', 'R&D'],
      your_departments: ['Quality'],
    })
    wrap(<StartChangeButton />)
    await waitFor(() =>
      expect(screen.getByTestId('start-change-button').hasAttribute('disabled')).toBe(true))
    const popup = screen.getByTestId('start-change-popup')
    expect(popup.textContent).toContain('Sales')
    expect(popup.textContent).toContain('R&D')
    expect(popup.textContent).toContain('Quality')
  })

  it('says so when the user is in no department at all', async () => {
    mockPermissions.mockResolvedValue({
      can_start: false,
      allowed_departments: ['Sales'],
      your_departments: [],
    })
    wrap(<StartChangeButton />)
    await waitFor(() =>
      expect(screen.getByTestId('start-change-popup').textContent)
        .toContain('not assigned to any department'))
  })

  it('stays enabled when the permission query fails, letting the server decide', async () => {
    mockPermissions.mockRejectedValue(new Error('network'))
    wrap(<StartChangeButton />)
    await waitFor(() =>
      expect(screen.getByTestId('start-change-button').hasAttribute('disabled')).toBe(false))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run from `frontend/`: `npm test -- --run StartChangeButton`
Expected: FAIL — cannot resolve `./StartChangeButton`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/changes/StartChangeButton.tsx`:

```tsx
/**
 * StartChangeButton - the single control for starting a change request.
 *
 * Used by ChangesPage, ProjectDetailPage and PartDetail so the action looks
 * and behaves identically wherever it appears. Permission comes from the
 * server (GET /changes/permissions) and department names are rendered
 * verbatim, so the popup can never drift from what is enforced.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { changesApi } from '../../api/changes';
import StartChangeModal, { type StartChangePrefill } from './StartChangeModal';

interface Props {
  prefill?: StartChangePrefill;
  variant?: 'primary' | 'inline';
  label?: string;
}

const STYLES = {
  primary:
    'px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium ' +
    'hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 ' +
    'disabled:cursor-not-allowed',
  inline:
    'text-xs text-blue-400 hover:text-blue-300 disabled:text-slate-500 ' +
    'disabled:cursor-not-allowed',
};

export default function StartChangeButton({
  prefill, variant = 'primary', label = 'Start change',
}: Props) {
  const [open, setOpen] = useState(false);

  const { data: perms, isLoading, isError } = useQuery({
    queryKey: ['changes', 'permissions'],
    queryFn: () => changesApi.permissions(),
    staleTime: 5 * 60 * 1000,
  });

  // Fail open on error: the server is the authority and returns 403 anyway.
  // A dead button after a transient network blip is worse than a failed POST.
  const denied = !isLoading && !isError && perms?.can_start === false;
  const allowed = perms?.allowed_departments ?? [];
  const yours = perms?.your_departments ?? [];

  return (
    <div className="relative inline-block group">
      <button
        data-testid="start-change-button"
        className={STYLES[variant]}
        disabled={isLoading || denied}
        aria-describedby="start-change-popup"
        onClick={() => setOpen(true)}
      >
        {label}
      </button>

      {allowed.length > 0 && (
        <div
          id="start-change-popup"
          data-testid="start-change-popup"
          role="tooltip"
          className="pointer-events-none absolute right-0 top-full z-20 mt-2 w-72
                     rounded-lg border border-slate-700 bg-slate-800 p-3 text-xs
                     text-slate-300 opacity-0 shadow-lg transition-opacity
                     group-hover:opacity-100 group-focus-within:opacity-100"
        >
          <p className="mb-1 font-semibold text-slate-200">
            Starting a change is restricted to:
          </p>
          <p className="text-slate-400">{allowed.join(' · ')}</p>
          {denied && (
            <p className="mt-2 text-slate-400">
              {yours.length > 0
                ? `You are in: ${yours.join(' · ')}`
                : 'You are not assigned to any department.'}
            </p>
          )}
        </div>
      )}

      {open && <StartChangeModal open onClose={() => setOpen(false)} prefill={prefill} />}
    </div>
  );
}
```

If `StartChangeModal` does not already export its prefill type, add
`export` to the existing `interface StartChangePrefill` declaration
(`StartChangeModal.tsx:31`) rather than redeclaring it here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- --run StartChangeButton`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/changes/StartChangeButton.tsx \
        frontend/src/components/changes/StartChangeButton.test.tsx \
        frontend/src/components/changes/StartChangeModal.tsx
git commit -m "feat(frontend): shared StartChangeButton with permission popup"
```

---

### Task 7: Wire the button into all three entry points

**Files:**
- Modify: `frontend/src/pages/ChangesPage.tsx:10,28-33,104`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx:18,1058`
- Modify: `frontend/src/pages/PartDetail.tsx:10,479`

**Interfaces:**
- Consumes: `StartChangeButton` from Task 6.
- Produces: no new interfaces. Each page ends with one `<StartChangeButton>` and no
  local `showCreate` state.

- [ ] **Step 1: Replace the button in ChangesPage**

In `frontend/src/pages/ChangesPage.tsx`: delete the `showCreate` state (line 10), the
`StartChangeModal` import (line 6), the `<button>` block (lines 28-33) and the
`<StartChangeModal>` render (line 104). Add `import StartChangeButton from
'../components/changes/StartChangeButton';` and, in the header row:

```tsx
        <StartChangeButton />
```

- [ ] **Step 2: Replace the button in ProjectDetailPage**

Replace lines 1040-1047 (the `<button>` ending in `Start change`) with:

```tsx
          <StartChangeButton prefill={{ projectId: id }} />
```

Delete the conditional modal block at lines 1057-1063 entirely:

```tsx
      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}
```

Delete the `StartChangeModal` import (line 18) and the `showStartChange` state
declaration, and add:

```tsx
import StartChangeButton from '../components/changes/StartChangeButton';
```

- [ ] **Step 3: Replace the button in PartDetail**

Replace lines 469-474 (the `<button>` ending in `Start change`) with:

```tsx
            <StartChangeButton
              prefill={{
                projectId: part.project_id,
                part: {
                  id: part.id,
                  part_number: part.part_number,
                  name: part.name,
                  item_category: part.item_category,
                },
              }}
            />
```

Delete the `{showStartChange && (<StartChangeModal ... />)}` block starting at line 478,
the `showStartChange` state declaration, and the `StartChangeModal` import (line 10).
Add:

```tsx
import StartChangeButton from '../components/changes/StartChangeButton';
```

- [ ] **Step 3b: Unify the label**

The three entry points currently disagree: `ChangesPage` says **"New Change"**, the
other two say **"Start change"**. Standardise on **"Start change"** — it is the more
accurate verb and already the majority. Set it as the default in
`StartChangeButton.tsx`:

```tsx
  prefill, variant = 'primary', label = 'Start change',
```

Pass no `label` prop from any of the three call sites.

- [ ] **Step 4: Verify no stale references remain**

Run from `frontend/`:

```bash
grep -rn "StartChangeModal" src/pages/
```

Expected: no output. `StartChangeModal` should now be imported only by
`StartChangeButton.tsx` and its own test.

- [ ] **Step 5: Type-check and run the frontend suite**

Run: `npx tsc --noEmit && npm test -- --run`
Expected: no type errors; all tests pass, including the pre-existing 31.

- [ ] **Step 6: Verify in the running app**

Open http://localhost/plm2/ and check all three surfaces: the Changes page header, a
project detail page, and a part detail page. The button must look identical on all
three, and hovering it must show the allowed-departments popup. Since you are `admin-1`
with the admin role, the button will be **enabled** — the admin bypass. To see the
denied state, temporarily set `role='engineer'` on your user:

```bash
docker exec claude-plm2-backend-1 sh -c "PGPASSWORD=plm psql -h plm2-db -U plm -d plm \
  -c \"UPDATE users SET role='engineer' WHERE username='admin-1';\""
```

Restore it afterwards with `role='admin'`. Note the bridge re-syncs hub-provisioned
users' roles on login (`auth.py:105`), so the override may not survive a re-login.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/
git commit -m "refactor(frontend): all three change entry points use StartChangeButton"
```

---

## Done when

- `python3 -m pytest -q` from `backend/` reports **364 passed**, zero failures.
- `npx tsc --noEmit && npm test -- --run` from `frontend/` is clean.
- `wf_departments` shows 11 active rows, with `can_start_change = true` on exactly
  Sales, Project Manager, Tool design, IE, R&D.
- `grep -rn "TYPE_DISCIPLINES" backend/` returns nothing.
- `grep -rn "StartChangeModal" frontend/src/pages/` returns nothing.

## Not in this plan

Parked defects from the spec's out-of-scope section, to be addressed during the
lifecycle walkthrough: all five change types mapping to `wf_templates` 116; ~10
blocking departments per change; Project Manager being R/A with zero rates and
activities; the unread hub `department` claim; `admin-1` having no department
memberships.
