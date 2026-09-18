"""store_revision_file: one code path for every file that lands on a revision."""
import hashlib
import os
from datetime import date

import pytest

from app.models.part import RevisionFile
from app.services.part_service import PartService, RevisionService
from app.services.revision_file_service import UnsupportedFile, store_revision_file


async def _rev(session_factory, seed):
    async with session_factory() as s:
        p = await PartService.create_part(s, project_id=seed["project_id"], part_number="P-RF",
                                          name="F", part_type="internal_mfg", created_by=seed["admin_id"])
        r = await RevisionService.receive_customer_data(s, p.id, "review", date(2026, 9, 1), created_by=seed["admin_id"])
        await s.commit()
        return r.id


async def test_store_writes_hashes_and_logs(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rid = await _rev(session_factory, seed)
    async with session_factory() as s:
        from app.models.part import PartRevision
        rev = await s.get(PartRevision, rid)
        f = await store_revision_file(s, rev, "3CR807425B.pdf", b"%PDF-1.4 hello", seed["admin_id"], file_type="drawing")
        await s.commit()
        assert f.file_type == "drawing" and f.mime_type == "application/pdf"
        assert f.file_hash == hashlib.sha256(b"%PDF-1.4 hello").hexdigest()
        assert os.path.isfile(f.file_path) and str(rid) in f.file_path
        assert (await s.get(RevisionFile, f.id)) is not None


async def test_store_rejects_unknown_extension(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rid = await _rev(session_factory, seed)
    async with session_factory() as s:
        from app.models.part import PartRevision
        rev = await s.get(PartRevision, rid)
        with pytest.raises(UnsupportedFile):
            await store_revision_file(s, rev, "x.exe", b"MZ", seed["admin_id"])


async def test_store_removes_the_written_file_when_the_database_step_fails(
        session_factory, seed, tmp_path, monkeypatch):
    """A file on disk without its row is invisible to the application and would
    leak on every retry, so the write is undone when anything after it fails."""
    monkeypatch.chdir(tmp_path)
    rid = await _rev(session_factory, seed)

    async def boom(*args, **kwargs):
        raise RuntimeError("changelog write failed")

    monkeypatch.setattr("app.services.revision_file_service.ChangelogService.log_action", boom)
    async with session_factory() as s:
        from app.models.part import PartRevision
        from sqlalchemy import select
        rev = await s.get(PartRevision, rid)
        with pytest.raises(RuntimeError, match="changelog write failed"):
            await store_revision_file(s, rev, "3CR807425B.pdf", b"%PDF-1.4 hello", seed["admin_id"])
        await s.rollback()
        assert os.listdir(tmp_path / "uploads" / "revisions" / str(rid)) == []
        rows = (await s.execute(select(RevisionFile).where(RevisionFile.revision_id == rid))).scalars().all()
        assert rows == []
