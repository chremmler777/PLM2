"""The workbook D-tabs are checklists: each department says which catalog
items the change touches, and costing starts from that answer."""
import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeImpactedItem, ChangeRequest
from app.models.change_cost import AssessmentActivity, AssessmentCostLine, DepartmentRate
from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def tab(session_factory, seed):
    """A department with a catalog, a rate at the project's plant, and a change
    in assessment carrying its assessment row."""
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        acts = [AssessmentActivity(department_id=dept.id, label=label, sort_order=i)
                for i, label in enumerate(["2D construction", "3D construction",
                                           "Tool trial"])]
        other = Department(name="APQP", flow_type="action", is_active=True)
        s.add(other)
        await s.flush()
        foreign = AssessmentActivity(department_id=other.id, label="Gauge study")
        s.add_all(acts + [foreign])
        await s.flush()

        from app.models.entities import Project
        project = await s.get(Project, seed["project_id"])
        s.add(DepartmentRate(department_id=dept.id, plant_id=project.plant_id,
                             hourly_rate=65.0, min_factor=1.0))

        change = ChangeRequest(
            change_number="C-CL-1", title="checklist", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dept.id,
                             stage_order=1)
        s.add(a)
        await s.commit()
        return {"change_id": change.id, "assessment_id": a.id,
                "department_id": dept.id, "activity_ids": [x.id for x in acts],
                "foreign_activity": foreign.id, "plant_id": project.plant_id}


async def _submit(client, auth, tab, impacts, **extra):
    details = {"impacts": impacts}
    details.update(extra)
    return await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                             json={"department_id": tab["department_id"],
                                   "verdict": "feasible", "details": details},
                             headers=auth)


async def test_the_catalog_is_readable_at_assessment(client, admin_auth, tab):
    res = await client.get(
        f"/api/v1/changes/reference/activities?department_id={tab['department_id']}",
        headers=admin_auth)
    assert res.status_code == 200, res.text
    labels = [r["label"] for r in res.json()]
    assert labels == ["2D construction", "3D construction", "Tool trial"]
    assert all(r["department_id"] == tab["department_id"] for r in res.json())


async def test_checklist_round_trips_with_remarks(client, admin_auth, tab):
    impacts = [
        {"activity_id": tab["activity_ids"][0], "label": "2D construction",
         "impacted": True, "remark": "Two views change"},
        {"activity_id": tab["activity_ids"][1], "label": "3D construction",
         "impacted": False},
        {"label": "Bespoke fixture review", "impacted": True,
         "remark": "Not in the catalog"},
    ]
    res = await _submit(client, admin_auth, tab, impacts)
    assert res.status_code == 200, res.text
    assert res.json()["details"]["impacts"] == impacts

    detail = (await client.get(f"/api/v1/changes/{tab['change_id']}",
                               headers=admin_auth)).json()
    row = next(a for a in detail["assessments"]
               if a["department_id"] == tab["department_id"])
    assert row["details"]["impacts"] == impacts


async def test_checklist_coexists_with_department_specific_keys(
        client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        [{"activity_id": tab["activity_ids"][0], "impacted": True}],
                        packaging_impacted=False)
    assert res.status_code == 200, res.text
    body = res.json()["details"]
    assert body["packaging_impacted"] is False
    assert len(body["impacts"]) == 1


async def test_another_departments_activity_is_refused(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        [{"activity_id": tab["foreign_activity"], "impacted": True}])
    assert res.status_code == 400
    assert "catalog" in res.json()["detail"]


async def test_free_text_needs_a_label(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab, [{"impacted": True, "remark": "?"}])
    assert res.status_code == 400
    assert "label" in res.json()["detail"]

    res = await _submit(client, admin_auth, tab, {"not": "a list"})
    assert res.status_code == 400


async def test_costing_starts_from_the_checked_items(
        client, admin_auth, tab, session_factory):
    impacts = [
        {"activity_id": tab["activity_ids"][0], "label": "2D construction",
         "impacted": True, "remark": "Two views change"},
        {"activity_id": tab["activity_ids"][1], "label": "3D construction",
         "impacted": False},
        {"label": "Bespoke fixture review", "impacted": True},
    ]
    assert (await _submit(client, admin_auth, tab, impacts)).status_code == 200

    url = (f"/api/v1/changes/{tab['change_id']}"
           f"/assessments/{tab['assessment_id']}/cost-lines")
    res = await client.get(url, headers=admin_auth)
    assert res.status_code == 200, res.text
    lines = res.json()
    # only the checked items, unchecked one absent
    assert len(lines) == 2
    assert [l["activity_label"] for l in lines] == ["2D construction",
                                                    "Bespoke fixture review"]
    assert lines[0]["activity_id"] == tab["activity_ids"][0]
    assert lines[1]["activity_id"] is None          # free text
    # zero hours, but priced at the department's current rate
    assert all(l["demand_hours"] == 0.0 for l in lines)
    assert all(l["rate_snapshot"] == 65.0 for l in lines)
    assert all(l["internal_cost"] == 0.0 for l in lines)
    assert all(l["plant_id"] == tab["plant_id"] for l in lines)
    # the checklist remark travels with the line it explains
    assert lines[0]["note"] == "Two views change"


async def test_seeding_is_idempotent_and_respects_deletions(
        client, admin_auth, tab, session_factory):
    impacts = [{"activity_id": tab["activity_ids"][0], "label": "2D construction",
                "impacted": True}]
    await _submit(client, admin_auth, tab, impacts)
    url = (f"/api/v1/changes/{tab['change_id']}"
           f"/assessments/{tab['assessment_id']}/cost-lines")

    first = (await client.get(url, headers=admin_auth)).json()
    again = (await client.get(url, headers=admin_auth)).json()
    assert len(first) == 1 and len(again) == 1
    assert [l["id"] for l in first] == [l["id"] for l in again]

    # a line the department deliberately removed stays removed
    res = await client.put(url, json={"lines": []}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert (await client.get(url, headers=admin_auth)).json() == []


async def test_nothing_checked_seeds_nothing(client, admin_auth, tab):
    await _submit(client, admin_auth, tab,
                  [{"activity_id": tab["activity_ids"][0], "impacted": False}])
    url = (f"/api/v1/changes/{tab['change_id']}"
           f"/assessments/{tab['assessment_id']}/cost-lines")
    assert (await client.get(url, headers=admin_auth)).json() == []


# --- the summation must render as the workbook matrix -----------------------

async def test_summation_carries_the_department_by_plant_matrix(
        client, admin_auth, tab, seed, session_factory):
    """The workbook is a department row with a column group per plant; neither
    margin can be derived from the other, so the matrix is its own rollup."""
    from app.models.entities import Plant, Project
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        usa = Plant(organization_id=seed["org_id"], name="NKTW USA", code="usa",
                    location="US", is_active=True)
        s.add(usa)
        await s.flush()
        s.add(DepartmentRate(department_id=tab["department_id"], plant_id=usa.id,
                             hourly_rate=100.0, min_factor=1.0))
        await s.commit()
        usa_id, home_id = usa.id, project.plant_id

    url = (f"/api/v1/changes/{tab['change_id']}"
           f"/assessments/{tab['assessment_id']}/cost-lines")
    res = await client.put(url, json={"lines": [
        {"plant_id": home_id, "activity_id": tab["activity_ids"][0],
         "cost_kind": "one_time", "demand_hours": 2.0, "external_cost": 500.0},
        {"plant_id": usa_id, "activity_id": tab["activity_ids"][0],
         "cost_kind": "one_time", "demand_hours": 1.0},
        {"plant_id": usa_id, "activity_label": "Series minutes",
         "cost_kind": "lifecycle", "demand_hours": 0.5},
    ]}, headers=admin_auth)
    assert res.status_code == 200, res.text

    summ = (await client.get(f"/api/v1/changes/{tab['change_id']}/summation",
                             headers=admin_auth)).json()
    cells = {(c["department_id"], c["plant_id"]): c
             for c in summ["by_department_plant"]}
    home = cells[(tab["department_id"], home_id)]
    assert home["one_time_internal"] == 130.0        # 2h x 65
    assert home["one_time_external"] == 500.0
    assert home["demand_hours"] == 2.0

    usa_cell = cells[(tab["department_id"], usa_id)]
    assert usa_cell["one_time_internal"] == 100.0    # 1h x 100 (its own rate)
    assert usa_cell["lifecycle_internal"] == 50.0    # 0.5h x 100
    assert usa_cell["demand_hours"] == 1.5

    # the existing margins still add up
    by_plant = {p["plant_id"]: p for p in summ["by_plant"]}
    assert by_plant[home_id]["one_time_internal"] == 130.0
    assert by_plant[usa_id]["lifecycle_internal"] == 50.0
    assert summ["totals"]["grand_total"] == 780.0
