"""Main FastAPI application."""
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import get_settings
from app.models import init_db
from app.api import api_router

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

settings = get_settings()
logger.debug(f"App settings loaded: debug={settings.debug}")


async def seed_test_data():
    """Create test data for Phase 1 testing."""
    from sqlalchemy import select
    from app.models import Organization, User, Plant, Project, AsyncSessionLocal
    from app.auth.security import get_password_hash

    async with AsyncSessionLocal() as session:
        try:
            # Create org
            result = await session.execute(
                select(Organization).where(Organization.code == "test-org")
            )
            test_org = result.scalar_one_or_none()
            if not test_org:
                logger.info("Creating test organization...")
                test_org = Organization(
                    name="Test Organization",
                    code="test-org",
                    description="Test organization",
                    is_active=True,
                )
                session.add(test_org)
                await session.flush()

            # Create plant
            result = await session.execute(
                select(Plant).where(Plant.code == "main-plant")
            )
            test_plant = result.scalar_one_or_none()
            if not test_plant:
                logger.info("Creating test plant...")
                test_plant = Plant(
                    organization_id=test_org.id,
                    name="Main Factory",
                    code="main-plant",
                    location="Germany",
                    is_active=True,
                )
                session.add(test_plant)
                await session.flush()

            # Create project
            result = await session.execute(
                select(Project).where(Project.code == "test-project")
            )
            test_project = result.scalar_one_or_none()
            if not test_project:
                logger.info("Creating test project...")
                test_project = Project(
                    plant_id=test_plant.id,
                    name="Test Project",
                    code="test-project",
                    description="Test project for Phase 1",
                    status="active",
                )
                session.add(test_project)
                await session.flush()

            # Create user
            result = await session.execute(
                select(User).where(User.email == "test@example.com")
            )
            test_user = result.scalar_one_or_none()
            if not test_user:
                logger.info("Creating test user...")
                test_user = User(
                    organization_id=test_org.id,
                    username="testuser",
                    email="test@example.com",
                    full_name="Test User",
                    hashed_password=get_password_hash("password"),
                    role="engineer",
                    is_active=True,
                    mfa_enabled=False,
                )
                session.add(test_user)

            await session.commit()
            logger.info("Test data seeded successfully")
        except Exception as e:
            logger.error(f"Error seeding test data: {e}")
            await session.rollback()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    # Startup
    logger.info("Starting up PLM application...")

    # Run Alembic migrations
    import subprocess
    logger.info("Running database migrations...")
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            logger.info("Database migrations completed successfully")
        else:
            logger.warning(f"Migration warnings: {result.stderr}")
    except Exception as e:
        logger.error(f"Failed to run migrations: {e}")

    await init_db()
    logger.info("Database initialized")
    await seed_test_data()
    logger.info("Test data seeded")
    yield
    # Shutdown
    logger.info("Shutting down PLM application...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Product Lifecycle Management System - Production Ready",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.app_version,
    }
