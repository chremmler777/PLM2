"""Scoping-stage meeting records: PM-gated CRUD and the decide side effects
(proceed -> kick off assessment; reject -> reject the change)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeRequest, ChangeMeeting, ChangeConcern, CONCERN_KINDS,
    MEETING_DECISIONS, MEETING_CHANNELS, SCOPING_STATUSES)
from app.models.entities import User
from app.models.workflow import Department
from app.services.change_service import ChangeService, ChangeError


class MeetingService:

    @staticmethod
    async def user_is_pm(session: AsyncSession, user: User) -> bool:
        """Admin, or member of the 'Project Manager' department (mirrors the
        pattern of ChangeService.user_can_confirm_impact for Development)."""
        if user.effective_role == "admin":
            return True
        from app.services.workflow_service import WorkflowService
        pm_dept = (await session.execute(
            select(Department).where(Department.name == "Project Manager"))
        ).scalar_one_or_none()
        if pm_dept is None:
            return False
        return pm_dept.id in await WorkflowService.effective_department_ids(
            session, user)

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
        # Meetings belong to scoping: capture is Sales writing the request
        # down, the scoping decision is the project team's. A change turned
        # down at capture is rejected via the direct transition endpoint
        # (with a rejection_reason), not via a meeting.
        if change.status != "scoping":
            raise ChangeError(
                "Scoping decisions can only be recorded while the change is in scoping")
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

    # ---- Concerns -----------------------------------------------------------
    # Flags raised by team members in parallel with (and before) the meeting.
    # They answer "who wants this rejected, and why" — which the meeting record
    # alone cannot, since it only knows who pressed the button.

    @staticmethod
    async def raise_concern(
        session: AsyncSession, change: ChangeRequest, user: User,
        kind: str, note: str, department_id: Optional[int] = None,
    ) -> ChangeConcern:
        """Two phases, two shapes. In scoping a concern is change-level: it
        feeds the scoping decision and blocks 'proceed'. In assessment it is
        one department's soft hold on its OWN assessment — so it must name the
        department, and the raiser must belong to it (admins may raise for
        any)."""
        await MeetingService._authz(session, change, user)
        in_assessment = change.status == "in_assessment"
        if change.status not in SCOPING_STATUSES and not in_assessment:
            raise ChangeError(
                "Concerns can only be raised during scoping or assessment")
        if kind not in CONCERN_KINDS:
            raise ChangeError(f"Invalid concern kind '{kind}'")
        if not (note or "").strip():
            raise ChangeError("A concern needs a note saying what the problem is")
        if in_assessment:
            if department_id is None:
                raise ChangeError(
                    "A concern raised during assessment must name the "
                    "department it holds (department_id)")
            dept = await session.get(Department, department_id)
            if dept is None:
                raise ChangeError(f"Department {department_id} not found")
            if user.effective_role != "admin":
                from app.services.workflow_service import WorkflowService
                mine = await WorkflowService.effective_department_ids(session, user)
                if department_id not in mine:
                    raise ChangeError(
                        "You can only raise a concern for your own department")
        elif department_id is not None:
            raise ChangeError(
                "Department-scoped concerns belong to the assessment phase")
        # One open concern per person per kind — a second is an edit, not a
        # vote. Scoped per department during assessment, so a person sitting in
        # two departments can still hold each of them.
        if any(c.is_open and c.raised_by == user.id and c.kind == kind
               and c.department_id == department_id
               for c in change.concerns):
            raise ChangeError(
                "You already have an open concern of this kind — withdraw it first")
        concern = ChangeConcern(
            change_id=change.id, kind=kind, note=note.strip(), raised_by=user.id,
            department_id=department_id)
        session.add(concern)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_raised",
            f"Concern ({kind}): {concern.note}", user.id,
            new_value={"concern_id": concern.id, "kind": kind,
                       "department_id": department_id},
            notes=concern.note)
        return concern

    @staticmethod
    async def withdraw_concern(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        resolution_note: Optional[str] = None,
    ) -> ChangeConcern:
        concern = await session.get(ChangeConcern, concern_id)
        if concern is None or concern.change_id != change.id:
            raise ChangeError("Concern not found on this change")
        if not concern.is_open:
            raise ChangeError("Concern is no longer open")
        # Only its author may withdraw it — clearing someone else's objection
        # for them is exactly what this feature exists to prevent. The lead and
        # admins are not exempt.
        if concern.raised_by != user.id:
            raise ChangeError("Only the person who raised a concern may withdraw it")
        # A department-scoped concern held that department's assessment.
        # Lifting the hold has to say how the point was addressed.
        note = (resolution_note or "").strip()
        if concern.department_id is not None and not note:
            raise ChangeError(
                "Withdrawing a department concern requires a resolution note "
                "saying how it was addressed")
        concern.withdrawn_at = datetime.utcnow()
        concern.withdrawn_by = user.id
        concern.resolution_note = note or None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_withdrawn",
            f"Concern #{concern.id} withdrawn"
            + (f" — {concern.resolution_note}" if concern.resolution_note else ""),
            user.id,
            old_value={"concern_id": concern.id},
            notes=concern.resolution_note)
        return concern

    @staticmethod
    def open_department_concerns(
        change: ChangeRequest, department_id: int,
    ) -> list[ChangeConcern]:
        """Open concerns holding one department's assessment."""
        return [c for c in change.concerns
                if c.is_open and c.department_id == department_id]

    @staticmethod
    def open_concerns(change: ChangeRequest) -> list[ChangeConcern]:
        return [c for c in change.concerns if c.is_open]

    @staticmethod
    async def decide_meeting(
        session: AsyncSession, change: ChangeRequest, meeting_id: int,
        decision: str, user: User, reason: Optional[str] = None,
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
        # Proceeding over an unanswered objection is the failure this exists to
        # stop. Either its author withdraws it, or the decision answers it.
        open_concerns = MeetingService.open_concerns(change)
        if decision == "proceed" and open_concerns:
            who = ", ".join(sorted({c.raised_by_name or f"user #{c.raised_by}"
                                    for c in open_concerns}))
            raise ChangeError(
                f"{len(open_concerns)} open concern(s) from {who} — they must be "
                "withdrawn by their author, or answered by rejecting / asking "
                "for more information")
        # Both of the negative outcomes owe the originator an answer: reject
        # says why the change cannot go ahead, needs_info says what is missing
        # before it can start. Only 'proceed' needs no justification.
        if decision == "reject" and not reason:
            raise ChangeError("A reason is required to reject a change")
        if decision == "needs_info" and not reason:
            raise ChangeError(
                "State what information is missing before the change can start")
        meeting.decision = decision
        meeting.decision_reason = reason
        # A negative decision answers the open concerns; they close with it.
        if decision in ("reject", "needs_info"):
            for c in open_concerns:
                c.resolved_by_meeting_id = meeting.id
        meeting.decided_by = user.id
        meeting.decided_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scoping_meeting_decided",
            f"Scoping meeting #{meeting.id}: {decision}"
            + (f" — {reason}" if reason else ""), user.id,
            field_name="decision", new_value=decision,
            notes=reason or meeting.notes)
        if decision in ("proceed", "reject"):
            # Meetings only exist in scoping now, so proceed always goes
            # straight to assessment; reject goes straight out.
            target = "in_assessment" if decision == "proceed" else "rejected"
            # The meeting's reason is the change's rejection reason — one
            # decision, one justification, not two places to keep in step.
            await ChangeService.transition(
                session, change, target, user.id, rejection_reason=reason)
        return meeting
