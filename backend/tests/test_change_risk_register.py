"""The per-change risk register, and the two document kinds around it.

A department's assessment now carries two different things: points that hold
its submit (legacy concerns, still soft-blocking) and risks it wants recorded
and travelling with the change. These tests pin the difference, plus the
document rules that changed with it — the customer deck the "not feasible"
verdict is gated on, and customer correspondence that belongs to nobody's
assessment.
"""
import pytest

from app.models.change import ChangeAssessment, ChangeConcern, ChangeRequest
from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def assessing(session_factory, seed):
    """A change in assessment with one department's assessment row on it."""
    async with session_factory() as s:
        dept = Department(name="Tool Engineer", flow_type="action", is_active=True)
        s.add(dept)
        await s.flush()
        change = ChangeRequest(
            change_number="C-RISK-1", title="risk register", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], status="in_assessment")
        s.add(change)
        await s.flush()
        a = ChangeAssessment(change_id=change.id, department_id=dept.id,
                             stage_order=1)
        s.add(a)
        await s.commit()
        return {"change_id": change.id, "assessment_id": a.id,
                "department_id": dept.id}


async def _raise(client, auth, assessing, **body):
    payload = {"kind": "risk", "note": "Thin wall will short-shot",
               "department_id": assessing["department_id"],
               "risk_type": "fill_issue", "severity": 2}
    payload.update(body)
    return await client.post(f"/api/v1/changes/{assessing['change_id']}/concerns",
                             json=payload, headers=auth)


async def _submit(client, auth, assessing, verdict="feasible"):
    return await client.post(
        f"/api/v1/changes/{assessing['change_id']}/assessments",
        json={"department_id": assessing["department_id"], "verdict": verdict},
        headers=auth)


async def _upload(client, auth, change_id, kind, **data):
    form = {"kind": kind}
    form.update({k: str(v) for k, v in data.items()})
    return await client.post(
        f"/api/v1/changes/{change_id}/attachments",
        files={"file": ("doc.pptx", b"PK x", "application/octet-stream")},
        data=form, headers=auth)


# --- raising a risk -------------------------------------------------------

async def test_a_risk_records_its_type_and_severity(client, admin_auth, assessing):
    res = await _raise(client, admin_auth, assessing)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "risk"
    assert body["risk_type"] == "fill_issue"
    assert body["severity"] == 2
    assert body["is_open"] is True


async def test_a_risk_type_outside_the_vocabulary_is_refused(
        client, admin_auth, assessing):
    """Free text would make the register uncountable, which is its only point."""
    res = await _raise(client, admin_auth, assessing, risk_type="vibes")
    assert res.status_code == 400, res.text
    assert "Invalid risk type" in res.json()["detail"]

    res = await _raise(client, admin_auth, assessing, risk_type=None)
    assert res.status_code == 400, res.text


async def test_severity_is_one_two_or_three(client, admin_auth, assessing):
    for bad in (0, 4, None):
        res = await _raise(client, admin_auth, assessing, severity=bad)
        assert res.status_code == 400, res.text
        assert "severity" in res.json()["detail"].lower()


async def test_several_risks_may_stand_at_once(client, admin_auth, assessing):
    """A register is a list — the one-per-kind rule that guards legacy concerns
    would make it useless."""
    assert (await _raise(client, admin_auth, assessing)).status_code == 200
    second = await _raise(client, admin_auth, assessing,
                          risk_type="dimensional_issue", severity=3,
                          note="Datum B moves")
    assert second.status_code == 200, second.text


async def test_a_direct_raise_can_only_be_a_risk(client, admin_auth, assessing):
    """reject_proposal and needs_info are outcomes of a scoping decision; minted
    by hand they are open points nobody owes an answer to."""
    for kind in ("reject_proposal", "needs_info"):
        res = await _raise(client, admin_auth, assessing, kind=kind)
        assert res.status_code == 400, res.text
        assert "scoping decision" in res.json()["detail"]


async def test_the_risk_vocabulary_is_served(client, admin_auth):
    res = await client.get("/api/v1/changes/reference/risk-types", headers=admin_auth)
    assert res.status_code == 200, res.text
    assert [i["key"] for i in res.json()["items"]] == [
        "fill_issue", "dimensional_issue", "visual_surface",
        "process_capability", "other"]


async def test_the_risk_reference_needs_a_login(client):
    assert (await client.get("/api/v1/changes/reference/risk-types")).status_code == 401


# --- risks are register-only ---------------------------------------------

async def test_an_open_risk_does_not_hold_the_submit(client, admin_auth, assessing):
    """The department signs its verdict WITH its risks — that is the point of
    recording them rather than arguing them away first."""
    assert (await _raise(client, admin_auth, assessing)).status_code == 200
    res = await _submit(client, admin_auth, assessing)
    assert res.status_code == 200, res.text


async def test_a_legacy_open_concern_still_holds_the_submit(
        client, admin_auth, assessing, session_factory, seed):
    """Written straight to the table: the scoping meeting still creates these,
    even though the raise endpoint no longer will."""
    async with session_factory() as s:
        s.add(ChangeConcern(
            change_id=assessing["change_id"], kind="needs_info",
            note="Which tolerance applies?", raised_by=seed["admin_id"],
            department_id=assessing["department_id"]))
        await s.commit()
    res = await _submit(client, admin_auth, assessing)
    assert res.status_code == 400, res.text
    assert "open concerns" in res.json()["detail"]


async def test_a_risk_does_not_flag_its_department_as_blocked(
        client, admin_auth, assessing):
    assert (await _raise(client, admin_auth, assessing)).status_code == 200
    detail = await client.get(f"/api/v1/changes/{assessing['change_id']}",
                              headers=admin_auth)
    assert detail.status_code == 200, detail.text
    assert detail.json()["blocked_department_ids"] == []


# --- document kinds -------------------------------------------------------

async def test_not_feasible_wants_the_customer_deck_specifically(
        client, admin_auth, assessing):
    """Generic evidence proves the work was done; it is not the thing the
    customer is shown."""
    res = await _submit(client, admin_auth, assessing, verdict="not_feasible")
    assert res.status_code == 400, res.text
    assert "change_ppt" in res.json()["detail"]

    up = await _upload(client, admin_auth, assessing["change_id"], "general",
                       assessment_id=assessing["assessment_id"])
    assert up.status_code in (200, 201), up.text
    res = await _submit(client, admin_auth, assessing, verdict="not_feasible")
    assert res.status_code == 400, res.text

    up = await _upload(client, admin_auth, assessing["change_id"], "change_ppt",
                       assessment_id=assessing["assessment_id"])
    assert up.status_code in (200, 201), up.text
    assert up.json()["assessment_id"] == assessing["assessment_id"]

    res = await _submit(client, admin_auth, assessing, verdict="not_feasible")
    assert res.status_code == 200, res.text


async def test_the_deck_is_reported_separately_from_other_evidence(
        client, admin_auth, assessing):
    up = await _upload(client, admin_auth, assessing["change_id"], "change_ppt",
                       assessment_id=assessing["assessment_id"])
    assert up.status_code in (200, 201), up.text
    detail = (await client.get(f"/api/v1/changes/{assessing['change_id']}",
                               headers=admin_auth)).json()
    row = next(a for a in detail["assessments"]
               if a["id"] == assessing["assessment_id"])
    assert row["has_change_ppt"] is True
    assert row["has_evidence"] is True
    assert row["has_rfq"] is False


async def test_customer_mail_is_change_level_only(client, admin_auth, assessing):
    """Filed into an assessment it would be invisible to everyone not looking
    at that department's row."""
    res = await _upload(client, admin_auth, assessing["change_id"],
                        "customer_email",
                        assessment_id=assessing["assessment_id"])
    assert res.status_code == 400, res.text
    assert "on the change itself" in res.json()["detail"]

    res = await _upload(client, admin_auth, assessing["change_id"], "customer_email")
    assert res.status_code in (200, 201), res.text
    assert res.json()["assessment_id"] is None


async def test_anyone_may_file_customer_mail(client, eng_auth, assessing):
    """The engineer is in no department and owns nothing on this change; they
    can still be the one in the mail thread."""
    res = await _upload(client, eng_auth, assessing["change_id"], "customer_email")
    assert res.status_code in (200, 201), res.text
    assert res.json()["kind"] == "customer_email"


async def test_evidence_still_belongs_to_the_assessed_department(
        client, eng_auth, assessing):
    """The loosening is for customer mail only — assessment evidence keeps its
    rule."""
    res = await _upload(client, eng_auth, assessing["change_id"], "change_ppt",
                        assessment_id=assessing["assessment_id"])
    assert res.status_code == 400, res.text
    assert "assessed department" in res.json()["detail"]
