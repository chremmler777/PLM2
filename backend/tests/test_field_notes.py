"""Field notes: one thread per (part, field_key), append-only comments, a flag,
and a changelog entry on the part for every comment and flag change."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.field_note import FieldNote
from app.models.part import Part, RevisionChangelog
from app.services.field_note_service import FieldNoteError, FieldNoteService

pytestmark = pytest.mark.asyncio


async def _mk(session_factory, seed, number="A-1", category="article"):
    async with session_factory() as s:
        p = Part(project_id=seed["project_id"], part_number=number, name=number,
                 part_type="internal_mfg", item_category=category, created_by=seed["engineer_id"])
        s.add(p)
        await s.commit()
        return p.id


async def _log(session_factory, part_id):
    async with session_factory() as s:
        return (await s.execute(select(RevisionChangelog).where(RevisionChangelog.part_id == part_id)
                                .order_by(RevisionChangelog.id))).scalars().all()


async def test_comments_share_one_note_per_field_and_append(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        await FieldNoteService.add_comment(s, part, "part.material", "Resin to be nominated", seed["engineer_id"])
        await FieldNoteService.add_comment(s, part, "part.material", "  Virgin grade asked  ", seed["engineer_id"])
        await FieldNoteService.add_comment(s, part, "part.name", "Drawing says Latch Cover 40", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        notes = (await s.execute(select(FieldNote).order_by(FieldNote.field_key))).scalars().all()
        assert [n.field_key for n in notes] == ["part.material", "part.name"]
        assert [c.body for c in notes[0].comments] == ["Resin to be nominated", "Virgin grade asked"]
    log = await _log(session_factory, pid)
    assert [e.action for e in log] == ["field_comment_added"] * 3
    assert log[0].field_name == "part.material"
    assert log[1].new_value == "Virgin grade asked"


async def test_blank_or_too_long_comment_is_refused(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.add_comment(s, part, "part.material", "   ", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.add_comment(s, part, "part.material", "x" * 4001, seed["engineer_id"])


@pytest.mark.parametrize("key", ["cavities", "Tool.cavities", "tool.", ".x", "tool.cav-ities", "a.b.c", ""])
async def test_malformed_keys_are_refused(session_factory, seed, key):
    pid = await _mk(session_factory, seed, category="tool")
    async with session_factory() as s:
        part = await s.get(Part, pid)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.add_comment(s, part, key, "x", seed["engineer_id"])


async def test_key_prefix_must_fit_the_item_category(session_factory, seed):
    article = await _mk(session_factory, seed, "A-1", "article")
    tool = await _mk(session_factory, seed, "T-1", "tool")
    async with session_factory() as s:
        a, t = await s.get(Part, article), await s.get(Part, tool)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, a, "tool.cavities", "open", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, a, "dfm.status", "open", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, t, "paint.colour", "open", seed["engineer_id"])
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, t, "revision.level", "open", seed["engineer_id"])
        # part.* applies to both
        assert await FieldNoteService.set_flag(s, t, "part.name", "open", seed["engineer_id"]) is not None
        assert await FieldNoteService.set_flag(s, a, "part.name", "open", seed["engineer_id"]) is not None


async def test_flag_transitions_are_logged_and_same_value_is_a_no_op(session_factory, seed):
    pid = await _mk(session_factory, seed, category="tool")
    uid = seed["engineer_id"]
    async with session_factory() as s:
        part = await s.get(Part, pid)
        note = await FieldNoteService.set_flag(s, part, "tool.cavities", "open", uid)
        assert (note.flag_status, note.flag_set_by) == ("open", uid)
        assert note.flag_set_at is not None
        await FieldNoteService.set_flag(s, part, "tool.cavities", "open", uid)  # same: nothing logged
        await FieldNoteService.set_flag(s, part, "tool.cavities", "confirmed", uid)
        await FieldNoteService.set_flag(s, part, "tool.cavities", "rejected", uid)
        note = await FieldNoteService.set_flag(s, part, "tool.cavities", None, uid)
        assert (note.flag_status, note.flag_set_by, note.flag_set_at) == (None, None, None)
        with pytest.raises(FieldNoteError):
            await FieldNoteService.set_flag(s, part, "tool.cavities", "maybe", uid)
        await s.commit()
    log = await _log(session_factory, pid)
    assert [(e.action, e.old_value, e.new_value) for e in log] == [
        ("field_flag_set", None, "open"),
        ("field_flag_set", "open", "confirmed"),
        ("field_flag_set", "confirmed", "rejected"),
        ("field_flag_set", "rejected", None),
    ]


async def test_clearing_a_flag_that_never_existed_creates_nothing(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        assert await FieldNoteService.set_flag(s, part, "part.material", None, seed["engineer_id"]) is None
        await s.commit()
    async with session_factory() as s:
        assert (await s.execute(select(FieldNote))).scalars().all() == []
    assert await _log(session_factory, pid) == []


async def test_one_note_per_part_and_field(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        s.add_all([FieldNote(part_id=pid, field_key="part.name"), FieldNote(part_id=pid, field_key="part.name")])
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_serialized_thread_and_summary(session_factory, seed):
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        await FieldNoteService.add_comment(s, part, "part.material", "first", seed["engineer_id"])
        note = await FieldNoteService.set_flag(s, part, "part.material", "open", seed["engineer_id"])
        await FieldNoteService.add_comment(s, part, "part.material", "second", seed["admin_id"])
        names = await FieldNoteService.names_for(s, [note])
        summary = FieldNoteService.summary(note, names)
        thread = FieldNoteService.thread(note, names)
    assert summary["field_key"] == "part.material"
    assert summary["flag_status"] == "open"
    assert summary["flag_set_by_name"] == "Engineer"
    assert summary["comment_count"] == 2
    assert summary["last_comment"]["body"] == "second"
    assert summary["last_comment"]["author_name"] == "Admin"
    assert "comments" not in summary
    assert [c["body"] for c in thread["comments"]] == ["first", "second"]
    empty = FieldNoteService.empty_thread(pid, "part.name")
    assert empty == {"id": None, "part_id": pid, "field_key": "part.name", "flag_status": None,
                     "flag_set_by": None, "flag_set_by_name": None, "flag_set_at": None,
                     "created_at": None, "comment_count": 0, "last_comment": None, "comments": []}


async def test_list_for_project_only_returns_that_projects_parts(session_factory, seed):
    from app.models.entities import Project
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        home = await s.get(Project, seed["project_id"])
        other = Project(plant_id=home.plant_id, name="Other", code="other", status="active")
        s.add(other)
        await s.flush()
        foreign = Part(project_id=other.id, part_number="F-1", name="F", part_type="internal_mfg",
                       item_category="article", created_by=seed["engineer_id"])
        s.add(foreign)
        await s.flush()
        await FieldNoteService.add_comment(s, await s.get(Part, pid), "part.name", "mine", seed["engineer_id"])
        await FieldNoteService.add_comment(s, foreign, "part.name", "not mine", seed["engineer_id"])
        await s.commit()
        notes = await FieldNoteService.list_for_project(s, seed["project_id"])
    assert [n.part_id for n in notes] == [pid]


async def test_concurrent_first_write_reuses_the_note_the_other_request_created(session_factory, seed, monkeypatch):
    """Two requests both see no note and both insert: the loser hits the unique
    constraint and must re-fetch the winner's note instead of failing."""
    pid = await _mk(session_factory, seed)
    async with session_factory() as s:
        part = await s.get(Part, pid)
        await FieldNoteService.add_comment(s, part, "part.material", "first", seed["engineer_id"])
        await s.commit()
    real_get = FieldNoteService.get
    calls = {"n": 0}

    async def stale_get(session, part_id, field_key):
        calls["n"] += 1
        if calls["n"] == 1:
            return None          # the other request's insert is not visible yet
        return await real_get(session, part_id, field_key)

    monkeypatch.setattr(FieldNoteService, "get", staticmethod(stale_get))
    async with session_factory() as s:
        part = await s.get(Part, pid)
        await FieldNoteService.add_comment(s, part, "part.material", "second", seed["engineer_id"])
        await s.commit()
    async with session_factory() as s:
        notes = (await s.execute(select(FieldNote))).scalars().all()
        assert len(notes) == 1
        assert [c.body for c in notes[0].comments] == ["first", "second"]
