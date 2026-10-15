"""ECR-solid spec §0 Notifications: one mail per item, ending
"Answer in PLM2: <link>". The mail follows the in-app notification (which is
already one per item and involved people only); it goes out only while SMTP
is enabled, at most once per notification.
Negative: SMTP off sends nothing; an old backlog, a notification already
read in PLM2, or a user without an e-mail address gets no mail."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.notification import Notification
from app.services import mail_outbox
from app.services.notification_service import NotificationService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def smtp_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_enabled", True)
    monkeypatch.setattr(s, "plm2_public_url", "https://plm.example/plm2/")
    sent = []
    return sent


async def test_one_mail_per_item_ending_with_the_plm2_link(session_factory, seed, smtp_on):
    sent = smtp_on
    async with session_factory() as s:
        for _ in range(2):    # the same item twice: one notification, one mail
            await NotificationService.notify_once(
                s, [seed["engineer_id"]], kind="deviation_pending", subject_key="dev:5",
                title="Decision needed: GB-CM-0005", body="Sally asks for an override.",
                link="/changes/5")
        await s.commit()
        assert await mail_outbox.send_pending(s, sender=sent.append) == 1
        assert await mail_outbox.send_pending(s, sender=sent.append) == 0
    assert len(sent) == 1
    msg = sent[0]
    assert msg["To"] == "eng@test.io"
    assert msg["Subject"] == "Decision needed: GB-CM-0005"
    body = msg.get_content().rstrip()
    assert body.startswith("Sally asks for an override.")
    assert body.endswith("Answer in PLM2: https://plm.example/plm2/changes/5")


async def test_no_link_points_at_my_tasks(session_factory, seed, smtp_on):
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "Hello")
        await s.commit()
        await mail_outbox.send_pending(s, sender=smtp_on.append)
    assert smtp_on[0].get_content().rstrip().endswith(
        "Answer in PLM2: https://plm.example/plm2/my-tasks")


async def test_smtp_off_sends_nothing(session_factory, seed):
    sent = []
    async with session_factory() as s:
        await NotificationService.notify_users(s, [seed["engineer_id"]], "x", link="/x")
        await s.commit()
        assert await mail_outbox.send_pending(s, sender=sent.append) == 0
        n = (await s.execute(select(Notification))).scalar_one()
        assert n.mailed_at is None       # it may still go once SMTP is on
    assert sent == []


async def test_backlog_read_and_addressless_are_skipped(session_factory, seed, smtp_on):
    from app.models.entities import User
    async with session_factory() as s:
        ghost = await s.get(User, seed["inactive_id"])
        ghost.email = ""
        s.add_all([
            Notification(user_id=seed["engineer_id"], title="old",
                         created_at=datetime.utcnow() - timedelta(days=3)),
            Notification(user_id=seed["engineer_id"], title="read", is_read=True),
            Notification(user_id=seed["inactive_id"], title="no address"),
        ])
        await s.commit()
        assert await mail_outbox.send_pending(s, sender=smtp_on.append) == 0
        rows = (await s.execute(select(Notification))).scalars().all()
        assert all(r.mailed_at is not None for r in rows)   # never retried
    assert smtp_on == []


async def test_plm2_link_falls_back_to_frontend_url(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "plm2_public_url", "")
    monkeypatch.setattr(s, "frontend_url", "https://ktx.example")
    assert mail_outbox.plm2_url("/changes/3") == "https://ktx.example/plm2/changes/3"
