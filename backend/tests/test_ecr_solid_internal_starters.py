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
