"""Duplicate template names must not break the legacy routing fallback
(roles audit issue 7): the 'ECM Assessment' lookup picks deterministically
(active first, then lowest id) instead of raising MultipleResultsFound."""
import pytest

from app.models.workflow import WfTemplate
from app.services.change_routing_service import default_assessment_template_id

pytestmark = pytest.mark.asyncio


async def _tmpl(s, seed, active=True, name="ECM Assessment"):
    t = WfTemplate(name=name, version=1, is_active=active, created_by=seed["admin_id"])
    s.add(t)
    await s.flush()
    return t.id


async def test_duplicates_pick_active_then_lowest_id(session_factory, seed):
    async with session_factory() as s:
        retired = await _tmpl(s, seed, active=False)
        first = await _tmpl(s, seed)
        await _tmpl(s, seed)
        await _tmpl(s, seed, name="Other")
        assert retired < first
        assert await default_assessment_template_id(s) == first


async def test_only_inactive_still_found(session_factory, seed):
    async with session_factory() as s:
        only = await _tmpl(s, seed, active=False)
        assert await default_assessment_template_id(s) == only


async def test_none_when_absent(session_factory, seed):
    async with session_factory() as s:
        await _tmpl(s, seed, name="Other")
        assert await default_assessment_template_id(s) is None
