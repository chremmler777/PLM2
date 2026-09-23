"""DFM entries: three columns, addressed-to, files, supersede chain collapsed
into history, closed topics refuse entries."""
import json

from tests.test_dfm_topics import make_tool


async def make_topic(client, eng_auth, tool, title="Gate position"):
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics", json={"title": title}, headers=eng_auth)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=("toolmaker", "tier1"),
                     note="DFM request rev A", sent_at="2026-09-24", supersedes_id=None, files=()):
    data = {"party": party, "addressed_to": json.dumps(list(addressed_to)), "note": note, "sent_at": sent_at}
    if supersedes_id is not None:
        data["supersedes_id"] = str(supersedes_id)
    multipart = [("files", (name, payload, ctype)) for name, payload, ctype in files]
    return await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/entries",
                             data=data, files=multipart or None, headers=eng_auth)


async def test_entry_with_two_files(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)

    res = await post_entry(client, eng_auth, tool, topic, files=[
        ("dfm_request_A.pdf", b"%PDF-1.4 a", "application/pdf"),
        ("volumes.xlsx", b"PK...", None),
    ])
    assert res.status_code == 201, res.text
    entry = res.json()
    assert entry["party"] == "ktx"
    assert entry["addressed_to"] == ["toolmaker", "tier1"]
    assert entry["note"] == "DFM request rev A"
    assert entry["sent_at"] == "2026-09-24"
    assert entry["recorded_by"] == seed["engineer_id"]
    assert entry["recorded_by_name"] == "Engineer"
    assert entry["history"] == []
    assert [f["original_filename"] for f in entry["files"]] == ["dfm_request_A.pdf", "volumes.xlsx"]
    assert entry["files"][0]["content_type"] == "application/pdf"
    assert entry["files"][1]["content_type"].startswith("application/")
    assert entry["files"][0]["uploaded_by_name"] == "Engineer"
    saved = tmp_path / "uploads" / "dfm" / str(tool) / str(entry["id"])
    assert len(list(saved.iterdir())) == 2

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)
    assert res.json()[0]["entry_count"] == 1
    assert res.json()[0]["last_activity"] == entry["recorded_at"]

    res = await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)
    assert any(e["action"] == "dfm_entry_recorded" and "2 file(s)" in e["action_description"] for e in res.json())


async def test_closed_topic_refuses_entries_until_reopened(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    assert (await post_entry(client, eng_auth, tool, topic)).status_code == 201

    assert (await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/close", headers=eng_auth)).status_code == 200
    res = await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"], note="late")
    assert res.status_code == 409
    assert res.json()["detail"] == "Topic is finished, reopen it first"

    assert (await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/reopen", headers=eng_auth)).status_code == 200
    res = await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"], note="late")
    assert res.status_code == 201


async def test_update_supersedes_and_keeps_history(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    first = (await post_entry(client, eng_auth, tool, topic, note="answer, 3 points open")).json()
    other = (await post_entry(client, eng_auth, tool, topic, party="toolmaker", addressed_to=["ktx"], note="study r1")).json()
    second = (await post_entry(client, eng_auth, tool, topic, note="answer, 2 points open", supersedes_id=first["id"])).json()
    assert second["supersedes_id"] == first["id"]
    third = (await post_entry(client, eng_auth, tool, topic, note="answer, 1 point open", supersedes_id=second["id"])).json()

    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=eng_auth)
    detail = res.json()
    # newest of the chain only, at its own time; the toolmaker entry stays in between
    assert [e["id"] for e in detail["entries"]] == [other["id"], third["id"]]
    top = detail["entries"][1]
    assert top["note"] == "answer, 1 point open"
    assert [h["note"] for h in top["history"]] == ["answer, 2 points open", "answer, 3 points open"]
    assert "history" not in top["history"][0]
    assert detail["entry_count"] == 4


async def test_supersede_guards(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic_a = await make_topic(client, eng_auth, tool, "A")
    topic_b = await make_topic(client, eng_auth, tool, "B")
    in_a = (await post_entry(client, eng_auth, tool, topic_a)).json()

    res = await post_entry(client, eng_auth, tool, topic_b, supersedes_id=in_a["id"])
    assert res.status_code == 400
    assert "not in this topic" in res.json()["detail"]

    res = await post_entry(client, eng_auth, tool, topic_a, party="toolmaker", addressed_to=["ktx"], supersedes_id=in_a["id"])
    assert res.status_code == 400
    assert "own column" in res.json()["detail"]

    res = await post_entry(client, eng_auth, tool, topic_a, supersedes_id=999999)
    assert res.status_code == 400


async def test_addressed_to_rules(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    assert (await post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=["ktx"])).status_code == 400
    assert (await post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=["brose"])).status_code == 400
    assert (await post_entry(client, eng_auth, tool, topic, party="ktx", addressed_to=[])).status_code == 400
    assert (await post_entry(client, eng_auth, tool, topic, party="brose", addressed_to=["ktx"])).status_code == 400
    res = await post_entry(client, eng_auth, tool, topic, party="tier1", addressed_to=["ktx", "ktx"])
    assert res.status_code == 201
    assert res.json()["addressed_to"] == ["ktx"]


async def test_bare_entry_and_blank_sent_at(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await post_entry(client, eng_auth, tool, topic, note="", sent_at="")
    assert res.status_code == 201, res.text
    assert res.json()["note"] is None
    assert res.json()["sent_at"] is None
    assert res.json()["files"] == []
    assert (await post_entry(client, eng_auth, tool, topic, sent_at="yesterday")).status_code == 400


async def test_double_supersede_is_rejected(client, eng_auth, seed, monkeypatch, tmp_path):
    """Two updates racing against the same entry: the first supersede wins,
    the second is rejected with 409 so the client can refresh instead of
    silently forking the history."""
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    first = (await post_entry(client, eng_auth, tool, topic, note="answer v1")).json()

    res = await post_entry(client, eng_auth, tool, topic, note="answer v2", supersedes_id=first["id"])
    assert res.status_code == 201, res.text
    second = res.json()

    res = await post_entry(client, eng_auth, tool, topic, note="answer v2 too", supersedes_id=first["id"])
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == "This entry was already updated, refresh"

    detail = (await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=eng_auth)).json()
    assert [e["id"] for e in detail["entries"]] == [second["id"]]
    assert detail["entry_count"] == 2  # first + second only, the rejected third never got stored


async def test_ledger_orders_by_sent_at_then_recorded(client, eng_auth, seed, monkeypatch, tmp_path):
    """A backfilled mail dated earlier sits above one recorded earlier but
    sent later."""
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)

    entry_a = (await post_entry(client, eng_auth, tool, topic, note="A", sent_at="2026-09-26")).json()
    entry_b = (await post_entry(client, eng_auth, tool, topic, note="B", sent_at="2026-09-20")).json()

    detail = (await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=eng_auth)).json()
    assert [e["id"] for e in detail["entries"]] == [entry_b["id"], entry_a["id"]]


async def test_long_filename_and_content_type_are_truncated(client, eng_auth, seed, monkeypatch, tmp_path):
    """Postgres varchar(255)/varchar(100) columns would overflow on an
    untruncated filename or content type; the service truncates before
    insert, keeping the extension."""
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)

    long_name = "a" * 296 + ".pdf"  # 300 chars total
    long_type = "application/" + "x" * 90  # > 100 chars

    res = await post_entry(client, eng_auth, tool, topic, files=[(long_name, b"%PDF-1.4", long_type)])
    assert res.status_code == 201, res.text
    f = res.json()["files"][0]
    assert len(f["original_filename"]) <= 255
    assert f["original_filename"].endswith(".pdf")
    assert len(f["content_type"]) <= 100
