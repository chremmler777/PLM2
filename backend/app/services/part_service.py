"""Service for managing parts and revisions (customer data index E<n> / <n>)."""
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List
from sqlalchemy import select, cast, text
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import joinedload
from app.models import (
    Part, PartRevision, RevisionFile, RevisionChangelog,
    RevisionPhase, RevisionStatus, TestDataStatus, User
)
from app.models.supplier import Supplier
from app.models.part import CUSTOMER_STATEMENTS
from app.services.revision_naming import next_major_name, next_minor_name

logger = logging.getLogger(__name__)

# Controlled item categories (automotive PLM)
VALID_ITEM_CATEGORIES = {"article", "tool", "assembly_equipment", "eoat", "gauge"}

TOOL_FIELDS = ("tool_cavities", "toolmaker_id", "tool_tonnage_class", "tool_cycle_time_s")
TOOL_FIELDS_ONLY_ON_TOOLS = "Tool fields (cavities, toolmaker, tonnage class, cycle time) only apply to tools"
ARTICLE_FIELDS_ONLY_ON_ARTICLES = "Colour code and grain only apply to articles"
ARTICLE_TEXT_FIELDS = ("colour_code", "grain")


def clean_text(value: Optional[str]) -> Optional[str]:
    """Trimmed; empty means none."""
    value = (value or "").strip()
    return value or None


def compute_next_calibration(
    last_calibrated_at: Optional[datetime],
    interval_months: Optional[int],
) -> Optional[datetime]:
    """Next calibration due date from the last calibration and interval."""
    if last_calibrated_at and interval_months:
        return last_calibrated_at + timedelta(days=round(interval_months * 30.44))
    return None


class PartService:
    """Service for part management and revision lifecycle."""

    @staticmethod
    async def _check_toolmaker(session: AsyncSession, toolmaker_id: Optional[int]) -> None:
        if toolmaker_id is not None and await session.get(Supplier, toolmaker_id) is None:
            raise ValueError("Toolmaker not found: no supplier with that id")

    @staticmethod
    async def _supplier_name(session: AsyncSession, supplier_id: Optional[int]) -> Optional[str]:
        """The supplier's name for a changelog entry, falling back to the id when unresolvable."""
        if supplier_id is None:
            return None
        supplier = await session.get(Supplier, supplier_id)
        return supplier.name if supplier else str(supplier_id)

    @staticmethod
    async def create_part(
        session: AsyncSession,
        project_id: int,
        part_number: str,
        name: str,
        part_type: str,
        description: Optional[str] = None,
        supplier: Optional[str] = None,
        created_by: int = None,
        data_classification: str = "confidential",
        parent_part_id: Optional[int] = None,
        item_category: str = "article",
        calibration_interval_months: Optional[int] = None,
        last_calibrated_at: Optional[datetime] = None,
        supplier_id: Optional[int] = None,
        customer_part_number: Optional[str] = None,
        tier1_part_number: Optional[str] = None,
        tool_cavities: Optional[int] = None,
        toolmaker_id: Optional[int] = None,
        tool_tonnage_class: Optional[int] = None,
        tool_cycle_time_s: Optional[float] = None,
        colour_code: Optional[str] = None,
        grain: Optional[str] = None,
    ) -> Part:
        """Create a new controlled item (article, tool, assembly equipment, gauge)."""
        if item_category not in VALID_ITEM_CATEGORIES:
            raise ValueError(
                f"Invalid item_category '{item_category}'. Valid: {', '.join(sorted(VALID_ITEM_CATEGORIES))}"
            )

        tool_values = {"tool_cavities": tool_cavities, "toolmaker_id": toolmaker_id,
                       "tool_tonnage_class": tool_tonnage_class, "tool_cycle_time_s": tool_cycle_time_s}
        if item_category != "tool" and any(v is not None for v in tool_values.values()):
            raise ValueError(TOOL_FIELDS_ONLY_ON_TOOLS)
        await PartService._check_toolmaker(session, toolmaker_id)
        article_values = {"colour_code": clean_text(colour_code), "grain": clean_text(grain)}
        if item_category != "article" and any(article_values.values()):
            raise ValueError(ARTICLE_FIELDS_ONLY_ON_ARTICLES)

        part = Part(
            project_id=project_id,
            part_number=part_number,
            name=name,
            description=description,
            part_type=part_type,
            supplier=supplier,
            created_by=created_by,
            data_classification=data_classification,
            parent_part_id=parent_part_id,
            supplier_id=supplier_id,
            customer_part_number=customer_part_number,
            tier1_part_number=tier1_part_number,
            item_category=item_category,
            calibration_interval_months=calibration_interval_months,
            last_calibrated_at=last_calibrated_at,
            next_calibration_due=compute_next_calibration(last_calibrated_at, calibration_interval_months),
            **tool_values,
            **article_values,
        )
        session.add(part)
        await session.flush()
        logger.info(f"Created {item_category} {part_number} in project {project_id}")
        return part

    @staticmethod
    async def get_part(session: AsyncSession, part_id: int) -> Optional[Part]:
        """Get a part by ID."""
        result = await session.execute(select(Part).where(Part.id == part_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_parts_by_project(
        session: AsyncSession,
        project_id: int,
    ) -> List[Part]:
        """Get all parts in a project."""
        result = await session.execute(
            select(Part).where(Part.project_id == project_id).order_by(Part.part_number)
        )
        return result.scalars().all()

    @staticmethod
    async def update_part(
        session: AsyncSession,
        part_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        part_type: Optional[str] = None,
        supplier: Optional[str] = None,
        updated_by: Optional[int] = None,
        parent_part_id: Optional[int] = None,
        update_parent: bool = False,
        item_category: Optional[str] = None,
        calibration_interval_months: Optional[int] = None,
        last_calibrated_at: Optional[datetime] = None,
        supplier_id: Optional[int] = None,
        update_supplier: bool = False,
        customer_part_number: Optional[str] = None,
        update_customer_part_number: bool = False,
        tier1_part_number: Optional[str] = None,
        update_tier1_part_number: bool = False,
        tool_cavities: Optional[int] = None,
        update_tool_cavities: bool = False,
        toolmaker_id: Optional[int] = None,
        update_toolmaker_id: bool = False,
        tool_tonnage_class: Optional[int] = None,
        update_tool_tonnage_class: bool = False,
        tool_cycle_time_s: Optional[float] = None,
        update_tool_cycle_time_s: bool = False,
        colour_code: Optional[str] = None,
        update_colour_code: bool = False,
        grain: Optional[str] = None,
        update_grain: bool = False,
    ) -> Optional[Part]:
        """Update a part. parent_part_id is only applied when update_parent is True
        (None then means: move to top level)."""
        part = await PartService.get_part(session, part_id)
        if not part:
            return None

        if update_parent:
            if parent_part_id == part_id:
                raise ValueError("A part cannot be its own parent")
            if parent_part_id is not None:
                new_parent = await PartService.get_part(session, parent_part_id)
                if not new_parent:
                    raise ValueError("Parent part not found")
                if new_parent.project_id != part.project_id:
                    raise ValueError("Parent part must be in the same project")
                # Walk up from the new parent to ensure part is not an ancestor (cycle)
                cursor = new_parent
                while cursor.parent_part_id is not None:
                    if cursor.parent_part_id == part_id:
                        raise ValueError("Cannot move a part under its own descendant")
                    cursor = await PartService.get_part(session, cursor.parent_part_id)
                    if cursor is None:
                        break
            part.parent_part_id = parent_part_id

        async def _log_field_change(attr: str, old, new, old_text=None, new_text=None) -> None:
            """One changelog entry for attr, only when the value actually changed."""
            if old == new:
                return
            old_text = old if old_text is None else old_text
            new_text = new if new_text is None else new_text
            label = attr.replace("_", " ")
            await ChangelogService.log_action(
                session, part_id=part.id, action="field_updated",
                action_description=f"{label.capitalize()}: {old_text or 'none'} -> {new_text or 'none'}",
                performed_by=updated_by, field_name=attr,
                old_value=None if old_text is None else str(old_text),
                new_value=None if new_text is None else str(new_text))

        if name is not None:
            old_name = part.name
            part.name = name
            await _log_field_change("name", old_name, name)
        if description is not None:
            part.description = description
        if part_type is not None:
            old_part_type = part.part_type
            part.part_type = part_type
            await _log_field_change("part_type", old_part_type, part_type)
        if supplier is not None:
            part.supplier = supplier
        if update_supplier:
            part.supplier_id = supplier_id
        if update_customer_part_number:
            old_customer_part_number = part.customer_part_number
            new_customer_part_number = clean_text(customer_part_number)
            part.customer_part_number = new_customer_part_number
            await _log_field_change("customer_part_number", old_customer_part_number, new_customer_part_number)
        if update_tier1_part_number:
            old_tier1_part_number = part.tier1_part_number
            new_tier1_part_number = clean_text(tier1_part_number)
            part.tier1_part_number = new_tier1_part_number
            await _log_field_change("tier1_part_number", old_tier1_part_number, new_tier1_part_number)

        tool_updates = {
            "tool_cavities": (update_tool_cavities, tool_cavities),
            "toolmaker_id": (update_toolmaker_id, toolmaker_id),
            "tool_tonnage_class": (update_tool_tonnage_class, tool_tonnage_class),
            "tool_cycle_time_s": (update_tool_cycle_time_s, tool_cycle_time_s),
        }
        if any(flag for flag, _ in tool_updates.values()):
            if (item_category or part.item_category) != "tool":
                raise ValueError(TOOL_FIELDS_ONLY_ON_TOOLS)
            if update_toolmaker_id:
                await PartService._check_toolmaker(session, toolmaker_id)
            for attr, (flag, value) in tool_updates.items():
                if flag:
                    old = getattr(part, attr)
                    if attr == "toolmaker_id":
                        old_text = await PartService._supplier_name(session, old)
                        new_text = await PartService._supplier_name(session, value)
                        setattr(part, attr, value)
                        await _log_field_change(attr, old, value, old_text, new_text)
                    elif attr == "tool_cycle_time_s":
                        # stored as Numeric(6,1): round before comparing/logging so re-saving the same
                        # unrounded value (12.34 after a 12.3 save) is not logged as a change.
                        new_cycle_time = None if value is None else round(value, 1)
                        setattr(part, attr, new_cycle_time)
                        await _log_field_change(attr, old, new_cycle_time)
                    else:
                        setattr(part, attr, value)
                        await _log_field_change(attr, old, value)

        article_updates = {name: clean_text(value) for name, flag, value in (
            ("colour_code", update_colour_code, colour_code), ("grain", update_grain, grain)) if flag}
        if any(article_updates.values()) and (item_category or part.item_category) != "article":
            raise ValueError(ARTICLE_FIELDS_ONLY_ON_ARTICLES)
        for attr, value in article_updates.items():
            old = getattr(part, attr)
            if old == value:
                continue
            setattr(part, attr, value)
            await _log_field_change(attr, old, value)

        if item_category is not None:
            if item_category not in VALID_ITEM_CATEGORIES:
                raise ValueError(
                    f"Invalid item_category '{item_category}'. Valid: {', '.join(sorted(VALID_ITEM_CATEGORIES))}"
                )
            part.item_category = item_category
        if calibration_interval_months is not None:
            part.calibration_interval_months = calibration_interval_months
        if last_calibrated_at is not None:
            part.last_calibrated_at = last_calibrated_at
        if calibration_interval_months is not None or last_calibrated_at is not None:
            part.next_calibration_due = compute_next_calibration(
                part.last_calibrated_at, part.calibration_interval_months
            )
        if updated_by is not None:
            part.updated_by = updated_by

        part.updated_at = datetime.utcnow()
        await session.flush()
        logger.info(f"Updated part {part_id}")
        return part

    @staticmethod
    async def delete_part(session: AsyncSession, part_id: int) -> bool:
        """Delete a part (soft or hard)."""
        part = await PartService.get_part(session, part_id)
        if not part:
            return False

        # For now, hard delete. In Phase 6, implement soft delete with archival
        await session.delete(part)
        logger.info(f"Deleted part {part_id}")
        return True


class RevisionService:
    """Service for managing part revisions.

    A major (E1, E2, 1, 2) exists only because the customer sent data and
    said whether it is review or official. A minor (E1.1, 1.1) is our own
    iteration on top of it. Counters never reset.
    """

    @staticmethod
    async def _majors(session: AsyncSession, part_id: int) -> list[PartRevision]:
        result = await session.execute(
            select(PartRevision)
            .where((PartRevision.part_id == part_id) & (PartRevision.parent_revision_id.is_(None)))
            .order_by(PartRevision.created_at))
        return list(result.scalars().all())

    @staticmethod
    async def receive_customer_data(
        session: AsyncSession,
        part_id: int,
        statement: str,
        received_at: date,
        customer_index: Optional[str] = None,
        summary: Optional[str] = None,
        created_by: int = None,
        copy_bom_from: Optional[int] = None,
        major: Optional[int] = None,
    ) -> PartRevision:
        """Create the next major from a customer statement. This — and
        promote_revision, which delegates here — is the only way a major
        revision comes into existence. The BOM is copied forward from
        ``copy_bom_from`` (a revision id) or, by default, the previous major.
        ``major`` lets the caller choose the major number (see
        ``next_major_name``)."""
        if statement not in CUSTOMER_STATEMENTS:
            raise ValueError(f"statement must be one of {CUSTOMER_STATEMENTS}")
        part = await session.get(Part, part_id)
        if part is None:
            raise ValueError("Part not found")
        majors = await RevisionService._majors(session, part_id)
        name = next_major_name([m.revision_name for m in majors], statement, requested=major)
        revision = PartRevision(
            part_id=part_id,
            revision_name=name,
            phase=statement,
            status=RevisionStatus.APPROVED.value,
            source="customer",
            customer_statement=statement,
            customer_index=customer_index,
            customer_received_at=received_at,
            part_phase_at_receipt=part.lifecycle_phase,
            summary=summary,
            created_by=created_by,
        )
        session.add(revision)
        await session.flush()
        part.active_revision_id = revision.id
        from app.services.bom_tree_service import BomTreeService
        source_rev_id = copy_bom_from if copy_bom_from is not None else (majors[-1].id if majors else None)
        if source_rev_id is not None:
            await BomTreeService.copy_lines(session, source_rev_id, revision.id, created_by)
        await ChangelogService.log_action(
            session=session, part_id=part_id, revision_id=revision.id, action="created",
            action_description=(f"Customer {statement} data received as {name}"
                                + (f" (customer index {customer_index})" if customer_index else "")),
            performed_by=created_by,
        )
        logger.info(f"Customer {statement} data {name} on part {part_id}")
        return revision

    @staticmethod
    async def create_proposal(
        session: AsyncSession,
        part_id: int,
        parent_revision_id: int,
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Our internal iteration on a customer major: E1 → E1.1, 1 → 1.1."""
        parent = await session.get(PartRevision, parent_revision_id)
        if parent is None or parent.part_id != part_id:
            raise ValueError("Parent revision not found on this part")
        if parent.parent_revision_id is not None:
            raise ValueError(f"{parent.revision_name} is a proposal; proposals hang off majors only")
        siblings = (await session.execute(
            select(PartRevision.revision_name).where(PartRevision.parent_revision_id == parent.id))).scalars().all()
        name = next_minor_name(parent.revision_name, list(siblings))
        proposal = PartRevision(
            part_id=part_id, revision_name=name, phase=parent.phase,
            status=RevisionStatus.DRAFT.value, parent_revision_id=parent.id,
            source="internal", part_phase_at_receipt=parent.part_phase_at_receipt,
            summary=summary, created_by=created_by,
        )
        session.add(proposal)
        await session.flush()
        from app.services.bom_tree_service import BomTreeService
        await BomTreeService.copy_lines(session, parent.id, proposal.id, created_by)
        await ChangelogService.log_action(
            session=session, part_id=part_id, revision_id=proposal.id, action="created",
            action_description=f"Created {name} as proposal to {parent.revision_name}",
            performed_by=created_by,
        )
        return proposal

    @staticmethod
    async def promote_revision(
        session: AsyncSession,
        revision_id: int,
        statement: str,
        received_at: date,
        customer_index: Optional[str] = None,
        created_by: int = None,
        major: Optional[int] = None,
    ) -> PartRevision:
        """The customer adopted one of our proposals as their next data state.
        Creates the next major (per statement), marks the proposal approved
        and its siblings rejected."""
        revision = await session.get(PartRevision, revision_id)
        if revision is None:
            raise ValueError("Revision not found")
        summary = f"Promoted from {revision.revision_name}"
        if revision.summary:
            summary = f"{revision.summary} (promoted from {revision.revision_name})"
        new_revision = await RevisionService.receive_customer_data(
            session, revision.part_id, statement, received_at,
            customer_index=customer_index, summary=summary, created_by=created_by,
            copy_bom_from=revision.id, major=major)
        revision.status = RevisionStatus.APPROVED.value
        await ChangelogService.log_action(
            session=session, part_id=revision.part_id, revision_id=revision.id, action="promoted",
            action_description=f"Promoted to {new_revision.revision_name}", performed_by=created_by)
        if revision.parent_revision_id:
            siblings = (await session.execute(
                select(PartRevision).where(
                    (PartRevision.parent_revision_id == revision.parent_revision_id)
                    & (PartRevision.id != revision.id)))).scalars().all()
            for sibling in siblings:
                sibling.status = RevisionStatus.REJECTED.value
                await ChangelogService.log_action(
                    session=session, part_id=revision.part_id, revision_id=sibling.id, action="rejected",
                    action_description=f"Rejected due to promotion of {revision.revision_name}",
                    performed_by=created_by)
        return new_revision

    @staticmethod
    async def set_lifecycle_phase(
        session: AsyncSession, part_id: int, phase: str, effective: date, created_by: int = None,
    ) -> Part:
        """rfq → nominated (sets nominated_at) → series (sets sop_at)."""
        part = await session.get(Part, part_id)
        if part is None:
            raise ValueError("Part not found")
        allowed = {"rfq": "nominated", "nominated": "series"}
        if allowed.get(part.lifecycle_phase) != phase:
            raise ValueError(f"Cannot move part from {part.lifecycle_phase} to {phase}")
        old = part.lifecycle_phase
        part.lifecycle_phase = phase
        if phase == "nominated":
            part.nominated_at = effective
        else:
            part.sop_at = effective
        await ChangelogService.log_action(
            session=session, part_id=part_id, revision_id=None, action="lifecycle_phase",
            action_description=f"Part moved from {old} to {phase} effective {effective.isoformat()}",
            field_name="lifecycle_phase", old_value=old, new_value=phase, performed_by=created_by,
        )
        await session.flush()
        return part

    @staticmethod
    async def reject_revision(
        session: AsyncSession,
        revision_id: int,
        created_by: int = None,
    ) -> PartRevision:
        """Reject a revision (major or proposal) - mark as rejected."""
        revision = await session.get(PartRevision, revision_id)
        if not revision:
            raise ValueError("Revision not found")

        # Mark as rejected
        revision.status = RevisionStatus.REJECTED.value

        # Log the rejection
        await ChangelogService.log_action(
            session=session,
            part_id=revision.part_id,
            revision_id=revision.id,
            action="rejected",
            action_description=f"Rejected {revision.revision_name}",
            performed_by=created_by,
        )

        logger.info(f"Rejected revision {revision.revision_name}")
        return revision

    @staticmethod
    async def unreject_revision(
        session: AsyncSession,
        revision_id: int,
        created_by: int = None,
    ) -> PartRevision:
        """Restore a rejected/archived revision back to draft (for proposals)."""
        revision = await session.get(PartRevision, revision_id)
        if not revision:
            raise ValueError("Revision not found")

        old_status = revision.status

        # Restore to DRAFT for proposals, or IN_PROGRESS for majors
        if revision.parent_revision_id:
            revision.status = RevisionStatus.DRAFT.value
        else:
            revision.status = RevisionStatus.IN_PROGRESS.value

        # Log the restoration
        await ChangelogService.log_action(
            session=session,
            part_id=revision.part_id,
            revision_id=revision.id,
            action="status_changed",
            action_description=f"Restored {revision.revision_name} from {old_status} to {revision.status}",
            field_name="status",
            old_value=old_status,
            new_value=revision.status,
            performed_by=created_by,
        )

        logger.info(f"Restored revision {revision.revision_name} from {old_status} to {revision.status}")
        return revision


    @staticmethod
    async def get_revision(
        session: AsyncSession,
        revision_id: int,
    ) -> Optional[PartRevision]:
        """Get a revision by ID."""
        result = await session.execute(select(PartRevision).where(PartRevision.id == revision_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_part_revisions(
        session: AsyncSession,
        part_id: int,
    ) -> List[PartRevision]:
        """Get all revisions for a part, ordered by creation time."""
        result = await session.execute(
            select(PartRevision)
            .where(PartRevision.part_id == part_id)
            .order_by(PartRevision.created_at)
        )
        return result.scalars().all()


class ChangelogService:
    """Service for managing revision changelog (audit trail)."""

    @staticmethod
    async def log_action(
        session: AsyncSession,
        part_id: int,
        action: str,
        action_description: str,
        performed_by: int,
        revision_id: Optional[int] = None,
        field_name: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        file_id: Optional[int] = None,
        notes: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> RevisionChangelog:
        """Log an action to the changelog."""
        entry = RevisionChangelog(
            part_id=part_id,
            revision_id=revision_id,
            action=action,
            action_description=action_description,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            file_id=file_id,
            performed_by=performed_by,
            notes=notes,
            ip_address=ip_address,
        )

        # TODO: Implement hash chaining in Phase 6
        # Get previous entry's hash
        # entry.previous_hash = await ChangelogService.get_last_entry_hash(session, part_id)
        # Calculate this entry's hash
        # entry.entry_hash = ChangelogService.calculate_entry_hash(entry)

        session.add(entry)
        await session.flush()
        logger.debug(f"Logged action '{action}' for part {part_id}")
        return entry

    @staticmethod
    async def get_part_changelog(
        session: AsyncSession,
        part_id: int,
    ) -> List[RevisionChangelog]:
        """Get full changelog for a part."""
        result = await session.execute(
            select(RevisionChangelog)
            .where(RevisionChangelog.part_id == part_id)
            .options(joinedload(RevisionChangelog.performed_by_user))  # Eager load the user
            .order_by(RevisionChangelog.performed_at)
        )
        return result.unique().scalars().all()

    @staticmethod
    async def get_revision_changelog(
        session: AsyncSession,
        revision_id: int,
    ) -> List[RevisionChangelog]:
        """Get changelog for a specific revision."""
        result = await session.execute(
            select(RevisionChangelog)
            .where(RevisionChangelog.revision_id == revision_id)
            .options(joinedload(RevisionChangelog.performed_by_user))  # Eager load the user
            .order_by(RevisionChangelog.performed_at)
        )
        return result.unique().scalars().all()
