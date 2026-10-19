"""1994 data of 2026-10-19 (filing request from Christoph via Asss 2):

1) E1.1 on 206.882.251 Handle LH: FZ toolmaker-modified data (changed per the
   DFMs), sent to Brose (Philip Paluch) via GlobalX 2026-10-19 08:12 on Dale's
   request, awaiting customer confirmation. Same treatment as the 10/15 E1.1s
   (add_1994_e11_fz_toolmaker.py). FZ sent LH only, RH 206.882.252 untouched.
2) E2 on 206.883.607 Belt exit cover: Brose KPR TM 005 CATPart (GlobalX
   2026-10-15 16:46, downloaded 10/19). Review data, gated like the
   206.886.197 E2 · 004: in_review, intake pending for Development's triage.

Idempotent: skips a part whose revision already holds the file. Dry run by
default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/add_1994_data_20261019.py --stage /app/uploads/_stage-1994-20261019 [--apply]
"""
import argparse
import asyncio
import hashlib
import os
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.part import Part, PartRevision, RevisionFile
from app.services.part_service import ChangelogService, RevisionService
from app.services.revision_file_service import store_revision_file

SENT_DIR = r"U:\Projects\1994\Modified Part Files\Sent to Brose\2026-10-19_GlobalX_to_Paluch"
HANDLE_FILE = "206.882.251_S00H4X-110_HANDLE-LH_toolmaker-modified_2026-10-19.stp"
HANDLE_SHA = "d6ef95fe49452e0d48468a7206e4971fa7227ed44957bacb6caa5d40d13d2c8b"
BELT_DIR = r"U:\Projects\1994\199407 Seat Belt Exit Cover\Brose Data\2026-10-15_GlobalX_from_Paluch"
BELT_FILE = "206_883_607____KPR_TM__005_____BELT_EXIT_COVER____B-RELEASE___20260528_ALLCATPART.CATPart"
BELT_SHA = "65a62a44ebcb605c31ce314a06a36c3791de4a491f617d5ae96f06e18030d592"


def load(stage, fname, sha):
    src = os.path.join(stage, fname)
    if not os.path.exists(src):
        raise SystemExit(f"missing {src}")
    with open(src, "rb") as fh:
        contents = fh.read()
    digest = hashlib.sha256(contents).hexdigest()
    if digest != sha:
        raise SystemExit(f"sha256 mismatch on {fname}: {digest}")
    return contents, digest


async def has_file(s, rev, digest):
    return (await s.execute(select(RevisionFile).where(
        RevisionFile.revision_id == rev.id, RevisionFile.file_hash == digest,
        RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712


async def article(s, project, cpn):
    return (await s.execute(select(Part).where(
        Part.project_id == project.id, Part.customer_part_number == cpn,
        Part.item_category == "article"))).scalar_one()


async def rev_named(s, part, name):
    return (await s.execute(select(PartRevision).where(
        PartRevision.part_id == part.id, PartRevision.revision_name == name))).scalar_one_or_none()


async def handle_lh(s, project, stage, user, apply):
    contents, digest = load(stage, HANDLE_FILE, HANDLE_SHA)
    part = await article(s, project, "206.882.251")
    e1 = await rev_named(s, part, "E1")
    e11 = await rev_named(s, part, "E1.1")
    label = f"206.882.251 / {part.tier1_part_number} Handle, height adjustment LH (KTX 199401, FZ-26361)"
    summary = (f"Toolmaker data, awaiting customer confirmation: {label}, modified by FZ Tools per the DFMs "
               f"(FZ data 2026-10-19), sent to Brose (Philip Paluch) via GlobalX 2026-10-19 08:12, "
               f"requested by Dale. DFM changes: sharp steel at slide entry, 0.05 mm step (not 0.1), "
               f"inner radius at handle tip. LH only, FZ did not send RH 206.882.252. "
               f"Base E1 · {e1.customer_index}. Brose not confirmed yet.")
    print(f"{part.part_number} {label}: E1 id {e1.id} (index {e1.customer_index}), "
          f"E1.1 {'exists id ' + str(e11.id) if e11 else 'will be created'}")
    if e11 and (dup := await has_file(s, e11, digest)):
        print(f"  file already on E1.1 (id {dup.id}); skip")
        return
    print(f"  attach {HANDLE_FILE} ({len(contents) / 1048576:.1f} MB) as cad/step with viewer")
    if not apply:
        return
    if e11 is None:
        e11 = await RevisionService.create_proposal(s, part.id, e1.id, summary=summary, created_by=user)
        await s.flush()
        print(f"  created {e11.revision_name} (id {e11.id})")
    rf = await store_revision_file(s, e11, HANDLE_FILE, contents, user, content_type="application/step")
    rf.cad_data = {"cad_revision": "FZ toolmaker-modified 2026-10-19",
                   "note": "Toolmaker data, awaiting Brose confirmation.",
                   "toolmaker": "FZ Tools", "fz_mold": "FZ-26361", "ktx_tool": "199401",
                   "sent": "GlobalX to Brose (Philip Paluch) 2026-10-19 08:12, requested by Dale",
                   "source": SENT_DIR + r"\02_Sent", "fz_original": SENT_DIR + r"\01_FZ_original",
                   "evidence": SENT_DIR + r"\03_Evidence"}
    await ChangelogService.log_action(
        s, part_id=part.id, revision_id=e11.id, action="metadata_updated",
        action_description="E1.1 opened for FZ toolmaker data sent to Brose, awaiting confirmation",
        performed_by=user, field_name="summary", new_value=summary)
    await s.commit()
    print(f"  attached file {rf.id}, viewer: {rf.has_viewer}")


async def belt_exit_cover(s, project, stage, user, apply):
    contents, digest = load(stage, BELT_FILE, BELT_SHA)
    part = await article(s, project, "206.883.607")
    e2 = await rev_named(s, part, "E2")
    summary = (f"Customer review data, index 005: 206.883.607 / {part.tier1_part_number} Belt exit cover "
               f"(KTX 199407), Brose KPR TM 005 CATPart (B-RELEASE 2026-05-28), Philip Paluch via GlobalX "
               f"2026-10-15 16:46, downloaded 2026-10-19. CATPart only, no STEP/drawing. Note: KPR file "
               f"type (E1 was PCA) and release date unchanged although index went 003 -> 005.")
    print(f"{part.part_number} 206.883.607 Belt exit cover: E2 {'exists id ' + str(e2.id) if e2 else 'will be created (index 005, pending triage)'}")
    if e2 and (dup := await has_file(s, e2, digest)):
        print(f"  file already on E2 (id {dup.id}); skip")
        return
    if e2 and e2.customer_index != "005":
        raise SystemExit(f"  E2 exists with index {e2.customer_index}, stop")
    print(f"  attach {BELT_FILE} ({len(contents) / 1048576:.1f} MB) as cad")
    if not apply:
        return
    if e2 is None:
        e2 = await RevisionService.receive_customer_data(
            s, part.id, "review", date(2026, 10, 15), customer_index="005", summary=summary,
            created_by=user, intake_source="customer_data")
        await s.flush()
        print(f"  created {e2.revision_name} (id {e2.id}, {e2.status})")
    rf = await store_revision_file(s, e2, BELT_FILE, contents, user)
    rf.cad_data = {"cad_revision": "KPR TM 005, B-RELEASE 2026-05-28",
                   "received": "GlobalX from Brose (Philip Paluch) 2026-10-15 16:46, downloaded 2026-10-19",
                   "source": BELT_DIR}
    await s.commit()
    print(f"  attached file {rf.id}, viewer: {rf.has_viewer}")


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
        await handle_lh(s, project, args.stage, args.user, args.apply)
        await belt_exit_cover(s, project, args.stage, args.user, args.apply)
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
