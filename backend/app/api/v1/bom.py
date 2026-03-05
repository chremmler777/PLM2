"""BOM endpoints for article revisions and project aggregation."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from app.models import Article, ArticleRevision, BOM, BOMItem, CatalogPart, User, get_db
from app.dependencies import get_current_user
from app.schemas.bom import (
    BOMItemCreateRequest, BOMItemUpdateRequest,
    BOMItemResponse, BOMResponse,
    ProjectBOMResponse, ProjectBOMLineResponse, ProjectBOMSourceResponse,
)

bom_router = APIRouter(tags=["bom"])
project_bom_router = APIRouter(tags=["bom"])


def _bom_item_to_response(item: BOMItem) -> BOMItemResponse:
    part = item.catalog_part
    return BOMItemResponse(
        id=item.id,
        bom_id=item.bom_id,
        catalog_part_id=item.catalog_part_id,
        part_number=part.part_number if part else None,
        name=part.name if part else item.name,
        part_type=part.part_type if part else None,
        quantity=item.quantity,
        unit=part.unit if part else item.unit,
        supplier=part.supplier if part else None,
        notes=item.notes,
        position=item.position,
    )


async def _get_or_create_bom(db: AsyncSession, article_id: int, revision_id: int, user_id: int) -> BOM:
    result = await db.execute(
        select(BOM)
        .where(and_(BOM.article_id == article_id, BOM.revision_id == revision_id))
        .options(selectinload(BOM.items).selectinload(BOMItem.catalog_part))
    )
    bom = result.scalar_one_or_none()
    if not bom:
        bom = BOM(
            article_id=article_id,
            revision_id=revision_id,
            name="BOM",
            status="draft",
            created_by=user_id,
        )
        db.add(bom)
        await db.flush()
        # Reload with relationships
        result = await db.execute(
            select(BOM)
            .where(BOM.id == bom.id)
            .options(selectinload(BOM.items).selectinload(BOMItem.catalog_part))
        )
        bom = result.scalar_one()
    return bom


@bom_router.get("/articles/{article_id}/revisions/{revision_id}/bom", response_model=BOMResponse)
async def get_bom(
    article_id: int,
    revision_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get BOM for a revision. Auto-creates empty BOM if none exists."""
    # Verify article belongs to user's org
    result = await db.execute(
        select(Article).where(
            and_(Article.id == article_id, Article.organization_id == current_user.organization_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    bom = await _get_or_create_bom(db, article_id, revision_id, current_user.id)
    await db.commit()

    return BOMResponse(
        id=bom.id,
        article_id=bom.article_id,
        revision_id=bom.revision_id,
        status=bom.status,
        items=[_bom_item_to_response(item) for item in sorted(bom.items, key=lambda x: x.position)],
    )


@bom_router.post(
    "/articles/{article_id}/revisions/{revision_id}/bom/items",
    response_model=BOMItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_bom_item(
    article_id: int,
    revision_id: int,
    request: BOMItemCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a catalog part to a revision's BOM."""
    result = await db.execute(
        select(Article).where(
            and_(Article.id == article_id, Article.organization_id == current_user.organization_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    # Verify catalog part belongs to same org
    result = await db.execute(
        select(CatalogPart).where(
            and_(
                CatalogPart.id == request.catalog_part_id,
                CatalogPart.organization_id == current_user.organization_id,
                CatalogPart.is_active == True,
            )
        )
    )
    catalog_part = result.scalar_one_or_none()
    if not catalog_part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Catalog part not found")

    bom = await _get_or_create_bom(db, article_id, revision_id, current_user.id)

    # Determine position
    if request.position is not None:
        position = request.position
    else:
        position = len(bom.items) + 1

    item = BOMItem(
        bom_id=bom.id,
        catalog_part_id=request.catalog_part_id,
        item_number=str(position),
        name=catalog_part.name,
        quantity=request.quantity,
        unit=catalog_part.unit,
        position=position,
        notes=request.notes,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    # Load catalog_part relationship
    result = await db.execute(
        select(BOMItem)
        .where(BOMItem.id == item.id)
        .options(selectinload(BOMItem.catalog_part))
    )
    item = result.scalar_one()
    return _bom_item_to_response(item)


@bom_router.put(
    "/articles/{article_id}/revisions/{revision_id}/bom/items/{item_id}",
    response_model=BOMItemResponse,
)
async def update_bom_item(
    article_id: int,
    revision_id: int,
    item_id: int,
    request: BOMItemUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update quantity, notes, or position of a BOM item."""
    result = await db.execute(
        select(Article).where(
            and_(Article.id == article_id, Article.organization_id == current_user.organization_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    result = await db.execute(
        select(BOMItem)
        .join(BOM)
        .where(
            and_(
                BOMItem.id == item_id,
                BOM.article_id == article_id,
                BOM.revision_id == revision_id,
            )
        )
        .options(selectinload(BOMItem.catalog_part))
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM item not found")

    if request.quantity is not None:
        item.quantity = request.quantity
    if request.notes is not None:
        item.notes = request.notes
    if request.position is not None:
        item.position = request.position

    await db.commit()
    await db.refresh(item)

    result = await db.execute(
        select(BOMItem).where(BOMItem.id == item.id).options(selectinload(BOMItem.catalog_part))
    )
    item = result.scalar_one()
    return _bom_item_to_response(item)


@bom_router.delete(
    "/articles/{article_id}/revisions/{revision_id}/bom/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_bom_item(
    article_id: int,
    revision_id: int,
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a BOM item."""
    result = await db.execute(
        select(Article).where(
            and_(Article.id == article_id, Article.organization_id == current_user.organization_id)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    result = await db.execute(
        select(BOMItem)
        .join(BOM)
        .where(
            and_(
                BOMItem.id == item_id,
                BOM.article_id == article_id,
                BOM.revision_id == revision_id,
            )
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOM item not found")

    await db.delete(item)
    await db.commit()


@project_bom_router.get("/projects/{project_id}/bom-aggregation", response_model=ProjectBOMResponse)
async def get_project_bom(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate BOM totals across all articles in a project."""
    from app.models.entities import Project, Plant

    # Verify project belongs to org (Project → Plant → Organization)
    result = await db.execute(
        select(Project)
        .join(Plant, Plant.id == Project.plant_id)
        .where(
            and_(
                Project.id == project_id,
                Plant.organization_id == current_user.organization_id,
            )
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Get all articles in this project that have an active revision
    result = await db.execute(
        select(Article, ArticleRevision, BOM, BOMItem, CatalogPart)
        .join(ArticleRevision, Article.active_revision_id == ArticleRevision.id)
        .join(BOM, and_(BOM.article_id == Article.id, BOM.revision_id == ArticleRevision.id))
        .join(BOMItem, BOMItem.bom_id == BOM.id)
        .join(CatalogPart, CatalogPart.id == BOMItem.catalog_part_id)
        .where(
            and_(
                Article.project_id == project_id,
                Article.organization_id == current_user.organization_id,
            )
        )
    )
    rows = result.all()

    # Aggregate in Python
    from collections import defaultdict
    totals: dict[int, dict] = defaultdict(lambda: {"total_quantity": 0.0, "sources": [], "part": None})

    for article, revision, bom, item, part in rows:
        cp_id = part.id
        totals[cp_id]["total_quantity"] += item.quantity
        totals[cp_id]["part"] = part
        totals[cp_id]["sources"].append(
            ProjectBOMSourceResponse(
                article_id=article.id,
                article_number=article.article_number,
                article_name=article.name,
                revision_id=revision.id,
                revision=revision.revision,
                quantity=item.quantity,
            )
        )

    lines = []
    for cp_id, data in totals.items():
        part = data["part"]
        lines.append(
            ProjectBOMLineResponse(
                catalog_part_id=cp_id,
                part_number=part.part_number,
                name=part.name,
                part_type=part.part_type,
                unit=part.unit,
                supplier=part.supplier,
                total_quantity=data["total_quantity"],
                sources=data["sources"],
            )
        )

    lines.sort(key=lambda x: x.part_number)
    return ProjectBOMResponse(project_id=project_id, lines=lines)
