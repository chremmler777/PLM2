"""DFM guards and the project-wide "general tooling DFM": finishing needs a
message, an entry needs a file or a note, rename, soft delete of an empty
topic, and the same endpoints under /projects/{project_id}/dfm."""
import json
import os

from sqlalchemy import select

from app.auth.security import get_password_hash
from app.models.dfm import DfmAuditEvent, DfmTopic
from app.models.entities import User
from tests.conftest import login
from tests.test_dfm_entries import make_topic, post_entry
from tests.test_dfm_topics import make_tool
import pytest


@pytest.fixture(autouse=True)
def _tool_engineer_member(tool_engineer):
    """DFM is Tool Engineer or admin only; the seeded engineer works as Tool Engineer."""



async def _other_user(session_factory, seed) -> int:
    """An active non-admin who did not open the topic."""
    async with session_factory() as s:
        u = User(organization_id=seed["org_id"], username="other", email="other@test.io", full_name="Other",
                 hashed_password=get_password_hash("other-secret-1"), role="engineer", is_active=True,
                 mfa_enabled=False)
        s.add(u)
        await s.commit()
        return u.id


async def _events(session_factory, **where):
    async with session_factory() as s:
        q = select(DfmAuditEvent).order_by(DfmAuditEvent.id)
        for k, v in where.items():
            q = q.where(getattr(DfmAuditEvent, k) == v)
        return list((await s.execute(q)).scalars().all())


def proj_url(seed, rest=""):
    return f"/api/v1/projects/{seed['project_id']}/dfm{rest}"


# ---- rules, tool scope ------------------------------------------------------

async def test_close_empty_topic_is_refused(client, eng_auth, seed):
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/close", headers=eng_auth)
    assert res.status_code == 409
    assert res.json()["detail"] == "Record at least one message before finishing the topic"


async def test_entry_without_file_or_note(client, eng_auth, seed):
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await post_entry(client, eng_auth, tool, topic, note="   ")
    assert res.status_code == 400
    assert res.json()["detail"] == "Attach the DFM file or write a note"


async def test_summary_names_and_can_delete(client, eng_auth, admin_auth, seed):
    tool = await make_tool(client, eng_auth, seed)
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics", json={"title": "Gate"}, headers=eng_auth)
    created = res.json()
    assert created["project_id"] is None and created["tool_part_id"] == tool
    assert created["opened_by_name"] == "Engineer" and created["closed_by_name"] is None
    assert created["can_delete"] is True
    rows = (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)).json()
    assert rows[0]["opened_by_name"] == "Engineer" and rows[0]["can_delete"] is True
    # an admin may delete it too
    rows = (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=admin_auth)).json()
    assert rows[0]["can_delete"] is True
    await post_entry(client, eng_auth, tool, created["id"])
    d = (await client.post(f"/api/v1/parts/{tool}/dfm/topics/{created['id']}/close", headers=eng_auth)).json()
    # a tool editor (admin here) may still delete it, with a reason since it has entries
    assert d["closed_by_name"] == "Engineer" and d["can_delete"] is True and d["can_edit"] is True


async def test_rename(client, eng_auth, seed, session_factory):
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool, title="DFM")
    url = f"/api/v1/parts/{tool}/dfm/topics/{topic}"
    res = await client.patch(url, json={"title": "  Gate position  "}, headers=eng_auth)
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Gate position"
    # same title: no-op, no second event
    res = await client.patch(url, json={"title": "Gate position"}, headers=eng_auth)
    assert res.status_code == 200
    assert (await client.patch(url, json={"title": "  "}, headers=eng_auth)).status_code == 422
    renamed = await _events(session_factory, action="topic_renamed")
    assert len(renamed) == 1
    assert renamed[0].details == {"from": "DFM", "to": "Gate position"}
    assert renamed[0].tool_part_id == tool and renamed[0].topic_id == topic
    # also allowed on a finished topic
    await post_entry(client, eng_auth, tool, topic)
    await client.post(f"{url}/close", headers=eng_auth)
    res = await client.patch(url, json={"title": "Gate position (final)"}, headers=eng_auth)
    assert res.status_code == 200 and res.json()["status"] == "finished_confirmed"
    log = (await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)).json()
    assert [e["action"] for e in log].count("dfm_topic_renamed") == 2
    audit = (await client.get(f"/api/v1/parts/{tool}/dfm/audit", params={"action": "topic_renamed"},
                              headers=eng_auth)).json()
    assert len(audit) == 2


async def test_delete_empty_topic_by_opener(client, eng_auth, seed, session_factory):
    tool = await make_tool(client, eng_auth, seed)
    keep = await make_topic(client, eng_auth, tool, title="Keep")
    topic = await make_topic(client, eng_auth, tool, title="DFM")
    url = f"/api/v1/parts/{tool}/dfm/topics/{topic}"
    res = await client.delete(url, headers=eng_auth)
    assert res.status_code == 204

    rows = (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)).json()
    assert [t["id"] for t in rows] == [keep]
    assert (await client.get(url, headers=eng_auth)).status_code == 404
    assert (await client.patch(url, json={"title": "x"}, headers=eng_auth)).status_code == 404
    assert (await client.post(f"{url}/close", headers=eng_auth)).status_code == 404
    assert (await client.post(f"{url}/reopen", headers=eng_auth)).status_code == 404
    assert (await post_entry(client, eng_auth, tool, topic)).status_code == 404
    assert (await client.delete(url, headers=eng_auth)).status_code == 404

    async with session_factory() as s:
        row = await s.get(DfmTopic, topic)
        assert row.deleted_at is not None and row.deleted_by == seed["engineer_id"]
    # the trail keeps its events and still names the topic
    audit = (await client.get(f"/api/v1/parts/{tool}/dfm/audit", headers=eng_auth)).json()
    mine = [e for e in audit if e["topic"] and e["topic"]["id"] == topic]
    assert [e["action"] for e in mine] == ["topic_deleted", "topic_opened"]
    assert all(e["topic"]["title"] == "DFM" for e in mine)
    assert mine[0]["details"] == {"title": "DFM"}
    res = await client.get(f"/api/v1/parts/{tool}/dfm/audit", params={"topic_id": topic}, headers=eng_auth)
    assert res.status_code == 200 and len(res.json()) == 2
    log = (await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)).json()
    assert "dfm_topic_deleted" in [e["action"] for e in log]


async def _dept(session_factory, name):
    from sqlalchemy import select as _select
    from app.models.workflow import Department
    async with session_factory() as s:
        d = (await s.execute(_select(Department).where(Department.name == name))).scalar_one_or_none()
        if d is None:
            d = Department(name=name, flow_type="action", is_active=True)
            s.add(d)
            await s.commit()
        return d.id


async def test_delete_rules(client, eng_auth, admin_auth, seed, session_factory):
    from app.services.tool_rights import TOOL_EDIT_DENIED
    quality = await _dept(session_factory, "Quality")
    tool_eng = await _dept(session_factory, "Tool Engineer")
    as_quality = {**admin_auth, "X-Acts-As-Department": str(quality)}
    as_tool_eng = {**admin_auth, "X-Acts-As-Department": str(tool_eng)}
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    url = f"/api/v1/parts/{tool}/dfm/topics/{topic}"

    # acting as another department: view only
    rows = (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=as_quality)).json()
    assert (rows[0]["can_edit"], rows[0]["can_delete"]) == (False, False)
    res = await client.delete(url, headers=as_quality)
    assert res.status_code == 403 and res.json()["detail"] == TOOL_EDIT_DENIED

    # a topic with entries needs a reason; hidden, entries and audit stay
    await post_entry(client, eng_auth, tool, topic)
    res = await client.delete(url, headers=as_tool_eng)
    assert res.status_code == 400
    assert res.json()["detail"] == "Say why this topic is deleted: it already has entries"
    assert await _events(session_factory, action="topic_deleted") == []
    res = await client.request("DELETE", url, json={"reason": "  Opened on the wrong tool  "}, headers=as_tool_eng)
    assert res.status_code == 204, res.text
    ev = await _events(session_factory, action="topic_deleted")
    assert len(ev) == 1 and ev[0].details["reason"] == "Opened on the wrong tool"
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)).json() == []
    log = (await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)).json()
    assert any(e["action"] == "dfm_topic_deleted" and "Opened on the wrong tool" in e["action_description"] for e in log)

    # an empty topic needs no reason
    second = await make_topic(client, eng_auth, tool, title="Second")
    res = await client.delete(f"/api/v1/parts/{tool}/dfm/topics/{second}", headers=admin_auth)
    assert res.status_code == 204


async def test_view_only_outside_tool_engineer(client, eng_auth, admin_auth, seed, session_factory):
    """Every DFM write is refused while acting as another department; reading still works."""
    quality = await _dept(session_factory, "Quality")
    as_quality = {**admin_auth, "X-Acts-As-Department": str(quality)}
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    base = f"/api/v1/parts/{tool}/dfm/topics"
    assert (await client.post(base, json={"title": "x"}, headers=as_quality)).status_code == 403
    assert (await client.patch(f"{base}/{topic}", json={"title": "y"}, headers=as_quality)).status_code == 403
    assert (await client.post(f"{base}/{topic}/close", headers=as_quality)).status_code == 403
    assert (await client.post(f"{base}/{topic}/reopen", headers=as_quality)).status_code == 403
    data = {"party": "ktx", "addressed_to": json.dumps(["toolmaker"]), "note": "n"}
    assert (await client.post(f"{base}/{topic}/entries", data=data, headers=as_quality)).status_code == 403
    assert (await client.get(f"{base}/{topic}", headers=as_quality)).status_code == 200


# ---- project scope ----------------------------------------------------------

async def test_project_topic_crud_entry_file_audit(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert (await client.get(proj_url(seed, "/topics"), headers=eng_auth)).json() == []

    res = await client.post(proj_url(seed, "/topics"), json={"title": "Tooling standard"}, headers=eng_auth)
    assert res.status_code == 201, res.text
    topic = res.json()
    assert topic["project_id"] == seed["project_id"] and topic["tool_part_id"] is None
    assert topic["can_delete"] is True and topic["opened_by_name"] == "Engineer"
    tid = topic["id"]

    rows = (await client.get(proj_url(seed, "/topics"), headers=eng_auth)).json()
    assert [t["id"] for t in rows] == [tid]

    res = await client.post(proj_url(seed, f"/topics/{tid}/close"), headers=eng_auth)
    assert res.status_code == 409

    data = {"party": "ktx", "addressed_to": json.dumps(["toolmaker"]), "note": "KTX tooling standard rev 3"}
    res = await client.post(proj_url(seed, f"/topics/{tid}/entries"), data=data,
                            files=[("files", ("standard.pdf", b"%PDF std", "application/pdf"))], headers=eng_auth)
    assert res.status_code == 201, res.text
    entry = res.json()
    fid = entry["files"][0]["id"]
    saved = os.listdir(tmp_path / "uploads" / "dfm" / f"project-{seed['project_id']}" / str(entry["id"]))
    assert len(saved) == 1

    res = await client.get(proj_url(seed, f"/files/{fid}/download"), headers=eng_auth)
    assert res.status_code == 200 and res.content == b"%PDF std"
    res = await client.get(proj_url(seed, f"/files/{fid}/inline"), headers=eng_auth)
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"

    d = (await client.get(proj_url(seed, f"/topics/{tid}"), headers=eng_auth)).json()
    assert d["entry_count"] == 1 and d["can_delete"] is True
    assert (await client.patch(proj_url(seed, f"/topics/{tid}"), json={"title": "Tooling standards"},
                               headers=eng_auth)).json()["title"] == "Tooling standards"
    res = await client.post(proj_url(seed, f"/topics/{tid}/close"), headers=eng_auth)
    assert res.status_code == 200 and res.json()["status"] == "finished_confirmed"
    res = await client.post(proj_url(seed, f"/topics/{tid}/reopen"), headers=eng_auth)
    assert res.status_code == 200 and res.json()["status"] == "open"
    assert (await client.delete(proj_url(seed, f"/topics/{tid}"), headers=eng_auth)).status_code == 400  # entries: reason needed

    audit = (await client.get(proj_url(seed, "/audit"), headers=eng_auth)).json()
    assert [e["action"] for e in audit] == [
        "topic_reopened", "topic_closed", "topic_renamed", "file_viewed", "file_downloaded",
        "file_attached", "entry_recorded", "topic_opened"]
    events = await _events(session_factory)
    assert all(e.project_id == seed["project_id"] and e.tool_part_id is None for e in events)

    res = await client.get(proj_url(seed, "/audit.csv"), headers=eng_auth)
    assert res.status_code == 200
    assert 'filename="dfm-audit-proj.csv"' in res.headers["content-disposition"]
    res = await client.get(proj_url(seed, "/audit.csv"), params={"topic_id": tid}, headers=eng_auth)
    assert f'filename="dfm-audit-proj-topic-{tid}.csv"' in res.headers["content-disposition"]


async def test_project_and_tool_archives_are_separate(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    tool_topic = await make_topic(client, eng_auth, tool)
    proj_topic = (await client.post(proj_url(seed, "/topics"), json={"title": "Material"},
                                    headers=eng_auth)).json()["id"]
    assert [t["id"] for t in (await client.get(proj_url(seed, "/topics"), headers=eng_auth)).json()] == [proj_topic]
    assert [t["id"] for t in (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)).json()] \
        == [tool_topic]
    assert (await client.get(proj_url(seed, f"/topics/{tool_topic}"), headers=eng_auth)).status_code == 404
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/topics/{proj_topic}", headers=eng_auth)).status_code == 404
    entry = (await post_entry(client, eng_auth, tool, tool_topic,
                              files=[("a.pdf", b"%PDF a", "application/pdf")])).json()
    fid = entry["files"][0]["id"]
    assert (await client.get(proj_url(seed, f"/files/{fid}/download"), headers=eng_auth)).status_code == 404
    assert (await client.get(proj_url(seed, "/audit"), params={"topic_id": tool_topic},
                             headers=eng_auth)).status_code == 404
    tool_audit = (await client.get(f"/api/v1/parts/{tool}/dfm/audit", headers=eng_auth)).json()
    assert all(e["topic"]["id"] == tool_topic for e in tool_audit)


async def test_project_delete_and_missing_project(client, eng_auth, seed, session_factory):
    tid = (await client.post(proj_url(seed, "/topics"), json={"title": "DFM"}, headers=eng_auth)).json()["id"]
    assert (await client.delete(proj_url(seed, f"/topics/{tid}"), headers=eng_auth)).status_code == 204
    assert (await client.get(proj_url(seed, "/topics"), headers=eng_auth)).json() == []
    assert (await client.get(proj_url(seed, f"/topics/{tid}"), headers=eng_auth)).status_code == 404
    audit = (await client.get(proj_url(seed, "/audit"), headers=eng_auth)).json()
    assert [e["action"] for e in audit] == ["topic_deleted", "topic_opened"]
    assert audit[0]["topic"] == {"id": tid, "title": "DFM"}

    res = await client.get("/api/v1/projects/999999/dfm/topics", headers=eng_auth)
    assert res.status_code == 404 and res.json()["detail"] == "Project not found"
    res = await client.post("/api/v1/projects/999999/dfm/topics", json={"title": "x"}, headers=eng_auth)
    assert res.status_code == 404
