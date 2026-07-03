# backend/tests/test_change_kickoff.py
import pytest
from datetime import datetime
from sqlalchemy import select, update

pytestmark = pytest.mark.asyncio


async def _approved_change(session_factory, seed, part_id):
    """Change with one lead impacted item, forced to approved with gates yes,
    and impact already confirmed (Task 18 soft-gate) so kickoff tests exercise
    what they intend to exercise, not the impact-confirmation guard."""
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem
    from app.models.change_cost import ChangeGate
    async with session_factory() as s:
        change = await ChangeService.create_change(
            s, project_id=seed["project_id"], title="kickoff",
            change_type="tooling", raised_by=seed["engineer_id"],
            lead_id=seed["engineer_id"])
        s.add(ChangeImpactedItem(change_id=change.id, part_id=part_id,
                                 is_lead=True, created_by=seed["engineer_id"]))
        change.status = "approved"
        change.impact_confirmed_by = seed["engineer_id"]
        change.impact_confirmed_at = datetime.utcnow()
        await s.execute(update(ChangeGate).where(ChangeGate.change_id == change.id)
                        .values(decision="yes"))
        await s.commit()
        return change.id


async def test_kickoff_spawns_backlinked_revision_and_check_wf(
        session_factory, seed, part, check_wf_standards):
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem
    from app.models.part import PartRevision
    from app.models.workflow import WfInstance, WfTemplate

    cid = await _approved_change(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_implementation",
                                       seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        assert item.resulting_revision_id is not None
        rev = await s.get(PartRevision, item.resulting_revision_id)
        assert rev.originating_change_id == cid
        inst = (await s.execute(select(WfInstance).where(
            WfInstance.part_revision_id == rev.id))).scalar_one()
        assert inst.status == "active"
        tmpl = await s.get(WfTemplate, inst.template_id)
        # part fixture is item_category 'article'
        assert tmpl.name == "ECN Umsetzung (Artikel)"


async def test_kickoff_blocked_without_check_mapping(session_factory, seed, part):
    from app.services.change_service import ChangeService, ChangeError

    cid = await _approved_change(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        with pytest.raises(ChangeError, match="check-workflow"):
            await ChangeService.transition(s, change, "in_implementation",
                                           seed["engineer_id"])


async def test_kickoff_idempotent_no_duplicate_instances(
        session_factory, seed, part, check_wf_standards):
    from app.services.change_service import ChangeService
    from app.models.change import ChangeImpactedItem
    from app.models.workflow import WfInstance
    from sqlalchemy import func

    cid = await _approved_change(session_factory, seed, part["part_id"])
    async with session_factory() as s:
        change = await ChangeService.get_change(s, cid)
        await ChangeService.transition(s, change, "in_implementation",
                                       seed["engineer_id"])
        # calling spawn again (e.g. resume from on_hold) must not duplicate
        await ChangeService.spawn_ecn_revisions(s, change, seed["engineer_id"])
        await s.commit()

    async with session_factory() as s:
        item = (await s.execute(select(ChangeImpactedItem).where(
            ChangeImpactedItem.change_id == cid))).scalar_one()
        n = (await s.execute(select(func.count()).select_from(WfInstance).where(
            WfInstance.part_revision_id == item.resulting_revision_id))).scalar()
        assert n == 1
