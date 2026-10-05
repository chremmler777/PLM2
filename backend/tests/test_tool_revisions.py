"""GET /tool-revisions?tool_number=N — the products a tool makes, each with its
current customer and internal index. PDB snapshots these onto a sampling
booking as the change level the trial runs at."""
from datetime import datetime, timedelta

import pytest

from app.models.part import Part, PartRelation, PartRevision

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1)


async def _build(session_factory, seed):
    """Tool 3457 makes LH and RH; 3999 makes nothing."""
    uid = seed["engineer_id"]
    async with session_factory() as s:
        def part(number, category="article", **kw):
            p = Part(project_id=seed["project_id"], part_number=number, name=f"Name {number}",
                     part_type="internal_mfg" if category == "article" else "purchased",
                     item_category=category, created_by=uid, **kw)
            s.add(p)
            return p
        tool = part("3457", "tool")
        lone = part("3999", "tool")
        lh = part("10-3457-001-0", customer_part_number="3CR.919.491.A")
        rh = part("10-3457-002-0", customer_part_number="3CR.919.492.A")
        await s.flush()

        def rev(p, name, minutes, *, source, phase="review", status="approved", **kw):
            s.add(PartRevision(part_id=p.id, revision_name=name, phase=phase, status=status, source=source,
                               created_by=uid, created_at=T0 + timedelta(minutes=minutes), **kw))
        # LH: E3 superseded by an approved E4; a later E5 still in draft does not count.
        rev(lh, "E3", 1, source="customer", customer_index="E03")
        rev(lh, "E4", 2, source="customer", customer_index="E04")
        rev(lh, "E5", 3, source="customer", status="draft", customer_index="E05")
        rev(lh, "E4.1", 4, source="internal")
        rev(lh, "E4.2", 5, source="internal", status="cancelled")
        # RH: legacy import major without a customer index; only a draft internal one.
        rev(rh, "1", 1, source="import", phase="official")
        rev(rh, "1.1", 2, source="internal", phase="official", status="draft")
        s.add_all([
            PartRelation(from_part_id=tool.id, to_part_id=lh.id, relation_type="produces", created_by=uid),
            PartRelation(from_part_id=tool.id, to_part_id=rh.id, relation_type="produces", created_by=uid),
        ])
        await s.commit()
        return {"tool": tool.id, "lone": lone.id}


async def test_products_with_current_customer_and_internal_index(client, admin_auth, seed, session_factory):
    await _build(session_factory, seed)
    res = await client.get("/api/v1/tool-revisions", params={"tool_number": "3457"}, headers=admin_auth)
    assert res.status_code == 200, res.text
    assert res.json() == [
        {"part_number": "10-3457-001-0", "name": "Name 10-3457-001-0", "customer_part_number": "3CR.919.491.A",
         "customer_index": "E04", "internal_index": "E4.1"},
        {"part_number": "10-3457-002-0", "name": "Name 10-3457-002-0", "customer_part_number": "3CR.919.492.A",
         "customer_index": "1", "internal_index": "1.1"},
    ]


async def test_tool_without_products_is_an_empty_list(client, admin_auth, seed, session_factory):
    await _build(session_factory, seed)
    res = await client.get("/api/v1/tool-revisions", params={"tool_number": "3999"}, headers=admin_auth)
    assert res.status_code == 200
    assert res.json() == []


async def test_unknown_tool_is_404(client, admin_auth, seed):
    res = await client.get("/api/v1/tool-revisions", params={"tool_number": "0000"}, headers=admin_auth)
    assert res.status_code == 404


async def test_requires_auth(client, seed):
    res = await client.get("/api/v1/tool-revisions", params={"tool_number": "3457"})
    assert res.status_code == 401


async def test_service_token_reads(client, seed, session_factory, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "plm2_service_token", "svc-test-token")
    await _build(session_factory, seed)
    res = await client.get("/api/v1/tool-revisions", params={"tool_number": "3457"},
                           headers={"Authorization": "Bearer svc-test-token"})
    assert res.status_code == 200, res.text
    assert len(res.json()) == 2
