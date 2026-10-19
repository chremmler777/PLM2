"""ECR-solid spec §0 Notifications: one mail per item, ending
"Answer in PLM2: <link>". The mail follows the in-app notification (which is
already one per item and involved people only); it goes out only while
ECR_MAIL_ENABLED and Graph is configured, at most once per notification,
through the part data mail's Graph transport (trial mode applies).
Negative: switched off or Graph not configured sends nothing and stamps
nothing; an old backlog, a notification already read in PLM2, or a user
without an e-mail address gets no mail; Graph refusing our app stops the
run."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.notification import Notification
from app.services import ecr_mail, part_data_mail
from app.services.notification_service import NotificationService

pytestmark = pytest.mark.asyncio


def switch_on(monkeypatch, *, graph: bool = True):
    """ECR_MAIL_ENABLED on; Graph configured unless graph=False."""
    s = get_settings()
    monkeypatch.setattr(s, "ecr_mail_enabled", True)
    for key in ("entra_tenant_id", "entra_client_id", "entra_client_secret"):
        monkeypatch.setattr(s, key, "x" if graph else "")
    monkeypatch.setattr(s, "notify_trial_recipient", "")


@pytest.fixture
def smtp_on(monkeypatch):
    switch_on(monkeypatch)
    monkeypatch.setattr(get_settings(), "notify_base_url", "https://plm.example/plm2/")
    return []


async def test_one_mail_per_item_ending_with_the_plm2_link(session_factory, seed, smtp_on):
    sent = smtp_on
    async with session_factory() as s:
        for _ in range(2):    # the same item twice: one notification, one mail
            await NotificationService.notify_once(
                s, [seed["engineer_id"]], kind="deviation_pending", subject_key="dev:5",
                title="Decision needed: GB-CM-0005", body="Sally asks for an override.",
                link="/changes/5")
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=sent.append) == 1
        assert await ecr_mail.send_pending(s, sender=sent.append) == 0
    assert len(sent) == 1
    msg = sent[0]
    assert msg.to == ["eng@test.io"]
    assert msg.subject == "Decision needed: GB-CM-0005"
    body = msg.body.rstrip()
    assert body.startswith("Sally asks for an override.")
    assert body.endswith("Answer in PLM2: https://plm.example/plm2/changes/5")


async def test_no_link_points_at_my_tasks(session_factory, seed, smtp_on):
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "Hello",
                                               kind="task_assigned")
        await s.commit()
        await ecr_mail.send_pending(s, sender=smtp_on.append)
    assert smtp_on[0].body.rstrip().endswith(
        "Answer in PLM2: https://plm.example/plm2/my-tasks")


async def test_the_default_sender_is_the_graph_transport_with_trial(
        session_factory, seed, smtp_on, monkeypatch):
    calls = []

    async def fake_graph_send(to, subject, body):
        calls.append((to, subject, body))
    monkeypatch.setattr(part_data_mail, "graph_send", fake_graph_send)
    monkeypatch.setattr(get_settings(), "notify_trial_recipient", "trial@ktx.example")
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "Hello",
                                               kind="task_assigned")
        await s.commit()
        assert await ecr_mail.send_pending(s) == 1
    [(to, subject, body)] = calls
    assert to == ["trial@ktx.example"]
    assert subject == "[TRIAL] Hello"
    assert body.startswith("Would have gone to: eng@test.io")


@pytest.mark.parametrize("on, graph", [(False, True), (True, False)])
async def test_switched_off_or_graph_missing_sends_nothing(
        session_factory, seed, monkeypatch, on, graph):
    switch_on(monkeypatch, graph=graph)
    monkeypatch.setattr(get_settings(), "ecr_mail_enabled", on)
    sent = []
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "x", link="/x",
                                               kind="task_assigned")
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=sent.append) == 0
        n = (await s.execute(select(Notification))).scalar_one()
        assert n.mailed_at is None       # it may still go once mail is on
    assert sent == []


async def test_graph_refusing_our_app_stops_the_run(session_factory, seed, smtp_on):
    def unauthorized(msg):
        raise RuntimeError("Graph sendMail 401: InvalidAuthenticationToken")
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "x",
                                               kind="task_assigned")
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=unauthorized) == 0
        n = (await s.execute(select(Notification))).scalar_one()
        assert n.mailed_at is None       # tried again next run


async def test_backlog_read_and_addressless_are_skipped(session_factory, seed, smtp_on):
    from app.models.entities import User
    async with session_factory() as s:
        ghost = await s.get(User, seed["inactive_id"])
        ghost.email = ""
        s.add_all([
            Notification(user_id=seed["engineer_id"], title="old", kind="task_assigned",
                         created_at=datetime.utcnow() - timedelta(days=3)),
            Notification(user_id=seed["engineer_id"], title="read", kind="task_assigned",
                         is_read=True),
            Notification(user_id=seed["inactive_id"], title="no address", kind="task_assigned"),
        ])
        await s.commit()
        assert await ecr_mail.send_pending(s, sender=smtp_on.append) == 0
        rows = (await s.execute(select(Notification))).scalars().all()
        assert all(r.mailed_at is not None for r in rows)   # never retried
    assert smtp_on == []


async def test_an_invalid_address_is_no_address():
    assert ecr_mail.address("Sam <sam@ktx.example>;") == "sam@ktx.example"
    assert ecr_mail.address("not an address@") is None


async def test_plm2_link_is_on_the_mail_link_base(monkeypatch):
    monkeypatch.setattr(get_settings(), "notify_base_url", "https://ktx.example/plm2")
    assert ecr_mail.plm2_url("/changes/3") == "https://ktx.example/plm2/changes/3"
    assert ecr_mail.plm2_url("changes/3") == "https://ktx.example/plm2/changes/3"
