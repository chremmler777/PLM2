"""Verify that every in-flight change can still progress (ECR-solid, lane L7).

Read-only: runs in one session that is rolled back at the end, so nothing
it touches is written. For every change that is not closed or cancelled:

  - the next hop (ChangeService.next_step_target) and the cockpit's
    why-blocked rows (next_step_missing): a HARD row must name an exit or
    an owner, a SOFT row its rule (an override lifts it), so no change is
    held with nobody able to move it (a dead end);
  - a dry run of that hop as an admin (inside a savepoint, rolled back):
    'ok', or the refusal and whether it is HARD (no override) or SOFT;
  - the read side of every stage the branch touched loads: the validation
    and release states, the hours, the validation issues, the index
    follow-ups.

Usage (in the backend container):
    python scripts/verify_inflight_changes.py [--all]
--all also lists the closed and cancelled changes (the hours window).
Exit code 1 when any change is at a dead end or a read fails.
"""
import asyncio
import sys
import traceback

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import ChangeRequest, User
from app.models.database import AsyncSessionLocal, engine

engine.echo = False      # the report, not the SQL

FINAL = ("closed", "cancelled")


async def _admin(session) -> User:
    u = (await session.execute(select(User).where(User.role == "admin",
                                                  User.is_active.is_(True))
                               .order_by(User.id).limit(1))).scalar_one()
    return u


async def _reads(session, change, admin) -> list[str]:
    """Load every read the branch added or changed; the failures, in words."""
    from app.services.hours_service import HoursService
    from app.services.release_service import ReleaseService
    from app.services.validation_issue_service import ValidationIssueService
    from app.services.validation_service import ValidationService
    errors = []
    for name, coro in (
            ("validation", lambda: ValidationService.state(session, change, ensure=False)),
            ("release", lambda: ReleaseService.state(session, change, admin)),
            ("hours", lambda: HoursService.state(session, change, admin)),
            ("issues", lambda: ValidationIssueService.list_issues(session, change)),
            ("concessions", lambda: ValidationIssueService.active_concessions(session, change))):
        try:
            async with session.begin_nested() as sp:
                await coro()
                await sp.rollback()
        except Exception as e:      # noqa: BLE001  (report every failure)
            errors.append(f"{name}: {type(e).__name__}: {e}")
    return errors


async def _dry_run(session, change, to, admin) -> str:
    from app.services.change_service import ChangeService, DeviationRequired
    try:
        async with session.begin_nested() as sp:
            await ChangeService.transition(session, change, to, admin.id,
                                           reason="verify dry run")
            await sp.rollback()
        return "ok"
    except DeviationRequired as e:
        return f"SOFT: {str(e)[:160]}"
    except Exception as e:          # noqa: BLE001
        return f"HARD: {str(e)[:160]}"
    finally:
        await session.refresh(change)


async def main(show_all: bool) -> int:
    from app.services.change_service import ChangeService
    bad = 0
    async with AsyncSessionLocal() as session:
        admin = await _admin(session)
        changes = (await session.execute(
            select(ChangeRequest).options(
                selectinload(ChangeRequest.impacted_items),
                selectinload(ChangeRequest.assessments),
                selectinload(ChangeRequest.gates),
                selectinload(ChangeRequest.transition_deviations))
            .order_by(ChangeRequest.id))).scalars().all()
        print(f"{'change':14} {'status':16} {'next':16} result / why-blocked")
        for c in changes:
            if c.status in FINAL and not show_all:
                continue
            try:
                nxt = await ChangeService.next_step_missing(session, c)
            except Exception:       # noqa: BLE001
                print(f"{c.change_number:14} {c.status:16} {'-':16} NEXT-STEP FAILED")
                traceback.print_exc()
                bad += 1
                continue
            reads = await _reads(session, c, admin)
            to = nxt["to"] if nxt else None
            result = await _dry_run(session, c, to, admin) if to else "final"
            items = (nxt or {}).get("items", [])
            dead = [i["key"] for i in items if i["kind"] == "hard"
                    and not i.get("exits") and not i.get("who")]
            rows = ", ".join(f"{i['kind']}:{i['key']}" for i in items) or "-"
            flag = ""
            if dead:
                flag += f"  DEAD END {dead}"
            if reads:
                flag += f"  READ FAILED {reads}"
            bad += bool(dead or reads)
            print(f"{c.change_number:14} {c.status:16} {to or '-':16} {result}")
            print(f"{'':48} rows: {rows}{flag}")
        await session.rollback()
    print(f"\n{len(changes)} changes read, {bad} with a problem")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--all" in sys.argv)))
