"""Seed the 1994 Moldflow timing overview (V1 per tool) from the mails of
2026-10-12..16. Tools are looked up by part number within the project, never
by id. Idempotent by tool + version + cavity layout: a row that exists is
left as it is (edits made in PLM win). Prints the planned rows as a table and
the project-level notes that belong to no single tool (not written to the DB).
Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/seed_1994_moldflow.py [--user <id>] [--apply]
"""
import argparse
import asyncio
import os
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.moldflow import ToolMoldflow
from app.models.part import Part, PartRelation
from app.services import moldflow_service as svc

D12 = "Mail 2026-10-12 Dale Perry 'MoldFlows' status"
D15_RCV = "Mail 2026-10-15 07:56 FZ (Joshua Liu): MF V1 received"
D15_REV = "Mail 2026-10-15 12:59 KTX review to FZ (FZ 10/16: analysis team checking)"
D15_BROSE = "Mail 2026-10-15 13:09 V1 sent to Brose"
UDB_EPSAN = "Mail 2026-10-16 EPSAN: PA6-GF15 generic UDB"
OCT15 = date(2026, 10, 15)
REVIEW_NOTE = ("V2 corrections requested: project name, CAD release, material label, .mfr files, 2 cav, "
               "shrinkage comparison 0.95%, UDB questions")
PA6_UDB = {"udb_status": "in_progress", "material_label": "PA6-GF15",
           "udb_source": "EPSAN generic, rcvd 2026-10-16, not yet sent to FZ"}
SENT = {"geometry_status": "ready", "gate_status": "ready", "received_on": OCT15, "ktx_review_on": OCT15,
        "sent_customer_on": OCT15, "status": "sent_to_customer", "notes": REVIEW_NOTE}
SENT_REF = "; ".join((D15_RCV, D15_REV, D15_BROSE))

# tool part number -> fields of its V1 row (cavity layout not split: NULL)
PLAN: dict[str, dict] = {
    "199401": {**PA6_UDB, "geometry_status": "in_progress", "status": "inputs_open",
               "blockers": "Start MF after 3D update", "source_ref": f"{D12}; {UDB_EPSAN}"},
    "199402": {"geometry_status": "in_progress", "status": "inputs_open",
               "blockers": "draw direction to confirm", "source_ref": D12},
    "199403": {**PA6_UDB, "geometry_status": "in_progress", "status": "inputs_open",
               "notes": "Near ready for MF (Dale 10-12)", "source_ref": f"{D12}; {UDB_EPSAN}"},
    "199404": {"geometry_status": "in_progress", "status": "inputs_open",
               "notes": "Near ready for MF (Dale 10-12)", "source_ref": D12},
    "199405": {**SENT, "source_ref": f"{D12} (gate detail before MF); {SENT_REF}"},
    "199406": {"geometry_status": "ready", "gate_status": "ready", "status": "ready_for_mf", "source_ref": D12},
    "199407": {"udb_status": "open", "material_label": "Romiloy 3020/11", "status": "inputs_open",
               "blockers": "Romiloy 3020/11 UDB open", "source_ref": D12},
    "199408": {**SENT, "source_ref": SENT_REF},
    "199409": {"geometry_status": "ready", "gate_status": "ready", "udb_status": "in_progress",
               "material_label": "Bayblend T85 XF", "status": "ready_for_mf",
               "blockers": "Bayblend T85 XF UDB: FZ to confirm", "source_ref": D12},
    "199410": {**SENT, "blockers": "Clamp force high, bigger machine needed",
               "notes": f"Clamp force high, bigger machine needed. {REVIEW_NOTE}",
               "source_ref": f"{D12}; {SENT_REF}"},
}
VERSION = "V1"
LAYOUT: Optional[str] = None

PROJECT_NOTES = [
    "2026-10-16 07:13/07:24 FZ sent 'other Moldflow reports' via TransferNow ZIP (283 MB, link valid until "
    "2026-10-23); tools unknown, not extracted - not assigned to any tool.",
    "2026-10-16 02:45 FZ will run MF for both cavity layouts (DFM response thread) - not tied to specific "
    "tools; add a cavity_layout row per layout once the reports name them.",
    "2026-10-16 09:30 Brose DFM + Moldflow review meeting.",
    "No MF request dates known (Dale 10-12 mail): mf_requested_on left empty.",
]

COLUMNS = [("tool", 7), ("articles", 47), ("ver", 3), ("geo", 11), ("gate", 11), ("udb", 11),
           ("material", 16), ("rcvd", 10), ("review", 10), ("sent", 10), ("status", 16), ("action", 8),
           ("blockers", 40)]


def _cell(v) -> str:
    if v is None:
        return "-"
    return v.isoformat() if isinstance(v, date) else str(v)


def _table(lines: list[dict]) -> list[str]:
    def fmt(vals):
        return " | ".join(_cell(v)[:w].ljust(w) for v, (_, w) in zip(vals, COLUMNS))
    out = [fmt([c for c, _ in COLUMNS]), "-+-".join("-" * w for _, w in COLUMNS)]
    out += [fmt([ln.get(c) for c, _ in COLUMNS]) for ln in lines]
    return out


async def _articles(s, tool: Part) -> str:
    rows = (await s.execute(select(Part).join(PartRelation, PartRelation.to_part_id == Part.id).where(
        PartRelation.from_part_id == tool.id, PartRelation.relation_type == "produces",
        Part.item_category == "article").order_by(Part.customer_part_number))).scalars().all()
    return ", ".join(f"{a.customer_part_number or a.part_number}/{a.tier1_part_number or '-'}" for a in rows)


async def seed(s, project_code: str, user_id: Optional[int]) -> tuple[list[dict], list[str]]:
    """Writes into session `s` (no commit); returns the table rows and warnings."""
    project = (await s.execute(select(Project).where(Project.code == project_code))).scalar_one()
    lines, warnings = [], []
    for number, fields in PLAN.items():
        tool = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.part_number == number, Part.item_category == "tool"))).scalar_one_or_none()
        if tool is None:
            warnings.append(f"! tool {number} not found in project {project_code}")
            continue
        existing = (await s.execute(select(ToolMoldflow).where(
            ToolMoldflow.tool_part_id == tool.id, ToolMoldflow.version == VERSION,
            func.coalesce(ToolMoldflow.cavity_layout, "") == (LAYOUT or ""),
            ToolMoldflow.deleted_at.is_(None)))).scalar_one_or_none()
        line = {"tool": number, "articles": await _articles(s, tool), "ver": VERSION,
                "geo": fields.get("geometry_status", "open"), "gate": fields.get("gate_status", "open"),
                "udb": fields.get("udb_status", "open"), "material": fields.get("material_label"),
                "rcvd": fields.get("received_on"), "review": fields.get("ktx_review_on"),
                "sent": fields.get("sent_customer_on"), "status": fields["status"],
                "blockers": fields.get("blockers")}
        if existing is not None:
            line["action"] = "= exists"
        else:
            await svc.create(s, tool, {"version": VERSION, "cavity_layout": LAYOUT, **fields}, user_id)
            line["action"] = "+ create"
        lines.append(line)
    return lines, warnings


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=None, help="created_by / audit user (default: none)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        lines, warnings = await seed(s, args.project, args.user)
        print(f"== Moldflow {VERSION} rows, project {args.project}")
        print("\n".join(_table(lines)))
        for w in warnings:
            print(w)
        print("\n== Project notes (printed only, not stored)")
        for n in PROJECT_NOTES:
            print(f"   - {n}")
        if args.apply:
            await s.commit()
            print("\nAPPLIED.")
        else:
            await s.rollback()
            print("\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
