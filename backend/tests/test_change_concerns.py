"""Concerns: parallel team flags feeding the scoping decision."""
import pytest

pytestmark = pytest.mark.asyncio


async def _change_in_scoping(client, auth, seed, suffix):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": f"concern {suffix}",
        "change_type": "physical_part", "lead_id": seed["engineer_id"]}, headers=auth)
    assert res.status_code in (200, 201), res.text
    cid = res.json()["id"]
    part = await client.post("/api/v1/parts", json={
        "project_id": seed["project_id"], "part_number": f"ART-C{suffix}",
        "name": "Part", "part_type": "internal_mfg"}, headers=auth)
    assert part.status_code in (200, 201), part.text
    await client.post(f"/api/v1/changes/{cid}/impacted-items",
                      json={"part_id": part.json()["id"], "is_lead": True}, headers=auth)
    # Complete the capture (description + attachment + required-by date) so
    # these tests exercise the concern rules rather than the kickoff gate.
    from tests.conftest import satisfy_capture_gate
    await satisfy_capture_gate(client, auth, cid)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    return cid


async def _dept_ids(session_factory):
    """Real department ids — the meeting validates them."""
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.services.wf_seed_service import seed_assessment_standard
    async with session_factory() as s:
        await seed_assessment_standard(s)
        await s.commit()
    async with session_factory() as s:
        return [d for (d,) in await s.execute(select(Department.id).limit(1))]


async def _lock_impact(session_factory, cid):
    """Assessment is hard-gated on a locked impacted set; lock it directly so
    these tests reach the concern rules."""
    from datetime import datetime
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.impact_confirmed_at = datetime.utcnow()
        c.impact_confirmed_by = c.raised_by
        await s.commit()


async def _meeting(client, auth, cid, dept_ids):
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "selected_department_ids": dept_ids}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def test_concern_records_who_objects_and_why(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "1")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "reject_proposal", "note": "Tool cannot hold the tolerance"})
    assert res.status_code == 200, res.text
    c = res.json()
    assert c["kind"] == "reject_proposal"
    assert c["note"] == "Tool cannot hold the tolerance"
    assert c["raised_by"] == seed["engineer_id"]
    assert c["raised_by_name"]           # the flag names its author
    assert c["is_open"] is True


async def test_concern_needs_a_note(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "2")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "   "})
    assert res.status_code == 400, res.text


async def test_second_open_concern_of_a_kind_is_refused(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "3")
    body = {"kind": "needs_info", "note": "Missing the CAD"}
    assert (await client.post(f"/api/v1/changes/{cid}/concerns", json=body,
                              headers=eng_auth)).status_code == 200
    res = await client.post(f"/api/v1/changes/{cid}/concerns", json=body, headers=eng_auth)
    assert res.status_code == 400, res.text
    assert "already have an open concern" in res.json()["detail"]


async def test_only_the_author_may_withdraw_even_for_an_admin(
        client, eng_auth, admin_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "4")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "reject_proposal", "note": "No capacity"})
    concern_id = res.json()["id"]

    # Clearing somebody else's objection is the thing this prevents — an admin
    # is not exempt.
    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}", headers=admin_auth)
    assert res.status_code == 400, res.text
    assert "only the person who raised" in res.json()["detail"].lower()

    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}", headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False
    # ...and not twice.
    assert (await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                                headers=eng_auth)).status_code == 400


async def test_open_concern_blocks_proceed_until_withdrawn(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "5")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "reject_proposal", "note": "Timing impossible"})
    concern_id = res.json()["id"]

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert "open concern" in detail
    assert "Timing" not in detail          # names the people, not the notes

    await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}", headers=eng_auth)
    await _lock_impact(session_factory, cid)
    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=eng_auth)
    assert res.status_code == 200, res.text


async def test_negative_decision_resolves_the_open_concerns(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "6")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                      json={"kind": "needs_info", "note": "Need the customer drawing"})

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide", headers=eng_auth,
                            json={"decision": "needs_info",
                                  "reason": "Customer drawing missing"})
    assert res.status_code == 200, res.text
    assert res.json()["decision_reason"] == "Customer drawing missing"

    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns", headers=eng_auth)).json()
    assert len(concerns) == 1
    assert concerns[0]["is_open"] is False
    assert concerns[0]["resolved_by_meeting_id"] == mid
    # The change stays in scoping — needs_info is not a rejection.
    got = await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)
    assert got.json()["status"] == "scoping"


async def test_meeting_reject_requires_a_reason_and_carries_it_to_the_change(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "7")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "reject"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    assert "reason is required" in res.json()["detail"].lower()

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide", headers=eng_auth,
                            json={"decision": "reject", "reason": "Not economical at this volume"})
    assert res.status_code == 200, res.text
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["status"] == "rejected"
    # One decision, one justification — the meeting's reason is the change's.
    assert got["rejection_reason"] == "Not economical at this volume"


async def test_needs_info_requires_saying_what_is_missing(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "8")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "needs_info"}, headers=eng_auth)
    assert res.status_code == 400, res.text
    assert "what information is missing" in res.json()["detail"].lower()


async def test_a_change_can_be_rejected_at_capture_without_being_scoped(
        client, eng_auth, seed, session_factory):
    """A request turned down outright never needed a full capture — forcing it
    through scoping on the way out would demand work on a change that is dying.
    Meetings live in scoping now, so the way out at capture is the direct
    transition with a rejection reason."""
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "dead on arrival",
        "change_type": "physical_part", "lead_id": seed["engineer_id"]}, headers=eng_auth)
    cid = res.json()["id"]
    # ... and a meeting cannot be recorded before scoping at all.
    early = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": []}, headers=eng_auth)
    assert early.status_code == 400

    res = await client.post(f"/api/v1/changes/{cid}/transition", headers=eng_auth,
                            json={"to_status": "rejected",
                                  "rejection_reason": "Customer withdrew"})
    assert res.status_code == 200, res.text
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["status"] == "rejected"
    assert got["rejection_reason"] == "Customer withdrew"


# --- assessment phase: a concern is one department's soft hold ---------------

async def _change_in_assessment(client, auth, seed, session_factory, suffix):
    """Scoping change driven to in_assessment (proceed meeting + impact lock).
    Returns (change_id, department_ids)."""
    cid = await _change_in_scoping(client, auth, seed, suffix)
    dept_ids = await _dept_ids(session_factory)
    await _lock_impact(session_factory, cid)
    mid = await _meeting(client, auth, cid, dept_ids)
    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            headers=auth, json={"decision": "proceed"})
    assert res.status_code == 200, res.text
    got = (await client.get(f"/api/v1/changes/{cid}", headers=auth)).json()
    assert got["status"] == "in_assessment", got["status"]
    return cid, dept_ids


async def _join_department(session_factory, user_id, department_id):
    from app.models.workflow import UserDepartment
    async with session_factory() as s:
        s.add(UserDepartment(user_id=user_id, department_id=department_id))
        await s.commit()


async def test_assessment_concern_requires_a_department(
        client, admin_auth, seed, session_factory):
    cid, _ = await _change_in_assessment(client, admin_auth, seed, session_factory, "A1")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth,
                            json={"kind": "needs_info", "note": "Need the CAD"})
    assert res.status_code == 400
    assert "department_id" in res.json()["detail"]


async def test_assessment_concern_only_for_your_own_department(
        client, admin_auth, eng_auth, seed, session_factory):
    cid, dept_ids = await _change_in_assessment(
        client, admin_auth, seed, session_factory, "A2")
    # the engineer is in no department -> refused
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "Need the CAD",
                                  "department_id": dept_ids[0]})
    assert res.status_code == 400
    assert "own department" in res.json()["detail"]

    await _join_department(session_factory, seed["engineer_id"], dept_ids[0])
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "Need the CAD",
                                  "department_id": dept_ids[0]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["department_id"] == dept_ids[0]
    assert body["is_open"] is True
    # surfaced as a badge on the change itself
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["blocked_department_ids"] == [dept_ids[0]]


async def test_department_concern_holds_only_its_own_assessment(
        client, admin_auth, seed, session_factory):
    cid, dept_ids = await _change_in_assessment(
        client, admin_auth, seed, session_factory, "A3")
    held = dept_ids[0]
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth,
                            json={"kind": "reject_proposal",
                                  "note": "Tolerance cannot be held",
                                  "department_id": held})
    assert res.status_code == 200, res.text
    concern_id = res.json()["id"]

    blocked = await client.post(f"/api/v1/changes/{cid}/assessments", headers=admin_auth,
                                json={"department_id": held, "verdict": "feasible"})
    assert blocked.status_code == 400
    detail = blocked.json()["detail"]
    assert "open concerns" in detail and "Tolerance cannot be held" in detail

    # the change itself is untouched — still in assessment
    got = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert got["status"] == "in_assessment"

    # note-less withdrawal is refused for a department concern
    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=admin_auth)
    assert res.status_code == 400
    assert "resolution note" in res.json()["detail"].lower()

    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            headers=admin_auth,
                            json={"resolution_note": "Supplier confirmed the tolerance"})
    assert res.status_code == 200, res.text
    assert res.json()["resolution_note"] == "Supplier confirmed the tolerance"
    assert res.json()["is_open"] is False

    ok = await client.post(f"/api/v1/changes/{cid}/assessments", headers=admin_auth,
                           json={"department_id": held, "verdict": "feasible"})
    assert ok.status_code == 200, ok.text

    log = await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin_auth)
    withdrawn = [e for e in log.json() if e["action"] == "concern_withdrawn"]
    assert len(withdrawn) == 1
    assert "Supplier confirmed the tolerance" in withdrawn[0]["action_description"]


async def test_scoping_concerns_keep_their_old_shape(
        client, eng_auth, seed):
    """No department, and withdrawal still needs no resolution note."""
    cid = await _change_in_scoping(client, eng_auth, seed, "A4")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "Missing drawing"})
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] is None
    concern_id = res.json()["id"]
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["blocked_department_ids"] == []

    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False
    assert res.json()["resolution_note"] is None




# --- scoping attribution: a department is a label there, not a hold ---------

async def _a_department(session_factory, name="Tool Engineer", active=True):
    from app.models.workflow import Department
    async with session_factory() as s:
        d = Department(name=name, flow_type="action", is_active=active)
        s.add(d)
        await s.commit()
        return d.id


async def test_scoping_concern_may_name_a_department_without_membership(
        client, eng_auth, seed, session_factory):
    """At scoping the department is attribution, not a submission gate — so no
    membership is required (unlike assessment)."""
    cid = await _change_in_scoping(client, eng_auth, seed, "S1")
    dept_id = await _a_department(session_factory)
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "Tooling unclear",
                                  "department_id": dept_id})
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] == dept_id
    # attribution does NOT soft-hold anything
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["blocked_department_ids"] == []


async def test_scoping_concern_without_a_department_is_the_whole_team(
        client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "S2")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "Change info missing"})
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] is None


async def test_scoping_concern_department_must_exist_and_be_active(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "S3")
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "x",
                                  "department_id": 999_999})
    assert res.status_code == 400
    assert "Unknown or inactive" in res.json()["detail"]

    dead = await _a_department(session_factory, name="Retired dept", active=False)
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
                            json={"kind": "needs_info", "note": "x",
                                  "department_id": dead})
    assert res.status_code == 400


async def test_withdrawing_an_attributed_scoping_concern_still_needs_a_note(
        client, eng_auth, seed, session_factory):
    """The rule keys off department_id, not the phase — naming a department
    means the withdrawal says how the point was addressed."""
    cid = await _change_in_scoping(client, eng_auth, seed, "S4")
    dept_id = await _a_department(session_factory)
    concern_id = (await client.post(
        f"/api/v1/changes/{cid}/concerns", headers=eng_auth,
        json={"kind": "needs_info", "note": "Tooling unclear",
              "department_id": dept_id})).json()["id"]

    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=eng_auth)
    assert res.status_code == 400
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            headers=eng_auth, json={"resolution_note": "Drawing arrived"})
    assert res.status_code == 200, res.text


# --- who may flag: anyone. Who may clear it: only its author ---------------

async def _plain_member(client, session_factory, seed, dept_name="Tool Engineer"):
    """A user who is neither the change lead, nor PM, nor admin — the case the
    scoping-meeting gate used to swallow."""
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    from tests.conftest import login
    async with session_factory() as s:
        dept = Department(name=dept_name, flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        u = User(organization_id=seed["org_id"], username="toolguy",
                 email="toolguy@test.io", full_name="Tool Guy",
                 hashed_password=get_password_hash("tool-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept.id))
        await s.commit()
        return {"auth": await login(client, "toolguy@test.io"),
                "user_id": u.id, "dept_id": dept.id}


async def test_any_member_may_raise_a_scoping_concern(
        client, eng_auth, seed, session_factory):
    """Not the lead, not PM, not admin — the flag must still land, both as a
    whole-team point and attributed to a department."""
    cid = await _change_in_scoping(client, eng_auth, seed, "W1")
    member = await _plain_member(client, session_factory, seed)

    res = await client.post(f"/api/v1/changes/{cid}/concerns",
                            headers=member["auth"],
                            json={"kind": "reject_proposal", "note": "Team point"})
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] is None
    assert res.json()["raised_by"] == member["user_id"]

    res = await client.post(f"/api/v1/changes/{cid}/concerns",
                            headers=member["auth"],
                            json={"kind": "needs_info", "note": "Tooling point",
                                  "department_id": member["dept_id"]})
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] == member["dept_id"]


async def test_admin_acting_as_development_may_raise_an_assessment_concern(
        client, admin_auth, seed, session_factory):
    cid, dept_ids = await _change_in_assessment(
        client, admin_auth, seed, session_factory, "W2")
    acting = {**admin_auth, "X-Acts-As-Department": str(dept_ids[0])}
    res = await client.post(f"/api/v1/changes/{cid}/concerns", headers=acting,
                            json={"kind": "needs_info", "note": "Need the CAD",
                                  "department_id": dept_ids[0]})
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] == dept_ids[0]


async def test_only_the_author_may_withdraw_even_without_meeting_rights(
        client, eng_auth, admin_auth, seed, session_factory):
    """Opening up raising must not open up clearing: the author rule is the
    whole authz on withdrawal."""
    cid = await _change_in_scoping(client, eng_auth, seed, "W3")
    member = await _plain_member(client, session_factory, seed)
    concern_id = (await client.post(
        f"/api/v1/changes/{cid}/concerns", headers=member["auth"],
        json={"kind": "reject_proposal", "note": "Mine"})).json()["id"]

    # the lead cannot clear someone else's objection...
    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=eng_auth)
    assert res.status_code == 400
    assert "who raised" in res.json()["detail"]
    # ...nor can an admin
    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=admin_auth)
    assert res.status_code == 400
    # its author can
    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=member["auth"])
    assert res.status_code == 200, res.text
