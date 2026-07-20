"""Load WinCarat extract JSON into the live PLM Postgres — SP-B steps 2-4.

Idempotent + re-runnable (match on natural keys; skip existing). Runs in
the PLM backend container (has models + asyncpg + DATABASE_URL). Consumes
the JSON produced by wincarat_extract.py.

Phases:
  1. Ensure the USA Toccoa plant, upsert every active project.
  2. Upsert every active-project part (tools/articles/purchased) into a
     global ARTNR -> part registry.
  3. Resolve BOM children against that registry; create the missing ones
     (raw material 40-*, clips 50-*, packaging 65-*) in their parent's
     project. Give every part a baseline WC-IMP revision, and hang the
     assembly BOM lines (with quantities) off the parent's revision.
  4. Tool -> article 'produces' relations by the number-segment heuristic.

Usage:
    docker exec claude-plm2-backend-1 python scripts/import_wincarat.py --in scripts/wincarat.json
"""
import argparse
import asyncio
import json
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.entities import Plant, Project
from app.models.part import Part, PartRevision, PartBOMItem, PartRelation

ORG_ID = 1
CREATED_BY = 3           # chris
PLANT_CODE = "usa-toccoa"
BASELINE_REV = "WC-IMP"  # WinCarat import baseline revision

def classify(teileart, has_bom, eigenkz):
    """Map WinCarat classification to PLM (item_category, part_type).

    item_category: TEILEART 'W' -> tool, everything else -> article.
    part_type: EIGENKZ (own-manufacture flag) is the make/buy signal —
      1 = in-house (internal_mfg, or sub_assembly when it has a BOM),
      0/None = bought (purchased). This correctly marks the 50-series
      clips/fasteners (TEILEART 'T' but EIGENKZ 0) as purchased.
    """
    if teileart == "W":
        return "tool", "purchased"      # tools are bought
    if has_bom:
        return "article", "sub_assembly"
    if eigenkz == 1:
        return "article", "internal_mfg"
    return "article", "purchased"


def compose_desc(a, project_name):
    bits = [f"WinCarat {project_name}."]
    if a.get("kdartnr"):
        bits.append(f"Customer no {a['kdartnr']}.")
    if a.get("zeichnr"):
        bits.append(f"Drawing {a['zeichnr']}.")
    if a.get("gewichtnetto"):
        bits.append(f"Net wt {a['gewichtnetto']}.")
    t = a.get("tool")
    if t:
        tb = []
        if t.get("kavitaet"):
            tb.append(f"{t['kavitaet']} cav")
        if t.get("wartungsintervall"):
            tb.append(f"maint every {t['wartungsintervall']} shots")
        if t.get("zustandstext"):
            tb.append(str(t["zustandstext"]))
        if t.get("gesamtprod"):
            tb.append(f"total shots {t['gesamtprod']}")
        if t.get("lieferant"):
            tb.append(f"maker {t['lieferant']}")
        if tb:
            bits.append("Tool: " + ", ".join(tb) + ".")
    return " ".join(bits)


def producing_tool_seg(part_number: str) -> str | None:
    """Middle segment of an article number, e.g. '20-3342-001-0' -> '3342'."""
    parts = part_number.split("-")
    return parts[1] if len(parts) >= 2 else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", required=True)
    args = ap.parse_args()
    data = json.load(open(args.infile))

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        # --- Phase 1: plant + projects ---
        plant = (await s.execute(select(Plant).where(Plant.code == PLANT_CODE))).scalar_one_or_none()
        if plant is None:
            plant = Plant(organization_id=ORG_ID, name="USA Toccoa", code=PLANT_CODE,
                          location="Toccoa, GA, USA", is_active=True)
            s.add(plant)
            await s.flush()
        proj_by_nr: dict[str, Project] = {}
        created_proj = 0
        for p in data["projects"]:
            ex = (await s.execute(select(Project).where(Project.code == p["projektnr"]))).scalar_one_or_none()
            if ex is None:
                ex = Project(plant_id=plant.id, name=p["name"], code=p["projektnr"],
                             description=f"WinCarat {p.get('status')}; customer {p.get('customer')}",
                             status="active")
                s.add(ex)
                await s.flush()
                created_proj += 1
            proj_by_nr[p["projektnr"]] = ex
        await s.commit()
        print(f"Phase 1: plant ok, projects created={created_proj} (total {len(proj_by_nr)})")

        # --- Phase 2: parts ---
        part_by_artnr: dict[str, Part] = {}
        # preload existing parts for these projects (idempotent re-run)
        proj_ids = [pr.id for pr in proj_by_nr.values()]
        for existing in (await s.execute(select(Part).where(Part.project_id.in_(proj_ids)))).scalars():
            part_by_artnr[existing.part_number] = existing
        created_parts = 0
        updated_parts = 0
        for p in data["projects"]:
            proj = proj_by_nr[p["projektnr"]]
            for a in p["parts"]:
                cat, ptype = classify(a.get("teileart"), bool(a.get("bom")), a.get("eigenkz"))
                ex = part_by_artnr.get(a["artnr"])
                if ex is not None:
                    # idempotent update: correct classification / supplier on re-run
                    if (ex.item_category, ex.part_type) != (cat, ptype) or ex.supplier != (a.get("supplier") or None):
                        ex.item_category, ex.part_type = cat, ptype
                        ex.supplier = a.get("supplier") or None
                        updated_parts += 1
                    continue
                part = Part(project_id=proj.id, part_number=a["artnr"],
                            name=(a.get("matchcode") or a["artnr"])[:255],
                            description=compose_desc(a, p["name"]),
                            part_type=ptype, item_category=cat,
                            supplier=(a.get("supplier") or None),
                            data_classification="confidential", created_by=CREATED_BY)
                s.add(part)
                part_by_artnr[a["artnr"]] = part
                created_parts += 1
            await s.flush()
        await s.commit()
        print(f"Phase 2: parts created={created_parts} updated={updated_parts} (registry {len(part_by_artnr)})")

        # --- Phase 3: BOM children + baseline revisions + BOM items ---
        created_children = 0
        for p in data["projects"]:
            proj = proj_by_nr[p["projektnr"]]
            for a in p["parts"]:
                for b in a.get("bom", []):
                    child_nr = b.get("child_artnr")
                    if not child_nr or child_nr in part_by_artnr:
                        continue
                    cat, ptype = classify(b.get("child_teileart"), False, b.get("child_eigenkz"))
                    child = Part(project_id=proj.id, part_number=child_nr,
                                 name=(b.get("name") or child_nr)[:255],
                                 description=f"WinCarat BOM component ({b.get('child_teileart')}) under {p['name']}.",
                                 part_type=ptype, item_category=cat,
                                 data_classification="confidential", created_by=CREATED_BY)
                    s.add(child)
                    part_by_artnr[child_nr] = child
                    created_children += 1
            await s.flush()
        await s.commit()
        print(f"Phase 3a: BOM-child parts created={created_children}")

        # baseline revision per part
        rev_by_part: dict[int, PartRevision] = {}
        for existing in (await s.execute(
                select(PartRevision).where(PartRevision.revision_name == BASELINE_REV))).scalars():
            rev_by_part[existing.part_id] = existing
        created_revs = 0
        for part in part_by_artnr.values():
            if part.id in rev_by_part:
                continue
            rev = PartRevision(part_id=part.id, revision_name=BASELINE_REV,
                               phase="engineering", status="approved", created_by=CREATED_BY)
            s.add(rev)
            await s.flush()
            part.active_revision_id = rev.id
            rev_by_part[part.id] = rev
            created_revs += 1
        await s.commit()
        print(f"Phase 3b: baseline revisions created={created_revs}")

        # BOM items on each assembly's baseline revision
        created_bom = 0
        skipped_bom = 0
        for p in data["projects"]:
            for a in p["parts"]:
                parent = part_by_artnr.get(a["artnr"])
                if parent is None or not a.get("bom"):
                    continue
                rev = rev_by_part[parent.id]
                existing_keys = {(bi.item_number, bi.child_part_id) for bi in (await s.execute(
                    select(PartBOMItem).where(PartBOMItem.revision_id == rev.id))).scalars()}
                for pos, b in enumerate(a["bom"], start=1):
                    child = part_by_artnr.get(b.get("child_artnr"))
                    item_number = str(b.get("posnr") or pos)
                    key = (item_number, child.id if child else None)
                    if key in existing_keys:
                        skipped_bom += 1
                        continue
                    note = []
                    if b.get("verschleissteil"):
                        note.append("wear part")
                    if b.get("ersatzteil"):
                        note.append("spare part")
                    if child is None:
                        note.append(f"unresolved WinCarat child {b.get('child_artnr')}")
                    s.add(PartBOMItem(
                        revision_id=rev.id,
                        child_part_id=child.id if child else None,
                        item_number=item_number,
                        name=(b.get("name") or b.get("child_artnr") or "item")[:255],
                        quantity=float(b.get("menge") or 1.0),
                        unit=(b.get("einheit") or "pcs")[:20],
                        position=pos,
                        notes=", ".join(note) or None,
                        created_by=CREATED_BY))
                    existing_keys.add(key)
                    created_bom += 1
            await s.flush()
        await s.commit()
        print(f"Phase 3c: BOM items created={created_bom} skipped={skipped_bom}")

        # --- Phase 4: tool -> article produces relations ---
        # group parts by project, map tool number-segment -> tool part
        created_rel = 0
        for p in data["projects"]:
            proj = proj_by_nr[p["projektnr"]]
            proj_parts = [part_by_artnr[a["artnr"]] for a in p["parts"] if a["artnr"] in part_by_artnr]
            tools = {pt.part_number: pt for pt in proj_parts if pt.item_category == "tool"}
            existing_rel = {(r.from_part_id, r.to_part_id) for r in (await s.execute(
                select(PartRelation).where(PartRelation.relation_type == "produces"))).scalars()}
            for art in proj_parts:
                if art.item_category != "article":
                    continue
                seg = producing_tool_seg(art.part_number)
                tool = tools.get(seg) if seg else None
                if tool is None or (tool.id, art.id) in existing_rel:
                    continue
                s.add(PartRelation(from_part_id=tool.id, to_part_id=art.id,
                                   relation_type="produces",
                                   notes="Imported from WinCarat (number-segment match).",
                                   created_by=CREATED_BY))
                existing_rel.add((tool.id, art.id))
                created_rel += 1
            await s.flush()
        await s.commit()
        print(f"Phase 4: produces relations created={created_rel}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
