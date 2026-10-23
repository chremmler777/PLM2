"""2277 Brose Backpanel, 206.881.972.A: Brose FEA_CM data 2026-10-15 (G01 cover,
TM 005) as the next E review level, and the 2277 part data mail list (approved
by Christoph 2026-10-23 via Ass: "same mail list as 1994, ok to import").

Received from Philip Paluch (Brose) via GlobalX 2026-10-23. Not a B-release.
The DFM basis Brose promised in the 10/19 "Backpanel latest CAD review"; DFM
meeting starts 10/28. Only the G01 model came, no PCA part file. Filed gated
(in_review, intake pending for Development's triage).

The list is copied from the active 1994 list and seeded first, in the same
session, so the filing queues the digest mail. The CATPart is 180 MB; the 100 MB
upload limit is lifted for this script only (as for the E1 STEP). The held
08-28 B-release package (add_2277_brose_release_20261021.py) is not touched.
Idempotent: skips the filing when the part already holds the file. Dry run by
default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/add_2277_972a_fea_cm_20261023.py --stage /app/uploads/_stage-2277-972a-1023 [--apply]
"""
import argparse
import asyncio
import hashlib
import os
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.mail import LIST_PART_DATA, MailOutbox, MailRecipient
from app.models.part import Part, PartRevision, RevisionFile
from app.services import revision_file_service
from app.services.part_service import RevisionService
from app.services.revision_file_service import store_revision_file

SRC = r"U:\RFQ\RFQ25_260112_Brose Backpanel\10_Deliveries\FEA-CM_2026-10-15\02_CAD"
FNAME = "206_881_972_A__G01_TM__005_____COVER_BACK_PANEL___FEA_CM______20261015.CATPart"
SHA = "19b269f9c005b4aaff6909d94c971322200b82be54bced2d9b1b1af8afc5afe5"
SIZE = 179_998_944
CPN = "206.881.972.A"
INDEX = "005"
RECEIVED = date(2026, 10, 23)
SUMMARY = ("Customer review data, index 005: 206.881.972.A Seat Back Panel PS, Brose G01 cover model "
           "TM 005, status FEA_CM 2026-10-15 (not a B-release), received from Philip Paluch (Brose) via "
           "GlobalX 2026-10-23. The 972.A CAD Brose promised in the 10/19 \"Backpanel latest CAD review\" "
           "as DFM basis; DFM meeting starts 10/28 (Cody). Only the G01 (cover) model was sent, no PCA "
           "part file this time. Previous: G01/PCA TM 003 B-release 2026-08-28.")


async def seed_list(s, project, apply):
    src = (await s.execute(select(Project).where(Project.code == "1994"))).scalar_one()
    people = (await s.execute(select(MailRecipient).where(
        MailRecipient.project_id == src.id, MailRecipient.list_key == LIST_PART_DATA,
        MailRecipient.active.is_(True)).order_by(MailRecipient.id))).scalars().all()
    have = {r.email: r for r in (await s.execute(select(MailRecipient).where(
        MailRecipient.project_id == project.id, MailRecipient.list_key == LIST_PART_DATA))).scalars()}
    print(f"== {project.code} list {LIST_PART_DATA} from 1994 ({len(people)} active)")
    for p in people:
        row = have.get(p.email)
        if row is None:
            print(f"   + {p.email} ({p.display_name})")
            if apply:
                s.add(MailRecipient(project_id=project.id, list_key=LIST_PART_DATA, email=p.email,
                                    display_name=p.display_name, active=True))
        elif not row.active:
            print(f"   ~ {p.email} re-activated")
            if apply:
                row.active = True
        else:
            print(f"   = {p.email} already on the list")
    if apply:
        await s.flush()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--project", default="2277")
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = os.path.join(args.stage, FNAME)
    if not os.path.exists(src):
        raise SystemExit(f"missing {src}")
    with open(src, "rb") as fh:
        contents = fh.read()
    digest = hashlib.sha256(contents).hexdigest()
    if digest != SHA or len(contents) != SIZE:
        raise SystemExit(f"{FNAME}: sha256 {digest}, {len(contents)} bytes, expected {SHA}, {SIZE}")

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == args.project))).scalar_one()
        part = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.customer_part_number == CPN,
            Part.item_category == "article"))).scalar_one()
        majors = (await s.execute(select(PartRevision.revision_name, PartRevision.status).where(
            PartRevision.part_id == part.id, PartRevision.parent_revision_id.is_(None))
            .order_by(PartRevision.id))).all()
        print(f"{part.part_number} {CPN} (id {part.id}): majors {', '.join(f'{n} {st}' for n, st in majors)}")
        await seed_list(s, project, args.apply)
        dup = (await s.execute(select(RevisionFile).join(PartRevision).where(
            PartRevision.part_id == part.id, RevisionFile.file_hash == digest,
            RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712
        if dup:
            print(f"file already filed (file {dup.id}, revision {dup.revision_id}); skip")
        else:
            print(f"new E level, index {INDEX} (pending triage) + {FNAME} ({len(contents) / 1048576:.1f} MB)")
        if args.apply and not dup:
            rev = await RevisionService.receive_customer_data(
                s, part.id, "review", RECEIVED, customer_index=INDEX, summary=SUMMARY,
                created_by=args.user, intake_source="customer_data",
                batch_id=f"2277-brose-972a-20261023-{uuid.uuid4().hex[:6]}")
            await s.flush()
            revision_file_service.MAX_FILE_SIZE = 200 * 1024 * 1024  # this file only, approved 10/23
            rf = await store_revision_file(s, rev, FNAME, contents, args.user)
            rf.cad_data = {"cad_revision": "G01 TM 005, FEA_CM 2026-10-15 (not a B-release)",
                           "received": "Brose (Philip Paluch) via GlobalX 2026-10-23", "source": SRC,
                           "note": "Only the G01 cover model; no PCA part file this time."}
            await s.commit()
            print(f"  created {rev.revision_name} (id {rev.id}, {rev.status}), file {rf.id}")
            rows = (await s.execute(select(MailOutbox.id, MailOutbox.event, MailOutbox.mail_status).where(
                MailOutbox.revision_id == rev.id))).all()
            print(f"  outbox: {rows}")
        elif args.apply:
            await s.commit()
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
