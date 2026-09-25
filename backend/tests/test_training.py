"""ECR training record: curriculum contract, status transitions, publish and
re-training, roster and CSV, and the gate that is wired but off by default.

Modelled on TWOS tests/test_training_{curriculum,flow,gate}.py.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import AuditLog
from app.models.training import TrainingAttempt, TrainingSignoff
from app.models.workflow import Department, UserDepartment
from app.services import training as svc
from app.version import SOFTWARE_VERSION
from tests.conftest import login

pytestmark = pytest.mark.asyncio

ACTS_AS = "X-Acts-As-Department"

#: Spelled out literally, like frontend/src/training/tasks.test.ts: a rename on
#: one side must be a deliberate two-file change.
EXPECTED_TASKS = {
    "project_management": ("pm_set_priority",),
    "sales": ("sales_start_change",),
    "engineering": ("eng_answer_checklist_row", "eng_submit_assessment"),
    "scheduling": ("sch_answer_checklist_row",),
    "quality": ("qa_answer_checklist_row",),
    "finance": ("fin_answer_checklist_row",),
}


# --------------------------------------------------------------- fixtures

@pytest.fixture
async def depts(session_factory):
    async with session_factory() as s:
        rows = {n: Department(name=n, flow_type="action", is_active=True,
                              can_start_change=n in ("Sales", "Project Manager"))
                for n in ("Sales", "Project Manager", "Tool Engineer", "Quality",
                          "Finance", "Scheduling", "Logistics")}
        s.add_all(rows.values())
        await s.commit()
        return {n: d.id for n, d in rows.items()}


async def _join(session_factory, user_id: int, dept_id: int) -> None:
    async with session_factory() as s:
        s.add(UserDepartment(user_id=user_id, department_id=dept_id))
        await s.commit()


@pytest.fixture
async def eng_sales(session_factory, seed, depts):
    """The engineer user, sitting in Sales. Not a real admin."""
    await _join(session_factory, seed["engineer_id"], depts["Sales"])
    return await login(None, "eng@test.io")


async def _status(client, auth):
    res = await client.get("/api/v1/training/status", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


async def _attest(client, auth, role="sales", **over):
    body = {"role": role, "training_date": date.today().isoformat(),
            "trainer_name": "C. Demmler", "confirmed": True, **over}
    return await client.post("/api/v1/training/attest", json=body, headers=auth)


async def _attempt(client, auth, task_key, result="passed", role="sales"):
    return await client.post("/api/v1/training/attempts", headers=auth, json={
        "role": role, "task_key": task_key, "result": result,
        "detail": {"hint": "x"} if result == "failed" else None,
        "duration_seconds": 42})


# --------------------------------------------------------------- curriculum

async def test_curriculum_keys_are_the_contract():
    assert {r: c.tasks for r, c in svc.CURRICULA.items()} == EXPECTED_TASKS


async def test_no_role_asks_more_than_five_tasks():
    for cur in svc.CURRICULA.values():
        assert 1 <= len(cur.tasks) <= svc.MAX_TASKS_PER_ROLE, cur.role


async def test_departments_map_to_roles_as_ruled():
    assert svc.roles_for_departments(["Sales"]) == ["sales"]
    assert svc.roles_for_departments(["Project Manager"]) == ["project_management"]
    for d in ("Development", "Tool Engineer", "Manufacturing Engineer",
              "Process Engineer", "APQP", "Packaging Engineer"):
        assert svc.roles_for_departments([d]) == ["engineering"], d
    assert svc.roles_for_departments(["Tool Engineer", "APQP"]) == ["engineering"]
    assert svc.roles_for_departments(["Logistics"]) == []
    assert svc.roles_for_departments(["Finance", "Quality", "Scheduling"]) == [
        "scheduling", "quality", "finance"]


async def test_software_version_is_the_ecr_version():
    assert SOFTWARE_VERSION.startswith("ECR ")


# --------------------------------------------------------------- status

async def test_user_without_training_department_owes_nothing(client, seed, depts):
    admin = await login(client, "admin@test.io")
    st = await _status(client, admin)
    assert st["has_roles"] is False and st["roles"] == []
    assert st["cleared"] is True
    assert {c["role"] for c in st["catalog"]} == set(EXPECTED_TASKS)
    assert st["gate_enabled"] is False and st["gate_source"] == "default"
    assert st["software_version"] == SOFTWARE_VERSION


async def test_department_member_owes_its_role(client, eng_sales):
    st = await _status(client, eng_sales)
    assert [r["role"] for r in st["roles"]] == ["sales"]
    sales = st["roles"][0]
    assert sales["status"] is None and sales["cleared"] is False
    assert sales["open_reason"]
    assert [t["key"] for t in sales["tasks"]] == ["sales_start_change"]


async def test_acting_as_owes_exactly_that_departments_role(client, seed, depts):
    admin = await login(client, "admin@test.io")
    st = await _status(client, {**admin, ACTS_AS: str(depts["Tool Engineer"])})
    assert [r["role"] for r in st["roles"]] == ["engineering"]
    assert st["acting_as"] == "Tool Engineer"


# --------------------------------------------------------------- attest

async def test_attest_opens_a_pending_record(client, eng_sales, session_factory):
    res = await _attest(client, eng_sales)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "pending_tasks"
    assert body["trainer_name"] == "C. Demmler"
    assert body["software_version"] is None  # stamped at the pass, not here
    async with session_factory() as s:
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert "training.attested" in actions


async def test_attest_refusals(client, eng_sales, seed):
    assert (await _attest(client, eng_sales, confirmed=False)).status_code == 422
    future = (date.today() + timedelta(days=2)).isoformat()
    assert (await _attest(client, eng_sales, training_date=future)).status_code == 422
    assert (await _attest(client, eng_sales, trainer_user_id=seed["engineer_id"])
            ).status_code == 422
    assert (await _attest(client, eng_sales, role="quality")).status_code == 403
    assert (await _attest(client, eng_sales, role="nonsense")).status_code == 422
    assert (await _attest(client, eng_sales)).status_code == 201
    assert (await _attest(client, eng_sales)).status_code == 409


# --------------------------------------------------------------- attempts

async def test_attempt_needs_an_attestation_and_a_known_task(client, eng_sales):
    assert (await _attempt(client, eng_sales, "sales_start_change")).status_code == 409
    await _attest(client, eng_sales)
    assert (await _attempt(client, eng_sales, "pm_set_priority")).status_code == 422
    assert (await _attempt(client, eng_sales, "sales_start_change", result="maybe")
            ).status_code == 422


async def test_fail_then_pass_goes_active_and_stamps_the_version(
        client, eng_sales, session_factory):
    await _attest(client, eng_sales)
    res = await _attempt(client, eng_sales, "sales_start_change", result="failed")
    assert res.status_code == 201
    assert res.json()["attempt_no"] == 1
    assert res.json()["role_state"]["status"] == "pending_tasks"

    res = await _attempt(client, eng_sales, "sales_start_change")
    body = res.json()
    assert body["attempt_no"] == 2
    state = body["role_state"]
    assert state["status"] == "active" and state["cleared"] is True
    assert state["software_version"] == SOFTWARE_VERSION
    passed_at = state["tasks_passed_at"]
    assert passed_at

    # A retake never moves the pass.
    again = (await _attempt(client, eng_sales, "sales_start_change")).json()
    assert again["role_state"]["tasks_passed_at"] == passed_at

    async with session_factory() as s:
        attempts = (await s.execute(select(TrainingAttempt))).scalars().all()
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert [a.result for a in attempts] == ["failed", "passed", "passed"]
    assert actions.count("training.tasks_passed") == 1

    st = await _status(client, eng_sales)
    assert st["cleared"] is True


async def test_engineering_needs_every_task(client, session_factory, seed, depts):
    await _join(session_factory, seed["engineer_id"], depts["Tool Engineer"])
    auth = await login(client, "eng@test.io")
    await _attest(client, auth, role="engineering")
    r = await _attempt(client, auth, "eng_answer_checklist_row", role="engineering")
    assert r.json()["role_state"]["status"] == "pending_tasks"
    r = await _attempt(client, auth, "eng_submit_assessment", role="engineering")
    assert r.json()["role_state"]["status"] == "active"


# --------------------------------------------------------------- publish

async def _pass_sales(client, auth):
    await _attest(client, auth)
    await _attempt(client, auth, "sales_start_change")


async def test_publish_is_for_admin_quality_or_pm(
        client, session_factory, seed, depts, eng_sales):
    # eng is a plain department member (not a real admin, not Quality/PM)
    res = await client.post("/api/v1/training/versions", headers=eng_sales,
                            json={"role": "sales", "summary": "x"})
    assert res.status_code == 403
    await _join(session_factory, seed["engineer_id"], depts["Quality"])
    res = await client.post("/api/v1/training/versions", headers=eng_sales,
                            json={"role": "sales", "summary": "New start form"})
    assert res.status_code == 201, res.text
    assert res.json()["version"] == 2
    assert res.json()["software_version"] == SOFTWARE_VERSION


async def test_publish_supersedes_and_carries_the_attestation(
        client, seed, eng_sales, session_factory):
    await _pass_sales(client, eng_sales)
    admin = await login(client, "admin@test.io")
    res = await client.post("/api/v1/training/versions", headers=admin,
                            json={"role": "sales", "summary": "Deadline moved"})
    assert res.status_code == 201

    st = await _status(client, eng_sales)
    sales = st["roles"][0]
    assert sales["required_version"] == 2
    assert sales["status"] == "pending_tasks"
    assert sales["cleared"] is False
    assert sales["retrain_due"] is True
    assert sales["attestation_carried_forward"] is True
    assert sales["trainer_name"] == "C. Demmler"
    assert sales["retrain_summary"] == "Deadline moved"

    async with session_factory() as s:
        rows = (await s.execute(select(TrainingSignoff).order_by(
            TrainingSignoff.version))).scalars().all()
    assert [(r.version, r.status) for r in rows] == [
        (1, "superseded"), (2, "pending_tasks")]
    assert rows[1].carried_from_id == rows[0].id

    # No new attestation is asked: the tasks alone clear version 2.
    r = await _attempt(client, eng_sales, "sales_start_change")
    assert r.json()["role_state"]["status"] == "active"


async def test_publish_refuses_unknown_role_and_empty_summary(client, seed):
    admin = await login(client, "admin@test.io")
    assert (await client.post("/api/v1/training/versions", headers=admin,
                              json={"role": "nope", "summary": "x"})).status_code == 422
    assert (await client.post("/api/v1/training/versions", headers=admin,
                              json={"role": "sales", "summary": "   "})).status_code == 422


# --------------------------------------------------------------- roster

async def test_roster_records_attendance_lists_and_exports(client, seed, depts):
    admin = await login(client, "admin@test.io")
    res = await client.post("/api/v1/training/roster", headers=admin, json={
        "user_id": seed["engineer_id"], "role": "quality",
        "training_date": date.today().isoformat(), "trainer_name": "QA Lead"})
    assert res.status_code == 201, res.text
    row = res.json()
    assert row["trainer_source"] == "roster"
    assert row["recorded_by"] == "admin@test.io"
    assert row["status"] == "pending_tasks"

    dup = await client.post("/api/v1/training/roster", headers=admin, json={
        "user_id": seed["engineer_id"], "role": "quality",
        "training_date": date.today().isoformat(), "trainer_name": "QA Lead"})
    assert dup.status_code == 409

    lst = (await client.get("/api/v1/training/roster", headers=admin)).json()
    assert lst["pending"] == 1 and lst["active"] == 0
    assert lst["items"][0]["email"] == "eng@test.io"

    csv_res = await client.get("/api/v1/training/roster.csv", headers=admin)
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    lines = csv_res.text.strip().splitlines()
    assert lines[0].startswith("user_id,email,name,role")
    assert "eng@test.io" in lines[1] and "quality" in lines[1]


async def test_people_lists_who_owes_what(client, eng_sales):
    admin = await login(client, "admin@test.io")
    res = await client.get("/api/v1/training/people", headers=admin)
    assert res.status_code == 200, res.text
    assert [(p["email"], p["roles"]) for p in res.json()] == [("eng@test.io", ["sales"])]
    assert (await client.get("/api/v1/training/people", headers=eng_sales)
            ).status_code == 403


async def test_roster_is_for_managers_only(client, eng_sales):
    assert (await client.get("/api/v1/training/roster", headers=eng_sales)
            ).status_code == 403
    assert (await client.get("/api/v1/training/roster.csv", headers=eng_sales)
            ).status_code == 403


# --------------------------------------------------------------- the gate

async def _start_change(client, auth, seed):
    return await client.post("/api/v1/changes", headers=auth, json={
        "project_id": seed["project_id"], "title": "gate", "reason": "r",
        "change_type": "physical_part"})


def _refused_by_training(res) -> bool:
    return res.status_code == 403 and "Training required" in res.text


async def test_gate_is_off_by_default_and_blocks_nothing(client, seed, eng_sales):
    """Ruling 2026-09-25: recorded, not blocking. An untrained Sales member
    starts a change with the gate in its default state."""
    st = await _status(client, eng_sales)
    assert st["gate_enabled"] is False and st["cleared"] is False
    res = await _start_change(client, eng_sales, seed)
    assert not _refused_by_training(res)
    assert res.status_code in (200, 201), res.text


async def test_gate_when_switched_on_refuses_writes_until_trained(
        client, seed, eng_sales):
    admin = await login(client, "admin@test.io")
    res = await client.put("/api/v1/training/settings", headers=admin,
                           json={"training_gate": True})
    assert res.status_code == 200 and res.json() == {"training_gate": True,
                                                     "source": "org"}
    refused = await _start_change(client, eng_sales, seed)
    assert _refused_by_training(refused)
    assert refused.headers["x-training-required"] == "sales"
    # Reads always pass, and the training routes stay reachable.
    assert (await client.get("/api/v1/changes", headers=eng_sales)).status_code == 200
    await _pass_sales(client, eng_sales)
    assert not _refused_by_training(await _start_change(client, eng_sales, seed))

    # Switched back off: nothing refused, whatever the record says.
    await client.put("/api/v1/training/settings", headers=admin,
                     json={"training_gate": False})
    admin_pub = await client.post("/api/v1/training/versions", headers=admin,
                                  json={"role": "sales", "summary": "v2"})
    assert admin_pub.status_code == 201
    assert not _refused_by_training(await _start_change(client, eng_sales, seed))


async def test_gate_exempts_acting_as_and_users_without_a_role(client, seed, depts):
    admin = await login(client, "admin@test.io")
    await client.put("/api/v1/training/settings", headers=admin,
                     json={"training_gate": True})
    # The admin sits in no training department: owes nothing.
    assert not _refused_by_training(await _start_change(client, admin, seed))
    acting = {**admin, ACTS_AS: str(depts["Sales"])}
    assert not _refused_by_training(await _start_change(client, acting, seed))


async def test_gate_switch_is_admin_only_and_env_pins_it(
        client, seed, eng_sales, monkeypatch):
    assert (await client.put("/api/v1/training/settings", headers=eng_sales,
                             json={"training_gate": True})).status_code == 403
    admin = await login(client, "admin@test.io")
    monkeypatch.setattr(get_settings(), "training_gate", False)
    res = await client.put("/api/v1/training/settings", headers=admin,
                           json={"training_gate": True})
    assert res.status_code == 409
    got = (await client.get("/api/v1/training/settings", headers=admin)).json()
    assert got == {"training_gate": False, "source": "env"}
    monkeypatch.setattr(get_settings(), "training_gate", True)
    assert _refused_by_training(await _start_change(client, eng_sales, seed))


async def test_status_transitions_are_a_pure_function_of_the_stamps():
    from datetime import datetime

    row = TrainingSignoff(user_id=1, role="sales", version=1)
    row.attempts = []
    assert svc.recompute_status(row) == "pending_tasks"
    row.tasks_passed_at = datetime.utcnow()
    assert svc.recompute_status(row) == "active"
    row.superseded_at = datetime.utcnow()
    assert svc.recompute_status(row) == "superseded"
