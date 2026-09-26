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
approved task; an R/A row still owed an active task. Only a TRUE deviation
add (a row in neither the routing snapshot nor the template) of a stage
that has already passed is flagged late for the lead (active, no step,
never waived on the department's behalf). A row the snapshot or template
gave a passed stage that never got its task keeps the earlier behaviour:
waived, with a note. An S/C row a noted task; an owed R/A row of a finished
change a waived task. Each repaired change gets a 'routing_repaired'
changelog entry (system action).

Changes swept: every change with an active change-scoped instance, plus
live changes whose instance has completed (a row added after every stage
passed gets its task there). Each late row is printed on its own line,
also when the repair completes the instance.
"""
import argparse
import asyncio
import sys

from sqlalchemy import select

from app.models import AsyncSessionLocal
from app.models.change import ChangeAssessment, ChangeRequest
from app.models.workflow import Department, WfInstance

FINISHED = ("released", "closed", "rejected", "cancelled")


async def _lines(s, change, ids: list[int], what: str) -> list[str]:
    if not ids:
        return []
    rows = (await s.execute(
        select(ChangeAssessment, Department.name)
        .join(Department, Department.id == ChangeAssessment.department_id)
        .where(ChangeAssessment.id.in_(ids))
        .order_by(ChangeAssessment.id))).all()
    return [f"    {what}: {change.change_number} assessment {a.id} "
            f"{name} {a.rasic_letter} stage {a.stage_order}"
            for a, name in rows]


async def sweep(apply: bool) -> int:
    from app.services.change_routing_service import ChangeRoutingService
    from app.services.change_service import ChangeService

    async with AsyncSessionLocal() as s:
        active = set((await s.execute(
            select(WfInstance.change_id).where(
                WfInstance.change_id.isnot(None),
                WfInstance.status == "active"))).scalars().all())
        completed_live = set((await s.execute(
            select(WfInstance.change_id)
            .join(ChangeRequest, ChangeRequest.id == WfInstance.change_id)
            .where(WfInstance.status == "completed",
                   ChangeRequest.status.notin_(FINISHED))
        )).scalars().all())
        change_ids = sorted(active | completed_live)

    total = 0
    touched = 0
    late_total = 0
    for cid in change_ids:
        # One transaction per change: a failure on one change neither
        # blocks nor half-writes another.
        async with AsyncSessionLocal() as s:
            try:
                change = await ChangeService.get_change(s, cid)
                if change is None:
                    continue
                # The late / waived ids come straight from the repair, so a
                # repair that completes the instance still lists them.
                report: dict = {}
                repaired = await ChangeRoutingService.repair_stage_tasks(
                    s, change, None, report=report)
                if repaired:
                    touched += 1
                    total += len(repaired)
                    late = report.get("late", [])
                    late_total += len(late)
                    print(f"{change.change_number} (id {cid}, {change.status}): "
                          f"{len(repaired)} row(s) {repaired}")
                    for line in await _lines(s, change, late,
                                             "LATE, owed, flagged for the lead"):
                        print(line)
                    for line in await _lines(s, change, report.get("waived_passed", []),
                                             "waived, stage passed (standard row)"):
                        print(line)
                if apply:
                    await s.commit()
                else:
                    await s.rollback()
            except Exception as exc:  # noqa: BLE001 - report and go on
                await s.rollback()
                print(f"!! change id {cid}: {exc}", file=sys.stderr)
    mode = "applied" if apply else "dry run, nothing written"
    print(f"{len(change_ids)} change(s) swept; {touched} need(ed) repair, "
          f"{total} row(s), {late_total} late ({mode})")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="write the repair (default: dry run, rolled back)")
    args = ap.parse_args()
    asyncio.run(sweep(args.apply))


if __name__ == "__main__":
    main()
