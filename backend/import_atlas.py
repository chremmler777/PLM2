"""One-off import: VW426 Atlas project (TWOS id 1864) + its tools + articles. Idempotent.

Run from backend/ with the project's python env:
    python import_atlas.py
"""
import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models.entities import Project, Plant
from app.models.part import Part, PartRelation

ORG_ID = 1
CREATED_BY = 3  # chris
PROJECT_CODE = "1864"  # corrected from 1846 (transposition); article data is authoritative

# (TWOS tool ID, name, supplier toolcode, [customer/part codes])
TOOLS = [
    ("3450", "Grille Carrier", None, ["AB_3CR 853 653"]),
    ("3451", "Lateral Trim MIC", "4671", ["C_3CS_807_643", "C_3CS_807_644"]),
    ("3452", "Upper cladding basis MIC", "4666", ["C_3CR_807_531_A"]),
    ("3453", "Under cladding basis MIC", "4667", ["A_3CR_807_532_A"]),
    ("3454", "Rear Cladding", "4669", ["I_3CR_807_425"]),
    ("3455", "Rear Cladding", "4673", ["I_3CR_807_425_B"]),
    ("3456", "REAR Upr Tray (Cross)", "4668", ["I_3CS_807_425"]),
    ("3457", "PDC Brackets", "4672",
     ["B_3CR_919_492_C", "C_3CR_919_491_C", "G_3CR_919_491_A", "G_3CR_919_492_A"]),
]

# (article part number, name, mfg stage [IM-WIP|IM-FG], VW customer number).
# Producing tool ID is the 4-digit middle segment of the part number
# (e.g. 20-3451-002-0 -> tool 3451). The customer numbers are the same codes
# parked on the tools above, written in VW's dotted form; the leading letter
# there (I_, C_, G_, ...) is a variant index and is not part of the number.
ARTICLES = [
    ("10-3457-001-0", "PDC Inner Bracket LH", "IM-WIP", "3CR.919.491.A"),
    ("10-3457-001-1", "PDC Inner Bracket (Peak) LH", "IM-WIP", "3CR.919.491.C"),
    ("10-3457-002-0", "PDC Inner Bracket RH", "IM-WIP", "3CR.919.492.A"),
    ("10-3457-002-1", "PDC Inner Bracket (Peak) RH", "IM-WIP", "3CR.919.492.C"),
    ("20-3450-001-0", "Grill Carrier", "IM-FG", "3CR.853.653"),
    ("20-3451-001-0", "Lat Lower Cover LH", "IM-FG", "3CS.807.643"),
    ("20-3451-002-0", "Lat Lower Cover RH", "IM-FG", "3CS.807.644"),
    ("20-3452-001-0", "Upper Cladding", "IM-FG", "3CR.807.531.A"),
    ("20-3453-001-0", "Lower Cladding", "IM-FG", "3CR.807.532.A"),
    ("20-3454-001-0", "RR Cladding (Basis)", "IM-FG", "3CR.807.425"),
    ("20-3455-001-0", "RR Cladding (Peak)", "IM-FG", "3CR.807.425.B"),
    ("20-3456-001-0", "RR Undertray (Cross)", "IM-FG", "3CS.807.425"),
]

STAGE_LABEL = {"IM-WIP": "injection-molded, work-in-progress",
               "IM-FG": "injection-molded, finished good"}


def producing_tool_id(article_pn: str) -> str:
    """Tool TWOS id is the middle segment: '20-3451-002-0' -> '3451'."""
    return article_pn.split("-")[1]


async def main():
    engine = create_async_engine("sqlite+aiosqlite:///plm.db", connect_args={"timeout": 30})
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        plant = (await s.execute(select(Plant).where(Plant.code == "usa-toccoa"))).scalar_one_or_none()
        if plant:
            print(f"Plant USA Toccoa already exists (id {plant.id})")
        else:
            plant = Plant(organization_id=ORG_ID, name="USA Toccoa", code="usa-toccoa",
                          location="Toccoa, GA, USA", is_active=True)
            s.add(plant)
            await s.flush()
            print(f"Created plant 'USA Toccoa' id={plant.id}")

        # Find project by name (code may still be the old 1846), then ensure code is 1864.
        proj = (await s.execute(
            select(Project).where(Project.name == "VW426 Atlas")
        )).scalar_one_or_none()
        if proj is None:
            proj = Project(plant_id=plant.id, name="VW426 Atlas", code=PROJECT_CODE,
                           description=f"TWOS main id {PROJECT_CODE}; program VW426 Atlas (OPmobility)",
                           status="active")
            s.add(proj)
            await s.flush()
            print(f"Created project 'VW426 Atlas' id={proj.id} code={PROJECT_CODE}")
        elif proj.code != PROJECT_CODE:
            old = proj.code
            proj.code = PROJECT_CODE
            proj.description = f"TWOS main id {PROJECT_CODE}; program VW426 Atlas (OPmobility)"
            print(f"Corrected project {proj.id} code {old} -> {PROJECT_CODE}")
        else:
            print(f"Project {proj.id} code already {PROJECT_CODE}")

        # Tools (idempotent)
        created_tools = []
        for pn, name, tc, cids in TOOLS:
            ex = (await s.execute(
                select(Part).where(Part.part_number == pn, Part.project_id == proj.id)
            )).scalar_one_or_none()
            if ex:
                continue
            desc = f"VW426 Atlas tool (TWOS ID {pn})."
            if tc:
                desc += f" Supplier toolcode: {tc}."
            desc += " Customer/part codes: " + ", ".join(cids) + "."
            s.add(Part(project_id=proj.id, part_number=pn, name=name, description=desc,
                       part_type="purchased", item_category="tool",
                       data_classification="confidential", created_by=CREATED_BY))
            created_tools.append(pn)
        await s.flush()
        print(f"Tools created this run: {created_tools or 'none (all present)'}")

        # Map tool TWOS id -> Part.id for relation linking
        tool_rows = (await s.execute(
            select(Part.id, Part.part_number).where(
                Part.project_id == proj.id, Part.item_category == "tool")
        )).all()
        tool_id_by_pn = {r.part_number: r.id for r in tool_rows}

        # Articles (idempotent)
        created_articles = []
        article_id_by_pn = {}
        for pn, name, stage, customer_pn in ARTICLES:
            ex = (await s.execute(
                select(Part).where(Part.part_number == pn, Part.project_id == proj.id)
            )).scalar_one_or_none()
            if ex:
                article_id_by_pn[pn] = ex.id
                if ex.customer_part_number != customer_pn:
                    ex.customer_part_number = customer_pn
                continue
            tool_pn = producing_tool_id(pn)
            desc = (f"VW426 Atlas article. Customer/program: OPmobility VW426. "
                    f"Stage: {STAGE_LABEL.get(stage, stage)}. Std qty 100 pcs. "
                    f"Produced by tool {tool_pn}.")
            p = Part(project_id=proj.id, part_number=pn,
                     customer_part_number=customer_pn,
                     name=name, description=desc,
                     part_type="internal_mfg", item_category="article",
                     data_classification="confidential", created_by=CREATED_BY)
            s.add(p)
            await s.flush()
            article_id_by_pn[pn] = p.id
            created_articles.append(pn)
        await s.flush()
        print(f"Articles created this run: {created_articles or 'none (all present)'}")

        # 'produces' relations: tool -> article (idempotent)
        created_rel = 0
        for pn, _name, _stage in ARTICLES:
            tool_pn = producing_tool_id(pn)
            from_id = tool_id_by_pn.get(tool_pn)
            to_id = article_id_by_pn.get(pn)
            if not from_id or not to_id:
                print(f"  !! missing part for relation {tool_pn}->{pn} (from={from_id} to={to_id})")
                continue
            ex = (await s.execute(
                select(PartRelation).where(
                    PartRelation.from_part_id == from_id,
                    PartRelation.to_part_id == to_id,
                    PartRelation.relation_type == "produces")
            )).scalar_one_or_none()
            if ex:
                continue
            s.add(PartRelation(from_part_id=from_id, to_part_id=to_id,
                               relation_type="produces",
                               notes="Imported from TWOS (VW426 Atlas).",
                               created_by=CREATED_BY))
            created_rel += 1
        await s.commit()
        print(f"'produces' relations created this run: {created_rel}")

        # Report
        parts = (await s.execute(
            select(Part.id, Part.part_number, Part.name, Part.item_category)
            .where(Part.project_id == proj.id).order_by(Part.item_category, Part.part_number)
        )).all()
        print(f"\nProject {proj.id} (VW426 Atlas, code {proj.code}) parts:")
        for r in parts:
            print(f"  [{r.item_category:7}] {r.part_number:14} {r.name}")
        rels = (await s.execute(
            select(PartRelation.from_part_id, PartRelation.to_part_id, PartRelation.relation_type)
        )).all()
        print(f"\nTotal part relations in DB: {len(rels)}")
    await engine.dispose()


asyncio.run(main())
