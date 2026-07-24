"""Equipment linkage reuses part_relations. 'serves' points equipment at every
tool it covers — the number only carries the lowest one, so coverage must be
readable without parsing numbers. 'feeds' points a tool at a downstream tool."""
import pytest

from app.services.equipment_numbering import EQUIPMENT_RELATION_TYPES

def test_vocabulary_is_pinned():
    assert EQUIPMENT_RELATION_TYPES == frozenset({"serves", "feeds"})


@pytest.mark.asyncio
async def test_serves_records_every_covered_tool(session_factory, seed):
    """A gauge numbered after the lowest tool still records both tools."""
    from sqlalchemy import select
    from app.models.part import Part, PartRelation

    async with session_factory() as s:
        tools = []
        for pn in ("3454", "3455"):
            t = Part(project_id=seed["project_id"], part_number=pn, name=f"tool {pn}",
                     part_type="purchased", item_category="tool",
                     created_by=seed["admin_id"])
            s.add(t)
            tools.append(t)
        gauge = Part(project_id=seed["project_id"], part_number="3454-40",
                     name="Rear Cladding gauge", part_type="purchased",
                     item_category="gauge", created_by=seed["admin_id"])
        s.add(gauge)
        await s.flush()
        for t in tools:
            s.add(PartRelation(from_part_id=gauge.id, to_part_id=t.id,
                               relation_type="serves", created_by=seed["admin_id"]))
        await s.commit()
        gauge_id = gauge.id

    async with session_factory() as s:
        rows = (await s.execute(
            select(PartRelation).where(PartRelation.from_part_id == gauge_id))
        ).scalars().all()
        assert {r.relation_type for r in rows} == {"serves"}
        assert len(rows) == 2
