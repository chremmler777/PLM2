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


async def test_the_checklist_definitions_are_served_per_department(
        client, admin_auth, tab, session_factory):
    """Config, not data: the frontend renders the list the backend validates."""
    from app.models.workflow import Department
    from sqlalchemy import select
    res = await client.get(
        "/api/v1/changes/reference/assessment-checklist"
        f"?department_id={tab['department_id']}", headers=admin_auth)
    assert res.status_code == 200, res.text
    items = res.json()
    keys = [i["key"] for i in items]
    assert keys == ["cycle_time_change", "scrap_increase", "maintenance_increase",
                    "threed_change", "dimensional_risk", "visual_risk",
                    "work_instruction_update", "new_process",
                    "sparepart_required", "modification_internal",
                    "modification_external", "prototyping_required",
                    "matching_required"]
    assert all(i["extra"] is False for i in items)      # Tool Engineer has no extras
    spare = next(i for i in items if i["key"] == "sparepart_required")
    assert spare["label_de"] == "Ersatzteil erforderlich"
    assert spare["label_en"] == "Spare part required"
    ext = next(i for i in items if i["key"] == "modification_external")
    assert ext["label_de"] == "Externe Änderung/Umbau (Lieferant)"

    async with session_factory() as sess:
        apqp = (await sess.execute(select(Department).where(
            Department.name == "APQP"))).scalar_one()
        apqp_id = apqp.id
    res = await client.get(
        "/api/v1/changes/reference/assessment-checklist"
        f"?department_id={apqp_id}", headers=admin_auth)
    extras = [i for i in res.json() if i["extra"]]
    assert [i["key"] for i in extras] == ["pfmea_update", "control_plan_update"]


async def test_development_extra_carries_its_choices(
        client, admin_auth, seed, session_factory):
    from app.models.workflow import Department
    async with session_factory() as s:
        dev = Department(name="Development", flow_type="action", is_active=True)
        s.add(dev)
        await s.commit()
        dev_id = dev.id
    res = await client.get(
        "/api/v1/changes/reference/assessment-checklist"
        f"?department_id={dev_id}", headers=admin_auth)
    item = next(i for i in res.json() if i["key"] == "article_design_update")
    assert item["extra"] is True
    assert [c["value"] for c in item["choices"]] == ["internal", "customer_given"]


async def test_keyed_checklist_round_trips_with_remarks(client, admin_auth, tab):
    impacts = [
        {"key": "cycle_time_change", "impacted": True, "remark": "+0.4s"},
        {"key": "scrap_increase", "impacted": False},
        {"key": "modification_external", "impacted": True,
         "remark": "Supplier rebuild"},
    ]
    res = await _submit(client, admin_auth, tab, impacts)
    assert res.status_code == 200, res.text
    assert res.json()["details"]["impacts"] == impacts


async def test_an_unknown_key_is_refused(client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        [{"key": "invented_item", "impacted": True}])
    assert res.status_code == 400
    assert "not a checklist item" in res.json()["detail"]


async def test_a_departments_extra_is_not_everyones(client, admin_auth, tab):
    """Tool Engineer cannot answer APQP's questions."""
    res = await _submit(client, admin_auth, tab,
                        [{"key": "pfmea_update", "impacted": True}])
    assert res.status_code == 400


async def test_the_sub_choice_is_validated(client, admin_auth, seed,
                                           session_factory):
    from app.models.change import ChangeAssessment, ChangeRequest
    from app.models.workflow import Department
    async with session_factory() as s:
        dev = Department(name="Development", flow_type="action", is_active=True)
        s.add(dev)
        await s.flush()
        c = ChangeRequest(change_number="C-CL-DEV", title="dev", reason="r",
                          change_type="physical_part", project_id=seed["project_id"],
                          raised_by=seed["admin_id"], status="in_assessment")
        s.add(c)
        await s.flush()
        s.add(ChangeAssessment(change_id=c.id, department_id=dev.id, stage_order=1))
        await s.commit()
        cid, dev_id = c.id, dev.id

    async def submit(choice):
        return await client.post(f"/api/v1/changes/{cid}/assessments", json={
            "department_id": dev_id, "verdict": "feasible",
            "details": {"impacts": [{"key": "article_design_update",
                                     "impacted": True, "choice": choice}]}},
            headers=admin_auth)

    bad = await submit("whatever")
    assert bad.status_code == 400
    assert "not a valid choice" in bad.json()["detail"]
    assert (await submit("customer_given")).status_code == 200


async def test_legacy_rows_are_still_accepted(client, admin_auth, tab):
    """Assessments stored before the checklist was fixed can be resubmitted."""
    res = await _submit(client, admin_auth, tab, [
        {"activity_id": tab["activity_ids"][0], "label": "2D construction",
         "impacted": True},
        {"label": "Bespoke fixture review", "impacted": True},
    ])
    assert res.status_code == 200, res.text


async def test_checklist_coexists_with_department_specific_keys(
        client, admin_auth, tab):
    res = await _submit(client, admin_auth, tab,
                        [{"key": "new_process", "impacted": True}],
                        packaging_impacted=False)
    assert res.status_code == 200, res.text
    body = res.json()["details"]
    assert body["packaging_impacted"] is False
    assert len(body["impacts"]) == 1


async def test_not_feasible_requires_the_explanation_document(
        client, admin_auth, tab):
    """The verdict that stops a change dead arrives with what the customer
    will be shown."""
    res = await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                            json={"department_id": tab["department_id"],
                                  "verdict": "not_feasible"}, headers=admin_auth)
    assert res.status_code == 400
    assert "explanation document" in res.json()["detail"]

    up = await client.post(
        f"/api/v1/changes/{tab['change_id']}/attachments",
        files={"file": ("why-not.pptx", b"PK x",
                        "application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation")},
        data={"assessment_id": str(tab["assessment_id"]), "kind": "change_ppt"},
        headers=admin_auth)
    assert up.status_code in (200, 201), up.text

    res = await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                            json={"department_id": tab["department_id"],
                                  "verdict": "not_feasible"}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_other_verdicts_need_no_evidence(client, admin_auth, tab):
    res = await client.post(f"/api/v1/changes/{tab['change_id']}/assessments",
                            json={"department_id": tab["department_id"],
                                  "verdict": "feasible_with_conditions",
                                  "conditions": "if the tool is freed up"},
                            headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_rfq_expectation_is_reported_not_enforced(client, admin_auth, tab):
    """Checking external modification is a promise to ask a supplier; the RFQ
    is expected, and submitting without it still works."""
    res = await _submit(client, admin_auth, tab,
                        [{"key": "modification_external", "impacted": True}])
    assert res.status_code == 200, res.text

    detail = (await client.get(f"/api/v1/changes/{tab['change_id']}",
                               headers=admin_auth)).json()
    row = next(a for a in detail["assessments"]
               if a["department_id"] == tab["department_id"])
    assert row["rfq_expected"] is True
    assert row["has_rfq"] is False
    assert row["has_evidence"] is False

    up = await client.post(
        f"/api/v1/changes/{tab['change_id']}/attachments",
        files={"file": ("rfq.pdf", b"%PDF x", "application/pdf")},
        data={"assessment_id": str(tab["assessment_id"]), "kind": "rfq"},
        headers=admin_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["kind"] == "rfq"

    detail = (await client.get(f"/api/v1/changes/{tab['change_id']}",
                               headers=admin_auth)).json()
    row = next(a for a in detail["assessments"]
               if a["department_id"] == tab["department_id"])
    assert row["has_rfq"] is True and row["has_evidence"] is True


async def test_costing_seeds_from_the_checked_keys(client, admin_auth, tab):
    """Cycle time is charged per part; everything else is a one-off."""
    await _submit(client, admin_auth, tab, [
        {"key": "cycle_time_change", "impacted": True, "remark": "+0.4s"},
        {"key": "scrap_increase", "impacted": False},
        {"key": "sparepart_required", "impacted": True},
        {"key": "modification_external", "impacted": True},
        {"key": "prototyping_required", "impacted": True},
        {"key": "matching_required", "impacted": False},
    ])
    url = (f"/api/v1/changes/{tab['change_id']}"
           f"/assessments/{tab['assessment_id']}/cost-lines")
    lines = (await client.get(url, headers=admin_auth)).json()
    assert [l["activity_label"] for l in lines] == [
        "Cycle time change", "Spare part required",
        "External modification (supplier)", "Prototyping required"]
    assert [l["cost_kind"] for l in lines] == [
        "lifecycle", "one_time", "one_time", "one_time"]
    assert all(l["activity_id"] is None for l in lines)   # keys, not catalog ids
    assert all(l["demand_hours"] == 0.0 for l in lines)
    assert all(l["rate_snapshot"] == 65.0 for l in lines)
    assert lines[0]["note"] == "+0.4s"


async def test_seeding_stays_idempotent_with_keys(client, admin_auth, tab):
    await _submit(client, admin_auth, tab,
                  [{"key": "new_process", "impacted": True}])
    url = (f"/api/v1/changes/{tab['change_id']}"
           f"/assessments/{tab['assessment_id']}/cost-lines")
    first = (await client.get(url, headers=admin_auth)).json()
    again = (await client.get(url, headers=admin_auth)).json()
    assert len(first) == 1 and [l["id"] for l in first] == [l["id"] for l in again]


async def test_nothing_checked_seeds_nothing(client, admin_auth, tab):
    await _submit(client, admin_auth, tab,
                  [{"key": "new_process", "impacted": False}])
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
