"""Notification fan-out service."""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.workflow import UserDepartment

logger = logging.getLogger(__name__)


class NotificationService:

    @staticmethod
    async def notify_users(
        db: AsyncSession,
        user_ids: list[int],
        title: str,
        body: str | None = None,
        link: str | None = None,
    ) -> int:
        """Create a notification per user. Returns how many were created."""
        unique_ids = set(user_ids)
        for user_id in unique_ids:
            db.add(Notification(user_id=user_id, title=title, body=body, link=link))
        if unique_ids:
            await db.flush()
        return len(unique_ids)

    @staticmethod
    async def notify_departments(
        db: AsyncSession,
        department_ids: list[int],
        title: str,
        body: str | None = None,
        link: str | None = None,
    ) -> int:
        """Notify every member of the given departments."""
        if not department_ids:
            return 0
        result = await db.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.department_id.in_(department_ids)
            )
        )
        member_ids = [u for (u,) in result.all()]
        return await NotificationService.notify_users(db, member_ids, title, body, link)

    @staticmethod
    async def notify_once(
        db: AsyncSession,
        user_ids: list[int],
        *,
        kind: str,
        subject_key: str,
        title: str,
        body: str | None = None,
        link: str | None = None,
    ) -> int:
        """Create a notification per user, deduped by (user, kind, subject_key).

        A user who already has an UNREAD notification for the same kind and
        subject is skipped — re-emitting the same event (e.g. a periodic
        sweep) must not spam their inbox. A notification the user already
        read does NOT suppress a fresh one: if the event recurs after they
        cleared the last one, it's news again.
        """
        if not user_ids:
            return 0
        unique_ids = set(user_ids)
        existing = set((await db.execute(
            select(Notification.user_id).where(
                Notification.user_id.in_(list(unique_ids)),
                Notification.kind == kind,
                Notification.subject_key == subject_key,
                Notification.is_read.is_(False),
            ))).scalars().all())
        n = 0
        for uid in unique_ids - existing:
            db.add(Notification(user_id=uid, kind=kind, subject_key=subject_key,
                                title=title, body=body, link=link))
            n += 1
        if n:
            await db.flush()
        return n

    @staticmethod
    async def notify_departments_once(
        db: AsyncSession,
        department_ids: list[int],
        *,
        kind: str,
        subject_key: str,
        title: str,
        body: str | None = None,
        link: str | None = None,
    ) -> int:
        """Expand department membership, then dedup-notify each member."""
        if not department_ids:
            return 0
        result = await db.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.department_id.in_(department_ids)
            )
        )
        member_ids = [u for (u,) in result.all()]
        return await NotificationService.notify_once(
            db, member_ids, kind=kind, subject_key=subject_key,
            title=title, body=body, link=link)
