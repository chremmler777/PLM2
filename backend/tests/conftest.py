"""Shared test fixtures: isolated SQLite DB per test, app client, seeded users."""
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.models import get_db
from app.models.database import Base
from app.models.entities import Organization, Plant, Project, User
from app.auth.security import get_password_hash

ADMIN_PASSWORD = "admin-secret-1"
ENGINEER_PASSWORD = "eng-secret-12"


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def seed(session_factory):
    """Org, plant, project, and three users (admin, engineer, inactive)."""
    async with session_factory() as s:
        org = Organization(name="Test Org", code="test-org", is_active=True)
        s.add(org)
        await s.flush()

        plant = Plant(organization_id=org.id, name="Plant", code="plant", location="DE", is_active=True)
        s.add(plant)
        await s.flush()

        project = Project(plant_id=plant.id, name="Project", code="proj", status="active")
        s.add(project)
        await s.flush()

        admin = User(
            organization_id=org.id, username="admin", email="admin@test.io",
            full_name="Admin", hashed_password=get_password_hash(ADMIN_PASSWORD),
            role="admin", is_active=True, mfa_enabled=False,
        )
        engineer = User(
            organization_id=org.id, username="eng", email="eng@test.io",
            full_name="Engineer", hashed_password=get_password_hash(ENGINEER_PASSWORD),
            role="engineer", is_active=True, mfa_enabled=False,
        )
        inactive = User(
            organization_id=org.id, username="ghost", email="ghost@test.io",
            full_name="Ghost", hashed_password=get_password_hash("ghost-secret-1"),
            role="viewer", is_active=False, mfa_enabled=False,
        )
        s.add_all([admin, engineer, inactive])
        await s.commit()

        return {
            "org_id": org.id,
            "project_id": project.id,
            "admin_id": admin.id,
            "engineer_id": engineer.id,
            "inactive_id": inactive.id,
        }


@pytest_asyncio.fixture
async def client(session_factory, seed):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def login(client: AsyncClient, email: str, password: str) -> dict:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def approve_gates(client, auth, change_id: int, *keys):
    """Set the given change gates to 'yes' (all three when no keys given)."""
    for k in keys or ("feasibility", "budget", "release"):
        res = await client.put(
            f"/api/v1/changes/{change_id}/gates/{k}",
            json={"decision": "yes"}, headers=auth,
        )
        assert res.status_code == 200, res.text


@pytest_asyncio.fixture
async def admin_auth(client):
    return await login(client, "admin@test.io", ADMIN_PASSWORD)


@pytest_asyncio.fixture
async def eng_auth(client):
    return await login(client, "eng@test.io", ENGINEER_PASSWORD)


@pytest_asyncio.fixture
async def part(client, eng_auth, seed):
    """A part with one RFQ revision; returns {'part_id', 'revision_id'}."""
    res = await client.post(
        "/api/v1/parts",
        json={
            "project_id": seed["project_id"],
            "part_number": "P-100",
            "name": "Housing",
            "part_type": "sub_assembly",
            "data_classification": "confidential",
        },
        headers=eng_auth,
    )
    assert res.status_code in (200, 201), res.text
    part_id = res.json()["id"]

    res = await client.post(
        f"/api/v1/parts/{part_id}/revisions/rfq",
        json={"summary": "initial"},
        headers=eng_auth,
    )
    assert res.status_code == 200, res.text
    return {"part_id": part_id, "revision_id": res.json()["id"]}


async def freeze_revision(session_factory, revision_id: int):
    """Force a revision into frozen state directly in the DB."""
    from app.models.part import PartRevision
    from sqlalchemy import update

    async with session_factory() as s:
        await s.execute(
            update(PartRevision).where(PartRevision.id == revision_id).values(status="frozen")
        )
        await s.commit()


@pytest_asyncio.fixture
async def check_wf_standards(session_factory, seed):
    """Seed the ECN Umsetzung check-workflow templates + category mappings."""
    from app.services.wf_seed_service import seed_check_standards
    async with session_factory() as s:
        await seed_check_standards(s)
        await s.commit()


async def force_complete_check_workflows(session_factory, change_id: int):
    """Mark every check-WF instance of a change's ECN revisions completed —
    for tests that need to pass the ready-to-go guard without driving tasks."""
    from datetime import datetime
    from sqlalchemy import select, update
    from app.models.change import ChangeImpactedItem
    from app.models.workflow import WfInstance
    async with session_factory() as s:
        rev_ids = [r for (r,) in await s.execute(
            select(ChangeImpactedItem.resulting_revision_id).where(
                ChangeImpactedItem.change_id == change_id,
                ChangeImpactedItem.resulting_revision_id.is_not(None)))]
        if rev_ids:
            await s.execute(update(WfInstance)
                            .where(WfInstance.part_revision_id.in_(rev_ids))
                            .values(status="completed",
                                    completed_at=datetime.utcnow()))
        await s.commit()
