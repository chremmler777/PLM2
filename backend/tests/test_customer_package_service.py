"""Package receive: only changed parts get a new major, files land on it,
the assembly BOM is copied forward, nothing is stored on error."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models.part import Part, PartRevision, RevisionFile
from app.services.bom_tree_service import BomTreeService
from app.services.customer_package_service import CustomerPackageService, PackageError, PackageRow
from app.services.part_service import PartService, RevisionService


async def _setup(session_factory, seed):
    """Assembly TOP (3CR.807.425, E1 index A) with children SUB (3CR.807.531, E1 index A)
    and CLAMP (no customer number, E1 index A). Returns ids."""
    async with session_factory() as s:
        admin = seed["admin_id"]
        top = await PartService.create_part(s, project_id=seed["project_id"], part_number="1994-100", name="Top",
                                            part_type="internal_mfg", created_by=admin)
        sub = await PartService.create_part(s, project_id=seed["project_id"], part_number="1994-110", name="Sub",
                                            part_type="internal_mfg", created_by=admin)
        clamp = await PartService.create_part(s, project_id=seed["project_id"], part_number="1994-120", name="Clamp",
                                              part_type="purchased", created_by=admin)
        top.customer_part_number = "3CR.807.425"
        sub.customer_part_number = "3CR.807.531"
        ids = {}
        for p in (top, sub, clamp):
            r = await RevisionService.receive_customer_data(s, p.id, "review", date(2026, 9, 1), customer_index="A", created_by=admin)
            ids[p.part_number] = (p.id, r.id)
        from app.models.part import PartBOMItem
        s.add(PartBOMItem(revision_id=ids["1994-100"][1], child_part_id=sub.id, item_number="10", name="Sub", quantity=1, unit="pcs", position=1, created_by=admin))
        s.add(PartBOMItem(revision_id=ids["1994-100"][1], child_part_id=clamp.id, item_number="20", name="Clamp", quantity=4, unit="pcs", position=2, created_by=admin))
        await s.commit()
        return ids


async def test_preview_matches_and_decides(session_factory, seed):
    ids = await _setup(session_factory, seed)
    async with session_factory() as s:
        rows = await CustomerPackageService.preview(
            s, ids["1994-100"][0], "review", date(2026, 9, 10), "B",
            ["3CR807425B_top.stp", "3CR807531A_sub.stp", "1994-120 clamp.stp", "stranger.stp"])
    by = {r.filename: r for r in rows}
    assert by["3CR807425B_top.stp"].action == "new_major" and by["3CR807425B_top.stp"].customer_index == "B"
    assert by["3CR807425B_top.stp"].suggested_name == "E2" and by["3CR807425B_top.stp"].current_revision == "E1"
    assert by["3CR807531A_sub.stp"].action == "unchanged" and by["3CR807531A_sub.stp"].customer_index == "A"
    # no index in the clamp filename -> package index B -> differs from A -> new major
    assert by["1994-120 clamp.stp"].action == "new_major" and by["1994-120 clamp.stp"].customer_index == "B"
    assert by["stranger.stp"].action == "unmatched" and by["stranger.stp"].part_id is None


async def test_confirm_creates_only_changed_majors_and_copies_bom(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = await _setup(session_factory, seed)
    top_id, sub_id, clamp_id = ids["1994-100"][0], ids["1994-110"][0], ids["1994-120"][0]
    rows = [
        PackageRow(filename="top.stp", part_id=top_id, customer_index="B", action="new_major", major=None),
        PackageRow(filename="sub.stp", part_id=sub_id, customer_index="A", action="unchanged"),
        PackageRow(filename="clamp.stp", part_id=clamp_id, customer_index="A", action="unchanged"),
        PackageRow(filename="stranger.stp", part_id=None, action="unmatched"),
    ]
    files = {n: (b"ISO-10303-21;" + n.encode(), "model/step") for n in ("top.stp", "sub.stp", "clamp.stp", "stranger.stp")}
    async with session_factory() as s:
        out = await CustomerPackageService.confirm(s, top_id, "review", date(2026, 9, 10), rows, files, seed["admin_id"])
        await s.commit()
    assert [c["revision_name"] for c in out["created"]] == ["E2"]
    assert {k["part_id"] for k in out["kept"]} == {sub_id, clamp_id}
    assert out["skipped"] == ["stranger.stp"]
    async with session_factory() as s:
        top = await s.get(Part, top_id)
        e2 = await s.get(PartRevision, top.active_revision_id)
        assert e2.revision_name == "E2" and e2.customer_index == "B"
        files_on_e2 = (await s.execute(select(RevisionFile).where(RevisionFile.revision_id == e2.id))).scalars().all()
        assert [f.filename for f in files_on_e2] == ["top.stp"]
        sub = await s.get(Part, sub_id)
        assert sub.active_revision_id == ids["1994-110"][1]  # untouched
        tree = await BomTreeService.tree(s, top_id)
        assert tree["revision_name"] == "E2" and len(tree["lines"]) == 2
        assert (await s.execute(select(RevisionFile).where(RevisionFile.filename == "sub.stp"))).scalar_one_or_none() is None


async def test_confirm_with_chosen_major_and_error_row(session_factory, seed, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = await _setup(session_factory, seed)
    top_id = ids["1994-100"][0]
    async with session_factory() as s:
        out = await CustomerPackageService.confirm(
            s, top_id, "review", date(2026, 9, 10),
            [PackageRow(filename="top.stp", part_id=top_id, customer_index="C", action="new_major", major=4)],
            {"top.stp": (b"x", None)}, seed["admin_id"])
        await s.commit()
    assert out["created"][0]["revision_name"] == "E4"
    async with session_factory() as s:
        with pytest.raises(PackageError) as ei:
            await CustomerPackageService.confirm(
                s, top_id, "review", date(2026, 9, 11),
                [PackageRow(filename="top.stp", part_id=top_id, customer_index="D", action="new_major", major=3),
                 PackageRow(filename="bad.exe", part_id=top_id, customer_index="D", action="new_major")],
                {"top.stp": (b"x", None), "bad.exe": (b"MZ", None)}, seed["admin_id"])
        errors = {r.filename: r.error for r in ei.value.rows if r.action == "error"}
        assert "above E4" in errors["top.stp"] and "Unsupported" in errors["bad.exe"]
        await s.rollback()
    async with session_factory() as s:
        names = (await s.execute(select(PartRevision.revision_name).where(PartRevision.part_id == top_id))).scalars().all()
        assert sorted(names) == ["E1", "E4"]
