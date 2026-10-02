"""BR167 Daimler / MBUSI (P: 1316) -> PLM project 91: articles, tools, BOM, drawings.

Consumes scripts/br167_stage/br167.json + staged drawings from br167_extract.py.
Idempotent + re-runnable (match on project code / part_number / file hash).

Rules (package prompt 00_PLM_PROMPT.md, 2026-10-02):
  - identity: KTX article no <-> Daimler part no (customer_part_number) <-> tool no;
    capacity tools 08xx-2 produce the same articles as the originals.
  - Part-BOM level is the baseline (customer_index on revision 1); Smaragd is the
    drawing master, so differences are reported, never written over.
  - CAD, tool data, programs, gauges, raw measurements stay on P: and are kept
    as path references only (part description for now).
  - Articles that already live in another project stay there; they are only
    linked (BOM, relations), and their BOM is filled only when empty.

    docker exec -e PYTHONPATH=/app claude-plm2-backend-1 python scripts/import_br167.py
"""
import asyncio
import hashlib
import json
import os
import shutil
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.entities import Plant, Project
from app.models.part import Part, PartRevision, PartRelation, PartBOMItem, RevisionFile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, "br167_stage")
UPLOADS = os.path.join(os.getcwd(), "uploads", "revisions")
CREATED_BY = 3            # chris
PLANT_CODE = "usa-toccoa"
BASELINE = "1"            # imported series data = official 1 (see migration 072)
SKIP = {"WM94SW": "welding machine, belongs in MachineDB (shared with G01)"}


def project_description(pr):
    return (
        "BR167 Mercedes-Benz GLE/GLS, MBUSI Tuscaloosa. Customer Daimler / MBUSI.\n"
        f"System of record (read-only, link only): {pr['p_root']} = {pr['unc_root']}\n"
        "Products: Window Frame 0827-0840, Center Console 0825/0826, Lamellas 0820-0824, "
        "Cover Loudspeaker 0841, Trim Panel Spring Link 0851, AMG Trim Panel Spring Link; "
        "capacity tools 2024/25: 0827-2..0830-2 (Siebenwurst), 0841-2 (Rathgeber).\n"
        "Imported 2026-10-02 from the BR167 PLM package (Daimler Part-BOM 2024-07-23).\n"
        "Known gaps: no moldflow results (request from Siebenwurst / Rathgeber); SEP matrix "
        "only for the 2024 capacity-tool project; non-window-frame products have 1-4 drawings on P:."
    )


def describe(p):
    bits = ["BR167 Daimler / MBUSI (P: 1316)."]
    if p.get("customer_part_number"):
        bits.append(f"Daimler part no {p['customer_part_number']}.")
    if p.get("drawing_no"):
        bits.append(f"Drawing {p['drawing_no']}.")
    if p.get("level"):
        bits.append(f"Part-BOM level {p['level']}.")
    for key, label in (("group", "Group"), ("colour", "Colour"), ("surface", "Surface"),
                       ("single_weight", "Weight"), ("shot_weight", "Shot weight"),
                       ("cavities", "Cavities"), ("cycle", "Cycle"), ("machine", "Machine"),
                       ("dimension", "Dimension"), ("parts_tray", "Parts/tray"),
                       ("parts_pallet", "Parts/pallet"), ("pack_code", "MBUSI pack code"),
                       ("sop_text", "SOP"), ("total_parts", "Total parts (plan)"),
                       ("supplier", "Supplier/maker"), ("status", "Status"),
                       ("customer_pns_text", "Customer part no(s)"), ("po_tts", "Daimler PO / TTS"),
                       ("replaces", "Capacity tool of")):
        if p.get(key):
            bits.append(f"{label}: {p[key]}.")
    if p.get("notes"):
        bits.append(p["notes"])
    if p.get("flag"):
        bits.append(f"CHECK: {p['flag']}")
    text = " ".join(bits)
    if p.get("links"):
        text += "\n\nP: data (read-only, link only, never copied):\n" + "\n".join(
            f"- {l['category']}: {l['path']}" for l in p["links"])
    return text


def tonnage(machine):
    import re
    m = re.match(r"^\s*(\d{2,4})\s*T", machine or "", re.I)
    return int(m.group(1)) if m else None


def cycle_s(v):
    import re
    m = re.search(r"\d+(?:[.,]\d+)?", v or "")
    return float(m.group(0).replace(",", ".")) if m else None


def cavities(v):
    import re
    n = sum(int(x) for x in re.findall(r"\d+", v or ""))
    return n or None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def main():
    data = json.load(open(os.path.join(STAGE, "br167.json")))
    pr = data["project"]
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    report = {"elsewhere": [], "bom_kept": [], "skipped": []}
    async with Session() as s:
        plant = (await s.execute(select(Plant).where(Plant.code == PLANT_CODE))).scalar_one()
        project = (await s.execute(select(Project).where(Project.code == pr["code"]))).scalar_one_or_none()
        if project is None:
            project = Project(plant_id=plant.id, code=pr["code"], name=pr["name"],
                              description=project_description(pr), status="active")
            s.add(project)
            await s.flush()
            print(f"project {pr['code']} created (id {project.id})")

        # --- parts -----------------------------------------------------------
        by_nr: dict[str, Part] = {}
        created = 0
        for p in data["parts"]:
            nr = p["artnr"]
            if nr in SKIP:
                report["skipped"].append(f"{nr}: {SKIP[nr]}")
                continue
            ex = (await s.execute(select(Part).where(Part.part_number == nr))).scalar_one_or_none()
            if ex is not None:
                by_nr[nr] = ex
                if ex.project_id != project.id:
                    report["elsewhere"].append(nr)
                continue
            is_tool = p["item_category"] == "tool"
            part = Part(
                project_id=project.id, part_number=nr,
                name=(p["name"] or nr)[:255], description=describe(p),
                customer_part_number=p.get("customer_part_number"),
                part_type=p["part_type"], item_category=p["item_category"],
                supplier=(p.get("supplier") or None),
                colour_code=(p.get("colour") or None) and p["colour"][:40],
                lifecycle_phase="series",
                sop_at=date.fromisoformat(p["sop"]) if p.get("sop") else None,
                data_classification="confidential", created_by=CREATED_BY)
            if is_tool:
                part.tool_cavities = cavities(p.get("cavities"))
                part.tool_cycle_time_s = cycle_s(p.get("cycle"))
                part.tool_machine = p.get("machine")
                part.tool_tonnage_class = tonnage(p.get("machine"))
            s.add(part)
            by_nr[nr] = part
            created += 1
        await s.flush()

        # --- baseline revision 1 ---------------------------------------------
        rev_by_part: dict[int, PartRevision] = {}
        revs_created = 0
        level_by_nr = {p["artnr"]: p.get("level") for p in data["parts"]}
        for nr, part in by_nr.items():
            rev = (await s.execute(select(PartRevision).where(
                PartRevision.part_id == part.id, PartRevision.revision_name == BASELINE))).scalar_one_or_none()
            if rev is None and part.project_id == project.id:
                rev = PartRevision(
                    part_id=part.id, revision_name=BASELINE, phase="official", status="approved",
                    source="import", customer_statement="official", part_phase_at_receipt="series",
                    customer_index=level_by_nr.get(nr),
                    summary="Series baseline from the BR167 PLM package (Daimler Part-BOM 2024-07-23).",
                    created_by=CREATED_BY)
                s.add(rev)
                await s.flush()
                part.active_revision_id = rev.id
                revs_created += 1
            if rev is not None:
                rev_by_part[part.id] = rev
        await s.flush()

        # --- BOM -------------------------------------------------------------
        bom_created = 0
        for parent_nr, lines in data["bom"].items():
            parent = by_nr.get(parent_nr)
            rev = rev_by_part.get(parent.id) if parent else None
            if rev is None:
                continue
            existing = (await s.execute(select(PartBOMItem).where(PartBOMItem.revision_id == rev.id))).scalars().all()
            if existing:
                if parent.project_id != project.id:
                    report["bom_kept"].append(f"{parent_nr} ({len(existing)} lines)")
                continue
            for pos, ln in enumerate(lines, start=1):
                child = by_nr.get(ln["child"])
                s.add(PartBOMItem(
                    revision_id=rev.id, child_part_id=child.id if child else None,
                    item_number=str(pos * 10),
                    name=(child.name if child else ln["child"])[:255],
                    quantity=ln["qty"], unit=ln["unit"], position=pos,
                    notes=ln.get("note"), created_by=CREATED_BY))
                bom_created += 1
        await s.flush()

        # --- relations -------------------------------------------------------
        rel_created = 0
        for rtype, mapping in (("produces", data["produces"]), ("assembles", data["assembles"])):
            for frm, tos in mapping.items():
                a = by_nr.get(frm)
                if a is None:
                    continue
                for to in tos:
                    b = by_nr.get(to)
                    if b is None:
                        continue
                    dup = (await s.execute(select(PartRelation).where(
                        PartRelation.from_part_id == a.id, PartRelation.to_part_id == b.id,
                        PartRelation.relation_type == rtype))).scalar_one_or_none()
                    if dup:
                        continue
                    note = "BR167 package" + ("; capacity tool 2024/25" if "-" in frm and rtype == "produces" else "")
                    s.add(PartRelation(from_part_id=a.id, to_part_id=b.id, relation_type=rtype,
                                       notes=note, created_by=CREATED_BY))
                    rel_created += 1
        await s.flush()

        # --- drawings --------------------------------------------------------
        files_created = 0
        for d in data["drawings"]:
            part = by_nr.get(d["artnr"])
            rev = rev_by_part.get(part.id) if part else None
            if rev is None:
                report["skipped"].append(f"drawing {d['file']}: no revision 1 on {d['artnr']}")
                continue
            src = os.path.join(STAGE, d["staged"])
            digest = sha256(src)
            dup = (await s.execute(select(RevisionFile).where(
                RevisionFile.revision_id == rev.id, RevisionFile.file_hash == digest,
                RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712
            if dup:
                continue
            rev_dir = os.path.join(UPLOADS, str(rev.id))
            os.makedirs(rev_dir, exist_ok=True)
            ext = os.path.splitext(d["file"])[1].lower()
            dst = os.path.join(rev_dir, f"{uuid.uuid4().hex}{ext}")
            shutil.copy2(src, dst)
            s.add(RevisionFile(
                revision_id=rev.id, filename=d["file"][:255], file_type="drawing",
                mime_type="application/pdf" if ext == ".pdf" else "application/octet-stream",
                file_size=os.path.getsize(dst), file_path=dst, kind="DRW",
                note=f"{d['note']}. Package: {d['rel']}"[:500],
                file_hash=digest, uploaded_by=CREATED_BY))
            files_created += 1

        await s.commit()
    await engine.dispose()
    print(f"parts created={created}, revisions created={revs_created}, BOM lines={bom_created}, "
          f"relations={rel_created}, drawings={files_created}")
    print(f"already in other projects (left there, linked): {len(report['elsewhere'])}: "
          + ", ".join(report["elsewhere"]))
    if report["bom_kept"]:
        print("existing BOM kept: " + "; ".join(report["bom_kept"]))
    for x in report["skipped"]:
        print("skipped: " + x)


if __name__ == "__main__":
    asyncio.run(main())
