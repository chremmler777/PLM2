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
        from app.services.change_people import department_members_of_change_org
        if not department_ids:
            return 0
        member_ids = await department_members_of_change_org(
            db, change, department_ids)
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
        project team (spec §18): the responsible of each department (or every
        member where none is set) gets it as today; a backup gets the same
        notification marked as info ("Info: you are backup here, main: X").
        Notifications have no quiet flag, so the info copy is still an
        ordinary unread notification. user_ids: the recipients when the
        caller already narrowed them; otherwise the ACTIVE members of the
        departments in the project's organization (change_people's rule for
        a change: never a namesake department elsewhere, never a disabled
        account). kind + subject_key dedup like notify_once."""
        from types import SimpleNamespace
        from app.services.change_people import department_members_of_change_org
        from app.services.project_team_service import ProjectTeamService
        if user_ids is None:
            if not department_ids:
                return 0
            user_ids = await department_members_of_change_org(
                db, SimpleNamespace(project_id=project_id), department_ids)
        mains, backups = await ProjectTeamService.split_recipients(
            db, project_id, department_ids, user_ids)

        async def _send(ids: list[int], text: str | None) -> int:
            if not ids:
                return 0
            if kind is not None and subject_key is not None:
                return await NotificationService.notify_once(
                    db, ids, kind=kind, subject_key=subject_key,
                    title=title, body=text, link=link)
            return await NotificationService.notify_users(db, ids, title, text, link,
                                                          kind=kind)

        n = await _send(mains, body)
        by_main: dict[str, list[int]] = {}
        for uid, main in backups.items():
            by_main.setdefault(main, []).append(uid)
        for main, ids in by_main.items():
            note = BACKUP_NOTE.format(main=main)
            n += await _send(ids, f"{body}\n{note}" if body else note)
        return n
