"""A new customer index on a part a live change already carries (ECR-solid
spec §1 "On an impacted item it drives the follow-up"; switch SCOPING_V2).

Triage attaches the new index D to the change, which already carried C for
that part: D supersedes C inside the change (RevisionIntakeService._link_item)
and "what changed" (the triager's areas) drives the follow-up:

- Rechecks (ChangeRecheck): every routed department that had submitted its
  assessment answers per changed area "no effect" (drawing ref / checklist
  row) or "effect" (what + evidence), plus anything else that changed;
  nothing is preselected. An effect before the offer went out (quoted)
  reopens that department's finalized costing (from quoting the change
  steps back to costing first); from quoted on it flags the scope change
  (scope_changed_after_quote + costing_update for that department). A "no
  visible change" makes no rechecks. A department that had not submitted
  assesses on D (the banner on its assessment).
- The lead: "Index D adds parts or departments?" (1 wd), once the change is
  past scoping; open, it shows on the recheck cards and in the C5 guard.
- Sales (an open quote): "D replaces C; deadline holds?": holds (mail or
  ref) / new date (date + mail or ref) / not asked yet (an Assumed answer,
  confirm by a date; the task stays until it is confirmed).
- Customer-driven (an internal change) is asked at triage and flips it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAttachment, ChangeRequest
from app.models.entities import User
from app.models.revision_intake import (
    DEADLINE_ANSWERS, NO_VISIBLE_CHANGE, ChangeRecheck, RevisionIntake,
)
from app.models.workflow import Department
from app.services import cm_switches, due_rules
from app.services.change_people import department_members_of_change_org
from app.services.change_service import ChangeError, ChangeService

#: The statuses with an open quote: Sales asks whether the deadline holds.
OPEN_QUOTE_STATUSES = ("captured", "scoping", "in_assessment", "costing",
                       "quoting", "quoted")
#: A department's costing reopens in these (early_costing.OPEN_STATUSES);
#: from quoting (no offer sent yet) the change steps back to costing first;
#: from quoted on an effect is a scope change (costing_update).
COSTING_OPEN = ("in_assessment", "costing")
BEFORE_QUOTED = (*COSTING_OPEN, "quoting")
AREA_LABELS = {"geometry": "geometry", "tolerance": "tolerance",
               "material": "material", "colour_grain": "colour/grain",
               "other": "other / not sure"}


class FollowupForbidden(ChangeError):
    """The caller may not answer this: 403."""


def _areas_text(areas) -> str:
    return ", ".join(AREA_LABELS.get(a, a) for a in areas or []) or "no area"


def lead_open(intake: RevisionIntake, change: ChangeRequest) -> bool:
    """The lead's "Index D adds parts or departments?" is owed."""
    return (intake.replaced_revision is not None and intake.scope_answer is None
            and intake.status != "superseded"
            and change.status not in ("captured", "scoping"))


def deadline_open(intake: RevisionIntake) -> bool:
    """Sales owes "D replaces C; deadline holds?" (or its confirmation)."""
    return (bool(intake.deadline_needed) and intake.status != "superseded"
            and intake.deadline_answer in (None, "not_asked"))


def _refuse_ended(change: ChangeRequest) -> None:
    """A2-07: a closed, cancelled or rejected change takes no answer."""
    from app.services.cm_rules import ended_refusal
    why = ended_refusal(change)
    if why:
        raise ChangeError(why)


class IndexFollowupService:

    # ------------------------------------------------------------------
    # Creation (from RevisionIntakeService._link_item)
    # ------------------------------------------------------------------
    @staticmethod
    async def on_new_index(session: AsyncSession, change: ChangeRequest,
                           intake: RevisionIntake, part_id: int, from_name: str,
                           to_name: str, user_id: int) -> None:
        """D replaced C on a part the change carried: rechecks for every
        routed department that had submitted, the lead's and Sales'
        questions. Notifies each owner once."""
        if not cm_switches.on("SCOPING_V2"):
            return
        intake.replaced_revision = (from_name or "?")[:20]
        areas = [a for a in (intake.what_changed or []) if a != NO_VISIBLE_CHANGE]
        made: list[ChangeRecheck] = []
        if areas:
            await session.refresh(change, ["assessments"])
            routed = sorted({a.department_id for a in change.assessments
                             if a.status != "waived"})
            submitted = {a.department_id for a in change.assessments
                         if a.submitted_at is not None}
            for did in routed:
                if did not in submitted:
                    continue     # it assesses on D (the banner), nothing to recheck
                r = ChangeRecheck(change_id=change.id, intake_id=intake.id,
                                  department_id=did, part_id=part_id,
                                  from_revision=from_name, to_revision=to_name,
                                  areas=areas, status="open")
                session.add(r)
                made.append(r)
        if (change.customer_relevant and change.status in OPEN_QUOTE_STATUSES
                and change.accepted_offer_id is None):
            intake.deadline_needed = True
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "index_followup",
            f"Index {to_name} replaces {from_name}: {_areas_text(areas) if areas else 'no visible change'}"
            + (f"; {len(made)} recheck(s)" if made else ""), user_id,
            new_value={"intake_id": intake.id, "areas": areas,
                       "recheck_department_ids": [r.department_id for r in made]})
        await IndexFollowupService._notify(session, change, intake, made, to_name, user_id)

    @staticmethod
    async def _notify(session: AsyncSession, change: ChangeRequest,
                      intake: RevisionIntake, rechecks: list[ChangeRecheck],
                      to_name: str, actor_id: int) -> None:
        """Task newly theirs, once per item, involved people only: the
        assessment's owner of each rechecking department (else its project
        team), the lead, the Sales contact (else Sales)."""
        from app.services.change_people import department_members_of_change_org
        from app.services.notification_service import NotificationService
        link = f"/changes/{change.id}?tab=assessments"
        for r in rechecks:
            owners = sorted({a.effective_owner_id or a.responsible_id
                             for a in change.assessments
                             if a.department_id == r.department_id
                             and (a.effective_owner_id or a.responsible_id)} - {actor_id})
            title = f"Recheck your assessment on index {to_name}: {change.change_number}"[:255]
            body = (f"Index {r.from_revision} -> {to_name} changed "
                    f"{_areas_text(r.areas)}: no effect (ref) or effect (what + evidence)")
            if owners:
                await NotificationService.notify_once(
                    session, owners, kind="assessment_recheck",
                    subject_key=f"recheck:{r.id}", title=title, body=body, link=link)
            else:
                await NotificationService.notify_team(
                    session, change.project_id, [r.department_id], title=title,
                    body=body, link=link, kind="assessment_recheck",
                    subject_key=f"recheck:{r.id}")
        if lead_open(intake, change) and change.lead_id not in (None, actor_id):
            await NotificationService.notify_once(
                session, [change.lead_id], kind="index_decision",
                subject_key=f"index_decision:{intake.id}",
                title=f"Index {to_name} adds parts or departments? {change.change_number}"[:255],
                body=(f"{intake.replaced_revision} -> {to_name}: answer due "
                      f"{due_rules.task_due(datetime.utcnow(), change, 'index_decision'):%a}"),
                link=f"/changes/{change.id}?tab=assessments")
        if deadline_open(intake):
            ids = [change.sales_owner_id] if change.sales_owner_id else []
            if not ids:
                sales = (await session.execute(select(Department.id).where(
                    Department.name == "Sales"))).scalar_one_or_none()
                if sales is not None:
                    ids = await department_members_of_change_org(session, change, [sales])
            ids = [i for i in ids if i != actor_id]
            await NotificationService.notify_once(
                session, ids, kind="index_deadline",
                subject_key=f"index_deadline:{intake.id}",
                title=f"{to_name} replaces {intake.replaced_revision}; deadline holds? "
                      f"{change.change_number}"[:255],
                body="Holds (mail or ref), new date, or not asked yet",
                link=f"/changes/{change.id}?tab=assessments")

    # ------------------------------------------------------------------
    # Answers
    # ------------------------------------------------------------------
    @staticmethod
    async def answer_recheck(session: AsyncSession, change: ChangeRequest,
                             recheck: ChangeRecheck, user: User, answers: list[dict],
                             something_else: Optional[dict] = None) -> ChangeRecheck:
        """A member of the department (acts-as aware; admins act as it)
        answers every area: {area, effect: false, ref} or {area, effect:
        true, what, evidence}. something_else: {what, evidence} (an effect)."""
        from app.services.cm_rules import reference_refusal
        from app.services.workflow_service import WorkflowService
        _refuse_ended(change)
        if recheck.change_id != change.id:
            raise ChangeError("Recheck not found")
        if recheck.status != "open":
            raise ChangeError("This recheck is already answered")
        if recheck.department_id not in await WorkflowService.effective_department_ids(
                session, user):
            raise FollowupForbidden("Only the rechecking department answers it "
                                    "(admins: act as that department)")
        by_area = {}
        for a in answers or []:
            area = (a or {}).get("area")
            if area in by_area:
                raise ChangeError(f"'{area}' is answered twice")
            by_area[area] = a
        missing = [x for x in recheck.areas or [] if x not in by_area]
        if missing:
            raise ChangeError("Answer every changed area: "
                              + ", ".join(AREA_LABELS.get(x, x) for x in missing))
        extra = set(by_area) - set(recheck.areas or [])
        if extra:
            raise ChangeError(f"Not a changed area of this index: {', '.join(sorted(extra))}")
        out, effect = [], False
        for area in recheck.areas or []:
            a = by_area[area]
            if a.get("effect") is True:
                what = (a.get("what") or "").strip()
                if len(what) < 5:
                    raise ChangeError(f"{AREA_LABELS.get(area, area)}: say what the "
                                      "effect is (at least 5 characters)")
                why = reference_refusal(a.get("evidence"),
                                        f"{AREA_LABELS.get(area, area)}: the evidence",
                                        "the drawing compare, a measurement or a mail")
                if why:
                    raise ChangeError(why)
                out.append({"area": area, "effect": True, "what": what,
                            "evidence": a["evidence"].strip()})
                effect = True
            elif a.get("effect") is False:
                why = reference_refusal(
                    a.get("ref"), f"{AREA_LABELS.get(area, area)}: the basis of 'no effect'",
                    "the drawing number or your checklist row")
                if why:
                    raise ChangeError(why)
                out.append({"area": area, "effect": False, "ref": a["ref"].strip()})
            else:
                raise ChangeError(f"{AREA_LABELS.get(area, area)}: pick no effect or effect")
        else_text = None
        if something_else:
            what = (something_else.get("what") or "").strip()
            if len(what) < 5:
                raise ChangeError("Something else changed: say what (at least 5 characters)")
            why = reference_refusal(something_else.get("evidence"),
                                    "Something else changed: the evidence",
                                    "the drawing compare, a measurement or a mail")
            if why:
                raise ChangeError(why)
            else_text = f"{what} ({something_else['evidence'].strip()})"
            effect = True
        recheck.answers = out
        recheck.something_else = else_text
        recheck.effect = effect
        recheck.status = "answered"
        recheck.answered_by = user.id
        recheck.answered_at = datetime.utcnow()
        await session.flush()
        name = (await session.get(Department, recheck.department_id))
        dept = name.name if name else f"dept {recheck.department_id}"
        await ChangeService.append_changelog(
            session, change, "assessment_recheck",
            f"{dept} rechecked index {recheck.to_revision}: "
            + ("effect" if effect else "no effect"), user.id,
            new_value={"recheck_id": recheck.id, "answers": out,
                       "something_else": else_text},
            for_department_id=recheck.department_id)
        if effect:
            await IndexFollowupService._apply_effect(session, change, recheck, dept, user)
        return recheck

    @staticmethod
    async def _tell_offer_on_hold(session: AsyncSession, change: ChangeRequest,
                                  recheck: ChangeRecheck, dept: str,
                                  actor_id: int) -> None:
        """The offer Sales was writing waits for a department's new costing:
        the Sales contact (else Sales) and the lead hear it once, with the
        reason (spec §0: a decision that moves their task)."""
        from app.services.notification_service import NotificationService
        ids = [change.sales_owner_id] if change.sales_owner_id else []
        if not ids:
            sales = (await session.execute(select(Department.id).where(
                Department.name == "Sales"))).scalar_one_or_none()
            if sales is not None:
                ids = await department_members_of_change_org(session, change, [sales])
        if change.lead_id is not None:
            ids.append(change.lead_id)
        ids = [i for i in dict.fromkeys(ids) if i != actor_id]
        if ids:
            await NotificationService.notify_once(
                session, ids, kind="assessment_recheck",
                subject_key=f"recheck_back:{recheck.id}",
                title=(f"Offer on hold: {dept} recosts for index {recheck.to_revision} "
                       f"({change.change_number})")[:255],
                body=(f"'{change.title}': {dept} sees an effect of index "
                      f"{recheck.to_revision}, so the change is back in costing until "
                      f"{dept} finalizes its costing again. The offer waits for it."),
                link=f"/changes/{change.id}?tab=assessments")

    @staticmethod
    async def _apply_effect(session: AsyncSession, change: ChangeRequest,
                            recheck: ChangeRecheck, dept: str, user: User) -> None:
        """Before quoted (spec §1 [R4]): the department's finalized costing
        reopens; in quoting (no offer sent) the change first steps back to
        costing, the correction path. From quoted on: the scope change with
        costing_update for the department (the §6 scope change card reuses
        it)."""
        from app.services import early_costing
        why = f"Customer index {recheck.to_revision} (was {recheck.from_revision}): effect for {dept}"
        if change.status == "quoting":
            await ChangeService.transition(
                session, change, "costing", user.id,
                reason=f"{why}: its costing reopens before the offer goes out")
            await IndexFollowupService._tell_offer_on_hold(
                session, change, recheck, dept, user.id)
        if change.status in COSTING_OPEN:
            await session.refresh(change, ["assessments"])
            rows = [a for a in change.assessments
                    if a.department_id == recheck.department_id
                    and a.details_dict.get("costing_finalized_at")]
            if rows and early_costing.is_finalized(change, recheck.department_id):
                for a in rows:
                    early_costing._set_details(a, costing_finalized_at=None,
                                               costing_finalized_by=None)
                await session.flush()
                await ChangeService.append_changelog(
                    session, change, "costing_input_reopened",
                    f"Costing input reopened for dept {recheck.department_id}: {why}",
                    user.id, new_value={"department_id": recheck.department_id},
                    notes=why, for_department_id=recheck.department_id)
            return
        if change.status in ("captured", "scoping"):
            return
        if cm_switches.on("COMMERCIAL_V2") and change.status in (
                "quoted", "approved", "in_implementation", "in_validation"):
            # §1 [R4]: the §6 scope change card, type "customer index" (P/N
            # + new index prefilled), re-costed by the departments with effect
            from app.models.part import Part
            from app.services import scope_change_service as scs
            part = await session.get(Part, recheck.part_id) if recheck.part_id else None
            number = part.part_number if part else None
            card = next((c for c in await scs.open_cards(session, change)
                         if c.kind == "customer_index" and c.part_number == number
                         and c.status == "recosting"), None)
            if card is not None:
                await scs.ScopeChangeService._start_recost(
                    session, change, card, [recheck.department_id], user.id)
            else:
                await scs.ScopeChangeService.request(
                    session, change, user, kind="customer_index", system=True,
                    part_number=number,
                    what=f"Customer index {recheck.to_revision} (was "
                         f"{recheck.from_revision}): effect for {dept}",
                    department_ids=[recheck.department_id], recheck_id=recheck.id)
            return
        prior = set(change.scope_change_department_ids or [])
        change.scope_changed_after_quote = True
        change.scope_changed_at = datetime.utcnow()
        change.scope_change_reason = why[:500]
        change.scope_change_department_ids = sorted(prior | {recheck.department_id})
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scope_changed_after_quote",
            f"Scope change, type customer index: {why}", user.id,
            new_value={"department_ids": [recheck.department_id],
                       "type": "customer_index"}, notes=why)

    @staticmethod
    async def answer_scope(session: AsyncSession, change: ChangeRequest,
                           intake: RevisionIntake, user: User, answer: str,
                           note: Optional[str] = None) -> RevisionIntake:
        """The lead (or Project Management, an admin): does index D add parts
        or departments? 'yes' says which, then the run team adds them."""
        _refuse_ended(change)
        if intake.change_id != change.id or intake.replaced_revision is None:
            raise ChangeError("No new-index question on this change")
        if intake.scope_answer is not None:
            raise ChangeError("Already answered")
        from app.services.early_stage_service import EarlyStageService
        if not (await EarlyStageService._roles(session, change, user))["run_team"]:
            raise FollowupForbidden("The lead or Project Management answers this")
        if answer not in ("no", "yes"):
            raise ChangeError("Answer no or yes")
        note = (note or "").strip() or None
        if answer == "yes" and (note is None or len(note) < 5):
            raise ChangeError("Yes: name the parts or departments it adds")
        intake.scope_answer = answer
        intake.scope_note = note[:500] if note else None
        intake.scope_by = user.id
        intake.scope_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "index_decision",
            f"Index adds parts or departments? {answer}" + (f": {note}" if note else ""),
            user.id, new_value={"intake_id": intake.id, "answer": answer, "note": note})
        return intake

    @staticmethod
    async def answer_deadline(session: AsyncSession, change: ChangeRequest,
                              intake: RevisionIntake, user: User, answer: str, *,
                              ref: Optional[str] = None, mail_id: Optional[int] = None,
                              new_date: Optional[datetime] = None,
                              confirm_by: Optional[datetime] = None) -> RevisionIntake:
        """Sales (any member; the owner is named): holds (mail or ref) / new
        date (date + the customer's filed mail) / not asked yet (confirm by a date, +5 wd
        by default; the task stays until it is confirmed)."""
        from app.services import due_rules
        from app.services.cm_rules import reference_refusal
        _refuse_ended(change)
        if intake.change_id != change.id or not deadline_open(intake):
            raise ChangeError("No deadline question waits on this change")
        if not await ChangeService.member_of(session, user, "Sales"):
            raise FollowupForbidden("Sales answers whether the deadline holds")
        if answer not in DEADLINE_ANSWERS:
            raise ChangeError("Answer holds, new_date or not_asked")
        evidence = None
        if answer == "new_date" and mail_id is None:
            # spec §1 "new date (date + mail)": a moved deadline is on the
            # change by the customer's own mail (R17), not a typed reference
            raise ChangeError("New date: pick the customer's mail with the new "
                              "date (file it on the change first)")
        if answer in ("holds", "new_date"):
            if mail_id is not None:
                mail = await session.get(ChangeAttachment, mail_id)
                if (mail is None or mail.change_id != change.id
                        or mail.kind != "customer_email"):
                    raise ChangeError("Pick a customer mail filed on this change")
                evidence = f"Mail: {mail.filename}"
            else:
                why = reference_refusal(ref, "The customer's mail or reference",
                                        "Mail from the buyer 15 Oct")
                if why:
                    raise ChangeError(why)
                evidence = ref.strip()
        if answer == "new_date":
            if new_date is None:
                raise ChangeError("New date: set the new quote deadline")
            if new_date.date() < datetime.utcnow().date():
                raise ChangeError("The new quote deadline is in the past: pick "
                                  "today or a later date")
            old = change.required_by_date
            change.required_by_date = new_date
            change.required_by_set_by = user.id
            change.required_by_set_at = datetime.utcnow()
            await ChangeService.append_changelog(
                session, change, "deadline_set",
                f"Quote deadline {old} -> {new_date} (index {intake.replaced_revision} "
                "replaced)", user.id, field_name="required_by_date",
                old_value=str(old) if old else None, new_value=str(new_date))
        if answer == "not_asked":
            if intake.deadline_answer == "not_asked":
                raise ChangeError("Still not asked: answer holds or new date once "
                                  "the customer replied")
            confirm_by = confirm_by or due_rules.add_wd(datetime.utcnow(), 5)
            intake.deadline_confirm_by = confirm_by
        intake.deadline_answer = answer
        intake.deadline_ref = evidence[:255] if evidence else None
        intake.deadline_by = user.id
        intake.deadline_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "index_deadline",
            {"holds": "Deadline holds", "new_date": "New quote deadline",
             "not_asked": "Deadline not asked yet (Assumed)"}[answer]
            + (f" ({evidence})" if evidence else ""), user.id,
            new_value={"intake_id": intake.id, "answer": answer,
                       "confirm_by": str(intake.deadline_confirm_by)
                       if answer == "not_asked" else None})
        return intake

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def for_change(session: AsyncSession, change: ChangeRequest) -> list[dict]:
        """The change's new-index follow-ups, newest first, for its
        Assessments tab: from -> to, areas, rechecks, the lead's and Sales'
        questions."""
        intakes = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.change_id == change.id,
                                         RevisionIntake.replaced_revision.isnot(None))
            .order_by(RevisionIntake.id.desc()))).scalars().all()
        if not intakes:
            return []
        from app.models.part import Part, PartRevision
        rechecks = (await session.execute(
            select(ChangeRecheck).where(ChangeRecheck.change_id == change.id)
            .order_by(ChangeRecheck.id))).scalars().all()
        depts = dict((await session.execute(select(Department.id, Department.name).where(
            Department.id.in_({r.department_id for r in rechecks} or {0})))).all())
        user_ids = {r.answered_by for r in rechecks} | {i.scope_by for i in intakes} \
            | {i.deadline_by for i in intakes}
        from app.services.change_plan_service import ChangePlanService
        names = await ChangePlanService._user_names(session, [u for u in user_ids if u])
        out = []
        for i in intakes:
            rev = await session.get(PartRevision, i.revision_id)
            part = await session.get(Part, i.part_id)
            out.append({
                "intake_id": i.id, "part_id": i.part_id,
                "part_number": part.part_number if part else None,
                "from_revision": i.replaced_revision,
                "to_revision": rev.revision_name if rev else None,
                "superseded": i.status == "superseded",
                "what_changed": i.what_changed or [],
                "what_changed_ref": i.what_changed_ref,
                "no_change_reason": i.no_change_reason,
                "rechecks": [{
                    "id": r.id, "department_id": r.department_id,
                    "department_name": depts.get(r.department_id),
                    "areas": r.areas or [], "status": r.status, "effect": r.effect,
                    "answers": r.answers or [], "something_else": r.something_else,
                    "answered_by_name": names.get(r.answered_by),
                    "answered_at": r.answered_at, "created_at": r.created_at,
                } for r in rechecks if r.intake_id == i.id],
                "lead_open": lead_open(i, change),
                "scope_answer": i.scope_answer, "scope_note": i.scope_note,
                "scope_by_name": names.get(i.scope_by), "scope_at": i.scope_at,
                "deadline_open": deadline_open(i),
                "deadline_answer": i.deadline_answer, "deadline_ref": i.deadline_ref,
                "deadline_confirm_by": i.deadline_confirm_by,
                "deadline_by_name": names.get(i.deadline_by),
            })
        return out

    @staticmethod
    async def notify_lead_on_assessment(session: AsyncSession, change: ChangeRequest,
                                        actor_id: Optional[int]) -> None:
        """An index attached during capture or scoping makes the lead's
        "adds parts or departments?" owed once the change enters assessment:
        task newly theirs, told once (the same key as at attach)."""
        if not cm_switches.on("SCOPING_V2") or change.lead_id in (None, actor_id):
            return
        from app.models.part import PartRevision
        from app.services.notification_service import NotificationService
        intakes = (await session.execute(select(RevisionIntake).where(
            RevisionIntake.change_id == change.id,
            RevisionIntake.replaced_revision.isnot(None),
            RevisionIntake.scope_answer.is_(None)))).scalars().all()
        for i in intakes:
            if not lead_open(i, change):
                continue
            rev = await session.get(PartRevision, i.revision_id)
            to_name = rev.revision_name if rev else "new index"
            await NotificationService.notify_once(
                session, [change.lead_id], kind="index_decision",
                subject_key=f"index_decision:{i.id}",
                title=f"Index {to_name} adds parts or departments? {change.change_number}"[:255],
                body=(f"{i.replaced_revision} -> {to_name}: answer due "
                      f"{due_rules.task_due(datetime.utcnow(), change, 'index_decision'):%a}"),
                link=f"/changes/{change.id}?tab=assessments")

    @staticmethod
    async def open_lines(session: AsyncSession, change: ChangeRequest) -> list[str]:
        """C5 lines: open rechecks and the lead's new-index question."""
        if not cm_switches.on("SCOPING_V2"):
            return []
        rows = (await session.execute(
            select(ChangeRecheck.department_id).where(
                ChangeRecheck.change_id == change.id,
                ChangeRecheck.status == "open"))).scalars().all()
        lines = []
        if rows:
            names = dict((await session.execute(select(Department.id, Department.name)
                                                .where(Department.id.in_(set(rows))))).all())
            lines.append("Recheck on the new index: "
                         + ", ".join(sorted(names.get(d, f"dept {d}") for d in set(rows))))
        intakes = (await session.execute(
            select(RevisionIntake).where(RevisionIntake.change_id == change.id,
                                         RevisionIntake.replaced_revision.isnot(None),
                                         RevisionIntake.scope_answer.is_(None)))).scalars().all()
        for i in intakes:
            if lead_open(i, change):
                who = change.lead_name or "the lead"
                lines.append(f"New-index task: {who} answers 'adds parts or departments?'")
        return lines

    @staticmethod
    async def task_rows(db: AsyncSession, user: User, open_changes: list,
                        dep_ids: set, base) -> list[dict]:
        """My Tasks: assessment_recheck (the department), index_decision (the
        lead, Project Management backs up), index_deadline (all of Sales, the
        owner named). Two queries for the whole list."""
        if not cm_switches.on("SCOPING_V2") or not open_changes:
            return []
        from app.services import due_rules
        from app.services.change_people import holds_lead
        by_id = {c.id: c for c in open_changes}
        out: list[dict] = []
        if dep_ids:
            for r in (await db.execute(select(ChangeRecheck).where(
                    ChangeRecheck.change_id.in_(by_id),
                    ChangeRecheck.status == "open",
                    ChangeRecheck.department_id.in_(dep_ids)))).scalars().all():
                c = by_id[r.change_id]
                # an "assessment*" row brings its own due (due_rules): the task rule
                due = due_rules.task_due(r.created_at or datetime.utcnow(), c,
                                         "assessment_recheck")
                out.append({**await base(c), "kind": "assessment_recheck",
                            "recheck_id": r.id, "department_id": r.department_id,
                            "reason": (f"{r.from_revision} -> {r.to_revision}: "
                                       f"{_areas_text(r.areas)}"),
                            "due_date": due, "overdue": due < datetime.utcnow(),
                            "target_tab": "assessments"})
        intakes = (await db.execute(select(RevisionIntake).where(
            RevisionIntake.change_id.in_(by_id),
            RevisionIntake.replaced_revision.isnot(None)))).scalars().all()
        if not intakes:
            return out
        is_pm = await ChangeService.member_of(db, user, "Project Manager")
        is_sales = await ChangeService.member_of(db, user, "Sales")
        leads = [i for i in intakes if lead_open(i, by_id[i.change_id])
                 and (holds_lead(by_id[i.change_id], user) or is_pm)]
        rev_names: dict = {}
        entered: dict = {}
        if leads:
            # the row names the new index, and starts when the question became
            # owed: the attach, or the change's entry into assessment for an
            # index attached during capture or scoping (never overdue at birth)
            from sqlalchemy import func
            from app.models.change import ChangeChangelog
            from app.models.part import PartRevision
            rev_names = dict((await db.execute(select(
                PartRevision.id, PartRevision.revision_name).where(
                PartRevision.id.in_({i.revision_id for i in leads})))).all())
            entered = dict((await db.execute(select(
                ChangeChangelog.change_id, func.min(ChangeChangelog.performed_at))
                .where(ChangeChangelog.change_id.in_({i.change_id for i in leads}),
                       ChangeChangelog.field_name == "status",
                       ChangeChangelog.new_value == '"in_assessment"')
                .group_by(ChangeChangelog.change_id))).all())
        for i in intakes:
            c = by_id[i.change_id]
            if i in leads:
                start = max(i.decided_at or datetime.utcnow(),
                            entered.get(c.id) or i.decided_at or datetime.utcnow())
                out.append({**await base(c), "kind": "index_decision",
                            "intake_id": i.id, "since": start,
                            "reason": (f"{i.replaced_revision} -> "
                                       f"{rev_names.get(i.revision_id) or 'new index'}"),
                            "target_tab": "assessments",
                            **({"main_user": (c.lead_id, c.lead_name or "")}
                               if c.lead_id is not None and not holds_lead(c, user) else {})})
            if deadline_open(i) and is_sales:
                confirm = i.deadline_answer == "not_asked"
                row = {**await base(c), "intake_id": i.id,
                       "kind": "index_deadline_confirm" if confirm else "index_deadline",
                       "since": i.decided_at, "target_tab": "assessments",
                       "reason": i.replaced_revision,
                       **({"main_user": (c.sales_owner_id, c.sales_owner_name or "")}
                          if c.sales_owner_id not in (None, user.id) else {})}
                if confirm:
                    # an Assumed "not asked yet" is confirmed by its own date
                    row["due_date"] = i.deadline_confirm_by
                    row["overdue"] = (i.deadline_confirm_by is not None
                                      and i.deadline_confirm_by < datetime.utcnow())
                out.append(row)
        return out
