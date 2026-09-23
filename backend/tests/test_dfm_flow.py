"""DFM flow: kinds (original, forward, answer, question), reply links, the
rules on who may answer, ask again or forward, and the derived answered or
waiting state per addressee."""
import json
from datetime import date, timedelta

from tests.test_dfm_entries import make_topic
from tests.test_dfm_topics import make_tool


def ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


async def step(client, eng_auth, tool, topic, party, to, kind=None, reply_to=None, note=None,
               sent_at=None, supersedes_id=None):
    data = {"party": party, "addressed_to": json.dumps(list(to))}
    if kind is not None:
        data["kind"] = kind
    if reply_to is not None:
        data["reply_to_id"] = str(reply_to)
    if note is not None:
        data["note"] = note
    if sent_at is not None:
        data["sent_at"] = sent_at
    if supersedes_id is not None:
        data["supersedes_id"] = str(supersedes_id)
    return await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/entries", data=data, headers=eng_auth)


async def ok(res):
    assert res.status_code == 201, res.text
    return res.json()


async def detail(client, eng_auth, tool, topic):
    res = await client.get(f"/api/v1/parts/{tool}/dfm/topics/{topic}", headers=eng_auth)
    assert res.status_code == 200, res.text
    return res.json()


def by_id(d):
    return {e["id"]: e for e in d["entries"]}


async def flow_topic(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    return tool, topic


# ---- rules ----------------------------------------------------------------

async def test_original_default_and_no_reply(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    e = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"]))
    assert e["kind"] == "original"
    assert e["reply_to_id"] is None
    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="original", reply_to=e["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "An original has no reply link"


async def test_unknown_kind(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="update")
    assert res.status_code == 400
    assert "Unknown kind" in res.json()["detail"]


async def test_reply_needs_link_in_same_topic(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    other = await make_topic(client, eng_auth, tool, "Other")
    orig = await ok(await step(client, eng_auth, tool, other, "toolmaker", ["ktx"]))
    for kind in ("answer", "question", "forward"):
        res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind=kind)
        assert res.status_code == 400
        assert res.json()["detail"] == f"A {kind} needs the message it replies to"
    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", reply_to=orig["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "The message replied to is not in this topic"
    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", reply_to=999999)
    assert res.status_code == 400


async def test_answer_rules(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    orig = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"]))
    # tier1 was not addressed
    res = await step(client, eng_auth, tool, topic, "tier1", ["toolmaker"], kind="answer", reply_to=orig["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "Only a party the message was addressed to can answer it"
    # must go back to the sender
    res = await step(client, eng_auth, tool, topic, "ktx", ["tier1"], kind="answer", reply_to=orig["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "An answer must be addressed to the sender of the message it replies to"
    # valid, with the third party as copy
    a = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker", "tier1"], kind="answer",
                            reply_to=orig["id"]))
    assert a["kind"] == "answer" and a["reply_to_id"] == orig["id"]


async def test_question_rules(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    orig = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"]))
    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="question", reply_to=orig["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "A question must reply to an answer"
    ans = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", reply_to=orig["id"]))
    res = await step(client, eng_auth, tool, topic, "tier1", ["ktx"], kind="question", reply_to=ans["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "Only a party the answer was addressed to can ask again on it"
    res = await step(client, eng_auth, tool, topic, "toolmaker", ["tier1"], kind="question", reply_to=ans["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "A question must be addressed to the sender of the answer it asks about"
    q = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"], kind="question", reply_to=ans["id"]))
    assert q["kind"] == "question"


async def test_forward_rules(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    orig = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"]))
    res = await step(client, eng_auth, tool, topic, "tier1", ["ktx"], kind="forward", reply_to=orig["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "Only KTX forwards messages"
    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="forward", reply_to=orig["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "A forward goes to a party that has not had the message yet"
    own = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"]))
    res = await step(client, eng_auth, tool, topic, "ktx", ["tier1"], kind="forward", reply_to=own["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "KTX can only forward a message it received"
    both = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx", "tier1"]))
    res = await step(client, eng_auth, tool, topic, "ktx", ["tier1"], kind="forward", reply_to=both["id"])
    assert res.status_code == 400
    fwd = await ok(await step(client, eng_auth, tool, topic, "ktx", ["tier1"], kind="forward", reply_to=orig["id"]))
    assert fwd["kind"] == "forward" and fwd["reply_to_id"] == orig["id"]


# ---- the relay --------------------------------------------------------------

async def test_full_relay(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)

    orig = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"], note="DFM rev 1", sent_at=ago(10)))
    assert orig["awaiting"] == [{"party": "ktx", "days": 10}]
    assert orig["answered_by"] == []
    d = await detail(client, eng_auth, tool, topic)
    assert d["waiting_on"] == [{"party": "ktx", "count": 1, "oldest_days": 10}]
    assert d["next_step"] == {"entry_id": orig["id"], "kind": "original", "from": "toolmaker", "to": "ktx", "days": 10}

    fwd = await ok(await step(client, eng_auth, tool, topic, "ktx", ["tier1"], kind="forward", reply_to=orig["id"],
                              sent_at=ago(8)))
    d = await detail(client, eng_auth, tool, topic)
    assert by_id(d)[fwd["id"]]["awaiting"] == [{"party": "tier1", "days": 8}]
    assert by_id(d)[orig["id"]]["awaiting"] == [{"party": "ktx", "days": 10}]  # a forward is not an answer
    assert d["waiting_on"] == [{"party": "ktx", "count": 1, "oldest_days": 10},
                               {"party": "tier1", "count": 1, "oldest_days": 8}]

    t1 = await ok(await step(client, eng_auth, tool, topic, "tier1", ["ktx"], kind="answer", reply_to=fwd["id"],
                             sent_at=ago(5)))
    d = await detail(client, eng_auth, tool, topic)
    assert by_id(d)[fwd["id"]]["awaiting"] == []
    assert by_id(d)[fwd["id"]]["answered_by"] == [{"party": "tier1", "entry_id": t1["id"], "date": ago(5)}]
    assert by_id(d)[t1["id"]]["awaiting"] == [] and by_id(d)[t1["id"]]["answered_by"] == []
    assert d["waiting_on"] == [{"party": "ktx", "count": 1, "oldest_days": 10}]

    ka = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", reply_to=orig["id"],
                             sent_at=ago(3)))
    d = await detail(client, eng_auth, tool, topic)
    assert by_id(d)[orig["id"]]["answered_by"] == [{"party": "ktx", "entry_id": ka["id"], "date": ago(3)}]
    assert d["waiting_on"] == []
    assert d["next_step"] is None
    assert d["all_answered"] is True

    q = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"], kind="question", reply_to=ka["id"],
                            sent_at=ago(1)))
    d = await detail(client, eng_auth, tool, topic)
    assert [e["id"] for e in d["entries"]] == [orig["id"], fwd["id"], t1["id"], ka["id"], q["id"]]
    assert [e["kind"] for e in d["entries"]] == ["original", "forward", "answer", "answer", "question"]
    assert by_id(d)[q["id"]]["awaiting"] == [{"party": "ktx", "days": 1}]
    assert d["waiting_on"] == [{"party": "ktx", "count": 1, "oldest_days": 1}]
    assert d["next_step"] == {"entry_id": q["id"], "kind": "question", "from": "toolmaker", "to": "ktx", "days": 1}
    assert d["all_answered"] is False
    assert d["last_step"] == {"kind": "question", "party": "toolmaker", "addressed_to": ["ktx"], "date": ago(1)}

    # the topic list carries the same summary
    rows = (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)).json()
    row = next(r for r in rows if r["id"] == topic)
    assert row["waiting_on"] == [{"party": "ktx", "count": 1, "oldest_days": 1}]
    assert row["last_step"] == d["last_step"]
    assert row["all_answered"] is False
    assert "entries" not in row


async def test_multi_addressee_partial_answer(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    orig = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker", "tier1"], sent_at=ago(4)))
    await ok(await step(client, eng_auth, tool, topic, "tier1", ["ktx"], kind="answer", reply_to=orig["id"]))
    d = await detail(client, eng_auth, tool, topic)
    e = by_id(d)[orig["id"]]
    assert e["awaiting"] == [{"party": "toolmaker", "days": 4}]
    assert [a["party"] for a in e["answered_by"]] == ["tier1"]
    assert d["all_answered"] is False


# ---- supersede --------------------------------------------------------------

async def test_update_of_answered_original_stays_answered(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    orig = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"], note="rev 1"))
    ans = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", reply_to=orig["id"]))
    upd = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"], note="rev 1 corrected",
                              supersedes_id=orig["id"]))
    assert upd["kind"] == "original" and upd["reply_to_id"] is None
    d = await detail(client, eng_auth, tool, topic)
    top = by_id(d)[upd["id"]]
    assert top["awaiting"] == []
    assert [a["entry_id"] for a in top["answered_by"]] == [ans["id"]]
    assert top["history"][0]["kind"] == "original"
    assert d["waiting_on"] == [] and d["all_answered"] is True


async def test_update_inherits_kind_and_reply(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    orig = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"]))
    ans = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", reply_to=orig["id"]))
    upd = await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], note="better",
                              supersedes_id=ans["id"]))
    assert upd["kind"] == "answer" and upd["reply_to_id"] == orig["id"]
    d = await detail(client, eng_auth, tool, topic)
    assert [a["entry_id"] for a in by_id(d)[orig["id"]]["answered_by"]] == [upd["id"]]

    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="original", supersedes_id=upd["id"])
    assert res.status_code == 400
    assert res.json()["detail"] == "An update keeps the kind of the message it updates"
    # giving the same kind is fine
    await ok(await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", supersedes_id=upd["id"]))


# ---- legacy and closed ------------------------------------------------------

async def test_legacy_rows_read_as_originals(client, eng_auth, seed, monkeypatch, tmp_path, session_factory):
    from app.models.dfm import DfmEntry
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    async with session_factory() as s:
        s.add(DfmEntry(topic_id=topic, party="ktx", addressed_to=["toolmaker"], note="old",
                       recorded_by=seed["engineer_id"], sent_at=date.today() - timedelta(days=2)))
        await s.commit()
    d = await detail(client, eng_auth, tool, topic)
    e = d["entries"][0]
    assert e["kind"] == "original" and e["reply_to_id"] is None
    assert e["awaiting"] == [{"party": "toolmaker", "days": 2}]
    assert d["all_answered"] is False


async def test_closed_topic_still_409(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    orig = await ok(await step(client, eng_auth, tool, topic, "toolmaker", ["ktx"]))
    assert (await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/close", headers=eng_auth)).status_code == 200
    res = await step(client, eng_auth, tool, topic, "ktx", ["toolmaker"], kind="answer", reply_to=orig["id"])
    assert res.status_code == 409


async def test_empty_topic_summary(client, eng_auth, seed, monkeypatch, tmp_path):
    tool, topic = await flow_topic(client, eng_auth, seed, monkeypatch, tmp_path)
    rows = (await client.get(f"/api/v1/parts/{tool}/dfm/topics", headers=eng_auth)).json()
    assert rows[0]["waiting_on"] == [] and rows[0]["last_step"] is None and rows[0]["all_answered"] is False
    d = await detail(client, eng_auth, tool, topic)
    assert d["next_step"] is None


def test_service_today_parameter():
    """Days are counted against the `today` the caller passes."""
    from datetime import datetime
    from types import SimpleNamespace
    from app.services.dfm_service import DfmService
    e = SimpleNamespace(id=1, topic_id=1, party="toolmaker", addressed_to=["ktx"], kind="original",
                        reply_to_id=None, supersedes_id=None, sent_at=date(2026, 9, 1),
                        recorded_at=datetime(2026, 9, 2, 8), note=None, recorded_by=1, files=[])
    topic = SimpleNamespace(id=1, tool_part_id=1, title="t", status="open", opened_by=1,
                            opened_at=datetime(2026, 9, 1), closed_by=None, closed_at=None, entries=[e])
    d = DfmService.topic_detail(topic, {}, today=date(2026, 9, 11))
    assert d["entries"][0]["awaiting"] == [{"party": "ktx", "days": 10}]
    assert DfmService.topic_summary(topic, today=date(2026, 9, 21))["waiting_on"] == [
        {"party": "ktx", "count": 1, "oldest_days": 20}]
