"""Article and revision endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.models import Article, ArticleRevision, User, get_db
from app.dependencies import get_current_user, get_org_filter
from app.schemas import (
    ArticleCreateRequest, ArticleUpdateRequest, ArticleResponse, ArticleDetailResponse,
    RevisionCreateRequest, ReleaseRevisionRequest, ChangeProposalRequest, RevisionStatusTransitionRequest,
    RevisionResponse, RevisionTreeResponse,
)
from app.services.revision_service import RevisionService

router = APIRouter(prefix="/articles", tags=["articles"])


@router.post("", response_model=ArticleResponse, status_code=status.HTTP_201_CREATED)
async def create_article(
    request: ArticleCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new article.

    The article_number must be unique within the organization.
    """
    # Check if article_number already exists in organization
    result = await db.execute(
        select(Article).where(
            and_(
                Article.organization_id == current_user.organization_id,
                Article.article_number == request.article_number,
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Article number '{request.article_number}' already exists in this organization",
        )

    # Create article
    article = Article(
        organization_id=current_user.organization_id,
        article_number=request.article_number,
        name=request.name,
        description=request.description,
        article_type=request.article_type,
        sourcing_type=request.sourcing_type,
        created_by=current_user.id,
    )

    db.add(article)
    await db.flush()
    await db.commit()

    return ArticleResponse.from_orm(article)


@router.get("", response_model=list[ArticleResponse])
async def list_articles(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List articles for the current organization.

    Can optionally filter by project_id (through CADFiles).
    """
    query = select(Article).where(Article.organization_id == current_user.organization_id)

    if project_id:
        # Filter by articles that have CAD files in this project
        from app.models import CADFile
        query = query.join(ArticleRevision).join(
            CADFile,
            and_(
                CADFile.project_id == project_id,
            )
        ).distinct()

    result = await db.execute(query.order_by(Article.article_number))
    articles = result.scalars().all()

    return [ArticleResponse.from_orm(a) for a in articles]


@router.get("/{article_id}", response_model=ArticleDetailResponse)
async def get_article(
    article_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get article details with all revisions and revision tree."""
    # Fetch article with revisions
    result = await db.execute(
        select(Article)
        .where(
            and_(
                Article.id == article_id,
                Article.organization_id == current_user.organization_id,
            )
        )
        .options(selectinload(Article.revisions))
    )
    article = result.scalar_one_or_none()

    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    # Build revision tree
    revision_tree = await RevisionService.get_revision_tree(db, article_id)

    return ArticleDetailResponse(
        article=ArticleResponse.from_orm(article),
        revisions=[RevisionResponse.from_orm(r) for r in article.revisions],
        revision_tree=RevisionTreeResponse(**revision_tree),
    )


@router.put("/{article_id}", response_model=ArticleResponse)
async def update_article(
    article_id: int,
    request: ArticleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update article metadata."""
    # Fetch article
    result = await db.execute(
        select(Article).where(
            and_(
                Article.id == article_id,
                Article.organization_id == current_user.organization_id,
            )
        )
    )
    article = result.scalar_one_or_none()

    if not article:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    # Update fields
    if request.name:
        article.name = request.name
    if request.description is not None:
        article.description = request.description
    if request.sourcing_type:
        article.sourcing_type = request.sourcing_type

    await db.commit()
    return ArticleResponse.from_orm(article)


# ============================================================================
# REVISION ENDPOINTS
# ============================================================================


@router.post(
    "/{article_id}/revisions/engineering",
    response_model=RevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_engineering_revision(
    article_id: int,
    request: RevisionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new engineering revision.

    Auto-numbered as !1, !2, !3, etc.
    """
    # Verify article exists and belongs to user's org
    result = await db.execute(
        select(Article).where(
            and_(
                Article.id == article_id,
                Article.organization_id == current_user.organization_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    try:
        revision = await RevisionService.create_engineering_revision(
            db,
            article_id,
            current_user.id,
        )
        await db.commit()
        return RevisionResponse.from_orm(revision)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{article_id}/revisions/{revision_id}/release",
    response_model=RevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def release_revision(
    article_id: int,
    revision_id: int,
    request: ReleaseRevisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Release an engineering revision to a released index.

    The revision must be in 'approved' status.
    """
    # Verify article exists
    result = await db.execute(
        select(Article).where(
            and_(
                Article.id == article_id,
                Article.organization_id == current_user.organization_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    try:
        released_revision = await RevisionService.release_revision(
            db,
            article_id,
            revision_id,
            current_user.id,
        )
        await db.commit()
        return RevisionResponse.from_orm(released_revision)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{article_id}/revisions/{revision_id}/change-proposal",
    response_model=RevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_change_proposal(
    article_id: int,
    revision_id: int,
    request: ChangeProposalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a change proposal to modify a released index.

    The revision_id is the released index to modify.
    """
    # Verify article exists
    result = await db.execute(
        select(Article).where(
            and_(
                Article.id == article_id,
                Article.organization_id == current_user.organization_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    try:
        change_revision = await RevisionService.create_change_proposal(
            db,
            article_id,
            revision_id,
            current_user.id,
            request.change_summary,
        )
        await db.commit()
        return RevisionResponse.from_orm(change_revision)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put(
    "/{article_id}/revisions/{revision_id}/status",
    response_model=RevisionResponse,
)
async def transition_revision_status(
    article_id: int,
    revision_id: int,
    request: RevisionStatusTransitionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition a revision to a new status.

    Allowed transitions:
    - draft → rfq, canceled
    - rfq → in_review, draft, canceled
    - in_review → approved, rejected, draft
    - approved → in_implementation, rejected
    - in_implementation → released, rejected
    - released, rejected, canceled, superseded → no transitions
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Revision not found",
        )

    # Verify article belongs to user's org
    result = await db.execute(
        select(Article).where(
            and_(
                Article.id == article_id,
                Article.organization_id == current_user.organization_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    try:
        updated_revision = await RevisionService.transition_status(
            db,
            revision_id,
            revision.status,
            request.new_status.value,
            request.notes,
        )
        await db.commit()
        return RevisionResponse.from_orm(updated_revision)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{article_id}/active-revision/{revision_id}")
async def set_active_revision(
    article_id: int,
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a specific revision as the active revision for BOM aggregation."""
    result = await db.execute(
        select(Article).where(
            and_(Article.id == article_id, Article.organization_id == current_user.organization_id)
        )
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    # Verify revision belongs to this article
    result = await db.execute(
        select(ArticleRevision).where(
            and_(ArticleRevision.id == revision_id, ArticleRevision.article_id == article_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")

    article.active_revision_id = revision_id
    await db.commit()
    return {"article_id": article_id, "active_revision_id": revision_id}


@router.put("/{article_id}/project")
async def set_article_project(
    article_id: int,
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign (or unassign) an article to a project."""
    result = await db.execute(
        select(Article).where(
            and_(Article.id == article_id, Article.organization_id == current_user.organization_id)
        )
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    article.project_id = project_id
    await db.commit()
    return {"article_id": article_id, "project_id": project_id}


@router.get("/{article_id}/revision-tree", response_model=RevisionTreeResponse)
async def get_revision_tree(
    article_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get hierarchical revision tree for an article."""
    # Verify article exists
    result = await db.execute(
        select(Article).where(
            and_(
                Article.id == article_id,
                Article.organization_id == current_user.organization_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    tree = await RevisionService.get_revision_tree(db, article_id)
    return RevisionTreeResponse(**tree)
