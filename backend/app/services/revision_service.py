"""Article revision lifecycle management service.

Handles complex revision business logic:
- Engineering revisions: !1, !2, !3
- Released indexes: 1, 2, 3
- Change proposals: 1.1, 1.2, 2.1
- Status transitions with validation
"""
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Article, ArticleRevision, User


class RevisionService:
    """Service for managing article revisions."""

    # Valid status transitions
    STATUS_TRANSITIONS = {
        "draft": ["rfq", "canceled"],
        "rfq": ["in_review", "draft", "canceled"],
        "in_review": ["approved", "rejected", "draft"],
        "approved": ["in_implementation", "rejected"],
        "in_implementation": ["released", "rejected"],
        "released": [],  # Can't transition from released directly (must use change proposal)
        "rejected": [],  # Terminal state
        "canceled": [],  # Terminal state
        "superseded": [],  # Terminal state
    }

    @staticmethod
    def get_next_engineering_revision_number(existing_revisions: list[ArticleRevision]) -> str:
        """Calculate next engineering revision number (!1, !2, !3, ...).

        Args:
            existing_revisions: List of all revisions for the article

        Returns:
            Next engineering revision number (e.g., "!1", "!2")
        """
        engineering_revs = [
            r for r in existing_revisions
            if r.revision_type == "engineering"
        ]
        if not engineering_revs:
            return "!1"

        # Extract numbers from revision strings like "!1", "!2"
        numbers = []
        for rev in engineering_revs:
            try:
                num = int(rev.revision.lstrip("!"))
                numbers.append(num)
            except (ValueError, AttributeError):
                pass

        return f"!{max(numbers) + 1 if numbers else 1}"

    @staticmethod
    def get_next_released_index(existing_revisions: list[ArticleRevision]) -> str:
        """Calculate next released index number (1, 2, 3, ...).

        Args:
            existing_revisions: List of all revisions for the article

        Returns:
            Next released index number (e.g., "1", "2")
        """
        released_revs = [
            r for r in existing_revisions
            if r.revision_type == "released" and "." not in r.revision
        ]
        if not released_revs:
            return "1"

        numbers = []
        for rev in released_revs:
            try:
                num = int(rev.revision)
                numbers.append(num)
            except (ValueError, AttributeError):
                pass

        return str(max(numbers) + 1 if numbers else 1)

    @staticmethod
    def get_next_change_revision(
        parent_index: str,
        existing_revisions: list[ArticleRevision]
    ) -> str:
        """Calculate next change proposal number (1.1, 1.2, 2.1, ...).

        Args:
            parent_index: Parent released index (e.g., "1", "2")
            existing_revisions: List of all revisions for the article

        Returns:
            Next change revision number (e.g., "1.1", "1.2")
        """
        # Find all changes to this parent
        changes = [
            r for r in existing_revisions
            if r.revision_type == "change" and r.revision.startswith(f"{parent_index}.")
        ]

        if not changes:
            return f"{parent_index}.1"

        numbers = []
        for rev in changes:
            try:
                # Extract the minor version from "1.1", "1.2", etc.
                minor = int(rev.revision.split(".")[1])
                numbers.append(minor)
            except (ValueError, IndexError):
                pass

        next_minor = max(numbers) + 1 if numbers else 1
        return f"{parent_index}.{next_minor}"

    @staticmethod
    def validate_status_transition(from_status: str, to_status: str) -> bool:
        """Validate if a status transition is allowed.

        Args:
            from_status: Current status
            to_status: Target status

        Returns:
            True if transition is allowed, False otherwise
        """
        if from_status not in RevisionService.STATUS_TRANSITIONS:
            return False
        return to_status in RevisionService.STATUS_TRANSITIONS[from_status]

    @staticmethod
    async def create_engineering_revision(
        db: AsyncSession,
        article_id: int,
        created_by_id: int,
    ) -> ArticleRevision:
        """Create a new engineering revision.

        Args:
            db: Database session
            article_id: Article ID
            created_by_id: User ID creating the revision

        Returns:
            New ArticleRevision object

        Raises:
            ValueError: If article not found
        """
        # Fetch article with existing revisions
        result = await db.execute(
            select(Article)
            .where(Article.id == article_id)
            .options(selectinload(Article.revisions))
        )
        article = result.scalar_one_or_none()

        if not article:
            raise ValueError(f"Article {article_id} not found")

        # Calculate next engineering revision number
        next_revision = RevisionService.get_next_engineering_revision_number(article.revisions)

        # Create new revision
        new_revision = ArticleRevision(
            article_id=article_id,
            revision=next_revision,
            revision_type="engineering",
            status="draft",
            created_by=created_by_id,
            created_at=datetime.utcnow(),
        )

        db.add(new_revision)
        await db.flush()  # Flush to get the ID
        return new_revision

    @staticmethod
    async def release_revision(
        db: AsyncSession,
        article_id: int,
        revision_id: int,
        released_by_id: int,
    ) -> ArticleRevision:
        """Release an engineering revision to a released index.

        Creates a new released index revision from an engineering revision.

        Args:
            db: Database session
            article_id: Article ID
            revision_id: Revision ID to release
            released_by_id: User ID releasing

        Returns:
            New released ArticleRevision

        Raises:
            ValueError: If revision not found or not in approved status
        """
        # Fetch revision
        result = await db.execute(
            select(ArticleRevision).where(
                and_(
                    ArticleRevision.id == revision_id,
                    ArticleRevision.article_id == article_id,
                )
            )
        )
        revision = result.scalar_one_or_none()

        if not revision:
            raise ValueError(f"Revision {revision_id} not found")

        if revision.status != "approved":
            raise ValueError(f"Can only release approved revisions (current status: {revision.status})")

        # Fetch article with all revisions
        result = await db.execute(
            select(Article)
            .where(Article.id == article_id)
            .options(selectinload(Article.revisions))
        )
        article = result.scalar_one_or_none()

        # Get next released index
        next_index = RevisionService.get_next_released_index(article.revisions)

        # Create released revision
        released_revision = ArticleRevision(
            article_id=article_id,
            revision=next_index,
            revision_type="released",
            status="released",
            parent_revision_id=revision_id,
            released_at=datetime.utcnow(),
            released_by=released_by_id,
            created_by=released_by_id,
            created_at=datetime.utcnow(),
        )

        db.add(released_revision)
        await db.flush()

        # Update original engineering revision as superseded
        revision.supersedes_id = released_revision.id
        revision.status = "superseded"

        # Update article's active revision
        article.active_revision_id = released_revision.id

        return released_revision

    @staticmethod
    async def create_change_proposal(
        db: AsyncSession,
        article_id: int,
        parent_index_id: int,
        created_by_id: int,
        change_summary: str | None = None,
    ) -> ArticleRevision:
        """Create a change proposal to a released index.

        Args:
            db: Database session
            article_id: Article ID
            parent_index_id: ID of the released index to modify
            created_by_id: User ID creating the proposal
            change_summary: Description of changes

        Returns:
            New change proposal ArticleRevision

        Raises:
            ValueError: If parent index not found or not released
        """
        # Fetch parent revision
        result = await db.execute(
            select(ArticleRevision).where(
                and_(
                    ArticleRevision.id == parent_index_id,
                    ArticleRevision.article_id == article_id,
                    ArticleRevision.revision_type == "released",
                )
            )
        )
        parent = result.scalar_one_or_none()

        if not parent:
            raise ValueError(f"Released index {parent_index_id} not found")

        # Fetch all revisions to calculate next change number
        result = await db.execute(
            select(Article)
            .where(Article.id == article_id)
            .options(selectinload(Article.revisions))
        )
        article = result.scalar_one_or_none()

        # Calculate next change revision number
        next_revision = RevisionService.get_next_change_revision(parent.revision, article.revisions)

        # Create change proposal
        change_revision = ArticleRevision(
            article_id=article_id,
            revision=next_revision,
            revision_type="change",
            status="draft",
            parent_index_id=parent_index_id,
            change_summary=change_summary,
            created_by=created_by_id,
            created_at=datetime.utcnow(),
        )

        db.add(change_revision)
        await db.flush()
        return change_revision

    @staticmethod
    async def transition_status(
        db: AsyncSession,
        revision_id: int,
        from_status: str,
        to_status: str,
        notes: str | None = None,
    ) -> ArticleRevision:
        """Transition a revision to a new status.

        Args:
            db: Database session
            revision_id: Revision ID
            from_status: Current status (for validation)
            to_status: Target status
            notes: Optional notes about the transition

        Returns:
            Updated ArticleRevision

        Raises:
            ValueError: If transition not allowed
        """
        # Validate transition
        if not RevisionService.validate_status_transition(from_status, to_status):
            raise ValueError(f"Cannot transition from {from_status} to {to_status}")

        # Fetch revision
        result = await db.execute(
            select(ArticleRevision).where(ArticleRevision.id == revision_id)
        )
        revision = result.scalar_one_or_none()

        if not revision:
            raise ValueError(f"Revision {revision_id} not found")

        if revision.status != from_status:
            raise ValueError(f"Revision status is {revision.status}, expected {from_status}")

        # Update status
        revision.status = to_status
        if notes:
            revision.comments = notes

        return revision

    @staticmethod
    async def get_active_revision(
        db: AsyncSession,
        article_id: int,
    ) -> ArticleRevision | None:
        """Get the active (current) revision for an article.

        Args:
            db: Database session
            article_id: Article ID

        Returns:
            Active ArticleRevision or None
        """
        result = await db.execute(
            select(ArticleRevision)
            .where(
                and_(
                    ArticleRevision.article_id == article_id,
                    ArticleRevision.revision_type == "released",
                )
            )
            .order_by(ArticleRevision.revision.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_revision_tree(
        db: AsyncSession,
        article_id: int,
    ) -> dict:
        """Get hierarchical revision tree for an article.

        Structure:
        {
            "engineering": [!1, !2, ...],
            "released_indexes": [
                {
                    "index": 1,
                    "revision_id": ...,
                    "changes": [1.1, 1.2, ...]
                },
                ...
            ]
        }

        Args:
            db: Database session
            article_id: Article ID

        Returns:
            Hierarchical revision structure
        """
        # Fetch all revisions
        result = await db.execute(
            select(ArticleRevision)
            .where(ArticleRevision.article_id == article_id)
            .order_by(ArticleRevision.revision)
        )
        revisions = result.scalars().all()

        # Organize by type
        engineering = []
        released_indexes = {}

        for rev in revisions:
            if rev.revision_type == "engineering":
                engineering.append({
                    "id": rev.id,
                    "revision": rev.revision,
                    "status": rev.status,
                })
            elif rev.revision_type == "released":
                released_indexes[rev.revision] = {
                    "id": rev.id,
                    "revision": rev.revision,
                    "status": rev.status,
                    "changes": [],
                }
            elif rev.revision_type == "change":
                # Find parent index
                parent_index = rev.revision.split(".")[0]
                if parent_index in released_indexes:
                    released_indexes[parent_index]["changes"].append({
                        "id": rev.id,
                        "revision": rev.revision,
                        "status": rev.status,
                    })

        return {
            "engineering": engineering,
            "released_indexes": list(released_indexes.values()),
        }
