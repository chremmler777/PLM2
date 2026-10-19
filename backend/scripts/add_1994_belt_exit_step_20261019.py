"""206.883.607 Belt exit cover E2 · 005: attach the STEP AP242 KTX converted
from Brose's KPR TM 005 CATPart (SpinFire 11.11, 2026-10-19, geometry
unchanged) so the 3D viewer works; point the CATPart's stored folder at Dale's
renamed folder; drop "no STEP" from the summary. No part-data mail (Christoph:
the revision itself was already announced): the outbox row the upload queues
is removed in the same transaction. Idempotent, dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/add_1994_belt_exit_step_20261019.py --stage /app/uploads/_stage-1994-belt-step [--apply]
"""
import argparse
import asyncio
import hashlib
import os

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.mail import MailOutbox
from app.models.part import PartRevision, RevisionFile
from app.services.revision_file_service import store_revision_file

REV_ID = 2253
CATPART_FILE_ID = 138
DIR = r"U:\Projects\1994\199407 2063.883.607 Seat Belt Exit Cover\Brose Data\2026-10-15_GlobalX_from_Paluch"
FNAME = "206_883_607____KPR_TM__005_____BELT_EXIT_COVER____B-RELEASE___20260528_ALLCATPART.CATPart.stp"
SHA = "068292a6029ce7d923a6fbcef648ed468f8e2909fc5f0d1293fd8028ed397f8b"
OLD_SUMMARY_TAIL = "CATPart only, no STEP/drawing."
NEW_SUMMARY_TAIL = ("Brose sent CATPart only, no drawing; STEP AP242 converted by KTX "
                    "(SpinFire 11.11, 2026-10-19, geometry unchanged).")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    with open(os.path.join(args.stage, FNAME), "rb") as fh:
        contents = fh.read()
    if hashlib.sha256(contents).hexdigest() != SHA:
        raise SystemExit("sha256 mismatch")
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        rev = await s.get(PartRevision, REV_ID)
        assert rev.revision_name == "E2" and rev.customer_index == "005", rev.revision_name
        catpart = await s.get(RevisionFile, CATPART_FILE_ID)
        assert catpart.revision_id == REV_ID
        dup = (await s.execute(select(RevisionFile).where(
            RevisionFile.revision_id == REV_ID, RevisionFile.file_hash == SHA,
            RevisionFile.is_deleted == False))).scalar_one_or_none()  # noqa: E712
        print(f"E2 · 005 rev {REV_ID}; STEP {'already attached id ' + str(dup.id) if dup else 'will be attached'}; "
              f"CATPart source {'ok' if (catpart.cad_data or {}).get('source') == DIR else 'will be updated'}; "
              f"summary {'will be updated' if OLD_SUMMARY_TAIL in (rev.summary or '') else 'ok'}")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            return
        if not dup:
            rf = await store_revision_file(s, rev, FNAME, contents, args.user, content_type="application/step")
            rf.cad_data = {"cad_revision": "KPR TM 005, B-RELEASE 2026-05-28",
                           "note": "STEP AP242 converted by KTX from the Brose CATPart (SpinFire 11.11 / "
                                   "HOOPS Exchange 2024.5, 2026-10-19). Format conversion only, not a Brose file.",
                           "source": DIR}
            gone = await s.execute(delete(MailOutbox).where(
                MailOutbox.revision_id == REV_ID, MailOutbox.mail_status == "pending",
                MailOutbox.event == "file_uploaded"))
            print(f"attached file {rf.id}, viewer: {rf.has_viewer}; mail rows suppressed: {gone.rowcount}")
        catpart.cad_data = {**(catpart.cad_data or {}), "source": DIR}
        if OLD_SUMMARY_TAIL in (rev.summary or ""):
            rev.summary = rev.summary.replace(OLD_SUMMARY_TAIL, NEW_SUMMARY_TAIL)
        await s.commit()
        print("APPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
