"""DFM audit trail: every change writes exactly one append-only event in the
same transaction, reads of files write a view/download event, the list and
CSV endpoints stay inside one tool, and migration 081 backfills old rows."""
import csv
import hashlib
import io
import json
from datetime import datetime

from sqlalchemy import select

from app.models.dfm import DfmAuditEvent, DfmEntry, DfmEntryFile, DfmTopic
from tests.test_dfm_entries import make_topic, post_entry
from tests.test_dfm_topics import make_tool


async def _events(session_factory, **where):
    async with session_factory() as s:
        q = select(DfmAuditEvent).order_by(DfmAuditEvent.id)
        for k, v in where.items():
            q = q.where(getattr(DfmAuditEvent, k) == v)
        return list((await s.execute(q)).scalars().all())


async def _audit(client, auth, tool, **params):
    res = await client.get(f"/api/v1/parts/{tool}/dfm/audit", params=params, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


# ---- writes -----------------------------------------------------------------

async def test_topic_open_close_reopen_write_one_event_each(client, eng_auth, seed, session_factory):
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool, title="Gate position")
    await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/close", headers=eng_auth)
    await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/reopen", headers=eng_auth)

    events = await _events(session_factory, tool_part_id=tool)
    assert [e.action for e in events] == ["topic_opened", "topic_closed", "topic_reopened"]
    for e in events:
        assert e.topic_id == topic
        assert e.entry_id is None and e.file_id is None
        assert e.actor_id == seed["engineer_id"]
        assert e.details == {"title": "Gate position"}
        assert isinstance(e.at, datetime)


async def test_failed_close_writes_nothing(client, eng_auth, seed, session_factory):
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/reopen", headers=eng_auth)
    assert res.status_code == 409
    assert [e.action for e in await _events(session_factory)] == ["topic_opened"]


async def test_entry_recorded_with_details(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    long_note = "x" * 300
    res = await post_entry(client, eng_auth, tool, topic, note=long_note)
    assert res.status_code == 201, res.text
    entry = res.json()

    events = await _events(session_factory, action="entry_recorded")
    assert len(events) == 1
    e = events[0]
    assert (e.tool_part_id, e.topic_id, e.entry_id, e.file_id) == (tool, topic, entry["id"], None)
    assert e.actor_id == seed["engineer_id"]
    assert e.details["kind"] == "original"
    assert e.details["party"] == "ktx"
    assert e.details["addressed_to"] == ["toolmaker", "tier1"]
    assert e.details["reply_to_id"] is None
    assert len(e.details["note"]) <= 120 and e.details["note"].startswith("xxx")


async def test_answer_entry_carries_reply_to(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    first = (await post_entry(client, eng_auth, tool, topic)).json()
    res = await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/entries", data={
        "party": "toolmaker", "addressed_to": json.dumps(["ktx"]), "kind": "answer",
        "reply_to_id": str(first["id"]), "note": "ok"}, headers=eng_auth)
    assert res.status_code == 201, res.text
    ev = (await _events(session_factory, entry_id=res.json()["id"]))[0]
    assert ev.action == "entry_recorded"
    assert ev.details["kind"] == "answer" and ev.details["reply_to_id"] == first["id"]


async def test_rejected_entries_write_no_event(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    res = await post_entry(client, eng_auth, tool, topic, party="nobody")
    assert res.status_code == 400
    await client.post(f"/api/v1/parts/{tool}/dfm/topics/{topic}/close", headers=eng_auth)
    res = await post_entry(client, eng_auth, tool, topic, files=[("a.pdf", b"%PDF a", "application/pdf")])
    assert res.status_code == 409
    assert [e.action for e in await _events(session_factory)] == ["topic_opened", "topic_closed"]


async def test_storage_failure_writes_no_event(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    import app.services.dfm_service as svc

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(svc.os, "makedirs", boom)
    res = await post_entry(client, eng_auth, tool, topic, files=[("a.pdf", b"%PDF a", "application/pdf")])
    assert res.status_code == 500
    assert [e.action for e in await _events(session_factory)] == ["topic_opened"]


async def test_supersede_writes_entry_updated(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    first = (await post_entry(client, eng_auth, tool, topic)).json()
    res = await post_entry(client, eng_auth, tool, topic, note="rev B", supersedes_id=first["id"])
    assert res.status_code == 201, res.text
    second = res.json()

    events = await _events(session_factory, entry_id=second["id"])
    assert [e.action for e in events] == ["entry_updated"]
    assert events[0].details["supersedes_id"] == first["id"]
    assert events[0].details["kind"] == "original"
    assert len(await _events(session_factory, action="entry_recorded")) == 1


async def test_file_attached_with_sha256(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    a, b = b"%PDF-1.4 a", b"PK volumes"
    res = await post_entry(client, eng_auth, tool, topic, files=[
        ("study.pdf", a, "application/pdf"), ("volumes.xlsx", b, None)])
    assert res.status_code == 201, res.text
    entry = res.json()

    async with session_factory() as s:
        rows = list((await s.execute(select(DfmEntryFile).order_by(DfmEntryFile.id))).scalars().all())
    assert [r.sha256 for r in rows] == [hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest()]

    events = await _events(session_factory, action="file_attached")
    assert [e.file_id for e in events] == [r.id for r in rows]
    for e, r in zip(events, rows):
        assert e.entry_id == entry["id"] and e.topic_id == topic and e.tool_part_id == tool
        assert e.details == {"filename": r.original_filename, "size": r.file_size,
                             "content_type": r.content_type, "sha256": r.sha256}


async def test_download_and_inline_write_events(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    entry = (await post_entry(client, eng_auth, tool, topic,
                              files=[("study.pdf", b"%PDF s", "application/pdf")])).json()
    fid = entry["files"][0]["id"]
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/download", headers=eng_auth)).status_code == 200
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/inline", headers=eng_auth)).status_code == 200

    for action in ("file_downloaded", "file_viewed"):
        events = await _events(session_factory, action=action)
        assert len(events) == 1, action
        e = events[0]
        assert (e.tool_part_id, e.topic_id, e.entry_id, e.file_id) == (tool, topic, entry["id"], fid)
        assert e.details == {"filename": "study.pdf"}


async def test_refused_reads_write_no_event(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    entry = (await post_entry(client, eng_auth, tool, topic, files=[("m.msg", b"mail", None)])).json()
    fid = entry["files"][0]["id"]
    other = await make_tool(client, eng_auth, seed, number="199404")
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/inline", headers=eng_auth)).status_code == 415
    assert (await client.get(f"/api/v1/parts/{other}/dfm/files/{fid}/download", headers=eng_auth)).status_code == 404
    assert await _events(session_factory, action="file_viewed") == []
    assert await _events(session_factory, action="file_downloaded") == []


async def test_reads_still_served_when_audit_fails(client, eng_auth, seed, session_factory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    entry = (await post_entry(client, eng_auth, tool, topic,
                              files=[("study.pdf", b"%PDF s", "application/pdf")])).json()
    fid = entry["files"][0]["id"]

    import app.services.dfm_audit as audit

    async def boom(*a, **k):
        raise RuntimeError("audit db down")
    monkeypatch.setattr(audit, "record_event", boom)

    res = await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/download", headers=eng_auth)
    assert res.status_code == 200 and res.content == b"%PDF s"
    res = await client.get(f"/api/v1/parts/{tool}/dfm/files/{fid}/inline", headers=eng_auth)
    assert res.status_code == 200 and res.content == b"%PDF s"
    assert await _events(session_factory, action="file_downloaded") == []


async def test_changelog_kept(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool)
    await post_entry(client, eng_auth, tool, topic)
    res = await client.get(f"/api/v1/parts/{tool}/changelog", headers=eng_auth)
    actions = {e["action"] for e in res.json()}
    assert {"dfm_topic_opened", "dfm_entry_recorded"} <= actions


# ---- read API ---------------------------------------------------------------

async def test_audit_list_shape_newest_first(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool, title="Gate position")
    entry = (await post_entry(client, eng_auth, tool, topic,
                              files=[("study.pdf", b"%PDF s", "application/pdf")])).json()

    events = await _audit(client, eng_auth, tool)
    assert [e["action"] for e in events] == ["file_attached", "entry_recorded", "topic_opened"]
    ids = [e["id"] for e in events]
    assert ids == sorted(ids, reverse=True)
    fa = events[0]
    assert fa["actor"] == {"id": seed["engineer_id"], "name": "Engineer"}
    assert fa["topic"] == {"id": topic, "title": "Gate position"}
    assert fa["entry"] == {"id": entry["id"], "kind": "original", "party": "ktx"}
    assert fa["file"] == {"id": entry["files"][0]["id"], "filename": "study.pdf"}
    assert fa["details"]["sha256"] == hashlib.sha256(b"%PDF s").hexdigest()
    assert fa["at"]
    opened = events[-1]
    assert opened["entry"] is None and opened["file"] is None


async def test_audit_filters_and_pagination(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    t1 = await make_topic(client, eng_auth, tool, title="One")
    t2 = await make_topic(client, eng_auth, tool, title="Two")
    for _ in range(3):
        await post_entry(client, eng_auth, tool, t1)

    only_t2 = await _audit(client, eng_auth, tool, topic_id=t2)
    assert [e["action"] for e in only_t2] == ["topic_opened"]
    assert await _audit(client, eng_auth, tool, action="topic_opened", topic_id=t1) != []
    recorded = await _audit(client, eng_auth, tool, action="entry_recorded")
    assert len(recorded) == 3 and all(e["action"] == "entry_recorded" for e in recorded)

    page1 = await _audit(client, eng_auth, tool, limit=2)
    page2 = await _audit(client, eng_auth, tool, limit=2, before_id=page1[-1]["id"])
    page3 = await _audit(client, eng_auth, tool, limit=2, before_id=page2[-1]["id"])
    all_ids = [e["id"] for e in await _audit(client, eng_auth, tool)]
    assert [e["id"] for e in page1 + page2 + page3] == all_ids
    assert len(all_ids) == 5 and len(page3) == 1

    bad = await client.get(f"/api/v1/parts/{tool}/dfm/audit", params={"action": "nope"}, headers=eng_auth)
    assert bad.status_code == 400
    bad = await client.get(f"/api/v1/parts/{tool}/dfm/audit", params={"limit": 0}, headers=eng_auth)
    assert bad.status_code == 422


async def test_audit_is_per_tool(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    a = await make_tool(client, eng_auth, seed)
    b = await make_tool(client, eng_auth, seed, number="199404")
    ta = await make_topic(client, eng_auth, a)
    tb = await make_topic(client, eng_auth, b)
    await post_entry(client, eng_auth, tool=b, topic=tb)

    events_a = await _audit(client, eng_auth, a)
    assert [e["topic"]["id"] for e in events_a] == [ta]
    res = await client.get(f"/api/v1/parts/{a}/dfm/audit", params={"topic_id": tb}, headers=eng_auth)
    assert res.status_code == 404
    res = await client.get(f"/api/v1/parts/{a}/dfm/audit.csv", params={"topic_id": tb}, headers=eng_auth)
    assert res.status_code == 404


async def test_audit_needs_tool_and_auth(client, eng_auth, seed):
    part = await make_tool(client, eng_auth, seed, number="199405", item_category="article")
    assert (await client.get(f"/api/v1/parts/{part}/dfm/audit", headers=eng_auth)).status_code == 400
    assert (await client.get(f"/api/v1/parts/{part}/dfm/audit.csv", headers=eng_auth)).status_code == 400
    assert (await client.get("/api/v1/parts/999999/dfm/audit", headers=eng_auth)).status_code == 404
    tool = await make_tool(client, eng_auth, seed)
    assert (await client.get(f"/api/v1/parts/{tool}/dfm/audit")).status_code == 401


async def test_no_write_routes_for_audit(client, eng_auth, seed):
    tool = await make_tool(client, eng_auth, seed)
    await make_topic(client, eng_auth, tool)
    ev = (await _audit(client, eng_auth, tool))[0]
    for method in ("post", "put", "patch", "delete"):
        res = await getattr(client, method)(f"/api/v1/parts/{tool}/dfm/audit", headers=eng_auth)
        assert res.status_code == 405, method
        res = await getattr(client, method)(f"/api/v1/parts/{tool}/dfm/audit/{ev['id']}", headers=eng_auth)
        assert res.status_code in (404, 405), method


async def test_audit_csv(client, eng_auth, seed, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tool = await make_tool(client, eng_auth, seed)
    topic = await make_topic(client, eng_auth, tool, title="Gate, position")
    other = await make_topic(client, eng_auth, tool, title="Other")
    await post_entry(client, eng_auth, tool, topic, files=[("Über.pdf", b"%PDF u", "application/pdf")])

    res = await client.get(f"/api/v1/parts/{tool}/dfm/audit.csv", headers=eng_auth)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="dfm-audit-199403.csv"' in res.headers["content-disposition"]
    assert res.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0] == ["at", "actor", "action", "topic", "entry", "file", "details"]
    assert [r[2] for r in rows[1:]] == ["file_attached", "entry_recorded", "topic_opened", "topic_opened"]
    fa = rows[1]
    assert fa[1] == "Engineer"
    assert datetime.fromisoformat(fa[0])
    assert "Gate, position" in fa[3]
    assert "Über.pdf" in fa[5]
    assert "sha256=" in fa[6]

    res = await client.get(f"/api/v1/parts/{tool}/dfm/audit.csv", params={"topic_id": other}, headers=eng_auth)
    assert f'filename="dfm-audit-199403-topic-{other}.csv"' in res.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(res.content.decode("utf-8-sig"))))
    assert [r[2] for r in rows[1:]] == ["topic_opened"]


# ---- backfill (migration 081 data step) ----------------------------------------

async def test_backfill_from_existing_rows(db_engine, session_factory, seed, client, eng_auth):
    from app.services.dfm_audit_backfill import backfill_dfm_audit

    tool = await make_tool(client, eng_auth, seed)
    eng = seed["engineer_id"]
    admin = seed["admin_id"]
    async with session_factory() as s:
        t1 = DfmTopic(tool_part_id=tool, title="Old", opened_by=eng, opened_at=datetime(2025, 1, 1, 8))
        t2 = DfmTopic(tool_part_id=tool, title="Done", opened_by=eng, opened_at=datetime(2025, 1, 2, 8),
                      status="finished_confirmed", closed_by=admin, closed_at=datetime(2025, 3, 1, 8))
        s.add_all([t1, t2])
        await s.flush()
        e1 = DfmEntry(topic_id=t1.id, party="ktx", addressed_to=["toolmaker"], note="n" * 200,
                      recorded_by=eng, recorded_at=datetime(2025, 1, 1, 9))
        s.add(e1)
        await s.flush()
        e2 = DfmEntry(topic_id=t1.id, party="toolmaker", addressed_to=["ktx"], kind="answer",
                      reply_to_id=e1.id, recorded_by=admin, recorded_at=datetime(2025, 1, 5, 9))
        e3 = DfmEntry(topic_id=t1.id, party="ktx", addressed_to=["toolmaker"], supersedes_id=e1.id,
                      recorded_by=eng, recorded_at=datetime(2025, 1, 3, 9))
        s.add_all([e2, e3])
        await s.flush()
        f1 = DfmEntryFile(entry_id=e1.id, original_filename="a.pdf", saved_filename="x.pdf", file_size=10,
                          content_type="application/pdf", uploaded_by=eng, uploaded_at=datetime(2025, 1, 1, 9))
        s.add(f1)
        await s.commit()
        ids = {"t1": t1.id, "t2": t2.id, "e1": e1.id, "e2": e2.id, "e3": e3.id, "f1": f1.id}

    async with db_engine.begin() as conn:
        n = await conn.run_sync(backfill_dfm_audit)
    assert n == 7

    events = await _events(session_factory)
    assert [e.action for e in events] == [
        "topic_opened", "entry_recorded", "file_attached", "topic_opened", "entry_updated", "entry_recorded",
        "topic_closed"]
    ats = [e.at for e in events]
    assert ats == sorted(ats)
    assert all(e.tool_part_id == tool and e.details.get("backfilled") is True for e in events)
    by = {(e.action, e.entry_id or e.topic_id): e for e in events}

    closed = by[("topic_closed", ids["t2"])]
    assert closed.actor_id == admin and closed.at == datetime(2025, 3, 1, 8)
    assert closed.details["title"] == "Done"
    rec = by[("entry_recorded", ids["e1"])]
    assert rec.topic_id == ids["t1"] and rec.actor_id == eng
    assert rec.details["kind"] == "original" and rec.details["party"] == "ktx"
    assert rec.details["addressed_to"] == ["toolmaker"] and len(rec.details["note"]) <= 120
    ans = by[("entry_recorded", ids["e2"])]
    assert ans.details["reply_to_id"] == ids["e1"] and ans.actor_id == admin
    upd = by[("entry_updated", ids["e3"])]
    assert upd.details["supersedes_id"] == ids["e1"]
    fa = [e for e in events if e.action == "file_attached"][0]
    assert (fa.file_id, fa.entry_id, fa.topic_id) == (ids["f1"], ids["e1"], ids["t1"])
    assert fa.details == {"filename": "a.pdf", "size": 10, "content_type": "application/pdf",
                          "sha256": None, "backfilled": True}

    # idempotent: a second run does nothing once events exist
    async with db_engine.begin() as conn:
        assert await conn.run_sync(backfill_dfm_audit) == 0
    assert len(await _events(session_factory)) == 7
