"""VW426 Atlas (project 1864): customer 3D on the article revisions (Christoph 2026-11-09).

Source: S:\\Capacity Studies\\Current Capacity\\KL\\2 OPmobility\\a 1864 - OPm VW Atlas 426 BPM 14009
  nom/    AOB\\AOB CAD-Dwgs-Spec Sheets\\Nomination CAD & Drwgs Sep 16 2024 -> index 1 (customer index A)
  out434/ ECRs\\434 OUT434 Recvd June 16 2026 -> grill carrier, latest implemented level (Part History
          sheet + OUT434 quoted expedited 6/16, tool back 6/30) -> its latest major
  out463/ ECRs\\463 OUT 463 Rev E (VZM9524 package two) -> open draft x.1 on the grill carrier
  out467/ ECRs\\467 OUT Sept 08 2026 (add material 4 paint tabs, Hi-Tech quote 10/14) -> open draft x.2
  OUT00470 (643 clip retention tuning) is NOT filed here: it comes with the ECR Cody enters in PLM
SpinFire STEP conversions sit next to the CATParts (<name>.stp or <name>.CATPart.stp) and are filed
as a sibling STEP; convert_vw426_viewers.py builds the 3D viewer from them.

Files larger than the upload limit are copied straight into uploads/revisions/<rev id>/ (like
attach_silao_steps.py). Idempotent on (revision, file hash); drafts are found again by their summary.
Dry run by default:

    docker exec -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \\
        python -m scripts.import_vw426_cad --stage /app/uploads/_stage_atlas --user christoph.demmler [--apply]
"""
import argparse
import asyncio
import hashlib
import logging
import os
import shutil
import uuid

from sqlalchemy import select

from app.models import AsyncSessionLocal
from app.models.entities import Project, User
from app.models.part import Part, PartRevision, RevisionFile
from app.services import revision_file_service as rfs
from app.services.part_service import ChangelogService, RevisionService

PROJECT = "1864"
UPLOADS = os.path.join(os.getcwd(), "uploads", "revisions")

NOM = "Nomination CAD 9.16.24 (S: AOB, OPm nomination package)"
# customer part number -> [(target, folder, file, note)]; target: "index1" | "latest" | draft key
PLAN = {
    "3CS.807.643": [("index1", "nom", "C_3CS_807_643.CATPart", NOM)],
    "3CS.807.644": [("index1", "nom", "C_3CS_807_644.CATPart", NOM)],
    "3CR.807.531.A": [("index1", "nom", "C_3CR_807_531_A.CATPart", NOM)],
    "3CR.807.532.A": [("index1", "nom", "A_3CR_807_532_A.CATPart", NOM)],
    "3CR.807.425": [("index1", "nom", "I_3CR_807_425.CATPart", NOM)],
    "3CR.807.425.B": [("index1", "nom", "I_3CR_807_425_B.CATPart", NOM)],
    "3CS.807.425": [("index1", "nom", "I_3CS_807_425.CATPart", NOM)],
    "3CR.919.491.A": [("index1", "nom", "G_3CR_919_491_A.CATPart", NOM)],
    "3CR.919.491.C": [("index1", "nom", "C_3CR_919_491_C.CATPart", NOM)],
    "3CR.919.492.A": [("index1", "nom", "G_3CR_919_492_A.CATPart", NOM)],
    "3CR.919.492.C": [("index1", "nom", "B_3CR_919_492_C.CATPart", NOM)],
    "3CR.853.653": [
        ("latest", "out434", "Cpa_00308479.CATPart",
         "OPm OUT00434 (feasibility study, received 6/16/2026), implemented: latest level on the tool"),
        ("out463", "out463", "Cpa_00309738_463.CATPart", "OPm OUT00463 Rev E (VZM9524 optimization package two)"),
        ("out467", "out467", "Cpa_00313711.CATPart", "OPm OUT00467 (add material to 4 paint tabs)"),
    ],
}
DRAFTS = {
    "out463": "OPm OUT00463 Rev E (VZM9524 grille carrier optimization package two), received 8/7/2026; "
              "open: quoted, not implemented",
    "out467": "OPm OUT00467 (add material to 4 upper paint tabs), received 9/8/2026; open: Hi-Tech quote "
              "ECR 467 10/14/2026, not implemented",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def step_of(path):
    for cand in (path + ".stp", os.path.splitext(path)[0] + ".stp"):
        if os.path.exists(cand):
            return cand
    return None


async def add_file(db, rev, src, filename, note, user_id, apply, written):
    digest = sha256(src)
    if (await db.execute(select(RevisionFile.id).where(
            RevisionFile.revision_id == rev.id, RevisionFile.file_hash == digest,
            RevisionFile.is_deleted.is_(False)))).first():
        print(f"     = {filename}")
        return
    ext, file_type, cad_format = rfs.classify(filename, None)
    size = os.path.getsize(src)
    print(f"     + {filename} ({size // (1 << 20)} MB, {file_type}/{cad_format})")
    dst = os.path.join(UPLOADS, str(rev.id), f"{uuid.uuid4().hex}{ext}")
    if apply:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        written.append(dst)
    db.add(RevisionFile(
        revision_id=rev.id, filename=filename[:255], file_type=file_type,
        mime_type=rfs.MIME_MAP.get(ext, "application/octet-stream"), file_size=size,
        file_path=dst, cad_format=cad_format, note=note[:500], file_hash=digest, uploaded_by=user_id))


async def main(stage, username, apply):
    missing = [os.path.join(stage, f, n) for steps in PLAN.values() for _, f, n, _ in steps
               if n and not os.path.exists(os.path.join(stage, f, n))]
    if missing:
        raise SystemExit(f"missing files: {missing}")
    written = []
    async with AsyncSessionLocal() as db:
        try:
            user = (await db.execute(select(User).where(User.username == username))).scalar_one()
            project = (await db.execute(select(Project).where(Project.code == PROJECT))).scalar_one()
            print(f"project {project.code} {project.name}, as {user.full_name}, {'APPLY' if apply else 'dry run'}")
            for cpn, steps in PLAN.items():
                part = (await db.execute(select(Part).where(
                    Part.project_id == project.id, Part.customer_part_number == cpn))).scalar_one()
                revs = (await db.execute(select(PartRevision).where(PartRevision.part_id == part.id)
                                         .order_by(PartRevision.id))).scalars().all()
                majors = [r for r in revs if r.parent_revision_id is None and r.status != "cancelled"]
                latest = next((r for r in majors if r.id == part.active_revision_id), majors[-1])
                print(f"{cpn} ({part.part_number}): majors {[r.revision_name for r in majors]}, active {latest.revision_name}")
                drafts = {}
                for target, folder, name, note in steps:
                    if target == "index1":
                        rev = next(r for r in majors if r.revision_name == "1")
                    elif target == "latest":
                        rev = latest
                    else:
                        rev = drafts.get(target) or next(
                            (r for r in revs if r.parent_revision_id == latest.id
                             and (r.summary or "").startswith(DRAFTS[target][:24])), None)
                        if rev is None:
                            print(f"  new draft on {latest.revision_name}: {DRAFTS[target][:70]}")
                            rev = await RevisionService.create_proposal(
                                db, part.id, latest.id, summary=DRAFTS[target], created_by=user.id)
                            revs.append(rev)
                        drafts[target] = rev
                    print(f"  -> {rev.revision_name}")
                    if name is None:        # draft without files yet
                        continue
                    src = os.path.join(stage, folder, name)
                    await add_file(db, rev, src, name, note, user.id, apply, written)
                    stp = step_of(src) if name.lower().endswith(".catpart") else None
                    if stp:
                        await add_file(db, rev, stp, f"{name}.stp", f"STEP AP242 converted with SpinFire from {name}",
                                       user.id, apply, written)
                    if target == "index1" and apply:
                        await ChangelogService.log_action(
                            db, part_id=part.id, revision_id=rev.id, action="file_uploaded",
                            action_description=f"Customer 3D {name} filed on {rev.revision_name} ({NOM})",
                            performed_by=user.id)
            if apply:
                await db.commit()
                print("committed")
            else:
                await db.rollback()
        except BaseException:
            await db.rollback()
            for p in written:
                if os.path.exists(p):
                    os.remove(p)
            raise


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.stage, a.user, a.apply))
