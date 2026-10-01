"""F-06: the ECN check workflows routed two stage-3 steps to retired departments.

"ECN Implementation (Article)" and "ECN Implementation (Tool)" (seeded
2026-07) give "Implement tool change" to Production (R) and "Update master
data & logistics" to Logistics (R). Both departments are retired, nobody is a
member, so those tasks reach nobody and only an admin acting as themselves can
finish them. Fixed in place (no stage is deleted, so running instances keep
their steps), the same way wf_seed_service now seeds them:

    Implement tool change            R Production   -> R Tool Engineer
                                     A Tool Engineer -> A Project Manager
    Update master data & logistics   R Logistics    -> R Scheduling

Every template of those two names is fixed (prod holds a second, unused copy
of each). Each changed template gets version + 1 and a wf_template_history
snapshot, as the workflow designer writes. Running instances pick the new
departments up when they reach stage 3; tasks already created are not touched
(the run prints any still open for a retired department).

Dry run by default; --apply writes in one transaction. Idempotent.

    docker exec -i -e PYTHONPATH=/app compose-plm2-backend-1 \\
        python scripts/fix_ecn_retired_departments.py [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.models.entities import User
from app.models.workflow import (
    Department, WfInstance, WfInstanceTask, WfStage, WfStep, WfStepRasic, WfTemplate,
    WfTemplateHistory,
)

TEMPLATES = ("ECN Implementation (Article)", "ECN Implementation (Tool)")
# step name -> [(old department, old letter, new department, new letter)], in order
FIXES = {
    "Implement tool change": [("Production", "R", "Tool Engineer", "R"),
                              ("Tool Engineer", "A", "Project Manager", "A")],
    "Update master data & logistics": [("Logistics", "R", "Scheduling", "R")],
}
NOTE = ("F-06 (TOC-PLM-06): retired departments replaced. Implement tool change: "
        "R Tool Engineer, A Project Manager (was R Production, A Tool Engineer). "
        "Update master data & logistics: R Scheduling (was R Logistics).")


def snapshot(t: WfTemplate, names: dict[int, str]) -> dict:
    return {
        "id": t.id, "name": t.name, "description": t.description, "version": t.version,
        "stages": [{
            "stage_order": st.stage_order, "name": st.name,
            "steps": [{
                "step_name": sp.step_name, "position_in_stage": sp.position_in_stage,
                "rasic": [{"department_id": r.department_id, "rasic_letter": r.rasic_letter,
                           "department_name": names.get(r.department_id)}
                          for r in sorted(sp.rasic_assignments, key=lambda r: (r.rasic_letter, r.id))],
            } for sp in sorted(st.steps, key=lambda x: x.position_in_stage)],
        } for st in sorted(t.stages, key=lambda x: x.stage_order)],
    }


async def run(apply: bool, actor_username: str) -> int:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        actor = (await s.execute(select(User).where(User.username == actor_username))).scalar_one_or_none()
        if actor is None:
            print(f"ABORT: user {actor_username!r} not found")
            return 2
        depts = {d.name: d for d in (await s.execute(select(Department))).scalars()}
        names = {d.id: d.name for d in depts.values()}
        for needed in ("Tool Engineer", "Project Manager", "Scheduling"):
            if needed not in depts or not depts[needed].is_active:
                print(f"ABORT: department {needed!r} missing or retired")
                return 2
        templates = (await s.execute(
            select(WfTemplate).where(WfTemplate.name.in_(TEMPLATES)).options(
                selectinload(WfTemplate.stages).selectinload(WfStage.steps)
                .selectinload(WfStep.rasic_assignments)).order_by(WfTemplate.id))).scalars().all()
        print(f"mode {'APPLY' if apply else 'DRY RUN'}; templates: "
              + ", ".join(f"{t.id} {t.name} v{t.version}" for t in templates))
        changed_any = 0
        for t in templates:
            changes = []
            for st in t.stages:
                for sp in st.steps:
                    for old_d, old_l, new_d, new_l in FIXES.get(sp.step_name, []):
                        row = next((r for r in sp.rasic_assignments
                                    if names.get(r.department_id) == old_d and r.rasic_letter == old_l), None)
                        if row is None:
                            continue
                        row.department_id = depts[new_d].id
                        row.rasic_letter = new_l
                        changes.append(f"  template {t.id} stage {st.stage_order} '{sp.step_name}': "
                                       f"{old_l} {old_d} -> {new_l} {new_d}")
            if changes:
                changed_any += 1
                t.version = (t.version or 1) + 1
                t.updated_at = datetime.utcnow()
                await s.flush()
                s.add(WfTemplateHistory(template_id=t.id, version=t.version,
                                        snapshot=snapshot(t, names), changed_by=actor.id,
                                        change_note=NOTE))
                print("\n".join(changes) + f"\n  template {t.id}: version -> {t.version}, history row")
            else:
                print(f"  template {t.id}: nothing to change (already fixed)")
        retired = [d.id for d in depts.values() if not d.is_active]
        open_rows = (await s.execute(
            select(WfInstanceTask.id, WfInstanceTask.department_id)
            .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
            .where(WfInstance.status == "active", WfInstanceTask.status == "active",
                   WfInstanceTask.department_id.in_(retired)))).all()
        print(f"open tasks of retired departments in running instances: {len(open_rows)}"
              + (" " + str([(i, names.get(d)) for i, d in open_rows]) if open_rows else ""))
        if apply and changed_any:
            await s.commit()
            print(f"APPLIED: {changed_any} template(s)")
        else:
            await s.rollback()
            print("DRY RUN: nothing written" if not apply else "nothing to apply")
    await engine.dispose()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--actor", default="christoph.demmler", help="username recorded in the history")
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args.apply, args.actor)))


if __name__ == "__main__":
    main()
