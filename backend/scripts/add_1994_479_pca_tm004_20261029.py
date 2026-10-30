"""1994 Brose Seat Trim, 206.881.479 Inner side shield (tool 199408): Brose PCA
TM 004 "TOOLING" 2026-10-31 as the next E review level on part 2280, index 004,
superseding nothing pending (E1 = TM 003 B-release 2026-05-29 is the active base).

Requested by Christoph 2026-10-29 via Ass ("brose data new revision"). Received
from Steffen Maciej (Brose) via GlobalX 2026-10-29 01:16 CET. Filed gated
(in_review, intake pending for Development's triage). The FZ toolmaker draft
E1.1 (2262, 10/22) stays as it is.

Idempotent: skips the filing when the part already holds the file. Dry run by
default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/add_1994_479_pca_tm004_20261029.py --stage /app/uploads/_stage-1994-479-1029 [--apply] [--no-mail]
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
from app.services.part_service import RevisionService
from app.services.revision_file_service import store_revision_file

SRC = r"U:\Projects\1994\Modified Part Files\New from Brose"
FNAME = "206_881_479____PCA_TM__004_____INNER_SIDE_COVER___TOOLING_____20261031.CATPart"
SHA = "4fdf1c7ec26ea5d16845d155a6595d5ff43f32281c91ce5828f286b96c1dec8e"
SIZE = 13_906_101
CPN = "206.881.479"
INDEX = "004"
RECEIVED = date(2026, 10, 29)
SUMMARY = ("Customer review data, index 004: 206.881.479 Inner side shield (KTX 199408), Brose PCA TM 004 "
           "\"TOOLING\" 2026-10-31. Received from Steffen Maciej (Brose) via GlobalX 2026-10-29. "
           "Philip Paluch (Brose) 10/29: with the slider taken into account the rib rotation is not "
           "necessary; the slider is needed, otherwise the inner edge cannot be demolded. "
           "Base E1 (PCA TM 003 B-release 2026-05-29).")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--project", default="1994")
    ap.add_argument("--no-mail", action="store_true")
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
                batch_id=f"1994-brose-479-20261029-{uuid.uuid4().hex[:6]}")
            await s.flush()
            rf = await store_revision_file(s, rev, FNAME, contents, args.user)
            rf.cad_data = {"cad_revision": "PCA TM 004 TOOLING 2026-10-31",
                           "received": "Brose (Steffen Maciej) via GlobalX 2026-10-29 01:16 CET",
                           "source": SRC}
            await s.flush()
            if args.no_mail:
                for row in (await s.execute(select(MailOutbox).where(
                        MailOutbox.revision_id == rev.id, MailOutbox.mail_status == "pending"))).scalars():
                    await s.delete(row)
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
