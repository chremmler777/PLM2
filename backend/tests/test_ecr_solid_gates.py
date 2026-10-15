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
        "to_status": to, "reason": "customer SOP 24 Oct, mail 2026-10-12",
        "reason_code": "in_parallel", **extra}, headers=auth)


async def _decide(client, auth, cid, dev_id, decision="approved"):
    return await client.post(f"/api/v1/changes/{cid}/deviations/{dev_id}/decide",
                             json={"decision": decision,
                                   **({"note": "not covered: wait for the costs"}
                                      if decision == "rejected" else {})}, headers=auth)


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
    assert r2.json()["reason_code"] == "in_parallel"
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
                          json={"release_due_date": _DUE, "rationale": "quality"}, headers=pm)
    assert r.status_code == 400  # NEGATIVE
    assert "Costing not finalized" in r.json()["detail"]
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await _propose(client, lead, cid, "approved",
                          guard_key="costing_not_finalized")).json()
    assert (await _decide(client, pm, cid, dev["id"])).status_code == 200
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"}, headers=pm)
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
                          json={"release_due_date": _DUE, "rationale": "quality"}, headers=pm)
    assert r.status_code == 403  # NEGATIVE: the raiser, although a PM member
    assert "raiser" in r.json()["detail"]
    cid2 = await _change(client, admin, seed, session_factory, "costing",
                         customer=False, raised_by=seed["admin_id"])
    r = await client.post(f"/api/v1/changes/{cid2}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"}, headers=admin)
    assert r.status_code == 403  # nor an admin who raised it
    r = await client.post(f"/api/v1/changes/{cid2}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"}, headers=pm)
    assert r.status_code == 200, r.text


async def test_configured_approver_replaces_the_pm_rule(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "internal_approvers", "u_management, nobody@x.io")
    cid = await _change(client, admin, seed, session_factory, "costing",
                        customer=False, raised_by=seed["engineer_id"])
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"},
                          headers=people["Project Manager"][1])
    assert r.status_code == 403  # NEGATIVE: PM is no approver once one is named
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "internal_approval")
    assert item["kind"] == "hard" and item["who"] == "U Management"
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"},
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
    # a concession Quality accepted covers the failed check
    from app.models.change_validation_issue import ValidationIssue
    async with session_factory() as s:
        s.add(ValidationIssue(change_id=cid, number=1, title="weight high", created_by=1,
                              description="12.4 g vs 12.2", check_id=check_id,
                              route="customer_concession", status="accepted",
                              customer_decision="accept_deviation",
                              customer_decided_by=people["Quality"][0]))
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


# ---------------------------------------------------------------------------
# L2 review loop 1
# ---------------------------------------------------------------------------

async def _told(session_factory, subject_key):
    from app.models.notification import Notification
    async with session_factory() as s:
        return {n.user_id for n in (await s.execute(select(Notification).where(
            Notification.subject_key == subject_key))).scalars()}


async def test_approver_who_raised_the_change_falls_back_to_pm(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    """HARD #8: the only configured approver raised the internal change. A
    PM member (or an admin) approves instead, the row names who, and the
    raiser still cannot (no dead end, R18)."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "internal_approvers", "u_management")
    mgmt_id, mgmt = people["Management"]
    cid = await _change(client, admin, seed, session_factory, "costing",
                        customer=False, raised_by=mgmt_id)
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "internal_approval")
    assert item["who"] == "a Project Management member or an admin"
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state",
                           headers=people["Project Manager"][1])).json()
    assert st["can_approve_internal"] is True
    assert st["internal_approvers"] == "a Project Management member or an admin"
    assert st["internal_needs_money"] is False      # no cost: one click
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"}, headers=mgmt)
    assert r.status_code == 403  # NEGATIVE: the raiser, although the approver
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"},
                          headers=people["Project Manager"][1])
    assert r.status_code == 200, r.text


async def test_internal_absorb_tells_the_fallback_deciders(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    """With no configured approver for the change, the PM members decide
    an internal Absorb, so they are the ones told (never the raiser)."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "internal_approvers", "nobody@x.io")
    cid = await _change(client, admin, seed, session_factory, "approved",
                        customer=False, price_open=True, raised_by=seed["engineer_id"])
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "our_error", "note": "estimate low on the insert"},
        headers=lead)).json()
    told = await _told(session_factory, f"dev:{dev['id']}")
    assert people["Project Manager"][0] in told
    assert seed["engineer_id"] not in told
    assert people["Sales"][0] not in told


async def _concession(session_factory, cid, check_id, uploader, *, mail=True, **values):
    from app.models.change import ChangeAttachment
    from app.models.change_validation_issue import ValidationIssue
    async with session_factory() as s:
        i = ValidationIssue(change_id=cid, number=1, title="weight high", created_by=1,
                            description="12.4 g vs 12.2", check_id=check_id,
                            route="customer_concession", status="route_decided",
                            customer_inform=True, **values)
        s.add(i); await s.flush()
        if mail:
            s.add(ChangeAttachment(change_id=cid, filename="yes.msg", stored_path="x",
                                   content_type="application/vnd.ms-outlook",
                                   size_bytes=1, sha256="0" * 64, kind="customer_email",
                                   validation_issue_id=i.id, uploaded_by=uploader))
        await s.commit()
        return i.id


async def test_concession_is_qualitys_decision(
        client, admin, seed, depts, people, session_factory):
    """HARD #3: the only exit from a failed check is a concession Quality
    decides once the customer's mail is filed. Sales, PM and an admin
    cannot produce it alone (no admin shortcut, R1/R25)."""
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    iid = await _concession(session_factory, cid, check_id, people["Sales"][0])
    url = f"/api/v1/changes/{cid}/validation/issues/{iid}/customer"
    yes = {"decision": "accept_deviation", "note": "customer mail 14 Oct: ship as is"}
    for auth in (people["Sales"][1], admin, people["Project Manager"][1]):
        r = await client.post(url, json=yes, headers=auth)
        assert r.status_code == 403, r.text  # NEGATIVE
        assert "Quality decides the concession" in r.json()["detail"]
    issues = (await client.get(f"/api/v1/changes/{cid}/validation/issues",
                               headers=people["Sales"][1])).json()
    row = issues[0] if isinstance(issues, list) else issues["issues"][0]
    assert "accept_deviation" not in row["customer_options"]
    issues = (await client.get(f"/api/v1/changes/{cid}/validation/issues",
                               headers=people["Quality"][1])).json()
    row = issues[0] if isinstance(issues, list) else issues["issues"][0]
    assert "accept_deviation" in row["customer_options"]
    assert "customer" in row["next_acts"]
    r = await client.post(url, json=yes, headers=people["Quality"][1])
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert "Validation failed" not in r.json().get("detail", "")


async def test_concession_recorded_without_quality_does_not_release(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    """An accepted concession whose yes nobody in Quality gave (recorded
    before the rule, or by Sales) does not lift HARD #3; with RELEASE_V2 off
    it does, as before."""
    from app.models.change_validation_issue import ValidationIssue
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    async with session_factory() as s:
        s.add(ValidationIssue(change_id=cid, number=1, title="weight high", created_by=1,
                              description="12.4 g vs 12.2", check_id=check_id,
                              route="customer_concession", status="accepted",
                              customer_decision="accept_deviation",
                              customer_decided_by=people["Sales"][0]))
        await s.commit()
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert r.status_code == 400
    assert "Validation failed" in r.json()["detail"]
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    from app.services.validation_service import ValidationService
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        failed, _ = await ValidationService.release_parts(s, c)
    assert failed is None


async def _sign(client, people, cid):
    for role, who in (("pm", "Project Manager"), ("quality", "Quality")):
        r = await client.post(f"/api/v1/changes/{cid}/sign-off", json={"role": role},
                              headers=people[who][1])
        assert r.status_code == 200, r.text


async def test_approval_and_release_use_one_signoff_rule_and_resign_is_the_way_out(
        client, admin, seed, depts, people, session_factory):
    """HARD #4/#9 (R37): a signature counts for the offer it was given on,
    at approval as at release; signing again for the latest offer is the
    way out, at quoted and later (no dead end, R18)."""
    cid = await _change(client, admin, seed, session_factory, "quoted",
                        customer_response="accepted",
                        release_due_date=datetime.utcnow() + timedelta(days=60))
    await _offer(session_factory, cid, 1)
    await _sign(client, people, cid)
    await _offer(session_factory, cid, 2)  # v2 went out after the signatures
    pm = people["Project Manager"][1]
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "approved"}, headers=pm)
    assert r.status_code == 400  # NEGATIVE: no approval on v1's signatures
    assert "sign-off missing for offer v2" in r.json()["detail"]
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    keys = {i["key"]: i for i in ch["next_step"]["items"]}
    assert keys["pm_signoff"]["sides"] == ["pm"] and keys["pm_signoff"]["detail"] == "v2"
    assert keys["quality_signoff"]["exits"] == ["sign"]
    await _sign(client, people, cid)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "approved"}, headers=pm)
    assert r.status_code == 200, r.text
    # a supplement after approval: release names the sides, signing clears it
    await _offer(session_factory, cid, 3)
    async with session_factory() as s:
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid)
                        .values(status="in_validation"))
        await s.commit()
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    row = next(i for i in ch["next_step"]["items"] if i["key"] == "release_signoffs")
    assert row["sides"] == ["pm", "quality"] and row["detail"] == "v3"
    assert row["who"] == "Project Management and Quality"
    assert ch["pm_signed_offer_id"] is not None
    await _sign(client, people, cid)
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    assert not any(i["key"] == "release_signoffs" for i in ch["next_step"]["items"])


async def test_signoff_rules_switch_off(client, admin, seed, depts, people,
                                        session_factory, monkeypatch):
    """COMMERCIAL_V2 off: approval checks only that both signed; RELEASE_V2
    off: release does not check the offer binding."""
    monkeypatch.setattr(cm_switches, "COMMERCIAL_V2", False)
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    cid = await _change(client, admin, seed, session_factory, "quoted",
                        customer_response="accepted",
                        release_due_date=datetime.utcnow() + timedelta(days=60))
    await _offer(session_factory, cid, 1)
    await _sign(client, people, cid)
    await _offer(session_factory, cid, 2)
    from app.services.early_stage_service import EarlyStageService
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        assert await EarlyStageService.hard_refusal(s, c, "approved") is None
        c.status = "in_validation"
        assert await EarlyStageService.hard_refusal(s, c, "released") is None


async def test_absorb_note_is_price_talk(client, admin, seed, depts, people,
                                         session_factory):
    """R23: an Absorb note names the money; a viewer outside the price rule
    (here Development, as Toolshop or Quality) reads the rule and the people,
    never the note, in the override list and the changelog."""
    cid = await _change(client, admin, seed, session_factory, "released", price_open=True)
    note = "EUR 300 over the offer, not worth a supplement"
    dev = (await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "small_amount", "note": note}, headers=people["Sales"][1])).json()
    dev_auth = people["Development"][1]
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations", headers=dev_auth)).json()
    assert rows[0]["reason"] == "" and rows[0]["guard_key"] == "price_open"
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations",
                             headers=people["Project Manager"][1])).json()
    assert rows[0]["reason"] == note  # a price viewer reads it
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev['id']}/decide",
                          json={"decision": "approved", "note": "ok, EUR 300 is fine"},
                          headers=people["Management"][1])
    assert r.status_code == 200, r.text
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=dev_auth)).json()
    text = " ".join(f"{e['action_description']} {e.get('notes') or ''}" for e in log)
    assert "EUR" not in text  # NEGATIVE: no amount leaks
    absorbed = next(e for e in log if e["action"] == "price_absorbed")
    assert absorbed["action_description"] == f"Open price absorbed (#{dev['id']})"
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin)).json()
    assert any(note in (e.get("notes") or "") for e in log)


async def test_override_needs_a_reason_pick_and_a_real_note(
        client, admin, seed, depts, people, session_factory):
    """R4: no default pick, no one-word note, 'customer date' names the date
    or the mail; the API refuses what the dialog refuses (scripts too)."""
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    base = {"to_status": "in_assessment", "guard_key": "no_quote_deadline"}
    for body, words in (
            ({"reason": "customer SOP 24 Oct per mail"}, "Pick a reason"),
            ({"reason": "x", "reason_code": "other"}, "says too little"),
            ({"reason": "urgent", "reason_code": "in_parallel"}, "says too little"),
            ({"reason": "the customer is waiting for us", "reason_code": "customer_date"},
             "name the date")):
        r = await client.post(f"/api/v1/changes/{cid}/deviations",
                              json={**base, **body}, headers=lead)
        assert r.status_code == 400, body  # NEGATIVE
        assert words in r.json()["detail"]
    # the legacy transition path (202) asks for the pick as well
    r = await client.post(f"/api/v1/changes/{cid}/transition", json={
        "to_status": "in_assessment", "deviation_reason": "customer SOP 24 Oct"},
        headers=lead)
    assert r.status_code == 400 and "Pick a reason" in r.json()["detail"]
    r = await client.post(f"/api/v1/changes/{cid}/transition", json={
        "to_status": "in_assessment", "deviation_reason": "customer SOP 24 Oct",
        "deviation_reason_code": "customer_date"}, headers=lead)
    assert r.status_code == 202, r.text
    assert "needs the OK of the lead, a Project Management member or an admin" \
        in r.json()["detail"]
    assert r.json()["deviation"]["reason_code"] == "customer_date"


async def test_asker_hears_the_decision_and_a_reject_says_why(
        client, admin, seed, depts, people, session_factory):
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    pm = people["Project Manager"][1]
    dev = (await _propose(client, lead, cid, "in_assessment",
                          guard_key="no_quote_deadline")).json()
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev['id']}/decide",
                          json={"decision": "rejected"}, headers=pm)
    assert r.status_code == 400  # NEGATIVE: a reject without a word
    assert "Say why" in r.json()["detail"]
    r = await client.post(f"/api/v1/changes/{cid}/deviations/{dev['id']}/decide",
                          json={"decision": "rejected", "note": "set the deadline first"},
                          headers=pm)
    assert r.status_code == 200, r.text
    from app.models.notification import Notification
    async with session_factory() as s:
        rows = (await s.execute(select(Notification).where(
            Notification.subject_key == f"dev:{dev['id']}:decided"))).scalars().all()
    assert [n.user_id for n in rows] == [seed["engineer_id"]]
    assert "rejected" in rows[0].title and rows[0].body == "set the deadline first"


async def test_internal_open_price_names_its_own_exit(client, admin, seed, depts,
                                                      session_factory):
    cid = await _change(client, admin, seed, session_factory, "released",
                        customer=False, price_open=True)
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    item = next(i for i in ch["next_step"]["items"] if i["key"] == "price_open")
    assert item["exits"] == ["absorb_internal"]  # no customer to accept


async def test_unused_override_lapses_when_the_change_moves_on(
        client, admin, seed, depts, people, session_factory):
    """An approved override is an OK for the step out of the status it was
    given in: one not used lapses when the change leaves it, so it never
    covers its rule again later without a new decision."""
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    pm = people["Project Manager"][1]
    dev = (await _propose(client, lead, cid, "in_assessment",
                          guard_key="no_quote_deadline")).json()
    assert (await _decide(client, pm, cid, dev["id"])).status_code == 200
    r = await client.post(f"/api/v1/changes/{cid}/transition", json={
        "to_status": "on_hold", "reason": "customer pauses the project until Nov"},
        headers=pm)
    assert r.status_code == 200, r.text
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations", headers=pm)).json()
    assert rows[0]["status"] == "lapsed"


async def test_acceptance_withdraws_a_pending_absorb(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "quoted", price_open=True)
    dev = (await client.post(f"/api/v1/changes/{cid}/absorb", json={
        "reason_code": "small_amount", "note": "EUR 300 over, not worth it"},
        headers=people["Sales"][1])).json()
    r = await client.post(f"/api/v1/changes/{cid}/customer-response", json={
        "response": "accepted", "release_due_date": _DUE}, headers=admin)
    assert r.status_code == 200, r.text
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations", headers=admin)).json()
    assert next(d for d in rows if d["id"] == dev["id"])["status"] == "withdrawn"
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions",
                             headers=people["Management"][1])).json()
    rows = acts if isinstance(acts, list) else acts.get("actions", [])
    assert not any(a.get("deviation_id") == dev["id"] for a in rows)


async def test_failed_check_switch_off_is_soft_again(
        client, admin, seed, depts, session_factory, monkeypatch):
    monkeypatch.setattr(cm_switches, "RELEASE_V2", False)
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert r.status_code == 400
    assert r.headers.get("X-Deviation-Required") == "released"  # soft, as before


async def test_internal_approval_switch_off_skips_the_costing_check(
        client, admin, seed, depts, people, session_factory, costing_pending, monkeypatch):
    monkeypatch.setattr(cm_switches, "ASSESSMENT_V2", False)
    cid = await _change(client, admin, seed, session_factory, "costing",
                        customer=False, raised_by=seed["engineer_id"])
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"},
                          headers=people["Project Manager"][1])
    assert r.status_code == 200, r.text


async def test_quality_decides_a_validation_override_into_release(
        client, admin, seed, depts, people, session_factory):
    from app.models.change_validation import ValidationCheck
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    async with session_factory() as s:
        s.add(ValidationCheck(change_id=cid, department_id=depts["Tool Engineer"],
                              check_key="weight", status="open"))
        await s.commit()
    lead = await login(client, "eng@test.io", admin=False)
    r = await _propose(client, lead, cid, "released", guard_key="validation_open")
    assert r.status_code == 200, r.text
    dev = r.json()
    assert dev["deciders"]["group"] == "quality"
    r = await _decide(client, people["Project Manager"][1], cid, dev["id"])
    assert r.status_code == 400  # NEGATIVE: PM is not Quality here
    assert (await _decide(client, people["Quality"][1], cid, dev["id"])).status_code == 200


# ---------------------------------------------------------------------------
# L2 review loop 2
# ---------------------------------------------------------------------------

async def test_admin_acting_as_quality_concession_counts_at_release(
        client, admin, seed, depts, people, session_factory):
    """One Quality rule (R37): an admin acting as Quality may record the
    concession's yes (like a Quality override), and then it counts at
    release; the flag is stored with the decision."""
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    iid = await _concession(session_factory, cid, check_id, people["Sales"][0])
    r = await client.post(
        f"/api/v1/changes/{cid}/validation/issues/{iid}/customer",
        json={"decision": "accept_deviation", "note": "customer mail 14 Oct: ship"},
        headers={**admin, ACTS: str(depts["Quality"])})
    assert r.status_code == 200, r.text
    from app.models.change_validation_issue import ValidationIssue
    async with session_factory() as s:
        assert (await s.get(ValidationIssue, iid)).customer_decided_as_quality is True
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert "Validation failed" not in r.json().get("detail", "")


async def test_quality_confirms_a_concession_sales_accepted(
        client, admin, seed, depts, people, session_factory):
    """No dead end (R18): an 'accepted' concession whose yes was Sales'
    (before the rule) does not count; Quality confirms it on the card."""
    from app.models.change_validation_issue import ValidationIssue
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    async with session_factory() as s:
        i = ValidationIssue(change_id=cid, number=1, title="weight high", created_by=1,
                            description="12.4 g vs 12.2", check_id=check_id,
                            route="customer_concession", status="accepted",
                            customer_decision="accept_deviation",
                            customer_decided_by=people["Sales"][0],
                            customer_decided_as_quality=False)
        s.add(i); await s.commit(); iid = i.id
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert "Validation failed" in r.json()["detail"]  # NEGATIVE
    issues = (await client.get(f"/api/v1/changes/{cid}/validation/issues",
                               headers=people["Quality"][1])).json()
    row = issues[0] if isinstance(issues, list) else issues["issues"][0]
    assert row["primary_act"] == "customer"
    url = f"/api/v1/changes/{cid}/validation/issues/{iid}/customer"
    yes = {"decision": "accept_deviation", "note": "mail 12 Oct read, ship as is"}
    r = await client.post(url, json=yes, headers=people["Sales"][1])
    assert r.status_code == 403  # NEGATIVE: Sales cannot confirm its own yes
    r = await client.post(url, json=yes, headers=people["Quality"][1])
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert "Validation failed" not in r.json().get("detail", "")


async def test_quality_concession_task_waits_for_the_mail(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    check_id = await _failed_weight(session_factory, cid, depts["Tool Engineer"])
    await _concession(session_factory, cid, check_id, people["Sales"][0], mail=False)
    issues = (await client.get(f"/api/v1/changes/{cid}/validation/issues",
                               headers=people["Quality"][1])).json()
    row = issues[0] if isinstance(issues, list) else issues["issues"][0]
    assert "customer" not in row["next_acts"]  # NEGATIVE: Sales files first
    assert row["customer_options"] == ["accept_deviation"]


async def test_raised_in_error_is_qualitys_close(
        client, admin, seed, depts, people, session_factory):
    """HARD #3: an open issue is no longer closed by PM, the lead or an
    admin with any note; Quality closes it as raised in error with the
    evidence."""
    from app.models.change_validation_issue import ValidationIssue
    cid = await _change(client, admin, seed, session_factory, "in_validation",
                        customer=False)
    async with session_factory() as s:
        i = ValidationIssue(change_id=cid, number=1, title="flash", created_by=1,
                            description="flash on rib", status="open")
        s.add(i); await s.commit(); iid = i.id
    url = f"/api/v1/changes/{cid}/validation/issues/{iid}/close"
    for auth in (admin, people["Project Manager"][1]):
        r = await client.post(url, json={"note": "not an issue"}, headers=auth)
        assert r.status_code == 403, r.text  # NEGATIVE
    r = await client.post(url, json={"note": "ok"}, headers=people["Quality"][1])
    assert r.status_code == 400  # NEGATIVE: no evidence
    r = await client.post(url, json={"note": "drawing rev C allows flash 0.2, MR-2231"},
                          headers=people["Quality"][1])
    assert r.status_code == 200, r.text


async def test_hard_rule_holding_the_move_refuses_the_override_ask(
        client, admin, seed, depts, people, session_factory):
    """C6 / HARD #1: an unlocked impacted set holds scoping -> assessment; the
    refusal names it (no override headers) and an override ask is refused,
    so nobody approves an override that lifts nothing."""
    cid = await _change(client, admin, seed, session_factory, "scoping")
    lead = await login(client, "eng@test.io", admin=False)
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "in_assessment"}, headers=lead)
    assert r.status_code == 400
    assert "Impacted set is not locked" in r.json()["detail"]
    assert "X-Deviation-Required" not in r.headers
    r = await _propose(client, lead, cid, "in_assessment", guard_key="no_proceed_meeting")
    assert r.status_code == 400  # NEGATIVE
    assert "no override lifts this" in r.json()["detail"]


async def test_routing_change_is_decided_not_overridden(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    from app.models.change import ChangeRouting
    from app.services.change_routing_service import ChangeRoutingService

    async def _none(session, change):
        return []
    monkeypatch.setattr(ChangeRoutingService, "blocking_rows", staticmethod(_none))
    cid = await _change(client, admin, seed, session_factory, "in_assessment")
    async with session_factory() as s:
        s.add(ChangeRouting(change_id=cid, deviation_status="pending_approval",
                            has_deviation=True))
        await s.commit()
    lead = await login(client, "eng@test.io", admin=False)
    pm = people["Project Manager"][1]
    r = await _propose(client, lead, cid, "costing", guard_key="routing_deviation_pending")
    assert r.status_code == 400  # NEGATIVE: decided, never overridden
    assert "decided, not overridden" in r.json()["detail"]
    # an ask without a key binds to the other rule, never to the routing one
    dev = await _propose(client, lead, cid, "costing")
    assert dev.status_code == 200, dev.text
    assert dev.json()["guard_key"] == "assessments_open"
    assert (await _decide(client, pm, cid, dev.json()["id"])).status_code == 200
    r = await client.post(f"/api/v1/changes/{cid}/transition",
                          json={"to_status": "costing"}, headers=pm)
    assert r.status_code == 400
    assert "Decide the routing change" in r.json()["detail"]
    assert "X-Deviation-Required" not in r.headers
    assert "X-Deviation-Rule" not in r.headers
    st = (await client.get(f"/api/v1/changes/{cid}/stage-state", headers=pm)).json()
    block = st["transition_blocks"]["costing"]
    assert block["kind"] == "decide" and block["deviation_possible"] is False


async def test_pending_override_is_withdrawn_when_the_change_moves(
        client, admin, seed, depts, people, session_factory):
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    pm = people["Project Manager"][1]
    dev = (await _propose(client, lead, cid, "in_assessment",
                          guard_key="no_quote_deadline")).json()
    r = await client.post(f"/api/v1/changes/{cid}/transition", json={
        "to_status": "on_hold", "reason": "customer pauses the project until Nov"},
        headers=pm)
    assert r.status_code == 200, r.text
    rows = (await client.get(f"/api/v1/changes/{cid}/deviations", headers=pm)).json()
    assert rows[0]["status"] == "withdrawn"
    r = await _decide(client, pm, cid, dev["id"])
    assert r.status_code == 400  # NEGATIVE: nothing left to decide
    acts = (await client.get(f"/api/v1/changes/{cid}/my-actions", headers=pm)).json()
    rows = acts if isinstance(acts, list) else acts.get("actions", [])
    assert not any(a.get("deviation_id") == dev["id"] for a in rows)
    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin)).json()
    assert any(e["action"] == "deviation_withdrawn" for e in log)


async def test_approval_is_no_immediate_notice_to_the_asker(
        client, admin, seed, depts, people, session_factory):
    """Spec §0 Notifications: the asker is told at once on a rejection; an
    approval of a non-urgent change is a badge. The deciders' notice names
    the asker and the reason."""
    cid = await _scoping_two_rules(client, admin, seed, session_factory)
    lead = await login(client, "eng@test.io", admin=False)
    dev = (await _propose(client, lead, cid, "in_assessment",
                          guard_key="no_quote_deadline")).json()
    from app.models.notification import Notification
    async with session_factory() as s:
        n = (await s.execute(select(Notification).where(
            Notification.subject_key == f"dev:{dev['id']}"))).scalars().first()
    assert "customer SOP 24 Oct" in n.body and "asks for an override" in n.body
    assert (await _decide(client, people["Project Manager"][1], cid,
                          dev["id"])).status_code == 200
    assert await _told(session_factory, f"dev:{dev['id']}:decided") == set()


async def test_internal_approver_acting_as_a_department_is_refused(
        client, admin, seed, depts, people, session_factory, monkeypatch):
    """HARD #8: a configured approver approves as themselves, never while
    acting as a department."""
    from app.core.config import get_settings
    async with session_factory() as s:
        await s.execute(update(User).where(User.id == seed["admin_id"])
                        .values(username="boss_admin"))
        await s.commit()
    monkeypatch.setattr(get_settings(), "internal_approvers", "boss_admin")
    cid = await _change(client, admin, seed, session_factory, "costing",
                        customer=False, raised_by=seed["engineer_id"])
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"},
                          headers={**admin, ACTS: str(depts["Project Manager"])})
    assert r.status_code == 403, r.text  # NEGATIVE
    r = await client.post(f"/api/v1/changes/{cid}/internal-approval",
                          json={"release_due_date": _DUE, "rationale": "quality"}, headers=admin)
    assert r.status_code == 200, r.text


async def test_quality_signs_again_only_when_the_offer_changed_technically(
        client, admin, seed, depts, people, session_factory):
    """Spec §7: PM signs every newer offer; Quality only when the quote plan
    or the parts (an index included) changed."""
    from app.models.change_offer import ChangeOffer
    cid = await _change(client, admin, seed, session_factory, "quoted",
                        customer_response="accepted",
                        release_due_date=datetime.utcnow() + timedelta(days=60))
    snap = {"tasks": [], "items": [{"number": "886.197", "name": "Cover", "index": "C"}]}
    async with session_factory() as s:
        for v in (1, 2):
            s.add(ChangeOffer(change_id=cid, version=v, status="sent", currency="EUR",
                              data={"_snapshot": snap}, created_by=1,
                              sent_at=datetime.utcnow() + timedelta(seconds=v)))
        await s.commit()
        v1 = (await s.execute(select(ChangeOffer.id).where(
            ChangeOffer.change_id == cid, ChangeOffer.version == 1))).scalar()
        await s.execute(update(ChangeRequest).where(ChangeRequest.id == cid).values(
            pm_signed_by=people["Project Manager"][0], pm_signed_offer_id=v1,
            quality_signed_by=people["Quality"][0], quality_signed_offer_id=v1))
        await s.commit()
    pm = people["Project Manager"][1]
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    keys = {i["key"] for i in ch["next_step"]["items"]}
    assert "pm_signoff" in keys and "quality_signoff" not in keys  # price-only v2
    # v3 changes a part index: Quality signs again
    async with session_factory() as s:
        s.add(ChangeOffer(change_id=cid, version=3, status="sent", currency="EUR",
                          data={"_snapshot": {**snap, "items": [
                              {"number": "886.197", "name": "Cover", "index": "D"}]}},
                          created_by=1, sent_at=datetime.utcnow() + timedelta(seconds=9)))
        await s.commit()
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=pm)).json()
    keys = {i["key"] for i in ch["next_step"]["items"]}
    assert {"pm_signoff", "quality_signoff"} <= keys


async def test_customer_acceptance_names_its_exit_and_release_needs_signatures(
        client, admin, seed, depts, people, session_factory):
    cid = await _change(client, admin, seed, session_factory, "quoted")
    ch = (await client.get(f"/api/v1/changes/{cid}", headers=admin)).json()
    keys = {i["key"]: i for i in ch["next_step"]["items"]}
    assert keys["customer_accepted"]["exits"] == ["record_answer"]
    # a customer change with no offer sent cannot release unsigned (HARD #9)
    cid2 = await _change(client, admin, seed, session_factory, "in_validation")
    r = await client.post(f"/api/v1/changes/{cid2}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert r.status_code == 400  # NEGATIVE
    assert "PM and Quality sign-off missing" in r.json()["detail"]
    assert "X-Deviation-Required" not in r.headers
    ch = (await client.get(f"/api/v1/changes/{cid2}", headers=admin)).json()
    row = next(i for i in ch["next_step"]["items"] if i["key"] == "release_signoffs")
    assert row["sides"] == ["pm", "quality"] and "detail" not in row
    await _sign(client, people, cid2)
    r = await client.post(f"/api/v1/changes/{cid2}/transition",
                          json={"to_status": "released"}, headers=admin)
    assert "sign-off missing" not in r.json().get("detail", "")
    # a change from the mother plant has no sign-offs: never held by them
    cid3 = await _change(client, admin, seed, session_factory, "in_validation",
                         origin="mother_plant")
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        assert await ChangeService.signoff_offer_refusal(
            s, await s.get(ChangeRequest, cid3)) is None
