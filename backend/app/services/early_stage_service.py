"""Early stages polish: capture, scoping, assessment (spec 2026-09-25 §16).

What lives here, and why in one module:
- transition rights for the early hops (P1-4), shared by the endpoint and
  the "stage state" payload so the buttons and the gate agree;
- impact-edit rights (P1-5), post-quote scope changes and the title that
  follows the lead item;
- the "stage state" payload the cockpit reads: who the assessment waits on,
  whether everything is in, not-feasible verdicts with their Change PPT,
  pending "not our responsibility" declines, the routing deviation's
  decider, end states and the Blocked by rows (P1-5 to P1-8, P2);
- the per-department checklist draft (P1-1);
- the change's own audit trail by entity ids (P1-9).

Every refusal text is plain English without dashes used as punctuation, so
it reads well in a toast.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    BLOCKING_LETTERS, SCOPING_STATUSES, ChangeAssessment, ChangeChangelog,
    ChangeImpactedItem, ChangeRequest,
)
from app.models.entities import User
from app.models.part import Part
from app.models.workflow import Department
from app.services import cm_labels
from app.services.change_people import is_acting
from app.services.change_service import (
    ALLOWED_TRANSITIONS, IMPACT_LOCKED_STATUSES, ChangeError, ChangeService,
)

# Impact edits from here on no longer match the offer (spec §16).
POST_QUOTE_STATUSES = ("quoted", "approved")
# The hops whose rights §16 P1-4 sets.
RUN_TEAM_TARGETS = ("rejected", "cancelled", "on_hold")
TITLE_MAX_LENGTH = 255


class EarlyStageService:

    # ------------------------------------------------------------------
    # Who is who on this change
    # ------------------------------------------------------------------
    @staticmethod
    async def _roles(session: AsyncSession, change: ChangeRequest,
                     user: User) -> dict:
        """Acts-as aware: effective_role drops the admin bypass for an
        acting admin, and department membership is the effective one."""
        from app.services.meeting_service import MeetingService
        admin = user.effective_role == "admin"
        # Acting as a department is being exactly that department: the
        # personal lead privilege steps aside, like the admin bypass.
        from app.services.change_people import holds_lead
        lead = holds_lead(change, user)
        pm = await MeetingService.user_is_pm_member(session, user)
        sales = await EarlyStageService._member_of(session, user, "Sales")
        return {"admin": admin, "lead": lead, "pm": pm, "sales": sales,
                "run_team": admin or lead or pm}

    @staticmethod
    async def _member_of(session: AsyncSession, user: User, name: str) -> bool:
        """Membership without the admin shortcut ChangeService's helper has."""
        from app.services.workflow_service import WorkflowService
        dept_id = (await session.execute(
            select(Department.id).where(Department.name == name))).scalar_one_or_none()
        if dept_id is None:
            return False
        return dept_id in await WorkflowService.effective_department_ids(session, user)

    # ------------------------------------------------------------------
    # P1-4: transition rights
    # ------------------------------------------------------------------
    @staticmethod
    async def transition_refusal(session: AsyncSession, change: ChangeRequest,
                                 user: User, to_status: str) -> Optional[str]:
        """None when the user may attempt this hop, else the 403 text.

        - reject, cancel, hold, recall to scoping, close the assessment:
          the change lead, Project Management members, admin;
        - kick off (captured -> scoping): Sales, PM, lead, admin;
        - Sales may also reject at capture, and a quoted change the customer
          declined (the commercial answer is theirs).
        Only hops that exist are judged: an illegal one keeps its 400."""
        frm = change.status
        if to_status not in ALLOWED_TRANSITIONS.get(frm, set()):
            return None
        early_hop = (
            to_status in RUN_TEAM_TARGETS
            or (frm == "captured" and to_status == "scoping")
            or (frm == "in_assessment" and to_status in ("scoping", "costing")))
        if not early_hop:
            return None
        r = await EarlyStageService._roles(session, change, user)
        if r["run_team"]:
            return None
        if frm == "captured" and to_status in ("scoping", "rejected") and r["sales"]:
            return None
        if frm == "quoted" and to_status == "rejected" and r["sales"]:
            return None
        verb = {
            "rejected": "reject this change",
            "cancelled": "cancel this change",
            "on_hold": "put this change on hold",
            "scoping": ("hand this change over to scoping" if frm == "captured"
                        else "recall this change to scoping"),
            "costing": "close the assessment",
        }.get(to_status, f"move this change to '{to_status}'")
        if frm == "captured" and to_status in ("scoping", "rejected"):
            return ("Only Sales, Project Management, the change lead or an "
                    f"admin may {verb}")
        return f"Only the change lead, Project Management or an admin may {verb}"

    @staticmethod
    async def transition_rights(session: AsyncSession, change: ChangeRequest,
                                user: User) -> dict:
        """{to_status: bool} for every hop out of the current status: the
        early-stage rights above plus the endpoint's existing role gates, so
        a hidden button is a refused request and the other way round."""
        out = {}
        for to_status in sorted(ALLOWED_TRANSITIONS.get(change.status, set())):
            ok = await EarlyStageService.transition_refusal(
                session, change, user, to_status) is None
            if ok and (change.status, to_status) in ChangeService.QUOTE_STAGE_TRANSITIONS:
                ok = await ChangeService.user_can_run_quote_stage(
                    session, user, change, to_status=to_status)
            if ok and (change.status, to_status) == ChangeService.COSTING_REOPEN:
                ok = await ChangeService.user_can_reopen_costing(session, user, change)
            if ok and change.status == "scoping" and to_status == "approved":
                # the mother plant's side track: the same right as the
                # endpoint (PM, the change lead, admin)
                from app.services.mother_plant_service import MotherPlantService
                ok = await MotherPlantService.may_send(session, change, user)
            if ok and change.status == "in_validation" and to_status == "in_implementation":
                from app.services.validation_service import ValidationService
                ok = await ValidationService.may_escalate(session, change, user)
            if ok and to_status in ("released", "closed"):
                from app.services.release_service import ReleaseService
                ok = await ReleaseService.is_pm_or_lead(session, change, user)
                if not ok and change.status == "rejected" and to_status == "closed":
                    ok = await ChangeService._user_in_department(session, user, "Sales")
            if ok and await EarlyStageService.hard_refusal(
                    session, change, to_status) is not None:
                ok = False
            out[to_status] = ok
        return out

    @staticmethod
    async def transition_blocks(session: AsyncSession,
                                change: ChangeRequest) -> dict:
        """{to_status: block} for every forward hop that would be refused
        today (final walk P2-5), so the cockpit disables its next step with
        the reason instead of offering a button that answers 400.

        block = {kind: 'hard' | 'gate' | 'guard', reason, gate_key,
        target_tab, deviation_possible, pending_deviation_id}. 'hard' is a
        rule no deviation lifts; 'gate' a D1 gate not answered Yes (target
        tab 'd1'); 'guard' any other soft guard. A hop an approved deviation
        already covers is not blocked and not listed. Reject, cancel and hold
        are never listed: they are not the next step."""
        from app.models.change_cost import GATE_TARGET_STATUS
        out: dict = {}
        for to_status in sorted(ALLOWED_TRANSITIONS.get(change.status, set())):
            if to_status in RUN_TEAM_TARGETS:
                continue
            hard = await EarlyStageService.hard_refusal(session, change, to_status)
            if hard is not None:
                out[to_status] = {"kind": "hard", "reason": hard, "gate_key": None,
                                  "target_tab": None, "deviation_possible": False,
                                  "pending_deviation_id": None}
                continue
            reason = await ChangeService._guard(session, change, to_status)
            if reason is None:
                continue
            devs = [d for d in change.transition_deviations if d.to_status == to_status]
            if any(d.status == "approved" for d in devs):
                continue
            pending = next((d for d in devs if d.status == "pending"), None)
            gate = next((g for g in change.gates
                         if GATE_TARGET_STATUS.get(g.gate_key) == to_status
                         and g.decision != "yes"), None)
            is_gate = gate is not None and reason == ChangeService.gate_message(
                gate.gate_key, gate.decision)
            out[to_status] = {
                "kind": "gate" if is_gate else "guard",
                "reason": reason,
                "gate_key": gate.gate_key if is_gate else None,
                "target_tab": "d1" if is_gate else None,
                "deviation_possible": True,
                "pending_deviation_id": pending.id if pending else None,
            }
        return out

    @staticmethod
    async def hard_refusal(session: AsyncSession, change: ChangeRequest,
                           to_status: str) -> Optional[str]:
        """The HARD rules of ChangeService.transition that no deviation
        lifts, so a button is never offered for a hop that is certain to be
        refused (spec §16: e.g. scoping -> approved is the mother plant's
        side track only)."""
        from app.services import mother_plants as mp
        mother_plant = mp.is_mother_plant(change)
        if mother_plant and to_status in mp.MOTHER_PLANT_SKIPPED:
            return (f"A change from {mp.plant_name(change)} has no assessment, "
                    "costing or quote")
        from app.services.engineering_review_service import review_refusal
        refusal = review_refusal(change, to_status)
        if refusal is not None:
            return refusal
        if change.status == "scoping" and to_status == "approved":
            if not mother_plant:
                return (f"Only a change from {mp.FALLBACK_NAME} goes from "
                        "scoping to approved")
            from app.services.mother_plant_service import MotherPlantService
            return await MotherPlantService.approval_blocker(session, change)
        if to_status == "approved" and not mother_plant:
            if change.customer_relevant:
                if change.customer_response != "accepted":
                    return "Customer has not accepted the offer"
                if change.pm_signed_by is None or change.quality_signed_by is None:
                    return "Both PM and Quality sign-off are required"
                if change.status == "costing":
                    return "Customer-relevant changes must go through the quote"
            elif change.internal_approved_at is None:
                return "Internal cost approval is required before approval"
        if to_status in ("quoting", "quoted") and not change.customer_relevant:
            return "Internal changes skip the quote"
        if to_status == "in_assessment" and change.impact_confirmed_at is None:
            return "Impacted set is not locked"
        if change.status == "on_hold" and to_status != "cancelled":
            before = await ChangeService._status_before_hold(session, change)
            if before is not None and before != "on_hold" and to_status != before:
                return f"Resume to '{before}'"
        return None

    # ------------------------------------------------------------------
    # P1-5: impact edits
    # ------------------------------------------------------------------
    @staticmethod
    async def impact_edit_refusal(session: AsyncSession, change: ChangeRequest,
                                  user: User) -> Optional[str]:
        """Editing the impacted set: the change lead, Project Management
        members, admin, at any open stage (after the lock their edit clears
        Development's confirmation: that is the reopen). Development members
        (acts-as aware, the same check as the confirm) pick the set
        themselves while it is at scoping and not locked, then confirm it."""
        r = await EarlyStageService._roles(session, change, user)
        if r["run_team"]:
            return None
        if (change.status == "scoping"
                and await ChangeService.user_can_confirm_impact(session, user)):
            if change.impact_confirmed_at is None:
                return None
            return ("The impacted set is locked (confirmed by Development). "
                    "Only the change lead, Project Management or an admin may "
                    "reopen it by editing")
        return ("Only Development (at scoping, before the lock), the change "
                "lead, Project Management or an admin may edit the impacted items")

    @staticmethod
    def post_quote(change: ChangeRequest) -> bool:
        return change.status in POST_QUOTE_STATUSES

    @staticmethod
    async def _objects_by_department(session: AsyncSession,
                                     change: ChangeRequest) -> dict[int, set]:
        await session.refresh(change, ["impacted_items"])
        return {d["department_id"]: {o["id"] for o in d["objects"]}
                for d in await ChangeService.assessment_objects(session, change)}

    @staticmethod
    async def begin_impact_edit(session: AsyncSession, change: ChangeRequest,
                                reason: Optional[str]) -> Optional[dict]:
        """Before an impact edit. From 'quoted' on the edit needs a reason
        (the offer no longer covers the scope); returns the department ->
        objects snapshot the post-quote bookkeeping diffs against, or None
        when the edit is an ordinary pre-quote one."""
        if not EarlyStageService.post_quote(change):
            return None
        if not (reason or "").strip():
            raise ChangeError(
                "The offer is already out: say why the impacted items change "
                "(reason required)")
        return await EarlyStageService._objects_by_department(session, change)

    @staticmethod
    async def finish_impact_edit(session: AsyncSession, change: ChangeRequest,
                                 user_id: int, reason: Optional[str],
                                 before: Optional[dict],
                                 part_ids: list[int]) -> None:
        """After an impact edit: recompose the title, and from 'quoted' on
        flag the scope change and reopen costing for the departments whose
        objects moved (all routed ones when nothing is traceable)."""
        await EarlyStageService.recompose_title(session, change, user_id)
        if before is None:
            return
        after = await EarlyStageService._objects_by_department(session, change)
        affected = sorted(d for d in set(before) | set(after)
                          if before.get(d, set()) != after.get(d, set()))
        if not affected:
            affected = sorted({a.department_id for a in change.assessments
                               if a.rasic_letter in BLOCKING_LETTERS})
        prior = set(change.scope_change_department_ids or [])
        change.scope_changed_after_quote = True
        change.scope_changed_at = datetime.utcnow()
        change.scope_change_reason = reason.strip()
        change.scope_change_department_ids = sorted(prior | set(affected))
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "scope_changed_after_quote",
            f"Impacted items changed after the quote: {reason.strip()}", user_id,
            new_value={"part_ids": sorted(part_ids),
                       "department_ids": affected},
            notes=reason.strip())

    @staticmethod
    async def scope_change_state(session: AsyncSession,
                                 change: ChangeRequest) -> Optional[dict]:
        """The post-quote scope change and whether it is covered: a newer
        offer version sent after it, or a transition deviation approved
        after it."""
        if not change.scope_changed_after_quote:
            return None
        from app.models.change_offer import ChangeOffer
        offers = (await session.execute(
            select(ChangeOffer).where(ChangeOffer.change_id == change.id,
                                      ChangeOffer.sent_at.isnot(None))
            .order_by(ChangeOffer.version))).scalars().all()
        at = change.scope_changed_at
        covering_offer = next((o for o in offers if at and o.sent_at >= at), None)
        covering_dev = next(
            (d for d in change.transition_deviations
             if d.status in ("approved", "consumed") and d.decided_at
             and at and d.decided_at >= at), None)
        latest = [o for o in offers if not at or o.sent_at < at]
        version = latest[-1].version if latest else None
        return {
            "changed_at": at,
            "reason": change.scope_change_reason,
            "department_ids": change.scope_change_department_ids or [],
            "offer_version": version,
            "covered": covering_offer is not None or covering_dev is not None,
            "covered_by_offer_version": covering_offer.version if covering_offer else None,
            "covered_by_deviation_id": covering_dev.id if covering_dev else None,
        }

    # ------------------------------------------------------------------
    # Title follows the lead item
    # ------------------------------------------------------------------
    @staticmethod
    async def compose_title(session: AsyncSession,
                            change: ChangeRequest) -> Optional[str]:
        """<our number>[ +n] - <customer number> - <item name>, from the lead
        item. Same rule as StartChangeModal.composeTitle."""
        await session.refresh(change, ["impacted_items"])
        items = change.impacted_items
        if not items:
            return None
        lead = next((i for i in items if i.is_lead), None) or min(
            items, key=lambda i: i.part_id)
        part = await session.get(Part, lead.part_id)
        if part is None:
            return None
        others = len(items) - 1
        ours = f"{part.part_number} +{others}" if others > 0 else part.part_number
        bits = [ours, part.customer_part_number, part.name]
        return " - ".join(b for b in bits if b)[:TITLE_MAX_LENGTH]

    @staticmethod
    async def recompose_title(session: AsyncSession, change: ChangeRequest,
                              user_id: int) -> None:
        """While title_auto holds, the title follows the impacted set; the
        title it replaces stays in the audit."""
        if not change.title_auto:
            return
        title = await EarlyStageService.compose_title(session, change)
        if not title or title == change.title:
            return
        old = change.title
        change.title = title
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "title_recomposed",
            f"Title follows the lead item: {title}", user_id,
            field_name="title", old_value=old, new_value=title)

    @staticmethod
    async def make_lead(session: AsyncSession, change: ChangeRequest,
                        item_id: int, user_id: int) -> ChangeImpactedItem:
        """Make an impacted item the lead. The lead names the change and
        departments are routed against it, so it moves only while the change
        is captured or in scoping."""
        if change.status not in SCOPING_STATUSES:
            raise ChangeError(
                "The lead item is fixed once assessment has started")
        item = await session.get(ChangeImpactedItem, item_id)
        if item is None or item.change_id != change.id:
            raise ChangeError("Impacted item not found")
        if item.is_lead:
            return item
        await session.refresh(change, ["impacted_items"])
        for other in change.impacted_items:
            if other.is_lead:
                other.is_lead = False
        item.is_lead = True
        await session.flush()
        part = await session.get(Part, item.part_id)
        await ChangeService.append_changelog(
            session, change, "impacted_lead_changed",
            f"Lead item is now {part.part_number if part else item.part_id}",
            user_id, new_value={"part_id": item.part_id})
        # The lead is part of the set Development confirmed: moving it is an
        # impacted-set edit and clears the confirmation like any other.
        await ChangeService._reset_impact_confirmation(session, change, user_id)
        await EarlyStageService.recompose_title(session, change, user_id)
        return item

    # ------------------------------------------------------------------
    # P1-1: checklist draft per department
    # ------------------------------------------------------------------
    @staticmethod
    async def _draft_row(session: AsyncSession, change: ChangeRequest,
                         assessment_id: int, user: User) -> ChangeAssessment:
        a = await session.get(ChangeAssessment, assessment_id)
        if a is None or a.change_id != change.id:
            raise ChangeError("Assessment not found on this change")
        if user.effective_role != "admin":
            from app.services.workflow_service import WorkflowService
            if not await WorkflowService.actor_in_department(
                    session, user, a.department_id):
                raise PermissionError(
                    "Only members of the assessed department (or an admin) may "
                    "keep its draft")
        return a

    @staticmethod
    async def save_draft(session: AsyncSession, change: ChangeRequest,
                         assessment_id: int, user: User, draft: dict) -> dict:
        """Keep the department's unfinished checklist in details["draft"].
        Submitting replaces details with the submitted answer, so the draft
        ends there by itself."""
        if not isinstance(draft, dict):
            raise ChangeError("A draft must be an object")
        a = await EarlyStageService._draft_row(session, change, assessment_id, user)
        if change.status != "in_assessment":
            raise ChangeError("Drafts are kept while the change is in assessment")
        if a.submitted_at is not None or a.verdict != "pending":
            raise ChangeError("This assessment is already submitted")
        details = a.details_dict
        details["draft"] = {"data": draft,
                            "saved_at": datetime.utcnow().isoformat(),
                            "saved_by": user.id}
        a.details = json.dumps(details)
        await session.flush()
        return EarlyStageService.draft_of(a)

    @staticmethod
    async def load_draft(session: AsyncSession, change: ChangeRequest,
                         assessment_id: int, user: User) -> dict:
        a = await EarlyStageService._draft_row(session, change, assessment_id, user)
        return EarlyStageService.draft_of(a)

    @staticmethod
    def draft_of(a: ChangeAssessment) -> dict:
        d = a.details_dict.get("draft") or {}
        return {"assessment_id": a.id, "department_id": a.department_id,
                "draft": d.get("data"), "saved_at": d.get("saved_at"),
                "saved_by": d.get("saved_by")}

    # ------------------------------------------------------------------
    # P1-2: the assessment stage is the first routing stage
    # ------------------------------------------------------------------
    @staticmethod
    def first_stage(change: ChangeRequest) -> Optional[int]:
        return min((a.stage_order for a in change.assessments), default=None)

    @staticmethod
    def is_assessment_row(a: ChangeAssessment, first: Optional[int]) -> bool:
        """A row of the assessment proper: the first routing stage, or a
        department somebody added by deviation (its task carries no step).
        Mirrors ChangeRoutingService.blocking_complete."""
        if first is None:
            return False
        return (a.stage_order == first
                or (a.task is not None and a.task.step_id is None)
                or (a.task is None and a.status == "active"))

    @staticmethod
    async def wake_later_stages(session: AsyncSession,
                                change: ChangeRequest) -> None:
        """Entering costing: the stage completed during assessment may now
        hand over to the next routing stage (WorkflowService holds it while
        the change is in assessment)."""
        from app.models.workflow import WfInstance
        from app.services.workflow_service import WorkflowService
        inst = (await session.execute(
            select(WfInstance).where(WfInstance.change_id == change.id,
                                     WfInstance.status == "active")
        )).scalar_one_or_none()
        if inst is not None:
            await WorkflowService._maybe_advance_stage(session, inst)
            # The stage that just started may carry a deviation-added row
            # the engine did not create a task for.
            from app.services.change_routing_service import ChangeRoutingService
            await ChangeRoutingService.repair_stage_tasks(session, change, None)

    @staticmethod
    async def supersede_assessments(session: AsyncSession, change: ChangeRequest,
                                    user_id: int, reason: str) -> None:
        """Back to scoping after a "not feasible" (spec §16 P1-8): the
        routing is rebuilt on the next proceed, so the rows go, but every
        submitted answer stays on the hash-chained record as an
        'assessment_superseded' entry (verdict, notes, checklist, who and
        when, the documents it carried). Its documents stay on the change."""
        from app.models.change import ChangeAttachment
        names = await EarlyStageService._dept_names(
            session, [a.department_id for a in change.assessments])
        done = [a for a in change.assessments
                if a.submitted_at is not None or a.verdict != "pending"]
        for a in done:
            atts = (await session.execute(
                select(ChangeAttachment).where(
                    ChangeAttachment.assessment_id == a.id))).scalars().all()
            for att in atts:
                att.assessment_id = None
            details = a.details_dict
            details.pop("draft", None)
            await ChangeService.append_changelog(
                session, change, "assessment_superseded",
                f"Assessment of {names.get(a.department_id, a.department_id)} "
                f"superseded ({cm_labels.label('verdict', a.verdict)}): {reason}",
                user_id,
                old_value={
                    "assessment_id": a.id, "department_id": a.department_id,
                    "department_name": names.get(a.department_id),
                    "stage_order": a.stage_order, "rasic_letter": a.rasic_letter,
                    "verdict": a.verdict, "notes": a.notes,
                    "conditions": a.conditions, "details": details,
                    "submitted_by": a.submitted_by,
                    "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                    "attachment_ids": [x.id for x in atts]},
                notes=reason)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "back_to_scoping",
            f"Back to scoping after 'not feasible': {reason}", user_id,
            new_value={"reason": reason,
                       "superseded_assessment_ids": [a.id for a in done]},
            notes=reason)

    # ------------------------------------------------------------------
    # Stage state: the cockpit's data (P1-5 .. P1-8, P2)
    # ------------------------------------------------------------------
    @staticmethod
    async def _dept_names(session: AsyncSession, ids) -> dict[int, str]:
        ids = {i for i in ids if i is not None}
        if not ids:
            return {}
        return {i: n for i, n in (await session.execute(
            select(Department.id, Department.name).where(Department.id.in_(ids))))}

    @staticmethod
    async def _user_names(session: AsyncSession, ids) -> dict[int, str]:
        ids = {i for i in ids if i is not None}
        if not ids:
            return {}
        return {i: (f or u) for i, f, u in (await session.execute(
            select(User.id, User.full_name, User.username).where(User.id.in_(ids))))}

    @staticmethod
    async def assessment_state(session: AsyncSession, change: ChangeRequest,
                               user: User) -> Optional[dict]:
        if change.routing is None and not change.assessments:
            return None
        first = EarlyStageService.first_stage(change)
        rows = [a for a in change.assessments
                if EarlyStageService.is_assessment_row(a, first)]
        from app.services.risk_types import labels_for_keys
        concerns = [c for c in change.concerns
                    if c.kind == "risk" and c.is_open]
        names = await EarlyStageService._dept_names(
            session, [a.department_id for a in rows]
            + [c.department_id for c in concerns])
        type_labels = await labels_for_keys(session, {c.risk_type for c in concerns})

        def done(a):
            return (a.effective_status in ("submitted", "waived")
                    or a.submitted_at is not None or a.verdict != "pending")

        blocking = [a for a in rows if a.rasic_letter in BLOCKING_LETTERS]
        submitted = [a for a in blocking if done(a)]
        waiting = [a for a in blocking if not done(a)]
        ppt = {att.assessment_id for att in change.attachments
               if att.kind == "change_ppt" and att.assessment_id is not None}
        by_dept_rows: dict[int, list] = {}
        for a in change.assessments:
            by_dept_rows.setdefault(a.department_id, []).append(a.id)
        risks_by_dept: dict[int, int] = {}
        for c in concerns:
            risks_by_dept[c.department_id] = risks_by_dept.get(c.department_id, 0) + 1

        def dept(a):
            return {"department_id": a.department_id,
                    "department_name": names.get(a.department_id),
                    "assessment_id": a.id, "rasic_letter": a.rasic_letter}

        not_feasible = [
            {**dept(a),
             "has_change_ppt": any(i in ppt for i in by_dept_rows.get(a.department_id, []))}
            for a in rows if a.verdict == "not_feasible"]
        declined = [
            {**dept(a), "to_letter": a.pending_rasic_letter}
            for a in rows if a.pending_rasic_letter]
        verdicts = [
            {**dept(a), "verdict": a.verdict,
             "verdict_label": cm_labels.label("verdict", a.verdict),
             "open_risks": risks_by_dept.get(a.department_id, 0)}
            for a in rows if done(a)]
        risks = [{"id": c.id, "department_id": c.department_id,
                  "department_name": names.get(c.department_id),
                  "risk_type": c.risk_type,
                  "risk_type_label": type_labels.get(c.risk_type),
                  "severity": c.severity, "note": c.note,
                  "checklist_key": c.checklist_key} for c in concerns]
        all_submitted = bool(blocking) and not waiting
        routing_pending = (change.routing is not None
                           and change.routing.deviation_status == "pending_approval")
        rights = await EarlyStageService.transition_refusal(
            session, change, user, "costing") is None
        return {
            "first_stage": first,
            "total": len(blocking),
            "submitted": len(submitted),
            "all_submitted": all_submitted,
            "waiting_on": [dept(a) for a in waiting],
            "not_feasible": not_feasible,
            "declined_pending": declined,
            "verdicts": verdicts,
            "open_risks": risks,
            "routing_deviation_pending": routing_pending,
            "can_close": (change.status == "in_assessment" and all_submitted
                          and not not_feasible and not routing_pending
                          and rights),
        }

    @staticmethod
    async def routing_deviation_state(session: AsyncSession,
                                      change: ChangeRequest,
                                      user: User) -> Optional[dict]:
        """Who decides the pending routing deviation, in words the wait row
        can use: a bundle the lead filed none of is the lead's call; once the
        lead filed any request of it, Project Management's (anyone who filed
        none). The same rule as user_can_decide_deviation, over the same
        proposers."""
        routing = change.routing
        if routing is None or routing.deviation_status != "pending_approval":
            return None
        from app.services.change_routing_service import ChangeRoutingService, _pending_proposers
        proposer = routing.deviation_proposed_by
        proposers = await _pending_proposers(session, routing)
        names = await EarlyStageService._user_names(session, [proposer, change.lead_id])
        proposer_is_lead = change.lead_id is not None and change.lead_id in proposers
        if change.lead_id is None:
            decider, decider_id = "anyone_but_proposer", None
            text = "Routing change pending: anyone but the proposer decides"
        elif proposer_is_lead:
            decider, decider_id = "pm", None
            text = ("Routing change includes a request by the change lead: waiting for "
                    "Project Management to decide")
        else:
            decider, decider_id = "lead", change.lead_id
            text = ("Routing change pending: waiting for the change lead "
                    f"({names.get(change.lead_id)}) to decide")
        return {
            "status": routing.deviation_status,
            "reason": routing.deviation_note,
            "proposed_by": proposer,
            "proposed_by_name": names.get(proposer),
            "proposer_is_lead": proposer_is_lead,
            "decider": decider,
            "decider_user_id": decider_id,
            "decider_name": names.get(decider_id) if decider_id else None,
            "can_decide": ChangeRoutingService.user_can_decide_deviation(
                change, routing, user.id,
                acting=is_acting(user), proposers=proposers),
            "text": text,
        }

    @staticmethod
    async def end_state(session: AsyncSession,
                        change: ChangeRequest) -> Optional[dict]:
        """Rejected (also after it was closed) and cancelled are end states
        of their own: where the flow stopped, when, by whom, why. Read from
        the status changelog."""
        if change.status not in ("rejected", "cancelled", "closed"):
            return None
        hops = (await session.execute(
            select(ChangeChangelog).where(
                ChangeChangelog.change_id == change.id,
                ChangeChangelog.field_name == "status")
            .order_by(ChangeChangelog.performed_at, ChangeChangelog.id)
        )).scalars().all()

        def val(raw):
            try:
                return json.loads(raw) if raw is not None else None
            except (TypeError, ValueError):
                return raw

        seq = [(val(h.old_value), val(h.new_value), h) for h in hops]
        kind = None
        if change.status in ("rejected", "cancelled"):
            kind = change.status
        elif seq and seq[-1][1] == "closed" and seq[-1][0] == "rejected":
            kind = "rejected"
        if kind is None:
            return None
        idx = max((i for i, (_, new, _h) in enumerate(seq) if new == kind),
                  default=None)
        stopped_at, at, by = None, None, None
        if idx is not None:
            stopped_at, _, hop = seq[idx]
            at, by = hop.performed_at, hop.performed_by
            # A hold is not a stage: look through it to the stage it held.
            j = idx
            while stopped_at == "on_hold" and j > 0:
                j -= 1
                if seq[j][1] == "on_hold":
                    stopped_at = seq[j][0]
        names = await EarlyStageService._user_names(session, [by])
        reason = (change.cancellation_reason if kind == "cancelled"
                  else change.rejection_reason)
        return {
            "kind": kind,
            "status": change.status,
            "closed": change.status == "closed",
            "stopped_at": stopped_at,
            "stopped_at_label": cm_labels.label("status", stopped_at) if stopped_at else None,
            "at": at,
            "by": by,
            "by_name": names.get(by),
            "reason": reason,
            "label": cm_labels.label("status", kind),
        }

    @staticmethod
    async def stage_state(session: AsyncSession, change: ChangeRequest,
                          user: User) -> dict:
        from app.services.meeting_service import MeetingService
        assessment = await EarlyStageService.assessment_state(session, change, user)
        routing_dev = await EarlyStageService.routing_deviation_state(
            session, change, user)
        end = await EarlyStageService.end_state(session, change)
        scope = await EarlyStageService.scope_change_state(session, change)
        live = change.status not in ("released", "closed", "rejected", "cancelled")
        waits: list[dict] = []

        if live and change.lead_id is None:
            waits.append({"kind": "no_lead", "text": "No lead assigned",
                          "target_tab": "overview"})
        if change.status == "captured":
            missing = await ChangeService.kickoff_missing(session, change)
            if missing:
                waits.append({"kind": "kickoff_missing",
                              "text": "Capture incomplete: missing " + ", ".join(missing),
                              "missing": missing, "target_tab": "overview"})
        open_concerns = MeetingService.open_concerns(change) if live else []
        votes = [c for c in open_concerns if c.kind == "reject_proposal"]
        if votes:
            who = ", ".join(sorted({c.raised_by_name or f"user {c.raised_by}"
                                    for c in votes}))
            waits.append({"kind": "open_cancel_votes",
                          "text": f"{len(votes)} open cancel vote(s) from {who}",
                          "concern_ids": [c.id for c in votes],
                          "target_tab": "scoping"})
        unanswered = [c for c in ChangeService.unanswered_questions(change)] if live else []
        if unanswered:
            waits.append({"kind": "waiting_on_sales_answer",
                          "text": f"Waiting on Sales to answer {len(unanswered)} question(s)",
                          "concern_ids": [c.id for c in unanswered],
                          "target_tab": "scoping"})
        if change.status == "scoping" and change.impact_confirmed_at is None:
            from app.services import mother_plants as mp
            if mp.is_mother_plant(change):
                # no proceed meeting on this track: the lock is what
                # scoping -> approved waits on (approval_blocker)
                waits.append({"kind": "impact_not_locked",
                              "text": ("Impacted set is not locked: Development "
                                       "confirms the impacted items"),
                              "target_tab": "impacted"})
        if change.status == "scoping":
            from app.services import mother_plants as mp
            # A mother-plant change has no cost carrier: its scoping record
            # only says who is informed (spec §14).
            open_meetings = [] if mp.is_mother_plant(change) else \
                [m for m in change.meetings if m.decision is None]
            if open_meetings and all(m.cost_carrier is None for m in open_meetings):
                waits.append({"kind": "cost_carrier_unconfirmed",
                              "text": "Cost carrier not confirmed at the scoping meeting",
                              "target_tab": "scoping"})
        if change.status == "in_assessment" and assessment is not None:
            if assessment["waiting_on"]:
                names = ", ".join(d["department_name"] or str(d["department_id"])
                                  for d in assessment["waiting_on"])
                waits.append({"kind": "assessment_waiting",
                              "text": (f"Assessment: waiting on {names} "
                                       f"({assessment['submitted']}/{assessment['total']})"),
                              "target_tab": "assessments"})
            for d in assessment["declined_pending"]:
                waits.append({"kind": "declined_pending",
                              "text": f"{d['department_name']}: declined, awaiting decision",
                              "department_id": d["department_id"],
                              "target_tab": "assessments"})
            for d in assessment["not_feasible"]:
                waits.append({"kind": "not_feasible",
                              "text": (f"{d['department_name']}: not feasible "
                                       + ("(Change PPT)" if d["has_change_ppt"]
                                          else "(no Change PPT)")),
                              "department_id": d["department_id"],
                              "assessment_id": d["assessment_id"],
                              "has_change_ppt": d["has_change_ppt"],
                              "target_tab": "assessments"})
        if routing_dev is not None and live:
            waits.append({"kind": "routing_deviation_pending",
                          "text": routing_dev["text"], "target_tab": "assessments"})
        if scope is not None and not scope["covered"] and live:
            v = scope["offer_version"]
            waits.append({"kind": "scope_not_covered",
                          "text": (f"Offer v{v} no longer covers the scope: "
                                   if v else "The offer no longer covers the scope: ")
                          + "new offer version or approved deviation",
                          "target_tab": "offer"})

        return {
            "change_id": change.id,
            "status": change.status,
            "status_label": cm_labels.label("status", change.status),
            "can_transition": await EarlyStageService.transition_rights(
                session, change, user),
            "transition_blocks": (await EarlyStageService.transition_blocks(
                session, change) if live else {}),
            "can_edit_impact": (
                change.status not in IMPACT_LOCKED_STATUSES
                and await EarlyStageService.impact_edit_refusal(
                    session, change, user) is None),
            "impact_edit_needs_reason": EarlyStageService.post_quote(change),
            "lead_assigned": change.lead_id is not None,
            "can_record_meeting": (
                change.status == "scoping"
                and await EarlyStageService._may_record_meeting(session, change, user)),
            "title_auto": bool(change.title_auto),
            "assessment": assessment,
            "routing_deviation": routing_dev,
            "end_state": end,
            "scope_change": scope,
            "waits": waits,
        }

    @staticmethod
    async def _may_record_meeting(session, change, user) -> bool:
        """Mirrors MeetingService._authz: the change lead, PM, admin."""
        from app.services.meeting_service import MeetingService
        from app.services.change_people import holds_lead
        if holds_lead(change, user):
            return True
        return await MeetingService.user_is_pm(session, user)

    # ------------------------------------------------------------------
    # Lead picker candidates
    # ------------------------------------------------------------------
    @staticmethod
    async def lead_candidates(session: AsyncSession,
                              change: ChangeRequest) -> list[dict]:
        """[{id, name, department, is_default}]: active users of the change's
        organization in the Project Manager department, plus the current
        lead. is_default marks the project's Project Manager responsible
        (the project team's standard PM), sorted first. Duplicate names get
        the username added so two people never read the same."""
        from app.models.entities import Plant, Project
        from app.models.workflow import UserDepartment
        from app.services.project_team_service import ProjectTeamService
        org_id = (await session.execute(
            select(Plant.organization_id).join(Project, Project.plant_id == Plant.id)
            .where(Project.id == change.project_id))).scalar_one_or_none()
        pm_id = (await session.execute(
            select(Department.id).where(Department.name == "Project Manager")
        )).scalar_one_or_none()
        default_id = await ProjectTeamService.responsible_user_id(
            session, change.project_id, "Project Manager")
        users: dict[int, tuple] = {}
        if pm_id is not None:
            q = (select(User).join(UserDepartment, UserDepartment.user_id == User.id)
                 .where(UserDepartment.department_id == pm_id,
                        User.is_active.is_(True)))
            if org_id is not None:
                q = q.where(User.organization_id == org_id)
            for u in (await session.execute(q)).scalars().all():
                users[u.id] = (u, "Project Manager")
        if change.lead_id is not None and change.lead_id not in users:
            lead = await session.get(User, change.lead_id)
            if lead is not None:
                depts = [n for (n,) in (await session.execute(
                    select(Department.name)
                    .join(UserDepartment, UserDepartment.department_id == Department.id)
                    .where(UserDepartment.user_id == lead.id)
                    .order_by(Department.name))).all()]
                users[lead.id] = (lead, ", ".join(depts) or None)
        base = {uid: (u.full_name or u.username) for uid, (u, _) in users.items()}
        counts: dict[str, int] = {}
        for n in base.values():
            counts[n.lower()] = counts.get(n.lower(), 0) + 1
        out = []
        for uid, (u, dept) in users.items():
            name = base[uid]
            if counts[name.lower()] > 1 and u.username and u.username != name:
                name = f"{name} ({u.username})"
            out.append({"id": uid, "name": name, "department": dept,
                        "is_default": uid == default_id,
                        "is_current": uid == change.lead_id})
        return sorted(out, key=lambda r: (
            not r["is_current"], not r["is_default"], r["name"].lower()))

    # ------------------------------------------------------------------
    # Served-by objects for parts, before routing exists
    # ------------------------------------------------------------------
    @staticmethod
    async def impact_objects(session: AsyncSession, change: ChangeRequest,
                             part_ids: list[int]) -> dict:
        """The objects that serve the given parts (tools, their stations,
        EOAT and gauges, equipment...), by the same two-hop relation walk
        as the assessment buckets, so the impact tree can show parts ->
        tools during scoping, before any department is routed.

        {"parts": [{"part_id", "served_by": [{id, number, name, category,
        type, via_part_id}]}], "departments": [{"department_name",
        "objects": [...]}]}"""
        from app.models.part import PartRelation
        wanted = {p for (p,) in (await session.execute(
            select(Part.id).where(Part.project_id == change.project_id,
                                  Part.id.in_(set(part_ids))))).all()} if part_ids else set()

        async def step(ids):
            if not ids:
                return {}
            rows = (await session.execute(select(PartRelation).where(
                PartRelation.from_part_id.in_(ids) | PartRelation.to_part_id.in_(ids)
            ))).scalars().all()
            out: dict[int, set] = {}
            for r in rows:
                if r.from_part_id in ids:
                    out.setdefault(r.from_part_id, set()).add(r.to_part_id)
                if r.to_part_id in ids:
                    out.setdefault(r.to_part_id, set()).add(r.from_part_id)
            return out

        found: dict[int, int] = {}
        for pid, others in (await step(set(wanted))).items():
            for o in others:
                if o not in wanted:
                    found.setdefault(o, pid)
        parts = {p.id: p for p in (await session.execute(
            select(Part).where(Part.id.in_(set(found) | wanted)))).scalars().all()}
        tools = {pid for pid in found if parts.get(pid) is not None
                 and parts[pid].item_category == "tool"}
        for tid, others in (await step(tools)).items():
            for o in others:
                if o not in wanted and o not in found:
                    found[o] = found[tid]
        missing = set(found) - set(parts)
        if missing:
            parts.update({p.id: p for p in (await session.execute(
                select(Part).where(Part.id.in_(missing)))).scalars().all()})

        def obj(p, via):
            return {"id": p.id, "number": p.part_number, "name": p.name,
                    "category": p.item_category,
                    "type": ChangeService._OBJECT_TYPE_BY_CATEGORY.get(
                        p.item_category, p.item_category),
                    "via_part_id": via}

        by_part: dict[int, list] = {pid: [] for pid in sorted(wanted)}
        for oid, via in sorted(found.items()):
            p = parts.get(oid)
            if p is not None:
                by_part.setdefault(via, []).append(obj(p, via))
        departments = []
        for dname, cats in ChangeService._DOMAIN_BY_DEPARTMENT.items():
            objs = [o for lst in by_part.values() for o in lst if o["category"] in cats]
            objs += [obj(parts[p], p) for p in sorted(wanted)
                     if p in parts and parts[p].item_category in cats]
            if objs:
                departments.append({"department_name": dname, "objects": objs})
        return {"parts": [{"part_id": pid, "served_by": lst}
                          for pid, lst in by_part.items()],
                "departments": departments}

    # ------------------------------------------------------------------
    # P1-9: the change's own audit trail
    # ------------------------------------------------------------------
    @staticmethod
    async def audit_condition(session: AsyncSession, change: ChangeRequest):
        """AuditLog rows that belong to this change by ENTITY, not by the
        change-number text (a reused number would pull another change's
        history in): the change itself, its workflow instances (the change
        scoped ones and the ECN flows on revisions it originated) and those
        revisions."""
        from app.models.entities import AuditLog
        from app.models.part import PartRevision
        from app.models.workflow import WfInstance
        rev_ids = [r for (r,) in (await session.execute(
            select(PartRevision.id).where(
                PartRevision.originating_change_id == change.id))).all()]
        inst_cond = WfInstance.change_id == change.id
        if rev_ids:
            inst_cond = inst_cond | WfInstance.part_revision_id.in_(rev_ids)
        inst_ids = [i for (i,) in (await session.execute(
            select(WfInstance.id).where(inst_cond))).all()]
        conds = [and_(AuditLog.entity_type == "change",
                      AuditLog.entity_id == change.id)]
        if inst_ids:
            conds.append(and_(AuditLog.entity_type == "wf_instance",
                              AuditLog.entity_id.in_(inst_ids)))
        if rev_ids:
            conds.append(and_(AuditLog.entity_type == "part_revision",
                              AuditLog.entity_id.in_(rev_ids)))
        return or_(*conds)

    # ------------------------------------------------------------------
    # P2: attendee list without non-person entries
    # ------------------------------------------------------------------
    NON_PERSON_PREFIXES = ("admin", "smoke", "live-verify", "verify", "e2e",
                           "test", "plm2-service", "service", "system", "bot")

    @staticmethod
    def is_person_contact(entry: dict, *, is_user: bool = False) -> bool:
        """A contact the attendee picker should offer: a real mailbox, not a
        service token, a smoke-test or an admin account.

        is_user: the entry is an actual PLM2 User row (a local user, or a hub
        entry resolved to one by email). Its mail domain proves nothing then:
        a real colleague on an on-prem ``.local`` or a seeded example.com
        address is still a person; only the name checks apply."""
        email = (entry.get("email") or "").strip().lower()
        name = (entry.get("name") or "").strip().lower()
        if "@" not in email and not is_user:
            return False
        local, _, domain = email.partition("@")
        if not is_user and (domain.endswith(".local")
                            or domain in ("example.com", "example.org")):
            return False
        username = (entry.get("username") or "").strip().lower()
        for probe in (local, username, name):
            if not probe:
                continue
            if any(probe == p or probe.startswith(p + "-") or probe.startswith(p + ".")
                   or probe.startswith(p + "_") or (p in ("admin", "e2e") and probe.startswith(p))
                   for p in EarlyStageService.NON_PERSON_PREFIXES):
                return False
            if "service" in probe or "token" in probe:
                return False
        return True
