"""Review fixes on the per-department costing pipeline (4221d4f0):

1. a later-stage row submitted after the finalization makes the department
   draft again (pending, costing_input task, writable);
2. the change-wide machine class: in assessment only PM / admin set it, and a
   re-price of a finalized department's lines reopens its finalization;
3. a superseded department's positions leave the summation and quote basis;
4. in assessment a question waits on Sales as before, not on the asker;
5. the zero lines seeded from the checklist do not satisfy finalize
   (test_costing_contract);
6. a finalized Tool department no longer changes the part weight;
7. finalize refuses a department that owes no cost input in costing too.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeAssessment, ChangeChangelog, ChangeRequest
from app.services.cost_service import CostService
from tests.conftest import insert_legacy_concern, make_department_member, ready_to_finalize
from tests.test_costing_cost_sheet import _add, _url as _cs_url, world  # noqa: F401
from tests.test_costing_review_fixes import _machine_world
from tests.test_early_costing import (  # noqa: F401
    _add_position, _detail, _member, _url, early,
)

pytestmark = pytest.mark.asyncio


async def _status(session_factory, change_id, status):
    async with session_factory() as s:
        (await s.get(ChangeRequest, change_id)).status = status
        await s.commit()


# ---------------------------------------------------------------- 1

async def test_later_stage_submit_after_finalize_reopens_the_department(
        client, admin_auth, session_factory, seed, early):
    tool = await _member(client, session_factory, seed, early["tool"], "rv-tool1@test.io")
    assert (await _add_position(client, tool, early, early["tool"])).status_code == 201
    await ready_to_finalize(session_factory, early["change_id"], early["tool"])
    assert (await client.post(_url(early, early["tool"], "finalize"),
                              headers=tool)).status_code == 200
    # entering costing wakes the Tool Engineer's stage 2, which it submits
    async with session_factory() as s:
        c = await s.get(ChangeRequest, early["change_id"])
        c.status = "costing"
        s.add(ChangeAssessment(
            change_id=early["change_id"], department_id=early["tool"],
            stage_order=2, verdict="feasible", status="submitted",
            submitted_at=datetime.utcnow() + timedelta(seconds=1)))
        await s.commit()
    detail = await _detail(client, admin_auth, early)
    assert early["tool"] in detail["costing_pending_department_ids"]
    assert early["tool"] not in detail["costing_finalized_department_ids"]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=tool)).json()
    assert [t["department_id"] for t in tasks if t["kind"] == "costing_input"
            and t["change_id"] == early["change_id"]] == [early["tool"]]
    # writable again, and finalizable again
    assert (await _add_position(client, tool, early, early["tool"])).status_code == 201
    await ready_to_finalize(session_factory, early["change_id"], early["tool"])
    assert (await client.post(_url(early, early["tool"], "finalize"),
                              headers=tool)).status_code == 200


# ---------------------------------------------------------------- 2

async def test_machine_class_in_assessment_is_pm_or_admin_only(
        client, admin_auth, session_factory, seed, world):
    from app.services import costing_rates
    from app.models.entities import User
    await _machine_world(session_factory, world)
    await _status(session_factory, world["change_id"], "in_assessment")
    tool = await _member(client, session_factory, seed, world["tool"], "rv-tool2@test.io")
    res = await client.put(_cs_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["big"]}, headers=tool)
    assert res.status_code == 403, res.text
    async with session_factory() as s:
        pm = (await s.execute(select(User).where(User.email == "rv-tool2@test.io"))
              ).scalar_one()
        pm_id = pm.id
    await make_department_member(session_factory, pm_id, "Project Manager")
    res = await client.put(_cs_url(world, "/costing/machine-class"),
                           json={"machine_class_id": world["big"]}, headers=tool)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        change.status = "costing"
        await s.commit()
    assert (await client.put(_cs_url(world, "/costing/machine-class"),
                             json={"machine_class_id": world["small"]},
                             headers=admin_auth)).status_code == 200
    # in costing a department that may write its costing may set it again
    async with session_factory() as s:
        change = await s.get(ChangeRequest, world["change_id"])
        member = await s.get(User, pm_id)
        assert await costing_rates.may_set_machine_class(s, change, member)


async def test_machine_class_change_reopens_finalized_departments_it_reprices(
        client, admin_auth, session_factory, world):
    await _machine_world(session_factory, world)
    assert (await client.put(_cs_url(world, "/costing/machine-class"),
                             json={"machine_class_id": world["big"]},
                             headers=admin_auth)).status_code == 200
    await _add(client, admin_auth, world, kind="machine_time", label="P", hours=2)
    await _add(client, admin_auth, world, department_id=world["qa"], label="Q", hours=1)
    fin = lambda d: (f"/api/v1/changes/{world['change_id']}/costing/departments/"
                     f"{d}/finalize")
    for d in (world["tool"], world["qa"]):
        await ready_to_finalize(session_factory, world["change_id"], d)
    assert (await client.post(fin(world["tool"]), headers=admin_auth)).status_code == 200
    assert (await client.post(fin(world["qa"]), headers=admin_auth)).status_code == 200
    assert (await client.put(_cs_url(world, "/costing/machine-class"),
                             json={"machine_class_id": world["small"]},
                             headers=admin_auth)).status_code == 200
    detail = (await client.get(_cs_url(world), headers=admin_auth)).json()
    # Tool's machine line moved: it reviews; Quality's own time did not
    assert detail["costing_finalized_department_ids"] == [world["qa"]]
    assert detail["costing_pending_department_ids"] == [world["tool"]]
    async with session_factory() as s:
        log = (await s.execute(select(ChangeChangelog).where(
            ChangeChangelog.change_id == world["change_id"],
            ChangeChangelog.action == "costing_input_reopened"))).scalars().all()
        assert len(log) == 1 and "machine class changed" in log[0].action_description
        assert log[0].notes and "machine class changed" in log[0].notes


# ---------------------------------------------------------------- 3

async def test_superseded_department_positions_leave_summation_and_quote(
        client, admin_auth, session_factory, seed, early):
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService
    from app.services.early_stage_service import EarlyStageService
    from app.services.offer_service import OfferService
    tool = await _member(client, session_factory, seed, early["tool"], "rv-tool3@test.io")
    assert (await _add_position(client, tool, early, early["tool"],
                                est_cost=250.0)).status_code == 201
    async with session_factory() as s:
        change = await s.get(ChangeRequest, early["change_id"])
        summ = await CostService.summation(s, change)
        assert summ["totals"]["one_time_external"] == 250
    async with session_factory() as s:
        change = await ChangeService.get_change(s, early["change_id"])
        await EarlyStageService.supersede_assessments(
            s, change, seed["admin_id"], "Development: not feasible")
        await ChangeRoutingService.teardown_routing(s, change, seed["admin_id"])
        change.status = "scoping"
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, early["change_id"])
        summ = await CostService.summation(s, change)
        assert summ["totals"]["one_time_external"] == 0
        assert summ["positions_by_department"] == []
        lines, total = await OfferService._costing_basis(s, change)
        assert total == 0
        assert not any(abs(l.get("amount") or 0) > 0 for l in lines)
    # the draft is still there, and counts again once it answers feasible
    positions = (await client.get(
        f"/api/v1/changes/{early['change_id']}/costing/positions",
        headers=admin_auth)).json()
    assert len(positions) == 1
    async with session_factory() as s:
        s.add(ChangeAssessment(change_id=early["change_id"],
                               department_id=early["tool"], stage_order=1,
                               verdict="feasible"))
        await s.commit()
    async with session_factory() as s:
        change = await s.get(ChangeRequest, early["change_id"])
        summ = await CostService.summation(s, change)
        assert summ["totals"]["one_time_external"] == 250


# ---------------------------------------------------------------- 4

@pytest.mark.usefixtures("old_question_routing")
async def test_assessment_question_goes_to_sales_not_the_asker(
        client, session_factory, seed, early):
    tool = await _member(client, session_factory, seed, early["tool"], "rv-tool4@test.io")
    from app.models.workflow import Department
    async with session_factory() as s:
        sales = Department(name="Sales", flow_type="action", is_active=True)
        s.add(sales)
        await s.commit()
        sales_id = sales.id
    sales_auth = await _member(client, session_factory, seed, sales_id, "rv-sales@test.io")
    await insert_legacy_concern(session_factory, early["change_id"], kind="needs_info",
                                note="Which grain?", raised_by=seed["admin_id"],
                                department_id=early["tool"])

    def info(tasks):
        return [t for t in tasks if t["kind"] == "obtain_info"
                and t["change_id"] == early["change_id"]]
    assert info((await client.get("/api/v1/changes/my-tasks", headers=tool)).json()) == []
    rows = info((await client.get("/api/v1/changes/my-tasks", headers=sales_auth)).json())
    assert len(rows) == 1 and rows[0]["question_count"] == 1
    assert "role_department_id" not in rows[0]


# ---------------------------------------------------------------- 6

async def test_finalized_tool_department_no_longer_changes_the_weight(
        client, admin_auth, session_factory, seed, early):
    tool = await _member(client, session_factory, seed, early["tool"], "rv-tool5@test.io")
    assert (await _add_position(client, tool, early, early["tool"])).status_code == 201
    await ready_to_finalize(session_factory, early["change_id"], early["tool"])
    await _status(session_factory, early["change_id"], "costing")
    url = f"/api/v1/changes/{early['change_id']}/weight-estimate"
    assert (await client.put(url, json={"weight_g": 120}, headers=tool)).status_code == 200
    assert (await client.post(_url(early, early["tool"], "finalize"),
                              headers=tool)).status_code == 200
    res = await client.put(url, json={"weight_g": 130}, headers=tool)
    assert res.status_code == 400 and "finalized" in res.json()["detail"]
    assert (await client.put(url, json={"weight_g": 130},
                             headers=admin_auth)).status_code == 200


# ---------------------------------------------------------------- 7

async def test_finalize_refuses_a_department_owing_nothing_in_costing_too(
        client, session_factory, seed, early):
    pack = await _member(client, session_factory, seed, early["pack"], "rv-pack@test.io")
    await _status(session_factory, early["change_id"], "costing")
    assert (await _add_position(client, pack, early, early["pack"])).status_code == 201
    res = await client.post(_url(early, early["pack"], "finalize"), headers=pack)
    assert res.status_code == 400
    assert "owes no costing" in res.json()["detail"]
