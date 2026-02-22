"""API v1 routes."""
from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.articles import router as articles_router
from app.api.v1.auth import router as auth_router
from app.api.v1.parts import router as parts_router
from app.api.v1.plants import router as plants_router
from app.api.v1.workflow_templates import router as workflow_templates_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth_router)
api_router.include_router(health_router)
api_router.include_router(articles_router)
api_router.include_router(parts_router)
api_router.include_router(plants_router)
api_router.include_router(workflow_templates_router)

__all__ = ["api_router"]
