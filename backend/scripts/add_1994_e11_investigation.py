"""First E1.1 on 1994: investigation data (not official) for the center
bearing cover 206.886.197 - Brose DRAFT_MOD STEP of 2026-05-29 carrying
draft index 004. Creates proposal E1.1 under E1 and attaches the STEP with a
viewer. Idempotent: skips when E1.1 already holds the file. Dry run by
default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/add_1994_e11_investigation.py --stage /app/uploads/_stage-1994E1-e11 [--apply]
"""
import argparse
import asyncio
import hashlib
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part, PartRevision, RevisionFile
from app.services.part_service import ChangelogService, RevisionService
from app.services.revision_file_service import store_revision_file

CPN = "206.886.197"
FILE = "206_886_197____PCA_TM__004_____CTR_BEARING_COVER__DRAFT_MOD___20260529.stp"
SUMMARY = ("Investigation data, not official: Brose DRAFT_MOD of 2026-05-29 "
           "(draft index 004) on top of E1 · 003. Feasibility check only.")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    src = os.path.join(args.stage, FILE)
    if not os.path.exists(src):
        raise SystemExit(f"missing {src}")
    with open(src, "rb") as fh:
        contents = fh.read()
    digest = hashlib.sha256(contents).hexdigest()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        part = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.customer_part_number == CPN, Part.item_category == "article"))).scalar_one()
        e1 = (await s.execute(select(PartRevision).where(
            PartRevision.part_id == part.id, PartRevision.revision_name == "E1"))).scalar_one()
        e11 = (await s.execute(select(PartRevision).where(
            PartRevision.part_id == part.id, PartRevision.revision_name == "E1.1"))).scalar_one_or_none()
        print(f"part {part.part_number} {part.name}: E1 id {e1.id} (index {e1.customer_index}), "
              f"E1.1 {'exists id ' + str(e11.id) if e11 else 'will be created'}")
        if e11:
            dup = (await s.execute(select(RevisionFile).where(
                RevisionFile.revision_id == e11.id, RevisionFile.file_hash == digest,
                RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712
            if dup:
                print(f"file already on E1.1 (id {dup.id}); nothing to do")
                await engine.dispose()
                return
        print(f"attach {FILE} ({len(contents) / 1048576:.1f} MB) as cad/step with viewer")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            await engine.dispose()
            return
        if e11 is None:
            e11 = await RevisionService.create_proposal(s, part.id, e1.id, summary=SUMMARY, created_by=args.user)
            await s.flush()
            print(f"created {e11.revision_name} (id {e11.id})")
        rf = await store_revision_file(s, e11, FILE, contents, args.user, content_type="application/step")
        rf.cad_data = {"cad_revision": "DRAFT_MOD 2026-05-29, draft index 004",
                       "note": "Investigation STEP, not official. Base: E1 · 003 B-RELEASE.",
                       "source": "Brose Sitech via 1994E1/PCA Copy/e11"}
        await ChangelogService.log_action(
            s, part_id=part.id, revision_id=e11.id, action="metadata_updated",
            action_description="E1.1 opened for the DRAFT_MOD investigation (not official)",
            performed_by=args.user, field_name="summary", new_value=SUMMARY)
        await s.commit()
        print(f"attached file {rf.id}, viewer: {rf.has_viewer}\nAPPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
