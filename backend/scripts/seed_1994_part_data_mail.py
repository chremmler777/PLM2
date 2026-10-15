"""Seed the 1994 part data mail list (8 people, list "part_data") and,
with --backfill, enqueue today's E1.1 iterations (FZ toolmaker data sent to
Brose 2026-10-15) so the first digest mails them. Idempotent: an address
already on the list is kept (re-activated if it was inactive); a revision
already in the outbox as "created" is not enqueued again. Dry run by default.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \
        python scripts/seed_1994_part_data_mail.py [--backfill] [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Project
from app.models.mail import LIST_PART_DATA, MailOutbox, MailRecipient
from app.models.part import PartRevision

RECIPIENTS = [
    ("cody.hrtyanski", "Cody Hrtyanski"),
    ("christoph.demmler", "Christoph Demmler"),
    ("christopher.holmes", "Christopher Holmes"),
    ("dale.perry", "Dale Perry"),
    ("russ.addison", "Russ Addison"),
    ("apurva.mhetre", "Apurva Mhetre"),
    ("george.richardson", "George Richardson"),
    ("karl.limburg", "Karl Limburg"),
]
DOMAIN = "us.ktx.group"
BACKFILL_REVISIONS = (2248, 2249, 2250, 2251)
BACKFILL_EVENT = "created"
BACKFILL_SUMMARY = ("E1.1 toolmaker data (FZ, per DFM) sent to Brose via GlobalX 2026-10-15, "
                    "awaiting customer confirmation")


async def seed(s, project_code: str, backfill: bool, user_id: int | None) -> list[str]:
    """Writes into session `s` (no commit); returns what it did, line by line."""
    out: list[str] = []
    project = (await s.execute(select(Project).where(Project.code == project_code))).scalar_one()
    existing = {r.email: r for r in (await s.execute(select(MailRecipient).where(
        MailRecipient.project_id == project.id, MailRecipient.list_key == LIST_PART_DATA))).scalars()}
    out.append(f"== {project.code} {project.name}: list {LIST_PART_DATA}")
    for local, name in RECIPIENTS:
        email = f"{local}@{DOMAIN}"
        row = existing.get(email)
        if row is None:
            s.add(MailRecipient(project_id=project.id, list_key=LIST_PART_DATA, email=email,
                                display_name=name, active=True))
            out.append(f"   + {email} ({name})")
        elif not row.active:
            row.active = True
            out.append(f"   ~ {email} re-activated")
        else:
            out.append(f"   = {email} already on the list")
    if backfill:
        out.append(f"== backfill {BACKFILL_EVENT}: revisions {', '.join(map(str, BACKFILL_REVISIONS))}")
        for rid in BACKFILL_REVISIONS:
            rev = await s.get(PartRevision, rid)
            if rev is None:
                out.append(f"   ! revision {rid} not found")
                continue
            done = (await s.execute(select(MailOutbox.id).where(
                MailOutbox.revision_id == rid, MailOutbox.event == BACKFILL_EVENT))).first()
            if done is not None:
                out.append(f"   = revision {rid} ({rev.revision_name}, part {rev.part_id}) already enqueued")
                continue
            s.add(MailOutbox(project_id=project.id, part_id=rev.part_id, revision_id=rid,
                             event=BACKFILL_EVENT, summary=BACKFILL_SUMMARY,
                             performed_by=user_id or rev.created_by, mail_status="pending"))
            out.append(f"   + revision {rid} ({rev.revision_name}, part {rev.part_id})")
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="1994")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--user", type=int, default=None,
                    help="performed_by on backfilled rows (default: the revision's creator)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        for line in await seed(s, args.project, args.backfill, args.user):
            print(line)
        if args.apply:
            await s.commit()
            print("\nAPPLIED.")
        else:
            await s.rollback()
            print("\nDRY RUN - nothing written.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
