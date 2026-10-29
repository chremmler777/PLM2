"""Close (reject) the FZ toolmaker proposal E1.1 (rev 2262, 10/22) on 206.881.479 Inner side shield,
superseded by Brose PCA TM 004 Tooling 20261031 (E2 · 004, add_1994_479_pca_tm004_20261029.py).
Christoph, 2026-10-29 via Ass, per Philip Paluch 10/29.

The reject has no reason field, so the close note is appended to the draft summary (logged as
metadata_updated). Standard part-data mail (Christoph: mail yes). Idempotent, dry run by default.

    docker exec -i -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python scripts/close_1994_479_e11_20261029.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.part import Part, PartRevision
from app.services.part_service import ChangelogService, RevisionService

# revision id -> Brose no.
CLOSE = {2262: "206.881.479"}
NOTE = ("Closed 2026-10-29: Superseded by Brose PCA TM 004 Tooling 20261031 (E2 · 004), per Philip Paluch "
        "10/29: with the slider the rib rotation is not necessary; the slider is needed to demold the inner edge.")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        for rev_id, cpn in CLOSE.items():
            rev = await s.get(PartRevision, rev_id)
            part = await s.get(Part, rev.part_id)
            if part.customer_part_number != cpn or rev.parent_revision_id is None:
                raise SystemExit(f"{rev_id}: not a proposal of {cpn}")
            todo = []
            if rev.status != "rejected":
                todo.append("reject")
            if NOTE not in (rev.summary or ""):
                todo.append("close note")
            print(f"{cpn} {rev.revision_name} id {rev_id} ({rev.status}): {', '.join(todo) or 'nothing to do'}")
            if not args.apply:
                continue
            if "close note" in todo:
                old = rev.summary
                rev.summary = f"{old} {NOTE}" if old else NOTE
                await ChangelogService.log_action(
                    s, part_id=part.id, revision_id=rev.id, action="metadata_updated",
                    action_description=f"{rev.revision_name} closed: superseded by Brose TM 004 Tooling (E2)",
                    performed_by=args.user, field_name="summary", old_value=old, new_value=rev.summary)
            if "reject" in todo:
                await RevisionService.reject_revision(s, rev.id, created_by=args.user)
        if args.apply:
            await s.commit()
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
