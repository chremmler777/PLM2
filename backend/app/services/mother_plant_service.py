"""Mother-plant changes (spec 2026-09-25 §14): the rules.

The side track is `captured -> scoping -> approved -> in_implementation ->
in_validation -> released -> closed`. There is no assessment, costing or
quote: the mother plant engineered and sold the change. What we do:

- at scoping the PM informs the teams ("Send information": one receipt per
  department, a "Read and understood" task for its members, a note back);
- scoping -> approved is hard-gated on the impact lock and the inform list
  being sent; entering approved sets the release deadline to the mother
  plant's SOP and seeds the detailed plan from their MS Project file (or a
  plan holding just the SOP milestone);
- the validated timing is not published to a customer: an "Inform mother
  plant" stamp records that the PM told the mother plant.

Refusals: ChangeError (400), MotherPlantForbidden (403), MotherPlantNotFound
(404).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeAttachment, ChangeRequest
from app.models.change_info import ChangeInfoReceipt
from app.models.entities import User
from app.models.workflow import Department
from app.services import mother_plants as cfg
from app.services.change_service import ChangeError, ChangeService

logger = logging.getLogger(__name__)

PM_DEPARTMENT = "Project Manager"
# Statuses in which the PM may (still) inform departments: first at scoping,
# and later to add a department that was forgotten.
SEND_WINDOW = ("scoping", "approved", "in_implementation")
# The "Inform mother plant" stamp: the validated timing, while it is live.
INFORM_WINDOW = ("approved", "in_implementation")


class MotherPlantForbidden(PermissionError):
    """Mapped to HTTP 403."""


class MotherPlantNotFound(LookupError):
    """Mapped to HTTP 404."""


def _require_mother_plant(change: ChangeRequest) -> None:
    if not cfg.is_mother_plant(change):
        raise ChangeError(
            f"This is not a change from {cfg.FALLBACK_NAME}")


class MotherPlantService:

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------
    @staticmethod
    def check_capture(name: Optional[str], ref: Optional[str],
                      sop: Optional[date]) -> tuple[str, Optional[str], date]:
        """(name, ref, sop) cleaned, or ChangeError. The name must be one of
        the configured mother plants (default Weissenburg); the SOP date is
        required: it becomes the release deadline."""
        name = (name or "").strip() or cfg.DEFAULT_MOTHER_PLANT
        if name not in cfg.MOTHER_PLANTS:
            raise ChangeError(
                f"Unknown plant '{name}' - one of "
                + ", ".join(cfg.MOTHER_PLANTS))
        if sop is None:
            raise ChangeError(
                f"The SOP date of {name} is required: it becomes the "
                "release deadline")
        ref = (ref or "").strip() or None
        if ref is not None and len(ref) > 120:
            raise ChangeError(f"The reference of {name} is at most 120 characters")
        return name, ref, sop

    @staticmethod
    async def may_start(session: AsyncSession, user: User) -> bool:
        """can_start_change departments (and admin), plus Project Management
        whatever its flag says: the PM is who hears from the mother plant."""
        if await ChangeService.user_can_start_change(session, user):
            return True
        return await ChangeService._user_in_department(session, user, PM_DEPARTMENT)

    # ------------------------------------------------------------------
    # Rights
    # ------------------------------------------------------------------
    @staticmethod
    async def may_send(session: AsyncSession, change: ChangeRequest,
                       user: User) -> bool:
        """PM, the change lead, admin: informing the team, moving the change
        to approved and stamping "Inform mother plant" are the PM's acts."""
        # An admin acting as a department is that department here: the
        # personal lead privilege steps aside (same as the change page).
        from app.services.change_people import holds_lead
        if holds_lead(change, user):
            return True
        return await ChangeService._user_in_department(session, user, PM_DEPARTMENT)

    @staticmethod
    async def _my_department_ids(session: AsyncSession, user: User) -> set[int]:
        from app.services.workflow_service import WorkflowService
        return set(await WorkflowService.effective_department_ids(session, user))

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def receipts(session: AsyncSession,
                       change: ChangeRequest) -> list[ChangeInfoReceipt]:
        return list((await session.execute(
            select(ChangeInfoReceipt)
            .where(ChangeInfoReceipt.change_id == change.id)
            .order_by(ChangeInfoReceipt.id))).scalars().all())

    @staticmethod
    async def default_department_ids(session: AsyncSession,
                                     change: ChangeRequest) -> list[int]:
        """The physical-part routing's stage-1 departments: the teams that
        would have assessed the change had it been ours to engineer."""
        from app.services.change_routing_service import ChangeRoutingService
        try:
            _, _, stages = await ChangeRoutingService.resolve_standard(
                session, "physical_part")
        except ChangeError:
            return []
        stage1 = next((s for s in stages if s["stage_order"] == 1), None)
        ids = {d["department_id"] for d in (stage1 or {}).get("departments", [])}
        if not ids:
            return []
        rows = (await session.execute(
            select(Department.id).where(Department.id.in_(ids),
                                        Department.is_active.is_(True))
            .order_by(Department.sort_order, Department.name))).scalars().all()
        return list(rows)

    @staticmethod
    def timing_attachment(change: ChangeRequest) -> Optional[ChangeAttachment]:
        """The mother plant's timing file, the newest one."""
        rows = [a for a in (change.attachments or [])
                if a.kind == cfg.TIMING_ATTACHMENT_KIND]
        return max(rows, key=lambda a: (a.created_at or datetime.min, a.id),
                   default=None)

    @staticmethod
    def receipt_out(r: ChangeInfoReceipt, names: dict[int, str]) -> dict:
        return {
            "id": r.id, "department_id": r.department_id,
            "department_name": names.get(r.department_id),
            "sent_by": r.sent_by, "sent_by_name": r.sent_by_name,
            "sent_at": r.sent_at,
            "acknowledged_by": r.acknowledged_by,
            "acknowledged_by_name": r.acknowledged_by_name,
            "acknowledged_at": r.acknowledged_at, "note": r.note,
        }

    @staticmethod
    async def state(session: AsyncSession, change: ChangeRequest,
                    user: User) -> dict:
        """Everything the Mother plant tab shows, with the caller's rights."""
        _require_mother_plant(change)
        names = dict((await session.execute(
            select(Department.id, Department.name))).all())
        receipts = await MotherPlantService.receipts(session, change)
        mine = await MotherPlantService._my_department_ids(session, user)
        timing = MotherPlantService.timing_attachment(change)
        docs = [a for a in (change.attachments or [])
                if a.kind == "general" and a.concern_id is None
                and a.assessment_id is None and a.validation_issue_id is None]
        return {
            "change_id": change.id,
            "mother_plant_name": change.mother_plant_name,
            "mother_plant_ref": change.mother_plant_ref,
            "mother_plant_sop": change.mother_plant_sop,
            "mother_plants": list(cfg.MOTHER_PLANTS),
            "default_department_ids":
                await MotherPlantService.default_department_ids(session, change),
            "receipts": [MotherPlantService.receipt_out(r, names) for r in receipts],
            "open_count": sum(1 for r in receipts if r.is_open),
            "timing_attachment": ({
                "id": timing.id, "filename": timing.filename,
                "created_at": timing.created_at,
            } if timing is not None else None),
            "documents": [{"id": a.id, "filename": a.filename,
                           "created_at": a.created_at,
                           "uploaded_by_name": a.uploaded_by_name}
                          for a in docs],
            "informed_at": change.plan_published_at,
            "informed_by_name": change.plan_published_by_name,
            "can_send": (change.status in SEND_WINDOW
                         and await MotherPlantService.may_send(session, change, user)),
            "can_inform": (change.status in INFORM_WINDOW
                           and change.timing_validated_at is not None
                           and await MotherPlantService.may_send(session, change, user)),
            "my_open_receipt_ids": [r.id for r in receipts
                                    if r.is_open and r.department_id in mine],
        }

    # ------------------------------------------------------------------
    # Inform the team
    # ------------------------------------------------------------------
    @staticmethod
    async def send_info(session: AsyncSession, change: ChangeRequest,
                        department_ids: list[int], user: User,
                        message: Optional[str] = None) -> list[ChangeInfoReceipt]:
        """One receipt per department not informed yet; its members get a
        notification and a "Read and understood" task."""
        _require_mother_plant(change)
        if not await MotherPlantService.may_send(session, change, user):
            raise MotherPlantForbidden(
                "Only Project Management, the change lead or an admin may "
                "send the information to the team")
        if change.status not in SEND_WINDOW:
            raise ChangeError(
                f"The team is informed at scoping (or later, to add a "
                f"department), not while the change is '{change.status}'")
        wanted = sorted({int(d) for d in department_ids or []})
        if not wanted:
            raise ChangeError("Select at least one department to inform")
        depts = {d.id: d for d in (await session.execute(
            select(Department).where(Department.id.in_(wanted)))).scalars().all()}
        unknown = [d for d in wanted if d not in depts or not depts[d].is_active]
        if unknown:
            raise ChangeError(
                "Unknown or inactive department(s): "
                + ", ".join(str(d) for d in unknown))
        existing = {r.department_id for r in
                    await MotherPlantService.receipts(session, change)}
        new = [d for d in wanted if d not in existing]
        if not new:
            raise ChangeError("Every selected department is already informed")
        now = datetime.utcnow()
        rows = []
        for did in new:
            r = ChangeInfoReceipt(change_id=change.id, department_id=did,
                                  sent_by=user.id, sent_at=now)
            session.add(r)
            rows.append(r)
        await session.flush()
        message = (message or "").strip() or None
        dept_names = [depts[d].name for d in new]
        await ChangeService.append_changelog(
            session, change, "mother_plant_info_sent",
            "Information sent to " + ", ".join(dept_names), user.id,
            new_value={"department_ids": new, "message": message},
            notes=message)
        # the members of the change's organization only (change_people)
        from app.services.change_people import department_members_of_change_org
        members = set(await department_members_of_change_org(session, change, new))
        members.discard(user.id)
        if members:
            from app.services.notification_service import NotificationService
            await NotificationService.notify_team(
                session, change.project_id, new, sorted(members),
                kind="change_info_sent",
                subject_key=f"change:{change.id}:info",
                title=(f"{change.change_number}: change from "
                       f"{cfg.plant_name(change)}, read and confirm")[:255],
                body=message or change.title,
                link=f"/changes/{change.id}?tab=mother")
        return rows

    @staticmethod
    async def acknowledge(session: AsyncSession, change: ChangeRequest,
                          receipt_id: int, user: User,
                          note: Optional[str] = None) -> ChangeInfoReceipt:
        """"Read and understood" by a member of the informed department,
        optionally with a note back to the PM."""
        _require_mother_plant(change)
        r = await session.get(ChangeInfoReceipt, receipt_id)
        if r is None or r.change_id != change.id:
            raise MotherPlantNotFound("Receipt not found on this change")
        if r.department_id not in await MotherPlantService._my_department_ids(
                session, user):
            raise MotherPlantForbidden(
                "Only a member of the informed department may confirm it "
                "read the information")
        if not r.is_open:
            raise ChangeError("This department already confirmed it read the information")
        note = (note or "").strip() or None
        r.acknowledged_by = user.id
        r.acknowledged_at = datetime.utcnow()
        r.note = note
        await session.flush()
        dept = await session.get(Department, r.department_id)
        dname = dept.name if dept else f"#{r.department_id}"
        await ChangeService.append_changelog(
            session, change, "mother_plant_info_acknowledged",
            f"{dname}: read and understood" + (f" ({note})" if note else ""),
            user.id, notes=note,
            new_value={"receipt_id": r.id, "department_id": r.department_id,
                       "note": note},
            for_department_id=r.department_id)
        if note and r.sent_by != user.id:
            from app.services.notification_service import NotificationService
            await NotificationService.notify_once(
                session, [r.sent_by], kind="change_info_note",
                subject_key=f"change:{change.id}:info:{r.id}",
                title=f"{change.change_number}: {dname} read the information"[:255],
                body=note, link=f"/changes/{change.id}?tab=mother")
        return r

    # ------------------------------------------------------------------
    # The transition into approved
    # ------------------------------------------------------------------
    @staticmethod
    async def approval_blocker(session: AsyncSession,
                               change: ChangeRequest) -> Optional[str]:
        """The hard gates on scoping -> approved, in words; None when clear."""
        if change.impact_confirmed_at is None:
            return ("Impacted set is not locked - Development confirms the "
                    "impacted items first")
        if not await MotherPlantService.receipts(session, change):
            return "The team is not informed yet - send the information first"
        if change.mother_plant_sop is None:
            return f"The SOP date of {cfg.plant_name(change)} is missing"
        return None

    @staticmethod
    async def on_approved(session: AsyncSession, change: ChangeRequest,
                          user_id: int) -> None:
        """Entering approved: the SOP becomes the release deadline, and the
        detailed plan starts from the mother plant's timing (their MS Project
        file) or, without one, from the SOP milestone alone."""
        from app.services.change_plan_service import ChangePlanService
        sop = change.mother_plant_sop
        await ChangeService._apply_release_deadline(
            session, change, datetime.combine(sop, time()), cfg.sop_reason(change),
            user_id)
        user = await session.get(User, user_id)
        if await ChangePlanService.tasks(session, change, "detailed"):
            return
        att = MotherPlantService.timing_attachment(change)
        if att is not None:
            try:
                with open(att.stored_path, "rb") as fh:
                    content = fh.read()
                result = await ChangePlanService.import_mspdi(
                    session, change, "detailed", content, user)
                await ChangeService.append_changelog(
                    session, change, "mother_plant_timing_imported",
                    f"Detailed plan seeded from the timing of "
                    f"{cfg.plant_name(change)} "
                    f"({att.filename}, {result['tasks']} blocks)", user_id,
                    new_value={"attachment_id": att.id, "tasks": result["tasks"],
                               "warnings": result.get("warnings") or []})
                return
            except (OSError, ChangeError) as e:
                # A file that cannot be read must not strand the change in
                # scoping: the SOP milestone stands in and the log says why.
                logger.warning("mother-plant timing import failed: %s", e)
                await ChangeService.append_changelog(
                    session, change, "mother_plant_timing_import_failed",
                    f"The timing of {cfg.plant_name(change)} ({att.filename}) "
                    f"could not be imported: {e}", user_id,
                    new_value={"attachment_id": att.id})
        await ChangePlanService.add_task(session, change, "detailed", {
            "name": f"SOP ({cfg.plant_name(change)})", "kind": "milestone",
            "lane": cfg.plant_name(change), "start_date": sop, "duration_days": 0,
        }, user)

    # ------------------------------------------------------------------
    # "Inform mother plant" (instead of the customer publish)
    # ------------------------------------------------------------------
    @staticmethod
    async def inform_timing(session: AsyncSession, change: ChangeRequest,
                            user: User) -> ChangeRequest:
        """The PM stamps that the validated timing went to the mother plant.
        Same columns as the customer publish (plan_published_*), which a
        mother-plant change never uses; restamping refreshes it."""
        _require_mother_plant(change)
        if not await MotherPlantService.may_send(session, change, user):
            raise MotherPlantForbidden(
                "Only Project Management, the change lead or an admin may "
                f"inform {cfg.plant_name(change)}")
        if change.status not in INFORM_WINDOW:
            raise ChangeError(
                f"{cfg.plant_name(change)} is informed of the timing while the "
                "change is approved or in implementation")
        if change.timing_validated_at is None:
            raise ChangeError(
                f"Validate the timing first: {cfg.plant_name(change)} is told "
                "the baseline every team confirmed")
        previous = change.plan_published_at
        change.plan_published_by = user.id
        change.plan_published_at = datetime.utcnow()
        await ChangeService.append_changelog(
            session, change, "mother_plant_informed",
            (f"{cfg.plant_name(change)} informed again of the timing" if previous
             else f"{cfg.plant_name(change)} informed of the validated timing"),
            user.id, field_name="plan_published_at",
            old_value={"published_at": previous.isoformat()} if previous else None,
            new_value={"published_at": change.plan_published_at.isoformat(),
                       "mother_plant": change.mother_plant_name})
        return change

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    @staticmethod
    async def my_actions(session: AsyncSession, change: ChangeRequest,
                         user: User, dept_ids: set) -> list[dict]:
        """Cockpit items: "Send information to the team" for the PM at
        scoping, "Read and understood" per open receipt of the caller's
        departments, "Inform the mother plant" once the timing is validated."""
        if not cfg.is_mother_plant(change):
            return []
        out: list[dict] = []
        receipts = await MotherPlantService.receipts(session, change)
        may_send = await MotherPlantService.may_send(session, change, user)
        if change.status == "scoping" and not receipts and may_send:
            out.append({"kind": "info_send",
                        "label": "Send information to the team",
                        "target_tab": "mother"})
        names = dict((await session.execute(
            select(Department.id, Department.name))).all()) if receipts else {}
        for r in receipts:
            if r.is_open and r.department_id in dept_ids:
                out.append({"kind": "info_ack",
                            "label": f"Read and understood: "
                                     f"{names.get(r.department_id, r.department_id)}",
                            "target_tab": "mother", "receipt_id": r.id,
                            "department_id": r.department_id})
        if (change.status in INFORM_WINDOW and change.timing_validated_at
                and change.plan_published_at is None and may_send):
            out.append({"kind": "inform_mother_plant",
                        "label": (f"Inform {cfg.plant_name(change)} of the "
                                  "validated timing"),
                        "target_tab": "timing"})
        return out

    @staticmethod
    async def open_receipts_for(session: AsyncSession, change_ids: list[int],
                                dept_ids: set) -> dict[int, list[ChangeInfoReceipt]]:
        """my-tasks batch: open receipts of the caller's departments."""
        if not change_ids or not dept_ids:
            return {}
        out: dict[int, list] = {}
        for r in (await session.execute(
                select(ChangeInfoReceipt).where(
                    ChangeInfoReceipt.change_id.in_(change_ids),
                    ChangeInfoReceipt.department_id.in_(dept_ids),
                    ChangeInfoReceipt.acknowledged_at.is_(None))
                .order_by(ChangeInfoReceipt.id))).scalars().all():
            out.setdefault(r.change_id, []).append(r)
        return out

    @staticmethod
    async def informed_department_ids(session: AsyncSession,
                                      change: ChangeRequest) -> list[int]:
        return sorted({r.department_id for r in
                       await MotherPlantService.receipts(session, change)})


def check_timing_file(content: bytes) -> None:
    """A mother-plant timing upload must be MS Project XML we can read."""
    from app.services import plan_engine as eng
    try:
        parsed = eng.parse_mspdi(content)
    except eng.MspdiError as e:
        raise ChangeError(f"The timing file is not usable MS Project XML: {e}")
    except (ValueError, OverflowError, RecursionError) as e:
        raise ChangeError(f"The timing file could not be read as MS Project XML ({e})")
    if not parsed.get("tasks"):
        raise ChangeError("The timing file has no tasks")

