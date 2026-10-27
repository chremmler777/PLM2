"""Scoping-stage meeting records: PM-gated CRUD and the decide side effects
(proceed -> kick off assessment; reject -> reject the change)."""
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeRequest, ChangeMeeting, ChangeConcern, CONCERN_KINDS,
    RISK_TYPES, RISK_SEVERITIES, TASK_LETTERS, BLOCKING_LETTERS,
    MEETING_DECISIONS, MEETING_CHANNELS, SCOPING_STATUSES,
    FLAG_TYPES, CHECK_WHAT, ANSWER_FROM, ANSWER_KINDS)
from app.services import cm_switches
from app.models.entities import User
from app.models.workflow import Department
from app.services.change_service import ChangeService, ChangeError
from app.services.workflow_service import WorkflowService


#: An ended change: its record stays as it is (no confirm, no add).
ENDED = ("closed", "cancelled", "rejected")


class MeetingForbidden(ChangeError):
    """A meeting act the caller has no right to: 403, not 400 (spec §16)."""


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
        from app.services.change_people import holds_lead
        if holds_lead(change, user):
            return
        if not await MeetingService.user_is_pm(session, user):
            raise MeetingForbidden(
                "Only Project Management, the change lead or an admin "
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
        R/A/S/C/I (I = Informed: notified, no task, never waited on), known
        departments only. Returns (map with str keys for JSON, ordered ids)."""
        if rasic is None:
            return None, []
        out: dict[str, str] = {}
        for k, v in rasic.items():
            letter = (v or "").strip().upper()
            if letter not in TASK_LETTERS:
                raise ChangeError(
                    f"Invalid RASIC letter '{v}' for department {k}: one of R, A, S, C, I")
            out[str(int(k))] = letter
        ids = await MeetingService._validate_departments(session, [int(k) for k in out])
        await MeetingService._refuse_unroutable(session, {int(k): v for k, v in out.items()})
        return out, ids

    @staticmethod
    async def _refuse_unroutable(session: AsyncSession, letters: dict[int, str]) -> None:
        """R25: Management and retired departments take no task letter
        (Informed is fine)."""
        from app.services.change_routing_service import ChangeRoutingService
        why = await ChangeRoutingService.unroutable_refusals(session, letters)
        if why:
            raise ChangeError("; ".join(why))

    @staticmethod
    def _participant_matches(user: User, name: str, username: str,
                             email: str) -> bool:
        """Does the id's user agree with what the client sent? A sent
        email must be that user's; else a sent name (or username) must be
        that user's full name or username. Nothing sent to compare: the id
        stands on its own."""
        u_email = (user.email or "").strip().lower()
        if email:
            return email == u_email
        names = {(user.full_name or "").strip().lower(),
                 (user.username or "").strip().lower()} - {""}
        probes = {name.strip().lower(), username} - {""}
        if not probes:
            return True
        return bool(probes & names)

    @staticmethod
    async def resolve_participants(session: AsyncSession,
                                   participants: Optional[list]) -> list[dict]:
        """Attendees as {name, user_id}: a given user_id is kept when that
        user exists AND agrees with the name/email sent alongside it (a
        client cannot pin an attendee on somebody else by id); otherwise
        the picker's username, then email, finds the PLM2 user
        (case-insensitive). Free-text names stay free text."""
        out: list[dict] = []
        for p in participants or []:
            if not isinstance(p, dict):
                p = p.model_dump() if hasattr(p, "model_dump") else {"name": str(p)}
            name = (p.get("name") or "").strip()
            uid = p.get("user_id")
            user = await session.get(User, uid) if uid else None
            username = (p.get("username") or "").strip().lower()
            email = (p.get("email") or "").strip().lower()
            if user is not None and not MeetingService._participant_matches(
                    user, name, username, email):
                user = None
            if user is None and username:
                user = (await session.execute(select(User).where(
                    func.lower(User.username) == username))).scalars().first()
            if user is None and email:
                user = (await session.execute(select(User).where(
                    func.lower(User.email) == email))).scalars().first()
            entry = {"name": name or (user.full_name or user.username if user else ""),
                     "user_id": user.id if user is not None else None}
            if email:
                entry["email"] = email
            if not entry["name"]:
                continue
            out.append(entry)
        return out

    @staticmethod
    async def create_meeting(
        session: AsyncSession, change: ChangeRequest, user: User, *,
        meeting_date: Optional[datetime] = None,
        participants: Optional[list] = None, notes: Optional[str] = None,
        selected_department_ids: Optional[list[int]] = None,
        channel: str = "meeting",
        department_rasic: Optional[dict] = None,
        cost_carrier: Optional[str] = None,
        raiser_waive_reason: Optional[str] = None,
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        # Meetings belong to scoping: capture is Project Management writing the request
        # down, the scoping decision is the project team's. A change turned
        # down at capture is rejected via the direct transition endpoint
        # (with a rejection_reason), not via a meeting.
        if change.status != "scoping":
            raise ChangeError(
                "Scoping decisions can only be recorded while the change is in scoping")
        if channel not in MEETING_CHANNELS:
            raise ChangeError(f"Invalid channel '{channel}'")
        MeetingService._refuse_internal_after_flip(change, cost_carrier)
        await MeetingService._refuse_carrier_move(
            session, change, user, MeetingService._validate_cost_carrier(cost_carrier))
        rasic, rasic_ids = await MeetingService._validate_rasic(session, department_rasic)
        # The letter map is authoritative when given: the id list follows it.
        dept_ids = rasic_ids if rasic is not None else \
            await MeetingService._validate_departments(session, selected_department_ids or [])
        if rasic is None:
            await MeetingService._refuse_unroutable(session, {i: "R" for i in dept_ids})
        meeting = ChangeMeeting(
            change_id=change.id, meeting_date=meeting_date or datetime.utcnow(),
            channel=channel,
            participants=await MeetingService.resolve_participants(session, participants),
            notes=notes,
            selected_department_ids=dept_ids, department_rasic=rasic,
            cost_carrier=MeetingService._validate_cost_carrier(cost_carrier),
            created_by=user.id)
        session.add(meeting)
        await session.flush()
        if rasic is not None or dept_ids:
            await MeetingService._check_raiser_letter(
                session, change, user, rasic or {str(i): "R" for i in dept_ids},
                None, raiser_waive_reason, meeting.id)
        await ChangeService.append_changelog(
            session, change, "scoping_meeting_recorded",
            f"Scoping decision #{meeting.id} recorded ({channel})", user.id,
            new_value={"meeting_id": meeting.id, "channel": channel})
        from app.services.ppap_decision_service import PpapDecisionService
        await PpapDecisionService.notify_owed(session, change, user.id)
        return meeting

    @staticmethod
    async def raiser_department_id(session: AsyncSession,
                                   change: ChangeRequest) -> Optional[int]:
        """Spec §3 "Internal: raiser's department auto-R" (SCOPING_V2): the
        active internal-starter department (P3 + D1: Development, Process, Tool,
        Manufacturing Engineer) of the person who raised an internal change, the first by
        sort order; else None."""
        if (not cm_switches.on("SCOPING_V2") or change.origin != "internal"
                or change.raised_by is None):
            return None
        from app.models.workflow import UserDepartment
        return (await session.execute(
            select(Department.id)
            .join(UserDepartment, UserDepartment.department_id == Department.id)
            .where(UserDepartment.user_id == change.raised_by,
                   Department.is_active.is_(True),
                   Department.can_start_internal_change.is_(True))
            .order_by(Department.sort_order, Department.id).limit(1))).scalar_one_or_none()

    @staticmethod
    async def _check_raiser_letter(
        session: AsyncSession, change: ChangeRequest, user: User,
        letters: dict, before: Optional[dict], reason: Optional[str],
        meeting_id: Optional[int] = None,
    ) -> None:
        """The raiser's department assesses an internal change (R); leaving
        it out, or below R/A, needs a reason, logged (spec §3). Checked when
        the room's call moves it out: a new meeting (unless an earlier one
        waived it already) or an edit that drops it."""
        rd = await MeetingService.raiser_department_id(session, change)
        if rd is None or letters.get(str(rd)) in BLOCKING_LETTERS:
            return
        # A2-06: an empty 'before' (a meeting recorded with no departments)
        # routed nobody yet: like a new meeting, not "already out"
        if before:
            if before.get(str(rd)) not in BLOCKING_LETTERS:
                return                      # already out: nothing moves
        else:
            from app.models.change import ChangeChangelog
            waived = (await session.execute(select(ChangeChangelog.id).where(
                ChangeChangelog.change_id == change.id,
                ChangeChangelog.action == "raiser_department_waived").limit(1))
            ).scalar_one_or_none()
            if waived is not None:
                return
        dept = await session.get(Department, rd)
        name = dept.name if dept else f"department {rd}"
        from app.services.cm_rules import reference_refusal
        why = reference_refusal(
            reason, f"{name} raised this internal change and assesses it (R): "
            "the reason to leave it out", "only the tool changes, no process step")
        if why:
            raise ChangeError(why)
        await ChangeService.append_changelog(
            session, change, "raiser_department_waived",
            f"{name} (the raiser's department) does not assess: {reason.strip()}",
            user.id, new_value={"department_id": rd, "meeting_id": meeting_id,
                                "letter": letters.get(str(rd))},
            notes=reason.strip())

    @staticmethod
    def _refuse_internal_after_flip(change: ChangeRequest,
                                    carrier: Optional[str]) -> None:
        """HARD #7: the room may not set a flipped change back to internal;
        only Sales' 'notification only' does."""
        if carrier != "internal":
            return
        from app.services.ppap_decision_service import back_to_internal_refusal
        why = back_to_internal_refusal(change)
        if why:
            raise ChangeError(why)

    @staticmethod
    async def _refuse_carrier_move(session: AsyncSession, change: ChangeRequest,
                                   user: User, carrier: Optional[str]) -> None:
        """P3 / [R4]: the room moves the cost carrier only with the rights
        PATCH customer_relevant asks (ChangeService.carrier_move_refusal):
        an engineering lead may not make an internal change a customer one,
        nor take the customer off one. 403."""
        if carrier is None:
            return
        why = await ChangeService.carrier_move_refusal(
            session, change, user, carrier == "customer")
        if why:
            raise MeetingForbidden(why)

    @staticmethod
    def _validate_cost_carrier(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if value not in ("customer", "internal"):
            raise ChangeError(
                f"Invalid cost carrier '{value}': customer or internal")
        return value

    @staticmethod
    async def _apply_cost_carrier(session: AsyncSession, change: ChangeRequest,
                                  meeting: ChangeMeeting, user: User) -> None:
        """Spec §16: the room re-confirms the cost carrier Project Management picked at
        capture. A flip is a decision with consequences (it selects the
        whole commercial branch), so it is audited and Sales is told."""
        wanted = meeting.cost_carrier == "customer"
        if bool(change.customer_relevant) == wanted:
            return
        before = "customer" if change.customer_relevant else "internal"
        change.customer_relevant = wanted
        from app.services import mother_plants as mp
        if not mp.is_mother_plant(change):
            change.origin = meeting.cost_carrier
            # C10 + spec §0 [R4], as PATCH: internal = no Sales contact;
            # customer = the project's Sales contact, led by the project PM
            await ChangeService.carrier_people(session, change, wanted, user.id)
        await session.flush()
        from app.services.cm_labels import label
        await ChangeService.append_changelog(
            session, change, "cost_carrier_changed",
            f"Cost carrier changed at the scoping meeting: "
            f"{label('cost_carrier', before)} to "
            f"{label('cost_carrier', meeting.cost_carrier)}", user.id,
            field_name="customer_relevant",
            old_value={"cost_carrier": before, "customer_relevant": not wanted},
            new_value={"cost_carrier": meeting.cost_carrier,
                       "customer_relevant": wanted,
                       "meeting_id": meeting.id})
        sales = (await session.execute(
            select(Department.id).where(Department.name == "Sales"))).scalar_one_or_none()
        if sales is not None:
            from app.services.notification_service import NotificationService
            from app.services.change_people import department_members_of_change_org
            await NotificationService.notify_team(
                session, change.project_id, [sales],
                await department_members_of_change_org(session, change, [sales]),
                title=f"Cost carrier changed: {change.change_number}",
                body=(f"The scoping meeting set '{change.title}' to "
                      f"{label('cost_carrier', meeting.cost_carrier).lower()}."),
                link=f"/changes/{change.id}?tab=scoping")

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
        waive = fields.pop("raiser_waive_reason", None)
        before = (dict(meeting.department_rasic) if meeting.department_rasic
                  else {str(i): "R" for i in meeting.selected_department_ids or []})
        if fields.get("department_rasic") is not None:
            rasic, ids = await MeetingService._validate_rasic(session, fields["department_rasic"])
            fields["department_rasic"] = rasic
            fields["selected_department_ids"] = ids
        elif "selected_department_ids" in fields and fields["selected_department_ids"] is not None:
            fields["selected_department_ids"] = await MeetingService._validate_departments(
                session, fields["selected_department_ids"])
            letters = meeting.department_rasic or {}
            await MeetingService._refuse_unroutable(session, {
                i: letters.get(str(i), "R") for i in fields["selected_department_ids"]})
            # An id-only edit drops letters for departments no longer picked.
            if meeting.department_rasic:
                keep = {str(i) for i in fields["selected_department_ids"]}
                fields["department_rasic"] = {k: v for k, v in meeting.department_rasic.items()
                                              if k in keep}
        if fields.get("participants") is not None:
            fields["participants"] = await MeetingService.resolve_participants(
                session, fields["participants"])
        if "cost_carrier" in fields:
            fields["cost_carrier"] = MeetingService._validate_cost_carrier(
                fields["cost_carrier"])
            MeetingService._refuse_internal_after_flip(change, fields["cost_carrier"])
            await MeetingService._refuse_carrier_move(
                session, change, user, fields["cost_carrier"])
        if (fields.get("department_rasic") is not None
                or fields.get("selected_department_ids") is not None):
            after = fields.get("department_rasic") or {
                str(i): "R" for i in fields.get("selected_department_ids") or []}
            await MeetingService._check_raiser_letter(
                session, change, user, after, before, waive, meeting.id)
        for k in ("meeting_date", "participants", "notes", "selected_department_ids",
                  "department_rasic", "cost_carrier"):
            if k in fields and fields[k] is not None:
                setattr(meeting, k, fields[k])
        await session.flush()
        if fields.get("cost_carrier") == "internal":
            from app.services.ppap_decision_service import PpapDecisionService
            await PpapDecisionService.notify_owed(session, change, user.id)
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
        flag_type: Optional[str] = None, check_what: Optional[str] = None,
        part_id: Optional[int] = None, answer_from: Optional[str] = None,
        scope_effect: Optional[str] = None,
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
        # C8 (spec §4, ASSESSMENT_V2): "Blocked? Ask a question". A
        # department asks Sales, the team or a supplier from its own
        # assessment; the question holds only that department's submit
        # (HARD #10). Check items are raised in scoping, never here.
        assess_question = (in_assessment and kind == "needs_info"
                           and cm_switches.on("ASSESSMENT_V2"))
        if in_assessment and kind != "risk" and not assess_question:
            raise ChangeError(
                f"'{kind}' concerns belong to scoping. During assessment "
                "the register takes risks")
        if not in_assessment and kind == "risk":
            raise ChangeError(
                "Risks belong to the assessment phase. During scoping, flag "
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
                    f"Invalid risk type '{risk_type}' for this department. One of: "
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
                if checklist_key not in checklist.accepted_keys_for(
                        dept_for_keys.name if dept_for_keys else None):
                    raise ChangeError(
                        f"'{checklist_key}' is not a checklist item for this department")
        if not (note or "").strip():
            raise ChangeError("A concern needs a note saying what the problem is")
        # C33 (spec §3, SCOPING_V2): a scoping flag is a QUESTION (blocks
        # 'proceed') or a CHECK item (the raised-for department checks it in
        # its assessment). A raise names its type; a legacy row without one
        # stays a question.
        structured = (kind == "needs_info" and not in_assessment
                      and cm_switches.on("SCOPING_V2"))
        if structured:
            flag_type, check_what, part_id, answer_from, scope_effect = \
                await MeetingService._validate_flag(
                    session, change, flag_type, check_what, part_id,
                    answer_from, scope_effect, department_id)
        elif assess_question:
            flag_type, check_what, part_id, answer_from = \
                MeetingService._validate_assessment_question(
                    change, flag_type, check_what, part_id, answer_from)
            scope_effect = None
            structured = True
        else:
            flag_type = check_what = part_id = answer_from = scope_effect = None
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
            if assess_question and not any(
                    a.department_id == department_id
                    and a.effective_status not in ("submitted", "waived")
                    for a in change.assessments):
                raise ChangeError(
                    f"{dept.name} has no open assessment on this change: a "
                    "question here holds your own submit, and there is none "
                    "left to hold")
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
        if structured:
            # C33: several questions per department; the limit is one open
            # question per asker, raised-for department and check-what (it
            # replaces the per-person-per-kind rule). Check items are a list.
            twin = next((c for c in change.concerns
                         if flag_type == "question" and c.is_open and c.is_question
                         and c.raised_by == user.id
                         and c.department_id == department_id
                         and c.check_what == check_what), None)
            if twin is not None:
                raise ChangeError(
                    f"You already asked this (#{twin.id}: {twin.note}): add to "
                    f"#{twin.id} or mark yours 'same as #{twin.id}'")
        elif kind != "risk" and any(
                c.is_open and c.raised_by == user.id and c.kind == kind
                and c.department_id == department_id
                for c in change.concerns):
            raise ChangeError(
                "You already have an open concern of this kind. Withdraw it first")
        concern = ChangeConcern(
            change_id=change.id, kind=kind, note=note.strip(), raised_by=user.id,
            department_id=department_id,
            risk_type=risk_type if kind == "risk" else None,
            severity=severity if kind == "risk" else None,
            checklist_key=checklist_key,
            flag_type=flag_type, check_what=check_what, part_id=part_id,
            answer_from=answer_from, scope_effect=scope_effect)
        session.add(concern)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_raised",
            (f"Concern ({kind}"
             + (f"/{concern.risk_type_label or concern.risk_type}, severity {concern.severity}"
                if kind == "risk" else "")
             + f"): {concern.note}") if kind == "risk" or not cm_switches.on("SCOPING_V2")
            else f"{MeetingService.flag_word(concern)} raised: {concern.note}", user.id,
            new_value={"concern_id": concern.id, "kind": kind,
                       "department_id": department_id,
                       "risk_type": concern.risk_type,
                       "risk_type_label": concern.risk_type_label,
                       "severity": concern.severity,
                       "checklist_key": checklist_key,
                       **({"flag_type": flag_type, "check_what": check_what,
                           "part_id": part_id} if structured else {})},
            notes=concern.note)
        if assess_question or (kind != "risk" and concern.answer_from == "customer"):
            # F8: a customer question at scoping is the Sales contact's task
            # too: told once when raised
            await MeetingService._tell_question_asked(session, change, concern, user)
        if kind == "reject_proposal" and change.lead_id and change.lead_id != user.id:
            # T19 / retest N11: a cancel vote holds proceed: the lead decides
            # on it (meeting), so the lead is told once
            from app.services.notification_service import NotificationService
            who = user.full_name or user.username
            await NotificationService.notify_once(
                session, [change.lead_id], kind="task_new",
                subject_key=f"concern:{concern.id}:cancel_vote",
                title=f"Cancel proposed: {change.change_number}"[:255],
                body=f"{who} proposes to cancel '{change.title}': {concern.note}",
                link=f"/changes/{change.id}?tab=scoping")
        return concern

    @staticmethod
    def _validate_assessment_question(
        change: ChangeRequest, flag_type: Optional[str], check_what: Optional[str],
        part_id: Optional[int], answer_from: Optional[str],
    ) -> tuple:
        """C8 (spec §4): a question from a department's own assessment. It
        names what it is about (check-what, part or whole change) and who can
        answer it; what it blocks is the department's own submit, so it owes
        no scope effect. A check item is a scoping act."""
        if flag_type not in (None, "question"):
            raise ChangeError(
                "In assessment you ask a question; check items are raised in "
                "scoping and checked here")
        if check_what not in CHECK_WHAT:
            raise ChangeError(
                "Pick what the question is about: one of " + ", ".join(CHECK_WHAT))
        if answer_from not in ANSWER_FROM:
            raise ChangeError(
                "Say who can answer the question: customer, our_team or supplier")
        if part_id is not None and part_id not in {
                i.part_id for i in change.impacted_items}:
            raise ChangeError(
                "Pick a part of this change's impacted set, or leave it for "
                "the whole change")
        return "question", check_what, part_id, answer_from

    @staticmethod
    async def _tell_question_asked(session: AsyncSession, change: ChangeRequest,
                                   concern: ChangeConcern, user: User) -> None:
        """C8: a question from an assessment is a task newly someone's (spec
        §0, immediate, once per question): a customer or supplier question
        goes to the Sales contact (else every Sales member, [R3]), a question
        for our team to the lead (else Project Management)."""
        from app.services.notification_service import NotificationService
        dept = (await session.get(Department, concern.department_id)
                if concern.department_id is not None else None)
        who = dept.name if dept is not None else (concern.raised_by_name or "A colleague")
        title = f"Question from {who}: {change.change_number}"[:255]
        # A3-13: the hold sentence only while the asking department's
        # submit is still open (asked after its submit, it holds nothing)
        holds = any(a.department_id == concern.department_id
                    and a.submitted_at is None
                    and a.effective_status not in ("submitted", "waived")
                    for a in change.assessments)
        body = (f"'{concern.note}'." + (f" It holds {who}'s assessment until it "
                                        "is answered." if holds else ""))
        link = f"/changes/{change.id}?tab=assessments"
        key = f"ask:{concern.id}"
        if concern.answer_from in ("customer", "supplier"):
            if change.sales_owner_id and change.sales_owner_id != user.id:
                await NotificationService.notify_once(
                    session, [change.sales_owner_id], kind="task_new",
                    subject_key=key, title=title, body=body, link=link)
                return
            sales = (await session.execute(
                select(Department.id).where(Department.name == "Sales"))
            ).scalar_one_or_none()
            if sales is not None:
                await NotificationService.notify_departments_once(
                    session, [sales], change=change, kind="task_new", subject_key=key,
                    title=title, body=body, link=link)
            return
        if change.lead_id and change.lead_id != user.id:
            await NotificationService.notify_once(
                session, [change.lead_id], kind="task_new", subject_key=key,
                title=title, body=body, link=link)
            return
        pm = (await session.execute(
            select(Department.id).where(Department.name == "Project Manager"))
        ).scalar_one_or_none()
        if pm is not None:
            await NotificationService.notify_departments_once(
                session, [pm], change=change, kind="task_new", subject_key=key,
                title=title, body=body, link=link)

    @staticmethod
    async def _validate_flag(
        session: AsyncSession, change: ChangeRequest, flag_type: Optional[str],
        check_what: Optional[str], part_id: Optional[int],
        answer_from: Optional[str], scope_effect: Optional[str],
        department_id: Optional[int],
    ) -> tuple:
        """C33: the structure of a scoping flag (spec §3 quick add / "Make it
        a question"). Returns (flag_type, check_what, part_id, answer_from,
        scope_effect), normalised. A new raise names its type (R2/R3: a
        question owes who answers and what it changes); flags from before
        C33 (flag_type NULL) stay questions, but none is raised that way."""
        if flag_type is None:
            raise ChangeError(
                "Say what it is: a check item (flag_type check: the raised-for "
                "department checks it in its assessment) or a question "
                "(flag_type question: who can answer, what the answer changes "
                "in the scope)")
        if flag_type not in FLAG_TYPES:
            raise ChangeError(
                f"Invalid flag type '{flag_type}': question or check")
        if check_what not in CHECK_WHAT:
            raise ChangeError(
                "Pick what to check: one of " + ", ".join(CHECK_WHAT))
        if part_id is not None and part_id not in {
                i.part_id for i in change.impacted_items}:
            raise ChangeError(
                "Pick a part of this change's impacted set, or leave it for "
                "the whole change")
        if flag_type == "check":
            if department_id is None:
                raise ChangeError(
                    "A check item needs the department that checks it "
                    "('Raised for')")
            await MeetingService.refuse_unroutable_check_owner(
                session, [department_id])
            return flag_type, check_what, part_id, None, None
        return (flag_type, check_what, part_id,
                *MeetingService._question_fields(answer_from, scope_effect))

    @staticmethod
    def _unroutable_reason(dept: Department) -> Optional[str]:
        """Why a department can own no check item: proceed routes an
        unrouted owner as C (A2-03), and Management (OKs only, no hours) or
        a retired department takes no task letter. None: it can."""
        from app.services.cost_sheet_service import NON_ROUTABLE_DEPARTMENTS
        if dept.name in NON_ROUTABLE_DEPARTMENTS:
            return f"{dept.name} gives OKs and books no hours, so it is never routed"
        if not dept.is_active:
            return f"{dept.name} is retired, so it cannot be routed"
        return None

    @staticmethod
    async def refuse_unroutable_check_owner(session: AsyncSession,
                                            dept_ids: list) -> None:
        """One rule everywhere (A2-03, R24): a check item is owned only by a
        department proceed can route. Refused at the raise, at 'same as'
        and at 'make it a check item', so proceed never meets it."""
        for d in dept_ids:
            dept = await session.get(Department, d) if d is not None else None
            why = MeetingService._unroutable_reason(dept) if dept else None
            if why:
                raise ChangeError(
                    f"{why}: a check item needs a department that checks it. "
                    "Raise it for that department, or make it a question")

    @staticmethod
    async def unroutable_check_owner_refusals(
            session: AsyncSession, auto_c: dict[int, list[int]]) -> list[str]:
        """Proceed's words for an open check item whose owner can take no
        task (an item from before the rule, or its department retired
        since): no override lifts it, the item is moved first."""
        out = []
        for d, ids in sorted(auto_c.items()):
            dept = await session.get(Department, d)
            why = MeetingService._unroutable_reason(dept) if dept else None
            if why:
                items = ", ".join(f"#{i}" for i in ids)
                out.append(f"{why}: its check item(s) {items} have no owner. "
                           "Make them questions or withdraw them")
        return out

    @staticmethod
    def _question_fields(answer_from: Optional[str],
                         scope_effect: Optional[str]) -> tuple[str, str]:
        """A question owes "who can answer" and "what the answer changes in
        the scope" (spec §3): if nothing in the scope hangs on it, it is a
        check item."""
        if answer_from not in ANSWER_FROM:
            raise ChangeError(
                "Say who can answer the question: customer, our_team or supplier")
        effect = (scope_effect or "").strip()
        if len(effect) < 5:
            raise ChangeError(
                "Say what the answer changes in the scope (parts, who assesses, "
                "go/no-go). Can we decide the scope without it? Then it is a "
                "check item")
        return answer_from, effect

    # ---- C33: switch type, same as / add to, Confirmed / Assumed ----------

    @staticmethod
    async def _open_scoping_flag(change: ChangeRequest, concern_id: int,
                                 session: AsyncSession) -> ChangeConcern:
        if not cm_switches.on("SCOPING_V2"):
            raise ChangeError("Questions and check items are switched off (SCOPING_V2)")
        concern = await session.get(ChangeConcern, concern_id)
        if concern is None or concern.change_id != change.id:
            raise ChangeError("Concern not found on this change")
        if concern.kind != "needs_info" or not concern.is_open:
            raise ChangeError("Only an open question or check item can be changed")
        if change.status not in SCOPING_STATUSES:
            raise ChangeError(
                "Questions and check items are sorted during capture and scoping")
        return concern

    @staticmethod
    async def set_flag_type(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        flag_type: str, *, answer_from: Optional[str] = None,
        scope_effect: Optional[str] = None, department_id: Optional[int] = None,
        check_what: Optional[str] = None,
    ) -> ChangeConcern:
        """Make it a question / make it a check item (spec §3): the asker or
        Project Management, any time during scoping [KEEP]. A question owes
        who answers and what the answer changes; a check item owes the
        department that checks it."""
        concern = await MeetingService._open_scoping_flag(change, concern_id, session)
        acting = getattr(user, "acts_as_department_id", None) is not None
        if not ((concern.raised_by == user.id and not acting)
                or await MeetingService.user_is_pm_member(session, user)):
            raise MeetingForbidden(
                "Only the person who raised it, or Project Management, may "
                "switch a question and a check item")
        if flag_type not in FLAG_TYPES:
            raise ChangeError(f"Invalid flag type '{flag_type}': question or check")
        if check_what is not None:
            if check_what not in CHECK_WHAT:
                raise ChangeError("Pick what to check: one of " + ", ".join(CHECK_WHAT))
            concern.check_what = check_what
        if department_id is not None:
            dept = await session.get(Department, department_id)
            if dept is None or not dept.is_active:
                raise ChangeError(f"Unknown or inactive department {department_id}")
            concern.department_id = department_id
        before = "check" if concern.is_check else "question"
        if flag_type == "question" and before != "question":
            # the same limit as a raise: one open question per asker,
            # raised-for department and check-what (spec §3 [R4])
            twin = next((c for c in change.concerns
                         if c.id != concern.id and c.is_open and c.is_question
                         and c.raised_by == concern.raised_by
                         and c.department_id == concern.department_id
                         and c.check_what == (concern.check_what or "other")), None)
            if twin is not None:
                raise ChangeError(
                    f"This is already asked (#{twin.id}: {twin.note}): add to "
                    f"#{twin.id} or mark it 'same as #{twin.id}'")
        if flag_type == "question":
            concern.answer_from, concern.scope_effect = MeetingService._question_fields(
                answer_from or concern.answer_from, scope_effect or concern.scope_effect)
            if concern.check_what is None:
                concern.check_what = "other"
        elif concern.department_id is None:
            raise ChangeError(
                "A check item needs the department that checks it ('Raised for')")
        else:
            await MeetingService.refuse_unroutable_check_owner(
                session, concern.owner_department_ids)
            if concern.check_what is None:
                concern.check_what = "other"
        concern.flag_type = flag_type
        await session.flush()
        if before != flag_type:
            await ChangeService.append_changelog(
                session, change, "concern_type_changed",
                f"#{concern.id} is now a {'question' if flag_type == 'question' else 'check item'}"
                f": {concern.note}", user.id,
                old_value={"concern_id": concern.id, "flag_type": before},
                new_value={"concern_id": concern.id, "flag_type": flag_type})
        return concern

    @staticmethod
    async def may_add_to(session: AsyncSession, change: ChangeRequest,
                         concern: ChangeConcern, user: User,
                         viewer: Optional[tuple[set[int], set[str]]] = None) -> bool:
        """'Add to #n' (spec §3): an open, unanswered question or check item
        in capture or scoping, by the asker, a department it is raised for,
        or whoever may answer it. Served as can_add_to (R24)."""
        if (not cm_switches.on("SCOPING_V2") or concern.kind != "needs_info"
                or not concern.is_open or concern.answered_at is not None
                or change.status not in SCOPING_STATUSES):
            return False
        acting = getattr(user, "acts_as_department_id", None) is not None
        if concern.raised_by == user.id and not acting:
            return True
        if viewer is None:
            viewer = await MeetingService.viewer_departments(session, user)
        if viewer[0] & set(concern.owner_department_ids):
            return True
        return await MeetingService.can_answer_question(
            session, change, concern, user, viewer)

    @staticmethod
    async def join_flag(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        *, department_id: Optional[int] = None, note: Optional[str] = None,
    ) -> ChangeConcern:
        """Spec §3 "same as #n" (the caller's department co-owns the item)
        and "add to #n" (a line appended to it) instead of a second flag on
        the same pick."""
        concern = await MeetingService._open_scoping_flag(change, concern_id, session)
        line = (note or "").strip()
        if department_id is None and not line:
            raise ChangeError("Say what to add, or which department it is the same for")
        if department_id is not None:
            # a department act: members only (admins act as the department),
            # as every department act of the branch; co-ownership holds that
            # department's own submit (HARD #10)
            if not await WorkflowService.actor_in_department(session, user, department_id):
                raise MeetingForbidden(
                    "'Same as' adds your own department as co-owner "
                    "(admins: act as that department)")
            dept = await session.get(Department, department_id)
            if dept is None or not dept.is_active:
                raise ChangeError(f"Unknown or inactive department {department_id}")
            if concern.is_check:
                await MeetingService.refuse_unroutable_check_owner(
                    session, [department_id])
            if department_id not in concern.owner_department_ids:
                concern.co_department_ids = [
                    *(concern.co_department_ids or []), department_id]
        if line:
            # 'add to' rewrites the question: not after it was answered (the
            # answer would no longer match it), else only by who may raise
            # it again or answer it
            if concern.answered_at is not None:
                raise ChangeError(
                    f"#{concern.id} is already answered: raise a new question "
                    "instead of adding to it")
            if not await MeetingService.may_add_to(session, change, concern, user):
                raise MeetingForbidden(
                    "Only the asker, the departments it is raised for, Sales or "
                    "Project Management may add to it")
            who = user.full_name or user.username
            concern.note = f"{concern.note}\n+ {who}: {line}"
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_joined",
            f"#{concern.id} "
            + (f"same for department {department_id}" if department_id else "")
            + (" and " if department_id and line else "")
            + (f"added to: {line}" if line else ""), user.id,
            new_value={"concern_id": concern.id, "department_id": department_id},
            notes=line or None)
        return concern

    @staticmethod
    async def _confirm_evidence(
        session: AsyncSession, change: ChangeRequest, concern: ChangeConcern,
        ref: Optional[str], mail_id: Optional[int] = None,
    ) -> Optional[str]:
        """Why this is not yet a Confirmed answer, or None (spec §0 Answer
        form): a customer question needs a filed customer mail (picked) or
        the customer's document filed on the question; anything else a
        filed document or a reference id."""
        from app.models.change import ChangeAttachment
        from app.services.cm_rules import reference_refusal
        if mail_id is not None:
            mail = await session.get(ChangeAttachment, mail_id)
            if (mail is None or mail.change_id != change.id
                    or mail.kind != "customer_email"):
                return "Pick a customer mail filed on this change"
            return None
        # a customer question: only the customer's own document (kind
        # customer_file) filed on it; an internal note is no customer answer
        customer = concern.answer_from == "customer"
        kinds = (("customer_file",) if customer
                 else ("info_response", "customer_file"))
        docs = (await session.execute(
            select(func.count()).select_from(ChangeAttachment).where(
                ChangeAttachment.change_id == change.id,
                ChangeAttachment.concern_id == concern.id,
                ChangeAttachment.kind.in_(kinds))
        )).scalar() or 0
        if docs:
            return None
        if customer:
            return ("A customer question is Confirmed only by the customer's "
                    "mail (filed on the change) or the customer's document "
                    "filed on it; without it, answer Assumed")
        return reference_refusal(ref, "Confirmed needs evidence",
                                 "a process sheet number, a drawing number or a mail")

    @staticmethod
    async def _apply_answer_form(
        session: AsyncSession, change: ChangeRequest, concern: ChangeConcern,
        *, answer_kind: str, ref: Optional[str], mail_id: Optional[int] = None,
        assumed_value: Optional[str],
        assumed_unit: Optional[str], assumed_risk: Optional[str],
        confirm_by_id: Optional[int], confirm_due,
    ) -> None:
        if answer_kind not in ANSWER_KINDS:
            raise ChangeError("Answer Confirmed (with evidence) or Assumed")
        if answer_kind == "confirmed":
            why = await MeetingService._confirm_evidence(
                session, change, concern, ref, mail_id)
            if why:
                raise ChangeError(why)
            concern.answer_kind = "confirmed"
            concern.answer_ref = await MeetingService._evidence_text(
                session, ref, mail_id)
            concern.assumed_value = concern.assumed_unit = concern.assumed_risk = None
            concern.confirm_by_id = concern.confirm_due = None
            return
        value = (assumed_value or "").strip()
        unit = (assumed_unit or "").strip()
        risk = (assumed_risk or "").strip()
        na = value.lower() in ("n/a", "na")
        if not value or (not na and not any(ch.isdigit() for ch in value)):
            raise ChangeError(
                "Assumed: give the value as a number (with its unit), or 'n/a'")
        if not na and not unit:
            raise ChangeError("Assumed: give the unit of the value")
        if len(risk) < 5:
            raise ChangeError("Assumed: say what happens if the assumption is wrong")
        named = confirm_by_id is not None
        if confirm_by_id is None:
            confirm_by_id = change.sales_owner_id or change.lead_id
        if named and not await MeetingService._may_confirm_for(
                session, change, confirm_by_id):
            raise ChangeError(
                "Who confirms must be an active colleague of this change's "
                "organization who can work on it (not a viewer)")
        if confirm_due is None:
            from app.services.due_rules import add_wd
            confirm_due = add_wd(datetime.utcnow(), 5).date()
        concern.answer_kind = "assumed"
        concern.answer_ref = (ref or "").strip() or None
        concern.assumed_value = "n/a" if na else value
        concern.assumed_unit = None if na else unit
        concern.assumed_risk = risk
        concern.confirm_by_id = confirm_by_id
        concern.confirm_due = confirm_due
        concern.confirmed_at = concern.confirmed_by = None

    #: Plain words of a check-what pick in a mail to the customer.
    CHECK_WHAT_WORDS = {
        "drawing": "drawing / 3D", "volume": "volume", "cycle_time": "cycle time",
        "weight": "part weight", "tool": "tool / cavities", "material": "material",
        "tolerance": "tolerance", "schedule": "schedule", "other": "other"}

    @staticmethod
    def customer_copy(change: ChangeRequest, concern: ChangeConcern,
                      part_number: Optional[str] = None) -> Optional[str]:
        """The mail text Sales copies for a customer question (spec §0 [R4],
        §3 "text and customer copy built from the picks"): what is asked,
        on which part, and what the answer decides. A supplier question
        (C8: Sales asks the supplier too) gets the same text, worded for the
        supplier. None for other questions."""
        if (concern.kind != "needs_info"
                or concern.answer_from not in ("customer", "supplier")):
            return None
        # F9: the customer's part number and the title without our numbers
        # (CR, article, project code); part_number is the customer's
        from app.services.customer_refs import customer_title
        topic = MeetingService.CHECK_WHAT_WORDS.get(concern.check_what or "", "")
        where = f" for part {part_number}" if part_number else ""
        whose = ("your change request" if concern.answer_from == "customer"
                 else "our change")
        name = customer_title(change.title)
        lines = [
            f"Subject: {name}: question"
            + (f" on {topic}" if topic and topic != "other" else ""),
            "",
            "Hello,",
            "",
            f"For {whose} ({name}){where} "
            "we need your answer:",
            "",
            concern.note.strip(),
        ]
        if concern.scope_effect:
            lines += ["", f"Your answer decides: {concern.scope_effect.strip()}"]
        lines += ["", "Thank you, and best regards"]
        return "\n".join(lines)

    @staticmethod
    async def _may_confirm_for(session: AsyncSession, change: ChangeRequest,
                               user_id: int) -> bool:
        """The named confirmer can act: active, of the change's organization,
        a writer (admin, or a member of an active department; a user without
        department reads only). Not the stored role: under strategy B a hub
        user's role follows a new department only at the next login."""
        u = await session.get(User, user_id)
        if u is None or not u.is_active:
            return False
        if change.project_id is not None:
            from app.models.entities import Plant, Project
            project = await session.get(Project, change.project_id)
            plant = await session.get(Plant, project.plant_id) if project else None
            if plant is not None and u.organization_id != plant.organization_id:
                return False
        if u.role == "admin":
            return True
        return bool(await WorkflowService.get_user_department_ids(session, u.id))

    @staticmethod
    async def can_confirm(session: AsyncSession, change: ChangeRequest,
                          concern: ChangeConcern, user: User,
                          viewer: Optional[tuple[set[int], set[str]]] = None) -> bool:
        """The confirm item of an Assumed answer is open and the caller may
        close it: the person named to confirm it, or anyone who may answer
        the question, in any live status, the question open or closed."""
        if not concern.confirm_open or change.status in ENDED:
            return False
        acting = getattr(user, "acts_as_department_id", None) is not None
        if concern.confirm_by_id == user.id and not acting:
            return True
        return await MeetingService.can_answer_question(
            session, change, concern, user, viewer)

    @staticmethod
    async def _evidence_text(session: AsyncSession, ref: Optional[str],
                             mail_id: Optional[int]) -> Optional[str]:
        """What the answer's evidence is called on the record: the ref, else
        the picked mail ("Mail: <file name>")."""
        text = (ref or "").strip()
        if text:
            return text
        if mail_id is not None:
            from app.models.change import ChangeAttachment
            mail = await session.get(ChangeAttachment, mail_id)
            if mail is not None:
                return f"Mail: {mail.filename}"[:255]
        return None

    @staticmethod
    async def confirm_assumption(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        ref: Optional[str] = None, mail_id: Optional[int] = None,
    ) -> ChangeConcern:
        """The confirm item of an Assumed answer: whoever was named to
        confirm it, or anyone who may answer the question, records the
        evidence; the answer becomes Confirmed. Any live status: the
        assumption travels into the assessment and the offer."""
        concern = await session.get(ChangeConcern, concern_id)
        if concern is None or concern.change_id != change.id:
            raise ChangeError("Concern not found on this change")
        if not concern.confirm_open:
            raise ChangeError("Nothing to confirm: the answer is not an open assumption")
        if change.status in ENDED:
            raise ChangeError(f"The change is {change.status}: its record stays as it is")
        if not await MeetingService.can_confirm(session, change, concern, user):
            raise MeetingForbidden(
                "Only the person named to confirm it, the asking department, "
                "Sales or Project Management may confirm this assumption")
        why = await MeetingService._confirm_evidence(
            session, change, concern, ref, mail_id)
        if why:
            raise ChangeError(why)
        concern.answer_kind = "confirmed"
        concern.answer_ref = (await MeetingService._evidence_text(
            session, ref, mail_id)) or concern.answer_ref
        concern.confirmed_at = datetime.utcnow()
        concern.confirmed_by = user.id
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "assumption_confirmed",
            f"#{concern.id} assumption {concern.assumed_value}"
            f"{' ' + concern.assumed_unit if concern.assumed_unit else ''} confirmed"
            + (f" ({ref.strip()})" if (ref or "").strip() else ""), user.id,
            new_value={"concern_id": concern.id})
        # A3-13: one action per answered question: a caller who may also
        # settle it (the asker, the asking department in assessment, PM)
        # settles it with the confirmation
        if (concern.is_question and concern.is_open
                and concern.answered_at is not None
                and await MeetingService._may_settle(session, change, concern, user)):
            await MeetingService.withdraw_concern(
                session, change, concern.id, user,
                resolution_note=f"Confirmed: {concern.answer_ref}"[:500])
        return concern

    @staticmethod
    async def _may_settle(session: AsyncSession, change: ChangeRequest,
                          concern: ChangeConcern, user: User) -> bool:
        """The close_question rule (withdraw_concern's, without raising):
        the asker (not acting), Project Management, or a member of the
        asking department while the change is in assessment."""
        acting = getattr(user, "acts_as_department_id", None) is not None
        if concern.raised_by == user.id and not acting:
            return True
        if await MeetingService.user_is_pm_member(session, user):
            return True
        return (change.status == "in_assessment" and concern.department_id is not None
                and await WorkflowService.actor_in_department(
                    session, user, concern.department_id))

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
        # Who settles it is recorded as a role (spec §16): the author
        # withdrawing their own point reads differently from Project
        # Management settling somebody else's.
        settled_as = None
        if concern.raised_by == user.id and not acting_as:
            settled_as = "author"
        elif await MeetingService.user_is_pm_member(session, user):
            settled_as = "pm"
        elif department_owns_it and any(
                [await WorkflowService.actor_in_department(session, user, d)
                 for d in concern.owner_department_ids]):
            settled_as = "department"
        allowed = settled_as is not None
        # A3-02: from the assessment on (any later status), never only in it
        if (concern.is_check
                and change.status not in ("draft", "captured", "scoping")
                and cm_switches.on("ASSESSMENT_V2")
                and (settled_as in ("department", "pm")
                     or user.effective_role == "admin"
                     or await MeetingService._owner_department_of(
                         session, concern, user) is not None)):
            # spec §4 (R4): the department closes its check item with what it
            # found, not with a free note (POST .../check); so does a member
            # who raised it for their own department, and Project Management.
            # Only a raiser outside the department drops their own item here.
            raise ChangeError(
                "Close a check item with what you found: Answered (a number "
                "with its unit, a reference or a file), Not relevant (checklist "
                "row, drawing reference, outside our scope or same as another "
                "item) or Assumed")
        if not allowed:
            raise ChangeError(
                "Only a member of the department it was raised for, or "
                "Project Management, may close it"
                if department_owns_it else
                "Only the person who raised it, or Project Management, may "
                "close it")
        if concern.department_id is not None and not note:
            # A department-attributed flag owes its resolution — how was the
            # point addressed, on the record.
            what = ("check item" if concern.is_check else "question"
                    if concern.kind == "needs_info" else "point")
            raise ChangeError(
                f"Closing a department's {what} needs a resolution note: "
                "how was it addressed?")
        if (concern.kind == "needs_info" and not concern.is_check
                and concern.department_id is not None
                and change.status == "in_assessment"
                and cm_switches.on("ASSESSMENT_V2")):
            # R4: an assessment question is settled with what settled it,
            # not 'ok' (the answer itself is checked by answer_concern)
            from app.services.cm_rules import says_what
            if not says_what(note):
                raise ChangeError(
                    f"Say what settles it, e.g. 'answer confirms 2.4 mm wall': "
                    f"'{note}' says too little")
        concern.withdrawn_at = datetime.utcnow()
        concern.withdrawn_by = user.id
        concern.settled_as = settled_as
        concern.resolution_note = note or None
        await session.flush()
        # The changelog row IS the thread: question (concern_raised) then
        # answer (concern_withdrawn), each with its note and its actor.
        from app.services.cm_labels import label
        await ChangeService.append_changelog(
            session, change,
            "concern_withdrawn",
            f"{MeetingService.flag_word(concern)} #{concern.id}: "
            f"{label('settled_as', settled_as).lower()}"
            + (f": {concern.resolution_note}" if concern.resolution_note else ""),
            user.id,
            old_value={"concern_id": concern.id},
            new_value={"settled_as": settled_as},
            notes=concern.resolution_note)
        if settled_as == "pm" and concern.raised_by not in (None, user.id) \
                and concern.kind == "needs_info":
            # spec §3 scoping record: a question closed over the asker tells
            # the asker (once per question)
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [concern.raised_by], kind="concern_settled",
                subject_key=f"settled:{concern.id}",
                title=f"Your {'check item' if concern.is_check else 'question'} "
                      f"was closed: {change.change_number}"[:255],
                body=(f"Project Management closed '{concern.note}'"
                      + (f": {concern.resolution_note}" if concern.resolution_note else "")),
                link=f"/changes/{change.id}?tab=scoping")
        return concern

    # ---- spec §4: the department checks its check items -------------------

    @staticmethod
    async def _owner_department_of(session: AsyncSession, concern: ChangeConcern,
                                   user: User) -> Optional[int]:
        """The owning department the caller acts for (raised-for first, then
        co-owners), or None. An admin acts as the raised-for department."""
        for d in concern.owner_department_ids:
            if await WorkflowService.actor_in_department(session, user, d):
                return d
        if user.effective_role == "admin" and concern.owner_department_ids:
            return concern.owner_department_ids[0]
        return None

    @staticmethod
    async def close_check(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        *, outcome: str, value: Optional[str] = None, unit: Optional[str] = None,
        ref: Optional[str] = None, basis: Optional[str] = None,
        checklist_key: Optional[str] = None, who: Optional[str] = None,
        same_as_id: Optional[int] = None, assumed_risk: Optional[str] = None,
        confirm_by_id: Optional[int] = None, confirm_due=None,
    ) -> ChangeConcern:
        """Spec §4 "Check items first": the owning department closes its
        check item inline with what it found. Answered: a number with its
        unit, a reference or a file filed on the item. Not relevant: a
        checklist row or a drawing reference, outside our scope + who owns
        it, or the same as another item. Assumed: value + unit (or n/a), the
        risk if wrong, who confirms by when (the confirm item). Closing it
        lifts the department's own hold (HARD #10); the raiser's and the
        lead's digest count it, and either may reopen it."""
        from app.models.change import (
            CHECK_OUTCOMES, NOT_RELEVANT_BASES, ChangeAttachment)
        from app.services import assessment_checklist as checklist
        from app.services.cm_rules import reference_refusal
        if not cm_switches.on("ASSESSMENT_V2"):
            raise ChangeError("Closing check items inline is switched off (ASSESSMENT_V2)")
        concern = await session.get(ChangeConcern, concern_id)
        if concern is None or concern.change_id != change.id:
            raise ChangeError("Concern not found on this change")
        if not concern.is_check or not concern.is_open:
            raise ChangeError("Only an open check item is closed this way")
        if change.status not in ("in_assessment", "costing"):
            # A3-02: an item still open in costing (a consulted department
            # owes no submit) is closed there too, with the same evidence
            raise ChangeError("Check items are closed in the assessment or costing")
        dept_id = await MeetingService._owner_department_of(session, concern, user)
        settled_as = "department"
        if (dept_id is None and concern.owner_department_ids
                and await MeetingService.user_is_pm_member(session, user)):
            # Project Management closes it for the department, with the same
            # evidence (R4: never a free note)
            dept_id, settled_as = concern.owner_department_ids[0], "pm"
        if dept_id is None:
            raise MeetingForbidden(
                "Only the department this check item was raised for, or Project "
                "Management, closes it")
        if outcome not in CHECK_OUTCOMES:
            raise ChangeError("Say what you found: answered, not_relevant or assumed")
        value = (value or "").strip()
        unit = (unit or "").strip()
        ref = (ref or "").strip()
        if outcome == "answered":
            # A3-10 (R4): the department's own evidence: a file filed on the
            # item after it was raised, not by its raiser (the raise-time
            # attachment is the question, not the answer)
            files = (await session.execute(
                select(func.count()).select_from(ChangeAttachment).where(
                    ChangeAttachment.change_id == change.id,
                    ChangeAttachment.concern_id == concern.id,
                    ChangeAttachment.uploaded_by != concern.raised_by,
                    ChangeAttachment.created_at >= concern.raised_at))).scalar() or 0
            if value:
                if not any(ch.isdigit() for ch in value):
                    raise ChangeError("Answered: the value is a number, e.g. 2.4")
                if not unit:
                    raise ChangeError("Answered: give the unit of the value, e.g. mm")
                text = f"{value} {unit}" + (f" ({ref})" if ref else "")
            elif ref:
                why = reference_refusal(ref, "Answered needs evidence",
                                        "a drawing number, a report or a mail")
                if why:
                    raise ChangeError(why)
                text = ref
            elif files:
                text = "see the file filed on the item"
            else:
                raise ChangeError(
                    "Answered needs evidence: a number with its unit, a "
                    "reference (drawing, report, mail) or a file filed on the item")
        elif outcome == "not_relevant":
            if basis not in NOT_RELEVANT_BASES:
                raise ChangeError(
                    "Not relevant: say why (checklist row, drawing reference, "
                    "outside our scope, or same as another item)")
            if basis == "checklist_row":
                dept = await session.get(Department, dept_id)
                if checklist_key not in checklist.accepted_keys_for(
                        dept.name if dept else None):
                    raise ChangeError(
                        "Not relevant: pick the checklist row of your department "
                        "that answers it")
                text = (f"not relevant: checklist row "
                        f"'{checklist.label_for(checklist_key, dept.name if dept else None) or checklist_key}'")
                ref = checklist_key
            elif basis == "drawing_ref":
                why = reference_refusal(ref, "Not relevant needs the drawing reference",
                                        "DRW-4471 rev C")
                if why:
                    raise ChangeError(why)
                text = f"not relevant: drawing {ref}"
            elif basis == "outside_scope":
                owner = (who or "").strip()
                if len(owner) < 3:
                    raise ChangeError(
                        "Outside our scope: say who owns it (a department, the "
                        "customer or a supplier)")
                text = f"outside our scope, owned by {owner}"
                ref = owner
            else:
                other = (await session.get(ChangeConcern, same_as_id)
                         if same_as_id is not None else None)
                if (other is None or other.change_id != change.id
                        or other.id == concern.id or other.kind == "risk"):
                    raise ChangeError(
                        "Same as: pick another question or check item on this change")
                text = f"same as #{other.id}"
                ref = f"#{other.id}"
        else:
            await MeetingService._apply_answer_form(
                session, change, concern, answer_kind="assumed", ref=ref or None,
                assumed_value=value, assumed_unit=unit, assumed_risk=assumed_risk,
                confirm_by_id=confirm_by_id, confirm_due=confirm_due)
            text = (f"assumed {concern.assumed_value}"
                    f"{' ' + concern.assumed_unit if concern.assumed_unit else ''}"
                    f", risk if wrong: {concern.assumed_risk}")
        if outcome != "assumed":
            concern.answer_ref = (ref or None) and ref[:255]
        concern.check_outcome = outcome
        concern.withdrawn_at = datetime.utcnow()
        concern.withdrawn_by = user.id
        concern.settled_as = settled_as
        concern.resolution_note = text
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_withdrawn",
            f"Check item #{concern.id} checked: {text}", user.id,
            old_value={"concern_id": concern.id},
            new_value={"settled_as": settled_as, "check_outcome": outcome,
                       "department_id": dept_id},
            notes=text)
        if outcome == "assumed" and concern.confirm_by_id not in (None, user.id):
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [concern.confirm_by_id], kind="confirm_assumption",
                subject_key=f"confirm:{concern.id}",
                title=f"Confirm an assumption: {change.change_number}"[:255],
                body=f"{text} for '{concern.note}'",
                link=f"/changes/{change.id}?tab=assessments")
        return concern

    @staticmethod
    def check_due(change: ChangeRequest, department_id: int):
        """C8/R5: when a department's check items are due: its own open
        assessment row's due date, else (a consulted row has none) the
        change's assessment due, the earliest of the R/A rows. None when
        no row carries one."""
        own = [a.effective_due_date for a in change.assessments
               if a.department_id == department_id
               and a.effective_due_date is not None
               and a.effective_status not in ("submitted", "waived")]
        if own:
            return min(own)
        stage = [a.effective_due_date for a in change.assessments
                 if a.rasic_letter in BLOCKING_LETTERS
                 and a.effective_due_date is not None]
        return min(stage) if stage else None

    @staticmethod
    def reopen_check_refusal(change: ChangeRequest, concern: ChangeConcern,
                             user: User) -> Optional[tuple[bool, str]]:
        """Why the caller may not reopen this check item, as (forbidden,
        text), or None. One rule for POST .../reopen and the served
        can_reopen (R24): a closed check item (by its department, Project
        Management, or its raiser before the evidence rule; not retracted),
        the raiser or the lead, while an owning department's assessment is
        still open."""
        from app.services.change_people import holds_lead
        if (not concern.is_check or concern.is_open
                or concern.withdrawn_at is None or concern.retracted_at is not None):
            return False, "Only a closed check item can be reopened"
        acting = getattr(user, "acts_as_department_id", None) is not None
        if not ((concern.raised_by == user.id and not acting)
                or holds_lead(change, user)):
            return True, ("Only the person who raised the check item or the "
                          "change lead may reopen it")
        # R5/R37: name an exit that exists (no per-department send-back yet,
        # open question C16): in assessment the department records it as a
        # risk on its assessment; later the lead changes the impacted set
        # (costing reopens) or, from quoted on, opens a scope change.
        lead = change.lead_name or "the change lead"
        if change.status != "in_assessment":
            return False, (
                "Assessment is over, so the check item stays closed: if its "
                f"answer is wrong, tell {lead}, who changes the impacted set "
                "(that reopens the costing) or opens a scope change after the offer")
        if not any(a.department_id in concern.owner_department_ids
                   and a.effective_status not in ("submitted", "waived")
                   for a in change.assessments):
            return False, (
                "The department already submitted its assessment, so the check "
                "item stays closed: if its answer is wrong, ask the department "
                f"to record it as a risk on its assessment ({lead} sees it)")
        return None

    @staticmethod
    async def reopen_check(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        reason: Optional[str],
    ) -> ChangeConcern:
        """Spec §4: the raiser or the lead reopens a check item its
        department closed, with a reason, while that department still has
        its assessment open (after the submit there is no hold left)."""
        if not cm_switches.on("ASSESSMENT_V2"):
            raise ChangeError("Reopening check items is switched off (ASSESSMENT_V2)")
        concern = await session.get(ChangeConcern, concern_id)
        if concern is None or concern.change_id != change.id:
            raise ChangeError("Concern not found on this change")
        refusal = MeetingService.reopen_check_refusal(change, concern, user)
        if refusal is not None:
            forbidden, text = refusal
            raise (MeetingForbidden if forbidden else ChangeError)(text)
        why = (reason or "").strip()
        if len(why) < 5:
            raise ChangeError("Say why you reopen it (at least 5 characters)")
        closer = concern.withdrawn_by
        concern.withdrawn_at = concern.withdrawn_by = None
        concern.settled_as = concern.check_outcome = None
        concern.resolution_note = None
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_reopened",
            f"Check item #{concern.id} reopened: {why}", user.id,
            new_value={"concern_id": concern.id}, notes=why)
        if closer not in (None, user.id):
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [closer], kind="check_reopened",
                subject_key=f"reopen:{concern.id}",
                title=f"Check item reopened: {change.change_number}"[:255],
                body=f"'{concern.note}': {why}",
                link=f"/changes/{change.id}?tab=assessments")
        return concern

    @staticmethod
    async def _decider_department_id(session: AsyncSession, user: User) -> Optional[int]:
        """The department a meeting-decision question is asked for: the
        decider's. Acting as a department, that one; else Project Management
        when the decider sits there; else their only department. None when it
        cannot be told (no or several memberships): the decider is the asker."""
        acting = getattr(user, "acts_as_department_id", None)
        if acting is not None:
            return acting
        mine = await WorkflowService.effective_department_ids(session, user)
        pm_dept = (await session.execute(
            select(Department.id).where(Department.name == "Project Manager"))
        ).scalar_one_or_none()
        if pm_dept is not None and pm_dept in mine:
            return pm_dept
        return mine[0] if len(mine) == 1 else None

    @staticmethod
    async def viewer_departments(session: AsyncSession,
                                 user: User) -> tuple[set[int], set[str]]:
        """The caller's effective department ids and names, read once for a
        whole list (R34, A2-10): pass as `viewer` to can_answer_question,
        can_confirm and may_add_to."""
        mine = set(await WorkflowService.effective_department_ids(session, user))
        names = set((await session.execute(
            select(Department.name).where(Department.id.in_(mine)))).scalars().all()) \
            if mine else set()
        return mine, names

    @staticmethod
    async def can_answer_question(
        session: AsyncSession, change: ChangeRequest, concern: ChangeConcern,
        user: User, viewer: Optional[tuple[set[int], set[str]]] = None,
    ) -> bool:
        """Who may answer a scoping question (needs_info, 2026-10-14).

        The question stays the ASKING side's task: members of the department
        it was asked for (department_id) or, with none, its author. Sales
        (the customer's contact) and Project Management may answer too; from
        the assessment on, the lead answers a question for our team.
        Acts-as is exactly that department: the acting admin's personal
        authorship and real memberships step aside, and so does the admin
        bypass (effective_role). Answering is not closing: see
        withdraw_concern."""
        if user.effective_role == "admin":
            return True
        # C8: a question for our team from an assessment is routed to the
        # lead (task and notice): the lead answers it, whatever their
        # department (an internal change's engineering lead, P3), R5
        if (concern.answer_from == "our_team"
                and change.status not in ("captured", "scoping")):
            from app.services.change_people import holds_lead
            if holds_lead(change, user):
                return True
        if viewer is None:
            viewer = await MeetingService.viewer_departments(session, user)
        mine, names = viewer
        acting = getattr(user, "acts_as_department_id", None) is not None
        if concern.department_id is not None:
            if concern.department_id in mine:
                return True
        elif not acting and concern.raised_by == user.id:
            return True
        if not mine:
            return False
        return bool(names & {"Sales", "Project Manager"})

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
        # The question is the decider's department's (2026-10-14): they own
        # the task, and they, Sales or Project Management answer it.
        dept_id = await MeetingService._decider_department_id(session, user)
        if any(c.is_open and c.kind == "needs_info" and c.department_id == dept_id
               and c.raised_by == user.id for c in change.concerns):
            return None
        # A2-05 (SCOPING_V2): every scoping raise names its type, who answers
        # and what the answer changes: the decider's team answers it (Sales
        # or PM may too), the reason is what it changes (the start)
        from app.services import mother_plants as mp
        typed = cm_switches.on("SCOPING_V2") and not mp.is_mother_plant(change)
        concern = ChangeConcern(
            change_id=change.id, kind="needs_info", note=reason.strip(),
            raised_by=user.id, department_id=dept_id,
            raised_by_meeting_id=meeting_id,
            **({"flag_type": "question", "check_what": "other",
                "answer_from": "our_team",
                "scope_effect": f"Decides whether the change can start: {reason.strip()}"}
               if typed else {}))
        session.add(concern)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "concern_raised",
            f"{MeetingService.flag_word(concern)} raised: {concern.note}"
            if typed else f"Concern (needs_info): {concern.note}", user.id,
            new_value={"concern_id": concern.id, "kind": "needs_info",
                       "department_id": dept_id, "meeting_id": meeting_id},
            notes=concern.note)
        return concern

    @staticmethod
    async def answer_concern(
        session: AsyncSession, change: ChangeRequest, concern_id: int, user: User,
        note: Optional[str] = None, *, answer_kind: Optional[str] = None,
        ref: Optional[str] = None, mail_id: Optional[int] = None,
        assumed_value: Optional[str] = None,
        assumed_unit: Optional[str] = None, assumed_risk: Optional[str] = None,
        confirm_by_id: Optional[int] = None, confirm_due=None,
    ) -> ChangeConcern:
        """Somebody writes the answer to an open question: a COMMENT on it,
        not a verdict on it. In scoping: the asking department (or the
        author), Sales or Project Management (can_answer_question).

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
        # A scoping QUESTION stays the asking side's (2026-10-14): the asking
        # department or the author answers it, or Sales (the customer's
        # contact) or Project Management. Words are enough.
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
        # C8 (ASSESSMENT_V2): a question asked from an assessment is answered
        # like any question (asking department, Sales, PM; answer form); a
        # check item is not answered by others, its department closes it.
        v2 = cm_switches.on("ASSESSMENT_V2") and change.status == "in_assessment"
        if v2 and concern.is_check:
            raise ChangeError(
                "A check item is closed by the department it was raised for, in "
                "its assessment (Answered / Not relevant / Assumed)")
        departmental = (concern.department_id is not None
                        and change.status == "in_assessment"
                        # a hold from before C8 (flag_type NULL) stays a
                        # proposal in flight; only a typed question is
                        # answered as a question
                        and not (v2 and concern.flag_type == "question"))
        if departmental:
            if not await ChangeService.has_info_response(
                    session, change, concern_id=concern.id):
                raise ChangeError(
                    "A proposal needs its documentation attached (PPT)")
        else:
            if not await MeetingService.can_answer_question(
                    session, change, concern, user):
                # A2-09: name the owning department; the asker answers only a
                # question raised for no department
                owner = None
                if concern.department_id is not None:
                    dept = await session.get(Department, concern.department_id)
                    owner = dept.name if dept else f"department {concern.department_id}"
                raise ChangeError(
                    f"Only {owner or 'the person who asked'}, Sales or Project "
                    "Management may answer this question")
            # C33 answer form (spec §0): Confirmed (evidence) or Assumed
            # (value + unit, risk if wrong, who confirms by when). With
            # SCOPING_V2 on, every scoping question (legacy untyped ones
            # included, A2-02) and a C8 question from an assessment take the
            # form: "ok" is no answer (R4). Switched off, the free answer
            # stands.
            from app.services import mother_plants as mp
            scoping_q = (change.status in SCOPING_STATUSES and concern.is_question
                         and not mp.is_mother_plant(change))
            if (answer_kind is None and cm_switches.on("SCOPING_V2")
                    and (scoping_q or (v2 and concern.flag_type == "question"))):
                raise ChangeError(
                    "Answer it Confirmed (with its evidence: a filed mail, a "
                    "document or a reference) or Assumed (value with its unit, "
                    "the risk if wrong)")
            if answer_kind is not None:
                if not cm_switches.on("SCOPING_V2"):
                    raise ChangeError(
                        "Confirmed / Assumed answers are switched off (SCOPING_V2)")
                await MeetingService._apply_answer_form(
                    session, change, concern, answer_kind=answer_kind, ref=ref,
                    mail_id=mail_id, assumed_value=assumed_value, assumed_unit=assumed_unit,
                    assumed_risk=assumed_risk, confirm_by_id=confirm_by_id,
                    confirm_due=confirm_due)
            # An answer needs content — either words, or the document that
            # carries them filed into this question's container.
            elif not note and not await ChangeService.has_info_response(
                    session, change, concern_id=concern.id):
                raise ChangeError(
                    "An answer needs content: write it or attach the response "
                    "document")
        concern.answer_note = note or None
        concern.answered_at = datetime.utcnow()
        concern.answered_by = user.id
        await session.flush()
        form = ""
        if concern.answer_kind == "assumed":
            form = (f" (Assumed: {concern.assumed_value}"
                    f"{' ' + concern.assumed_unit if concern.assumed_unit else ''})")
        elif concern.answer_kind == "confirmed":
            form = " (Confirmed" + (f": {concern.answer_ref}" if concern.answer_ref else "") + ")"
        await ChangeService.append_changelog(
            session, change, "concern_answered",
            f"{MeetingService.flag_word(concern)} #{concern.id} answered{form}"
            + (f": {note}" if note else "" if form else " (see attached document)"),
            user.id,
            new_value={"concern_id": concern.id, "answer_kind": concern.answer_kind},
            notes=note or None)
        if v2 and concern.raised_by != user.id:
            # C8: the asker hears the answer (a badge, once per question)
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [concern.raised_by], kind="question_answered",
                subject_key=f"answered:{concern.id}",
                title=f"Your question was answered: {change.change_number}"[:255],
                body=f"'{concern.note}': {note or concern.answer_ref or concern.assumed_value or 'see the attached document'}"[:1000],
                link=f"/changes/{change.id}?tab=assessments")
        if answer_kind == "assumed" and concern.confirm_by_id not in (None, user.id):
            # task newly theirs (spec §0): the confirm item, once per question
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [concern.confirm_by_id], kind="confirm_assumption",
                subject_key=f"confirm:{concern.id}",
                title=f"Confirm an assumption: {change.change_number}"[:255],
                body=(f"Assumed {concern.assumed_value}"
                      f"{' ' + concern.assumed_unit if concern.assumed_unit else ''} "
                      f"for '{concern.note}'"
                      + (f"; confirm by {concern.confirm_due:%a %d %b}"
                         if concern.confirm_due else "")),
                link=f"/changes/{change.id}?tab=scoping")
        return concern

    @staticmethod
    def flag_word(concern: ChangeConcern) -> str:
        """R37 four words: the name a flag has in what users read (SCOPING_V2:
        Question / Check item / Cancel vote / Risk); switched off, Concern."""
        if not cm_switches.on("SCOPING_V2"):
            return "Concern"
        if concern.kind == "reject_proposal":
            return "Cancel vote"
        if concern.kind == "risk":
            return "Risk"
        return "Check item" if concern.is_check else "Question"

    @staticmethod
    def open_department_concerns(
        change: ChangeRequest, department_id: int,
    ) -> list[ChangeConcern]:
        """Open concerns holding one department's assessment."""
        return [c for c in change.concerns
                if c.is_open and c.kind != "risk"
                and c.department_id == department_id]

    @staticmethod
    def open_blocking(change: ChangeRequest) -> list[ChangeConcern]:
        """The open flags that hold 'proceed' (HARD #2): cancel votes and
        questions. C33 check items never do (SCOPING_V2): they go to their
        department's assessment as conditions of the go."""
        flags = MeetingService.open_concerns(change)
        if not cm_switches.on("SCOPING_V2"):
            return flags
        return [c for c in flags if not c.is_check]

    @staticmethod
    def unrouted_check_owners(change: ChangeRequest,
                              meeting: Optional[ChangeMeeting] = None) -> dict[int, list[int]]:
        """Spec §3 "Not routed": owner departments of open check items that
        the meeting does not route with a task letter (R/A/S/C; I = told
        only), each with its item ids. Such an item would leave proceed with
        no owner, no due and no task (R18). `meeting`: else the latest
        undecided one; no meeting yet: nothing (the dialog asks for
        departments first)."""
        checks = MeetingService.open_checks(change)
        if not checks:
            return {}
        if meeting is None:
            meeting = next((m for m in reversed(change.meetings or [])
                            if m.decision is None), None)
        if meeting is None:
            return {}
        if meeting.department_rasic:
            routed = {int(k) for k, v in meeting.department_rasic.items() if v != "I"}
        else:
            routed = set(meeting.selected_department_ids or [])
        out: dict[int, list[int]] = {}
        for c in checks:
            for d in c.owner_department_ids:
                if d not in routed:
                    out.setdefault(d, []).append(c.id)
        return out

    @staticmethod
    async def _route_unrouted_checks(session: AsyncSession, change: ChangeRequest,
                                     meeting: ChangeMeeting, user: User,
                                     auto_c: dict[int, list[int]]) -> None:
        """Spec §3 "Not routed" (SOFT, A2-03): proceed routes each owner
        department of open check items that the meeting skips (or marks I)
        as C, so every item leaves with an owner, a due and a task (R18).
        `auto_c`: department id -> its item ids (unrouted_check_owners).
        Logged; the lead may pick R or reassign before proceeding."""
        letters = (dict(meeting.department_rasic) if meeting.department_rasic
                   else {str(i): "R" for i in meeting.selected_department_ids or []})
        for d in auto_c:
            letters[str(d)] = "C"
        meeting.department_rasic = letters
        meeting.selected_department_ids = list(dict.fromkeys(
            [*(meeting.selected_department_ids or []), *auto_c]))
        names = dict((await session.execute(select(Department.id, Department.name).where(
            Department.id.in_(list(auto_c))))).all())
        parts = []
        for d in auto_c:
            n = len(auto_c[d])
            parts.append(f"{names.get(d, f'department {d}')} "
                         f"({n} check item{'s' if n != 1 else ''})")
        await ChangeService.append_changelog(
            session, change, "unrouted_checks_routed",
            f"Proceed routes {', '.join(parts)} as C: "
            "they own open check items the meeting did not route", user.id,
            new_value={"meeting_id": meeting.id,
                       "department_ids": list(auto_c), "letter": "C"})
        await session.flush()

    @staticmethod
    def open_checks(change: ChangeRequest) -> list[ChangeConcern]:
        """Open C33 check items (empty with SCOPING_V2 off)."""
        if not cm_switches.on("SCOPING_V2"):
            return []
        return [c for c in MeetingService.open_concerns(change) if c.is_check]

    @staticmethod
    async def open_check_text(session: AsyncSession, change: ChangeRequest,
                              exclude_departments: frozenset = frozenset()
                              ) -> Optional[str]:
        """A3-02 (spec §5, ASSESSMENT_V2): the check items still open, by
        owning department with its due: 'Check items open: Toolshop #12, #14
        (due Thu 22 Oct)'. A consulted department owes no submit, so its
        items would hold nothing otherwise. Departments in
        exclude_departments are named elsewhere (their open submit)."""
        if not cm_switches.on("ASSESSMENT_V2"):
            return None
        # Read on guard paths (leaving costing) whose caller may not have
        # loaded the concerns: an async lazy load would raise MissingGreenlet
        from sqlalchemy import inspect as _inspect
        if "concerns" in _inspect(change).unloaded:
            await session.refresh(change, ["concerns"])
        by_dept: dict[int, list[int]] = {}
        for c in MeetingService.open_checks(change):
            owners = c.owner_department_ids
            if not owners or set(owners) & set(exclude_departments):
                continue
            by_dept.setdefault(owners[0], []).append(c.id)
        if not by_dept:
            return None
        names = dict((await session.execute(
            select(Department.id, Department.name).where(
                Department.id.in_(by_dept)))).all())
        parts = []
        for d, ids in by_dept.items():
            due = MeetingService.check_due(change, d)
            parts.append(f"{names.get(d, f'dept {d}')} "
                         + ", ".join(f"#{i}" for i in sorted(ids))
                         + (f" ({due.strftime('due %a %d %b')})" if due else ""))
        return "Check items open: " + ", ".join(parts)

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
    async def open_flags_refusal(
        session: AsyncSession, open_concerns: list[ChangeConcern],
    ) -> str:
        """Why 'proceed' is refused, naming every open flag: kind, author,
        department, note. The UI shows the same list in its warning dialog."""
        dept_ids = {c.department_id for c in open_concerns if c.department_id}
        names = dict((await session.execute(
            select(Department.id, Department.name).where(
                Department.id.in_(dept_ids)))).all()) if dept_ids else {}
        kinds = {"needs_info": "question", "reject_proposal": "cancel vote"}
        lines = []
        for c in sorted(open_concerns, key=lambda c: c.id):
            who = c.raised_by_name or f"user #{c.raised_by}"
            if c.department_id:
                who += f" ({names.get(c.department_id, c.department_id)})"
            line = f"{kinds.get(c.kind, c.kind)} by {who}: {c.note}"
            if c.kind == "needs_info" and c.is_answered:
                # A2-04: the ball is with the asker, who settles it
                asker = (names.get(c.department_id) if c.department_id
                         else c.raised_by_name) or f"user #{c.raised_by}"
                line += f" (answered, {asker} settles)"
            lines.append(line)
        if cm_switches.on("SCOPING_V2"):
            return (f"{len(open_concerns)} open question(s) or cancel vote(s) "
                    "block proceed (check items do not): "
                    + "; ".join(lines)
                    + ". Each must be withdrawn or settled first (its asker or "
                    "Project Management), or made a check item if the scope "
                    "can be decided without it")
        return (f"{len(open_concerns)} open concern(s) block 'proceed': "
                + "; ".join(lines)
                + ". Each must be withdrawn or settled first (its author or "
                "Project Management), or answered by a 'needs info' or "
                "'reject' decision")

    @staticmethod
    async def _asking_sides(session: AsyncSession,
                            concerns: list[ChangeConcern]) -> list[str]:
        """Who the open questions wait on, in words: the asking department,
        else the asker; each once, in question order."""
        dept_ids = {c.department_id for c in concerns if c.department_id}
        names = dict((await session.execute(
            select(Department.id, Department.name).where(
                Department.id.in_(dept_ids)))).all()) if dept_ids else {}
        return MeetingService.asking_sides(concerns, names)

    @staticmethod
    def asking_sides(concerns: list[ChangeConcern], names: dict,
                     change: Optional[ChangeRequest] = None) -> list[str]:
        """_asking_sides with the department names at hand (lists). With
        the change, each side carries the due weekday of its earliest open
        question (the task rule: 2 wd, 1 wd urgent): "Sales Thu"."""
        from app.services import due_rules
        out: list[str] = []
        due: dict[str, datetime] = {}
        for c in sorted(concerns, key=lambda c: c.id):
            side = (names.get(c.department_id) if c.department_id
                    else c.raised_by_name or f"user #{c.raised_by}")
            if not side:
                continue
            if side not in out:
                out.append(side)
            if change is not None and c.raised_at is not None:
                d = due_rules.task_due(c.raised_at, change, "obtain_info")
                due[side] = min(d, due.get(side, d))
        return [f"{s} {due[s]:%a}" if s in due else s for s in out]

    @staticmethod
    def split_answered(concerns: list[ChangeConcern]) -> tuple[list, list]:
        """(unanswered, answered) open questions; a cancel vote is never
        answered (A2-04: an answered question waits on its asker)."""
        answered = [c for c in concerns if c.is_question and c.is_answered]
        return [c for c in concerns if c not in answered], answered

    @staticmethod
    def waiting_words(concerns: list[ChangeConcern], names: dict,
                      change: Optional[ChangeRequest] = None) -> str:
        """'waiting for 2 answers (Sales Thu, Process Fri); 1 answered,
        Quality settles' (A2-04)."""
        unanswered, answered = MeetingService.split_answered(concerns)
        parts = []
        if unanswered:
            sides = MeetingService.asking_sides(unanswered, names, change)
            parts.append(f"waiting for {len(unanswered)} answer"
                         f"{'s' if len(unanswered) != 1 else ''} ({', '.join(sides)})")
        if answered:
            settlers = MeetingService.asking_sides(answered, names)
            parts.append(f"{len(answered)} answered, {', '.join(settlers)} "
                         f"settle{'s' if len(settlers) == 1 else ''}")
        return "; ".join(parts)

    @staticmethod
    async def proceed_holds(session: AsyncSession, change: ChangeRequest, *,
                            names: Optional[dict] = None,
                            entered: Optional[datetime] = None,
                            with_text: bool = True,
                            meeting: Optional[ChangeMeeting] = None) -> list[dict]:
        """What holds 'proceed' outside the meeting form (departments, R/A,
        cost carrier and the urgent need-by are answered in the proceed
        dialog): open questions and cancel votes (HARD #2), Quality's PPAP
        decision and the flip's Sales answer (HARD #7), an empty impacted
        set (HARD #1). Check items whose owner the meeting does not route
        hold nothing (spec §3 "Not routed" is SOFT, A2-03): proceed routes
        that department as C (_route_unrouted_checks).
        Each {key, owner, text, n?, due?}, owner and due in
        words, so the PM's scoping row, the change's checklist and the
        refusal name every hold at once, each with its owner. `names`:
        department id -> name (else read); `entered`: when the change
        entered scoping (the PPAP decision's start; else no due);
        with_text=False skips the questions' refusal text (lists: no
        query per change)."""
        from app.services import due_rules
        from app.services.ppap_decision_service import applies, flip_open
        out: list[dict] = []
        blocking = MeetingService.open_blocking(change)
        if blocking:
            if names is None:
                ids = {c.department_id for c in blocking if c.department_id}
                names = dict((await session.execute(
                    select(Department.id, Department.name).where(
                        Department.id.in_(ids)))).all()) if ids else {}
            out.append({"key": "questions", "n": len(blocking),
                        "owner": ", ".join(MeetingService.asking_sides(
                            blocking, names, change)),
                        "text": (await MeetingService.open_flags_refusal(
                            session, blocking) if with_text else "")})
        if applies(change) and change.ppap_decision is None:
            due = (due_rules.task_due(entered, change, "ppap_decision")
                   if entered is not None else None)
            out.append({"key": "ppap_decision",
                        "owner": "Quality" + (f", due {due:%a}" if due else ""),
                        **({"due": due} if due else {}),
                        "text": "Proceed waits for Quality's PPAP decision "
                                "(parameters / tool / material / cycle time "
                                "changed on any part?). No override lifts it"})
        if flip_open(change):
            who = change.sales_owner_name or "Sales"
            due = due_rules.task_due(change.customer_flip_at, change, "customer_flip")
            out.append({"key": "customer_flip",
                        "owner": f"{who}, due {due:%a}", "due": due,
                        "text": f"The change became a customer change; proceed "
                                f"waits for {who}: customer notification only, "
                                "or offer needed?"})
        if not change.impacted_items and change.impact_confirmed_at is None:
            out.append({"key": "impacted_items",
                        "owner": change.lead_name or "Project Management",
                        "text": "No impacted parts picked: pick the impacted "
                                "parts on the Impacted tab before proceeding"})
        return out

    @staticmethod
    async def decide_meeting(
        session: AsyncSession, change: ChangeRequest, meeting_id: int,
        decision: str, user: User, reason: Optional[str] = None,
        need_by_check: Optional[str] = None,
        need_by_proposed: Optional[datetime] = None,
    ) -> ChangeMeeting:
        await MeetingService._authz(session, change, user)
        if decision not in MEETING_DECISIONS:
            raise ChangeError(f"Invalid meeting decision '{decision}'")
        meeting = await MeetingService._get_meeting(session, change, meeting_id)
        if meeting.decision is not None:
            raise ChangeError(f"Meeting already decided ('{meeting.decision}')")
        # Proceed names everything that holds it at once (owner each), not
        # one refusal per press: the dialog's own fields (departments, R/A,
        # cost carrier, the urgent need-by) and proceed_holds.
        open_concerns = MeetingService.open_concerns(change)
        blocking = MeetingService.open_blocking(change)
        auto_c: dict[int, list[int]] = {}
        if decision == "proceed":
            # P3 / [R4]: proceed applies the room's carrier, on the decider's
            # rights (a room saved before the rule, or by somebody else)
            await MeetingService._refuse_carrier_move(
                session, change, user, meeting.cost_carrier)
            problems: list[str] = []
            if not meeting.selected_department_ids:
                problems.append(
                    "Select at least one impacted department before proceeding")
            # With letters on the record, somebody has to own the assessment:
            # a room of Supports and Consulteds leaves stage 1 with no gate.
            elif (meeting.department_rasic and not any(
                    v in BLOCKING_LETTERS for v in meeting.department_rasic.values())):
                problems.append(
                    "At least one department must be Responsible or Accountable "
                    "(R/A) before proceeding")
            # R25: a room saved before the rule may still name Management or
            # a retired department for a task; nobody could ever submit it.
            if meeting.selected_department_ids:
                from app.services.change_routing_service import ChangeRoutingService
                problems += await ChangeRoutingService.unroutable_refusals(
                    session, meeting.rasic_map if meeting.department_rasic else
                    {i: "R" for i in meeting.selected_department_ids})
            # §3 "Not routed" (SOFT, A2-03): a department that owns open
            # check items but is not routed with a task letter is routed C
            # (the spec's preselected pick); one that takes no task letter
            # (Management, retired) is named like any unroutable letter
            auto_c = MeetingService.unrouted_check_owners(change, meeting)
            if auto_c:
                problems += await MeetingService.unroutable_check_owner_refusals(
                    session, auto_c)
            # HARD #2: proceeding over an unanswered objection is the failure
            # this exists to stop (C33: check items go along as conditions);
            # HARD #7 the PPAP decision and the flip's Sales answer; HARD #1
            # an empty impacted set locks nothing.
            problems += [h["text"] for h in await MeetingService.proceed_holds(
                session, change, meeting=meeting)]
            # The room re-confirms the cost carrier (spec §16): it selects the
            # whole commercial branch, so nobody proceeds without saying it.
            if meeting.cost_carrier is None:
                problems.append("Confirm the cost carrier (customer or internal "
                                "change) before proceeding")
            # §3 urgent (SCOPING_V2): "Need-by realistic?" at proceed
            from app.services import capture_rules
            why = capture_rules.need_by_refusal(change, need_by_check, need_by_proposed)
            if why:
                problems.append(why)
            if len(problems) == 1:
                raise ChangeError(problems[0])
            if problems:
                raise ChangeError(
                    f"Proceed is held by {len(problems)} things: "
                    + " | ".join(f"({i}) {p}" for i, p in enumerate(problems, 1)))
            # anything but yes gives Sales "Tell customer: new date or start
            # at risk?" (customer changes; internal: the lead is told)
            await capture_rules.check_need_by(session, change, user.id,
                                              need_by_check, need_by_proposed)
        # Both of the negative outcomes owe the originator an answer: reject
        # says why the change cannot go ahead, needs_info says what is missing
        # before it can start. Only 'proceed' needs no justification.
        if decision == "reject" and not reason:
            raise ChangeError("A reason is required to reject a change")
        v2 = cm_switches.on("SCOPING_V2")
        waiting = [c for c in blocking if c.is_question]
        if decision == "needs_info" and not reason and v2 and waiting:
            # "Not yet: waiting for 3 answers (Sales, Process)": the open
            # questions are the reason; no new one is raised. An answered
            # one waits on its asker, who settles it (A2-04).
            dept_ids = {c.department_id for c in waiting if c.department_id}
            names = dict((await session.execute(
                select(Department.id, Department.name).where(
                    Department.id.in_(dept_ids)))).all()) if dept_ids else {}
            reason = "Not yet: " + MeetingService.waiting_words(waiting, names, change)
            raise_question = False
        else:
            raise_question = True
        if decision == "needs_info" and not reason:
            raise ChangeError(
                "State what information is missing before the change can start")
        meeting.decision = decision
        meeting.decision_reason = reason
        # A rejection answers the open concerns; they close with it. C13
        # (SCOPING_V2): 'Not yet' (needs_info) closes nothing: every
        # department's question stays open and keeps its owner.
        if decision == "reject" or (decision == "needs_info" and not v2):
            for c in open_concerns:
                c.resolved_by_meeting_id = meeting.id
        if decision == "proceed" and auto_c:
            await MeetingService._route_unrouted_checks(
                session, change, meeting, user, auto_c)
        if decision == "proceed" and v2:
            checks = MeetingService.open_checks(change)
            meeting.go_conditions = [
                {"id": c.id, "department_id": c.department_id,
                 "co_department_ids": c.co_department_ids or [],
                 "check_what": c.check_what, "part_id": c.part_id,
                 "note": c.note} for c in checks] or None
        meeting.decided_by = user.id
        meeting.decided_at = datetime.utcnow()
        await session.flush()
        if decision == "needs_info" and raise_question:
            await MeetingService._flag_missing_information(
                session, change, user, reason, meeting_id=meeting.id)
        conditions = len(meeting.go_conditions or [])
        await ChangeService.append_changelog(
            session, change, "scoping_meeting_decided",
            f"Scoping meeting #{meeting.id}: {decision}"
            + (f" with conditions: {conditions} check item"
               f"{'s' if conditions != 1 else ''} go to departments"
               if conditions else "")
            + (f": {reason}" if reason else ""), user.id,
            field_name="decision", new_value=decision,
            notes=reason or meeting.notes)
        if decision == "proceed":
            await MeetingService._apply_cost_carrier(session, change, meeting, user)
            # The room's 'proceed' locks the impacted set, on the decider's
            # name (no-op while Development's manual confirm is switched on).
            await ChangeService.auto_lock_impact(
                session, change, user.id, "the scoping decision 'proceed'")
        if decision in ("proceed", "reject"):
            # Meetings only exist in scoping now, so proceed always goes
            # straight to assessment; reject goes straight out.
            target = "in_assessment" if decision == "proceed" else "rejected"
            # The meeting's reason is the change's rejection reason — one
            # decision, one justification, not two places to keep in step.
            await ChangeService.transition(
                session, change, target, user.id, rejection_reason=reason)
        return meeting
