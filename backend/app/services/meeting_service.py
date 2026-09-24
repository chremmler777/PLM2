"""Scoping-stage meeting records: PM-gated CRUD and the decide side effects
(proceed -> kick off assessment; reject -> reject the change)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeRequest, ChangeMeeting, ChangeConcern, CONCERN_KINDS,
    RISK_TYPES, RISK_SEVERITIES, TASK_LETTERS, BLOCKING_LETTERS,
    MEETING_DECISIONS, MEETING_CHANNELS, SCOPING_STATUSES)
from app.models.entities import User
from app.models.workflow import Department
from app.services.change_service import ChangeService, ChangeError
from app.services.workflow_service import WorkflowService


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
    async def user_is_pm_member(session: AsyncSession, user: User) -> bool:
        """Project Manager MEMBERSHIP — no admin shortcut, unlike user_is_pm.

        Settling someone else's objection is exactly the act that must not be
        available to whoever happens to hold an admin flag; a real admin does
        it by acting as Project Manager, which puts the department on the
        record."""
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
    async def _validate_rasic(session: AsyncSession,
                              rasic: Optional[dict]) -> tuple[Optional[dict], list[int]]:
        """Normalise the room's RASIC call: int keys, upper-case letters out of
        R/A/S/C ("I" for Informed is taken as Consulted — the engine owes an
        informed department nothing more than it owes a consulted one), known
        departments only. Returns (map with str keys for JSON, ordered ids)."""
        if rasic is None:
            return None, []
        out: dict[str, str] = {}
        for k, v in rasic.items():
            letter = (v or "").strip().upper()
            if letter == "I":
                letter = "C"
            if letter not in TASK_LETTERS:
                raise ChangeError(
                    f"Invalid RASIC letter '{v}' for department {k} — one of R, A, S, C")
            out[str(int(k))] = letter
        ids = await MeetingService._validate_departments(session, [int(k) for k in out])
        return out, ids

    @staticmethod
    async def create_meeting(
        session: AsyncSession, change: ChangeRequest, user: User, *,
        meeting_date: Optional[datetime] = None,
        participants: Optional[list] = None, notes: Optional[str] = None,
        selected_department_ids: Optional[list[int]] = None,
        channel: str = "meeting",
        department_rasic: Optional[dict] = None,
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
        rasic, rasic_ids = await MeetingService._validate_rasic(session, department_rasic)
        # The letter map is authoritative when given: the id list follows it.
        dept_ids = rasic_ids if rasic is not None else \
            await MeetingService._validate_departments(session, selected_department_ids or [])
        meeting = ChangeMeeting(
            change_id=change.id, meeting_date=meeting_date or datetime.utcnow(),
            channel=channel, participants=participants or [], notes=notes,
            selected_department_ids=dept_ids, department_rasic=rasic,
            created_by=user.id)
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
        if fields.get("department_rasic") is not None:
            rasic, ids = await MeetingService._validate_rasic(session, fields["department_rasic"])
            fields["department_rasic"] = rasic
            fields["selected_department_ids"] = ids
        elif "selected_department_ids" in fields and fields["selected_department_ids"] is not None:
            fields["selected_department_ids"] = await MeetingService._validate_departments(
                session, fields["selected_department_ids"])
            # An id-only edit drops letters for departments no longer picked.
            if meeting.department_rasic:
                keep = {str(i) for i in fields["selected_department_ids"]}
                fields["department_rasic"] = {k: v for k, v in meeting.department_rasic.items()
                                              if k in keep}
        for k in ("meeting_date", "participants", "notes", "selected_department_ids",
                  "department_rasic"):
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
        risk_type: Optional[str] = None, severity: Optional[int] = None,
        checklist_key: Optional[str] = None,
    ) -> ChangeConcern:
        """Two phases, two meanings for department_id.

        In scoping a concern feeds the decision and blocks 'proceed'. Naming a
        department there is pure attribution — "this is a Tooling point" vs the
        whole team's — so it is optional and needs no membership.

        In assessment the department is the concern's teeth: it soft-holds that
        department's own assessment submit. So it is required, and it must be
        the raiser's own department (admins may raise for any).

        Authz is deliberately open: ANY authenticated user may flag a concern.
        This is the one thing the feature exists for — an objection that only
        the lead or a PM could file is not a parallel team voice, it is the
        meeting again. The scoping-meeting gate (_authz) belongs to meetings,
        not to this. Withdrawal has its own rule (see withdraw_concern):
        the author, the raising department, or Project Management.
        """
        in_assessment = change.status == "in_assessment"
        if change.status not in SCOPING_STATUSES and not in_assessment:
            raise ChangeError(
                "Concerns can only be raised during scoping or assessment")
        if kind not in CONCERN_KINDS:
            raise ChangeError(f"Invalid concern kind '{kind}'")
        # Two phases, two vocabularies. Scoping is the team working the
        # decision in parallel: anyone may ask for missing information
        # (needs_info) or vote to reject the change (reject_proposal), and
        # those flags block 'proceed' until they are withdrawn or answered by
        # a decision. The risk register belongs to assessment — a risk holds
        # nothing and is worked with a mitigation proposal where the technical
        # work happens, not in the scoping room.
        if in_assessment and kind != "risk":
            raise ChangeError(
                f"'{kind}' concerns belong to scoping — during assessment "
                "the register takes risks")
        if not in_assessment and kind == "risk":
            raise ChangeError(
                "Risks belong to the assessment phase — during scoping, flag "
                "a concern (needs_info or reject_proposal) instead")
        if kind == "risk":
            # The vocabulary is per department (app/services/risk_types.py):
            # a Tool Engineer's "not steel-safe" is not a Sales risk. The
            # legacy moulding keys stay valid for everyone.
            from app.services.risk_types import allowed_keys
            dept_for_vocab = (await session.get(Department, department_id)
                              if department_id is not None else None)
            allowed = await allowed_keys(session, dept_for_vocab)
            if risk_type not in allowed:
                raise ChangeError(
                    f"Invalid risk type '{risk_type}' for this department — one of: "
                    + ", ".join(sorted(allowed)))
            if severity not in RISK_SEVERITIES:
                raise ChangeError(
                    "Risk severity must be 1 (low), 2 (medium) or 3 (high)")
        if checklist_key is not None:
            if kind != "risk":
                raise ChangeError("Only a risk can point at a checklist row")
            if len(checklist_key) > 120:
                raise ChangeError("checklist_key is too long")
            if not checklist_key.startswith("free:"):
                from app.services import assessment_checklist as checklist
                dept_for_keys = (await session.get(Department, department_id)
                                 if department_id is not None else None)
                if checklist_key not in checklist.keys_for(
                        dept_for_keys.name if dept_for_keys else None):
                    raise ChangeError(
                        f"'{checklist_key}' is not a checklist item for this department")
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
            # Scoping: attribution only — any active department, no membership.
            dept = await session.get(Department, department_id)
            if dept is None or not dept.is_active:
                raise ChangeError(
                    f"Unknown or inactive department {department_id}")
        # One open concern per person per kind — a second is an edit, not a
        # vote. Scoped per department during assessment, so a person sitting in
        # two departments can still hold each of them. Risks are exempt: a
        # register is a list, and one person routinely sees a fill risk AND a
        # dimensional one on the same change.
        if kind != "risk" and any(
                c.is_open and c.raised_by == user.id and c.kind == kind
                and c.department_id == department_id
                for c in change.concerns):
            raise ChangeError(
                "You already have an open concern of this kind — withdraw it first")
        concern = ChangeConcern(
            change_id=change.id, kind=kind, note=note.strip(), raised_by=user.id,
            department_id=department_id,
            risk_type=risk_type if kind == "risk" else None,
            severity=severity if kind == "risk" else None,
            checklist_key=checklist_key)
        session.add(concern)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_raised",
            f"Concern ({kind}"
            + (f"/{concern.risk_type}, severity {concern.severity}"
               if kind == "risk" else "")
            + f"): {concern.note}", user.id,
            new_value={"concern_id": concern.id, "kind": kind,
                       "department_id": department_id,
                       "risk_type": concern.risk_type,
                       "severity": concern.severity,
                       "checklist_key": checklist_key},
            notes=concern.note)
        return concern

    @staticmethod
    async def retract_concern(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
    ) -> ChangeConcern:
        """Delete a risk raised by mistake. Only its raiser, only while it is
        open, and only while nothing hangs off it — once a mitigation proposal
        or a document exists, the risk has a history and is closed with a
        resolution instead."""
        concern = await session.get(ChangeConcern, concern_id)
        if concern is None or concern.change_id != change.id:
            raise ChangeError("Concern not found on this change")
        if concern.kind != "risk":
            raise ChangeError("Only a risk can be deleted; close other concerns instead")
        if not concern.is_open:
            raise ChangeError("This risk is no longer open")
        if concern.raised_by != user.id:
            raise ChangeError("Only the person who raised this risk may delete it")
        from app.models.change import ChangeAttachment
        docs = (await session.execute(
            select(func.count()).select_from(ChangeAttachment).where(
                ChangeAttachment.concern_id == concern.id))).scalar() or 0
        if concern.answered_at is not None or docs:
            raise ChangeError(
                "This risk already has a mitigation proposal or documents; "
                "resolve it instead of deleting it")
        concern.retracted_at = datetime.utcnow()
        concern.retracted_by = user.id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_retracted",
            f"Risk #{concern.id} deleted, raised by mistake: {concern.note}",
            user.id, new_value={"concern_id": concern.id,
                                "checklist_key": concern.checklist_key})
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
        # Settling a concern belongs to the side that raised it, plus Project
        # Management as the standing arbiter. Who "the side" is depends on
        # what the flag is. An assessment hold or a risk is the DEPARTMENT's,
        # not one member's — colleagues cover for each other and people leave
        # — so any member of that department may settle it. A scoping question
        # or cancel vote belongs to the person who raised it, even when
        # attributed to a department: attribution is a label anyone may pick,
        # so it grants nobody — Sales least of all — the right to declare the
        # point settled.
        #
        # Nobody else, however senior: an objection cleared by the person it
        # inconveniences is the failure this feature exists to prevent, and
        # answering a question (see answer_concern) is deliberately NOT the
        # same act as deciding the answer was good enough.
        note = (resolution_note or "").strip()
        department_owns_it = (concern.department_id is not None
                              and (concern.kind == "risk"
                                   or change.status == "in_assessment"))
        # Acting-as means being exactly that department and nothing else
        # (spec D2): the admin's personal authorship steps aside with their
        # real memberships, so driving the Sales view never keeps the
        # requester right on a question they asked as themselves.
        acting_as = getattr(user, "acts_as_department_id", None) is not None
        allowed = ((concern.raised_by == user.id and not acting_as)
                   or await MeetingService.user_is_pm_member(session, user)
                   or (department_owns_it
                       and await WorkflowService.actor_in_department(
                           session, user, concern.department_id)))
        if not allowed:
            raise ChangeError(
                "Only a member of the department that raised this concern, "
                "or Project Management, may settle it"
                if department_owns_it else
                "Only the person who raised this concern, or Project "
                "Management, may settle it")
        if concern.department_id is not None and not note:
            # A department-attributed flag owes its resolution — how was the
            # point addressed, on the record.
            raise ChangeError(
                "Withdrawing a department concern requires a resolution note "
                "saying how it was addressed")
        concern.withdrawn_at = datetime.utcnow()
        concern.withdrawn_by = user.id
        concern.resolution_note = note or None
        await session.flush()
        # The changelog row IS the thread: question (concern_raised) then
        # answer (concern_withdrawn), each with its note and its actor.
        await ChangeService.append_changelog(
            session, change,
            "concern_withdrawn",
            f"Concern #{concern.id} withdrawn"
            + (f" — {concern.resolution_note}" if concern.resolution_note else ""),
            user.id,
            old_value={"concern_id": concern.id},
            notes=concern.resolution_note)
        return concern

    @staticmethod
    async def _flag_missing_information(
        session: AsyncSession, change: ChangeRequest, user: User, reason: str,
        meeting_id: Optional[int] = None,
    ) -> Optional[ChangeConcern]:
        """A needs_info decision IS an open point against the change, so it
        becomes a Team concern in its own right rather than a note in a meeting
        row nobody watches. From there it obeys every existing rule: it blocks
        'proceed', only its author clears it, and the follow-up decision
        resolves it.

        Idempotent per decider: the same person deciding needs_info twice in a
        row is one open question, not two. Raised directly (not via
        raise_concern) because the decision has already been authorized and
        validated — re-running those checks here could only reject a decision
        that has already been written."""
        if any(c.is_open and c.kind == "needs_info" and c.department_id is None
               and c.raised_by == user.id for c in change.concerns):
            return None
        concern = ChangeConcern(
            change_id=change.id, kind="needs_info", note=reason.strip(),
            raised_by=user.id, department_id=None,
            raised_by_meeting_id=meeting_id)
        session.add(concern)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_raised",
            f"Concern (needs_info): {concern.note}", user.id,
            new_value={"concern_id": concern.id, "kind": "needs_info",
                       "department_id": None, "meeting_id": meeting_id},
            notes=concern.note)
        return concern

    @staticmethod
    async def answer_concern(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        note: Optional[str] = None,
    ) -> ChangeConcern:
        """Sales writes the answer to an open question — a COMMENT on it, not a
        verdict on it.

        Deliberately separate from withdrawal: the side that asked decides
        whether the answer settles the point, so answering leaves the concern
        open and the task list simply stops nagging. Re-answering overwrites
        the stored note; every round stays in the changelog, so a thin first
        answer is visible rather than silently replaced.
        """
        concern = await session.get(ChangeConcern, concern_id)
        if concern is None or concern.change_id != change.id:
            raise ChangeError("Concern not found on this change")
        if not concern.is_open:
            raise ChangeError("Concern is no longer open")
        note = (note or "").strip()
        # Two shapes of answer, told apart by where the change is standing.
        #
        # A CUSTOMER question (scoping) is Sales' to answer: they own the
        # relationship, and words are enough.
        #
        # A DEPARTMENT hold during assessment is a technical problem, and the
        # answer is a PROPOSAL — anyone on the team may put one forward, but it
        # arrives as a document. "We could shim it" in a text box is a
        # conversation; the PPT is the proposal the raising department is asked
        # to accept or refuse.
        #
        # Keyed on the change's CURRENT status rather than a stored phase: the
        # question is what this concern is doing now, and adding a column to
        # remember which room it was raised in would answer a different one.
        departmental = (concern.department_id is not None
                        and change.status == "in_assessment")
        if departmental:
            if not await ChangeService.has_info_response(
                    session, change, concern_id=concern.id):
                raise ChangeError(
                    "A proposal needs its documentation attached (PPT)")
        else:
            if not await ChangeService._user_in_department(session, user, "Sales"):
                raise ChangeError(
                    "Only a Sales department member may answer a concern")
            # An answer needs content — either words, or the document that
            # carries them filed into this question's container.
            if not note and not await ChangeService.has_info_response(
                    session, change, concern_id=concern.id):
                raise ChangeError(
                    "An answer needs content — write it or attach the response "
                    "document")
        concern.answer_note = note or None
        concern.answered_at = datetime.utcnow()
        concern.answered_by = user.id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_answered",
            f"Concern #{concern.id} answered"
            + (f" — {note}" if note else " (see attached document)"),
            user.id,
            new_value={"concern_id": concern.id}, notes=note or None)
        return concern

    @staticmethod
    def open_department_concerns(
        change: ChangeRequest, department_id: int,
    ) -> list[ChangeConcern]:
        """Open concerns holding one department's assessment."""
        return [c for c in change.concerns
                if c.is_open and c.kind != "risk"
                and c.department_id == department_id]

    @staticmethod
    def open_concerns(change: ChangeRequest) -> list[ChangeConcern]:
        """Open points somebody still owes an answer to.

        Risks are excluded on both counts this list is used for: they do not
        block 'proceed' (a change ships with its risks recorded — refusing to
        decide until the register is empty would just teach people to withdraw
        them), and a reject/needs_info decision does not answer them, so they
        must not be closed as though it had."""
        return [c for c in change.concerns if c.is_open and c.kind != "risk"]

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
        # With letters on the record, somebody has to own the assessment:
        # a room of Supports and Consulteds leaves stage 1 with no gate.
        if (decision == "proceed" and meeting.department_rasic
                and not any(v in BLOCKING_LETTERS for v in meeting.department_rasic.values())):
            raise ChangeError(
                "At least one department must be Responsible or Accountable (R/A) "
                "before proceeding")
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
        if decision == "needs_info":
            await MeetingService._flag_missing_information(
                session, change, user, reason, meeting_id=meeting.id)
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
