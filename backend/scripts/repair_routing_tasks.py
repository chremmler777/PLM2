"""Admin sweep: every assessment row of a started routing stage gets its
engine task (ChangeRoutingService.repair_stage_tasks), on every change with
an active change-scoped workflow instance.

    docker exec -i -e PYTHONPATH=/app <backend container> \
        python scripts/repair_routing_tasks.py            # dry run (default)
    docker exec -i -e PYTHONPATH=/app <backend container> \
        python scripts/repair_routing_tasks.py --apply    # write

Run after the migration, dry run first. The dry run performs the same
repair per change inside a transaction and rolls it back, so what it prints
is exactly what --apply would write. Idempotent: a second --apply (and the
dry run after it) finds nothing to repair.

What a repaired row gets (see repair_stage_tasks): an answered row an
approved task; an R/A row still owed an active task, flagged for the lead
when its stage has already passed (never waived on the department's
behalf); an S/C row a noted task; an owed R/A row of a finished change a
waived task. Each repaired change gets a 'routing_repaired' changelog entry
(system action).
"""
import argparse
import asyncio
import sys

from sqlalchemy import select

from app.models import AsyncSessionLocal
from app.models.change import ChangeAssessment
from app.models.workflow import WfInstance, WfInstanceTask


async def sweep(apply: bool) -> int:
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService

    async with AsyncSessionLocal() as s:
        change_ids = sorted(set((await s.execute(
            select(WfInstance.change_id).where(
                WfInstance.change_id.isnot(None),
                WfInstance.status == "active"))).scalars().all()))

    total = 0
    touched = 0
    for cid in change_ids:
        # One transaction per change: a failure on one change neither
        # blocks nor half-writes another.
        async with AsyncSessionLocal() as s:
            try:
                change = await ChangeService.get_change(s, cid)
                if change is None:
                    continue
                repaired = await ChangeRoutingService.repair_stage_tasks(s, change, None)
                late = []
                if repaired:
                    inst = await ChangeRoutingService.lock_instance(s, cid)
                    late = (await s.execute(
                        select(ChangeAssessment.id)
                        .join(WfInstanceTask,
                              WfInstanceTask.id == ChangeAssessment.wf_instance_task_id)
                        .where(ChangeAssessment.id.in_(repaired),
                               WfInstanceTask.status == "active",
                               WfInstanceTask.is_actionable.is_(True),
                               WfInstanceTask.step_id.is_(None),
                               WfInstanceTask.stage_order
                               < (inst.current_stage_order if inst else 0))
                    )).scalars().all()
                if repaired:
                    touched += 1
                    total += len(repaired)
                    print(f"{change.change_number} (id {cid}, {change.status}): "
                          f"{len(repaired)} row(s) {repaired}"
                          + (f"; late, flagged for the lead: {list(late)}"
                             if late else ""))
                if apply:
                    await s.commit()
                else:
                    await s.rollback()
            except Exception as exc:  # noqa: BLE001 - report and go on
                await s.rollback()
                print(f"!! change id {cid}: {exc}", file=sys.stderr)
    mode = "applied" if apply else "dry run, nothing written"
    print(f"{len(change_ids)} change(s) with an active instance; "
          f"{touched} need(ed) repair, {total} row(s) ({mode})")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the repair (default: dry run, rolled back)")
    args = ap.parse_args()
    asyncio.run(sweep(args.apply))


if __name__ == "__main__":
    main()
