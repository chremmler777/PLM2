"""Paint tables exist and cascade."""
from sqlalchemy import select
from app.models.paint import PAINT_TYPES, Paint, PartPaint, PartPaintLayer
from app.models.part import Part
from app.services.part_service import PartService


async def test_paint_setup_round_trip_and_cascade(session_factory, seed):
    async with session_factory() as s:
        p = await PartService.create_part(s, project_id=seed["project_id"], part_number="PT-1", name="Cover",
                                          part_type="internal_mfg", created_by=seed["admin_id"])
        base = Paint(organization_id=seed["org_id"], name="RAL 9005 base", paint_type="basecoat",
                     colour_code="RAL 9005", created_by=seed["admin_id"])
        s.add(base); await s.flush()
        setup = PartPaint(part_id=p.id, paint_required=True, process="spray", updated_by=seed["admin_id"])
        setup.layers.append(PartPaintLayer(paint_id=base.id, layer_order=1, area="A-side"))
        s.add(setup); await s.commit()
        pid, sid = p.id, setup.id
    async with session_factory() as s:
        got = (await s.execute(select(PartPaint).where(PartPaint.part_id == pid))).scalar_one()
        assert got.paint_required and got.layers[0].paint.colour_code == "RAL 9005"
        await s.delete(got); await s.commit()
    async with session_factory() as s:
        assert (await s.execute(select(PartPaintLayer).where(PartPaintLayer.part_paint_id == sid))).first() is None
    assert "basecoat" in PAINT_TYPES
