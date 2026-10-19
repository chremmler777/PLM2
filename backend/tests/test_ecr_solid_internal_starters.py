"""ECR-solid P3: Development, Process Engineer and Tool Engineer may start
INTERNAL changes (can_start_internal_change) and then lead them. A customer
change stays Sales' and Project Management's; other departments start
nothing."""
import pytest
import pytest_asyncio

from app.models.workflow import Department, UserDepartment
from tests.conftest import KEEP_LEAD_RULE, login

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"


@pytest_asyncio.fixture
async def depts(session_factory, seed):
    ids = {}
    async with session_factory() as s:
        for i, (n, cust, internal) in enumerate((
                ("Sales", True, False), ("Project Manager", True, False),
                ("Development", False, True), ("Process Engineer", False, True),
                ("Tool Engineer", False, True), ("Quality", False, False))):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=cust, can_start_internal_change=internal)
            s.add(d); await s.flush(); ids[n] = d.id
        await s.commit()
    return ids


async def _join(session_factory, user_id, dept_id):
    async with session_factory() as s:
        s.add(UserDepartment(user_id=user_id, department_id=dept_id))
        await s.commit()


def _body(seed, customer):
    return {"project_id": seed["project_id"], "title": "internal fix",
            "reason": "flash on rib", "change_type": "physical_part",
            "customer_relevant": customer}


@pytest.mark.parametrize("dept", ["Development", "Process Engineer", "Tool Engineer"])
async def test_engineering_starts_internal_and_leads_it(client, seed, depts,
                                                        session_factory, dept):
    await _join(session_factory, seed["engineer_id"], depts[dept])
    eng = await login(client, "eng@test.io", admin=False)
    perms = (await client.get("/api/v1/changes/permissions", headers=eng)).json()
    assert perms["can_start_change"] is False
    assert perms["can_start_internal_change"] is True
    res = await client.post("/api/v1/changes", json=_body(seed, False),
                            headers={**eng, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["origin"] == "internal"
    assert res.json()["lead_id"] == seed["engineer_id"]


async def test_engineering_may_not_start_a_customer_change(client, seed, depts,
                                                           session_factory):
    await _join(session_factory, seed["engineer_id"], depts["Development"])
    eng = await login(client, "eng@test.io", admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed, True), headers=eng)
    assert res.status_code == 403
    assert "internal" in res.json()["detail"]


async def test_quality_starts_nothing(client, seed, depts, session_factory):
    await _join(session_factory, seed["engineer_id"], depts["Quality"])
    eng = await login(client, "eng@test.io", admin=False)
    perms = (await client.get("/api/v1/changes/permissions", headers=eng)).json()
    assert perms["can_start_change"] is False
    assert perms["can_start_internal_change"] is False
    res = await client.post("/api/v1/changes", json=_body(seed, False), headers=eng)
    assert res.status_code == 403


async def test_sales_internal_change_is_led_by_the_project_pm(client, seed, depts,
                                                               session_factory):
    """Only an engineering raiser leads: Sales raising an internal change
    gets the project's standard PM (none here), not itself."""
    admin = await login(client, "admin@test.io")
    sales = {**admin, ACTS: str(depts["Sales"])}
    res = await client.post("/api/v1/changes", json=_body(seed, False),
                            headers={**sales, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["lead_id"] is None


async def test_engineering_lead_gets_the_kickoff_task(client, seed, depts, session_factory):
    """No dead end: the raiser who leads its internal change sees "Hand over
    to scoping" in My Tasks and may make the hop; a colleague may not."""
    await _join(session_factory, seed["engineer_id"], depts["Process Engineer"])
    eng = await login(client, "eng@test.io", admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed, False),
                            headers={**eng, KEEP_LEAD_RULE: "1"})
    cid = res.json()["id"]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=eng)).json()
    assert any(t["kind"] == "kickoff" and t["change_id"] == cid for t in tasks)
    admin = await login(client, "admin@test.io")
    other = {**admin, ACTS: str(depts["Development"])}
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=other)).json()
    assert not any(t["kind"] == "kickoff" and t["change_id"] == cid for t in tasks)
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=other)).json()
    assert st["can_transition"]["scoping"] is False


# --- L4 review 2: spec §3 "Internal: raiser's department auto-R" -------------

async def _internal_in_scoping(client, seed, depts, session_factory):
    from sqlalchemy import update
    from app.models.change import ChangeRequest
    await _join(session_factory, seed["engineer_id"], depts["Process Engineer"])
    eng = await login(client, "eng@test.io", admin=False)
    res = await client.post("/api/v1/changes", json=_body(seed, False),
                            headers={**eng, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(status="scoping"))
        await s.commit()
    return cid


def _meeting_body(rasic, **extra):
    return {"channel": "meeting", "participants": [{"name": "Eva"}],
            "department_rasic": rasic, "cost_carrier": "internal", **extra}


async def test_raiser_department_is_auto_r_and_waived_only_with_a_reason(
        client, seed, depts, session_factory):
    cid = await _internal_in_scoping(client, seed, depts, session_factory)
    admin = await login(client, "admin@test.io")
    proc, tool = str(depts["Process Engineer"]), str(depts["Tool Engineer"])
    rec = (await client.get(f"/api/v1/changes/{cid}/recommended-departments",
                            headers=admin)).json()
    row = next(r for r in rec if r["id"] == depts["Process Engineer"])
    assert row["rasic_letter"] == "R" and row["raiser"] is True
    url = f"/api/v1/changes/{cid}/meetings"
    # negative: left out (or only C) without a reason, or with an empty one
    for body in (_meeting_body({tool: "R"}), _meeting_body({tool: "R", proc: "C"}),
                 _meeting_body({tool: "R"}, raiser_waive_reason="ok")):
        res = await client.post(url, json=body, headers=admin)
        assert res.status_code == 400, body
        assert "Process Engineer raised this internal change" in res.json()["detail"]
    res = await client.post(url, json=_meeting_body({tool: "R", proc: "R"}), headers=admin)
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    # an edit that drops it needs the reason too, and is logged
    res = await client.patch(f"{url}/{mid}", json={"department_rasic": {tool: "R"}},
                             headers=admin)
    assert res.status_code == 400
    res = await client.patch(f"{url}/{mid}", json={
        "department_rasic": {tool: "R"},
        "raiser_waive_reason": "Only the tool insert changes, no process step"},
        headers=admin)
    assert res.status_code == 200, res.text
    log = await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin)
    assert log.status_code == 200, log.text
    assert any(e["action"] == "raiser_department_waived" for e in log.json())


async def test_raiser_department_rule_off_with_the_switch(
        client, seed, depts, session_factory, monkeypatch):
    from app.services import cm_switches
    monkeypatch.setattr(cm_switches, "SCOPING_V2", False)
    cid = await _internal_in_scoping(client, seed, depts, session_factory)
    admin = await login(client, "admin@test.io")
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json=_meeting_body(
        {str(depts["Tool Engineer"]): "R"}), headers=admin)
    assert res.status_code == 200, res.text


async def test_a2_06_meeting_without_departments_cannot_skip_the_raiser_waiver(
        client, seed, depts, session_factory):
    """Close-out A2-06: a meeting recorded with no departments, then edited
    to route others, still owes the logged reason for leaving the raiser's
    department out (an empty 'before' is not 'already out')."""
    cid = await _internal_in_scoping(client, seed, depts, session_factory)
    admin = await login(client, "admin@test.io")
    tool = str(depts["Tool Engineer"])
    url = f"/api/v1/changes/{cid}/meetings"
    res = await client.post(url, json={"channel": "meeting",
                                       "participants": [{"name": "Eva"}],
                                       "cost_carrier": "internal"}, headers=admin)
    assert res.status_code == 200, res.text
    mid = res.json()["id"]
    # negative: departments edited in without the raiser and without a reason
    res = await client.patch(f"{url}/{mid}", json={"department_rasic": {tool: "R"}},
                             headers=admin)
    assert res.status_code == 400, res.text
    assert "Process Engineer raised this internal change" in res.json()["detail"]
    res = await client.patch(f"{url}/{mid}", json={"selected_department_ids": [int(tool)]},
                             headers=admin)
    assert res.status_code == 400, res.text
    res = await client.patch(f"{url}/{mid}", json={
        "department_rasic": {tool: "R"},
        "raiser_waive_reason": "Only the tool insert changes, no process step"},
        headers=admin)
    assert res.status_code == 200, res.text
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin)).json()
    assert any(e["action"] == "raiser_department_waived" for e in log)


# --- D1 (Christoph 2026-10-19): Manufacturing Engineer starts internal ECRs --

def _load_migration_147():
    """By file path; the real alembic package first, as
    test_change_starter_departments does (backend/alembic shadows it)."""
    import importlib.util
    import pathlib
    import sys
    path = (pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
            / "147_manufacturing_engineer_internal_starter.py")
    backend_dir = str(path.parents[2])
    for name in list(sys.modules):
        if name == "alembic" or name.startswith("alembic."):
            if (getattr(sys.modules[name], "__file__", "") or "").startswith(backend_dir):
                del sys.modules[name]
    original = sys.path[:]
    sys.path[:] = [p for p in sys.path if p not in ("", backend_dir)]
    try:
        import alembic  # noqa: F401
        import alembic.op  # noqa: F401
    finally:
        sys.path[:] = original
    spec = importlib.util.spec_from_file_location("migration_147", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_manufacturing_engineer_starts_internal_after_migration_147(
        client, seed, depts, session_factory, db_engine):
    """D1: migration 147 flags Manufacturing Engineer (idempotent); its member
    then starts an internal change and leads it, like the other engineering
    starters. Before the flag (NEGATIVE) it starts nothing, and it never
    starts a customer change."""
    async with session_factory() as s:
        me = Department(name="Manufacturing Engineer", flow_type="action",
                        is_active=True, sort_order=9)
        s.add(me); await s.flush(); me_id = me.id
        await s.commit()
    await _join(session_factory, seed["engineer_id"], me_id)
    eng = await login(client, "eng@test.io", admin=False)
    perms = (await client.get("/api/v1/changes/permissions", headers=eng)).json()
    assert perms["can_start_internal_change"] is False          # before 147
    assert (await client.post("/api/v1/changes", json=_body(seed, False),
                              headers=eng)).status_code == 403

    mig = _load_migration_147()
    for _ in range(2):                                         # idempotent
        async with db_engine.begin() as conn:
            await conn.run_sync(mig.flag_internal_starters)
    perms = (await client.get("/api/v1/changes/permissions", headers=eng)).json()
    assert perms["can_start_change"] is False
    assert perms["can_start_internal_change"] is True
    res = await client.post("/api/v1/changes", json=_body(seed, False),
                            headers={**eng, KEEP_LEAD_RULE: "1"})
    assert res.status_code in (200, 201), res.text
    assert res.json()["origin"] == "internal"
    assert res.json()["lead_id"] == seed["engineer_id"]
    # NEGATIVE: still no customer change, and Quality is not flagged
    res = await client.post("/api/v1/changes", json=_body(seed, True), headers=eng)
    assert res.status_code == 403
    async with session_factory() as s:
        q = await s.get(Department, depts["Quality"])
        assert q.can_start_internal_change is False


def test_seed_names_manufacturing_engineer_an_internal_starter():
    from app.main import INTERNAL_STARTER_DEPARTMENTS
    assert INTERNAL_STARTER_DEPARTMENTS == {
        "Development", "Process Engineer", "Tool Engineer", "Manufacturing Engineer"}
