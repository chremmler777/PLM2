import pytest
from sqlalchemy import select, update

from tests.conftest import force_complete_check_workflows
from tests.test_change_kickoff import _approved_change

pytestmark = pytest.mark.asyncio


async def _kickoff(session_factory, seed, part_id):
    from app.services.change_service import ChangeService
    cid = await _approved_change(session_factory, seed, part_id)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_implementation",
                                       seed["engineer_id"])
        await s.commit()
    return cid


async def test_progress_not_ready_until_instances_complete(
        session_factory, seed, part, check_wf_standards, client, eng_auth):
    from app.services.change_service import ChangeService

    cid = await _kickoff(session_factory, seed, part["part_id"])

    res = await client.get(f"/api/v1/changes/{cid}/implementation",
                           headers=eng_auth)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ready_to_go"] is False
    assert len(data["items"]) == 1
    entry = data["items"][0]
    assert entry["instance_status"] == "active"
    assert entry["total_stages"] == 4
    assert entry["ready"] is False

    await force_complete_check_workflows(session_factory, cid)
    data = (await client.get(f"/api/v1/changes/{cid}/implementation",
                             headers=eng_auth)).json()
    assert data["ready_to_go"] is True
    assert data["items"][0]["ready"] is True


async def test_release_guarded_by_ready_to_go(
        session_factory, seed, part, check_wf_standards):
    from app.services.change_service import ChangeService, ChangeError

    cid = await _kickoff(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_validation",
                                       seed["engineer_id"])
        with pytest.raises(ChangeError, match="ready"):
            await ChangeService.transition(s, change, "released",
                                           seed["engineer_id"])
        await s.commit()

    await force_complete_check_workflows(session_factory, cid)
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "released",
                                       seed["engineer_id"])
        await s.commit()
        assert change.status == "released"
