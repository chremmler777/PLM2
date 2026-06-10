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


async def escalate_overdue_targets(db: AsyncSession) -> int:
    """Escalate in-work lessons past their target date to owner + department (1/24h)."""
    now = datetime.utcnow()
    lessons = (await db.execute(
        select(LessonLearned).where(
            LessonLearned.status == "in_work",
            LessonLearned.target_date.is_not(None),
            LessonLearned.target_date < now,
        )
    )).scalars().all()

    escalated = 0
    for lesson in lessons:
        if lesson.last_escalated_at and now - lesson.last_escalated_at < REMIND_EVERY:
            continue
        days_over = (now - lesson.target_date).days
        title = f"Lesson past target date ({days_over}d): {lesson.title}"
        if lesson.owner_id:
            await NotificationService.notify_users(db, [lesson.owner_id], title=title, link="/lessons")
        if lesson.department_id:
            await NotificationService.notify_departments(db, [lesson.department_id], title=title, link="/lessons")
        lesson.last_escalated_at = now
        escalated += 1

    if escalated:
        await db.commit()
        logger.info("Escalated %d lessons past target date", escalated)
    return escalated
