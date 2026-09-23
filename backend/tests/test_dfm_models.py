"""DFM archive tables: a topic on a tool, entries in three columns, files per
entry, superseding chain. Pure model round-trip through the session."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload


async def _tool(session_factory, seed):
    from app.models.part import Part
    async with session_factory() as s:
        tool = Part(project_id=seed["project_id"], part_number="199403", name="ISOFIX Cover",
                    part_type="purchased", item_category="tool", created_by=seed["engineer_id"])
        s.add(tool)
        await s.commit()
        return tool.id


async def test_topic_entries_files_roundtrip(session_factory, seed):
    from app.models.dfm import DfmTopic, DfmEntry, DfmEntryFile, DFM_PARTIES, DFM_TOPIC_OPEN
    tool_id = await _tool(session_factory, seed)
    assert DFM_PARTIES == ("toolmaker", "ktx", "tier1")

    async with session_factory() as s:
        topic = DfmTopic(tool_part_id=tool_id, title="Gate position", opened_by=seed["engineer_id"])
        s.add(topic)
        await s.flush()
        assert topic.status == DFM_TOPIC_OPEN
        first = DfmEntry(topic_id=topic.id, party="ktx", addressed_to=["toolmaker", "tier1"],
                         note="DFM request rev A", recorded_by=seed["engineer_id"], sent_at=date(2026, 9, 24))
        s.add(first)
        await s.flush()
        s.add(DfmEntryFile(entry_id=first.id, original_filename="dfm_request_A.pdf", saved_filename="abc.pdf",
                           file_size=10, content_type="application/pdf", uploaded_by=seed["engineer_id"]))
        update = DfmEntry(topic_id=topic.id, party="ktx", addressed_to=["toolmaker"], note="rev B",
                          supersedes_id=first.id, recorded_by=seed["engineer_id"])
        s.add(update)
        await s.commit()
        topic_id = topic.id

    async with session_factory() as s:
        topic = (await s.execute(select(DfmTopic).where(DfmTopic.id == topic_id)
                                 .options(selectinload(DfmTopic.entries).selectinload(DfmEntry.files)))).scalar_one()
        assert topic.tool_part_id == tool_id
        assert [e.note for e in topic.entries] == ["DFM request rev A", "rev B"]
        assert topic.entries[0].addressed_to == ["toolmaker", "tier1"]
        assert topic.entries[0].sent_at == date(2026, 9, 24)
        assert topic.entries[0].files[0].original_filename == "dfm_request_A.pdf"
        assert topic.entries[1].supersedes_id == topic.entries[0].id
        assert topic.closed_at is None
