"""Overdue lesson-action reminders, sent at most once per 24h per action."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import LessonAction, LessonLearned
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

REMIND_EVERY = timedelta(hours=24)


async def send_overdue_action_reminders(db: AsyncSession) -> int:
    """Notify assignees of overdue open actions. Returns reminders sent."""
    now = datetime.utcnow()
    rows = (await db.execute(
        select(LessonAction, LessonLearned)
        .join(LessonLearned, LessonAction.lesson_id == LessonLearned.id)
        .where(
            LessonAction.status == "open",
            LessonAction.assignee_id.is_not(None),
            LessonAction.due_date.is_not(None),
            LessonAction.due_date < now,
        )
    )).all()

    sent = 0
    for action, lesson in rows:
        if action.last_reminded_at and now - action.last_reminded_at < REMIND_EVERY:
            continue
        days_overdue = (now - action.due_date).days
        await NotificationService.notify_users(
            db, [action.assignee_id],
            title=f"Overdue lesson action ({days_overdue}d): {lesson.title}",
            body=action.description,
            link="/lessons",
        )
        action.last_reminded_at = now
        sent += 1

    if sent:
        await db.commit()
        logger.info("Sent %d overdue lesson-action reminders", sent)
    return sent
