"""API v1 routes, grouped into functional modules."""
from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.articles import router as articles_router
from app.api.v1.plants import router as plants_router
from app.api.v1.catalog_parts import router as catalog_parts_router
from app.api.v1.bom import bom_router, project_bom_router

# Module: accounts (authentication, user management)
from app.api.v1.accounts.auth import router as auth_router
from app.api.v1.accounts.users import router as users_router

# Module: items (parts, revisions, files, BOM, relations)
from app.api.v1.items.parts import router as parts_router
from app.api.v1.items.revision_files import router as revision_files_router
from app.api.v1.items.part_bom import router as part_bom_router
from app.api.v1.items.part_relations import router as part_relations_router

# Module: workflows (RASIC templates and instances)
from app.api.v1.workflows.workflow_templates import router as workflow_templates_router
from app.api.v1.workflows.workflow_instances import router as workflow_instances_router

# Module: overview (dashboard, search, notifications)
from app.api.v1.overview.dashboard import router as dashboard_router
from app.api.v1.overview.search import router as search_router
from app.api.v1.overview.notifications import router as notifications_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(articles_router)
api_router.include_router(parts_router)
api_router.include_router(revision_files_router)
api_router.include_router(part_bom_router)
api_router.include_router(part_relations_router)
api_router.include_router(users_router)
api_router.include_router(dashboard_router)
api_router.include_router(search_router)
api_router.include_router(notifications_router)
api_router.include_router(plants_router)
api_router.include_router(workflow_templates_router)
api_router.include_router(workflow_instances_router)
api_router.include_router(catalog_parts_router)
api_router.include_router(bom_router)
api_router.include_router(project_bom_router)

__all__ = ["api_router"]
