"""Scoping-stage meeting records: PM-gated CRUD and the decide side effects
(proceed -> kick off assessment; reject -> reject the change)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest, ChangeMeeting, MEETING_DECISIONS, MEETING_CHANNELS
from app.models.entities import User
from app.models.workflow import Department
from app.services.change_service import ChangeService, ChangeError


class MeetingService:

    @staticmethod
    async def user_is_pm(session: AsyncSession, user: User) -> bool:
        """Admin, or member of the 'Project Manager' department (mirrors the
        pattern of ChangeService.user_can_confirm_impact for R&D)."""
        if user.role == "admin":
            return True
        from app.services.workflow_service import WorkflowService
        pm_dept = (await session.execute(
            select(Department).where(Department.name == "Project Manager"))
        ).scalar_one_or_none()
        if pm_dept is None:
            return False
        return pm_dept.id in await WorkflowService.get_user_department_ids(
            session, user.id)

    @staticmethod
    async def _authz(session: AsyncSession, change: ChangeRequest, user: User):
        if user.id == change.lead_id:
            return
        if not await MeetingService.user_is_pm(session, user):
            raise ChangeError(
                "Only Project Management, the change lead, or an admin "
                "may manage scoping meetings")

    @staticmethod
    async def _validate_departments(session: AsyncSession, dept_ids: list[int]) -> list[int]:
        dept_ids = list(dict.fromkeys(dept_ids or []))
        if dept_ids:
            found = {d for (d,) in await session.execute(
                select(Department.id).where(Department.id.in_(dept_ids)))}
            unknown = sorted(set(dept_ids) - found)
            if unknown:
                raise ChangeError(f"Unknown departments: {unknown}")
        return dept_ids

    @staticmethod
    async def create_meeting(
        session: AsyncSession, change: ChangeRequest, user: User, *,
        meeting_date: Optional[datetime] = None,
        participants: Optional[list] = None, notes: Optional[str] = None,
        selected_department_ids: Optional[list[int]] = None,
        channel: str = "meeting",
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        if change.status not in ("captured", "scoping"):
            raise ChangeError(
                "Scoping decisions can only be recorded before assessment starts")
        if channel not in MEETING_CHANNELS:
            raise ChangeError(f"Invalid channel '{channel}'")
        dept_ids = await MeetingService._validate_departments(
            session, selected_department_ids or [])
        meeting = ChangeMeeting(
            change_id=change.id, meeting_date=meeting_date or datetime.utcnow(),
            channel=channel, participants=participants or [], notes=notes,
            selected_department_ids=dept_ids, created_by=user.id)
        session.add(meeting)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scoping_meeting_recorded",
            f"Scoping decision #{meeting.id} recorded ({channel})", user.id,
            new_value={"meeting_id": meeting.id, "channel": channel})
        return meeting

    @staticmethod
    async def _get_meeting(session: AsyncSession, change: ChangeRequest,
                           meeting_id: int) -> ChangeMeeting:
        meeting = await session.get(ChangeMeeting, meeting_id)
        if meeting is None or meeting.change_id != change.id:
            raise ChangeError("Meeting not found on this change")
        return meeting

    @staticmethod
    async def update_meeting(
        session: AsyncSession, change: ChangeRequest, meeting_id: int,
        user: User, **fields,
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        meeting = await MeetingService._get_meeting(session, change, meeting_id)
        if meeting.decision is not None:
            raise ChangeError("A decided meeting can no longer be edited")
        if "selected_department_ids" in fields and fields["selected_department_ids"] is not None:
            fields["selected_department_ids"] = await MeetingService._validate_departments(
                session, fields["selected_department_ids"])
        for k in ("meeting_date", "participants", "notes", "selected_department_ids"):
            if k in fields and fields[k] is not None:
                setattr(meeting, k, fields[k])
        await session.flush()
        return meeting

    @staticmethod
    async def decide_meeting(
        session: AsyncSession, change: ChangeRequest, meeting_id: int,
        decision: str, user: User,
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        if decision not in MEETING_DECISIONS:
            raise ChangeError(f"Invalid meeting decision '{decision}'")
        meeting = await MeetingService._get_meeting(session, change, meeting_id)
        if meeting.decision is not None:
            raise ChangeError(f"Meeting already decided ('{meeting.decision}')")
        if decision == "proceed" and not meeting.selected_department_ids:
            raise ChangeError(
                "Select at least one impacted department before proceeding")
        meeting.decision = decision
        meeting.decided_by = user.id
        meeting.decided_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scoping_meeting_decided",
            f"Scoping meeting #{meeting.id}: {decision}", user.id,
            field_name="decision", new_value=decision, notes=meeting.notes)
        if decision in ("proceed", "reject"):
            if change.status == "captured":
                await ChangeService.transition(session, change, "scoping", user.id)
            target = "in_assessment" if decision == "proceed" else "rejected"
            await ChangeService.transition(session, change, target, user.id)
        return meeting
