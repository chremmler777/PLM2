"""GET /workflow-templates/departments: active roles by default, retired ones
only on request (admin screens)."""
import pytest

from app.models.workflow import Department

pytestmark = pytest.mark.asyncio


async def test_departments_active_only_unless_retired_asked(client, admin_auth, session_factory):
    async with session_factory() as s:
        s.add_all([Department(name="Quality", flow_type="action", is_active=True),
                   Department(name="Developer", flow_type="action", is_active=False)])
        await s.commit()
    res = await client.get("/api/v1/workflow-templates/departments", headers=admin_auth)
    assert res.status_code == 200, res.text
    names = {d["name"] for d in res.json()}
    assert "Quality" in names and "Developer" not in names
    res = await client.get("/api/v1/workflow-templates/departments?include_retired=1",
                           headers=admin_auth)
    by_name = {d["name"]: d for d in res.json()}
    assert by_name["Developer"]["is_active"] is False
    assert "Quality" in by_name


async def test_seed_creates_retired_roles_retired():
    """main.seed_test_data's list: the roles migration 043 retired are seeded
    inactive, and the renamed seed-era names are not seeded at all."""
    import inspect
    import app.main as main
    src = inspect.getsource(main)
    for name in ("Logistics", "Production", "Purchasing", "Production control",
                 "Operations Manager", "Developer"):
        assert f'("{name}", ' in src
        line = next(l for l in src.splitlines() if l.strip().startswith(f'("{name}", '))
        assert line.rstrip().endswith("False),"), line
    for old in ("R&D", "Tooling Engineer", "Planner/Scheduler"):
        assert f'("{old}", ' not in src
