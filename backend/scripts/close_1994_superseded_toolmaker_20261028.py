"""Close (reject) the toolmaker-modified 1994 drafts superseded by the FZ 2026-10-28 data (E1.3,
see add_1994_fz_toolmaker_20261028.py): the 10/15 E1.1 and 10/22 E1.2 on 206.881.800, 206.881.799
(E1.2 = options 1 + 2) and 206.885.967. Christoph, 2026-10-28. Brose E-levels are not touched.

The reject has no reason field, so the close note is appended to the draft summary (logged as
metadata_updated). No part-data mail (requested): the outbox rows the reject queues are removed in
the same transaction. Idempotent, dry run by default.

    docker exec -i -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python /tmp/close_1994_superseded_toolmaker_20261028.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.mail import MailOutbox
from app.models.part import Part, PartRevision
from app.services.part_service import ChangelogService, RevisionService

# revision id -> Brose no. (E1.1 10/15, E1.2 10/22)
CLOSE = {2250: "206.881.800", 2259: "206.881.800", 2251: "206.881.799", 2264: "206.881.799",
         2248: "206.885.967", 2257: "206.885.967"}
NOTE = ("Closed 2026-10-28: Superseded by FZ 2026-10-28 version (sent to Brose 2026-10-28). Brose 10/26-10/27 "
        "(Steffen Maciej): 967 shortened clip not accepted, keep original; 800/799 ribs too thin, use Brose design.")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=14)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        first_mail = (await s.execute(select(func.coalesce(func.max(MailOutbox.id), 0)))).scalar_one()
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
                    action_description=f"{rev.revision_name} closed: superseded by FZ 2026-10-28 data",
                    performed_by=args.user, field_name="summary", old_value=old, new_value=rev.summary)
            if "reject" in todo:
                await RevisionService.reject_revision(s, rev.id, created_by=args.user)
        if args.apply:
            await s.flush()
            gone = await s.execute(delete(MailOutbox).where(
                MailOutbox.id > first_mail, MailOutbox.part_id.in_(
                    select(PartRevision.part_id).where(PartRevision.id.in_(CLOSE))),
                MailOutbox.mail_status == "pending"))
            print(f"mail rows suppressed: {gone.rowcount}")
            await s.commit()
        print("APPLIED." if args.apply else "\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
