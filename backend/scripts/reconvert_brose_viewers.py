"""Re-run the STEP -> glb conversion for Brose revision files whose viewer file is the
placeholder cube (written when the converter's OCC import failed, e.g. missing libgomp).

Idempotent: only files whose current glb is under 2 KB are touched.
    docker exec -e PYTHONPATH=/app compose-plm2-backend-1 python scripts/reconvert_brose_viewers.py
"""
import asyncio
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.entities import Project
from app.models.part import Part, PartRevision, RevisionFile
from app.utils.cad_converter import convert_step_to_gltf

PROJECT_CODES = ("1994A", "1994B")
PLACEHOLDER_MAX = 2048


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        rows = (await s.execute(
            select(RevisionFile, Part.customer_part_number)
            .join(PartRevision, PartRevision.id == RevisionFile.revision_id)
            .join(Part, Part.id == PartRevision.part_id)
            .join(Project, Project.id == Part.project_id)
            .where(Project.code.in_(PROJECT_CODES), RevisionFile.cad_format == "step",
                   RevisionFile.is_deleted == False)  # noqa: E712
            .order_by(RevisionFile.file_size))).all()
        for rf, cpn in rows:
            size = os.path.getsize(rf.viewer_file_path) if rf.viewer_file_path and os.path.exists(rf.viewer_file_path) else 0
            if size > PLACEHOLDER_MAX:
                continue
            out = os.path.join(os.path.dirname(rf.file_path), f"{uuid.uuid4().hex}.glb")
            ok = await convert_step_to_gltf(rf.file_path, out, timeout_seconds=3600)
            new_size = os.path.getsize(out) if ok and os.path.exists(out) else 0
            if ok and new_size > PLACEHOLDER_MAX:
                old = rf.viewer_file_path
                rf.viewer_file_path, rf.has_viewer = out, True
                await s.commit()
                if old and os.path.exists(old) and old != out:
                    os.remove(old)
                print(f"OK   {cpn} file {rf.id}: {new_size/1e6:.1f} MB glb")
            else:
                if os.path.exists(out):
                    os.remove(out)
                print(f"FAIL {cpn} file {rf.id}: conversion still yields placeholder/none")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
