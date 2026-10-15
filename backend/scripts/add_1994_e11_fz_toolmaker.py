"""E1.1 on four 1994 parts: FZ toolmaker-modified data (changed per the DFMs),
sent to Brose (Philip Paluch) via GlobalX 2026-10-15 09:32-09:33, awaiting
customer confirmation. Creates proposal E1.1 under E1 and attaches the STEP
as sent (with viewer). Once Brose confirms: "Customer adopted" (promote);
on rejection the iteration is closed. Idempotent: skips a part whose E1.1
already holds the file. Dry run by default.

The sent file names carry outdated Scout numbers from RFQ2; the summary uses
the prod tier1_part_number.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/add_1994_e11_fz_toolmaker.py --stage /app/uploads/_stage-1994-e11-fz [--apply]
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

U_DIR = r"U:\RFQ\RFQ26_260112_Brose Seat Trim\30_Outgoing\2026-10-15_GlobalX_to_Brose_Paluch"
# (Brose no., part, KTX tool, FZ mold, FZ data date, sent file)
PARTS = [
    ("206.885.967", "Latch Cover 40", "199402", "FZ-26364", "2026-10-13",
     "206.885.967_S00GOD-000_LATCH-COVER-40_toolmaker-modified_2026-10-13.stp"),
    ("206.887.233", "ISOFIX Cover", "199403", "FZ-26365", "2026-10-14",
     "206.887.233_S00G77-000_ISOFIX-COVER_toolmaker-modified_2026-10-14.stp"),
    ("206.881.800", "A-Bracket Inner Trim", "199404", "FZ-26362", "2026-10-13",
     "206.881.800_S00FX6-001_A-BRKT-INNER-TRIM_toolmaker-modified_2026-10-13.stp"),
    ("206.881.799", "A-Bracket Outer Trim", "199410", "FZ-26370", "2026-10-15",
     "206.881.799_S00FX7-001_A-BRKT-OUTER-TRIM_toolmaker-modified_2026-10-15.stp"),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--project", default="1994")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        for cpn, name, tool, mold, fz_date, fname in PARTS:
            src = os.path.join(args.stage, fname)
            if not os.path.exists(src):
                raise SystemExit(f"missing {src}")
            with open(src, "rb") as fh:
                contents = fh.read()
            digest = hashlib.sha256(contents).hexdigest()
            part = (await s.execute(select(Part).where(
                Part.project_id == project.id, Part.customer_part_number == cpn,
                Part.item_category == "article"))).scalar_one()
            e1 = (await s.execute(select(PartRevision).where(
                PartRevision.part_id == part.id, PartRevision.revision_name == "E1"))).scalar_one()
            e11 = (await s.execute(select(PartRevision).where(
                PartRevision.part_id == part.id, PartRevision.revision_name == "E1.1"))).scalar_one_or_none()
            label = f"{cpn} / {part.tier1_part_number} {name} (KTX {tool}, {mold})"
            summary = (f"Toolmaker data, awaiting customer confirmation: {label}, modified by FZ Tools "
                       f"per the DFMs (FZ data {fz_date}), sent to Brose (Philip Paluch) via GlobalX "
                       f"2026-10-15 09:33. Base E1 · {e1.customer_index}. Brose not confirmed yet.")
            print(f"{part.part_number} {label}: E1 id {e1.id} ({e1.status}, index {e1.customer_index}), "
                  f"E1.1 {'exists id ' + str(e11.id) if e11 else 'will be created'}")
            if e11:
                dup = (await s.execute(select(RevisionFile).where(
                    RevisionFile.revision_id == e11.id, RevisionFile.file_hash == digest,
                    RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712
                if dup:
                    print(f"  file already on E1.1 (id {dup.id}); skip")
                    continue
            print(f"  attach {fname} ({len(contents) / 1048576:.1f} MB) as cad/step with viewer")
            if not args.apply:
                continue
            if e11 is None:
                e11 = await RevisionService.create_proposal(s, part.id, e1.id, summary=summary, created_by=args.user)
                await s.flush()
                print(f"  created {e11.revision_name} (id {e11.id})")
            rf = await store_revision_file(s, e11, fname, contents, args.user, content_type="application/step")
            rf.cad_data = {"cad_revision": f"FZ toolmaker-modified {fz_date}",
                           "note": "Toolmaker data, awaiting Brose confirmation. File name carries the "
                                   "outdated RFQ2 Scout no.",
                           "toolmaker": "FZ Tools", "fz_mold": mold, "ktx_tool": tool,
                           "sent": "GlobalX to Brose (Philip Paluch) 2026-10-15 09:33",
                           "source": U_DIR + r"\02_Sent", "fz_original": U_DIR + r"\01_FZ_original",
                           "evidence": U_DIR + r"\03_Evidence"}
            await ChangelogService.log_action(
                s, part_id=part.id, revision_id=e11.id, action="metadata_updated",
                action_description="E1.1 opened for FZ toolmaker data sent to Brose, awaiting confirmation",
                performed_by=args.user, field_name="summary", new_value=summary)
            await s.commit()
            print(f"  attached file {rf.id}, viewer: {rf.has_viewer}")
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
