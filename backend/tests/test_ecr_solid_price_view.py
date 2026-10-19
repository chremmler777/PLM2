"""Click-through R38 (R23/R24): /auth/me says whether the viewer reads any
prices, so the P&L link and page do not show zeros to someone who reads none:
'all' (admin, PM, Sales, Management), 'led' (only the changes they lead),
'none'."""
import pytest

from app.models.change import ChangeRequest

pytestmark = pytest.mark.asyncio


async def _view(client, auth):
    res = await client.get("/api/v1/auth/me", headers=auth)
    assert res.status_code == 200, res.text
    return res.json()["price_view"]


async def test_admin_reads_all(client, admin_auth):
    assert await _view(client, admin_auth) == "all"


async def test_engineer_without_price_rights_reads_none(client, eng_auth):
    assert await _view(client, eng_auth) == "none"


async def test_engineer_reads_the_changes_he_leads(client, eng_auth, seed, session_factory):
    async with session_factory() as s:
        s.add(ChangeRequest(
            change_number="C-PV-1", title="led", reason="r",
            change_type="physical_part", project_id=seed["project_id"],
            raised_by=seed["admin_id"], lead_id=seed["engineer_id"],
            status="scoping"))
        await s.commit()
    assert await _view(client, eng_auth) == "led"
