"""The 1994 Moldflow seed: tools found by number within the project, the
planned V1 rows and statuses, dry run writes nothing, apply writes once (a
rerun leaves existing rows alone), audit entries per created row."""
import importlib.util
from pathlib import Path

from sqlalchemy import func, select

from app.models.entities import AuditLog, Project
from app.models.moldflow import ToolMoldflow
from app.models.part import Part, PartRelation

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_1994_moldflow.py"

TOOLS = {
    "199401": [("206.882.251", "S00H4X-110"), ("206.882.252", "S00H4W-110")],
    "199402": [("206.885.967", "S00G0E-110"), ("206.885.968", "S00G0D-110")],
    "199403": [("206.887.233", "S00H54-110")], "199404": [("206.881.800", "S00H48-110")],
    "199405": [("206.885.219", "S00HT7-110")], "199406": [("206.886.197", "S00HQJ-110")],
    "199407": [("206.883.607", "S00H4D-110")], "199408": [("206.881.479", "S00H43-110")],
    "199409": [("206.881.793", "S00H4R-110")], "199410": [("206.881.799", "S00HP8-110")],
}


def load():
    spec = importlib.util.spec_from_file_location("seed_1994_moldflow", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def build_1994(s, project_id: int, user_id: int, tools=TOOLS) -> None:
    """Project 1994 with its tools and produced articles (as on prod), plus a
    199401 tool in another project that must not be touched."""
    project = await s.get(Project, project_id)
    project.code = "1994"
    other = Project(plant_id=project.plant_id, name="Other", code="other", status="active")
    s.add(other)
    await s.flush()
    s.add(Part(project_id=other.id, part_number="199401", name="decoy", part_type="purchased",
               item_category="tool", created_by=user_id))
    n = 0
    for number, arts in tools.items():
        tool = Part(project_id=project_id, part_number=number, name=f"Tool {number}", part_type="purchased",
                    item_category="tool", created_by=user_id)
        s.add(tool)
        await s.flush()
        for brose, scout in arts:
            n += 1
            a = Part(project_id=project_id, part_number=f"20-1994-{n:03d}-0", name=f"Article {brose}",
                     customer_part_number=brose, tier1_part_number=scout, part_type="internal_mfg",
                     item_category="article", created_by=user_id)
            s.add(a)
            await s.flush()
            s.add(PartRelation(from_part_id=tool.id, to_part_id=a.id, relation_type="produces", created_by=user_id))
    await s.commit()


async def _count(s) -> int:
    return (await s.execute(select(func.count(ToolMoldflow.id)))).scalar_one()


async def test_dry_run_apply_and_rerun(session_factory, seed):
    mod = load()
    async with session_factory() as s:
        await build_1994(s, seed["project_id"], seed["admin_id"])

    async with session_factory() as s:  # dry run
        lines, warnings = await mod.seed(s, "1994", seed["admin_id"])
        await s.rollback()
        assert warnings == [] and len(lines) == 10
        assert {ln["action"] for ln in lines} == {"+ create"}
        assert await _count(s) == 0
        table = mod._table(lines)
        assert table[0].startswith("tool ") and len(table) == 12

    async with session_factory() as s:  # apply
        await mod.seed(s, "1994", seed["admin_id"])
        await s.commit()
    async with session_factory() as s:
        rows = {p.part_number: r for r, p in (await s.execute(
            select(ToolMoldflow, Part).join(Part, Part.id == ToolMoldflow.tool_part_id))).all()}
        assert set(rows) == set(TOOLS)
        assert all(p.project_id == seed["project_id"] for p in (await s.execute(
            select(Part).join(ToolMoldflow, ToolMoldflow.tool_part_id == Part.id))).scalars())
        status = {k: r.status for k, r in rows.items()}
        assert status == {
            "199401": "inputs_open", "199402": "inputs_open", "199403": "inputs_open", "199404": "inputs_open",
            "199405": "sent_to_customer", "199406": "ready_for_mf", "199407": "inputs_open",
            "199408": "sent_to_customer", "199409": "ready_for_mf", "199410": "sent_to_customer"}
        assert all(r.version == "V1" and r.cavity_layout is None and r.mf_requested_on is None for r in rows.values())
        r10 = rows["199410"]
        assert (r10.received_on.isoformat(), r10.ktx_review_on.isoformat(), r10.sent_customer_on.isoformat()) == (
            "2026-10-15", "2026-10-15", "2026-10-15")
        assert "bigger machine" in r10.blockers and "shrinkage comparison 0.95%" in r10.notes
        assert r10.customer_feedback is None and "13:09" in r10.source_ref
        assert (rows["199401"].udb_status, rows["199401"].material_label) == ("in_progress", "PA6-GF15")
        assert "EPSAN" in rows["199403"].udb_source
        assert (rows["199407"].udb_status, rows["199407"].material_label) == ("open", "Romiloy 3020/11")
        assert rows["199409"].material_label == "Bayblend T85 XF"
        assert rows["199402"].blockers == "draw direction to confirm"
        assert (await s.execute(select(func.count(AuditLog.id)).where(
            AuditLog.action == "moldflow_created"))).scalar_one() == 10

    async with session_factory() as s:  # an edit made in PLM survives a rerun
        r = (await s.execute(select(ToolMoldflow).join(Part, Part.id == ToolMoldflow.tool_part_id).where(
            Part.part_number == "199406"))).scalar_one()
        r.status = "running"
        await s.commit()
    async with session_factory() as s:
        lines, _ = await mod.seed(s, "1994", seed["admin_id"])
        await s.commit()
        assert {ln["action"] for ln in lines} == {"= exists"}
        assert await _count(s) == 10
        r = (await s.execute(select(ToolMoldflow).join(Part, Part.id == ToolMoldflow.tool_part_id).where(
            Part.part_number == "199406"))).scalar_one()
        assert r.status == "running"


async def test_missing_tool_is_warned(session_factory, seed):
    mod = load()
    async with session_factory() as s:
        await build_1994(s, seed["project_id"], seed["admin_id"],
                         tools={k: v for k, v in TOOLS.items() if k != "199404"})
    async with session_factory() as s:
        lines, warnings = await mod.seed(s, "1994", None)
        assert warnings == ["! tool 199404 not found in project 1994"] and len(lines) == 9
