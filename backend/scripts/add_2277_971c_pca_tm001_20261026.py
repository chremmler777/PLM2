"""2277 Brose Backpanel, 206.881.971: Brose 971.C data (PCA TM 001, change
AEKOBZ01115, 2026-10-13) as the next E review level on part 2268, superseding
E2 (TM 005 B-release 2026-08-28).

Decided by Christoph 2026-10-26 via Ass: no new part, 971.C is the new state of
206.881.971. Received from Philip Paluch (Brose) via GlobalX 2026-10-13 together
with 971_D; resent unchanged by Aristotelis Papadopoulos 2026-10-26 so Dale has
it for the 971 DFM. 971_D (probably the new state of 971.B) is held until Brose
confirms. Filed gated (in_review, intake pending for Development's triage). The
2277 part data list gets the digest mail (approved, Dale needs it for the DFM).

The CATPart is 274 MB; the 100 MB upload limit is lifted for this script only.
Idempotent: skips the filing when the part already holds the file. Dry run by
default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/add_2277_971c_pca_tm001_20261026.py --stage /app/uploads/_stage-2277-971c-1026 [--apply]
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
from app.models.mail import MailOutbox
from app.models.part import Part, PartRevision, RevisionFile
from app.services import revision_file_service
from app.services.part_service import RevisionService
from app.services.revision_file_service import store_revision_file

SRC = r"U:\RFQ\RFQ25_260112_Brose Backpanel\10_Deliveries\AEKOBZ01115_2026-10-13\02_CAD"
FNAME = "206_881_971_C__PCA_TM__001_____SEAT_BACK_PANEL____AEKOBZ01115_20261013.CATPart"
SHA = "39bfb2be10e23bef60ed205f05a3968d059ced290e4915a2b51abd97aaa9364d"
SIZE = 274_424_822
CPN = "206.881.971"
INDEX = "C"
RECEIVED = date(2026, 10, 13)
SUMMARY = ("Customer review data, index C: 206.881.971 Seat Back Panel MIC, Brose 971.C, PCA TM 001, "
           "change AEKOBZ01115 2026-10-13 (RFQ stage, not a B-release). Received from Philip Paluch (Brose) "
           "via GlobalX 2026-10-13, resent identical by Aristotelis Papadopoulos 2026-10-26 for the 971 DFM "
           "(Dale). Supersedes E2 (PCA TM 005 B-release 2026-08-28). Single CATPart; Dale asked Brose 10/22 "
           "for the components as individual files (open). 971.D from the same delivery is held until Brose "
           "confirms it belongs to 971.B.")


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
                batch_id=f"2277-brose-971c-20261026-{uuid.uuid4().hex[:6]}")
            await s.flush()
            revision_file_service.MAX_FILE_SIZE = 300 * 1024 * 1024  # this file only (274 MB)
            rf = await store_revision_file(s, rev, FNAME, contents, args.user)
            rf.cad_data = {"cad_revision": "971.C, PCA TM 001, change AEKOBZ01115 2026-10-13",
                           "received": "Brose (Philip Paluch) via GlobalX 2026-10-13; resent identical "
                                       "(Aristotelis Papadopoulos, GlobalX version 2) 2026-10-26",
                           "source": SRC,
                           "note": "Single CATPart incl. components; individual files requested 10/22."}
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
