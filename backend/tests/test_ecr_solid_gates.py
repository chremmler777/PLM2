"""ECR-solid lane L2: gates.

- C6: an override (transition deviation) is bound to ONE soft rule; a hop
  held by two rules needs two; the OK is never the proposer's and belongs to
  the rule's deciders (lead / PM member / admin; Quality for implementation
  start, release and validation; PM or Management for price rules and Absorb);
  the deciders are told once. Switch COMMERCIAL_V2 off = the old rule.
- C5: closing costing (to the quote, or an internal change to approval)
  waits for every finalized department costing; SOFT, override bound to
  'costing_not_finalized'. Switch ASSESSMENT_V2.
- HARD #8: internal approval by an engineering approver, never the raiser.
- HARD #3 (C7): a failed check or an open validation issue holds the release;
  no override, no admin; a concession is the exit. Switch RELEASE_V2.
- HARD #9: release needs the PM and Quality sign-offs for the latest offer
  sent; close is refused while a price is open; exits: the customer accepts,
  or Absorb (reason + OK of PM/Management; internal: the approver).
- Why blocked: next_step items name the rule, owner, exits and override.
- In flight: an approved deviation from before the binding still covers.
"""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.models.change import ChangeRequest, ChangeTransitionDeviation
from app.models.entities import User
from app.models.workflow import Department, UserDepartment
from app.services import cm_switches
from tests.conftest import login, lock_impact

pytestmark = pytest.mark.asyncio
ACTS = "X-Acts-As-Department"
DEPTS = ("Sales", "Project Manager", "Development", "Quality", "Management",
         "Tool Engineer")


@pytest_asyncio.fixture
async def depts(session_factory, seed):
    ids = {}
    async with session_factory() as s:
        for i, n in enumerate(DEPTS):
            d = Department(name=n, flow_type="action", is_active=True, sort_order=i,
                           can_start_change=n in ("Sales", "Project Manager"),
                           can_start_internal_change=n == "Development")
            s.add(d); await s.flush(); ids[n] = d.id
        # the seeded engineer writes through Development
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=ids["Development"]))
        await s.commit()
    return ids


@pytest_asyncio.fixture
async def admin(client):
    return await login(client, "admin@test.io")


@pytest_asyncio.fixture
async def people(client, session_factory, seed, depts):
    """One plain member per department (no admin): name -> (id, auth)."""
    out = {}
    async with session_factory() as s:
        for n in ("Sales", "Project Manager", "Quality", "Management", "Development"):
            key = n.split()[0].lower()
            u = User(organization_id=seed["org_id"], username=f"u_{key}",
                     email=f"u_{key}@test.io", full_name=f"U {n}",
                     hashed_password="x", role="engineer", is_active=True)
            s.add(u); await s.flush()
            s.add(UserDepartment(user_id=u.id, department_id=depts[n]))
            out[n] = u.id
        await s.commit()
    return {n: (uid, await login(client, f"u_{n.split()[0].lower()}@test.io", admin=False))
            for n, uid in out.items()}


async def _change(client, admin, seed, session_factory, status, *, customer=True,
                  lead=None, raised_by=None, **values):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "gates", "reason": "r",
        "change_type": "physical_part", "customer_relevant": customer,
        "lead_id": lead or seed["engineer_id"]}, headers=admin)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid).values(
            status=status, **({"raised_by": raised_by} if raised_by else {}), **values))
        await s.commit()
    return cid


async def _scoping_two_rules(client, admin, seed, session_factory):
    """A customer change in scoping held by two soft rules: no quote
    deadline, no 'proceed' meeting (impact locked: the hard gate is out of
    the way)."""
    cid = await _change(client, admin, seed, session_factory, "scoping")
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": f"ART-G{cid}",
        "name": "Gate part", "part_type": "internal_mfg"}, headers=admin)
    assert part.status_code in (200, 201), part.text
    r = await client.post(f"/api/v1/changes/{cid}/impacted-items",
                          json={"part_id": part.json()["id"], "is_lead": True},
                          headers=admin)
    assert r.status_code in (200, 201), r.text
    await lock_impact(session_factory, cid)
    return cid


async def _propose(client, auth, cid, to, **extra):
    return await client.post(f"/api/v1/changes/{cid}/deviations", json={
        "to_status": to, "reason": "urgent customer date", **extra}, headers=auth)


async def _decide(client, auth, cid, dev_id, decision="approved"):
    return await client.post(f"/api/v1/changes/{cid}/deviations/{dev_id}/decide",
                             json={"decision": decision}, headers=auth)


# ---------------------------------------------------------------------------
# C6: one override, one rule
# ---------------------------------------------------------------------------

async def test_override_is_bound_to_its_rule_and_lifts_nothing_else(
        client, admin, seed, depts, people, session_factory):
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    pm = people["Project Manager"][1]
    # an override of the quote-deadline rule ...
    r = await _propose(client, lead, cid, "in_assessment", guard_key="no_quote_deadline",
                       reason_code="customer_date")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["guard_key"] == "no_quote_deadline"
    assert body["reason_code"] == "customer_date"
    assert body["rule_label"] == "No quote deadline"
    assert body["deciders"]["group"] == "run"
    assert (await _decide(client, pm, cid, body["id"])).status_code == 200
    # ... does NOT lift the missing proceed meeting (NEGATIVE)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "in_assessment"}, headers=lead)
    assert r.status_code == 400
    assert "proceed" in r.json()["detail"]
    assert r.headers.get("X-Deviation-Rule") == "no_proceed_meeting"
    # without a key the next request binds to the next uncovered rule
    r2 = await _propose(client, lead, cid, "in_assessment")
    assert r2.status_code == 200, r2.text
    assert r2.json()["guard_key"] == "no_proceed_meeting"
    assert r2.json()["reason_code"] == "other"
    assert (await _decide(client, pm, cid, r2.json()["id"])).status_code == 200
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "in_assessment"}, headers=lead)
    assert r.status_code == 200, r.text
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations", headers=lead)).json()
    assert {d["status"] for d in rows} == {"consumed"}
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin)).json()
    hop = next(e for e in log if e["action"] == "deviated_transition")
    assert "waives 'No quote deadline'" in hop["action_description"]
    assert "waives 'No scoping decision 'proceed''" in hop["action_description"]


async def test_override_refused_when_the_rule_does_not_hold(
        client, admin, seed, depts, session_factory):
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    r = await _propose(client, lead, cid, "in_assessment", guard_key="timing_not_validated")
    assert r.status_code == 400
    assert "nothing to override" in r.json()["detail"]
    r = await _propose(client, lead, cid, "in_assessment", reason_code="because")
    assert r.status_code == 400
    # a hop no soft rule holds: nothing to override
    cid2 = await _change(client, admin, seed, session_factory, "in_implementation")
    r = await _propose(client, lead, cid2, "on_hold")
    assert r.status_code == 400
    assert "Nothing to override" in r.json()["detail"]
    # the same rule twice: the second waits for the first
    assert (await _propose(client, lead, cid, "in_assessment",
                           guard_key="no_quote_deadline")).status_code == 200
    r = await _propose(client, lead, cid, "in_assessment", guard_key="no_quote_deadline")
    assert r.status_code == 400
    assert "already pending" in r.json()["detail"]


async def test_decider_is_never_a_plain_colleague_of_the_lead(
        client, admin, seed, depts, people, session_factory):
    """Before C6 any engineer could approve the lead's own deviation. Now
    the run team decides: PM member or admin (the lead proposed)."""
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await _propose(client, lead, cid, "in_assessment")).json()
    # the proposer, a Development colleague, Sales: refused (NEGATIVE)
    assert "own" in (await _decide(client, lead, cid, dev["id"])).json()["detail"]
    for who in ("Development", "Sales", "Quality"):
        r = await _decide(client, people[who][1], cid, dev["id"])
        assert r.status_code == 400, who
        assert "Project Management member or an admin" in r.json()["detail"]
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations",
                             headers=people["Sales"][1])).json()
    assert rows[0]["can_decide"] is False
    # the deciders were told once: PM members (the lead asked), not Sales
    from app.models.notification import Notification
    async with session_factory() as s:
        told = {n.user_id for n in (await s.execute(select(Notification).where(
            Notification.subject_key == f"dev:{dev['id']}"))).scalars()}
    assert people["Project Manager"][0] in told
    assert people["Sales"][0] not in told
    assert seed["engineer_id"] not in told
    assert (await _decide(client, people["Project Manager"][1], cid, dev["id"])).status_code == 200


async def test_quality_decides_overrides_into_implementation(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "approved",
                        impact_confirmed_at=datetime.utcnow())
    lead = await login(client, "eng@test.io", admin=False)
    r = await _propose(client, lead, cid, "in_implementation")
    assert r.status_code == 200, r.text
    dev = r.json()
    assert dev["guard_key"] == "timing_not_validated"
    assert dev["deciders"]["group"] == "quality"
    # PM member and a plain admin are not Quality (NEGATIVE)
    for auth in (people["Project Manager"][1], admin):
        r = await _decide(client, auth, cid, dev["id"])
        assert r.status_code == 400
        assert "Quality member" in r.json()["detail"]
    acting_quality = {**admin, ACTS: str(depts["Quality"])}
    assert (await _decide(client, acting_quality, cid, dev["id"])).status_code == 200


async def test_switch_off_keeps_the_old_deviation_rule(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await _propose(client, lead, cid, "in_assessment")).json()
    assert dev["guard_key"] is None
    # the old 4-eyes: any engineer decides the lead's deviation
    assert (await _decide(client, people["Development"][1], cid, dev["id"])).status_code == 200
    # and one approved deviation lifts every soft rule of the hop
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "in_assessment"}, headers=lead)
    assert r.status_code == 200, r.text


async def test_legacy_deviation_still_covers_an_in_flight_change(
        client, admin, seed, depts, session_factory):
    """A deviation approved before the binding (guard_key NULL) lets the
    in-flight change move as it did; it is consumed."""
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    async with session_factory() as s:
        s.add(ChangeTransitionDeviation(
            change_id=cid, to_status="in_assessment", reason="legacy",
            status="approved", proposed_by=seed["admin_id"],
            decided_by=seed["engineer_id"], decided_at=datetime.utcnow()))
        await s.commit()
    lead = await login(client, "eng@test.io", admin=False)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "in_assessment"}, headers=lead)
    assert r.status_code == 200, r.text


async def test_legacy_pending_is_bound_when_approved(
        client, admin, seed, depts, people, session_factory):
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    async with session_factory() as s:
        d = ChangeTransitionDeviation(change_id=cid, to_status="in_assessment",
                                      reason="legacy", proposed_by=seed["engineer_id"])
        s.add(d); await s.commit(); dev_id = d.id
    r = await _decide(client, people["Project Manager"][1], cid, dev_id)
    assert r.status_code == 200, r.text
    assert r.json()["guard_key"] == "no_quote_deadline"
    lead = await login(client, "eng@test.io", admin=False)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "in_assessment"}, headers=lead)
    assert r.status_code == 400
    assert r.headers.get("X-Deviation-Rule") == "no_proceed_meeting"


# ---------------------------------------------------------------------------
# C5: close costing waits for every finalized costing (SOFT)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def costing_pending(monkeypatch, depts):
    """Toolshop... here Tool Engineer owes its costing; every assessment
    is in (the routing side is not what C5 is about)."""
    from app.services.change_service import ChangeService
    from app.services.change_routing_service import ChangeRoutingService
    state = {"pending": [depts["Tool Engineer"]]}

    async def _pending(session, change):
        return list(state["pending"]) if change.status in ("in_assessment", "costing") else []

    async def _waiting(session, change):
        return []
    monkeypatch.setattr(ChangeService, "costing_pending_department_ids",
                        staticmethod(_pending))
    monkeypatch.setattr(ChangeRoutingService, "blocking_waiting", staticmethod(_waiting))
    return state


async def test_close_costing_waits_for_finalized_costing(
        client, admin, seed, depts, people, session_factory, costing_pending):
    cid = await _change(client, admin, seed, session_factory, "costing")
    pm = people["Project Manager"][1]
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "quoting"}, headers=pm)
    assert r.status_code == 400  # NEGATIVE: no quote on unfinished costing
    assert "Costing not finalized: Tool Engineer" in r.json()["detail"]
    assert r.headers.get("X-Deviation-Rule") == "costing_not_finalized"
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "costing_input")
    assert item["kind"] == "soft" and item["rule"] == "costing_not_finalized"
    assert item["who"].startswith("Tool Engineer")
    # the lead asks, PM decides; then the quote may start on the estimate
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await _propose(client, lead, cid, "quoting",
                          guard_key="costing_not_finalized")).json()
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "costing_input")
    assert item["override"] == {"id": dev["id"], "status": "pending"}
    assert (await _decide(client, pm, cid, dev["id"])).status_code == 200
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "quoting"}, headers=pm)
    assert r.status_code == 200, r.text


async def test_close_costing_switch_off(client, admin, seed, depts, people,
                                        session_factory, costing_pending, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    cid = await _change(client, admin, seed, session_factory, "costing")
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "quoting"},
                          headers=people["Project Manager"][1])
    assert r.status_code == 200, r.text


_DUE = (datetime.utcnow() + timedelta(days=90)).isoformat()


async def test_internal_approval_waits_for_finalized_costing(
        client, admin, seed, depts, people, session_factory, costing_pending):
    cid = await _change(client, admin, seed, session_factory, "costing",
                        customer=False, raised_by=seed["engineer_id"])
    pm = people["Project Manager"][1]
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE}, headers=pm)
    assert r.status_code == 400  # NEGATIVE
    assert "Costing not finalized" in r.json()["detail"]
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await _propose(client, lead, cid, "approved",
                          guard_key="costing_not_finalized")).json()
    assert (await _decide(client, pm, cid, dev["id"])).status_code == 200
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE}, headers=pm)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "approved"}, headers=pm)
    assert r.status_code == 200, r.text
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations", headers=pm)).json()
    assert rows[0]["status"] == "consumed"


# ---------------------------------------------------------------------------
# HARD #8: internal approval by an engineering approver, never the raiser
# ---------------------------------------------------------------------------

async def test_raiser_never_approves_own_internal_spend(
        client, admin, seed, depts, people, session_factory):
    pm_id, pm = people["Project Manager"]
    cid = await _change(client, admin, seed, session_factory, "costing",
                        customer=False, raised_by=pm_id)
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE}, headers=pm)
    assert r.status_code == 403  # NEGATIVE: the raiser, although a PM member
    assert "raiser" in r.json()["detail"]
    cid2 = await _change(client, admin, seed, session_factory, "costing",
                         customer=False, raised_by=seed["admin_id"])
    r = await client.post(f"/api/v1/changes/{cid2}/internal-approval",
                          json={"release_due_date": _DUE}, headers=admin)
    assert r.status_code == 403  # nor an admin who raised it
    r = await client.post(f"/api/v1/changes/{cid2}/internal-approval",
                          json={"release_due_date": _DUE}, headers=pm)
    assert r.status_code == 200, r.text


async def test_configured_approver_replaces_the_pm_rule(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "internal_approvers", "u_management, nobody@x.io")
    cid = await _change(client, admin, seed, session_factory, "costing",
                        customer=False, raised_by=seed["engineer_id"])
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE},
                          headers=people["Project Manager"][1])
    assert r.status_code == 403  # NEGATIVE: PM is no approver once one is named
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "internal_approval")
    assert item["kind"] == "hard" and item["who"] == "U Management"
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE},
                          headers=people["Management"][1])
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# HARD #3 (C7): failed check / open issue at release
# ---------------------------------------------------------------------------

async def _failed_weight(session_factory, cid, dept_id):
    from app.models.change_validation import ValidationCheck
    async with session_factory() as s:
        row = ValidationCheck(change_id=cid, department_id=dept_id, check_key="weight",
                              status="failed", value=12.4, checked_by=1,
                              checked_at=datetime.utcnow())
        s.add(row); await s.commit()
        return row.id


async def test_failed_check_is_hard_at_release(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    # even an approved override (legacy wildcard) and an admin do not lift it
    async with session_factory() as s:
        s.add(ChangeTransitionDeviation(
            change_id=cid, to_status="released", reason="ship it", status="approved",
            proposed_by=seed["engineer_id"], decided_by=seed["admin_id"],
            decided_at=datetime.utcnow()))
        await s.commit()
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert r.status_code == 400
    assert "Validation failed: Tool Engineer" in r.json()["detail"]
    assert "concession" in r.json()["detail"]
    assert "X-Deviation-Required" not in r.headers
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=admin)).json()
    assert st["can_transition"]["released"] is False
    assert st["transition_blocks"]["released"]["kind"] == "hard"
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "validation_failed")
    assert item["kind"] == "hard" and item["exits"] == ["concession"]
    # proposing an override for it is refused: it is no soft rule
    lead = await login(client, "eng@test.io", admin=False)
    r = await _propose(client, lead, cid, "released", guard_key="validation_failed")
    assert r.status_code == 400
    # a concession accepted by the customer covers the failed check
    from app.models.change_validation_issue import ValidationIssue
    async with session_factory() as s:
        s.add(ValidationIssue(change_id=cid, number=1, title="weight high", created_by=1,
                              description="12.4 g vs 12.2", check_id=check_id,
                              route="customer_concession", status="accepted"))
        await s.commit()
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert "Validation failed" not in r.json().get("detail", "")


async def test_open_issue_is_hard_and_switch_off_makes_it_soft(
        client, admin, seed, depts, session_factory, monkeypatch):
    from app.models.change_validation_issue import ValidationIssue
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    async with session_factory() as s:
        s.add(ValidationIssue(change_id=cid, number=1, title="flash", created_by=1,
                              description="flash on rib", status="open"))
        await s.commit()
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert r.status_code == 400
    assert "validation issue open" in r.json()["detail"]
    assert "X-Deviation-Required" not in r.headers
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert r.status_code == 400
    assert r.headers.get("X-Deviation-Required") == "released"


# ---------------------------------------------------------------------------
# HARD #9: sign-offs bound to the latest offer; no close with a price open
# ---------------------------------------------------------------------------

async def _offer(session_factory, cid, version, sent=True):
    from app.models.change_offer import ChangeOffer
    async with session_factory() as s:
        o = ChangeOffer(change_id=cid, version=version, status="sent" if sent else "draft",
                        currency="EUR", data={}, created_by=1,
                        sent_at=datetime.utcnow() if sent else None)
        s.add(o); await s.commit()
        return o.id


async def test_release_needs_signoffs_for_the_latest_offer(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "quoted")
    v1 = await _offer(session_factory, cid, 1)
    for role, who in (("pm", "Project Manager"), ("quality", "Quality")):
        r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": role},
                              headers=people[who][1])
        assert r.status_code == 200, r.text
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        assert c.pm_signed_offer_id == v1 and c.quality_signed_offer_id == v1
        c.status = "in_validation"
        await s.commit()
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        assert await ChangeService.signoff_offer_refusal(s, c) is None
    await _offer(session_factory, cid, 2)  # a supplement went out after
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert r.status_code == 400  # NEGATIVE
    assert "PM and Quality sign-off missing for offer v2" in r.json()["detail"]


async def test_price_open_blocks_close_and_absorb_clears_it(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "released", price_open=True)
    pm_id, pm = people["Project Manager"]
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "closed"}, headers=admin)
    assert r.status_code == 400  # NEGATIVE: not even an admin
    assert "price is still open" in r.json()["detail"]
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "price_open")
    assert item["kind"] == "hard" and item["exits"] == ["customer_accepts", "absorb"]
    # Development may not ask to absorb (NEGATIVE); Sales may
    r = await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "goodwill", "note": "x"}, headers=people["Development"][1])
    assert r.status_code == 403
    r = await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "because", "note": "x"}, headers=people["Sales"][1])
    assert r.status_code == 400
    r = await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "small_amount", "note": "EUR 300 over, not worth a supplement"},
        headers=people["Sales"][1])
    assert r.status_code == 200, r.text
    dev = r.json()
    assert dev["guard_key"] == "price_open" and dev["deciders"]["group"] == "pm_mgmt"
    # neither the proposer, nor Quality, nor a plain admin give the OK
    for auth in (people["Sales"][1], people["Quality"][1], admin):
        assert (await _decide(client, auth, cid, dev["id"])).status_code == 400
    r = await _decide(client, people["Management"][1], cid, dev["id"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "consumed"
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).price_open is False
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "closed"}, headers=admin)
    assert r.status_code == 200, r.text
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin)).json()
    assert any(e["action"] == "price_absorbed" for e in log)


async def test_internal_absorb_is_the_approvers_call(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "internal_approvers", "u_management")
    cid = await _change(client, admin, seed, session_factory, "approved",
                        customer=False, price_open=True, raised_by=seed["engineer_id"])
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "our_error", "note": "estimate low by 2k"}, headers=lead)).json()
    assert dev["deciders"]["group"] == "approver"
    r = await _decide(client, people["Project Manager"][1], cid, dev["id"])
    assert r.status_code == 400  # NEGATIVE: PM is not the approver here
    assert (await _decide(client, people["Management"][1], cid, dev["id"])).status_code == 200


async def test_customer_acceptance_closes_the_open_price(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "quoted", price_open=True)
    r = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": _DUE}, headers=admin)
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        assert (await s.get(ChangeRequest, cid)).price_open is False


async def test_price_open_switch_off_closes(client, admin, seed, depts,
                                            session_factory, monkeypatch):
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    cid = await _change(client, admin, seed, session_factory, "released", price_open=True)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "closed"}, headers=admin)
    assert r.status_code == 200, r.text
