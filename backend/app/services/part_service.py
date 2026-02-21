"""Service for managing parts and revisions with RFQ/ENG/FREEZE/ECR workflow."""
import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, cast, text
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import joinedload
from app.models import (
    Part, PartRevision, RevisionFile, RevisionChangelog,
    RevisionPhase, RevisionStatus, TestDataStatus, User
)

logger = logging.getLogger(__name__)


class PartService:
    """Service for part management and revision lifecycle."""

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
    ) -> Part:
        """Create a new part."""
        part = Part(
            project_id=project_id,
            part_number=part_number,
            name=name,
            description=description,
            part_type=part_type,
            supplier=supplier,
            created_by=created_by,
            data_classification=data_classification,
        )
        session.add(part)
        await session.flush()
        logger.info(f"Created part {part_number} in project {project_id}")
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
    ) -> Optional[Part]:
        """Update a part."""
        part = await PartService.get_part(session, part_id)
        if not part:
            return None

        if name is not None:
            part.name = name
        if description is not None:
            part.description = description
        if part_type is not None:
            part.part_type = part_type
        if supplier is not None:
            part.supplier = supplier
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
    """Service for managing part revisions and their lifecycle."""

    @staticmethod
    async def get_latest_revision_in_phase(
        session: AsyncSession,
        part_id: int,
        phase: str,
    ) -> Optional[PartRevision]:
        """Get the latest major version in a phase (e.g., RFQ1, ENG1, IND1)."""
        result = await session.execute(
            select(PartRevision)
            .where(
                (PartRevision.part_id == part_id)
                & (PartRevision.phase == phase)
                & (PartRevision.parent_revision_id.is_(None))  # Major versions have no parent
            )
            .order_by(PartRevision.revision_name.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_next_major_version_name(
        session: AsyncSession,
        part_id: int,
        phase: str,
        phase_prefix: str,  # "RFQ", "ENG", "IND", "ECR"
    ) -> str:
        """Calculate the next major version name (RFQ1 → RFQ2, ENG1 → ENG2, etc)."""
        latest = await RevisionService.get_latest_revision_in_phase(session, part_id, phase)
        if not latest:
            return f"{phase_prefix}1"

        # Extract number from revision_name (e.g., "RFQ1" → 1)
        current_num = int(latest.revision_name[len(phase_prefix):].split('.')[0])
        return f"{phase_prefix}{current_num + 1}"

    @staticmethod
    async def has_draft_proposals(
        session: AsyncSession,
        part_id: int,
    ) -> tuple[bool, Optional[PartRevision]]:
        """Check if there are draft proposals under the latest major RFQ. Returns (has_drafts, latest_major_rfq)."""
        latest = await RevisionService.get_latest_revision_in_phase(
            session, part_id, RevisionPhase.RFQ_PHASE.value
        )
        if not latest:
            return False, None

        # Check if there are any draft proposals under this major version
        result = await session.execute(
            select(PartRevision)
            .where(
                (PartRevision.parent_revision_id == latest.id)
                & (PartRevision.status == RevisionStatus.DRAFT.value)
            )
            .limit(1)
        )
        has_drafts = result.scalar_one_or_none() is not None
        return has_drafts, latest

    @staticmethod
    async def create_rfq_revision(
        session: AsyncSession,
        part_id: int,
        summary: Optional[str] = None,
        created_by: int = None,
        reject_drafts: bool = False,
    ) -> PartRevision:
        """Create a new major RFQ revision (RFQ1, RFQ2, etc) - auto-increments."""
        # Check if there are draft proposals that should be promoted first
        has_drafts, latest = await RevisionService.has_draft_proposals(session, part_id)
        if has_drafts:
            if reject_drafts:
                # Reject all draft proposals under the latest major version
                result = await session.execute(
                    select(PartRevision).where(
                        (PartRevision.part_id == part_id)
                        & (PartRevision.parent_revision_id == latest.id)
                        & (PartRevision.status == RevisionStatus.DRAFT.value)
                    )
                )
                drafts = result.scalars().all()

                for draft in drafts:
                    draft.status = RevisionStatus.ARCHIVED.value
                    await ChangelogService.log_action(
                        session=session,
                        part_id=part_id,
                        revision_id=draft.id,
                        action="status_changed",
                        action_description=f"Automatically archived {draft.revision_name} when creating new major version",
                        field_name="status",
                        old_value=RevisionStatus.DRAFT.value,
                        new_value=RevisionStatus.ARCHIVED.value,
                        performed_by=created_by,
                    )
            else:
                raise ValueError(
                    f"Cannot create new RFQ while {latest.revision_name} has draft proposals. "
                    f"Promote one of them first or reject {latest.revision_name}."
                )

        # Calculate next major RFQ version
        revision_name = await RevisionService.get_next_major_version_name(
            session, part_id, RevisionPhase.RFQ_PHASE.value, "RFQ"
        )

        revision = PartRevision(
            part_id=part_id,
            revision_name=revision_name,
            phase=RevisionPhase.RFQ_PHASE.value,
            status=RevisionStatus.IN_PROGRESS.value,  # Use IN_PROGRESS instead of DRAFT for major versions
            summary=summary,
            created_by=created_by,
        )
        session.add(revision)
        await session.flush()

        # Log the creation
        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=revision.id,
            action="created",
            action_description=f"Created {revision_name}",
            performed_by=created_by,
        )

        logger.info(f"Created RFQ revision {revision_name} for part {part_id}")
        return revision

    @staticmethod
    async def create_rfq_proposal(
        session: AsyncSession,
        part_id: int,
        parent_revision_id: int,  # Parent RFQ1, RFQ2, etc
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Create a minor RFQ proposal (RFQ1.1, RFQ1.2, etc)."""
        parent = await session.get(PartRevision, parent_revision_id)
        if not parent or parent.phase != RevisionPhase.RFQ_PHASE.value:
            raise ValueError("Parent must be an RFQ revision")

        # Find next minor version under this parent
        result = await session.execute(
            select(PartRevision)
            .where(PartRevision.parent_revision_id == parent_revision_id)
            .order_by(PartRevision.revision_name.desc())
            .limit(1)
        )
        last_proposal = result.scalar_one_or_none()

        if last_proposal:
            # Extract minor version (e.g., "RFQ1.2" → 2)
            minor_num = int(last_proposal.revision_name.split('.')[-1])
            new_minor = minor_num + 1
        else:
            new_minor = 1

        revision_name = f"{parent.revision_name}.{new_minor}"

        proposal = PartRevision(
            part_id=part_id,
            revision_name=revision_name,
            phase=RevisionPhase.RFQ_PHASE.value,
            status=RevisionStatus.DRAFT.value,
            parent_revision_id=parent_revision_id,
            summary=summary,
            created_by=created_by,
        )
        session.add(proposal)
        await session.flush()

        # Log the creation
        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=proposal.id,
            action="created",
            action_description=f"Created {revision_name} as proposal to {parent.revision_name}",
            performed_by=created_by,
        )

        logger.info(f"Created RFQ proposal {revision_name} for part {part_id}")
        return proposal

    @staticmethod
    async def promote_revision(
        session: AsyncSession,
        revision_id: int,
        created_by: int = None,
    ) -> PartRevision:
        """Promote a revision to the next major version (e.g., RFQ1.2 → RFQ2)."""
        revision = await session.get(PartRevision, revision_id)
        if not revision:
            raise ValueError("Revision not found")

        # Determine which major version to promote from
        if revision.parent_revision_id:
            # This is a proposal (RFQ1.1, RFQ1.2, etc) - promote from its parent's phase
            parent = await session.get(PartRevision, revision.parent_revision_id)
            if not parent:
                raise ValueError("Parent revision not found")
            phase = parent.phase
            # Extract prefix (RFQ, ENG, IND, ECR) from revision_name like "RFQ2"
            major_name = parent.revision_name.split('.')[0]  # "RFQ2"
            phase_prefix = ''.join([c for c in major_name if not c.isdigit()])  # "RFQ"
            parent_major = major_name
        else:
            # This is a major version - promote directly from it
            phase = revision.phase
            major_name = revision.revision_name.split('.')[0]  # "RFQ2"
            phase_prefix = ''.join([c for c in major_name if not c.isdigit()])  # "RFQ"
            parent_major = major_name

        # Calculate next major version
        next_major_name = await RevisionService.get_next_major_version_name(
            session, revision.part_id, phase, phase_prefix
        )

        # Create the new major version (copy of the promoted revision)
        summary = f"Promoted from {revision.revision_name}"
        if revision.summary:
            summary = f"{revision.summary} (promoted from {revision.revision_name})"

        new_revision = PartRevision(
            part_id=revision.part_id,
            revision_name=next_major_name,
            phase=phase,
            status=RevisionStatus.IN_PROGRESS.value,  # Active status for major versions
            parent_revision_id=None,  # New major version has no parent
            summary=summary,
            created_by=created_by,
        )
        session.add(new_revision)
        await session.flush()

        # Mark the promoted revision with status "promoted" for audit trail
        revision.status = RevisionStatus.APPROVED.value  # Use APPROVED to indicate it was chosen/promoted

        # Tag the promoted revision
        await ChangelogService.log_action(
            session=session,
            part_id=revision.part_id,
            revision_id=revision.id,
            action="promoted",
            action_description=f"Promoted to {next_major_name}",
            performed_by=created_by,
        )

        # Mark all sibling proposals as rejected (if promoting a proposal)
        if revision.parent_revision_id:
            siblings = (
                await session.execute(
                    select(PartRevision).where(
                        (PartRevision.parent_revision_id == revision.parent_revision_id)
                        & (PartRevision.id != revision.id)
                    )
                )
            ).scalars().all()

            for sibling in siblings:
                sibling.status = RevisionStatus.REJECTED.value
                await ChangelogService.log_action(
                    session=session,
                    part_id=revision.part_id,
                    revision_id=sibling.id,
                    action="rejected",
                    action_description=f"Rejected due to promotion of {revision.revision_name}",
                    performed_by=created_by,
                )

        logger.info(f"Promoted {revision.revision_name} to {next_major_name}")
        return new_revision

    @staticmethod
    async def reject_revision(
        session: AsyncSession,
        revision_id: int,
        created_by: int = None,
    ) -> PartRevision:
        """Reject a revision (mark as rejected so you can go back to previous)."""
        revision = await session.get(PartRevision, revision_id)
        if not revision:
            raise ValueError("Revision not found")

        if revision.parent_revision_id:
            raise ValueError("Cannot reject a proposal - only major versions can be rejected")

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
    async def transition_rfq_to_engineering(
        session: AsyncSession,
        rfq_revision_id: int,
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Transition from RFQ to Engineering phase (RFQ → ENG1)."""
        rfq_rev = await session.get(PartRevision, rfq_revision_id)
        if not rfq_rev or rfq_rev.phase != RevisionPhase.RFQ_PHASE.value:
            raise ValueError("Revision is not in RFQ phase")

        # Archive the RFQ major version (awarded, no longer active)
        rfq_rev.status = RevisionStatus.ARCHIVED.value
        await ChangelogService.log_action(
            session=session,
            part_id=rfq_rev.part_id,
            revision_id=rfq_rev.id,
            action="status_changed",
            action_description=f"Archived {rfq_rev.revision_name} (awarded to engineering)",
            field_name="status",
            old_value=RevisionStatus.IN_PROGRESS.value,
            new_value=RevisionStatus.ARCHIVED.value,
            performed_by=created_by,
        )

        # Create ENG1 revision with IN_PROGRESS status (major version, not draft)
        eng_revision = PartRevision(
            part_id=rfq_rev.part_id,
            revision_name="ENG1",
            phase=RevisionPhase.ENGINEERING_PHASE.value,
            status=RevisionStatus.IN_PROGRESS.value,
            parent_revision_id=rfq_rev.id,
            summary=summary or f"Engineering from {rfq_rev.revision_name}",
            created_by=created_by,
        )
        session.add(eng_revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=rfq_rev.part_id,
            revision_id=eng_revision.id,
            action="created",
            action_description=f"Transitioned from {rfq_rev.revision_name} to ENG1 (awarded)",
            performed_by=created_by,
        )

        logger.info(f"Created ENG1 from {rfq_rev.revision_name} for part {rfq_rev.part_id}")
        return eng_revision

    @staticmethod
    async def create_engineering_proposal_simple(
        session: AsyncSession,
        part_id: int,
        parent_revision_id: int,  # Parent ENG1, ENG2, etc
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Create a minor engineering proposal (ENG1.1, ENG1.2, etc) - auto-calculates minor version."""
        parent = await session.get(PartRevision, parent_revision_id)
        if not parent or parent.phase != RevisionPhase.ENGINEERING_PHASE.value:
            raise ValueError("Parent must be an ENG revision")

        # Find next minor version under this parent
        result = await session.execute(
            select(PartRevision)
            .where(PartRevision.parent_revision_id == parent_revision_id)
            .order_by(PartRevision.revision_name.desc())
            .limit(1)
        )
        last_proposal = result.scalar_one_or_none()

        if last_proposal:
            minor_num = int(last_proposal.revision_name.split('.')[-1])
            new_minor = minor_num + 1
        else:
            new_minor = 1

        revision_name = f"{parent.revision_name}.{new_minor}"

        proposal = PartRevision(
            part_id=part_id,
            revision_name=revision_name,
            phase=RevisionPhase.ENGINEERING_PHASE.value,
            status=RevisionStatus.DRAFT.value,
            parent_revision_id=parent_revision_id,
            summary=summary,
            created_by=created_by,
        )
        session.add(proposal)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=proposal.id,
            action="created",
            action_description=f"Created {revision_name} as proposal to {parent.revision_name}",
            performed_by=created_by,
        )

        logger.info(f"Created ENG proposal {revision_name} for part {part_id}")
        return proposal

    @staticmethod
    async def advance_engineering_proposal(
        session: AsyncSession,
        part_id: int,
        proposal_revision_id: int,
        created_by: int = None,
    ) -> PartRevision:
        """Advance (promote) an engineering proposal to next major version (ENG1.2 → ENG2)."""
        proposal = await session.get(PartRevision, proposal_revision_id)
        if not proposal or proposal.phase != RevisionPhase.ENGINEERING_PHASE.value:
            raise ValueError("Revision is not in engineering phase")
        if not proposal.parent_revision_id:
            raise ValueError("Cannot advance a major version - only proposals can be advanced")

        parent = await session.get(PartRevision, proposal.parent_revision_id)
        if not parent:
            raise ValueError("Parent revision not found")

        # Extract major version number (e.g., "ENG1" → 1)
        parent_major_num = int(parent.revision_name.replace("ENG", ""))
        next_major_num = parent_major_num + 1
        next_major_name = f"ENG{next_major_num}"

        # Create new major version
        summary = f"Promoted from {proposal.revision_name}"
        if proposal.summary:
            summary = f"{proposal.summary} (promoted from {proposal.revision_name})"

        new_revision = PartRevision(
            part_id=proposal.part_id,
            revision_name=next_major_name,
            phase=RevisionPhase.ENGINEERING_PHASE.value,
            status=RevisionStatus.IN_PROGRESS.value,
            parent_revision_id=None,
            summary=summary,
            created_by=created_by,
        )
        session.add(new_revision)
        await session.flush()

        # Mark promoted proposal as APPROVED
        proposal.status = RevisionStatus.APPROVED.value
        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=proposal.id,
            action="status_changed",
            action_description=f"Advanced {proposal.revision_name} to {next_major_name}",
            field_name="status",
            old_value=RevisionStatus.DRAFT.value,
            new_value=RevisionStatus.APPROVED.value,
            performed_by=created_by,
        )

        # Archive sibling proposals
        result = await session.execute(
            select(PartRevision).where(
                (PartRevision.parent_revision_id == proposal.parent_revision_id)
                & (PartRevision.id != proposal.id)
                & (PartRevision.status == RevisionStatus.DRAFT.value)
            )
        )
        siblings = result.scalars().all()

        for sibling in siblings:
            sibling.status = RevisionStatus.ARCHIVED.value
            await ChangelogService.log_action(
                session=session,
                part_id=part_id,
                revision_id=sibling.id,
                action="status_changed",
                action_description=f"Automatically archived {sibling.revision_name} when advancing {proposal.revision_name}",
                field_name="status",
                old_value=RevisionStatus.DRAFT.value,
                new_value=RevisionStatus.ARCHIVED.value,
                performed_by=created_by,
            )

        # Log the new major version creation
        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=new_revision.id,
            action="created",
            action_description=f"Created {next_major_name}",
            performed_by=created_by,
        )

        logger.info(f"Advanced ENG proposal {proposal.revision_name} to {next_major_name}")
        return new_revision

    @staticmethod
    async def transition_engineering_to_freeze(
        session: AsyncSession,
        eng_revision_id: int,
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Transition from Engineering to Design Freeze (IND) phase."""
        eng_rev = await session.get(PartRevision, eng_revision_id)
        if not eng_rev or eng_rev.phase != RevisionPhase.ENGINEERING_PHASE.value:
            raise ValueError("Revision is not in engineering phase")

        # Create IND1, IND2, etc based on existing freeze count
        result = await session.execute(
            select(PartRevision)
            .where(PartRevision.phase == RevisionPhase.DESIGN_FREEZE_PHASE.value)
            .order_by(PartRevision.revision_name.desc())
            .limit(1)
        )
        last_freeze = result.scalar_one_or_none()

        if last_freeze:
            freeze_num = int(last_freeze.revision_name.replace("IND", ""))
            next_freeze_num = freeze_num + 1
        else:
            next_freeze_num = 1

        freeze_name = f"IND{next_freeze_num}"

        # Archive the ENG major version (frozen, no longer active in engineering)
        eng_rev.status = RevisionStatus.ARCHIVED.value
        await ChangelogService.log_action(
            session=session,
            part_id=eng_rev.part_id,
            revision_id=eng_rev.id,
            action="status_changed",
            action_description=f"Archived {eng_rev.revision_name} (frozen in design freeze)",
            field_name="status",
            old_value=RevisionStatus.IN_PROGRESS.value,
            new_value=RevisionStatus.ARCHIVED.value,
            performed_by=created_by,
        )

        freeze_revision = PartRevision(
            part_id=eng_rev.part_id,
            revision_name=freeze_name,
            phase=RevisionPhase.DESIGN_FREEZE_PHASE.value,
            status=RevisionStatus.IN_PROGRESS.value,
            parent_revision_id=eng_rev.id,
            summary=summary or f"Design freeze from {eng_rev.revision_name}",
            created_by=created_by,
        )
        session.add(freeze_revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=eng_rev.part_id,
            revision_id=freeze_revision.id,
            action="created",
            action_description=f"Transitioned from {eng_rev.revision_name} to {freeze_name} (design freeze)",
            performed_by=created_by,
        )

        logger.info(f"Created {freeze_name} from {eng_rev.revision_name} for part {eng_rev.part_id}")
        return freeze_revision

    @staticmethod
    async def create_engineering_proposal(
        session: AsyncSession,
        part_id: int,
        parent_revision_id: int,  # Link to official version (ENG1, ENG2, etc)
        major_version: int,  # Major version (1 for ENG1.x, 2 for ENG2.x)
        proposal_number: int,  # 1 for first proposal, 2 for second, etc (ENG1.1, ENG1.2)
        summary: Optional[str] = None,
        change_reason: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Create a proposal for engineering revision (ENG1.1, ENG1.2, ENG2.1, etc)."""
        revision_name = f"ENG{major_version}.{proposal_number}"

        revision = PartRevision(
            part_id=part_id,
            revision_name=revision_name,
            phase=RevisionPhase.ENGINEERING_PHASE.value,
            status=RevisionStatus.DRAFT.value,
            test_data_status=TestDataStatus.UNCONFIRMED,
            parent_revision_id=parent_revision_id,
            summary=summary,
            change_reason=change_reason,
            created_by=created_by,
        )
        session.add(revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=revision.id,
            action="created",
            action_description=f"Created proposal {revision_name}",
            performed_by=created_by,
        )

        logger.info(f"Created engineering proposal {revision_name} for part {part_id}")
        return revision

    @staticmethod
    async def approve_engineering_proposal(
        session: AsyncSession,
        proposal_revision_id: int,
        next_major_version: int,  # 2 for ENG1.1→ENG2, 3 for ENG2.1→ENG3, etc
        approved_by: int = None,
        approval_notes: Optional[str] = None,
    ) -> PartRevision:
        """Approve an engineering proposal, creating the next major version."""
        proposal = await session.get(PartRevision, proposal_revision_id)
        if not proposal or proposal.phase != RevisionPhase.ENGINEERING_PHASE.value:
            raise ValueError("Revision is not in Engineering phase")
        if proposal.test_data_status == TestDataStatus.APPROVED:
            raise ValueError("Revision is already approved")

        # Mark proposal as approved
        proposal.status = RevisionStatus.APPROVED.value
        proposal.test_data_status = TestDataStatus.APPROVED
        proposal.approved_at = datetime.utcnow()
        proposal.approved_by = approved_by
        proposal.approval_notes = approval_notes
        await session.flush()

        # Create next major version (ENG1.1 → ENG2, ENG2.1 → ENG3, etc)
        new_revision_name = f"ENG{next_major_version}"
        new_revision = PartRevision(
            part_id=proposal.part_id,
            revision_name=new_revision_name,
            phase=RevisionPhase.ENGINEERING_PHASE.value,
            status=RevisionStatus.DRAFT.value,
            parent_revision_id=proposal_revision_id,
            supersedes_revision_id=proposal_revision_id,
            summary=f"Official release from {proposal.revision_name}",
            created_by=approved_by,
        )
        session.add(new_revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=proposal.part_id,
            revision_id=proposal_revision_id,
            action="approved",
            action_description=f"Approved {proposal.revision_name}, created {new_revision_name}",
            performed_by=approved_by,
        )

        logger.info(f"Approved {proposal.revision_name}, created {new_revision_name}")
        return new_revision

    @staticmethod
    async def reject_engineering_proposal(
        session: AsyncSession,
        proposal_revision_id: int,
        rejected_by: int = None,
    ) -> PartRevision:
        """Reject an engineering proposal (remains visible as rejected)."""
        proposal = await session.get(PartRevision, proposal_revision_id)
        if not proposal:
            raise ValueError("Revision not found")

        proposal.status = RevisionStatus.REJECTED.value
        proposal.test_data_status = TestDataStatus.REJECTED
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=proposal.part_id,
            revision_id=proposal_revision_id,
            action="rejected",
            action_description=f"Rejected proposal {proposal.revision_name}",
            performed_by=rejected_by,
        )

        logger.info(f"Rejected {proposal.revision_name} for part {proposal.part_id}")
        return proposal

    @staticmethod
    async def create_design_freeze(
        session: AsyncSession,
        part_id: int,
        parent_revision_id: int,  # Link to official ENG version
        created_by: int = None,
    ) -> PartRevision:
        """Create a design freeze revision (IND1, IND2, IND3, etc)."""
        # Determine the next IND number
        result = await session.execute(
            select(PartRevision)
            .where(
                (PartRevision.part_id == part_id)
                & (PartRevision.phase == RevisionPhase.DESIGN_FREEZE_PHASE.value)
            )
            .order_by(PartRevision.revision_name.desc())
        )
        last_freeze = result.scalars().first()
        next_ind_num = 1
        if last_freeze and last_freeze.revision_name.startswith("IND"):
            try:
                next_ind_num = int(last_freeze.revision_name[3:]) + 1
            except ValueError:
                pass

        revision_name = f"IND{next_ind_num}"

        revision = PartRevision(
            part_id=part_id,
            revision_name=revision_name,
            phase=RevisionPhase.DESIGN_FREEZE_PHASE.value,
            status=RevisionStatus.FROZEN.value,
            parent_revision_id=parent_revision_id,
            summary="Design freeze - locked for production",
            frozen_at=datetime.utcnow(),
            frozen_by=created_by,
            created_by=created_by,
        )
        session.add(revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=revision.id,
            action="frozen",
            action_description=f"Created design freeze {revision_name}",
            performed_by=created_by,
        )

        logger.info(f"Created design freeze {revision_name} for part {part_id}")
        return revision

    @staticmethod
    async def create_ecr_proposal(
        session: AsyncSession,
        part_id: int,
        parent_freeze_id: int,  # Link to IND1, IND2, etc
        freeze_major_version: int,  # 1 for IND1.x, 2 for IND2.x
        proposal_number: int,  # 1 for first proposal, 2 for second, etc (ECR1.1, ECR1.2)
        summary: Optional[str] = None,
        change_reason: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Create an ECR (Engineering Change Request) proposal after design freeze."""
        revision_name = f"ECR{freeze_major_version}.{proposal_number}"

        revision = PartRevision(
            part_id=part_id,
            revision_name=revision_name,
            phase=RevisionPhase.ECN_PHASE.value,
            status=RevisionStatus.DRAFT.value,
            test_data_status=TestDataStatus.UNCONFIRMED,
            parent_revision_id=parent_freeze_id,
            summary=summary,
            change_reason=change_reason,
            created_by=created_by,
        )
        session.add(revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=part_id,
            revision_id=revision.id,
            action="created",
            action_description=f"Created ECR proposal {revision_name}",
            performed_by=created_by,
        )

        logger.info(f"Created ECR proposal {revision_name} for part {part_id}")
        return revision

    @staticmethod
    async def approve_ecr_proposal(
        session: AsyncSession,
        ecr_revision_id: int,
        next_freeze_major_version: int,  # 2 for IND1.1→IND2, 3 for IND2.1→IND3, etc
        approved_by: int = None,
        approval_notes: Optional[str] = None,
    ) -> PartRevision:
        """Approve an ECR proposal, creating the next design freeze level."""
        ecr = await session.get(PartRevision, ecr_revision_id)
        if not ecr or ecr.phase != RevisionPhase.ECN_PHASE.value:
            raise ValueError("Revision is not in ECN phase")

        # Mark ECR as approved
        ecr.status = RevisionStatus.APPROVED.value
        ecr.test_data_status = TestDataStatus.APPROVED
        ecr.approved_at = datetime.utcnow()
        ecr.approved_by = approved_by
        ecr.approval_notes = approval_notes
        await session.flush()

        # Create next freeze level (ECR1.1 → IND2, ECR2.1 → IND3, etc)
        new_revision_name = f"IND{next_freeze_major_version}"
        new_revision = PartRevision(
            part_id=ecr.part_id,
            revision_name=new_revision_name,
            phase=RevisionPhase.DESIGN_FREEZE_PHASE.value,
            status=RevisionStatus.FROZEN.value,
            parent_revision_id=ecr_revision_id,
            supersedes_revision_id=ecr_revision_id,
            summary=f"Design freeze from {ecr.revision_name}",
            frozen_at=datetime.utcnow(),
            frozen_by=approved_by,
            created_by=approved_by,
        )
        session.add(new_revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=ecr.part_id,
            revision_id=ecr_revision_id,
            action="approved",
            action_description=f"Approved {ecr.revision_name}, created {new_revision_name}",
            performed_by=approved_by,
        )

        logger.info(f"Approved {ecr.revision_name}, created {new_revision_name}")
        return new_revision

    @staticmethod
    async def reject_ecr_proposal(
        session: AsyncSession,
        ecr_revision_id: int,
        rejected_by: int = None,
    ) -> PartRevision:
        """Reject an ECR proposal (remains visible as rejected)."""
        ecr = await session.get(PartRevision, ecr_revision_id)
        if not ecr:
            raise ValueError("Revision not found")

        ecr.status = RevisionStatus.REJECTED.value
        ecr.test_data_status = TestDataStatus.REJECTED
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=ecr.part_id,
            revision_id=ecr_revision_id,
            action="rejected",
            action_description=f"Rejected ECR proposal {ecr.revision_name}",
            performed_by=rejected_by,
        )

        logger.info(f"Rejected {ecr.revision_name} for part {ecr.part_id}")
        return ecr

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
