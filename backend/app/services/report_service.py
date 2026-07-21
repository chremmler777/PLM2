"""Live SQL aggregates for the reports/analytics surface: pipeline funnel +
throughput + cycle time, department/owner workload, and cost roll-ups.

All three entry points are org-scoped through Task 13's `_org_scope` (which
now also bypasses scoping entirely for admin viewers - see change_service.py)
and are designed to return zero-filled, division-by-zero-safe shapes even
against an empty database.
"""
import json
from collections import defaultdict
from datetime import datetime
from statistics import mean
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import (
    ChangeAssessment, ChangeRequest, CHANGE_STATUSES, TERMINAL_STATUSES,
)
from app.models.change_cost import AssessmentCostLine
from app.models.entities import AuditLog, Plant, Project, User
from app.services.change_service import ChangeService, _org_scope

TRANSITION_ACTIONS = ("status_changed", "deviated_transition")


class ReportService:

    @staticmethod
    async def pipeline(session: AsyncSession, viewer: Optional[User]) -> dict:
        # --- funnel: count of changes per status, zero-filled ---
        counts = dict.fromkeys(CHANGE_STATUSES, 0)
        rows = (await session.execute(_org_scope(
            select(ChangeRequest.status, func.count()).group_by(ChangeRequest.status),
            viewer,
        ))).all()
        for status, cnt in rows:
            counts[status] = cnt
        funnel = [{"status": s, "count": counts[s]} for s in CHANGE_STATUSES]

        # --- throughput: released changes per month, last 12 months ---
        released_dates = (await session.execute(_org_scope(
            select(ChangeRequest.released_at).where(ChangeRequest.released_at.is_not(None)),
            viewer,
        ))).scalars().all()
        by_month: dict[str, int] = defaultdict(int)
        for d in released_dates:
            by_month[f"{d.year:04d}-{d.month:02d}"] += 1

        now = datetime.utcnow()
        months = []
        y, m = now.year, now.month
        for i in range(11, -1, -1):
            mm = m - i
            yy = y
            while mm <= 0:
                mm += 12
                yy -= 1
            months.append(f"{yy:04d}-{mm:02d}")
        throughput = [{"month": mk, "released": by_month.get(mk, 0)} for mk in months]

        # --- avg_stage_days: consecutive status_changed/deviated_transition
        # AuditLog rows per change. Each row's own (old_value, new_value) is
        # the pair label; the duration attributed to that pair is the time
        # until the *next* transition on the same change (i.e. how long the
        # change stayed in `new_value` before moving on). A change's most
        # recent transition contributes no duration (still in that stage). ---
        numbers = (await session.execute(_org_scope(
            select(ChangeRequest.change_number), viewer))).scalars().all()
        pair_deltas: dict[tuple, list[float]] = defaultdict(list)
        if numbers:
            audit_rows = (await session.execute(
                select(AuditLog)
                .where(AuditLog.correlation_id.in_(numbers),
                       AuditLog.action.in_(TRANSITION_ACTIONS))
                .order_by(AuditLog.correlation_id, AuditLog.timestamp)
            )).scalars().all()
            by_change: dict[str, list[AuditLog]] = defaultdict(list)
            for row in audit_rows:
                by_change[row.correlation_id].append(row)
            for entries in by_change.values():
                for i in range(len(entries) - 1):
                    cur, nxt = entries[i], entries[i + 1]
                    old_v = json.loads(cur.old_values) if cur.old_values else None
                    new_v = json.loads(cur.new_values) if cur.new_values else None
                    delta_days = (nxt.timestamp - cur.timestamp).total_seconds() / 86400.0
                    pair_deltas[(old_v, new_v)].append(delta_days)
        avg_stage_days = [
            {"from_status": frm, "to_status": to, "avg_days": mean(deltas)}
            for (frm, to), deltas in pair_deltas.items()
        ]

        # --- on_time_rate: released/closed changes with a required_by_date ---
        eligible = (await session.execute(_org_scope(
            select(ChangeRequest).where(
                ChangeRequest.required_by_date.is_not(None),
                ChangeRequest.status.in_(("released", "closed")),
            ), viewer,
        ))).scalars().all()
        on_time_rate = None
        if eligible:
            on_time = 0
            for c in eligible:
                completed = c.released_at or c.closed_at
                if completed is not None and completed <= c.required_by_date:
                    on_time += 1
            on_time_rate = on_time / len(eligible)

        return {
            "funnel": funnel,
            "throughput": throughput,
            "avg_stage_days": avg_stage_days,
            "on_time_rate": on_time_rate,
        }

    @staticmethod
    async def workload(session: AsyncSession, viewer: Optional[User]) -> dict:
        from app.models.part import PartRevision
        from app.models.workflow import Department, WfInstance, WfInstanceTask

        now = datetime.utcnow()

        change_ids = set((await session.execute(_org_scope(
            select(ChangeRequest.id), viewer))).scalars().all())

        dept_agg: dict[int, dict] = {}
        owner_agg: dict[int, dict] = {}
        escalation_count = 0

        if change_ids:
            # Task-based counts are the workload source of truth: every
            # engine-managed piece of work now runs through WfInstanceTask,
            # via either a change-scoped instance (WfInstance.change_id) or a
            # part-revision instance spawned off the change's ECN revisions
            # (PartRevision.originating_change_id). Legacy ChangeAssessment
            # rows with no linked wf_instance_task_id are pre-engine data and
            # are deliberately excluded here rather than double-counted.
            rows_by_change = (await session.execute(
                select(WfInstanceTask, Department.name)
                .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
                .join(Department, Department.id == WfInstanceTask.department_id)
                .where(WfInstance.change_id.in_(change_ids),
                       WfInstance.status == "active",
                       WfInstanceTask.status == "active")
            )).all()
            rows_by_revision = (await session.execute(
                select(WfInstanceTask, Department.name)
                .join(WfInstance, WfInstance.id == WfInstanceTask.instance_id)
                .join(PartRevision, PartRevision.id == WfInstance.part_revision_id)
                .join(Department, Department.id == WfInstanceTask.department_id)
                .where(PartRevision.originating_change_id.in_(change_ids),
                       WfInstance.status == "active",
                       WfInstanceTask.status == "active")
            )).all()

            seen_task_ids: set[int] = set()
            for task, dept_name in (*rows_by_change, *rows_by_revision):
                if task.id in seen_task_ids:
                    continue
                seen_task_ids.add(task.id)
                overdue = task.due_date is not None and task.due_date < now

                d = dept_agg.setdefault(task.department_id, {
                    "department_id": task.department_id, "name": dept_name,
                    "open": 0, "overdue": 0,
                })
                d["open"] += 1
                if overdue:
                    d["overdue"] += 1
                    escalation_count += 1

                if task.owner_id is not None:
                    o = owner_agg.setdefault(task.owner_id, {
                        "owner_id": task.owner_id, "owner_name": task.owner_name,
                        "open": 0, "overdue": 0,
                    })
                    o["open"] += 1
                    if overdue:
                        o["overdue"] += 1

        # --- at-risk changes: Sales-set required_by_date at risk/overdue ---
        candidates = (await session.execute(_org_scope(
            select(ChangeRequest).where(
                ChangeRequest.status.not_in(TERMINAL_STATUSES),
                ChangeRequest.required_by_date.is_not(None),
            ), viewer,
        ))).scalars().all()
        at_risk_changes = []
        for c in candidates:
            state = await ChangeService.deadline_state(session, c)
            if state in ("at_risk", "overdue"):
                at_risk_changes.append({
                    "id": c.id, "change_number": c.change_number, "title": c.title,
                    "required_by_date": c.required_by_date.isoformat(),
                    "deadline_state": state,
                })

        return {
            "departments": list(dept_agg.values()),
            "owners": list(owner_agg.values()),
            "at_risk_changes": at_risk_changes,
            "escalation_count": escalation_count,
        }

    @staticmethod
    async def cost(session: AsyncSession, viewer: Optional[User]) -> dict:
        cost_expr = AssessmentCostLine.internal_cost + AssessmentCostLine.external_cost

        budget_rows = (await session.execute(_org_scope(
            select(ChangeRequest.project_id, func.sum(ChangeRequest.estimated_cost))
            .group_by(ChangeRequest.project_id), viewer,
        ))).all()

        actual_rows = (await session.execute(_org_scope(
            select(ChangeRequest.project_id, func.sum(cost_expr))
            .select_from(AssessmentCostLine)
            .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
            .group_by(ChangeRequest.project_id), viewer,
        ))).all()

        project_ids = {pid for pid, _ in (*budget_rows, *actual_rows) if pid is not None}
        names: dict[int, str] = {}
        if project_ids:
            names = dict((await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )).all())

        merged: dict[int, dict] = {}
        for pid, budget in budget_rows:
            if pid is None:
                continue
            merged.setdefault(pid, {"project_id": pid, "name": names.get(pid, ""),
                                     "budget": 0.0, "actual": 0.0})
            merged[pid]["budget"] = budget or 0.0
        for pid, actual in actual_rows:
            if pid is None:
                continue
            merged.setdefault(pid, {"project_id": pid, "name": names.get(pid, ""),
                                     "budget": 0.0, "actual": 0.0})
            merged[pid]["actual"] = actual or 0.0
        projects = list(merged.values())

        plant_rows = (await session.execute(_org_scope(
            select(AssessmentCostLine.plant_id, Plant.name, func.sum(cost_expr))
            .select_from(AssessmentCostLine)
            .join(ChangeAssessment, ChangeAssessment.id == AssessmentCostLine.assessment_id)
            .join(ChangeRequest, ChangeRequest.id == ChangeAssessment.change_id)
            .join(Plant, Plant.id == AssessmentCostLine.plant_id)
            .group_by(AssessmentCostLine.plant_id, Plant.name), viewer,
        ))).all()
        plants = [{"plant_id": pid, "name": name, "actual": actual or 0.0}
                  for pid, name, actual in plant_rows]

        return {"projects": projects, "plants": plants}
