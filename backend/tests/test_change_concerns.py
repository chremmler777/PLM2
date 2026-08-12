"""Concerns: the flags a change carries alongside its decisions.

Two phases, two vocabularies. During SCOPING the team works the decision in
parallel: anyone may ask for missing information (needs_info) or vote to
reject the change (reject_proposal), those flags block 'proceed', and the
scoping meeting also writes the needs_info it decided on. During ASSESSMENT
the only hand-raised kind is a RISK — a register entry, not a hold. Legacy
department holds (reject_proposal rows with a department) still block their
department's submit until settled with a note.
"""
import pytest

from tests.conftest import insert_legacy_concern

pytestmark = pytest.mark.asyncio

RISK = {"kind": "risk", "risk_type": "dimensional_issue", "severity": 2}


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


async def _raise(client, auth, cid, note, kind="needs_info", **extra):
    body = {"kind": kind, "note": note}
    body.update(extra)
    return await client.post(f"/api/v1/changes/{cid}/concerns", json=body,
                             headers=auth)


async def test_scoping_takes_questions_and_cancel_votes_by_hand(
        client, eng_auth, seed):
    """The team works the decision in parallel: a member may ask for more
    information, or vote for cancellation, without waiting for the meeting."""
    cid = await _change_in_scoping(client, eng_auth, seed, "1")
    for kind in ("needs_info", "reject_proposal"):
        res = await _raise(client, eng_auth, cid, "Tool cannot hold it", kind=kind)
        assert res.status_code == 200, res.text
        assert res.json()["kind"] == kind
        assert res.json()["is_open"] is True


async def test_a_risk_cannot_be_raised_during_scoping(client, eng_auth, seed):
    """The risk register belongs to assessment — scoping talks concerns."""
    cid = await _change_in_scoping(client, eng_auth, seed, "1r")
    res = await _raise(client, eng_auth, cid, "Datum B will move", **RISK)
    assert res.status_code == 400, res.text
    assert "assessment" in res.json()["detail"]


async def test_a_concern_records_who_flagged_it_and_why(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "1b")
    res = await _raise(client, eng_auth, cid, "Datum B will move")
    assert res.status_code == 200, res.text
    c = res.json()
    assert c["kind"] == "needs_info"
    assert c["note"] == "Datum B will move"
    assert c["raised_by"] == seed["engineer_id"]
    assert c["raised_by_name"]           # the flag names its author
    assert c["is_open"] is True


async def test_concern_needs_a_note(client, eng_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "2")
    res = await _raise(client, eng_auth, cid, "   ")
    assert res.status_code == 400, res.text


async def test_only_the_author_may_withdraw_even_for_an_admin(
        client, eng_auth, admin_auth, seed):
    cid = await _change_in_scoping(client, eng_auth, seed, "4")
    concern_id = (await _raise(client, eng_auth, cid, "No capacity")).json()["id"]

    # Clearing somebody else's flag is the thing this prevents — an admin
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
    concern_id = (await _raise(client, eng_auth, cid, "Timing impossible",
                               kind="reject_proposal")).json()["id"]

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


async def test_an_open_risk_does_not_block_the_decision(
        client, eng_auth, seed, session_factory):
    """A change proceeds WITH its risks — gating the decision on an empty
    register would only teach people to withdraw risks they still believe in.
    Risks are assessment-raised now, so the row is seeded the way one would
    exist on a change that came back around."""
    cid = await _change_in_scoping(client, eng_auth, seed, "5b")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    await insert_legacy_concern(
        session_factory, cid, kind="risk", note="Warpage on the long rib",
        raised_by=seed["engineer_id"])
    await _lock_impact(session_factory, cid)

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                            json={"decision": "proceed"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    # ...and it is still standing afterwards: proceeding did not answer it.
    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns", headers=eng_auth)).json()
    assert [c["is_open"] for c in concerns] == [True]


async def test_negative_decision_resolves_the_open_concerns(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "6")
    mid = await _meeting(client, eng_auth, cid, await _dept_ids(session_factory))
    assert (await _raise(client, eng_auth, cid,
                         "Need the customer drawing")).status_code == 200
    # A risk is not a question, so the decision must leave it alone.
    await insert_legacy_concern(
        session_factory, cid, kind="risk", note="Sink marks",
        raised_by=seed["engineer_id"])

    res = await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide", headers=eng_auth,
                            json={"decision": "needs_info",
                                  "reason": "Customer drawing missing"})
    assert res.status_code == 200, res.text
    assert res.json()["decision_reason"] == "Customer drawing missing"

    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns", headers=eng_auth)).json()
    # The pre-existing flag is answered by the decision...
    answered = [c for c in concerns if c["note"] == "Need the customer drawing"]
    assert len(answered) == 1
    assert answered[0]["is_open"] is False
    assert answered[0]["resolved_by_meeting_id"] == mid
    # ...and the decision itself becomes the open Team question that replaces
    # it, so the change still visibly owes an answer.
    questions = [c for c in concerns if c["is_open"] and c["kind"] == "needs_info"]
    assert len(questions) == 1
    assert questions[0]["note"] == "Customer drawing missing"
    assert questions[0]["department_id"] is None
    # The risk is untouched — nothing about it was decided.
    risk = next(c for c in concerns if c["kind"] == "risk")
    assert risk["is_open"] is True
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


# --- assessment phase --------------------------------------------------------

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


async def test_assessment_takes_only_risks_by_hand(
        client, admin_auth, seed, session_factory):
    """The scoping vocabulary stops at the phase door: once the change is in
    assessment, a hand raise is a register entry, not a question or a vote."""
    cid, dept_ids = await _change_in_assessment(
        client, admin_auth, seed, session_factory, "A0")
    for kind in ("needs_info", "reject_proposal"):
        res = await _raise(client, admin_auth, cid, "Too late for this", kind=kind,
                           department_id=dept_ids[0])
        assert res.status_code == 400, res.text
        assert "belong to scoping" in res.json()["detail"]


async def test_a_risk_in_assessment_must_name_its_department(
        client, admin_auth, seed, session_factory):
    cid, _ = await _change_in_assessment(client, admin_auth, seed, session_factory, "A1")
    res = await _raise(client, admin_auth, cid, "Need the CAD", **RISK)
    assert res.status_code == 400
    assert "department_id" in res.json()["detail"]


async def test_a_risk_in_assessment_is_only_for_your_own_department(
        client, admin_auth, eng_auth, seed, session_factory):
    cid, dept_ids = await _change_in_assessment(
        client, admin_auth, seed, session_factory, "A2")
    # the engineer is in no department -> refused
    res = await _raise(client, eng_auth, cid, "Wall too thin",
                       department_id=dept_ids[0], **RISK)
    assert res.status_code == 400
    assert "own department" in res.json()["detail"]

    await _join_department(session_factory, seed["engineer_id"], dept_ids[0])
    res = await _raise(client, eng_auth, cid, "Wall too thin",
                       department_id=dept_ids[0], **RISK)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["department_id"] == dept_ids[0]
    assert body["is_open"] is True
    # ...and it is NOT a hold, so no badge on the change
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["blocked_department_ids"] == []


async def test_a_legacy_hold_still_blocks_and_is_settled_with_a_note(
        client, admin_auth, seed, session_factory):
    """The one surviving reject_proposal test: nothing produces these any more,
    but the rows exist and the department that carries one still cannot sign
    off until it is lifted, on the record."""
    cid, dept_ids = await _change_in_assessment(
        client, admin_auth, seed, session_factory, "A3")
    held = dept_ids[0]
    concern_id = await insert_legacy_concern(
        session_factory, cid, kind="reject_proposal",
        note="Tolerance cannot be held", raised_by=seed["admin_id"],
        department_id=held)

    # it is a hold, and it says so on the change
    got = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    assert got["blocked_department_ids"] == [held]

    blocked = await client.post(f"/api/v1/changes/{cid}/assessments", headers=admin_auth,
                                json={"department_id": held, "verdict": "feasible"})
    assert blocked.status_code == 400
    detail = blocked.json()["detail"]
    assert "open concerns" in detail and "Tolerance cannot be held" in detail

    # the change itself is untouched — still in assessment
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


# --- scoping attribution: a department is a label there, not a hold ---------

async def _a_department(session_factory, name="Tool Engineer", active=True):
    from app.models.workflow import Department
    async with session_factory() as s:
        d = Department(name=name, flow_type="action", is_active=active)
        s.add(d)
        await s.commit()
        return d.id


async def test_a_scoping_concern_may_name_a_department_without_membership(
        client, eng_auth, seed, session_factory):
    """At scoping the department is attribution, not a submission gate — so no
    membership is required (unlike assessment)."""
    cid = await _change_in_scoping(client, eng_auth, seed, "S1")
    dept_id = await _a_department(session_factory)
    res = await _raise(client, eng_auth, cid, "Tooling unclear", department_id=dept_id)
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] == dept_id
    # attribution does NOT soft-hold anything
    got = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    assert got["blocked_department_ids"] == []


async def test_a_named_department_must_exist_and_be_active(
        client, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, eng_auth, seed, "S3")
    res = await _raise(client, eng_auth, cid, "x", department_id=999_999)
    assert res.status_code == 400
    assert "Unknown or inactive" in res.json()["detail"]

    dead = await _a_department(session_factory, name="Retired dept", active=False)
    res = await _raise(client, eng_auth, cid, "x", department_id=dead)
    assert res.status_code == 400


async def test_withdrawing_an_attributed_concern_still_needs_a_note(
        client, eng_auth, seed, session_factory):
    """The rule keys off department_id, not the phase — naming a department
    means the withdrawal says how the point was addressed."""
    cid = await _change_in_scoping(client, eng_auth, seed, "S4")
    dept_id = await _a_department(session_factory)
    concern_id = (await _raise(client, eng_auth, cid, "Tooling unclear",
                               department_id=dept_id)).json()["id"]

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


async def test_any_member_may_flag_a_concern(
        client, eng_auth, seed, session_factory):
    """Not the lead, not PM, not admin — the flag must still land, both as a
    whole-team point and attributed to a department."""
    cid = await _change_in_scoping(client, eng_auth, seed, "W1")
    member = await _plain_member(client, session_factory, seed)

    res = await _raise(client, member["auth"], cid, "Team point")
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] is None
    assert res.json()["raised_by"] == member["user_id"]

    res = await _raise(client, member["auth"], cid, "Tooling point",
                       department_id=member["dept_id"])
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] == member["dept_id"]

    # The list names the asker's role next to their name: who is asking is
    # read with the hat they wear, not as a bare username.
    listed = (await client.get(f"/api/v1/changes/{cid}/concerns",
                               headers=eng_auth)).json()
    mine = next(c for c in listed if c["note"] == "Team point")
    assert mine["raised_by_name"] == "Tool Guy"
    assert mine["raised_by_departments"] == ["Tool Engineer"]


async def test_admin_acting_as_a_department_may_flag_for_it(
        client, admin_auth, seed, session_factory):
    cid, dept_ids = await _change_in_assessment(
        client, admin_auth, seed, session_factory, "W2")
    acting = {**admin_auth, "X-Acts-As-Department": str(dept_ids[0])}
    res = await _raise(client, acting, cid, "Gate freeze marginal",
                       department_id=dept_ids[0], **RISK)
    assert res.status_code == 200, res.text
    assert res.json()["department_id"] == dept_ids[0]


async def test_acting_as_a_department_sets_authorship_aside(
        client, admin_auth, seed, session_factory):
    """The acts-as switch means being exactly that department (spec D2): an
    admin driving another department's view — Sales, typically — must not
    keep their personal requester right on a question they asked as
    themselves. Dropping the switch brings the right back."""
    cid = await _change_in_scoping(client, admin_auth, seed, "AA1")
    dept_id = await _a_department(session_factory)
    concern_id = (await _raise(client, admin_auth, cid,
                               "Need the drawing")).json()["id"]

    acting = {**admin_auth, "X-Acts-As-Department": str(dept_id)}
    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=acting)
    assert res.status_code == 400
    assert "Project Management" in res.json()["detail"]

    res = await client.delete(f"/api/v1/changes/{cid}/concerns/{concern_id}",
                              headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_only_the_author_may_withdraw_even_without_meeting_rights(
        client, eng_auth, admin_auth, seed, session_factory):
    """Opening up raising must not open up clearing: the author rule is the
    whole authz on withdrawal."""
    cid = await _change_in_scoping(client, eng_auth, seed, "W3")
    member = await _plain_member(client, session_factory, seed)
    concern_id = (await _raise(client, member["auth"], cid, "Mine")).json()["id"]

    # the lead cannot clear someone else's flag...
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
