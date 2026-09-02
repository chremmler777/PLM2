"""Brose Sitech award (RFQ 25 Backpanel, RFQ 26 Seat Trim) -> PLM projects, articles, tools.

Data leans on the RFQ2 database (rfqs 25/26, REV8 tool set, current loop).
Award list = "KTX 17 parts" sheet from Brose, 2026-09-02. Numbers follow the
award list where it differs from the RFQ (799 named Outer, top tether 85H).

Idempotent + re-runnable (match on project code / part_number; skip existing).
Runs in the PLM backend container:
    docker exec -e PYTHONPATH=/app claude-plm2-backend-1 python scripts/import_brose.py
"""
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.entities import Plant, Project
from app.models.part import Part, PartRevision, PartRelation, PartBOMItem

CREATED_BY = 3            # chris
PLANT_CODE = "usa-toccoa"
BASELINE_REV = "RFQ1"     # awarded quote baseline
CUSTOMER = "Brose Sitech"
NOT_AWARDED = "NOT ON AWARD LIST (KTX 17 parts). Loaded for full RFQ scope."

# project code -> (name, RFQ2 id)
PROJECTS = {
    "1994A": ("Brose Backpanel", 25),
    "1994B": ("Brose Seat Trim", 26),
}

# (project, seq, customer_pn, name, brose_pn, material, color, box, weight_g,
#  peak_year_pcs, lifetime_pcs, rfq_bom_id, note)
ARTICLES = [
    # --- 1994A Backpanel (RFQ 25) ---
    ("1994A", 1, "206.881.971", "Seat Back Panel MIC (Lehnenabdeckung)", "S00FKH-001",
     "PP-TD20", "Forge Black", "529 x 525.7 x 137.3", 1127, 253336, 2127194, 313, None),
    ("1994A", 2, "206.881.971.B", "Seat Back Panel DS", "S00FZU-000",
     "PP-TD20", "Forge Black", "495 x 455 x 188.1", 1132, 10401, 87186, 314, None),
    ("1994A", 3, "206.881.972.A", "Seat Back Panel PS", "S00FXC-001",
     "PP-TD20", "Forge Black", "495 x 455 x 188.1", 1132, 10401, 87186, 315, None),
    # --- 1994B Seat Trim (RFQ 26) ---
    ("1994B", 1, "206.882.251", "Handle, manual lift, passenger", "S00G2Q-000",
     "PA6GF15", "Forge Black", "152 x 82 x 29", 48.79, 55280, 463612, 317, None),
    ("1994B", 2, "206.882.252", "Handle, manual lift, driver", "S00DF9-001",
     "PA6GF15", "Forge Black", "152 x 82 x 29", 48.79, 55280, 463612, 318, None),
    ("1994B", 3, "206.885.967", "Bracket, seat back latch cover 40", "S00GOD-000",
     "PP-TD20", "Forge Black", "98 x 93 x 118", 40.17, 122000, 1019000, 321, None),
    ("1994B", 4, "206.885.968", "Bracket, seat back latch cover 60", "S00GOE-000",
     "PP-TD20", "Forge Black", "98 x 93 x 118", 40.17, 122000, 1019000, 376, None),
    ("1994B", 5, "206.887.233", "ISOFIX Cover", "S00G77-000",
     "PA6GF15", "MIC 3 colors", "67 x 115 x 34", 40.36, 488000, 4076000, 324, None),
    ("1994B", 6, "206.881.800", "A-Bracket Inner Trim", "S00FX6-001",
     "PP-TD20", "Forge Black", "139 x 153 x 31.5", 101.02, 19423, 163017, 319, None),
    ("1994B", 7, "206.885.219", "Cover Trim", "S00G1E-000",
     "PP-TD20", "MIC 1 color", "315 x 35 x 25.83", 47.55, 89154, 744654, 325, None),
    ("1994B", 8, "206.886.197", "Cover, center bearing", "S00G0A-000",
     "PP-TD20", "Forge Black", "40 x 108 x 105", 47.76, 122000, 1019000, 326, None),
    ("1994B", 9, "206.883.607", "Seat Belt Exit Cover", "S00FXB-001",
     "ASA", "MIC 3 colors", "90 x 81 x 50", 40.15, 141423, 1182017, 320, "Paint required per RFQ."),
    ("1994B", 10, "206.881.479", "Cover, side shield inner LH", "S00FX2-001",
     "PP-TD20", "forge black / cracked earth", "230 x 152 x 61", 124, 25000, 143000, 337, None),
    ("1994B", 11, "206.881.480", "Cover, side shield inner RH", "S00FX2-001",
     "PP-TD20", "forge black / cracked earth", "230 x 152 x 61", 124, 25000, 143000, 400,
     "NOT ON AWARD LIST (KTX 17 parts). Added because it shares the 1+1 tool with 206.881.479 LH. Confirm with Brose."),
    ("1994B", 12, "206.881.793", "Trim, seat back upper center", "S00FX8-001",
     "PC/ABS", "Skyscraper TBD", "265 x 36 x 28", 46.59, 203000, 1663000, 334, "Paint required per RFQ."),
    ("1994B", 13, "206.881.799", "A-Bracket Outer Cover", "S00FX7-001",
     "PP-TD20", "Forge Black", "138 x 120 x 20", 50.8, 16000, 143000, 338,
     "Award list name (RFQ called it A-Bracket Inner Cover)."),
    ("1994B", 14, "4M0.881.547", "Bracket, light fixture mount cover", "S001V9-110",
     "PP", None, "118 x 34 x 27", 10, 192000, 1600000, 370, None),
    ("1994B", 15, "85H.886.747", "Trim Top Tether", "S000VJ-110",
     "PA6", None, "85.52 x 53.23 x 34.56", 24.81, 300000, 2900000, 375,
     "Award list number 85H.886.747; RFQ quoted 3G0.886.747."),
    # --- full RFQ scope, NOT on the award list (loaded 2026-09-02 on request) ---
    ("1994A", 4, "206.881.971_G02", "Map Pocket", "S00G5U-000",
     "PP-TD20 (TL 52388-F)", None, "401.1 x 228.8 x 69.6", 337.41, 273800, 2301566, 316, NOT_AWARDED),
    ("1994A", 5, "206.881.971_G05", "Pivot Axis (G05)", "S00G5Q-001",
     "PA6-GF15", None, "10 x 34 x 10", 0.97, 821400, 4603132, 341, NOT_AWARDED),
    ("1994A", 6, "206.881.971_G07", "Rossette (G07)", "S00G5Q-000",
     "TPU (TL 52622, Shore 95A)", None, "90 x 24 x 7", 6.69, 547600, 4603132, 343, NOT_AWARDED),
    ("1994B", 16, "5NA.881.253", "Griff", "S000ZP-110",
     "PP/PE-TD20", None, "194 x 66 x 20", 17.82, 45000, 413000, 374, NOT_AWARDED),
]

# Purchased parts from RFQ 25 (50- family = bought components).
# (project, seq, customer_pn, name, material/spec, box, weight_g, rfq_bom_id)
PURCHASED = [
    ("1994A", 1, "206.881.971_G03", "Spring (G03)", "Spring steel DH per DIN EN 10270-2", "39.5 x 47.3 x 66.1", 8.2, 339),
    ("1994A", 2, "206.881.971_G04", "Rubber Bumper (G04)", "TPE acc. TL 52622", "9.4 x 7.9 x 7.5", 0.2, 340),
    ("1994A", 3, "206.881.971_G06", "Strap Sub-Assy (G06)", "Elastic strap + 2x PP fixation plate (TL 52388-F)", "48.2 x 360.6 x 80.6", 30.7, 342),
]

# Back panel 206.881.971 assembly BOM per RFQ 25: (child customer_pn, qty)
BACKPANEL_BOM = [
    ("206.881.971_G02", 1), ("206.881.971_G03", 1), ("206.881.971_G04", 1),
    ("206.881.971_G05", 3), ("206.881.971_G06", 1), ("206.881.971_G07", 2),
]

# (project, tool_seq, name, [(customer_pn, cavities)], mold_type, rfq_tool_id)
TOOLS = [
    ("1994A", 1, "Seat Back Panel MIC", [("206.881.971", 2)], "fixed side ejector", 202),
    ("1994A", 2, "Seat Back Panel DS/PS", [("206.881.971.B", 1), ("206.881.972.A", 1)], "fixed side ejector", 203),
    ("1994B", 1, "Handle, manual lift LH/RH", [("206.882.251", 2), ("206.882.252", 2)], "2-plate", 204),
    ("1994B", 2, "Seat back latch cover 40/60", [("206.885.967", 2), ("206.885.968", 2)], "2-plate", 205),
    ("1994B", 3, "ISOFIX Cover", [("206.887.233", 2)], "2-plate", 206),
    ("1994B", 4, "A-Bracket Inner Trim", [("206.881.800", 2)], "2-plate", 207),
    ("1994B", 5, "Cover Trim", [("206.885.219", 2)], "2-plate", 208),
    ("1994B", 6, "Center Bearing Cover", [("206.886.197", 2)], "2-plate", 209),
    ("1994B", 7, "Seat Belt Exit Cover", [("206.883.607", 2)], "2-plate", 210),
    ("1994B", 8, "Side Shield Inner LH/RH", [("206.881.479", 1), ("206.881.480", 1)], "2-plate", 211),
    ("1994B", 9, "Seat back upper trim center", [("206.881.793", 8)], "2-plate", 212),
    ("1994B", 10, "A-Bracket Outer Cover", [("206.881.799", 2)], "2-plate", 213),
    ("1994B", 11, "Light Fixture Mount Cover", [("4M0.881.547", 2)], "2-plate", 215),
    ("1994B", 12, "Trim Top Tether", [("85H.886.747", 1)], "2-plate", 217),
    # not awarded
    ("1994A", 3, "Map Pocket", [("206.881.971_G02", 2)], "fixed side ejector", 200),
    ("1994A", 4, "Pivot Axis (G05)", [("206.881.971_G05", 8)], "2-plate", 201),
    ("1994A", 5, "Rossette (G07)", [("206.881.971_G07", 4)], "2-plate", 199),
    ("1994B", 13, "Griff", [("5NA.881.253", 2)], "2-plate", 216),
]


def article_pn(project: str, seq: int, family: int = 20) -> str:
    return f"{family}-{project}-{seq:03d}-0"


def purchased_desc(p) -> str:
    proj, _, cpn, _, spec, box, wt, bom_id = p
    return "\n".join([
        f"Customer {CUSTOMER}, program {PROJECTS[proj][0]}. Purchased component of back panel 206.881.971.",
        f"Customer number {cpn}. Spec: {spec}. Box {box} mm, weight {wt} g. RFQ2 bom_item {bom_id}.",
        NOT_AWARDED,
    ])


def article_desc(a) -> str:
    proj, _, cpn, _, brose, mat, color, box, wt, peak, life, bom_id, note = a
    rfq_id = PROJECTS[proj][1]
    lines = [
        f"Customer {CUSTOMER}, program {PROJECTS[proj][0]}. Awarded 2026-09-02 (RFQ {rfq_id}, KTX 17 parts list).",
        f"Customer number {cpn}; Brose number {brose}.",
        f"Material {mat}" + (f", color {color}" if color else "") + f". Box {box} mm, weight {wt} g.",
        f"Peak year {peak:,} pcs, lifetime {life:,} pcs. RFQ2 bom_item {bom_id}.",
    ]
    if note:
        lines.append(note)
    return "\n".join(lines)


def tool_desc(t) -> str:
    proj, _, name, cavs, mold, rfq_tool = t
    rfq_id = PROJECTS[proj][1]
    cav_txt = ", ".join(f"{pn} x{n}" for pn, n in cavs)
    total = sum(n for _, n in cavs)
    return (f"Injection mold, {mold}, {total} cavities: {cav_txt}. "
            f"Customer {CUSTOMER}. Awarded 2026-09-02 (RFQ {rfq_id} REV8, tooling_calc {rfq_tool}).")


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        plant = (await s.execute(select(Plant).where(Plant.code == PLANT_CODE))).scalar_one()

        projects = {}
        for code, (name, rfq_id) in PROJECTS.items():
            proj = (await s.execute(select(Project).where(Project.code == code))).scalar_one_or_none()
            if proj is None:
                proj = Project(plant_id=plant.id, name=name, code=code, status="active",
                               description=f"Customer {CUSTOMER}. Awarded 2026-09-02 from RFQ2 rfq {rfq_id}.")
                s.add(proj)
                await s.flush()
                print(f"Created project {code} {name} (id {proj.id})")
            else:
                print(f"Project {code} exists (id {proj.id})")
            projects[code] = proj
        await s.commit()

        async def get_part(pn):
            return (await s.execute(select(Part).where(Part.part_number == pn))).scalar_one_or_none()

        by_customer_pn = {}
        created = 0
        for a in ARTICLES:
            proj, seq, cpn, name = a[0], a[1], a[2], a[3]
            pn = article_pn(proj, seq)
            part = await get_part(pn)
            if part is None:
                part = Part(project_id=projects[proj].id, part_number=pn, customer_part_number=cpn,
                            name=f"{cpn} {name}", description=article_desc(a), part_type="internal_mfg",
                            item_category="article", data_classification="confidential",
                            created_by=CREATED_BY)
                s.add(part)
                await s.flush()
                created += 1
            by_customer_pn[cpn] = part
        print(f"Articles created={created} (of {len(ARTICLES)})")

        created = 0
        for p in PURCHASED:
            proj, seq, cpn, name = p[0], p[1], p[2], p[3]
            pn = article_pn(proj, seq, family=50)
            part = await get_part(pn)
            if part is None:
                part = Part(project_id=projects[proj].id, part_number=pn, customer_part_number=cpn,
                            name=f"{cpn} {name}", description=purchased_desc(p), part_type="purchased",
                            item_category="article", data_classification="confidential",
                            created_by=CREATED_BY)
                s.add(part)
                await s.flush()
                created += 1
            by_customer_pn[cpn] = part
        print(f"Purchased parts created={created} (of {len(PURCHASED)})")

        created = 0
        tools = {}
        for t in TOOLS:
            proj, seq, name = t[0], t[1], t[2]
            pn = f"{proj}-{seq}"
            part = await get_part(pn)
            if part is None:
                part = Part(project_id=projects[proj].id, part_number=pn, name=f"{proj} TOOL {name}",
                            description=tool_desc(t), part_type="purchased", item_category="tool",
                            data_classification="confidential", created_by=CREATED_BY)
                s.add(part)
                await s.flush()
                created += 1
            tools[pn] = part
        print(f"Tools created={created} (of {len(TOOLS)})")
        await s.commit()

        created = 0
        for part in list(by_customer_pn.values()) + list(tools.values()):
            rev = (await s.execute(select(PartRevision).where(
                PartRevision.part_id == part.id, PartRevision.revision_name == BASELINE_REV))).scalar_one_or_none()
            if rev is None:
                rev = PartRevision(part_id=part.id, revision_name=BASELINE_REV, phase="rfq_phase",
                                   status="approved", created_by=CREATED_BY,
                                   summary="Awarded quote baseline (RFQ2 REV8).")
                s.add(rev)
                await s.flush()
                part.active_revision_id = rev.id
                created += 1
        print(f"Baseline revisions created={created}")
        await s.commit()

        created = 0
        for t in TOOLS:
            tool = tools[f"{t[0]}-{t[1]}"]
            for cpn, n in t[3]:
                art = by_customer_pn[cpn]
                ex = (await s.execute(select(PartRelation).where(
                    PartRelation.from_part_id == tool.id, PartRelation.to_part_id == art.id,
                    PartRelation.relation_type == "produces"))).scalar_one_or_none()
                if ex is None:
                    s.add(PartRelation(from_part_id=tool.id, to_part_id=art.id, relation_type="produces",
                                       notes=f"{n} cavities", created_by=CREATED_BY))
                    created += 1
        print(f"Produces relations created={created}")
        await s.commit()

        parent = by_customer_pn["206.881.971"]
        created = 0
        for pos, (cpn, qty) in enumerate(BACKPANEL_BOM, start=1):
            child = by_customer_pn[cpn]
            ex = (await s.execute(select(PartBOMItem).where(
                PartBOMItem.revision_id == parent.active_revision_id,
                PartBOMItem.child_part_id == child.id))).scalar_one_or_none()
            if ex is None:
                s.add(PartBOMItem(revision_id=parent.active_revision_id, child_part_id=child.id,
                                  item_number=str(pos * 10), name=child.name, quantity=float(qty),
                                  unit="pcs", position=pos, created_by=CREATED_BY,
                                  notes="Per RFQ 25 BOM (206.881.971 assembly)."))
                created += 1
        print(f"Back panel BOM items created={created}")
        await s.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
