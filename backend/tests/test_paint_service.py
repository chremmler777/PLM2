"""PaintService: org-scoped catalog, part paint setup, overviews."""
import pytest
from sqlalchemy import select

from app.models.entities import Organization, Plant, Project, User
from app.models.part import RevisionChangelog
from app.services.paint_service import DuplicatePaint, PaintService
from app.services.part_service import PartService


async def _paint(s, org_id, admin_id, name, **fields):
    return await PaintService.create_paint(s, org_id=org_id, created_by=admin_id, name=name, **fields)


async def _part(s, seed, number, name="Cover"):
    return await PartService.create_part(
        s, project_id=seed["project_id"], part_number=number, name=name,
        part_type="internal_mfg", created_by=seed["admin_id"])


async def _second_org(s):
    org = Organization(name="Other Org", code="other-org", is_active=True)
    s.add(org)
    await s.flush()
    return org


# --- catalog ---------------------------------------------------------------

async def test_create_paint_and_duplicate_name(session_factory, seed):
    async with session_factory() as s:
        p = await _paint(s, seed["org_id"], seed["admin_id"], "RAL 9005 base",
                         paint_type="basecoat", colour_code="RAL 9005")
        await s.commit()
        assert p.id and p.organization_id == seed["org_id"] and p.is_active

        with pytest.raises(DuplicatePaint):
            await _paint(s, seed["org_id"], seed["admin_id"], "RAL 9005 base")


async def test_same_name_allowed_in_other_org(session_factory, seed):
    async with session_factory() as s:
        other = await _second_org(s)
        await _paint(s, seed["org_id"], seed["admin_id"], "Shared name")
        await _paint(s, other.id, seed["admin_id"], "Shared name")
        await s.commit()


async def test_list_paints_query_and_active_only(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        await _paint(s, org, admin, "RAL 9005 base", colour_code="RAL 9005")
        await _paint(s, org, admin, "2K clear", paint_type="clearcoat", colour_code="CLR-1")
        gone = await _paint(s, org, admin, "Old primer", paint_type="primer")
        other = await _second_org(s)
        await _paint(s, other.id, admin, "Foreign paint")
        await PaintService.update_paint(s, org_id=org, paint_id=gone.id, is_active=False)
        await s.commit()

        names = [p.name for p in await PaintService.list_paints(s, org_id=org)]
        assert names == ["2K clear", "RAL 9005 base"]  # active only, foreign excluded

        with_inactive = [p.name for p in await PaintService.list_paints(s, org_id=org, active_only=False)]
        assert "Old primer" in with_inactive

        by_name = await PaintService.list_paints(s, org_id=org, q="clear")
        assert [p.name for p in by_name] == ["2K clear"]

        by_code = await PaintService.list_paints(s, org_id=org, q="ral 9005")
        assert [p.name for p in by_code] == ["RAL 9005 base"]


async def test_update_paint_rename_clash_and_org_scope(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        a = await _paint(s, org, admin, "Paint A")
        b = await _paint(s, org, admin, "Paint B")
        other = await _second_org(s)
        foreign = await _paint(s, other.id, admin, "Foreign")
        await s.commit()

        updated = await PaintService.update_paint(s, org_id=org, paint_id=b.id,
                                                  name="Paint B2", colour_hex="#101010")
        assert updated.name == "Paint B2" and updated.colour_hex == "#101010"

        with pytest.raises(DuplicatePaint):
            await PaintService.update_paint(s, org_id=org, paint_id=b.id, name="Paint A")

        with pytest.raises(ValueError):
            await PaintService.update_paint(s, org_id=org, paint_id=foreign.id, name="Nope")
        assert a.name == "Paint A"


# --- part setup ------------------------------------------------------------

async def test_get_setup_empty(session_factory, seed):
    async with session_factory() as s:
        part = await _part(s, seed, "PS-EMPTY")
        await s.commit()
        assert await PaintService.get_setup(s, part.id) == {
            "paint_required": False, "process": None, "notes": None, "layers": []}


async def test_put_setup_round_trip_reorder_and_changelog(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        part = await _part(s, seed, "PS-1")
        base = await _paint(s, org, admin, "RAL 9005 base", paint_type="basecoat", colour_code="RAL 9005")
        clear = await _paint(s, org, admin, "2K clear", paint_type="clearcoat")
        await s.flush()

        out = await PaintService.put_setup(
            s, part_id=part.id, org_id=org, paint_required=True, process="spray", notes="outer only",
            layers=[{"paint_id": base.id, "area": "A-side", "notes": "2 passes"},
                    {"paint_id": clear.id, "area": None, "notes": None}],
            updated_by=admin)
        await s.commit()

        assert out["paint_required"] is True and out["process"] == "spray" and out["notes"] == "outer only"
        assert [ly["layer_order"] for ly in out["layers"]] == [1, 2]
        assert [ly["paint"]["name"] for ly in out["layers"]] == ["RAL 9005 base", "2K clear"]
        assert out["layers"][0]["area"] == "A-side" and out["layers"][0]["notes"] == "2 passes"
        assert out["layers"][0]["paint"]["colour_code"] == "RAL 9005"
        assert out["layers"][0]["paint"]["paint_type"] == "basecoat"
        assert out["layers"][0]["paint"]["is_active"] is True
        assert set(out["layers"][0]["paint"]) == {
            "id", "name", "paint_type", "colour_code", "colour_name", "colour_hex",
            "supplier_id", "supplier_text", "spec_reference", "notes", "is_active"}
        pid, base_id, clear_id = part.id, base.id, clear.id

    async with session_factory() as s:
        assert await PaintService.get_setup(s, pid) == out

        rows = (await s.execute(select(RevisionChangelog).where(
            RevisionChangelog.part_id == pid,
            RevisionChangelog.action == "paint_updated"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].action_description == (
            "Paint required · spray · RAL 9005 base (basecoat) → 2K clear (clearcoat)")
        assert rows[0].performed_by == seed["admin_id"]

        # second put: reversed order, renumbered 1..n, old layers replaced
        again = await PaintService.put_setup(
            s, part_id=pid, org_id=seed["org_id"], paint_required=True, process="spray", notes=None,
            layers=[{"paint_id": clear_id}, {"paint_id": base_id}], updated_by=seed["admin_id"])
        await s.commit()
        assert [(ly["layer_order"], ly["paint"]["id"]) for ly in again["layers"]] == [
            (1, clear_id), (2, base_id)]

    async with session_factory() as s:
        fresh = await PaintService.get_setup(s, pid)
        assert [(ly["layer_order"], ly["paint"]["id"]) for ly in fresh["layers"]] == [
            (1, clear_id), (2, base_id)]
        rows = (await s.execute(select(RevisionChangelog).where(
            RevisionChangelog.part_id == pid,
            RevisionChangelog.action == "paint_updated"))).scalars().all()
        assert len(rows) == 2


async def test_put_setup_not_required_clears_layers_and_logs(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        part = await _part(s, seed, "PS-2")
        base = await _paint(s, org, admin, "Primer grey", paint_type="primer")
        await s.flush()
        await PaintService.put_setup(s, part_id=part.id, org_id=org, paint_required=True,
                                     process=None, notes=None,
                                     layers=[{"paint_id": base.id}], updated_by=admin)
        out = await PaintService.put_setup(s, part_id=part.id, org_id=org, paint_required=False,
                                           process=None, notes=None, layers=[], updated_by=admin)
        await s.commit()
        assert out == {"paint_required": False, "process": None, "notes": None, "layers": []}

        rows = (await s.execute(select(RevisionChangelog).where(
            RevisionChangelog.part_id == part.id,
            RevisionChangelog.action == "paint_updated"))).scalars().all()
        assert rows[-1].action_description == "Paint not required"


async def test_put_setup_rejects_paint_from_other_org(session_factory, seed):
    async with session_factory() as s:
        part = await _part(s, seed, "PS-3")
        other = await _second_org(s)
        foreign = await _paint(s, other.id, seed["admin_id"], "Foreign paint")
        await s.flush()
        with pytest.raises(ValueError) as exc:
            await PaintService.put_setup(
                s, part_id=part.id, org_id=seed["org_id"], paint_required=True, process=None,
                notes=None, layers=[{"paint_id": foreign.id}], updated_by=seed["admin_id"])
        assert str(foreign.id) in str(exc.value)


async def test_deactivated_paint_stays_in_setup(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        part = await _part(s, seed, "PS-4")
        paint = await _paint(s, org, admin, "Retired blue", colour_code="RAL 5010")
        await s.flush()
        await PaintService.put_setup(s, part_id=part.id, org_id=org, paint_required=True,
                                     process="spray", notes=None,
                                     layers=[{"paint_id": paint.id}], updated_by=admin)
        await PaintService.update_paint(s, org_id=org, paint_id=paint.id, is_active=False)
        await s.commit()
        pid = part.id

    async with session_factory() as s:
        got = await PaintService.get_setup(s, pid)
        assert len(got["layers"]) == 1
        assert got["layers"][0]["paint"]["name"] == "Retired blue"
        assert got["layers"][0]["paint"]["is_active"] is False


# --- overviews -------------------------------------------------------------

async def test_project_overview_lists_only_required_parts(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        painted = await _part(s, seed, "OV-1", name="Painted cover")
        plain = await _part(s, seed, "OV-2", name="Plain bracket")
        untouched = await _part(s, seed, "OV-3", name="Untouched")
        paint = await _paint(s, org, admin, "RAL 9005 base", paint_type="basecoat", colour_code="RAL 9005")
        await s.flush()
        await PaintService.put_setup(s, part_id=painted.id, org_id=org, paint_required=True,
                                     process="spray", notes=None,
                                     layers=[{"paint_id": paint.id, "area": "A-side"}], updated_by=admin)
        await PaintService.put_setup(s, part_id=plain.id, org_id=org, paint_required=False,
                                     process=None, notes=None, layers=[], updated_by=admin)
        await s.commit()
        painted_id, untouched_id = painted.id, untouched.id

    async with session_factory() as s:
        rows = await PaintService.project_overview(s, seed["project_id"])
        assert [r["part_id"] for r in rows] == [painted_id]
        assert untouched_id not in [r["part_id"] for r in rows]
        row = rows[0]
        assert row["part_number"] == "OV-1" and row["name"] == "Painted cover" and row["process"] == "spray"
        assert row["layers"][0]["layer_order"] == 1
        assert row["layers"][0]["area"] == "A-side"
        assert row["layers"][0]["paint"]["colour_code"] == "RAL 9005"


async def test_used_in_returns_parts_with_project_code(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        part = await _part(s, seed, "UI-1", name="Used cover")
        base = await _paint(s, org, admin, "RAL 9005 base", paint_type="basecoat")
        clear = await _paint(s, org, admin, "2K clear", paint_type="clearcoat")
        unused = await _paint(s, org, admin, "Unused paint")
        await s.flush()
        await PaintService.put_setup(s, part_id=part.id, org_id=org, paint_required=True,
                                     process="spray", notes=None,
                                     layers=[{"paint_id": base.id}, {"paint_id": clear.id}],
                                     updated_by=admin)
        await s.commit()
        pid, clear_id, unused_id = part.id, clear.id, unused.id

    async with session_factory() as s:
        rows = await PaintService.used_in(s, org_id=seed["org_id"], paint_id=clear_id)
        assert rows == [{
            "part_id": pid, "part_number": "UI-1", "name": "Used cover",
            "project_id": seed["project_id"], "project_code": "proj", "layer_order": 2}]
        assert await PaintService.used_in(s, org_id=seed["org_id"], paint_id=unused_id) == []


async def test_used_in_is_org_scoped(session_factory, seed):
    async with session_factory() as s:
        org, admin = seed["org_id"], seed["admin_id"]
        part = await _part(s, seed, "UI-2")
        paint = await _paint(s, org, admin, "Scoped paint")
        await s.flush()
        await PaintService.put_setup(s, part_id=part.id, org_id=org, paint_required=True,
                                     process=None, notes=None,
                                     layers=[{"paint_id": paint.id}], updated_by=admin)
        other = await _second_org(s)
        await s.commit()
        # asking as the other org must not see this org's paint usage
        assert await PaintService.used_in(s, org_id=other.id, paint_id=paint.id) == []
