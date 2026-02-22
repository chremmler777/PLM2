"""Database connection and session management."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

# Create async engine with proper connection pooling
# SQLite doesn't support pool parameters, so only add them for PostgreSQL
engine_kwargs = {
    "echo": settings.debug,
}

if "sqlite" not in settings.database_url:
    # PostgreSQL connection pooling
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,
    })

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


async def get_db():
    """Dependency to get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database - create tables if they don't exist.

    For SQLite (development), use create_all().
    For PostgreSQL (production), tables are managed by Alembic migrations.
    """
    import logging
    logger = logging.getLogger(__name__)

    # For SQLite development, create tables directly
    if "sqlite" in settings.database_url:
        try:
            logger.info("Creating SQLite tables...")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("SQLite tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create SQLite tables: {e}")
            raise
    # For PostgreSQL, tables are created by Alembic migrations
    # This function is just a placeholder
