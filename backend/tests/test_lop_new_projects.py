"""Project LOP: every project created through the API gets the LOP; older ones stay out."""
import pytest

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/lop"


async def _plant_id(client, admin_auth):
    return (await client.get("/api/v1/plants", headers=admin_auth)).json()[0]["id"]


async def _create(client, admin_auth, code):
    r = await client.post("/api/v1/plants/projects", headers=admin_auth,
                          json={"name": f"New {code}", "code": code,
                                "plant_id": await _plant_id(client, admin_auth)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_new_project_gets_the_lop(client, admin_auth):
    pid = await _create(client, admin_auth, "9001")
    r = await client.get(f"{BASE}/projects/{pid}?view=open", headers=admin_auth)
    assert r.status_code == 200, r.text
    assert r.json()["project"]["lop_enabled"] is True


async def test_older_project_outside_the_list_has_none(client, admin_auth, plain_project):
    r = await client.get(f"{BASE}/projects/{plain_project.id}?view=open", headers=admin_auth)
    assert r.status_code == 404


async def test_project_without_sep_works_with_tasks_only(client, admin_auth):
    pid = await _create(client, admin_auth, "9002")      # no SEP gates exist
    r = await client.get(f"{BASE}/projects/{pid}?view=open", headers=admin_auth)
    assert r.status_code == 200 and r.json()["lines"] == []
    r = await client.post(f"{BASE}/projects/{pid}/lines", headers=admin_auth,
                          json={"title": "First task"})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "task"
