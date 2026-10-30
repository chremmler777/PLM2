"""1994: the three pending Brose E2 indexes are official and have no impact (Christoph 2026-10-28).
Cancel engineering review CR-2026-0008 (206.887.233, still in scoping) and triage all three
intakes as administrative, which activates E2 at once. Runs as Christoph (user 14) through the
same service calls and checks as the API. Part-data mails go out as usual (user OK).

Dry run by default: everything runs, then rolls back.

    docker exec -i -e PYTHONPATH=/app -w /app compose-plm2-backend-1 \
        python /tmp/activate_1994_e2_admin_20261028.py [--apply]
"""
import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.change import ChangeRequest
from app.models.entities import User
from app.models.mail import MailOutbox
from app.models.part import Part, PartRevision
from app.models.revision_intake import RevisionIntake
from app.services.change_service import ChangeService
from app.services.early_stage_service import EarlyStageService
from app.services.revision_intake_service import RevisionIntakeService

USER = 14  # christoph.demmler
CHANGE_ID = 8  # CR-2026-0008, engineering review of 206.887.233 E2
CANCEL_REASON = ("No impact: official Brose data, activated administratively "
                 "(Christoph 2026-10-28).")
REASON = "Official Brose data, no impact (Christoph 2026-10-28)."
INTAKES = {2: "206.886.197", 3: "206.883.607", 4: "206.887.233"}


async def main(apply: bool) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        user = await s.get(User, USER)
        print(f"user {user.username} role {user.role} effective {user.effective_role}")
        first_mail = (await s.execute(select(MailOutbox.id).order_by(MailOutbox.id.desc()).limit(1))).scalar() or 0

        change = await s.get(ChangeRequest, CHANGE_ID)
        print(f"{change.change_number} {change.status}: {change.title}")
        if change.status != "cancelled":
            refusal = await EarlyStageService.transition_refusal(s, change, user, "cancelled")
            if refusal:
                raise SystemExit(f"cancel refused: {refusal}")
            await ChangeService.transition(s, change, "cancelled", USER, cancellation_reason=CANCEL_REASON)
            print(f"  -> cancelled")

        for iid, cpn in INTAKES.items():
            intake = await s.get(RevisionIntake, iid)
            rev = await s.get(PartRevision, intake.revision_id)
            part = await s.get(Part, intake.part_id)
            if part.customer_part_number != cpn:
                raise SystemExit(f"intake {iid} is on {part.customer_part_number}, expected {cpn}")
            print(f"intake {iid} {cpn} {rev.revision_name} (rev {rev.id}, index {rev.customer_index}): "
                  f"{intake.status}, route {intake.route}")
            if intake.activated_at is not None:
                print("  already active; skip")
                continue
            await RevisionIntakeService.decide(s, intake, "administrative", user, reason=REASON)
            await s.flush()
            await s.refresh(part)
            active = await s.get(PartRevision, part.active_revision_id)
            print(f"  -> {intake.status} administrative, active now {active.revision_name} (rev {active.id})")

        await s.flush()
        mails = (await s.execute(select(MailOutbox.event, MailOutbox.part_id).where(
            MailOutbox.id > first_mail))).all()
        print(f"mail rows queued: {len(mails)} {sorted(m.event for m in mails)}")
        if apply:
            await s.commit()
            print("APPLIED.")
        else:
            await s.rollback()
            print("DRY RUN - rolled back.")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    asyncio.run(main(ap.parse_args().apply))
