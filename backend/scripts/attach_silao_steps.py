"""File SpinFire STEP conversions of the Silao CATIA data next to their source.

For every <name>.stp in <stage>/steps, the CATPart / CATProduct revision files
named <name> on VW316PA / AU436 get a sibling STEP on the same revision (same
kind, note says where it came from). convert_silao_viewers.py then builds the
3D viewer file from it. Idempotent on (revision, file hash).

    docker exec -e PYTHONPATH=/app compose-plm2-backend-1 python \
        /app/uploads/_stage_silao/attach_silao_steps.py --stage /app/uploads/_stage_silao [--apply]
"""
import argparse
import asyncio
import hashlib
import os
import shutil
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part, PartRevision, RevisionFile

PROJECT_CODES = ("VW316PA", "AU436")
UPLOADS = os.path.join(os.getcwd(), "uploads", "revisions")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def main(stage, apply, created_by):
    steps_dir = os.path.join(stage, "steps")
    steps = {fn[:-4]: os.path.join(steps_dir, fn) for fn in os.listdir(steps_dir) if fn.lower().endswith(".stp")}
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    added = skipped = unmatched = 0
    written = []
    async with Session() as s:
        try:
            rows = (await s.execute(
                select(RevisionFile)
                .join(PartRevision, PartRevision.id == RevisionFile.revision_id)
                .join(Part, Part.id == PartRevision.part_id)
                .join(Project, Project.id == Part.project_id)
                .where(Project.code.in_(PROJECT_CODES), RevisionFile.filename.in_(list(steps)),
                       RevisionFile.is_deleted == False))).scalars().all()  # noqa: E712
            matched = {r.filename for r in rows}
            unmatched = len(set(steps) - matched)
            digests = {}
            for src_rf in rows:
                stp = steps[src_rf.filename]
                digest = digests.setdefault(stp, sha256(stp))
                if (await s.execute(select(RevisionFile.id).where(
                        RevisionFile.revision_id == src_rf.revision_id, RevisionFile.file_hash == digest,
                        RevisionFile.is_deleted == False))).first():  # noqa: E712
                    skipped += 1
                    continue
                dst = os.path.join(UPLOADS, str(src_rf.revision_id), f"{uuid.uuid4().hex}.stp")
                if apply:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(stp, dst)
                    written.append(dst)
                s.add(RevisionFile(
                    revision_id=src_rf.revision_id, filename=f"{src_rf.filename}.stp"[:255],
                    file_type="cad", mime_type="application/step", file_size=os.path.getsize(stp),
                    file_path=dst, cad_format="step", kind=src_rf.kind,
                    note=f"STEP AP242 converted with SpinFire from {src_rf.filename}"[:500],
                    file_hash=digest, uploaded_by=created_by))
                added += 1
            if apply:
                await s.commit()
            else:
                await s.rollback()
        except BaseException:
            await s.rollback()
            for p in written:
                if os.path.exists(p):
                    os.remove(p)
            raise
    await engine.dispose()
    print(f"{'APPLIED' if apply else 'DRY RUN'}: steps={len(steps)} added={added} "
          f"already={skipped} no_matching_source={unmatched}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="/app/uploads/_stage_silao")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--created-by", type=int, default=14)
    a = ap.parse_args()
    asyncio.run(main(a.stage, a.apply, a.created_by))
