import pytest
from sqlalchemy import select

from tests.conftest import freeze_revision

pytestmark = pytest.mark.asyncio


async def test_sign_no_geometry_change(client, eng_auth, part, session_factory):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "label text change only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["no_geometry_change"] is True
    assert body["no_geometry_change_by"] is not None

    from app.models.entities import AuditLog
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "part_revision",
            AuditLog.entity_id == part["revision_id"],
            AuditLog.action == "no_geometry_change_signed"))).scalars().all()
    assert len(rows) == 1

    # double-sign is rejected
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "again"}, headers=eng_auth)
    assert res.status_code == 400


async def test_sign_requires_reason(client, eng_auth, part):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "  "}, headers=eng_auth)
    assert res.status_code == 400


async def test_sign_blocked_on_locked_revision(client, eng_auth, part, session_factory):
    await freeze_revision(session_factory, part["revision_id"])
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "doc change"}, headers=eng_auth)
    assert res.status_code == 409
