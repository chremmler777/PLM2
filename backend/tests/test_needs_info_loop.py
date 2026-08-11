"""Closing the needs-info loop: a decision raises a Team flag, Sales gets the
task, and the question/answer documents are linked to each other."""
import pytest

from tests.conftest import login, satisfy_capture_gate

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
