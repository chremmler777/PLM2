"""Reset project 1994 (Brose Seat Trim, RFQ 26) to the nominated E1 data set.

What it does, in one transaction:
  1. WIPE   every non-deleted file on every revision of the project (soft-delete
            the rows the way the app does, remove the files and viewer glbs from
            disk). Covers the 4 non-nominated parts too - they keep their part
            and E1, just without files.
  2. NOMINATE the 12 parts of the won RFQ 26 BOM (rfq -> nominated, sets
            nominated_at), set the customer index on their E1 from the Brose 3D
            filename (the `__003__` token) and the received date of the B release.
  3. ATTACH  the staged Brose folder (`1994E1`): per part the DMU and PCA CATParts
            as cad/catia, the DRW_TZ drawing PDF as drawing, and a STEP as
            cad/step with viewer conversion when one is staged next to them.
            Mirrored parts (same tool, Brose ships one side) get the sibling's
            drawing; a mirror with no CATPart of its own also gets the sibling's
            CATParts, flagged in cad_data.mirror_of.

Idempotent: a file whose SHA-256 already sits on the revision is skipped, a
part already nominated is left alone. Dry run by default, --apply writes.

Prod (the source of truth for data - never run this against local to decide
anything):
    rsync the folder to /data/appdata/plm2/revision-uploads/_stage-1994E1
    docker exec -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/reset_1994_e1.py --stage /app/uploads/_stage-1994E1
    ...check the plan, take a DB dump, then add --apply
"""
import argparse
import asyncio
import hashlib
import os
import re
import shutil
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.models.entities import Project
from app.models.part import Part, PartRelation, PartRevision, RevisionFile
from app.services.part_service import ChangelogService, RevisionService
from app.services.revision_file_service import MIME_MAP, uploads_dir
from app.utils.cad_converter import convert_step_to_gltf

# The won RFQ 26 BOM (rfq2 prod, rfqs.id=26, status won): exactly these 12.
NOMINATED = [
    "206.882.251", "206.882.252",  # manual lift handle passenger / driver (tool 199401, mirror)
    "206.885.967", "206.885.968",  # seat back latch cover 40 / 60 (tool 199402, mirror)
    "206.887.233",                 # ISOFIX cover
    "206.881.800",                 # A-bracket inner trim
    "206.885.219",                 # cover trim
    "206.886.197",                 # center bearing cover
    "206.883.607",                 # seat belt exit cover
    "206.881.479",                 # side shield inner LH
    "206.881.793",                 # seat back upper trim center
    "206.881.799",                 # A-bracket outer cover
]
B_RELEASE = date(2026, 5, 28)
SOURCE = "Brose Sitech B-RELEASE 2026-05-28, nominated data folder 1994E1"
# VW data-type token in the filename -> what the file is for (docs/CUSTOMER_DATA_INDEX.md)
KIND_NOTE = {
    "PCA": "PCA engineering master: full construction model with RPS, reference points/lines, annotations. Open this one in CATIA.",
    "DMU": "DMU lightweight solid for packaging and quick viewing, no RPS or references. Archive copy.",
    "DRW": "DRW_TZ customer part drawing.",
}

# 206_881_479____DMU_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260529.CATPart
NAME_RE = re.compile(r"^(\d{3})_(\d{3})_(\d{3})_+([A-Z]{3})_([A-Z]{2})__(\d{3})", re.I)
EXT_KIND = {".catpart": "cad", ".catproduct": "cad", ".pdf": "drawing", ".stp": "cad", ".step": "cad"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_stage(stage):
    """{customer_part_number: {"3d": [(path, kind, index)], "2d": [(path, index)], "step": [path]}}"""
    found = defaultdict(lambda: {"3d": [], "2d": [], "step": []})
    unmatched = []
    seen = set()  # the same drawing is staged once per mirrored part
    for root, _dirs, files in os.walk(stage):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in EXT_KIND:
                continue
            m = NAME_RE.match(fn)
            if not m:
                unmatched.append(fn)
                continue
            digest = sha256(os.path.join(root, fn))
            if digest in seen:
                continue
            seen.add(digest)
            cpn = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            kind, index = m.group(4).upper(), m.group(6)
            path = os.path.join(root, fn)
            if ext == ".pdf":
                found[cpn]["2d"].append((path, index))
            elif ext in (".stp", ".step"):
                found[cpn]["step"].append(path)
            else:
                found[cpn]["3d"].append((path, kind, index))
    return found, unmatched


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, help="folder holding the Brose 1994E1 tree")
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14, help="users.id recorded as performer")
    ap.add_argument("--nominated-on", type=date.fromisoformat, default=date(2026, 9, 21),
                    help="nomination date (default: the day RFQ 26 was set to won in RFQ2)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    found, unmatched = scan_stage(args.stage)
    if unmatched:
        print("UNPARSED filenames (skipped):")
        for fn in unmatched:
            print("   ", fn)

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        parts = (await s.execute(
            select(Part).where(Part.project_id == project.id)
            .options(selectinload(Part.revisions))
        )).scalars().all()
        articles = {p.customer_part_number: p for p in parts if p.item_category == "article"}
        missing = [c for c in NOMINATED if c not in articles]
        if missing:
            raise SystemExit(f"nominated parts not in project {args.project}: {missing}")

        # mirrors: two articles produced by the same tool
        rels = (await s.execute(select(PartRelation).where(PartRelation.relation_type == "produces"))).scalars().all()
        by_tool = defaultdict(list)
        art_ids = {p.id: p for p in articles.values()}
        for r in rels:
            if r.to_part_id in art_ids:
                by_tool[r.from_part_id].append(art_ids[r.to_part_id])
        mirror_of = {}
        for group in by_tool.values():
            if len(group) == 2:
                a, b = group
                mirror_of[a.customer_part_number] = b.customer_part_number
                mirror_of[b.customer_part_number] = a.customer_part_number

        # ---- 1. wipe plan
        rev_ids = [rv.id for p in parts for rv in p.revisions]
        old_files = (await s.execute(select(RevisionFile).where(
            RevisionFile.revision_id.in_(rev_ids), RevisionFile.is_deleted == False))).scalars().all()  # noqa: E712
        print(f"\n== WIPE: {len(old_files)} files on project {args.project} ({len(parts)} parts)")
        for f in old_files:
            print(f"   del file {f.id:>5}  {f.file_type:<8} {f.filename}")

        # ---- 2/3. nominate + attach plan
        print("\n== NOMINATE + ATTACH")
        plan = []  # (part, rev, phase_change, index, attachments[(src, file_type, cad_format, note)])
        for cpn in NOMINATED:
            part = articles[cpn]
            rev = next((rv for rv in part.revisions if rv.id == part.active_revision_id), None)
            if rev is None or rev.revision_name != "E1":
                raise SystemExit(f"{cpn}: active revision is {rev.revision_name if rev else None}, expected E1")
            own = found.get(cpn, {"3d": [], "2d": [], "step": []})
            sib = mirror_of.get(cpn)
            sib_data = found.get(sib) if sib else None
            att = []
            three_d, note3d = own["3d"], None
            if not three_d and sib_data and sib_data["3d"]:
                three_d, note3d = sib_data["3d"], sib
            for path, kind, idx in three_d:
                att.append((path, "cad", "catia", f"{KIND_NOTE.get(kind, kind + ' CATPart')} Customer index {idx}.", note3d))
            two_d, note2d = own["2d"], None
            if not two_d and sib_data and sib_data["2d"]:
                two_d, note2d = sib_data["2d"], sib
            for path, idx in two_d:
                att.append((path, "drawing", None, f"{KIND_NOTE['DRW']} Drawing index {idx}.", note2d))
            steps = own["step"] or (sib_data["step"] if (not own["step"] and sib_data) else [])
            for path in steps:
                att.append((path, "cad", "step", "STEP export for the viewer", None if own["step"] else sib))
            index = own["3d"][0][2] if own["3d"] else (sib_data["3d"][0][2] if sib_data and sib_data["3d"] else None)
            phase_change = part.lifecycle_phase == "rfq"
            plan.append((part, rev, phase_change, index, att))
            flag = "" if own["3d"] else f"   (3D via mirror {sib})"
            print(f"   {cpn}  {part.part_number}  phase {part.lifecycle_phase}->{'nominated' if phase_change else part.lifecycle_phase}"
                  f"  E1 index {rev.customer_index!r}->{index!r}{flag}")
            for path, ftype, fmt, note, via in att:
                print(f"        + {ftype:<8} {os.path.basename(path)}" + (f"   [mirror of {via}]" if via else ""))
            if not att:
                print("        ! NO DATA in stage folder")

        others = [p for c, p in articles.items() if c not in NOMINATED]
        print("\n== NOT NOMINATED (files wiped, part kept in rfq):")
        for p in others:
            print(f"   {p.customer_part_number}  {p.part_number}  {p.name}")
        staged_unused = [c for c in found if c not in NOMINATED]
        if staged_unused:
            print(f"\n!! staged data for parts outside the nominated list: {staged_unused}")

        empty = [p.customer_part_number for p, _rev, _pc, _idx, att in plan if not att]
        if empty:
            print(f"\nREFUSING: no staged data for nominated parts {empty} - the wipe would leave them empty.")
            await engine.dispose()
            raise SystemExit(2)
        if not args.apply:
            print("\nDRY RUN - nothing written. Re-run with --apply.")
            await engine.dispose()
            return

        # ---- apply
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for f in old_files:
            rev = await s.get(PartRevision, f.revision_id)
            f.is_deleted = True
            f.deleted_at = now
            await ChangelogService.log_action(
                s, part_id=rev.part_id, revision_id=rev.id, action="file_deleted",
                action_description=f"Deleted file '{f.filename}' from {rev.revision_name} (1994 E1 reset)",
                performed_by=args.user, file_id=f.id)
            for path in (f.file_path, f.viewer_file_path):
                if path and os.path.exists(path):
                    os.remove(path)
        await s.flush()

        for part, rev, phase_change, index, att in plan:
            if phase_change:
                await RevisionService.set_lifecycle_phase(s, part.id, "nominated", args.nominated_on, created_by=args.user)
            changes = []
            if index and rev.customer_index != index:
                changes.append(("customer_index", rev.customer_index, index))
                rev.customer_index = index
            if rev.customer_received_at is None:
                changes.append(("customer_received_at", None, B_RELEASE.isoformat()))
                rev.customer_received_at = B_RELEASE
            for field, old, new in changes:
                await ChangelogService.log_action(
                    s, part_id=part.id, revision_id=rev.id, action="metadata_updated",
                    action_description=f"E1 {field}: {old!r} -> {new!r} (Brose B-RELEASE nominated data)",
                    performed_by=args.user, field_name=field, old_value=str(old) if old else None, new_value=str(new))
            for src, ftype, fmt, note, via in att:
                digest = sha256(src)
                dup = (await s.execute(select(RevisionFile).where(
                    RevisionFile.revision_id == rev.id, RevisionFile.file_hash == digest,
                    RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712
                if dup:
                    print(f"   skip {part.customer_part_number}: {os.path.basename(src)} already on E1")
                    continue
                target_dir = uploads_dir(rev.id)
                os.makedirs(target_dir, exist_ok=True)
                ext = os.path.splitext(src)[1].lower()
                dst = os.path.join(target_dir, f"{uuid.uuid4().hex}{ext}")
                shutil.copy2(src, dst)
                viewer = None
                if fmt == "step":
                    glb = os.path.join(target_dir, f"{uuid.uuid4().hex}.glb")
                    if await convert_step_to_gltf(dst, glb, timeout_seconds=1500):
                        viewer = glb
                    else:
                        print(f"   ! viewer conversion failed for {os.path.basename(src)}")
                cad_data = None
                if ftype == "cad":
                    cad_data = {"cad_revision": "B-RELEASE 2026-05-28", "note": note, "source": SOURCE}
                    if via:
                        cad_data["mirror_of"] = via
                rf = RevisionFile(
                    revision_id=rev.id, filename=os.path.basename(src), file_type=ftype,
                    mime_type=MIME_MAP.get(ext, "application/octet-stream"),
                    file_size=os.path.getsize(dst), file_path=dst, cad_format=fmt, cad_data=cad_data,
                    file_hash=digest, viewer_file_path=viewer, has_viewer=viewer is not None,
                    uploaded_by=args.user,
                )
                s.add(rf)
                await s.flush()
                await ChangelogService.log_action(
                    s, part_id=part.id, revision_id=rev.id, action="file_uploaded",
                    action_description=f"Attached {ftype} '{rf.filename}' to E1 ({note}"
                                       + (f", mirror of {via}" if via else "") + ")",
                    performed_by=args.user, file_id=rf.id)
                print(f"   attached {part.customer_part_number}: {ftype} {rf.filename} (file {rf.id})")
        await s.commit()
        print("\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
