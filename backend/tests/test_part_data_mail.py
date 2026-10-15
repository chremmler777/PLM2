"""Part data mail: outbox enqueue from the changelog, the per-project digest,
trial mode, missing Graph config, address validation, the endpoints' rights."""
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import get_settings
from app.models.entities import AuditLog, Project
from app.models.mail import MailOutbox, MailRecipient
from app.models.part import Part, PartRelation, PartRevision
from app.models.workflow import Department, UserDepartment
from app.services import part_data_mail
from app.services.part_service import ChangelogService, RevisionService
from tests.conftest import login

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mail_env(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "entra_tenant_id", "tenant")
    monkeypatch.setattr(s, "entra_client_id", "client")
    monkeypatch.setattr(s, "entra_client_secret", "secret")
    monkeypatch.setattr(s, "notify_trial_recipient", "")
    monkeypatch.setattr(s, "notify_base_url", "https://apps.ad.us.ktx.group/plm2")
    monkeypatch.setattr(s, "notify_digest_minutes", 5)
    monkeypatch.setattr(part_data_mail, "_token", None)
    return s


@pytest.fixture
def graph(monkeypatch):
    """Mock Microsoft Graph at the httpx transport; records each sendMail."""
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "login.microsoftonline.com" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        import json
        sent.append({"url": str(request.url), "json": json.loads(request.content)})
        return httpx.Response(202)

    real = httpx.AsyncClient

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(part_data_mail.httpx, "AsyncClient", client)
    return sent


@pytest_asyncio.fixture
async def world(session_factory, seed):
    """Project 1994 with two articles (each made by a tool), E1 on each."""
    async with session_factory() as s:
        project = await s.get(Project, seed["project_id"])
        project.code, project.name = "1994", "Brose Seat Trim"
        uid = seed["admin_id"]
        a1 = Part(project_id=project.id, part_number="199401-A", customer_part_number="206.881.799",
                  tier1_part_number="S00HP8-110", name="206.881.799 A-Bracket Outer COVER",
                  part_type="internal_mfg", item_category="article", created_by=uid)
        a2 = Part(project_id=project.id, part_number="199402-A", customer_part_number="206.881.800",
                  tier1_part_number=None, name="A-Bracket Inner Cover",
                  part_type="internal_mfg", item_category="article", created_by=uid)
        t1 = Part(project_id=project.id, part_number="199401", name="Tool outer",
                  part_type="internal_mfg", item_category="tool", created_by=uid)
        s.add_all([a1, a2, t1])
        await s.flush()
        s.add(PartRelation(from_part_id=t1.id, to_part_id=a1.id, relation_type="produces", created_by=uid))
        revs = {}
        for p in (a1, a2):
            r = PartRevision(part_id=p.id, revision_name="E1", phase="review", status="approved",
                             source="customer", created_by=uid)
            s.add(r)
            await s.flush()
            revs[p.id] = r.id
        await s.commit()
        return {"project_id": project.id, "a1": a1.id, "a2": a2.id, "tool": t1.id,
                "e1": revs, "uid": uid}


async def _add_list(session_factory, project_id, emails=("a.b@us.ktx.group",), active=True):
    async with session_factory() as s:
        for e in emails:
            s.add(MailRecipient(project_id=project_id, list_key="part_data", email=e,
                                display_name=e.split("@")[0], active=active))
        await s.commit()


async def _outbox(session_factory):
    async with session_factory() as s:
        return list((await s.execute(select(MailOutbox).order_by(MailOutbox.id))).scalars())


# ---------------------------------------------------------------- enqueue

async def test_no_list_enqueues_nothing(session_factory, world):
    async with session_factory() as s:
        await RevisionService.create_proposal(s, world["a1"], world["e1"][world["a1"]],
                                              created_by=world["uid"])
        await s.commit()
    assert await _outbox(session_factory) == []


async def test_inactive_list_enqueues_nothing(session_factory, world):
    await _add_list(session_factory, world["project_id"], active=False)
    async with session_factory() as s:
        await RevisionService.create_proposal(s, world["a1"], world["e1"][world["a1"]],
                                              created_by=world["uid"])
        await s.commit()
    assert await _outbox(session_factory) == []


async def test_included_actions_enqueue_in_same_session(session_factory, world):
    await _add_list(session_factory, world["project_id"])
    async with session_factory() as s:
        e11 = await RevisionService.create_proposal(s, world["a1"], world["e1"][world["a1"]],
                                                    created_by=world["uid"])
        await ChangelogService.log_action(s, part_id=world["a1"], revision_id=e11.id,
                                          action="file_uploaded", action_description="Uploaded cad",
                                          performed_by=world["uid"])
        await ChangelogService.log_action(s, part_id=world["a1"], revision_id=e11.id,
                                          action="rejected", action_description="Rejected E1.1",
                                          performed_by=world["uid"])
        await ChangelogService.log_action(s, part_id=world["a1"], action="lifecycle_phase",
                                          action_description="rfq to nominated", performed_by=world["uid"])
        await s.rollback()        # a rolled back change never mails
    assert await _outbox(session_factory) == []
    async with session_factory() as s:
        e11 = await RevisionService.create_proposal(s, world["a1"], world["e1"][world["a1"]],
                                                    created_by=world["uid"])
        await ChangelogService.log_action(s, part_id=world["a1"], revision_id=e11.id,
                                          action="file_uploaded", action_description="Uploaded cad",
                                          performed_by=world["uid"])
        await s.commit()
    rows = await _outbox(session_factory)
    assert [(r.event, r.mail_status, r.part_id, r.project_id, r.performed_by) for r in rows] == [
        ("created", "pending", world["a1"], world["project_id"], world["uid"]),
        ("file_uploaded", "pending", world["a1"], world["project_id"], world["uid"]),
    ]
    assert rows[0].summary == "Created E1.1 as proposal to E1"


@pytest.mark.parametrize("action", ["thumbnail_updated", "bom_item_added", "field_comment_added",
                                    "material_refreshed", "paint_updated", "field_flag_set",
                                    "package_unchanged", "ppap_created", "file_deleted"])
async def test_excluded_actions_enqueue_nothing(session_factory, world, action):
    await _add_list(session_factory, world["project_id"])
    async with session_factory() as s:
        await ChangelogService.log_action(s, part_id=world["a1"], revision_id=world["e1"][world["a1"]],
                                          action=action, action_description="x", performed_by=world["uid"])
        await s.commit()
    assert await _outbox(session_factory) == []


async def test_metadata_updated_only_on_brand_new_iteration(session_factory, world):
    await _add_list(session_factory, world["project_id"])
    async with session_factory() as s:
        # on a customer major (no parent): noise
        await ChangelogService.log_action(s, part_id=world["a1"], revision_id=world["e1"][world["a1"]],
                                          action="metadata_updated", action_description="E1 field",
                                          performed_by=world["uid"])
        # on the part, no revision: noise
        await ChangelogService.log_action(s, part_id=world["a1"], action="metadata_updated",
                                          action_description="Tier 1 number", performed_by=world["uid"])
        e11 = await RevisionService.create_proposal(s, world["a2"], world["e1"][world["a2"]],
                                                    created_by=world["uid"])
        await ChangelogService.log_action(s, part_id=world["a2"], revision_id=e11.id,
                                          action="metadata_updated", action_description="E1.1 opened",
                                          performed_by=world["uid"])
        old = await RevisionService.create_proposal(s, world["a1"], world["e1"][world["a1"]],
                                                    created_by=world["uid"])
        old.created_at = datetime.utcnow() - timedelta(days=2)
        await s.flush()
        await ChangelogService.log_action(s, part_id=world["a1"], revision_id=old.id,
                                          action="metadata_updated", action_description="later edit",
                                          performed_by=world["uid"])
        await s.commit()
    got = [(r.event, r.summary) for r in await _outbox(session_factory)]
    assert ("metadata_updated", "E1.1 opened") in got
    assert all(summary not in ("E1 field", "Tier 1 number", "later edit") for _, summary in got)


# ---------------------------------------------------------------- digest

async def _two_part_updates(session_factory, world, age_min=6):
    async with session_factory() as s:
        for pid in (world["a1"], world["a2"]):
            await RevisionService.create_proposal(s, pid, world["e1"][pid], created_by=world["uid"])
        await s.commit()
        for r in (await s.execute(select(MailOutbox))).scalars():
            r.created_at = datetime.utcnow() - timedelta(minutes=age_min)
        await s.commit()


async def test_digest_waits_for_the_oldest_row(session_factory, world, mail_env, graph):
    await _add_list(session_factory, world["project_id"])
    await _two_part_updates(session_factory, world, age_min=2)
    assert await part_data_mail.run_digest(session_factory) == {}
    assert graph == []
    assert {r.mail_status for r in await _outbox(session_factory)} == {"pending"}


async def test_two_parts_one_mail(session_factory, world, mail_env, graph):
    await _add_list(session_factory, world["project_id"], ("a.b@us.ktx.group", "c.d@us.ktx.group"))
    await _two_part_updates(session_factory, world)
    assert await part_data_mail.run_digest(session_factory) == {world["project_id"]: "sent"}
    assert len(graph) == 1
    msg = graph[0]["json"]["message"]
    assert graph[0]["url"].endswith("/users/apps-noreply@us.ktx.group/sendMail")
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == [
        "a.b@us.ktx.group", "c.d@us.ktx.group"]
    assert msg["subject"] == "PLM2 1994 Brose Seat Trim: 2 new iterations"
    body = msg["body"]["content"]
    assert msg["body"]["contentType"] == "Text"
    # customer identity first, duplicate number stripped from the name, KTX tool after
    assert ("206.881.799 / S00HP8-110 A-Bracket Outer COVER (KTX 199401) — E1.1 draft: "
            "Created E1.1 as proposal to E1") in body
    assert "206.881.800 A-Bracket Inner Cover (KTX 199402-A) — E1.1 draft" in body
    assert f"https://apps.ad.us.ktx.group/plm2/parts/{world['a1']}" in body
    assert "Admin, " in body and " ET" in body
    assert body.rstrip().endswith("You get this as a member of the 1994 Brose Seat Trim part data list.")
    rows = await _outbox(session_factory)
    assert {r.mail_status for r in rows} == {"sent"} and all(r.sent_at for r in rows)
    # a second run sends nothing
    assert await part_data_mail.run_digest(session_factory) == {}
    assert len(graph) == 1
    async with session_factory() as s:
        audit = (await s.execute(select(AuditLog).where(
            AuditLog.action == "part_data_mail.sent"))).scalars().all()
    assert len(audit) == 1 and audit[0].entity_id == world["project_id"]


async def test_trial_mode_reroutes(session_factory, world, mail_env, graph, monkeypatch):
    monkeypatch.setattr(mail_env, "notify_trial_recipient", "christoph.demmler@us.ktx.group")
    await _add_list(session_factory, world["project_id"], ("a.b@us.ktx.group", "c.d@us.ktx.group"))
    await _two_part_updates(session_factory, world)
    await part_data_mail.run_digest(session_factory)
    msg = graph[0]["json"]["message"]
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == ["christoph.demmler@us.ktx.group"]
    assert msg["subject"].startswith("[TRIAL] PLM2 1994")
    assert msg["body"]["content"].startswith("Would have gone to: a.b@us.ktx.group, c.d@us.ktx.group\n\n")


async def test_missing_entra_marks_skipped(session_factory, world, mail_env, graph, monkeypatch):
    monkeypatch.setattr(mail_env, "entra_client_secret", "")
    await _add_list(session_factory, world["project_id"])
    await _two_part_updates(session_factory, world)
    assert await part_data_mail.run_digest(session_factory) == {world["project_id"]: "skipped"}
    assert graph == []
    rows = await _outbox(session_factory)
    assert {r.mail_status for r in rows} == {"skipped"} and "ENTRA" in rows[0].error


async def test_list_emptied_after_enqueue_marks_skipped(session_factory, world, mail_env, graph):
    await _add_list(session_factory, world["project_id"])
    await _two_part_updates(session_factory, world)
    async with session_factory() as s:
        for r in (await s.execute(select(MailRecipient))).scalars():
            r.active = False
        await s.commit()
    assert await part_data_mail.run_digest(session_factory) == {world["project_id"]: "skipped"}
    assert graph == []


async def test_graph_failure_marks_failed_and_audits(session_factory, world, mail_env, monkeypatch):
    async def boom(*a, **kw):
        raise httpx.ReadTimeout("")
    monkeypatch.setattr(part_data_mail, "graph_send", boom)
    await _add_list(session_factory, world["project_id"])
    await _two_part_updates(session_factory, world)
    assert await part_data_mail.run_digest(session_factory) == {world["project_id"]: "failed"}
    rows = await _outbox(session_factory)
    assert {r.mail_status for r in rows} == {"failed"} and rows[0].error == "ReadTimeout"
    async with session_factory() as s:
        assert (await s.execute(select(AuditLog).where(
            AuditLog.action == "part_data_mail.failed"))).scalars().first() is not None


async def test_claimed_rows_are_not_sent_twice(session_factory, world, mail_env, graph):
    await _add_list(session_factory, world["project_id"])
    await _two_part_updates(session_factory, world)
    ids = await part_data_mail._claim(session_factory, world["project_id"])
    assert len(ids) == 2
    assert await part_data_mail._claim(session_factory, world["project_id"]) == []
    assert await part_data_mail.send_project(session_factory, world["project_id"]) is None


# ---------------------------------------------------------------- addresses

@pytest.mark.parametrize("raw,clean,ok", [
    ("Cody Hrtyanski <Cody.Hrtyanski@us.ktx.group>;", "cody.hrtyanski@us.ktx.group", True),
    ("mailto:dale.perry@us.ktx.group", "dale.perry@us.ktx.group", True),
    ("russ.addison@us.ktx.group​", "russ.addison@us.ktx.group", True),
    ("jürgen@us.ktx.group", "jürgen@us.ktx.group", False),
    ("not an address", "not an address", False),
    ("a@b", "a@b", False),
])
async def test_address_validation(raw, clean, ok):
    assert part_data_mail.clean_address(raw) == clean
    assert part_data_mail.valid_address(clean) is ok


# ---------------------------------------------------------------- endpoints

@pytest_asyncio.fixture
async def pm_auth(client, session_factory, seed):
    async with session_factory() as s:
        d = Department(name="Project Manager", flow_type="action", is_active=True, sort_order=0)
        s.add(d)
        await s.flush()
        s.add(UserDepartment(user_id=seed["engineer_id"], department_id=d.id))
        await s.commit()
    return await login(client, "eng@test.io")


async def test_endpoints_refuse_non_pm(client, seed):
    eng = await login(client, "eng@test.io")
    pid = seed["project_id"]
    assert (await client.get(f"/api/v1/projects/{pid}/mail-recipients", headers=eng)).status_code == 403
    assert (await client.post(f"/api/v1/projects/{pid}/mail-recipients", headers=eng,
                              json={"email": "a.b@us.ktx.group"})).status_code == 403
    assert (await client.get("/api/v1/notifications/mail-status", headers=eng)).status_code == 403
    assert (await client.post("/api/v1/notifications/mail-test", headers=eng)).status_code == 403


async def test_pm_keeps_the_list(client, seed, pm_auth, session_factory):
    pid = seed["project_id"]
    url = f"/api/v1/projects/{pid}/mail-recipients"
    r = await client.post(url, headers=pm_auth,
                          json={"email": "Dale Perry <Dale.Perry@us.ktx.group>", "display_name": "Dale Perry"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["email"] == "dale.perry@us.ktx.group"
    assert (await client.post(url, headers=pm_auth, json={"email": "dale.perry@us.ktx.group"})).status_code == 409
    assert (await client.post(url, headers=pm_auth, json={"email": "nope"})).status_code == 422
    rows = (await client.get(url, headers=pm_auth)).json()
    assert [x["email"] for x in rows] == ["dale.perry@us.ktx.group"]
    assert (await client.delete(f"{url}/{rid}", headers=pm_auth)).status_code == 204
    assert (await client.get(url, headers=pm_auth)).json() == []
    assert (await client.delete(f"{url}/{rid}", headers=pm_auth)).status_code == 404
    async with session_factory() as s:
        actions = [a for (a,) in (await s.execute(select(AuditLog.action).where(
            AuditLog.entity_type == "project")))]
    assert actions == ["mail_recipient.added", "mail_recipient.removed"]


async def test_admin_status_and_test_mail_goes_only_to_self(client, seed, mail_env, graph, monkeypatch):
    monkeypatch.setattr(mail_env, "notify_trial_recipient", "someone.else@us.ktx.group")
    admin = await login(client, "admin@test.io")
    st = (await client.get("/api/v1/notifications/mail-status", headers=admin)).json()
    assert st == {"configured": True, "trial_recipient": "someone.else@us.ktx.group",
                  "sender": "apps-noreply@us.ktx.group", "digest_minutes": 5}
    r = await client.post("/api/v1/notifications/mail-test", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"sent_to": "admin@test.io"}
    assert [x["emailAddress"]["address"] for x in graph[0]["json"]["message"]["toRecipients"]] == ["admin@test.io"]


async def test_test_mail_unconfigured_is_503(client, seed, mail_env, monkeypatch):
    monkeypatch.setattr(mail_env, "entra_tenant_id", "")
    admin = await login(client, "admin@test.io")
    assert (await client.post("/api/v1/notifications/mail-test", headers=admin)).status_code == 503


# ---------------------------------------------------------------- seed script

async def test_seed_script_is_idempotent_and_backfills(session_factory, world):
    from scripts import seed_1994_part_data_mail as seed_mod
    async with session_factory() as s:
        e11s = []
        for pid in (world["a1"], world["a2"]):
            r = PartRevision(part_id=pid, revision_name="E1.1", phase="review", status="draft",
                             parent_revision_id=world["e1"][pid], source="internal", created_by=world["uid"])
            s.add(r)
            await s.flush()
            e11s.append(r.id)
        await s.commit()
    seed_mod.BACKFILL_REVISIONS = tuple(e11s)
    try:
        async with session_factory() as s:
            out = await seed_mod.seed(s, "1994", True, None)
            await s.commit()
        assert sum(line.startswith("   +") for line in out) == 8 + 2
        async with session_factory() as s:
            out = await seed_mod.seed(s, "1994", True, None)
            await s.commit()
        assert not any(line.startswith("   +") for line in out)
    finally:
        seed_mod.BACKFILL_REVISIONS = (2248, 2249, 2250, 2251)
    async with session_factory() as s:
        emails = list((await s.execute(select(MailRecipient.email))).scalars())
    assert len(emails) == 8 and "christoph.demmler@us.ktx.group" in emails
    rows = await _outbox(session_factory)
    assert len(rows) == 2 and {r.event for r in rows} == {"created"}
    assert rows[0].summary.startswith("E1.1 toolmaker data (FZ, per DFM) sent to Brose")
