"""Mail for notifications (ECR-solid spec §0 Notifications).

PLM2's notice channel is the in-app notification: one per item and person
(NotificationService.notify_once), involved people only. This sends each new
notification once as a plain-text mail ending "Answer in PLM2: <link>", so
the answer is given in PLM2, never by reply (reply-to auto-answer and
30-minute batching: cut 2).

Only the immediate class is mailed (spec §0 Notifications): a task newly
yours, a decision needed, an escalation to acknowledge, and the daily digest
(MAIL_KINDS; kind-less notices are the older direct task and assignment
notices). "Everything else is a badge": due reminders, late notices,
deadline alerts, FYI and stage-entry notices, decisions told back, and a
backup's info copy are stamped and never mailed.

Off unless settings.smtp_enabled. A notification goes out at most once
(notifications.mailed_at); one already read in PLM2, older than MAX_AGE (a
backlog from before SMTP was switched on) or for a user without an active
account and address is stamped and skipped, never retried."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import User
from app.models.notification import Notification

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(hours=24)
#: The kinds that are mailed; None = a kind-less direct notice.
MAIL_KINDS = frozenset({
    None, "task_assigned", "deviation_pending", "routing_deviation_pending",
    "revision_intake", "change_review", "change_info_sent",
    "routing_late_assessment", "validation_issue_escalated", "overdue_digest",
})


def mailable(n: Notification) -> bool:
    """Immediate class only; a backup's info copy is a badge."""
    from app.services.notification_service import BACKUP_NOTE_PREFIX
    return n.kind in MAIL_KINDS and BACKUP_NOTE_PREFIX not in (n.body or "")
BATCH = 200
FOOTER = "Answer in PLM2: {url}"


def plm2_url(link: Optional[str]) -> str:
    """Absolute PLM2 URL of a frontend path ("/changes/5"); My Tasks when
    the notification names no page."""
    s = get_settings()
    base = (s.plm2_public_url or f"{s.frontend_url.rstrip('/')}/plm2").rstrip("/")
    path = link or "/my-tasks"
    return f"{base}{path if path.startswith('/') else '/' + path}"


def compose(n: Notification, to: str) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from_email
    msg["To"] = to
    msg["Subject"] = n.title
    text = (n.body or "").rstrip()
    footer = FOOTER.format(url=plm2_url(n.link))
    msg.set_content(f"{text}\n\n{footer}\n" if text else f"{footer}\n")
    return msg


def smtp_send(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        if s.smtp_use_tls:
            smtp.starttls()
        if s.smtp_username:
            smtp.login(s.smtp_username, s.smtp_password or "")
        smtp.send_message(msg)


async def send_pending(session: AsyncSession, *,
                       sender: Optional[Callable[[EmailMessage], None]] = None,
                       now: Optional[datetime] = None) -> int:
    """Mail every notification not mailed yet. Returns how many were sent."""
    if not get_settings().smtp_enabled:
        return 0
    now = now or datetime.utcnow()
    rows = (await session.execute(
        select(Notification, User.email, User.is_active)
        .join(User, User.id == Notification.user_id)
        .where(Notification.mailed_at.is_(None))
        .order_by(Notification.id).limit(BATCH))).all()
    sent = 0
    for n, email, active in rows:
        skip = (n.is_read or not mailable(n) or not active or not (email or "").strip()
                or (n.created_at is not None and n.created_at < now - MAX_AGE))
        if not skip:
            msg = compose(n, email.strip())
            try:
                if sender is not None:
                    sender(msg)
                else:
                    await asyncio.to_thread(smtp_send, msg)
            except Exception as e:      # the relay is down: try again next run
                logger.warning(f"Notification mail {n.id} not sent: {e}")
                break
            sent += 1
        n.mailed_at = now
    if rows:
        await session.commit()
    return sent
