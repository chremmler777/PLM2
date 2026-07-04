import pytest

pytestmark = pytest.mark.asyncio


async def test_audit_action_column_fits_long_actions(session_factory):
    from app.models.entities import AuditLog
    assert AuditLog.action.type.length >= 64, (
        "AuditLog.action must fit actions like 'customer_response_recorded' "
        "(26 chars) with headroom")


async def test_long_action_roundtrips(session_factory, seed):
    from app.services.audit_service import AuditService
    from app.models.entities import AuditLog
    from sqlalchemy import select

    long_action = "customer_response_recorded_with_negotiation"  # 43 chars
    async with session_factory() as s:
        await AuditService.record(
            s, entity_type="change", entity_id=999999, action=long_action,
            user_id=seed["engineer_id"], correlation_id="CR-TEST-WIDTH")
        await s.commit()
    async with session_factory() as s:
        row = (await s.execute(select(AuditLog).where(
            AuditLog.correlation_id == "CR-TEST-WIDTH"))).scalar_one()
        assert row.action == long_action
