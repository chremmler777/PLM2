import pytest
pytestmark = pytest.mark.asyncio

async def test_contacts_falls_back_to_local_users(client, admin_auth, seed):
    res = await client.get("/api/v1/contacts", headers=admin_auth)
    assert res.status_code == 200, res.text
    names = [c["name"] for c in res.json()]
    assert "Admin" in names  # seeded local user
    assert all("source" in c for c in res.json())
