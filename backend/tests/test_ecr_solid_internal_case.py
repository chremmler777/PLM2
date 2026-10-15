"""ECR-solid spec §5 (switch ASSESSMENT_V2): the internal approval card and
"ready to quote".

- The approval always names why (rationale pick). With money it also owes
  the annual volume, the saving per year and whether that saving is
  calculated or estimated; payback is computed. All at no cost: one click +
  the rationale. Never the raiser (HARD #8, kept).
- Closing costing (-> quoting) tells the Sales owner once: ready to quote.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.notification import Notification
from app.services import cm_switches
from tests.conftest import login, make_department_member

pytestmark = pytest.mark.asyncio
DUE = (datetime.utcnow() + timedelta(days=120)).isoformat()


@pytest.fixture
async def internal(client, session_factory, seed):
    async with session_factory() as s:
        change = ChangeRequest(
            change_number="C-IC-1", title="internal case", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["engineer_id"], lead_id=seed["engineer_id"],
            status="costing", customer_relevant=False)
        s.add(change)
        await s.commit()
        return change.id


def _url(cid):
    return f"/api/v1/changes/{cid}/internal-approval"


async def test_no_cost_is_one_click_and_a_rationale(client, admin_auth, internal):
    res = await client.post(_url(internal), json={"release_due_date": DUE},
                            headers=admin_auth)
    assert res.status_code == 400 and "why we spend it" in res.json()["detail"]
    res = await client.post(_url(internal), json={"release_due_date": DUE,
                                                  "rationale": "quality"},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["internal_rationale"] == "quality"


async def test_with_money_the_case_owes_volume_and_saving(
        client, admin_auth, internal, session_factory, seed):
    from app.models.workflow import Department
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(CostingPosition(change_id=internal, department_id=dept.id,
                              label="Insert re-cut", kind="external",
                              pricing="estimate", est_cost=4800.0,
                              created_by=seed["admin_id"]))
        await s.commit()
    # one round trip: every missing part of the case in one refusal
    res = await client.post(_url(internal), json={"release_due_date": DUE},
                            headers=admin_auth)
    detail = res.json()["detail"]
    assert res.status_code == 400 and all(w in detail for w in (
        "why we spend it", "annual volume", "saving per year", "calculated or an estimate"))
    base = {"release_due_date": DUE, "rationale": "saving"}
    for extra, words in (({}, "annual volume"),
                         ({"volume": 120000}, "saving per year"),
                         ({"volume": 120000, "saving": 2400}, "calculated or an estimate")):
        res = await client.post(_url(internal), json={**base, **extra}, headers=admin_auth)
        assert res.status_code == 400 and words in res.json()["detail"], res.text
    res = await client.post(_url(internal), json={
        **base, "volume": 120000, "saving": 2400, "saving_basis": "calculated"},
        headers=admin_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["internal_volume"], body["internal_saving"],
            body["internal_saving_basis"]) == (120000, 2400, "calculated")


async def test_the_raiser_still_never_approves(client, internal, seed):
    from tests.conftest import ENGINEER_PASSWORD
    eng = await login(client, "eng@test.io", ENGINEER_PASSWORD)
    res = await client.post(_url(internal), json={"release_due_date": DUE,
                                                  "rationale": "quality"}, headers=eng)
    assert res.status_code == 403


async def test_switch_off_needs_no_case(client, admin_auth, internal, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    res = await client.post(_url(internal), json={"release_due_date": DUE},
                            headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_closing_costing_tells_the_sales_owner(
        client, admin_auth, session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="ic-sales",
                 email="ic-sales@test.io", full_name="IC sales",
                 hashed_password=get_password_hash("ic-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        change = ChangeRequest(
            change_number="C-IC-2", title="ready", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["admin_id"], status="costing",
            customer_relevant=True, sales_owner_id=u.id)
        s.add(change)
        await s.flush()
        from app.models.change import ChangeAssessment
        from app.models.workflow import Department
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        s.add(ChangeAssessment(change_id=change.id, department_id=dept.id,
                               stage_order=1, rasic_letter="R", status="submitted",
                               verdict="feasible", submitted_at=datetime(2026, 9, 1),
                               details='{"costing_finalized_at": "2026-10-01T00:00:00"}'))
        await s.commit()
        cid, sales_id = change.id, u.id
    await make_department_member(session_factory, sales_id, "Sales")
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "quoting"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"ready_to_quote:{cid}"))).scalars().all()
        assert told == [sales_id]
