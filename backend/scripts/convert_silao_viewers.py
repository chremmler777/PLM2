"""STEP -> glb viewer files for the Silao projects (VW316PA, AU436): revision
files imported by import_silao.py skip the upload path, so nothing converted
them. Smallest first; the preview deflection scales with file size like
reconvert_brose_viewers.py. Idempotent: files that already have a viewer are
skipped, so it can be stopped and restarted.

    docker exec -d -e PYTHONPATH=/app compose-plm2-backend-1 nice -n 19 \
        python /app/uploads/_stage_silao/convert_silao_viewers.py
"""
import asyncio
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part, PartRevision, RevisionFile
from app.utils.cad_converter import convert_step_to_gltf

PROJECT_CODES = ("VW316PA", "AU436")
PLACEHOLDER_MAX = 2048


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        rows = (await s.execute(
            select(RevisionFile.id, Part.part_number)
            .join(PartRevision, PartRevision.id == RevisionFile.revision_id)
            .join(Part, Part.id == PartRevision.part_id)
            .join(Project, Project.id == Part.project_id)
            .where(Project.code.in_(PROJECT_CODES), RevisionFile.cad_format.in_(("stp", "step")),
                   RevisionFile.has_viewer == False, RevisionFile.is_deleted == False)  # noqa: E712
            .order_by(RevisionFile.file_size))).all()
        print(f"{len(rows)} STEP files to convert", flush=True)
        ok_n = fail_n = 0
        for fid, pn in rows:
            rf = await s.get(RevisionFile, fid)
            out = os.path.join(os.path.dirname(rf.file_path), f"{uuid.uuid4().hex}.glb")
            mb = rf.file_size / 1e6
            lin = 0.05 if mb < 20 else 0.25 if mb < 80 else 0.5
            ok = await convert_step_to_gltf(rf.file_path, out, linear_deflection=lin,
                                            angular_deflection=0.5, timeout_seconds=5400)
            size = os.path.getsize(out) if ok and os.path.exists(out) else 0
            if ok and size > PLACEHOLDER_MAX:
                rf.viewer_file_path, rf.has_viewer = out, True
                await s.commit()
                ok_n += 1
                print(f"OK   {pn} {rf.filename} ({mb:.0f} MB -> {size / 1e6:.1f} MB glb)", flush=True)
            else:
                if os.path.exists(out):
                    os.remove(out)
                fail_n += 1
                print(f"FAIL {pn} {rf.filename} ({mb:.0f} MB)", flush=True)
        print(f"done: {ok_n} converted, {fail_n} failed", flush=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
