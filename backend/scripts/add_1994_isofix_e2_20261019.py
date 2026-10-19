"""206.887.233 ISOFIX Cover (KTX 199403, FZ-26365): Brose PCA TM 002,
B-RELEASE 2026-10-19 (GlobalX 2026-10-19 10:14, Philip Paluch, Brose doc
P007193 / D605064-A) as E2 · 002, pending triage, with the Brose CATPart and
the KTX STEP conversion (viewer). Brose's 002 takes over the FZ toolmaker
data of E1.1 (geometry check 2026-10-19: 89 of 92 FZ change points match 002
within 0.05 mm, the other 3 at 0.054-0.056 mm from both), so E2 is linked as
the promotion of E1.1: when Development activates E2, E1.1 becomes approved.
Idempotent, dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/add_1994_isofix_e2_20261019.py --stage /app/uploads/_stage-1994-isofix [--apply]
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
from app.services.part_service import RevisionService
from app.services.revision_file_service import store_revision_file

DIR = r"U:\Projects\1994\Modified Part Files\New from Brose"
BASE = "P007193_D605064-A_206_887_233____PCA_TM__002_____ISOFIX_COVER_______B-RELEASE___20261019_1_10_19_2026 16_54_13.CATPart"
FILES = [
    (BASE, "e6475107a334fb1da93f31528e76c1c89f88f5c7eca835d34c1dd8ab03aef9b9", None,
     "Brose original (GlobalX 2026-10-19 10:14, P007193 / D605064-A)"),
    (BASE + ".stp", "cd5c2b62299caa40929a21131ddbcdbdcd284e8ebe1ce25b0ed8e210ab39eda4", "application/step",
     "STEP AP242 converted by KTX from the Brose CATPart (SpinFire 11.11 / HOOPS Exchange 2024.5, "
     "2026-10-19). Format conversion only, not a Brose file."),
]
CHECK = ("Geometry check 2026-10-19: 89 of 92 FZ change points match PCA TM 002 within 0.05 mm "
         "(other 3 at 0.054-0.056 mm from both).")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    blobs = []
    for name, sha, ctype, note in FILES:
        with open(os.path.join(args.stage, name), "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != sha:
            raise SystemExit(f"sha256 mismatch: {name}")
        blobs.append((name, data, ctype, note))
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        project = (await s.execute(select(Project).where(Project.code == "1994"))).scalar_one()
        part = (await s.execute(select(Part).where(
            Part.project_id == project.id, Part.customer_part_number == "206.887.233",
            Part.item_category == "article"))).scalar_one()
        e11 = (await s.execute(select(PartRevision).where(
            PartRevision.part_id == part.id, PartRevision.revision_name == "E1.1"))).scalar_one()
        e2 = (await s.execute(select(PartRevision).where(
            PartRevision.part_id == part.id, PartRevision.revision_name == "E2"))).scalar_one_or_none()
        print(f"{part.part_number} 206.887.233 / {part.tier1_part_number} ISOFIX Cover: "
              f"E2 {'exists id ' + str(e2.id) + ' (' + str(e2.customer_index) + ')' if e2 else 'will be created (002, pending triage, promotion of E1.1)'}")
        if e2 and e2.customer_index != "002":
            raise SystemExit("E2 exists with another index, stop")
        if not args.apply:
            print("\nDRY RUN - nothing written.")
            return
        if e2 is None:
            summary = (f"Customer B-Release 2026-10-19, index 002: 206.887.233 / {part.tier1_part_number} ISOFIX Cover "
                       f"(KTX 199403), Brose PCA TM 002 (P007193 / D605064-A), Philip Paluch via GlobalX "
                       f"2026-10-19 10:14. Takes over the FZ toolmaker data of E1.1 (FZ-26365). {CHECK} "
                       f"Brose sent CATPart only, no drawing; STEP converted by KTX.")
            e2 = await RevisionService.receive_customer_data(
                s, part.id, "review", date(2026, 10, 19), customer_index="002", summary=summary,
                created_by=args.user, intake_source="customer_data", promoted_from_revision_id=e11.id)
            await s.flush()
            print(f"created E2 id {e2.id} ({e2.status})")
        have = set((await s.execute(select(RevisionFile.file_hash).where(
            RevisionFile.revision_id == e2.id, RevisionFile.is_deleted == False))).scalars())  # noqa: E712
        for name, data, ctype, note in blobs:
            if hashlib.sha256(data).hexdigest() in have:
                print(f"  {name[:40]}… already attached")
                continue
            rf = await store_revision_file(s, e2, name, data, args.user, content_type=ctype)
            rf.cad_data = {"cad_revision": "PCA TM 002, B-RELEASE 2026-10-19", "note": note, "source": DIR}
            print(f"  attached file {rf.id} ({len(data) / 1048576:.1f} MB), viewer: {rf.has_viewer}")
        if "Adopted by Brose as E2 · 002" not in (e11.summary or ""):
            e11.summary = (e11.summary or "") + f" Adopted by Brose as E2 · 002 (PCA TM 002, 2026-10-19). {CHECK}"
        await s.commit()
        print("APPLIED.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
