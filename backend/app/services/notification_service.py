"""Notification fan-out service."""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.workflow import UserDepartment

logger = logging.getLogger(__name__)

#: How notify_team marks a backup's info copy (spec §18). The mail outbox
#: reads it: an info copy stays a badge, never a mail.
BACKUP_NOTE = "Info: you are backup here, main: {main}."
BACKUP_NOTE_PREFIX = BACKUP_NOTE.split("{", 1)[0]


class NotificationService:

    @staticmethod
    async def notify_users(
        db: AsyncSession,
        user_ids: list[int],
        title: str,
        body: str | None = None,
        link: str | None = None,
        kind: str | None = None,
    ) -> int:
        """Create a notification per user. Returns how many were created.
        kind: what it is (ecr_mail.MAIL_KINDS decides what is mailed;
        a kind-less notice is a badge only)."""
        unique_ids = set(user_ids)
        for user_id in unique_ids:
            db.add(Notification(user_id=user_id, title=title, body=body, link=link,
                                kind=kind))
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
        kind: str | None = None,
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
        return await NotificationService.notify_users(db, member_ids, title, body, link,
                                                      kind=kind)

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
        include_read: bool = False,
    ) -> int:
        """Create a notification per user, deduped by (user, kind, subject_key).

        A user who already has an UNREAD notification for the same kind and
        subject is skipped — re-emitting the same event (e.g. a periodic
        sweep) must not spam their inbox. A notification the user already
        read does NOT suppress a fresh one: if the event recurs after they
        cleared the last one, it's news again. include_read=True: one
        notification per (user, kind, subject_key) ever, read or not — for a
        state a periodic sweep re-detects every run (a late task, a deadline
        at risk), which is no news the second time (spec §0: one per item).
        """
        if not user_ids:
            return 0
        unique_ids = set(user_ids)
        q = select(Notification.user_id).where(
            Notification.user_id.in_(list(unique_ids)),
            Notification.kind == kind,
            Notification.subject_key == subject_key)
        if not include_read:
            q = q.where(Notification.is_read.is_(False))
        existing = set((await db.execute(q)).scalars().all())
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
        change,
        kind: str,
        subject_key: str,
        title: str,
        body: str | None = None,
        link: str | None = None,
    ) -> int:
        """Expand department membership, then dedup-notify each member. Only
        ACTIVE members in the change's organization (change_people's rule):
        never a namesake department elsewhere, never a disabled account."""
        from app.services.change_people import team_owner_ids
        if not department_ids:
            return 0
        # F7: the project team's owner of each department, not everyone in it
        member_ids = await team_owner_ids(
            db, getattr(change, "project_id", None), department_ids)
        return await NotificationService.notify_once(
            db, member_ids, kind=kind, subject_key=subject_key,
            title=title, body=body, link=link)

    @staticmethod
    async def notify_team(
        db: AsyncSession,
        project_id: int | None,
        department_ids: list[int],
        user_ids: list[int] | None = None,
        *,
        title: str,
        body: str | None = None,
        link: str | None = None,
        kind: str | None = None,
        subject_key: str | None = None,
    ) -> int:
        """Per-department notification about a project's work, routed by the
        project team: each department's owner on the project (responsible,
        else named backup; every live member where the team names nobody).
        F7 (2026-10-26): no backup info copies any more. user_ids: the
        caller's narrowed recipients, filtered by the same rule (a person
        who is no member of these departments, e.g. the lead, stays).
        kind + subject_key dedup like notify_once."""
        from app.services.change_people import team_owner_ids
        from app.services.project_team_service import ProjectTeamService
        # F7 / R33 (test 2026-10-26): only who owns the work hears it: the
        # project team's responsible per department (its named backup while
        # the responsible is out), else the department's members. No info
        # copies to backups or to members the team does not name (a late
        # item reaches the backup through the sweep).
        owners = await team_owner_ids(db, project_id, department_ids)
        if user_ids is None:
            if not department_ids:
                return 0
            ids = owners
        else:
            mains, _backups = await ProjectTeamService.split_recipients(
                db, project_id, department_ids, user_ids)
            ids = [u for u in mains if u in owners or not await _is_member(
                db, u, department_ids)]
        ids = await _real_accounts(db, ids)
        if kind == "stage_entered" and ids:
            # one notice per person per event: whoever just got the task
            # for it is not told the stage started too
            ids = await _not_just_told(db, ids)
        if not ids:
            return 0
        if kind is not None and subject_key is not None:
            return await NotificationService.notify_once(
                db, ids, kind=kind, subject_key=subject_key,
                title=title, body=body, link=link)
        return await NotificationService.notify_users(db, ids, title, body, link,
                                                      kind=kind)


async def _is_member(db, user_id: int, department_ids) -> bool:
    return (await db.execute(select(UserDepartment.user_id).where(
        UserDepartment.user_id == user_id,
        UserDepartment.department_id.in_(list(department_ids or []))))).first() is not None


async def _real_accounts(db, user_ids) -> list[int]:
    """Active accounts that may count as people (no placeholder / local
    account, hub_departments.member_clause)."""
    from app.models.entities import User
    from app.services.hub_departments import member_clause
    ids = sorted({int(u) for u in user_ids or []})
    if not ids:
        return []
    return sorted((await db.execute(select(User.id).where(
        User.id.in_(ids), User.is_active.is_(True), member_clause()))).scalars().all())


async def _not_just_told(db, user_ids) -> list[int]:
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(minutes=2)
    told = set((await db.execute(select(Notification.user_id).where(
        Notification.user_id.in_(list(user_ids)),
        Notification.kind.in_(("task_new", "task_assigned")),
        Notification.created_at >= since))).scalars().all())
    return [u for u in user_ids if u not in told]
