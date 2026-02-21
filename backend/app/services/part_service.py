"""Service for managing parts and revisions with RFQ/ENG/FREEZE/ECR workflow."""
import logging
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    async def create_rfq_revision(
        session: AsyncSession,
        part_id: int,
        revision_number: int,  # 1 for RFQ1, 2 for RFQ2, etc
        summary: Optional[str] = None,
        created_by: int = None,
    ) -> PartRevision:
        """Create a new RFQ revision (RFQ1, RFQ2, etc)."""
        revision_name = f"RFQ{revision_number}"

        revision = PartRevision(
            part_id=part_id,
            revision_name=revision_name,
            phase=RevisionPhase.RFQ_PHASE,
            status=RevisionStatus.DRAFT,
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
    async def transition_rfq_to_engineering(
        session: AsyncSession,
        rfq_revision_id: int,
        created_by: int = None,
    ) -> PartRevision:
        """Transition from RFQ to Engineering phase (RFQ1 → ENG1)."""
        rfq_rev = await session.get(PartRevision, rfq_revision_id)
        if not rfq_rev or rfq_rev.phase != RevisionPhase.RFQ_PHASE:
            raise ValueError("Revision is not in RFQ phase")

        # Create ENG1 revision
        eng_revision = PartRevision(
            part_id=rfq_rev.part_id,
            revision_name="ENG1",
            phase=RevisionPhase.ENGINEERING_PHASE,
            status=RevisionStatus.DRAFT,
            parent_revision_id=rfq_rev.id,
            summary="Official engineering release after RFQ award",
            created_by=created_by,
        )
        session.add(eng_revision)
        await session.flush()

        await ChangelogService.log_action(
            session=session,
            part_id=rfq_rev.part_id,
            revision_id=eng_revision.id,
            action="created",
            action_description="Transitioned from RFQ1 to ENG1 (awarded)",
            performed_by=created_by,
        )

        logger.info(f"Created ENG1 from RFQ for part {rfq_rev.part_id}")
        return eng_revision

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
            phase=RevisionPhase.ENGINEERING_PHASE,
            status=RevisionStatus.DRAFT,
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
        if not proposal or proposal.phase != RevisionPhase.ENGINEERING_PHASE:
            raise ValueError("Revision is not in Engineering phase")
        if proposal.test_data_status == TestDataStatus.APPROVED:
            raise ValueError("Revision is already approved")

        # Mark proposal as approved
        proposal.status = RevisionStatus.APPROVED
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
            phase=RevisionPhase.ENGINEERING_PHASE,
            status=RevisionStatus.DRAFT,
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

        proposal.status = RevisionStatus.REJECTED
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
                & (PartRevision.phase == RevisionPhase.DESIGN_FREEZE_PHASE)
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
            phase=RevisionPhase.DESIGN_FREEZE_PHASE,
            status=RevisionStatus.FROZEN,
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
            phase=RevisionPhase.ECN_PHASE,
            status=RevisionStatus.DRAFT,
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
        if not ecr or ecr.phase != RevisionPhase.ECN_PHASE:
            raise ValueError("Revision is not in ECN phase")

        # Mark ECR as approved
        ecr.status = RevisionStatus.APPROVED
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
            phase=RevisionPhase.DESIGN_FREEZE_PHASE,
            status=RevisionStatus.FROZEN,
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

        ecr.status = RevisionStatus.REJECTED
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
            .order_by(RevisionChangelog.performed_at)
        )
        return result.scalars().all()

    @staticmethod
    async def get_revision_changelog(
        session: AsyncSession,
        revision_id: int,
    ) -> List[RevisionChangelog]:
        """Get changelog for a specific revision."""
        result = await session.execute(
            select(RevisionChangelog)
            .where(RevisionChangelog.revision_id == revision_id)
            .order_by(RevisionChangelog.performed_at)
        )
        return result.scalars().all()
