"""Test parts for the ECR simulations (TOC-PLM-06) in project test-project.

Project Management walks engineering changes end to end on prod before the
ECR go-live; a change needs affected items, and Test Project had none. This
loads a small, realistic family, numbered like the real series parts
(FF-TTTT-NNN-C, the tool number in the middle), every name marked SIM:

    tool 9901 (1+1)  produces 20-9901-001-0 / -002-0  door trim carrier LH / RH
    tool 9902 (1+1)  produces 20-9902-001-0 / -002-0  map pocket LH / RH
    tool 9903        produces 20-9903-001-0           grille carrier
    tool 9904 (1+1)  produces 20-9904-001-0 / -002-0  bracket 40 / 60
    10-9901-001-0 door trim assembly LH  BOM: carrier LH + map pocket LH
    10-9901-002-0 door trim assembly RH  BOM: carrier RH + map pocket RH

Every part is in series with the official baseline revision "1" (approved),
like the WinCarat series parts, so a change creates its ECN revision the same
way. Articles and tools both have a check workflow (check_workflow_standards),
so "Start implementation" is not held on an unmapped category.

The project is also moved to the USA Toccoa plant (where every real project
is): a change is costed at its project's plant, and Test Project sat on the
placeholder "Main Factory" plant, which has no cost sheet rates.

Dry run by default (prints the plan, writes nothing). --apply writes, in one
transaction. Idempotent: an existing SIM part is left alone; a part number
that exists in ANOTHER project aborts the run.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/seed_sim_test_project.py [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Plant, Project, User
from app.models.part import Part, PartBOMItem, PartRelation, PartRevision

PROJECT_CODE = "test-project"
TARGET_PLANT_CODE = "usa-toccoa"
BASELINE = "1"
NOTE = "SIM test item for the ECR simulations (TOC-PLM-06). Not a real article."

# (tool number, tool name, cavities, tonnage class t, [(article, customer no., name)])
TOOLS = [
    ("9901", "SIM TOOL DOOR TRIM CARRIER LH/RH", 2, 450, [
        ("20-9901-001-0", "SIM.867.011", "SIM DOOR TRIM CARRIER LH"),
        ("20-9901-002-0", "SIM.867.012", "SIM DOOR TRIM CARRIER RH"),
    ]),
    ("9902", "SIM TOOL MAP POCKET LH/RH", 2, 350, [
        ("20-9902-001-0", "SIM.867.021", "SIM MAP POCKET LH"),
        ("20-9902-002-0", "SIM.867.022", "SIM MAP POCKET RH"),
    ]),
    ("9903", "SIM TOOL GRILLE CARRIER", 1, 650, [
        ("20-9903-001-0", "SIM.853.653", "SIM GRILLE CARRIER"),
    ]),
    ("9904", "SIM TOOL BRACKET 40/60", 2, 200, [
        ("20-9904-001-0", "SIM.885.967", "SIM BRACKET SEAT BACK 40"),
        ("20-9904-002-0", "SIM.885.968", "SIM BRACKET SEAT BACK 60"),
    ]),
]

# (assembly, customer no., name, [(child article, qty)])
ASSEMBLIES = [
    ("10-9901-001-0", "SIM.867.001", "SIM DOOR TRIM ASSEMBLY LH",
     [("20-9901-001-0", 1), ("20-9902-001-0", 1)]),
    ("10-9901-002-0", "SIM.867.002", "SIM DOOR TRIM ASSEMBLY RH",
     [("20-9901-002-0", 1), ("20-9902-002-0", 1)]),
]


async def run(apply: bool, actor_username: str) -> int:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    plan: list[str] = []
    async with Session() as s:
        project = (await s.execute(
            select(Project).where(Project.code == PROJECT_CODE))).scalar_one_or_none()
        if project is None:
            print(f"ABORT: project {PROJECT_CODE!r} not found")
            return 2
        actor = (await s.execute(
            select(User).where(User.username == actor_username))).scalar_one_or_none()
        if actor is None:
            print(f"ABORT: user {actor_username!r} not found")
            return 2
        plant = (await s.execute(
            select(Plant).where(Plant.code == TARGET_PLANT_CODE))).scalar_one_or_none()
        if plant is None:
            print(f"ABORT: plant {TARGET_PLANT_CODE!r} not found")
            return 2
        print(f"Project {project.code} (id {project.id}), actor {actor.username} "
              f"(id {actor.id}), mode {'APPLY' if apply else 'DRY RUN'}")

        if project.plant_id != plant.id:
            plan.append(f"move project to plant {plant.name} ({plant.code}, id {plant.id}),"
                        f" from plant id {project.plant_id}")
            project.plant_id = plant.id

        wanted = ([(t[0], "tool") for t in TOOLS]
                  + [(a[0], "article") for t in TOOLS for a in t[4]]
                  + [(a[0], "article") for a in ASSEMBLIES])
        existing = {p.part_number: p for p in (await s.execute(
            select(Part).where(Part.part_number.in_([w[0] for w in wanted])))).scalars()}
        foreign = [pn for pn, p in existing.items() if p.project_id != project.id]
        if foreign:
            print(f"ABORT: part numbers already used in another project: {', '.join(foreign)}")
            return 2

        parts: dict[str, Part] = dict(existing)

        async def part(pn: str, **kw) -> Part:
            if pn in parts:
                return parts[pn]
            p = Part(project_id=project.id, part_number=pn, created_by=actor.id,
                     data_classification="confidential", lifecycle_phase="series",
                     description=NOTE, **kw)
            s.add(p)
            await s.flush()
            rev = PartRevision(part_id=p.id, revision_name=BASELINE, phase="official",
                               status="approved", source="customer",
                               part_phase_at_receipt="series", created_by=actor.id,
                               summary="SIM baseline for the ECR simulations.")
            s.add(rev)
            await s.flush()
            p.active_revision_id = rev.id
            parts[pn] = p
            plan.append(f"create {kw.get('item_category')} {pn}  {kw.get('name')}  (revision {BASELINE})")
            return p

        for tool_no, tool_name, cavities, tonnage, articles in TOOLS:
            tool = await part(tool_no, name=tool_name, part_type="internal_mfg",
                              item_category="tool", tool_cavities=cavities,
                              tool_tonnage_class=tonnage)
            for pn, cpn, name in articles:
                art = await part(pn, name=name, customer_part_number=cpn,
                                 part_type="internal_mfg", item_category="article")
                rel = (await s.execute(select(PartRelation).where(
                    PartRelation.from_part_id == tool.id, PartRelation.to_part_id == art.id,
                    PartRelation.relation_type == "produces"))).scalar_one_or_none()
                if rel is None:
                    s.add(PartRelation(from_part_id=tool.id, to_part_id=art.id,
                                       relation_type="produces", created_by=actor.id,
                                       notes=f"{cavities} cavit{'y' if cavities == 1 else 'ies'} (SIM)"))
                    plan.append(f"relate tool {tool_no} produces {pn}")

        for pn, cpn, name, children in ASSEMBLIES:
            asm = await part(pn, name=name, customer_part_number=cpn,
                             part_type="sub_assembly", item_category="article")
            for pos, (child_pn, qty) in enumerate(children, start=1):
                child = parts[child_pn]
                bom = (await s.execute(select(PartBOMItem).where(
                    PartBOMItem.revision_id == asm.active_revision_id,
                    PartBOMItem.child_part_id == child.id))).scalar_one_or_none()
                if bom is None:
                    s.add(PartBOMItem(revision_id=asm.active_revision_id, child_part_id=child.id,
                                      item_number=str(pos * 10), name=child.name,
                                      quantity=float(qty), unit="pcs", position=pos,
                                      created_by=actor.id, notes="SIM BOM"))
                    plan.append(f"BOM {pn} pos {pos * 10}: {child_pn} x{qty}")

        for line in plan or ["nothing to do (already seeded)"]:
            print("  " + line)
        if apply:
            await s.commit()
            print(f"APPLIED: {len(plan)} step(s)")
        else:
            await s.rollback()
            print("DRY RUN: nothing written; rerun with --apply")
    await engine.dispose()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--actor", default="christoph.demmler",
                    help="username recorded as creator (default christoph.demmler)")
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args.apply, args.actor)))


if __name__ == "__main__":
    main()
