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
