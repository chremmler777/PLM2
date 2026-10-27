"""ECR mail: one mail per notification (ECR-solid spec §0 Notifications).

PLM2's notice channel is the in-app notification: one per item and person
(NotificationService.notify_once), involved people only. This sends each new
notification once as a plain-text mail ending "Answer in PLM2: <link>", so
the answer is given in PLM2, never by reply (reply-to auto-answer and
30-minute batching: cut 2).

Transport: the part data mail's Microsoft Graph sender as "KTX Apps"
(app/services/part_data_mail.py: graph_send, apply_trial), so PLM2 has one
mail transport and NOTIFY_TRIAL_RECIPIENT diverts these mails too. The
per-user dedupe is notifications.mailed_at; the mail_outbox table stays the
part data digest's (per project list), these mails do not go through it.

Only the immediate class is mailed (spec §0 Notifications): a task newly
yours (task_assigned: to you; task_new: to your department), a decision
needed, an escalation to acknowledge, and the daily digests (MAIL_KINDS).
"Everything else is a badge": due reminders, late notices, deadline alerts,
FYI and stage-entry notices, decisions told back, kind-less notices and a
backup's info copy are stamped and never mailed.

Off unless settings.ecr_mail_enabled (ECR_MAIL_ENABLED) and Graph is
configured (ENTRA_*). A notification goes out at most once
(notifications.mailed_at); one already read in PLM2, older than MAX_AGE (a
backlog from before the mail was switched on) or for a user without an
active account and a valid address is stamped and skipped, never retried. A
hub account's bare username gets "@settings.mail_default_domain"; without
that setting it is no address. A mail Graph refuses for its recipient or
content (4xx other than auth/throttling) is stamped and skipped too; Graph
unreachable, throttling or refusing our app stops the run (tried again next
run)."""
from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import User
from app.models.notification import Notification
from app.services import part_data_mail

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(hours=24)
#: The kinds that are mailed. A kind-less notice is a badge.
MAIL_KINDS = frozenset({
    "task_assigned", "task_new", "deviation_pending", "routing_deviation_pending",
    "revision_intake", "change_review", "change_info_sent",
    "routing_late_assessment", "validation_issue_escalated", "overdue_digest",
    "change_digest",
    # §10: an urgent change's FAIL reaches Management at once
    "validation_urgent_fail",
    # §0 Immediate: a decision needed (A6-02); an override's answer (sent
    # only when it is a no or the change is urgent)
    "decision_needed", "deviation_decided",
    # the project team dialog's Save: newly Responsible / Backup (a
    # "no longer" notice, team_removed, stays a badge)
    "team_assigned",
})
#: graph_send raises "Graph sendMail <status>: ..." for a non-202 answer.
#: 401/403 (our app), 408/429 (throttling) and 5xx stop the run; any other
#: 4xx is this mail's recipient or content: stamped and skipped.
_GRAPH_STATUS = re.compile(r"^Graph sendMail (\d{3})\b")
_RUN_STOPPERS = {401, 403, 408, 429}
BATCH = 200
FOOTER = "Answer in PLM2: {url}"


@dataclass(frozen=True)
class Mail:
    to: list[str]
    subject: str
    body: str


Sender = Callable[[Mail], Union[None, Awaitable[None]]]


def mailable(n: Notification) -> bool:
    """Immediate class only; a backup's info copy is a badge."""
    from app.services.notification_service import BACKUP_NOTE_PREFIX
    return n.kind in MAIL_KINDS and BACKUP_NOTE_PREFIX not in (n.body or "")


def enabled() -> bool:
    return bool(get_settings().ecr_mail_enabled) and part_data_mail.configured()


def plm2_url(link: Optional[str]) -> str:
    """Absolute PLM2 URL of a frontend path ("/changes/5") on the mail link
    base (NOTIFY_BASE_URL, as the part data mail); My Tasks when the
    notification names no page."""
    base = get_settings().notify_base_url.rstrip("/")
    path = link or "/my-tasks"
    return f"{base}{path if path.startswith('/') else '/' + path}"


def address(email: Optional[str]) -> Optional[str]:
    """The mail address of a user's stored e-mail; a hub account's bare
    username ("christoph.demmler") gets the configured domain. None when
    there is no valid address to send to."""
    e = (email or "").strip()
    if not e:
        return None
    if "@" not in e:
        domain = (get_settings().mail_default_domain or "").strip().lstrip("@")
        if not domain:
            return None
        e = f"{e}@{domain}"
    e = part_data_mail.clean_address(e)
    return e if part_data_mail.valid_address(e) else None


def display_address(email: Optional[str]) -> Optional[str]:
    """esc P3-7: the e-mail an API shows (mailto links): a bare hub
    username with the default domain; anything else as stored."""
    e = (email or "").strip()
    if not e or "@" in e:
        return email
    domain = (get_settings().mail_default_domain or "").strip().lstrip("@")
    return f"{e}@{domain}" if domain else email


def compose(n: Notification, to: str) -> Mail:
    text = (n.body or "").rstrip()
    footer = FOOTER.format(url=plm2_url(n.link))
    return Mail(to=[to], subject=n.title,
                body=f"{text}\n\n{footer}\n" if text else f"{footer}\n")


async def graph_sender(mail: Mail) -> None:
    """Send through part_data_mail's Graph transport, trial mode applied."""
    to, subject, body, _trial = part_data_mail.apply_trial(mail.to, mail.subject, mail.body)
    await part_data_mail.graph_send(to, subject, body)


def refused(exc: Exception) -> bool:
    """True when only this mail is refused (recipient, content); False when
    the transport itself failed and the run should stop."""
    if isinstance(exc, (ValueError, TypeError)):
        return True
    m = _GRAPH_STATUS.match(str(exc))
    if not m:
        return False
    status = int(m.group(1))
    return 400 <= status < 500 and status not in _RUN_STOPPERS


async def send_pending(session: AsyncSession, *,
                       sender: Optional[Sender] = None,
                       now: Optional[datetime] = None) -> int:
    """Mail every notification not mailed yet. Returns how many were sent."""
    if not enabled():
        return 0
    send = sender or graph_sender
    now = now or datetime.utcnow()
    rows = (await session.execute(
        select(Notification, User.email, User.is_active)
        .join(User, User.id == Notification.user_id)
        .where(Notification.mailed_at.is_(None))
        .order_by(Notification.id).limit(BATCH))).all()
    sent = 0
    stamped = 0
    for n, stored, active in rows:
        to = address(stored)
        skip = (n.is_read or not mailable(n) or not active or to is None
                or (n.created_at is not None and n.created_at < now - MAX_AGE))
        if not skip:
            try:
                result = send(compose(n, to))
                if inspect.isawaitable(result):
                    await result
                sent += 1
            except Exception as e:
                if not refused(e):    # Graph down / refusing us: next run
                    logger.warning(f"Notification mail {n.id} not sent, transport down: "
                                   f"{part_data_mail.describe_error(e)}")
                    break
                logger.warning(f"Notification mail {n.id} refused, skipped: "
                               f"{part_data_mail.describe_error(e)}")
        n.mailed_at = now
        stamped += 1
    if stamped:
        await session.commit()
    return sent
