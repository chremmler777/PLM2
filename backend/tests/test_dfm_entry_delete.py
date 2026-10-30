"""DFM entry soft delete: the recorder or an admin, with a reason, only while
no live update or reply builds on it. A deleted entry is hidden everywhere
(flow, counts, status, file downloads); row, files on disk and audit stay.
Deleting an update makes the superseded entry current again."""
import os

import pytest
from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.dfm import DfmAuditEvent, DfmEntry
from app.models.entities import User
from tests.conftest import login, make_tool_engineer
from tests.test_dfm_entries import make_topic, post_entry
from tests.test_dfm_flow import step
from tests.test_dfm_topics import make_tool


@pytest.fixture(autouse=True)
def _tool_engineer_member(tool_engineer):
    """DFM is Tool Engineer or admin only; the seeded engineer works as Tool Engineer."""


@pytest.fixture
async def other_auth(client, session_factory, seed):
    """A second Tool Engineer (no admin) who did not record anything."""
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="eng2", email="eng2@test.io", full_name="Other Engineer",
                 hashed_password=get_password_hash("eng2-secret-12"), role="engineer", is_active=True,
                 mfa_enabled=False)
        s.add(u)
        await s.commit()
        uid = u.id
    await make_tool_engineer(session_factory, uid)
    return await login(client, "eng2@test.io")


async def delete(client, auth, tool, topic, entry, reason="uploaded the wrong file"):
    body = {"reason": reason} if reason is not None else {}
    return await client.request("DELETE", f"/api/v1/parts/{tool}/dfm/topics/{topic}/entries/{entry}",
                                json=body, headers=auth)


async def detail(client, auth, tool, topic):
    return (await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=auth)).json()


async def test_recorder_deletes_with_reason_hidden_everywhere(client, eng_auth, seed, session_factory,
                                                              monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    first = (await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"],
                              note="DFM rev 1")).json()
    early = (await post_entry(client, eng_auth, tool, topic, party="tier1", addressed_to=["ktx"],
                              note="Brose comments (not all in yet)", sent_at="2026-09-25",
                              files=[("brose.pdf", b"%PDF-1.4 partial", "application/pdf")])).json()
    file_id = early["files"][0]["id"]
    d = await detail(client, eng_auth, tool, topic)
    assert d["entry_count"] == 2
    assert {e["id"]: e["can_delete"] for e in d["entries"]} == {first["id"]: True, early["id"]: True}
    assert d["last_step"]["party"] == "tier1"

    # no reason: refused (blank or missing)
    assert (await delete(client, eng_auth, tool, topic, early["id"], reason="   ")).status_code == 422
    assert (await delete(client, eng_auth, tool, topic, early["id"], reason=None)).status_code == 422

    res = await delete(client, eng_auth, tool, topic, early["id"])
    assert res.status_code == 204, res.text

    d = await detail(client, eng_auth, tool, topic)
    assert [e["id"] for e in d["entries"]] == [first["id"]]
    assert d["entry_count"] == 1
    assert d["last_step"]["party"] == "toolmaker"
    assert d["waiting_on"] == [{"party": "ktx", "count": 1, "oldest_days": d["waiting_on"][0]["oldest_days"]}]
    topics = (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)).json()
    assert topics[0]["entry_count"] == 1 and topics[0]["last_step"]["party"] == "toolmaker"

    # its file: 404 for download and view, but still on disk
    for mode in ("download", "inline"):
        res = await client.get(f"/api/v1/parts/{tool}/dfm/files/{file_id}/{mode}", headers=eng_auth)
        assert res.status_code == 404
    assert os.listdir(tmp_path / "uploads" / "dfm" / str(tool) / str(early["id"]))

    # deleting it again: not found
    assert (await delete(client, eng_auth, tool, topic, early["id"])).status_code == 404

    async with session_factory() as s:
        row = await s.get(DfmEntry, early["id"])
        assert row.deleted_at is not None and row.deleted_by == seed["engineer_id"]
        assert row.delete_reason == "uploaded the wrong file"
        events = (await s.execute(select(DfmAuditEvent).where(DfmAuditEvent.action == "entry_deleted"))).scalars().all()
    assert len(events) == 1
    assert events[0].entry_id == early["id"] and events[0].actor_id == seed["engineer_id"]
    assert events[0].details["reason"] == "uploaded the wrong file"
    assert events[0].details["files"] == ["brose.pdf"]

    # the audit log shows it (the trail stays readable)
    log = (await client.get(f"/api/v1/parts/{tool}/dfm/audit", params={"action": "entry_deleted"},
                            headers=eng_auth)).json()
    assert [e["details"]["reason"] for e in log] == ["uploaded the wrong file"]
    changelog = (await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)).json()
    line = next(c for c in changelog if c["action"] == "dfm_entry_deleted")
    assert "uploaded the wrong file" in line["action_description"]


async def test_other_engineer_is_refused_admin_may(client, eng_auth, admin_auth, other_auth, seed,
                                                   monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    a = (await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"])).json()

    d = await detail(client, other_auth, tool, topic)
    assert d["entries"][0]["can_delete"] is False
    res = await delete(client, other_auth, tool, topic, a["id"])
    assert res.status_code == 403
    assert res.json()["detail"] == "Only the user who recorded this entry or an admin can delete it"

    assert (await detail(client, admin_auth, tool, topic))["entries"][0]["can_delete"] is True
    assert (await delete(client, admin_auth, tool, topic, a["id"])).status_code == 204
    assert (await detail(client, eng_auth, tool, topic))["entries"] == []


async def test_viewer_without_tool_rights_is_refused(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    a = (await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"])).json()
    viewer = await login(client, "eng@test.io", admin=False)  # plm2_Viewer: read only
    assert (await delete(client, viewer, tool, topic, a["id"])).status_code == 403


async def test_refused_while_a_reply_or_update_builds_on_it(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    orig = (await step(client, eng_auth, tool, topic, party="toolmaker", to=["ktx"], note="DFM rev 1")).json()
    ans = (await step(client, eng_auth, tool, topic, party="ktx", to=["toolmaker"], kind="answer",
                      reply_to=orig["id"], note="ok")).json()

    d = await detail(client, eng_auth, tool, topic)
    assert {e["id"]: e["can_delete"] for e in d["entries"]} == {orig["id"]: False, ans["id"]: True}
    res = await delete(client, eng_auth, tool, topic, orig["id"])
    assert res.status_code == 409
    assert res.json()["detail"] == (f"#{ans['id']} replies to this entry. Delete the later step first, "
                                    "or use Update instead")

    upd = (await step(client, eng_auth, tool, topic, party="ktx", to=["toolmaker"], note="ok, v2",
                      supersedes_id=ans["id"])).json()
    res = await delete(client, eng_auth, tool, topic, ans["id"])
    assert res.status_code == 409
    assert res.json()["detail"] == (f"This entry was updated by #{upd['id']}. Delete the later step first, "
                                    "or use Update instead")

    # later step first: the update, then the answer, then the original
    assert (await delete(client, eng_auth, tool, topic, upd["id"])).status_code == 204
    assert (await delete(client, eng_auth, tool, topic, ans["id"])).status_code == 204
    assert (await delete(client, eng_auth, tool, topic, orig["id"])).status_code == 204
    assert (await detail(client, eng_auth, tool, topic))["entry_count"] == 0


async def test_deleting_an_update_makes_the_superseded_current(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    orig = (await step(client, eng_auth, tool, topic, party="toolmaker", to=["ktx"], note="DFM rev 1")).json()
    v1 = (await step(client, eng_auth, tool, topic, party="ktx", to=["toolmaker"], kind="answer",
                     reply_to=orig["id"], note="answer v1")).json()
    v2 = (await step(client, eng_auth, tool, topic, party="ktx", to=["toolmaker"], note="answer v2 (too early)",
                     supersedes_id=v1["id"])).json()
    d = await detail(client, eng_auth, tool, topic)
    assert [e["id"] for e in d["entries"]] == [orig["id"], v2["id"]]

    assert (await delete(client, eng_auth, tool, topic, v2["id"])).status_code == 204
    d = await detail(client, eng_auth, tool, topic)
    assert [e["id"] for e in d["entries"]] == [orig["id"], v1["id"]]
    current = d["entries"][1]
    assert current["note"] == "answer v1" and current["history"] == [] and current["can_delete"] is True
    # the original stays answered by the restored version
    assert [a["entry_id"] for a in d["entries"][0]["answered_by"]] == [v1["id"]]
    assert d["entry_count"] == 2

    # the restored entry can be updated again (the deleted update does not block it)
    v3 = await step(client, eng_auth, tool, topic, party="ktx", to=["toolmaker"], note="answer v3",
                    supersedes_id=v1["id"])
    assert v3.status_code == 201, v3.text
    d = await detail(client, eng_auth, tool, topic)
    assert [e["id"] for e in d["entries"]] == [orig["id"], v3.json()["id"]]
    assert [h["id"] for h in d["entries"][1]["history"]] == [v1["id"]]


async def test_deleted_entry_cannot_be_replied_to_or_updated(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    orig = (await step(client, eng_auth, tool, topic, party="toolmaker", to=["ktx"], note="DFM rev 1")).json()
    assert (await delete(client, eng_auth, tool, topic, orig["id"])).status_code == 204
    res = await step(client, eng_auth, tool, topic, party="ktx", to=["toolmaker"], kind="answer",
                     reply_to=orig["id"], note="ok")
    assert res.status_code == 400
    res = await step(client, eng_auth, tool, topic, party="toolmaker", to=["ktx"], note="v2",
                     supersedes_id=orig["id"])
    assert res.status_code == 400


async def test_finished_topic_and_other_topic(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool, "A")
    other = await make_topic(client, eng_auth, tool, "B")
    a = (await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"])).json()
    # the entry is not in the other topic
    assert (await delete(client, eng_auth, tool, other, a["id"])).status_code == 404

    assert (await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/close", headers=eng_auth)).status_code == 200
    assert (await detail(client, eng_auth, tool, topic))["entries"][0]["can_delete"] is False
    res = await delete(client, eng_auth, tool, topic, a["id"])
    assert res.status_code == 409
    assert res.json()["detail"] == "Topic is finished, reopen it first"


async def test_project_scope(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pid = seed["project_id"]
    res = await client.post(f"/api/v1/projects/{pid}/dfm/topics", json={"title": "Standard"}, headers=eng_auth)
    topic = res.json()["id"]
    res = await client.post(f"/api/v1/projects/{pid}/dfm/topics/{topic}/entries", data={
        "party": "ktx", "addressed_to": '["toolmaker"]', "note": "standard v1"}, headers=eng_auth)
    entry = res.json()["id"]
    res = await client.request("DELETE", f"/api/v1/projects/{pid}/dfm/topics/{topic}/entries/{entry}",
                               json={"reason": "wrong project"}, headers=eng_auth)
    assert res.status_code == 204, res.text
    d = (await client.get(f"/api/v1/projects/{pid}/dfm/topics/{topic}", headers=eng_auth)).json()
    assert d["entries"] == [] and d["entry_count"] == 0
