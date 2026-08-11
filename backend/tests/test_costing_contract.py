"""The costing contract the shipped UI already speaks: per-part minutes, lead
time, the summation rollups they feed, and who still owes a number."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeRequest
from app.models.change_cost import AssessmentActivity, DepartmentRate
from app.models.entities import Plant, Project
from app.models.workflow import Department, UserDepartment
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def costing(session_factory, seed):
    """A change in costing with two feasible departments, two plants, rates."""
    async with session_factory() as s:
        tool = Department(name="Tool Engineer", flow_type="action", is_active=True)
        dev = Department(name="Development", flow_type="action", is_active=True)
        s.add_all([tool, dev])
        await s.flush()
        project = await s.get(Project, seed["project_id"])
        usa = Plant(organization_id=seed["org_id"], name="USA", code="usa",
                    location="US", is_active=True)
        s.add(usa)
        await s.flush()
        for dept in (tool, dev):
            for plant_id, rate in ((project.plant_id, 65.0), (usa.id, 100.0)):
                s.add(DepartmentRate(department_id=dept.id, plant_id=plant_id,
                                     hourly_rate=rate, min_factor=1.0))
        change = ChangeRequest(
            change_number="C-CO-1", title="costing", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing")
        s.add(change)
        await s.flush()
        rows = {}
        for dept in (tool, dev):
            a = ChangeAssessment(change_id=change.id, department_id=dept.id,
                                 stage_order=1, verdict="feasible")
            s.add(a)
            await s.flush()
            rows[dept.name] = a.id
        await s.commit()
        return {"change_id": change.id, "tool": tool.id, "dev": dev.id,
                "assessments": rows, "home_plant": project.plant_id,
                "usa_plant": usa.id}


async def _member(client, session_factory, seed, dept_id, email):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                 email=email, full_name=email, role="engineer",
                 hashed_password=get_password_hash("member-secret-1"),
                 is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept_id))
        await s.commit()
        return await login(client, email)


# --- (1) minutes per part ---------------------------------------------------

async def test_minutes_per_part_round_trips_including_negative(
        client, admin_auth, costing):
    url = (f"/api/v1/changes/{costing['change_id']}"
           f"/assessments/{costing['assessments']['Tool Engineer']}/cost-lines")
    res = await client.put(url, json={"lines": [
        {"plant_id": costing["home_plant"], "activity_label": "Cycle time",
         "cost_kind": "lifecycle", "demand_hours": 0.0, "minutes_per_part": 0.25},
        {"plant_id": costing["home_plant"], "activity_label": "Saved handling",
         "cost_kind": "lifecycle", "minutes_per_part": -0.1},
        {"plant_id": costing["home_plant"], "activity_label": "Rework",
         "cost_kind": "one_time", "demand_hours": 1.0},
    ]}, headers=admin_auth)
    assert res.status_code == 200, res.text
    lines = res.json()
    assert lines[0]["minutes_per_part"] == 0.25
    assert lines[1]["minutes_per_part"] == -0.1     # a saving is a real answer
    assert lines[2]["minutes_per_part"] is None     # one-time carries none

    fetched = (await client.get(url, headers=admin_auth)).json()
    assert [l["minutes_per_part"] for l in fetched] == [0.25, -0.1, None]


# --- (2) lead time ----------------------------------------------------------

async def test_department_member_sets_its_own_lead_time(
        client, session_factory, seed, costing):
    tool_member = await _member(client, session_factory, seed, costing["tool"],
                                "tooling@test.io")
    res = await client.post(f"/api/v1/changes/{costing['change_id']}/cost-lead-time",
                            json={"department_id": costing["tool"],
                                  "lead_time_days": 14}, headers=tool_member)
    assert res.status_code == 200, res.text
    assert res.json()["lead_time_impact_days"] == 14
    assert res.json()["department_id"] == costing["tool"]

    log = (await client.get(f"/api/v1/changes/{costing['change_id']}/changelog",
                            headers=tool_member)).json()
    assert any(e["action"] == "cost_lead_time_set" for e in log)


async def test_a_stranger_cannot_set_another_departments_lead_time(
        client, session_factory, seed, costing):
    outsider = await _member(client, session_factory, seed, costing["dev"],
                             "devperson@test.io")
    res = await client.post(f"/api/v1/changes/{costing['change_id']}/cost-lead-time",
                            json={"department_id": costing["tool"],
                                  "lead_time_days": 5}, headers=outsider)
    assert res.status_code == 400
    assert "member of that department" in res.json()["detail"]


async def test_the_change_lead_may_fill_it_in_for_a_department(
        client, admin_auth, costing):
    """Somebody reads the number out in the costing meeting; the lead types it."""
    res = await client.post(f"/api/v1/changes/{costing['change_id']}/cost-lead-time",
                            json={"department_id": costing["tool"],
                                  "lead_time_days": 7}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_lead_time_needs_a_routed_department(client, admin_auth, costing):
    res = await client.post(f"/api/v1/changes/{costing['change_id']}/cost-lead-time",
                            json={"department_id": 999_999,
                                  "lead_time_days": 3}, headers=admin_auth)
    assert res.status_code == 400
    assert "no assessment" in res.json()["detail"]


# --- (3) summation rollups --------------------------------------------------

async def test_summation_rolls_up_lead_time_and_minutes(
        client, admin_auth, costing):
    for dept, aid, plant, minutes in (
            ("Tool Engineer", costing["assessments"]["Tool Engineer"],
             costing["home_plant"], 0.4),
            ("Development", costing["assessments"]["Development"],
             costing["usa_plant"], 0.1)):
        url = f"/api/v1/changes/{costing['change_id']}/assessments/{aid}/cost-lines"
        res = await client.put(url, json={"lines": [
            {"plant_id": plant, "activity_label": "Cycle", "cost_kind": "lifecycle",
             "demand_hours": 1.0, "minutes_per_part": minutes},
        ]}, headers=admin_auth)
        assert res.status_code == 200, res.text

    for dept_id, days in ((costing["tool"], 21), (costing["dev"], 5)):
        res = await client.post(
            f"/api/v1/changes/{costing['change_id']}/cost-lead-time",
            json={"department_id": dept_id, "lead_time_days": days},
            headers=admin_auth)
        assert res.status_code == 200, res.text

    summ = (await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                             headers=admin_auth)).json()
    leads = {l["department_id"]: l["lead_time_days"]
             for l in summ["lead_time_by_department"]}
    assert leads == {costing["tool"]: 21, costing["dev"]: 5}
    # the slowest department, not the sum — they wait in parallel
    assert summ["max_lead_time_days"] == 21

    minutes = {m["plant_id"]: m["minutes_per_part"]
               for m in summ["lifecycle_minutes_by_plant"]}
    assert minutes == {costing["home_plant"]: 0.4, costing["usa_plant"]: 0.1}
    assert round(summ["total_minutes_per_part"], 6) == 0.5
    cell = next(c for c in summ["by_department_plant"]
                if c["department_id"] == costing["tool"])
    assert cell["minutes_per_part"] == 0.4


async def test_empty_summation_reports_zeroes_not_nulls(client, admin_auth, costing):
    summ = (await client.get(f"/api/v1/changes/{costing['change_id']}/summation",
                             headers=admin_auth)).json()
    assert summ["max_lead_time_days"] == 0
    assert summ["total_minutes_per_part"] == 0.0
    assert summ["lead_time_by_department"] == []
    assert summ["lifecycle_minutes_by_plant"] == []


# --- (4) who still owes a number -------------------------------------------

async def test_costing_pending_lists_feasible_departments_without_lines(
        client, admin_auth, costing):
    detail = (await client.get(f"/api/v1/changes/{costing['change_id']}",
                               headers=admin_auth)).json()
    assert sorted(detail["costing_pending_department_ids"]) == sorted(
        [costing["tool"], costing["dev"]])

    url = (f"/api/v1/changes/{costing['change_id']}"
           f"/assessments/{costing['assessments']['Tool Engineer']}/cost-lines")
    await client.put(url, json={"lines": [
        {"plant_id": costing["home_plant"], "activity_label": "Nothing to do",
         "cost_kind": "one_time", "demand_hours": 0.0},
    ]}, headers=admin_auth)

    detail = (await client.get(f"/api/v1/changes/{costing['change_id']}",
                               headers=admin_auth)).json()
    # a zero line is an answer; silence is not
    assert detail["costing_pending_department_ids"] == [costing["dev"]]


async def test_pending_is_empty_outside_costing(
        client, admin_auth, costing, session_factory):
    async with session_factory() as s:
        c = await s.get(ChangeRequest, costing["change_id"])
        c.status = "in_assessment"
        await s.commit()
    detail = (await client.get(f"/api/v1/changes/{costing['change_id']}",
                               headers=admin_auth)).json()
    assert detail["costing_pending_department_ids"] == []


async def test_costing_input_task_reaches_the_department(
        client, session_factory, seed, costing):
    tool_member = await _member(client, session_factory, seed, costing["tool"],
                                "tooling2@test.io")

    async def rows():
        res = await client.get("/api/v1/changes/my-tasks", headers=tool_member)
        assert res.status_code == 200, res.text
        return [t for t in res.json()
                if t["kind"] == "costing_input"
                and t["change_id"] == costing["change_id"]]

    got = await rows()
    assert len(got) == 1
    assert got[0]["department_id"] == costing["tool"]
    assert got[0]["project_number"] == "proj"

    url = (f"/api/v1/changes/{costing['change_id']}"
           f"/assessments/{costing['assessments']['Tool Engineer']}/cost-lines")
    await client.put(url, json={"lines": [
        {"plant_id": costing["home_plant"], "activity_label": "Priced",
         "cost_kind": "one_time", "demand_hours": 2.0},
    ]}, headers=tool_member)
    assert await rows() == []
