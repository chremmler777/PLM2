import pytest
from sqlalchemy import select, update

pytestmark = pytest.mark.asyncio


async def test_record_chains_hashes(session_factory, seed):
    from app.models.entities import AuditLog
    from app.services.audit_service import AuditService
    async with session_factory() as s:
        e1 = await AuditService.record(
            s, entity_type="change", entity_id=1, action="created",
            user_id=seed["engineer_id"], correlation_id="CR-2026-0001")
        e2 = await AuditService.record(
            s, entity_type="change", entity_id=1, action="status_changed",
            user_id=seed["engineer_id"],
            old_values={"status": "captured"}, new_values={"status": "in_assessment"},
            correlation_id="CR-2026-0001")
        await s.commit()
    assert e1.entry_hash and len(e1.entry_hash) == 64
    assert e1.previous_hash is None
    assert e2.previous_hash == e1.entry_hash


async def test_change_actions_dual_write_audit(client, eng_auth, seed, session_factory):
    from app.models.entities import AuditLog
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "audit me",
        "change_type": "physical_part"}, headers=eng_auth)
    assert res.status_code in (200, 201), res.text
    number = res.json()["change_number"]
    async with session_factory() as s:
        rows = (await s.execute(
            select(AuditLog).where(AuditLog.correlation_id == number))).scalars().all()
    assert any(r.action == "created" for r in rows)
    assert all(r.entity_type == "change" for r in rows)


async def test_verify_chain_detects_tamper(session_factory, seed):
    from app.models.entities import AuditLog
    from app.services.audit_service import AuditService
    async with session_factory() as s:
        e1 = await AuditService.record(s, entity_type="change", entity_id=1,
                                       action="created", user_id=seed["engineer_id"])
        await AuditService.record(s, entity_type="change", entity_id=1,
                                  action="updated", user_id=seed["engineer_id"])
        await s.commit()
        assert (await AuditService.verify_chain(s))["valid"] is True
        await s.execute(update(AuditLog).where(AuditLog.id == e1.id)
                        .values(action="deleted"))
        await s.commit()
        result = await AuditService.verify_chain(s)
    assert result["valid"] is False
    assert result["first_broken_id"] == e1.id


async def test_audit_api_filters_by_correlation_id(client, eng_auth, seed):
    res = await client.post("/api/v1/changes", json={
        "project_id": seed["project_id"], "title": "api audit",
        "change_type": "physical_part"}, headers=eng_auth)
    number = res.json()["change_number"]
    listed = await client.get(f"/api/v1/audit?correlation_id={number}", headers=eng_auth)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body) >= 1
    assert all(e["correlation_id"] == number for e in body)

    verify = await client.get("/api/v1/audit/verify", headers=eng_auth)
    assert verify.json()["valid"] is True

    export = await client.get(f"/api/v1/audit/export?correlation_id={number}", headers=eng_auth)
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert number in export.text
