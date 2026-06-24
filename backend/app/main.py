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
    from app.models import Organization, User, Plant, Project, Department, AsyncSessionLocal
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

            # Create admin user (for user management; change password after first login)
            result = await session.execute(
                select(User).where(User.email == "admin@example.com")
            )
            admin_user = result.scalar_one_or_none()
            if not admin_user:
                logger.info("Creating admin user...")
                admin_user = User(
                    organization_id=test_org.id,
                    username="admin",
                    email="admin@example.com",
                    full_name="Administrator",
                    hashed_password=get_password_hash("admin1234"),
                    role="admin",
                    is_active=True,
                    mfa_enabled=False,
                )
                session.add(admin_user)

            # Create workflow departments
            departments_data = [
                ("Developer", "action", 1),
                ("Tool Engineer", "action", 2),
                ("Manufacturing Engineer", "action", 3),
                ("APQP", "action", 4),
                ("Sales", "action", 5),
                ("Project Manager", "action", 6),
                ("Planner/Scheduler", "info", 7),
                ("Operations Manager", "info", 8),
            ]
            for dept_name, flow_type, sort_order in departments_data:
                result = await session.execute(
                    select(Department).where(Department.name == dept_name)
                )
                if not result.scalar_one_or_none():
                    logger.info(f"Creating department: {dept_name}")
                    dept = Department(
                        name=dept_name,
                        flow_type=flow_type,
                        is_active=True,
                        sort_order=sort_order,
                    )
                    session.add(dept)

            await session.commit()

            # --- Change-management cost reference data (idempotent) ---
            from app.models.change_cost import DepartmentRate, AssessmentActivity
            from app.models.entities import Plant, Organization
            from app.models.workflow import Department as _Dep
            org = (await session.execute(select(Organization))).scalars().first()
            if org is not None:
                plants = {p.name: p for p in (await session.execute(
                    select(Plant).where(Plant.organization_id == org.id))).scalars().all()}
                for name, code, loc, factor in [("Weissenburg", "WUG", "DE", 0.6), ("USA", "USA", "US", 0.36)]:
                    if name not in plants:
                        p = Plant(organization_id=org.id, name=name, code=code, location=loc)
                        session.add(p)
                        await session.flush()
                        plants[name] = p
                rate_table = {
                    "Sales": (50.0, None), "R&D": (65.0, 21.5), "Tool design": (65.0, 21.5),
                    "IE": (65.0, 21.5), "Quality": (45.0, 21.5), "Logistics": (50.0, 21.5),
                    "Production": (55.0, 21.5), "Purchasing": (50.0, 21.5),
                    "Production control": (50.0, 21.5),
                }
                existing_rates = {(r.department_id, r.plant_id) for r in (await session.execute(
                    select(DepartmentRate))).scalars().all()}
                for dep_name, (wug, usa) in rate_table.items():
                    dep = (await session.execute(
                        select(_Dep).where(_Dep.name == dep_name))).scalar_one_or_none()
                    if dep is None:
                        continue
                    for plant_name, rate, factor in [("Weissenburg", wug, 0.6), ("USA", usa, 0.36)]:
                        if rate is None:
                            continue
                        pid = plants[plant_name].id
                        if (dep.id, pid) not in existing_rates:
                            session.add(DepartmentRate(department_id=dep.id, plant_id=pid,
                                                       hourly_rate=rate, min_factor=factor))
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

    # Refuse to run with the dev secret key outside debug mode
    if not settings.debug and settings.secret_key == "dev-secret-key-change-in-production":
        raise RuntimeError(
            "SECRET_KEY is still the development default. Set SECRET_KEY in the "
            "environment (or .env) before running with DEBUG=false."
        )

    # Skip Alembic migrations for SQLite (development)
    # For PostgreSQL (production), migrations are handled separately
    if "sqlite" not in settings.database_url:
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

    logger.info(f"Database URL: {settings.database_url}")
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    try:
        await seed_test_data()
        logger.info("Test data seeded")
    except Exception as e:
        logger.warning(f"Warning seeding test data: {e}")

    # Periodic overdue lesson-action reminders (every 6h, deduped to 1/24h per action)
    import asyncio

    async def _reminder_loop():
        from app.models import AsyncSessionLocal
        from app.services.lesson_reminder_service import (
            send_overdue_action_reminders, escalate_overdue_targets,
        )
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    await send_overdue_action_reminders(session)
                async with AsyncSessionLocal() as session:
                    await escalate_overdue_targets(session)
            except Exception as e:
                logger.warning(f"Lesson reminder run failed: {e}")
            await asyncio.sleep(6 * 3600)

    reminder_task = asyncio.create_task(_reminder_loop())

    yield
    # Shutdown
    reminder_task.cancel()
    logger.info("Shutting down PLM application...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Product Lifecycle Management System - Production Ready",
    lifespan=lifespan,
)

# CORS middleware (origins configurable via CORS_ORIGINS env)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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
