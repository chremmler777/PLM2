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

async def test_roster_records_attendance_lists_and_exports(
        client, session_factory, seed, depts):
    await _join(session_factory, seed["engineer_id"], depts["Quality"])
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


# --------------------------------------------------------------- review fixes

async def test_roster_csv_neutralises_formulas(client, seed, eng_sales):
    evil = '=HYPERLINK("http://evil","x")'
    assert (await _attest(client, eng_sales, trainer_name=evil)).status_code == 201
    admin = await login(client, "admin@test.io")
    text = (await client.get("/api/v1/training/roster.csv", headers=admin)).text
    import csv as _csv, io as _io
    rows = list(_csv.DictReader(_io.StringIO(text)))
    assert rows[0]["trainer"] == "'" + evil
    from app.api.v1.training import _csv_cell
    for lead in ("=", "+", "-", "@", "\t", "\r"):
        assert _csv_cell(lead + "x") == "'" + lead + "x"
    assert _csv_cell("C. Demmler") == "C. Demmler"
    assert _csv_cell(3) == 3


async def test_attempt_detail_is_capped(client, eng_sales):
    await _attest(client, eng_sales)
    big = {"hint": "x" * 5000}
    res = await client.post("/api/v1/training/attempts", headers=eng_sales, json={
        "role": "sales", "task_key": "sales_start_change", "result": "failed",
        "detail": big})
    assert res.status_code == 422 and "KB" in res.text
    ok = await client.post("/api/v1/training/attempts", headers=eng_sales, json={
        "role": "sales", "task_key": "sales_start_change", "result": "failed",
        "detail": {"hint": "x" * 1000}})
    assert ok.status_code == 201, ok.text


async def test_attest_trainer_user_must_be_an_active_colleague(client, seed, eng_sales):
    assert (await _attest(client, eng_sales, trainer_user_id=987654)).status_code == 400
    assert (await _attest(client, eng_sales, trainer_user_id=seed["inactive_id"])
            ).status_code == 400
    # Whitespace is no name.
    assert (await _attest(client, eng_sales, trainer_name="   ")).status_code == 422
    # Named by id only: the name defaults to that user's.
    res = await _attest(client, eng_sales, trainer_name=None,
                        trainer_user_id=seed["admin_id"])
    assert res.status_code == 201, res.text
    assert res.json()["trainer_name"] == "Admin"


async def test_attest_trainer_from_another_org_is_refused(
        client, session_factory, seed, eng_sales):
    from app.models.entities import Organization, User as _User
    async with session_factory() as s:
        other = Organization(name="Other", code="other", is_active=True)
        s.add(other)
        await s.flush()
        stranger = _User(organization_id=other.id, username="x", email="x@other.io",
                         full_name="Stranger", hashed_password="!", role="engineer",
                         is_active=True, mfa_enabled=False)
        s.add(stranger)
        await s.commit()
        sid = stranger.id
    assert (await _attest(client, eng_sales, trainer_user_id=sid)).status_code == 400
    admin = await login(client, "admin@test.io")
    # ...and a manager cannot roster somebody outside the organisation.
    res = await client.post("/api/v1/training/roster", headers=admin, json={
        "user_id": sid, "role": "sales", "training_date": date.today().isoformat(),
        "trainer_name": "QA Lead"})
    assert res.status_code == 404


async def test_roster_checks_the_trainee_and_the_trainer(client, seed, depts, eng_sales):
    admin = await login(client, "admin@test.io")

    def entry(**over):
        return {"user_id": seed["engineer_id"], "role": "sales",
                "training_date": date.today().isoformat(), "trainer_name": "QA Lead",
                **over}

    post = lambda body: client.post("/api/v1/training/roster", headers=admin, json=body)  # noqa: E731
    assert (await post(entry(trainer_name="   "))).status_code == 422
    # eng sits in Sales only: Finance is not owed.
    res = await post(entry(role="finance"))
    assert res.status_code == 400 and "owes" in res.text
    assert (await post(entry(user_id=seed["inactive_id"]))).status_code == 400
    # Four eyes: nobody rosters themselves.
    res = await post(entry(user_id=seed["admin_id"]))
    assert res.status_code == 403 and "Four eyes" in res.text
    assert (await post(entry())).status_code == 201


async def test_concurrent_publish_is_a_conflict_not_a_500(client, seed, monkeypatch):
    admin = await login(client, "admin@test.io")
    assert (await client.post("/api/v1/training/versions", headers=admin,
                              json={"role": "sales", "summary": "v2"})).status_code == 201

    # The second publisher read the required version before the first committed.
    async def stale(db):
        return {r: 1 for r in svc.CURRICULA}
    monkeypatch.setattr(svc, "required_versions", stale)
    res = await client.post("/api/v1/training/versions", headers=admin,
                            json={"role": "sales", "summary": "also v2"})
    assert res.status_code == 409, res.text


async def test_acting_as_is_practice_only(client, seed, depts):
    admin = await login(client, "admin@test.io")
    acting = {**admin, ACTS_AS: str(depts["Sales"])}
    st = await _status(client, acting)
    assert st["practice_only"] is True
    res = await _attest(client, acting)
    assert res.status_code == 403 and "practice only" in res.text
    res = await _attempt(client, acting, "sales_start_change")
    assert res.status_code == 403 and "practice only" in res.text
    assert (await _status(client, admin))["practice_only"] is False


# ---- the gate as an allowlist

def _gated_writes() -> set[tuple[str, str]]:
    import importlib
    from fastapi.routing import APIRoute
    mods = [f"app.api.v1.changes.{m}" for m in (
        "changes", "plan_offer", "validation_issues", "actual_costs", "mother_plant",
        "early_stage", "engineering_review", "costing_context")] + ["app.api.v1.items.intakes"]
    out = set()
    for mod in mods:
        for r in importlib.import_module(mod).router.routes:
            if isinstance(r, APIRoute):
                out |= {(m, r.path) for m in r.methods - {"GET", "HEAD", "OPTIONS"}}
    return out


async def test_every_gated_write_is_classified():
    from app.api.v1.training import GATE_EXEMPT_WRITES, GUARDED_WRITES
    writes = _gated_writes()
    assert not (GUARDED_WRITES & GATE_EXEMPT_WRITES)
    unclassified = writes - GUARDED_WRITES - GATE_EXEMPT_WRITES
    assert not unclassified, f"decide guard or exempt: {sorted(unclassified)}"
    stale = (GUARDED_WRITES | GATE_EXEMPT_WRITES) - writes
    assert not stale, f"no such route: {sorted(stale)}"


async def _gate_on(client):
    admin = await login(client, "admin@test.io")
    res = await client.put("/api/v1/training/settings", headers=admin,
                           json={"training_gate": True})
    assert res.status_code == 200
    return admin


async def test_gate_never_refuses_read_style_posts_or_reference_data(
        client, seed, depts, eng_sales, session_factory):
    await _gate_on(client)
    res = await client.post("/api/v1/changes/999999/impact-tree/suggest",
                            headers=eng_sales, json={"part_ids": []})
    assert not _refused_by_training(res), res.text
    # a Sales member who is also Quality still reaches the reference lists
    res = await client.post("/api/v1/changes/reference/risk-types", headers=eng_sales,
                            json={"key": "x", "name": "X"})
    assert not _refused_by_training(res), res.text
    # ...while the guarded writes on the same routers are refused
    assert _refused_by_training(await client.patch(
        "/api/v1/changes/999999", headers=eng_sales, json={"priority": "high"}))
    assert _refused_by_training(await client.post(
        "/api/v1/changes/999999/transition", headers=eng_sales, json={"to": "x"}))
    assert _refused_by_training(await client.post(
        "/api/v1/intakes/999999/decide", headers=eng_sales,
        json={"route": "administrative", "reason": "r"}))


async def test_gate_costs_nothing_on_unguarded_routes_and_authenticates_once(
        client, seed, eng_sales):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    stmts: list[str] = []

    def cb(conn, cursor, statement, params, context, executemany):
        stmts.append(statement)

    event.listen(Engine, "before_cursor_execute", cb)
    try:
        await client.post("/api/v1/changes/999999/impact-tree/suggest",
                          headers=eng_sales, json={"part_ids": []})
        unguarded = list(stmts)
        stmts.clear()
        await client.patch("/api/v1/changes/999999", headers=eng_sales,
                           json={"priority": "high"})
        guarded = list(stmts)
    finally:
        event.remove(Engine, "before_cursor_execute", cb)
    assert not [s for s in unguarded if "org_settings" in s]
    assert len([s for s in guarded if "org_settings" in s]) == 1
    # get_current_user ran once: one lookup of the user by email.
    by_email = [s for s in guarded if "FROM users" in s and "users.email" in s]
    assert len(by_email) == 1, by_email


async def test_blank_training_gate_env_means_unset(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("TRAINING_GATE", "")
    assert Settings().training_gate is None
    monkeypatch.setenv("TRAINING_GATE", "  ")
    assert Settings().training_gate is None
    monkeypatch.setenv("TRAINING_GATE", "0")
    assert Settings().training_gate is False
    monkeypatch.setenv("TRAINING_GATE", "true")
    assert Settings().training_gate is True


# --------------------------------------------------------------- robustness
# Final walk: a hot reload once left the gate calling a helper the reloaded
# service no longer had (AttributeError training.gate_may_be_on) and every
# guarded save answered 500. The gate must never break a save.

@pytest.mark.parametrize("setting", ["default", "org_off", "org_on", "env_off", "env_on"])
async def test_guarded_write_succeeds_for_a_trained_user_in_every_gate_setting(
        client, seed, eng_sales, monkeypatch, setting):
    admin = await login(client, "admin@test.io")
    await _pass_sales(client, eng_sales)
    if setting.startswith("org_"):
        res = await client.put("/api/v1/training/settings", headers=admin,
                               json={"training_gate": setting == "org_on"})
        assert res.status_code == 200, res.text
    elif setting.startswith("env_"):
        monkeypatch.setattr(get_settings(), "training_gate", setting == "env_on")
    res = await _start_change(client, eng_sales, seed)
    assert res.status_code in (200, 201), res.text


@pytest.mark.parametrize("broken", ["gate_enabled", "blocking_roles"])
async def test_a_broken_gate_lets_the_write_through(
        client, seed, eng_sales, monkeypatch, broken):
    """Whatever the gate trips over (a missing helper after a reload, a
    failing read) the guarded write still goes through."""
    admin = await login(client, "admin@test.io")
    await client.put("/api/v1/training/settings", headers=admin,
                     json={"training_gate": True})

    async def boom(*a, **k):
        raise AttributeError("module 'app.services.training' has no attribute "
                             "'gate_may_be_on'")

    monkeypatch.setattr(svc, broken, boom)
    res = await _start_change(client, eng_sales, seed)
    assert res.status_code in (200, 201), res.text


async def test_a_missing_gate_helper_lets_the_write_through(
        client, seed, eng_sales, monkeypatch):
    monkeypatch.delattr(svc, "gate_enabled")
    res = await _start_change(client, eng_sales, seed)
    assert res.status_code in (200, 201), res.text
