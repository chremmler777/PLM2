"""ECR-solid lane L5 (assessment + costing) review fixes, loop 2.

- Department notices reach only active members in the change's
  organization (R23, R33).
- HARD #8 holds for the amount approved: costs finalized above it in
  costing withdraw the internal approval (R7, R25).
- The internal 'estimate low' task and notice go to the lead (PM without a
  lead), who may propose the Absorb and reads prices; the approver decides
  the Absorb on its own task (R5, R23).
"""
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.change import ChangeChangelog, ChangeRequest
from app.models.entities import Organization, User
from app.models.notification import Notification
from tests.conftest import make_department_member, ready_to_finalize
from tests.test_ecr_solid_l5_review import _position, _set, _u, _user, cc  # noqa: F401

pytestmark = pytest.mark.asyncio
DUE = (datetime.utcnow() + timedelta(days=120)).isoformat()
REF = "Tool 3343 recut 2025, FZ 4.1k"


async def _bare_user(session_factory, key, org_id, *, active=True):
    from app.auth.security import get_password_hash
    async with session_factory() as s:
        u = User(organization_id=org_id, username=f"l5b-{key}",
                 email=f"l5b-{key}@test.io", full_name=f"L5b {key}",
                 hashed_password=get_password_hash("l5-secret-12"),
                 role="engineer", is_active=active, mfa_enabled=False)
        s.add(u)
        await s.commit()
        return u.id


# --- R23/R33: department notices stay in the change's organization ----------

async def test_sales_notice_skips_other_orgs_and_inactive_accounts(
        client, cc, seed, session_factory):
    sales_id, _, _ = await _user(client, session_factory, seed, "sa", "Sales")
    async with session_factory() as s:
        other = Organization(name="Other Org", code="other-org", is_active=True)
        s.add(other)
        await s.commit()
        other_id = other.id
    elsewhere = await _bare_user(session_factory, "elsewhere", other_id)
    gone = await _bare_user(session_factory, "gone", seed["org_id"], active=False)
    for uid in (elsewhere, gone):
        await make_department_member(session_factory, uid, "Sales")
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          estimate_check="pending")
    await _set(session_factory, cc["cid"], status="approved",
               quoted_at=datetime.utcnow(), sales_owner_id=None)
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/estimate-check"),
                            json={"verdict": "above", "over": 4200}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_low:{pid}"))).scalars().all()
    assert told == [sales_id]


# --- R7: HARD #8 is bound to the amount approved ------------------------------

async def _approve(client, cid, auth):
    return await client.post(_u(cid, "/internal-approval"), json={
        "release_due_date": DUE, "rationale": "saving", "volume": 120000,
        "saving": 2400, "saving_basis": "calculated"}, headers=auth)


async def _finalized(session_factory, cid, dept):
    from app.models.change import ChangeAssessment
    async with session_factory() as s:
        a = (await s.execute(select(ChangeAssessment).where(
            ChangeAssessment.change_id == cid,
            ChangeAssessment.department_id == dept))).scalars().first()
        d = json.loads(a.details or "{}")
        d["costing_finalized_at"] = datetime.utcnow().isoformat()
        a.details = json.dumps(d)
        await s.commit()


async def test_costs_raised_after_the_internal_approval_need_it_again(
        client, cc, seed, session_factory):
    await _set(session_factory, cc["cid"], customer_relevant=False)
    await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                    basis_ref=REF)
    await _finalized(session_factory, cc["cid"], cc["shop"])
    res = await _approve(client, cc["cid"], cc["lead"])
    assert res.status_code == 200, res.text
    # Toolshop reopens and adds an estimated position after the approval
    res = await client.post(_u(cc["cid"], f"/costing/departments/{cc['shop']}/reopen"),
                            json={"reason": "insert recut at FZ after all"},
                            headers=cc["dale"])
    assert res.status_code == 200, res.text
    await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                    label="Insert recut at FZ", basis_ref=REF)
    # negative: while it is still a draft, costing -> approved is refused
    res = await client.post(_u(cc["cid"], "/transition"),
                            json={"to_status": "approved"}, headers=cc["lead"])
    assert res.status_code in (400, 409) and "Costs rose" in res.text, res.text
    # finalized above the approved total: the approval is withdrawn
    await ready_to_finalize(session_factory, cc["cid"], cc["shop"])
    res = await client.post(
        _u(cc["cid"], f"/costing/departments/{cc['shop']}/finalize"), headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cc["cid"])
        assert c.internal_approved_at is None and c.internal_approved_amount is None
        log = (await s.execute(select(ChangeChangelog.action).where(
            ChangeChangelog.change_id == cc["cid"]))).scalars().all()
        assert "internal_approval_withdrawn" in log
        told = (await s.execute(select(Notification).where(
            Notification.subject_key.like(f"internal_reapprove:{cc['cid']}:%")))
        ).scalars().all()
        assert [n.user_id for n in told] == [cc["lead_id"]]
        assert not any(ch.isdigit() for ch in told[0].body)       # no amount
    st = (await client.get(_u(cc["cid"], "/stage-state"), headers=cc["lead"])).json()
    assert st["can_approve_internal"] is True
    res = await client.post(_u(cc["cid"], "/transition"),
                            json={"to_status": "approved"}, headers=cc["lead"])
    assert res.status_code in (400, 409), res.text
    # approved again on the new total: HARD #8 holds again
    res = await _approve(client, cc["cid"], cc["lead"])
    assert res.status_code == 200, res.text
    assert res.json()["internal_approved_amount"] == 10000.0


async def test_an_unchanged_total_keeps_the_approval(client, cc, seed, session_factory):
    await _set(session_factory, cc["cid"], customer_relevant=False)
    await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                    basis_ref=REF)
    await _finalized(session_factory, cc["cid"], cc["shop"])
    assert (await _approve(client, cc["cid"], cc["lead"])).status_code == 200
    res = await client.post(_u(cc["cid"], f"/costing/departments/{cc['shop']}/reopen"),
                            json={"reason": "typo in the label"}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    await ready_to_finalize(session_factory, cc["cid"], cc["shop"])
    res = await client.post(
        _u(cc["cid"], f"/costing/departments/{cc['shop']}/finalize"), headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cc["cid"])).internal_approved_at is not None
    # negative: a second approval of the same total is still refused
    res = await _approve(client, cc["cid"], cc["lead"])
    assert res.status_code == 400 and "already approved" in res.text


# --- R5/R23: the internal 'estimate low' goes to who may act on it ----------

async def test_internal_estimate_low_goes_to_the_lead_not_the_approvers(
        client, cc, seed, session_factory):
    pm2_id, _, pm2 = await _user(client, session_factory, seed, "pm2", "Project Manager")
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          estimate_check="pending")
    await _set(session_factory, cc["cid"], customer_relevant=False, status="approved",
               internal_approved_at=datetime.utcnow())
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/estimate-check"),
                            json={"verdict": "above", "over": 500}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_low:{pid}"))).scalars().all()
    assert told == [cc["lead_id"]]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=cc["lead"])).json()
    row = next(t for t in tasks if t["kind"] == "estimate_low")
    assert "500.00" in row["hint"] and "absorb" in row["hint"]
    # negative: the fallback approver (PM, not the lead) has no row to act on
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=pm2)).json()
    assert not [t for t in tasks if t["kind"] == "estimate_low"]


async def test_internal_estimate_low_without_a_lead_goes_to_pm(
        client, cc, seed, session_factory):
    pm2_id, _, pm2 = await _user(client, session_factory, seed, "pm3", "Project Manager")
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          estimate_check="pending")
    await _set(session_factory, cc["cid"], customer_relevant=False, status="approved",
               internal_approved_at=datetime.utcnow(), lead_id=None)
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/estimate-check"),
                            json={"verdict": "above", "over": 500}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        told = set((await s.execute(select(Notification.user_id).where(
            Notification.subject_key == f"estimate_low:{pid}"))).scalars().all())
    assert {cc["lead_id"], pm2_id} <= told and cc["dale_id"] not in told
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=pm2)).json()
    assert [t for t in tasks if t["kind"] == "estimate_low"]


async def test_a_pm_edit_above_the_approved_total_owes_the_approval_again(
        client, cc, seed, session_factory):
    """A3-04: PM/admin may write positions at any time; an edit that lifts
    the total above the approved amount withdraws the approval like a
    finalize does: the approver gets the notice and the My Tasks row back
    (no dead end behind HARD #8)."""
    pm2_id, _, pm2 = await _user(client, session_factory, seed, "pm-a304", "Project Manager")
    await _set(session_factory, cc["cid"], customer_relevant=False)
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          basis_ref=REF)
    await _finalized(session_factory, cc["cid"], cc["shop"])
    assert (await _approve(client, cc["cid"], cc["lead"])).status_code == 200
    # negative: an edit that keeps the total keeps the approval
    res = await client.put(_u(cc["cid"], f"/costing/positions/{pid}"),
                           json={"notes": "FZ figure"}, headers=pm2)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cc["cid"])).internal_approved_at is not None
    res = await client.put(_u(cc["cid"], f"/costing/positions/{pid}"),
                           json={"est_cost": 7000.0}, headers=pm2)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cc["cid"])).internal_approved_at is None
        told = (await s.execute(select(Notification.user_id).where(
            Notification.subject_key.like(f"internal_reapprove:{cc['cid']}:%")))
        ).scalars().all()
    assert told == [cc["lead_id"]]
    tasks = (await client.get("/api/v1/changes/my-tasks", headers=cc["lead"])).json()
    assert [t for t in tasks if t["kind"] == "internal_approval"
            and t["change_id"] == cc["cid"]]


async def _above_after_approval(client, cc, seed, session_factory, key):
    pm2_id, _, pm2 = await _user(client, session_factory, seed, key, "Project Manager")
    await _set(session_factory, cc["cid"], customer_relevant=False)
    pid = await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"],
                          basis_ref=REF, estimate_check="pending")
    await _finalized(session_factory, cc["cid"], cc["shop"])
    assert (await _approve(client, cc["cid"], cc["lead"])).status_code == 200
    res = await client.post(_u(cc["cid"], f"/costing/positions/{pid}/estimate-check"),
                            json={"verdict": "above", "over": 800}, headers=cc["dale"])
    assert res.status_code == 200, res.text
    return pid, pm2_id, pm2


async def test_internal_quote_above_is_re_approved_and_clears_the_price(
        client, cc, seed, session_factory):
    """A3-05 (spec §4 [R4]): internal, in costing: 're-approve or absorb
    (reason)' for the lead and the approver; the re-approval of the new
    total clears price_open and the row."""
    pid, pm2_id, pm2 = await _above_after_approval(client, cc, seed, session_factory,
                                                   "pm-a305")
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cc["cid"])).price_open is True
        told = (await s.execute(select(Notification).where(
            Notification.subject_key == f"estimate_low:{pid}:approver"))).scalars().all()
    assert [n.user_id for n in told] == [pm2_id]
    assert not any(ch.isdigit() for ch in told[0].body)       # no amount (R23)
    lead_rows = [t for t in (await client.get("/api/v1/changes/my-tasks",
                                              headers=cc["lead"])).json()
                 if t["kind"] == "estimate_low"]
    assert lead_rows and "re-approve or absorb" in lead_rows[0]["hint"]
    assert lead_rows[0]["kind_label"] == "Cost above the approved estimate: re-approve or absorb"
    rows = [t for t in (await client.get("/api/v1/changes/my-tasks", headers=pm2)).json()
            if t["kind"] == "estimate_low"]
    assert rows and rows[0]["target_tab"] == "offer"
    assert not any(ch.isdigit() for ch in rows[0]["hint"])
    st = (await client.get(_u(cc["cid"], "/stage-state"), headers=pm2)).json()
    assert st["can_approve_internal"] is True
    res = await _approve(client, cc["cid"], pm2)
    assert res.status_code == 200, res.text
    assert res.json()["internal_approved_amount"] == 5800.0
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cc["cid"])
        assert c.price_open is False
    for auth in (cc["lead"], pm2):
        assert not [t for t in (await client.get("/api/v1/changes/my-tasks",
                                                 headers=auth)).json()
                    if t["kind"] in ("estimate_low", "internal_approval")
                    and t["change_id"] == cc["cid"]]
    # negative: nothing owed any more: a third approval is refused
    res = await _approve(client, cc["cid"], pm2)
    assert res.status_code == 400 and "already approved" in res.text


async def test_internal_re_approval_keeps_a_price_open_for_another_cause(
        client, cc, seed, session_factory):
    """A3-05 negative: start at risk also holds the price: the re-approval
    of the quote above leaves price_open set."""
    pid, pm2_id, pm2 = await _above_after_approval(client, cc, seed, session_factory,
                                                   "pm-a305b")
    await _set(session_factory, cc["cid"], start_at_risk_approved_at=datetime.utcnow())
    res = await _approve(client, cc["cid"], pm2)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cc["cid"])).price_open is True


async def test_the_approval_card_holds_while_costing_is_not_finalized(
        client, cc, seed, session_factory):
    """A3-09 (R24): C5 holds the internal approval: no approve button (the
    POST would 400), the card names why and offers the override; an
    approved override of 'Costing not finalized' gives the button back."""
    pm2_id, _, pm2 = await _user(client, session_factory, seed, "pm-a309", "Project Manager")
    await _set(session_factory, cc["cid"], customer_relevant=False)
    await _position(session_factory, cc["cid"], cc["shop"], cc["dale_id"], basis_ref=REF)
    st = (await client.get(_u(cc["cid"], "/stage-state"), headers=cc["lead"])).json()
    assert st["can_approve_internal"] is False
    assert "Costing not finalized" in st["internal_approval_hold"]
    assert st["internal_hold_can_override"] is True
    res = await _approve(client, cc["cid"], cc["lead"])
    assert res.status_code == 400 and "Costing not finalized" in res.text
    # negative: a Toolshop member is no approver: no hold served either
    st = (await client.get(_u(cc["cid"], "/stage-state"), headers=cc["dale"])).json()
    assert st["can_approve_internal"] is False and st["internal_approval_hold"] is None
    res = await client.post(_u(cc["cid"], "/deviations"), json={
        "to_status": "approved", "guard_key": "costing_not_finalized",
        "reason": "customer SOP 24 Oct, mail 2026-10-12", "reason_code": "in_parallel"},
        headers=cc["lead"])
    assert res.status_code == 200, res.text
    res = await client.post(_u(cc["cid"], f"/deviations/{res.json()['id']}/decide"),
                            json={"decision": "approved"}, headers=pm2)
    assert res.status_code == 200, res.text
    st = (await client.get(_u(cc["cid"], "/stage-state"), headers=cc["lead"])).json()
    assert st["can_approve_internal"] is True and st["internal_approval_hold"] is None
