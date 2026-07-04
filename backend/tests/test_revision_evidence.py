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
    from app.models.part import PartRevision, RevisionChangelog
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "part_revision",
            AuditLog.entity_id == part["revision_id"],
            AuditLog.action == "no_geometry_change_signed"))).scalars().all()
        rev = await s.get(PartRevision, part["revision_id"])
        changelog_rows = (await s.execute(select(RevisionChangelog).where(
            RevisionChangelog.revision_id == part["revision_id"],
            RevisionChangelog.action == "no_geometry_change_signed"))).scalars().all()
    assert len(rows) == 1
    assert rev.no_geometry_change_at is not None
    assert rev.no_geometry_change_reason == "label text change only"
    assert len(changelog_rows) == 1

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


async def test_sign_404_on_unknown_or_mismatched_revision(client, eng_auth, part, seed):
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/999999/no-geometry-change",
        json={"reason": "x"}, headers=eng_auth)
    assert res.status_code == 404

    # mismatched part: create a second part, then sign part A's revision via part B's id
    res2 = await client.post(
        "/api/v1/parts",
        json={
            "project_id": seed["project_id"],
            "part_number": "P-404",
            "name": "Bracket",
            "part_type": "sub_assembly",
            "data_classification": "confidential",
        },
        headers=eng_auth,
    )
    assert res2.status_code in (200, 201), res2.text
    other_part_id = res2.json()["id"]

    res3 = await client.post(
        f"/api/v1/parts/{other_part_id}/revisions/rfq",
        json={"summary": "initial"},
        headers=eng_auth,
    )
    assert res3.status_code == 200, res3.text

    res4 = await client.post(
        f"/api/v1/parts/{other_part_id}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "x"}, headers=eng_auth)
    assert res4.status_code == 404


async def test_sign_audit_correlates_to_originating_change(
        client, eng_auth, part, seed, session_factory):
    from app.models.part import PartRevision
    from app.models.entities import AuditLog
    from app.services.change_service import ChangeService
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=seed["project_id"], title="corr", change_type="tooling",
            raised_by=seed["engineer_id"])
        number = change.change_number
        rev = await s.get(PartRevision, part["revision_id"])
        rev.originating_change_id = change.id
        await s.commit()
    res = await client.post(
        f"/api/v1/parts/{part['part_id']}/revisions/{part['revision_id']}/no-geometry-change",
        json={"reason": "doc only"}, headers=eng_auth)
    assert res.status_code == 200, res.text
    async with session_factory() as s:
        row = (await s.execute(select(AuditLog).where(
            AuditLog.entity_type == "part_revision",
            AuditLog.action == "no_geometry_change_signed",
            AuditLog.entity_id == part["revision_id"]))).scalar_one()
        assert row.correlation_id == number
