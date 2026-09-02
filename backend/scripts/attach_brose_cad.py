"""Attach the latest customer 3D data to the Brose RFQ1 revisions (projects 1994A / 1994B).

Sources: files staged under scripts/brose_cad_stage/ (copied from the RFQ2 working
folders on C:\\temp). Where the RFQ2 project already produced a viewer glb
(<name>.stp.fine.glb) it is reused; otherwise the PLM converter runs.

Idempotent: a file is skipped when the revision already holds one with the
same SHA-256. Runs in the PLM backend container:
    docker exec -e PYTHONPATH=/app claude-plm2-backend-1 python scripts/attach_brose_cad.py
"""
import asyncio
import hashlib
import os
import shutil
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.part import Part, PartRevision, RevisionFile
from app.services.part_service import ChangelogService
from app.utils.cad_converter import convert_step_to_gltf

CREATED_BY = 3
STAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brose_cad_stage")
UPLOADS = os.path.join(os.getcwd(), "uploads", "revisions")
B_REL = "B-RELEASE 2026-05-28 (customer STEP, PCA_TM)"

# customer_part_number -> (staged filename, cad revision note)
FILES = {
    # 1994B Seat Trim
    "206.881.479": ("206_881_479____PCA_TM__003_____INNER_SIDE_COVER___B-RELEASE___20260528.stp", B_REL),
    "206.881.793": ("206_881_793____PCA_TM__002_____DECOR_COVER________B-RELEASE___20260528.stp", B_REL),
    "206.881.799": ("206_881_799____PCA_TM__003_____A-BRKT_OUTER_TRIM__B-RELEASE___20260528.stp", B_REL),
    "206.881.800": ("206_881_800____PCA_TM__003_____A-BRKT_INNER_TRIM__B-RELEASE___20260528.stp", B_REL),
    "206.882.251": ("206_882_251____PCA_TM__003_____HANDLE_HA_LEFT_____B-RELEASE___20260528.stp", B_REL),
    "206.882.252": ("206_882_252____PCA_TM__003_____HANDLE_HA_RIGHT____B-RELEASE___20260528.stp", B_REL),
    "206.883.607": ("206_883_607____PCA_TM__002_____BELT_EXIT_COVER____B-RELEASE___20260528.stp", B_REL),
    "206.885.219": ("206_885_219____PCA_TM__002_____BACKPANEL_REAR_____B-RELEASE___20260528.stp", B_REL),
    "206.885.967": ("206_885_967____PCA_TM__003_____LATCH_COVER_40_____B-RELEASE_2026-05-28.stp", B_REL),
    "206.885.968": ("206_885_968____PCA_TM__003_____LATCH_COVER_60_____B-RELEASE_2026-05-28.stp", B_REL),
    "206.886.197": ("206_886_197____PCA_TM__003_000_CTR_BEARING_COVER__B_RELEASE___20260528.stp", B_REL),
    "206.887.233": ("206_887_233____PCA_TM__001_____ISOFIX_COVER_______B-RELEASE_2026-05-28.stp", B_REL),
    "85H.886.747": ("3G0_886_747____PCA_TM__006_____BLENDE_TT_______________ADS_BY_22072021.stp",
                    "Quoted reference 3G0.886.747, ADS 2021-07-22. No 85H.886.747 data received yet."),
    # 1994A Backpanel
    "206.881.971": ("206_881_971____PCA_TM__003_____SEAT_BACK_PANEL____CP3_________20260220.stp",
                    "CP3 2026-02-20 STEP. B-RELEASE 2026-05-28 exists as CATPart only (U:\\RFQ\\RFQ25\\Loop_09\\02_CAD), not attached."),
    "206.881.971_G02": ("206_881_971____G02_TM__004_003_MAP_POCKET_________B-RELEASE___20260528.stp", B_REL),
    "206.881.971_G03": ("206_881_971____G03_TM__004_006_SPRING_____________B-RELEASE___20260528.stp", B_REL),
    "206.881.971_G04": ("206_881_971____G04_TM__004_005_RUBBER_BUMPER______B-RELEASE___20260528.stp", B_REL),
    "206.881.971_G05": ("206_881_971____G05_TM__004_004_PIVOT_AXIS_________B-RELEASE___20260528.stp", B_REL),
    "206.881.971_G06": ("206_881_971____G06_TM__001_007_STRAP_SUB_ASSY_____B-RELEASE___20260528.stp", B_REL),
    "206.881.971_G07": ("206_881_971____G07_TM__001_008_ROSSETTE___________B-RELEASE___20260528.stp", B_REL),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        for cpn, (fname, note) in FILES.items():
            src = os.path.join(STAGE, fname)
            if not os.path.exists(src):
                print(f"MISSING {cpn}: {fname}")
                continue
            part = (await s.execute(select(Part).where(
                Part.customer_part_number == cpn, Part.item_category == "article"))).scalar_one()
            rev = (await s.execute(select(PartRevision).where(
                PartRevision.part_id == part.id, PartRevision.revision_name == "RFQ1"))).scalar_one()
            digest = sha256(src)
            dup = (await s.execute(select(RevisionFile).where(
                RevisionFile.revision_id == rev.id, RevisionFile.file_hash == digest,
                RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712
            if dup:
                print(f"skip {cpn}: already attached (file {dup.id})")
                continue

            rev_dir = os.path.join(UPLOADS, str(rev.id))
            os.makedirs(rev_dir, exist_ok=True)
            stp_path = os.path.join(rev_dir, f"{uuid.uuid4().hex}.stp")
            shutil.copy2(src, stp_path)

            glb_path = os.path.join(rev_dir, f"{uuid.uuid4().hex}.glb")
            pre = src + ".fine.glb"
            if os.path.exists(pre):
                shutil.copy2(pre, glb_path)
                viewer = "reused RFQ2 glb"
            else:
                ok = await convert_step_to_gltf(stp_path, glb_path, timeout_seconds=1500)
                if not ok:
                    glb_path = None
                viewer = "converted" if ok else "NO VIEWER (conversion failed)"

            rf = RevisionFile(
                revision_id=rev.id, filename=fname, file_type="cad", mime_type="application/step",
                file_size=os.path.getsize(stp_path), file_path=stp_path, cad_format="step",
                cad_data={"cad_revision": note, "source": "Brose Sitech customer data via RFQ2"},
                file_hash=digest, viewer_file_path=glb_path, has_viewer=glb_path is not None,
                uploaded_by=CREATED_BY,
            )
            s.add(rf)
            await s.flush()
            await ChangelogService.log_action(
                s, part_id=part.id, revision_id=rev.id, action="file_uploaded",
                action_description=f"Attached customer 3D data '{fname}' to RFQ1 ({note})",
                performed_by=CREATED_BY, file_id=rf.id)
            await s.commit()
            print(f"attached {cpn}: file {rf.id}, {viewer}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
