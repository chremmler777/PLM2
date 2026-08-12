"""Closing the needs-info loop: a decision raises a Team flag, Sales gets the
task, and the question/answer documents are linked to each other.

A needs_info question now has exactly one producer — the scoping meeting that
decided it — and that is how the Team flags below are created. Questions
attributed to a DEPARTMENT have no producer left at all, but plenty of them
exist on live changes, and everything downstream (the Sales errand, the
close_question errand, the proposal-with-document rule) still has to handle
them. Those tests seed the row directly; see conftest.insert_legacy_concern.
"""
import pytest

from tests.conftest import insert_legacy_concern, login, satisfy_capture_gate

pytestmark = pytest.mark.asyncio


async def _change_in_scoping(client, auth, seed, suffix):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": f"ni {suffix}", "reason": "r",
        "change_type": "physical_part", "lead_id": seed["admin_id"]}, headers=auth)
    assert res.status_code == 200, res.text
    cid = res.json()["id"]
    await satisfy_capture_gate(client, auth, cid)
    res = await client.post(f"/api/v1/changes/{cid}/transition",
                            json={"to_status": "scoping"}, headers=auth)
    assert res.status_code == 200, res.text
    return cid


async def _upload(client, auth, cid, name, **form):
    return await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": (name, b"x", "text/plain")}, data=form, headers=auth)


# --- part 1: classification -------------------------------------------------

async def test_attachment_defaults_to_general(client, admin_auth, seed):
    cid = await _change_in_scoping(client, admin_auth, seed, "1")
    res = await _upload(client, admin_auth, cid, "any.txt")
    assert res.status_code in (200, 201), res.text
    assert res.json()["kind"] == "general"
    assert res.json()["responds_to_id"] is None


async def test_response_links_back_to_its_request(client, admin_auth, seed):
    cid = await _change_in_scoping(client, admin_auth, seed, "2")
    q = (await _upload(client, admin_auth, cid, "question.pdf",
                       kind="info_request")).json()
    assert q["kind"] == "info_request"
    a = await _upload(client, admin_auth, cid, "answer.pdf",
                      kind="info_response", responds_to_id=q["id"])
    assert a.status_code in (200, 201), a.text
    assert a.json()["responds_to_id"] == q["id"]

    detail = (await client.get(f"/api/v1/changes/{cid}", headers=admin_auth)).json()
    by_name = {x["filename"]: x for x in detail["attachments"]}
    assert by_name["answer.pdf"]["kind"] == "info_response"
    assert by_name["answer.pdf"]["responds_to_id"] == q["id"]


async def test_link_validations(client, admin_auth, seed):
    cid = await _change_in_scoping(client, admin_auth, seed, "3")
    other = await _change_in_scoping(client, admin_auth, seed, "4")
    q = (await _upload(client, admin_auth, cid, "q.pdf", kind="info_request")).json()
    general = (await _upload(client, admin_auth, cid, "g.pdf")).json()

    # unknown kind
    res = await _upload(client, admin_auth, cid, "x.pdf", kind="nonsense")
    assert res.status_code == 400 and "kind" in res.json()["detail"]
    # only an info_response may link
    res = await _upload(client, admin_auth, cid, "x.pdf", kind="general",
                        responds_to_id=q["id"])
    assert res.status_code == 400
    # the target must be an info_request
    res = await _upload(client, admin_auth, cid, "x.pdf", kind="info_response",
                        responds_to_id=general["id"])
    assert res.status_code == 400
    # ...on THIS change
    res = await _upload(client, admin_auth, other, "x.pdf", kind="info_response",
                        responds_to_id=q["id"])
    assert res.status_code == 400


# --- part 2: the decision raises the Team flag itself -----------------------

async def _departments(session_factory):
    from sqlalchemy import select
    from app.models.workflow import Department
    from app.services.wf_seed_service import seed_assessment_standard
    async with session_factory() as s:
        await seed_assessment_standard(s)
        await s.commit()
    async with session_factory() as s:
        return [d for (d,) in await s.execute(select(Department.id).limit(1))]


async def _meeting(client, auth, cid, dept_ids):
    res = await client.post(f"/api/v1/changes/{cid}/meetings", json={
        "channel": "meeting", "participants": [{"name": "Eva"}],
        "selected_department_ids": dept_ids}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["id"]


async def _decide(client, auth, cid, mid, decision, reason=None):
    body = {"decision": decision}
    if reason:
        body["reason"] = reason
    return await client.post(f"/api/v1/changes/{cid}/meetings/{mid}/decide",
                             json=body, headers=auth)


async def test_needs_info_decision_raises_one_team_flag(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "5")
    depts = await _departments(session_factory)
    mid = await _meeting(client, admin_auth, cid, depts)
    res = await _decide(client, admin_auth, cid, mid, "needs_info",
                        "Customer drawing missing")
    assert res.status_code == 200, res.text

    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    open_ = [c for c in concerns if c["is_open"]]
    assert len(open_) == 1
    assert open_[0]["kind"] == "needs_info"
    assert open_[0]["department_id"] is None          # a Team flag
    assert open_[0]["note"] == "Customer drawing missing"
    assert open_[0]["raised_by"] == seed["admin_id"]  # the decider owns it

    # ...and it behaves like any other open concern: proceed is blocked
    mid2 = await _meeting(client, admin_auth, cid, depts)
    blocked = await _decide(client, admin_auth, cid, mid2, "proceed")
    assert blocked.status_code == 400
    assert "open concern" in blocked.json()["detail"]

    # a second needs_info from the same decider is the same question, not a new one
    res = await _decide(client, admin_auth, cid, mid2, "needs_info", "Still missing")
    assert res.status_code == 200, res.text
    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    assert len([c for c in concerns if c["is_open"]]) == 1


# --- part 3: Sales owns going and getting it -------------------------------

async def _sales_member(client, session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    from sqlalchemy import select
    async with session_factory() as s:
        dept = (await s.execute(select(Department).where(
            Department.name == "Sales"))).scalar_one_or_none()
        if dept is None:
            dept = Department(name="Sales", flow_type="action", is_active=True)
            s.add(dept)
            await s.flush()
        u = User(organization_id=seed["org_id"], username="salesperson",
                 email="salesperson@test.io", full_name="Sales Person",
                 hashed_password=get_password_hash("sales-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept.id))
        await s.commit()
        return await login(client, "salesperson@test.io")


async def test_obtain_info_row_appears_for_sales_and_clears_on_a_decision(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "6")
    depts = await _departments(session_factory)
    sales = await _sales_member(client, session_factory, seed)

    async def rows():
        res = await client.get("/api/v1/changes/my-tasks", headers=sales)
        assert res.status_code == 200, res.text
        return [t for t in res.json()
                if t["kind"] == "obtain_info" and t["change_id"] == cid]

    assert await rows() == []

    mid = await _meeting(client, admin_auth, cid, depts)
    await _decide(client, admin_auth, cid, mid, "needs_info", "Send us the CAD")
    got = await rows()
    assert len(got) == 1
    assert got[0]["reason"] == "Send us the CAD"
    assert got[0]["project_number"] == "proj"

    # a follow-up decision closes the loop; the row goes away
    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    open_id = next(c["id"] for c in concerns if c["is_open"])
    await client.delete(f"/api/v1/changes/{cid}/concerns/{open_id}",
                        headers=admin_auth)
    mid2 = await _meeting(client, admin_auth, cid, depts)
    res = await _decide(client, admin_auth, cid, mid2, "reject", "Not economical")
    assert res.status_code == 200, res.text
    assert await rows() == []


# --- Sales answers and marks solved; the meeting is the review --------------

async def _open_team_flag(client, admin_auth, seed, session_factory, suffix):
    """A change in scoping carrying an open Team needs_info flag."""
    cid = await _change_in_scoping(client, admin_auth, seed, suffix)
    depts = await _departments(session_factory)
    mid = await _meeting(client, admin_auth, cid, depts)
    res = await _decide(client, admin_auth, cid, mid, "needs_info",
                        "Send us the customer drawing")
    assert res.status_code == 200, res.text
    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    return cid, next(c["id"] for c in concerns if c["is_open"]), depts


async def _pm_member(client, session_factory, seed):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    from sqlalchemy import select
    async with session_factory() as s:
        dept = (await s.execute(select(Department).where(
            Department.name == "Project Manager"))).scalar_one_or_none()
        if dept is None:
            dept = Department(name="Project Manager", flow_type="action",
                              is_active=True)
            s.add(dept)
            await s.flush()
        u = User(organization_id=seed["org_id"], username="pmperson",
                 email="pmperson@test.io", full_name="PM Person",
                 hashed_password=get_password_hash("pm-secret-12"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept.id))
        await s.commit()
        return await login(client, "pmperson@test.io")


async def test_sales_answers_but_does_not_settle(
        client, admin_auth, seed, session_factory):
    """Answering is a comment on the question, not a verdict on it: the
    concern stays open for the side that asked."""
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "7")
    sales = await _sales_member(client, session_factory, seed)

    # substance is required
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "   "}, headers=sales)
    assert res.status_code == 400
    assert "needs content" in res.json()["detail"]

    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "Customer sent rev C"}, headers=sales)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer_note"] == "Customer sent rev C"
    assert body["answered_at"] is not None
    assert body["answered_by"] is not None
    assert body["is_open"] is True          # answering does not settle it

    # ...and the list names who answered, not a bare '#id'
    listed = (await client.get(f"/api/v1/changes/{cid}/concerns",
                               headers=admin_auth)).json()
    row = next(x for x in listed if x["id"] == concern_id)
    assert row["answered_by_name"] == "Sales Person"

    # ...and Sales cannot settle it either
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            json={"resolution_note": "closing my own answer"},
                            headers=sales)
    assert res.status_code == 400
    assert "Project Management" in res.json()["detail"]


async def test_attribution_to_sales_gives_sales_no_settle_right(
        client, admin_auth, seed, session_factory):
    """The hole this pins shut: a question ATTRIBUTED to the Sales department
    ("Sales must ask the customer") must still not be Sales' to settle. In
    scoping, attribution is a label anyone may pick — settling stays with the
    person who asked, or Project Management."""
    from sqlalchemy import select
    from app.models.workflow import Department
    cid = await _change_in_scoping(client, admin_auth, seed, "7b")
    sales = await _sales_member(client, session_factory, seed)
    async with session_factory() as s:
        sales_dept_id = (await s.execute(select(Department.id).where(
            Department.name == "Sales"))).scalar_one()

    concern_id = (await client.post(
        f"/api/v1/changes/{cid}/concerns", headers=admin_auth,
        json={"kind": "needs_info", "note": "Ask the customer for rev D",
              "department_id": sales_dept_id})).json()["id"]

    # Sales answers — that is their part, and it changes nothing about who
    # decides the answer was good enough.
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "Customer confirmed rev D"}, headers=sales)
    assert res.status_code == 200, res.text

    # the close-question errand goes to the asker, not to Sales
    assert await _close_rows(client, sales, cid) == []
    author_rows = await _close_rows(client, admin_auth, cid)
    assert len(author_rows) == 1 and author_rows[0]["concern_id"] == concern_id

    # Sales cannot settle it, resolution note or not
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            json={"resolution_note": "closing it myself"},
                            headers=sales)
    assert res.status_code == 400
    assert "Project Management" in res.json()["detail"]

    # the person who asked settles it, on the record
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            json={"resolution_note": "Rev D confirmed is enough"},
                            headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False


async def test_re_answering_overwrites_and_keeps_every_round_in_the_chain(
        client, admin_auth, seed, session_factory):
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "8")
    sales = await _sales_member(client, session_factory, seed)
    for note in ("Asked the customer", "Customer sent rev C"):
        res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                                json={"note": note}, headers=sales)
        assert res.status_code == 200, res.text
    assert res.json()["answer_note"] == "Customer sent rev C"

    log = (await client.get(f"/api/v1/changes/{cid}/changelog", headers=admin_auth)).json()
    answered = [e for e in log if e["action"] == "concern_answered"]
    assert len(answered) == 2
    assert "Asked the customer" in answered[0]["action_description"]
    assert "Customer sent rev C" in answered[1]["action_description"]


async def test_a_document_in_the_container_is_content_enough(
        client, admin_auth, seed, session_factory):
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "9")
    sales = await _sales_member(client, session_factory, seed)
    up = await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("drawing.pdf", b"x", "application/pdf")},
        data={"kind": "info_response", "concern_id": str(concern_id)},
        headers=sales)
    assert up.status_code in (200, 201), up.text
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={}, headers=sales)
    assert res.status_code == 200, res.text


async def test_only_sales_may_answer(client, admin_auth, eng_auth, seed,
                                     session_factory):
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "10")
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "not mine to answer"}, headers=eng_auth)
    assert res.status_code == 400
    assert "Sales" in res.json()["detail"]


async def test_the_author_or_pm_settles_a_team_flag(
        client, admin_auth, seed, session_factory):
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "11")
    pm = await _pm_member(client, session_factory, seed)

    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            json={"resolution_note": "Rev C is what we needed"},
                            headers=pm)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False

    # the author (the decider) can settle their own too
    cid2, concern2, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "12")
    res = await client.post(f"/api/v1/changes/{cid2}/concerns/{concern2}/withdraw",
                            json={}, headers=admin_auth)
    assert res.status_code == 200, res.text


async def test_any_member_of_the_raising_department_may_settle_its_flag(
        client, admin_auth, eng_auth, seed, session_factory):
    """A department flag is the department's, not one person's — colleagues
    cover for each other."""
    from app.models.workflow import Department, UserDepartment
    cid, _, depts = await _open_team_flag(
        client, admin_auth, seed, session_factory, "13")
    dept_id = depts[0]
    # admin raises for the department (acting as it), a colleague settles it
    async with session_factory() as s:
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=dept_id))
        await s.commit()
    from app.models.change import ChangeRequest
    async with session_factory() as s:
        c = await s.get(ChangeRequest, cid)
        c.status = "in_assessment"
        await s.commit()

    dept_concern = await insert_legacy_concern(
        session_factory, cid, kind="reject_proposal", note="Tolerance",
        raised_by=seed["admin_id"], department_id=dept_id)

    res = await client.post(f"/api/v1/changes/{cid}/concerns/{dept_concern}/withdraw",
                            json={"resolution_note": "Supplier confirmed"},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False


async def test_obtain_info_task_clears_on_the_answer_not_the_settlement(
        client, admin_auth, seed, session_factory):
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "14")
    sales = await _sales_member(client, session_factory, seed)

    async def rows():
        res = await client.get("/api/v1/changes/my-tasks", headers=sales)
        return [t for t in res.json()
                if t["kind"] == "obtain_info" and t["change_id"] == cid]

    assert len(await rows()) == 1
    await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                      json={"note": "Answered by phone"}, headers=sales)
    assert await rows() == []          # Sales is done; the flag is still open

    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    assert [c for c in concerns if c["is_open"]]


# --- concern containers -----------------------------------------------------

async def test_anyone_may_file_into_an_open_concern(
        client, admin_auth, eng_auth, seed, session_factory):
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "12")
    # a team member explains the question with a document
    up = await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("what-we-mean.pdf", b"x", "application/pdf")},
        data={"kind": "info_request", "concern_id": str(concern_id)},
        headers=eng_auth)
    assert up.status_code in (200, 201), up.text
    assert up.json()["concern_id"] == concern_id

    detail = (await client.get(f"/api/v1/changes/{cid}", headers=eng_auth)).json()
    filed = [a for a in detail["attachments"] if a["concern_id"] == concern_id]
    assert len(filed) == 1
    assert filed[0]["kind"] == "info_request"


async def test_container_validations(
        client, admin_auth, seed, session_factory):
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "13")
    other_cid, other_concern, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "14")
    sales = await _sales_member(client, session_factory, seed)

    async def up(target_cid, concern):
        return await client.post(
            f"/api/v1/changes/{target_cid}/attachments",
            files={"file": ("x.pdf", b"x", "application/pdf")},
            data={"concern_id": str(concern)}, headers=admin_auth)

    assert (await up(cid, 999_999)).status_code == 400
    # a concern on ANOTHER change is not this change's container
    assert (await up(cid, other_concern)).status_code == 400

    # settled containers are closed for filing (the author settles it)
    settled = await client.post(
        f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
        json={"resolution_note": "done"}, headers=admin_auth)
    assert settled.status_code == 200, settled.text
    res = await up(cid, concern_id)
    assert res.status_code == 400
    assert "already settled" in res.json()["detail"]


async def test_substance_is_counted_per_container(
        client, admin_auth, seed, session_factory):
    """A document filed into ANOTHER question does not answer this one."""
    cid, first, depts = await _open_team_flag(
        client, admin_auth, seed, session_factory, "15")
    sales = await _sales_member(client, session_factory, seed)
    await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("first-answer.pdf", b"x", "application/pdf")},
        data={"kind": "info_response", "concern_id": str(first)}, headers=sales)
    # answered with the document, then settled by its author
    assert (await client.post(
        f"/api/v1/changes/{cid}/concerns/{first}/answer",
        json={}, headers=sales)).status_code == 200
    await client.post(f"/api/v1/changes/{cid}/concerns/{first}/withdraw",
                      json={}, headers=admin_auth)

    mid = await _meeting(client, admin_auth, cid, depts)
    await _decide(client, admin_auth, cid, mid, "needs_info", "And the tolerances?")
    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    second = next(c["id"] for c in concerns if c["is_open"])

    # the earlier document belongs to the earlier question
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{second}/answer",
                            json={}, headers=sales)
    assert res.status_code == 400
    assert "needs content" in res.json()["detail"]


async def test_the_auto_flag_names_the_meeting_that_raised_it(
        client, admin_auth, seed, session_factory):
    """The container traces back to where the question was decided."""
    cid = await _change_in_scoping(client, admin_auth, seed, "16")
    depts = await _departments(session_factory)
    mid = await _meeting(client, admin_auth, cid, depts)
    await _decide(client, admin_auth, cid, mid, "needs_info", "Which revision?")

    concerns = (await client.get(f"/api/v1/changes/{cid}/concerns",
                                 headers=admin_auth)).json()
    auto = next(c for c in concerns if c["kind"] == "needs_info" and c["is_open"])
    assert auto["raised_by_meeting_id"] == mid

    # a hand-raised flag stands on its own, with no meeting behind it (the
    # decider already owns the open needs_info above, so this one is a vote)
    manual = await client.post(f"/api/v1/changes/{cid}/concerns", headers=admin_auth,
                               json={"kind": "reject_proposal", "note": "mine"})
    assert manual.status_code == 200, manual.text
    assert manual.json()["raised_by_meeting_id"] is None


# --- Sales answers ANY open question, whoever asked -------------------------

async def test_department_raised_question_reaches_sales(
        client, admin_auth, seed, session_factory):
    """The live bug: an APQP question produced no Sales task because only Team
    flags counted. Attribution says who wants to know, not who has to ask."""
    from app.models.workflow import Department, UserDepartment
    cid = await _change_in_scoping(client, admin_auth, seed, "17")
    sales = await _sales_member(client, session_factory, seed)
    async with session_factory() as s:
        apqp = Department(name="APQP", flow_type="action", is_active=True)
        s.add(apqp)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=apqp.id))
        await s.commit()
        apqp_id = apqp.id

    async def rows():
        res = await client.get("/api/v1/changes/my-tasks", headers=sales)
        assert res.status_code == 200, res.text
        return [t for t in res.json()
                if t["kind"] == "obtain_info" and t["change_id"] == cid]

    assert await rows() == []

    # APQP asks — attribution says who wants to know, not who has to ask
    concern_id = await insert_legacy_concern(
        session_factory, cid, kind="needs_info", note="Which tolerance class?",
        raised_by=seed["engineer_id"], department_id=apqp_id)

    got = await rows()
    assert len(got) == 1
    assert got[0]["reason"] == "Which tolerance class?"
    assert got[0]["question_count"] == 1
    assert got[0]["concern_id"] == concern_id
    assert got[0]["department_id"] == apqp_id

    await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                      json={"note": "Class 2"}, headers=sales)
    assert await rows() == []


async def test_one_row_per_change_counts_the_questions(
        client, admin_auth, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "18")
    sales = await _sales_member(client, session_factory, seed)
    for who, note in ((seed["admin_id"], "First question"),
                      (seed["engineer_id"], "Second question")):
        await insert_legacy_concern(session_factory, cid, kind="needs_info",
                                    note=note, raised_by=who)

    res = await client.get("/api/v1/changes/my-tasks", headers=sales)
    rows = [t for t in res.json()
            if t["kind"] == "obtain_info" and t["change_id"] == cid]
    assert len(rows) == 1                       # one errand, not two
    assert rows[0]["question_count"] == 2
    assert rows[0]["reason"] == "Second question"   # the newest one


async def test_objections_are_not_questions(client, admin_auth, seed,
                                            session_factory):
    """reject_proposal is an objection — nobody can answer it for its author."""
    cid = await _change_in_scoping(client, admin_auth, seed, "19")
    sales = await _sales_member(client, session_factory, seed)
    await insert_legacy_concern(session_factory, cid, kind="reject_proposal",
                                note="Too expensive", raised_by=seed["admin_id"])
    res = await client.get("/api/v1/changes/my-tasks", headers=sales)
    assert [t for t in res.json()
            if t["kind"] == "obtain_info" and t["change_id"] == cid] == []


async def test_a_question_in_assessment_still_reaches_sales(
        client, admin_auth, seed, session_factory):
    """Questions do not stop at scoping — the row follows the change."""
    from app.models.change import ChangeRequest
    from app.models.workflow import Department, UserDepartment
    cid = await _change_in_scoping(client, admin_auth, seed, "20")
    sales = await _sales_member(client, session_factory, seed)
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        dept_id = dept.id
        c = await s.get(ChangeRequest, cid)
        c.status = "in_assessment"
        await s.commit()

    await insert_legacy_concern(session_factory, cid, kind="needs_info",
                                note="Steel grade?", raised_by=seed["admin_id"],
                                department_id=dept_id)

    res = await client.get("/api/v1/changes/my-tasks", headers=sales)
    rows = [t for t in res.json()
            if t["kind"] == "obtain_info" and t["change_id"] == cid]
    assert len(rows) == 1 and rows[0]["reason"] == "Steel grade?"


# --- the other half: somebody has to review the answer ----------------------

async def _dept_member(client, session_factory, seed, name, email):
    from app.auth.security import get_password_hash
    from app.models.entities import User
    from app.models.workflow import Department, UserDepartment
    from sqlalchemy import select
    async with session_factory() as s:
        dept = (await s.execute(select(Department).where(
            Department.name == name))).scalar_one_or_none()
        if dept is None:
            dept = Department(name=name, flow_type="action", is_active=True)
            s.add(dept)
            await s.flush()
        u = User(organization_id=seed["org_id"], username=email.split("@")[0],
                 email=email, full_name=name,
                 hashed_password=get_password_hash("member-secret-1"),
                 role="engineer", is_active=True, mfa_enabled=False)
        s.add(u)
        await s.flush()
        s.add(UserDepartment(user_id=u.id, department_id=dept.id))
        await s.commit()
        return {"auth": await login(client, email), "dept_id": dept.id,
                "user_id": u.id}


async def _close_rows(client, auth, cid):
    res = await client.get("/api/v1/changes/my-tasks", headers=auth)
    assert res.status_code == 200, res.text
    return [t for t in res.json()
            if t["kind"] == "close_question" and t["change_id"] == cid]


async def test_answered_department_question_reaches_that_department_and_pm(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "21")
    sales = await _sales_member(client, session_factory, seed)
    apqp = await _dept_member(client, session_factory, seed, "APQP", "apqp@test.io")
    pm = await _dept_member(client, session_factory, seed,
                            "Project Manager", "pm2@test.io")

    concern_id = await insert_legacy_concern(
        session_factory, cid, kind="needs_info", note="Which tolerance?",
        raised_by=apqp["user_id"], department_id=apqp["dept_id"])

    # unanswered: nobody is asked to close it yet
    assert await _close_rows(client, apqp["auth"], cid) == []
    assert await _close_rows(client, pm["auth"], cid) == []

    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "Class 2 per the drawing"}, headers=sales)
    assert res.status_code == 200, res.text

    for who in (apqp, pm):
        rows = await _close_rows(client, who["auth"], cid)
        assert len(rows) == 1, who["dept_id"]
        assert rows[0]["reason"] == "Class 2 per the drawing"
        assert rows[0]["question_note"] == "Which tolerance?"
        assert rows[0]["concern_id"] == concern_id
        assert rows[0]["question_count"] == 1
        assert rows[0]["department_id"] == apqp["dept_id"]

    # Sales, having answered, is not the one who decides it is settled
    assert await _close_rows(client, sales, cid) == []

    # settling it clears the row
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            json={"resolution_note": "Good enough"},
                            headers=apqp["auth"])
    assert res.status_code == 200, res.text
    assert await _close_rows(client, apqp["auth"], cid) == []
    assert await _close_rows(client, pm["auth"], cid) == []


async def test_answered_team_flag_goes_to_project_management(
        client, admin_auth, eng_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "22")
    sales = await _sales_member(client, session_factory, seed)
    pm = await _dept_member(client, session_factory, seed,
                            "Project Manager", "pm3@test.io")

    concern_id = await insert_legacy_concern(
        session_factory, cid, kind="needs_info", note="Customer drawing?",
        raised_by=seed["admin_id"])
    await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                      json={"note": "Rev C received"}, headers=sales)

    rows = await _close_rows(client, pm["auth"], cid)
    assert len(rows) == 1
    assert rows[0]["department_id"] is None
    assert rows[0]["reason"] == "Rev C received"

    # a bystander in no relevant department is not asked
    assert await _close_rows(client, eng_auth, cid) == []

    await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                      json={"resolution_note": "That answers it"}, headers=pm["auth"])
    assert await _close_rows(client, pm["auth"], cid) == []


async def test_pm_sees_both_kinds_and_counts_them_once_per_change(
        client, admin_auth, seed, session_factory):
    cid = await _change_in_scoping(client, admin_auth, seed, "23")
    sales = await _sales_member(client, session_factory, seed)
    pm = await _dept_member(client, session_factory, seed,
                            "Project Manager", "pm4@test.io")
    tool = await _dept_member(client, session_factory, seed,
                              "Tool Engineer", "tool2@test.io")

    team = await insert_legacy_concern(
        session_factory, cid, kind="needs_info", note="Team question",
        raised_by=seed["admin_id"])
    dept = await insert_legacy_concern(
        session_factory, cid, kind="needs_info", note="Tool question",
        raised_by=tool["user_id"], department_id=tool["dept_id"])
    for concern_id, note in ((team, "Team answer"), (dept, "Tool answer")):
        await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                          json={"note": note}, headers=sales)

    rows = await _close_rows(client, pm["auth"], cid)
    assert len(rows) == 1                      # one errand per change
    assert rows[0]["question_count"] == 2
    assert rows[0]["reason"] == "Tool answer"  # the most recently answered

    # Tool Engineering is asked about its own only
    rows = await _close_rows(client, tool["auth"], cid)
    assert len(rows) == 1 and rows[0]["question_count"] == 1
    assert rows[0]["concern_id"] == dept


# --- a department hold is answered with a proposal, by anyone ---------------

async def _dept_concern_in_assessment(client, admin_auth, seed, session_factory,
                                      suffix):
    """A change in assessment carrying an open Tool Engineer hold."""
    from app.models.change import ChangeRequest
    from app.models.workflow import Department
    cid = await _change_in_scoping(client, admin_auth, seed, suffix)
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        dept_id = dept.id
        c = await s.get(ChangeRequest, cid)
        c.status = "in_assessment"
        await s.commit()
    concern_id = await insert_legacy_concern(
        session_factory, cid, kind="needs_info",
        note="Tolerance cannot be held", raised_by=seed["admin_id"],
        department_id=dept_id)
    return cid, concern_id, dept_id


async def test_anyone_may_propose_a_solution_with_its_documentation(
        client, admin_auth, eng_auth, seed, session_factory):
    cid, concern_id, _ = await _dept_concern_in_assessment(
        client, admin_auth, seed, session_factory, "24")

    # text alone is a conversation, not a proposal
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "We could shim it"}, headers=eng_auth)
    assert res.status_code == 400
    assert "documentation attached" in res.json()["detail"]

    up = await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("proposal.pptx", b"PK x", "application/vnd."
                        "openxmlformats-officedocument.presentationml.presentation")},
        data={"kind": "info_response", "concern_id": str(concern_id)},
        headers=eng_auth)
    assert up.status_code in (200, 201), up.text

    # ...and a non-Sales team member may put it forward
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "Shim + revised tolerance, see deck"},
                            headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is True          # the raiser still decides


async def test_only_the_raising_department_or_pm_closes_the_loop(
        client, admin_auth, eng_auth, seed, session_factory):
    cid, concern_id, dept_id = await _dept_concern_in_assessment(
        client, admin_auth, seed, session_factory, "25")
    await client.post(
        f"/api/v1/changes/{cid}/attachments",
        files={"file": ("proposal.pptx", b"PK x", "application/pdf")},
        data={"kind": "info_response", "concern_id": str(concern_id)},
        headers=eng_auth)
    await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                      json={}, headers=eng_auth)

    # the proposer cannot accept their own proposal
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            json={"resolution_note": "good enough"}, headers=eng_auth)
    assert res.status_code == 400

    acting = {**admin_auth, "X-Acts-As-Department": str(dept_id)}
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/withdraw",
                            json={"resolution_note": "Shim accepted"}, headers=acting)
    assert res.status_code == 200, res.text
    assert res.json()["is_open"] is False


async def test_customer_questions_stay_sales_only(
        client, admin_auth, eng_auth, seed, session_factory):
    """The scoping-phase rule is untouched: words are enough, Sales answers."""
    cid, concern_id, _ = await _open_team_flag(
        client, admin_auth, seed, session_factory, "26")
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "I asked the customer"}, headers=eng_auth)
    assert res.status_code == 400
    assert "Sales" in res.json()["detail"]

    sales = await _sales_member(client, session_factory, seed)
    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "Customer sent rev C"}, headers=sales)
    assert res.status_code == 200, res.text


async def test_a_department_attribution_during_scoping_stays_sales_only(
        client, admin_auth, eng_auth, seed, session_factory):
    """Attribution at scoping is a label on a customer question, not a hold —
    so it keeps the Sales rule while the change is still in scoping."""
    from app.models.workflow import Department
    cid = await _change_in_scoping(client, admin_auth, seed, "27")
    async with session_factory() as s:
        dept = Department(name="APQP", flow_type="action", is_active=True)
        s.add(dept)
        await s.commit()
        dept_id = dept.id
    concern_id = await insert_legacy_concern(
        session_factory, cid, kind="needs_info", note="Which tolerance class?",
        raised_by=seed["admin_id"], department_id=dept_id)

    res = await client.post(f"/api/v1/changes/{cid}/concerns/{concern_id}/answer",
                            json={"note": "Class 2"}, headers=eng_auth)
    assert res.status_code == 400
    assert "Sales" in res.json()["detail"]
