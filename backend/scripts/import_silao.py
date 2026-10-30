"""Silao (KTX Mexico, ex Moriroku MTDM) -> PLM projects VW316PA (VW Taos PA) and
AU436 (Audi Q5 air vents): articles, tools, BOM, relations, files, SEP documents.

Consumes <stage>/silao.json + the staged files from silao_extract.py (WSL host).
Source: SharePoint mtdmexico.sharepoint.com/sites/VW316TAOSPA (state ~April/May
2025, part number list 2026-10-16) plus mail changes; see the stage notes.

Rules (Christoph 2026-10-30):
  - part_number = Silao SAP number (FG 1057xxxxx/1027xxxxx, molded 102xxxxxx),
    customer (VW/Audi) number as customer_part_number; tools by mold number.
  - per-part / per-tool data (drawings, CAD, transfer sheets, mold specs, parts
    lists, certificates, moldflow, graining) is filed on revision 1 of that part;
    project documents go on the fitting SEP work item (scripts/silao_sep_map.py).
  - no part-data mail: the new projects have no mail list, and nothing here
    goes through part_data_mail.enqueue.

Idempotent + re-runnable (match on project code / part_number / file hash).

    docker exec -e PYTHONPATH=/app compose-plm2-backend-1 python /app/scripts/import_silao.py \
        --stage /app/uploads/_stage_silao [--apply] [--created-by 14]
Without --apply everything runs inside a transaction that is rolled back.
"""
import argparse
import asyncio
import hashlib
import json
import mimetypes
import os
import shutil
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Plant, Project
from app.models.part import Part, PartBOMItem, PartRelation, PartRevision, RevisionFile
from app.models.sep import SepGate, SepItemFile, SepWorkItem
from app.services.cavity_layout import layout_from_text

PLANT_CODE = "SIL"
BASELINE = "1"  # imported series data = official 1 (see migration 072)
UPLOADS = os.path.join(os.getcwd(), "uploads")
SEP_TEMPLATE = Path("/app/app/data/sep_template.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mime(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def store(src, apply, *parts, name=None):
    """Copy a staged file into uploads/<parts...>/<uuid><ext or _name>; returns the
    path. A dry run only checks the staged file and copies nothing."""
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    d = os.path.join(UPLOADS, *parts)
    tail = f"_{name}" if name else os.path.splitext(src)[1].lower()
    dst = os.path.join(d, f"{uuid.uuid4().hex}{tail}")
    if apply:
        os.makedirs(d, exist_ok=True)
        shutil.copy2(src, dst)
    return dst


async def ensure_sep(s, project_id):
    """Same copy of the template as POST /sep/projects/{id}/activate."""
    if (await s.execute(select(func.count()).select_from(SepGate).where(
            SepGate.project_id == project_id))).scalar():
        return False
    template = json.loads(SEP_TEMPLATE.read_text())
    for tg in template["gates"]:
        gate = SepGate(project_id=project_id, code=tg["code"], seq=tg["seq"],
                       phase_de=tg["phase_de"], phase_en=tg["phase_en"],
                       status="in_progress" if tg["seq"] == 1 else "pending")
        s.add(gate)
        await s.flush()
        for ti in tg["items"]:
            s.add(SepWorkItem(gate_id=gate.id, project_id=project_id, item_no=ti["item_no"],
                              title_de=ti["title_de"], title_en=ti["title_en"],
                              psp_no=ti.get("psp_no"), department=ti["department"]))
    await s.flush()
    return True


async def main(stage, apply, created_by, allow_missing=False):
    data = json.load(open(os.path.join(stage, "silao.json")))
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    n = dict(projects=0, sep=0, parts=0, revisions=0, bom=0, relations=0,
             part_files=0, sep_files=0, bytes=0)
    report = {"elsewhere": [], "skipped": [], "updated": []}
    written: list[str] = []
    async with Session() as s:
        try:
            plant = (await s.execute(select(Plant).where(Plant.code == PLANT_CODE))).scalar_one()

            # --- projects + SEP --------------------------------------------------
            projects: dict[str, Project] = {}
            for pr in data["projects"]:
                p = (await s.execute(select(Project).where(Project.code == pr["code"]))).scalar_one_or_none()
                if p is None:
                    p = Project(plant_id=plant.id, code=pr["code"], name=pr["name"],
                                description=pr["description"], status="active",
                                customer_naming=pr.get("customer_naming"))
                    s.add(p)
                    await s.flush()
                    n["projects"] += 1
                    print(f"project {pr['code']} created (id {p.id})")
                elif p.plant_id != plant.id:
                    raise SystemExit(f"ABORT: project code {pr['code']} exists in another plant (id {p.id})")
                projects[pr["code"]] = p
                if await ensure_sep(s, p.id):
                    n["sep"] += 1

            # --- parts -----------------------------------------------------------
            by_nr: dict[str, Part] = {}
            for d in data["parts"]:
                nr = d["pn"]
                proj = projects[d["project"]]
                ex = (await s.execute(select(Part).where(Part.part_number == nr))).scalar_one_or_none()
                if ex is not None:
                    by_nr[nr] = ex
                    if ex.project_id != proj.id:
                        report["elsewhere"].append(f"{nr} (project id {ex.project_id})")
                    continue
                part = Part(
                    project_id=proj.id, part_number=nr, name=d["name"][:255],
                    description=d.get("description"),
                    customer_part_number=d.get("customer_part_number"),
                    part_type=d["part_type"], item_category=d["item_category"],
                    supplier=d.get("supplier"), toolmaker_id=d.get("toolmaker_id"),
                    colour_code=(d.get("colour_code") or None) and d["colour_code"][:40],
                    grain=d.get("grain"),
                    material_source="new" if d.get("material") else None,
                    material_new_text=(d.get("material") or None) and d["material"][:500],
                    lifecycle_phase=d.get("lifecycle_phase", "series"),
                    sop_at=date.fromisoformat(d["sop"]) if d.get("sop") else None,
                    data_classification="confidential", created_by=created_by)
                if d["item_category"] == "tool":
                    part.tool_cavities = layout_from_text(d.get("cavities"))
                    part.tool_cycle_time_s = d.get("cycle_s")
                    part.tool_machine = d.get("machine")
                    part.tool_tonnage_class = d.get("tonnage_t")
                s.add(part)
                by_nr[nr] = part
                n["parts"] += 1
            await s.flush()

            # --- baseline revision 1 --------------------------------------------
            rev_by_nr: dict[str, PartRevision] = {}
            idx = {d["pn"]: d for d in data["parts"]}
            for nr, part in by_nr.items():
                rev = (await s.execute(select(PartRevision).where(
                    PartRevision.part_id == part.id,
                    PartRevision.revision_name == BASELINE))).scalar_one_or_none()
                if rev is None and part.project_id in {p.id for p in projects.values()}:
                    d = idx[nr]
                    rev = PartRevision(
                        part_id=part.id, revision_name=BASELINE, phase="official",
                        status="approved", source="import", customer_statement="official",
                        part_phase_at_receipt="series", customer_index=d.get("customer_index"),
                        summary=d.get("revision_summary") or data["revision_summary"],
                        created_by=created_by)
                    s.add(rev)
                    await s.flush()
                    part.active_revision_id = rev.id
                    n["revisions"] += 1
                if rev is not None:
                    rev_by_nr[nr] = rev
            await s.flush()

            # --- BOM -------------------------------------------------------------
            for parent_nr, lines in data["bom"].items():
                rev = rev_by_nr.get(parent_nr)
                if rev is None:
                    report["skipped"].append(f"BOM {parent_nr}: no revision 1")
                    continue
                if (await s.execute(select(func.count()).select_from(PartBOMItem).where(
                        PartBOMItem.revision_id == rev.id))).scalar():
                    continue
                for pos, ln in enumerate(lines, start=1):
                    child = by_nr.get(ln["child"])
                    s.add(PartBOMItem(
                        revision_id=rev.id, child_part_id=child.id if child else None,
                        item_number=str(pos * 10),
                        name=(child.name if child else ln.get("name") or ln["child"])[:255],
                        quantity=ln.get("qty", 1), unit=ln.get("unit", "pcs"), position=pos,
                        notes=ln.get("note"), created_by=created_by))
                    n["bom"] += 1
            await s.flush()

            # --- relations -------------------------------------------------------
            for r in data["relations"]:
                a, b = by_nr.get(r["from"]), by_nr.get(r["to"])
                if a is None or b is None:
                    report["skipped"].append(f"relation {r['from']} -{r['type']}-> {r['to']}: part missing")
                    continue
                if (await s.execute(select(PartRelation).where(
                        PartRelation.from_part_id == a.id, PartRelation.to_part_id == b.id,
                        PartRelation.relation_type == r["type"]))).scalar_one_or_none():
                    continue
                s.add(PartRelation(from_part_id=a.id, to_part_id=b.id, relation_type=r["type"],
                                   notes=r.get("note", "Silao SharePoint import"),
                                   created_by=created_by))
                n["relations"] += 1
            await s.flush()

            # --- files on parts / tools -----------------------------------------
            for f in data["part_files"]:
                rev = rev_by_nr.get(f["pn"])
                if rev is None:
                    report["skipped"].append(f"file {f['rel']}: no revision 1 on {f['pn']}")
                    continue
                src = os.path.join(stage, "files", f["rel"])
                if allow_missing and not os.path.isfile(src):
                    report["skipped"].append(f"missing in stage: {f['rel']}")
                    continue
                digest = f.get("sha256") or sha256(src)
                if (await s.execute(select(RevisionFile.id).where(
                        RevisionFile.revision_id == rev.id, RevisionFile.file_hash == digest,
                        RevisionFile.is_deleted == False))).first():  # noqa: E712
                    continue
                dst = store(src, apply, "revisions", str(rev.id))
                written.append(dst)
                size = os.path.getsize(src)
                ext = os.path.splitext(f["filename"])[1].lower().lstrip(".")
                s.add(RevisionFile(
                    revision_id=rev.id, filename=f["filename"][:255], file_type=f["file_type"],
                    mime_type=mime(f["filename"]), file_size=size, file_path=dst,
                    cad_format=ext if f["file_type"] == "cad" else None,
                    kind=f.get("kind"), note=(f.get("note") or "")[:500] or None,
                    file_hash=digest, uploaded_by=created_by))
                n["part_files"] += 1
                n["bytes"] += size
            await s.flush()

            # --- newer customer data as the next official revision -------------
            n["revisions_new"] = 0
            for r in data.get("extra_revisions", []):
                base = rev_by_nr.get(r["pn"])
                part = by_nr.get(r["pn"])
                if base is None or part is None:
                    report["skipped"].append(f"revision {r['revision_name']} on {r['pn']}: no revision 1")
                    continue
                rev = (await s.execute(select(PartRevision).where(
                    PartRevision.part_id == part.id,
                    PartRevision.revision_name == r["revision_name"]))).scalar_one_or_none()
                if rev is None:
                    rev = PartRevision(
                        part_id=part.id, revision_name=r["revision_name"], phase="official",
                        status="approved", source="import", customer_statement="official",
                        part_phase_at_receipt="series", customer_index=r.get("customer_index"),
                        parent_revision_id=base.id, supersedes_revision_id=base.id,
                        summary=r["summary"], created_by=created_by)
                    s.add(rev)
                    await s.flush()
                    part.active_revision_id = rev.id
                    n["revisions_new"] += 1
                for f in r["files"]:
                    src = os.path.join(stage, "files", f["rel"])
                    if allow_missing and not os.path.isfile(src):
                        report["skipped"].append(f"missing in stage: {f['rel']}")
                        continue
                    digest = sha256(src)
                    if (await s.execute(select(RevisionFile.id).where(
                            RevisionFile.revision_id == rev.id, RevisionFile.file_hash == digest,
                            RevisionFile.is_deleted == False))).first():  # noqa: E712
                        continue
                    dst = store(src, apply, "revisions", str(rev.id))
                    written.append(dst)
                    s.add(RevisionFile(
                        revision_id=rev.id, filename=f["filename"][:255], file_type=f["file_type"],
                        mime_type=mime(f["filename"]), file_size=os.path.getsize(src), file_path=dst,
                        kind=f.get("kind"), note=f.get("note"), file_hash=digest, uploaded_by=created_by))
                    n["part_files"] += 1
            await s.flush()

            # --- project documents on SEP items ---------------------------------
            items = {}
            for code, p in projects.items():
                for it in (await s.execute(select(SepWorkItem, SepGate.code).join(
                        SepGate, SepGate.id == SepWorkItem.gate_id).where(
                        SepWorkItem.project_id == p.id))).all():
                    items[(code, it[1], it[0].item_no)] = it[0]
            for f in data["sep_files"]:
                item = items.get((f["project"], f["gate"], f["item_no"]))
                if item is None:
                    report["skipped"].append(f"sep file {f['rel']}: no item {f['gate']} #{f['item_no']}")
                    continue
                src = os.path.join(stage, "files", f["rel"])
                if allow_missing and not os.path.isfile(src):
                    report["skipped"].append(f"missing in stage: {f['rel']}")
                    continue
                digest = f.get("sha256") or sha256(src)
                if (await s.execute(select(SepItemFile.id).where(
                        SepItemFile.item_id == item.id, SepItemFile.sha256 == digest,
                        SepItemFile.is_deleted == False))).first():  # noqa: E712
                    continue
                dst = store(src, apply, "sep", str(item.project_id), str(item.id), name=f["filename"])
                written.append(dst)
                size = os.path.getsize(src)
                s.add(SepItemFile(item_id=item.id, project_id=item.project_id,
                                  filename=f["filename"][:255], stored_path=dst,
                                  content_type=mime(f["filename"]), size_bytes=size,
                                  sha256=digest, uploaded_by=created_by))
                n["sep_files"] += 1
                n["bytes"] += size
            await s.flush()

            if apply:
                await s.commit()
            else:
                await s.rollback()
        except BaseException:
            await s.rollback()
            apply = False
            raise
        finally:
            if not apply:
                for path in written:  # failure after copying: leave no blobs behind
                    if os.path.exists(path):
                        os.remove(path)
    await engine.dispose()
    mode = "APPLIED" if apply else "DRY RUN (rolled back)"
    print(f"{mode}: " + ", ".join(f"{k}={v}" for k, v in n.items()))
    if report["elsewhere"]:
        print(f"already in other projects (left there, linked): {len(report['elsewhere'])}: "
              + ", ".join(report["elsewhere"]))
    for x in report["skipped"]:
        print("skipped: " + x)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=os.environ.get("SILAO_STAGE", "/app/uploads/_stage_silao"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-missing", action="store_true", help="skip staged files that are missing")
    ap.add_argument("--created-by", type=int, default=int(os.environ.get("CREATED_BY", "3")))
    a = ap.parse_args()
    asyncio.run(main(a.stage, a.apply, a.created_by, a.allow_missing))
